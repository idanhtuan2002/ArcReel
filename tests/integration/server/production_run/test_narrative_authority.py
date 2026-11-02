"""Automatic owner authority uses activated grants; this is not launch/creative qualification."""

import pytest
import sqlalchemy as sa

from lib.db.models.automation_grant import AutomationDecisionModel
from lib.db.models.narrative_lifecycle import RevisionAcceptanceDecisionModel
from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from lib.db.repositories.production_runs import ProductionRunRepository
from r2.contracts.automation import RunStage
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from server.story_authoring.narrative import StoryIdentity, acceptance_command
from tests.integration.lib.db.repositories.test_production_runs import intent_for
from tests.integration.server.services.test_automation_grants import delegated_host as delegated_host
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env
from tests.integration.server.services.test_automation_grants import subject_for
from tests.integration.server.story_authoring import test_commit as commit_fixtures


@pytest.fixture
async def manuscript_bound_run(delegated_host, monkeypatch):
    issuer, sessions, _, grant, run, *_ = delegated_host
    identity = StoryIdentity(user_id=run.user_id, project_name=run.project_name, run_id="story-run-1")
    monkeypatch.setattr(commit_fixtures, "IDENTITY", identity)
    manifest = await commit_fixtures._manifest()
    async with sessions() as session, session.begin():
        repo = ProductionRunRepository(session)
        await repo.transition(
            expected=run,
            updated=run.model_copy(update={"stage": RunStage.STORY_COMMIT, "version": run.version + 1}),
            fencing_epoch=run.fencing_epoch,
        )
    async with sessions() as session, session.begin():
        repo = ProductionRunRepository(session)
        current = await repo.claim_due(owner_id="commit-worker", lease_seconds=30)
        await repo.stage_intent(run=current, intent=intent_for(current))
    subject = subject_for(current, grant).model_copy(update={"subject_digest": manifest.digest()})
    return issuer, sessions, grant, current, manifest, subject, identity


async def test_manifest_projection_uses_actual_actor_and_exact_owner_member(manuscript_bound_run):
    from r2.automation.authorization import parse_automation_authorization_reference
    from r2.contracts.narrative_lifecycle import NarrativeAutomationDecisionAuthorizationV1
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, grant, run, manifest, subject, _ = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    entry = manifest.scenes[0]
    command = acceptance_command(entry.revision, decision_id=entry.decision_id, actor_id=grant.principal)
    projection = await adapter.authorize_initial_decision(grant.principal, command)
    assert type(projection) is NarrativeAutomationDecisionAuthorizationV1
    assert projection.actor_id == grant.principal
    assert projection.authority_role == "RUN_AUTOMATION"
    assert parse_automation_authorization_reference(projection.authenticated_via) == (
        run.run_id,
        subject.command_id,
        grant.grant_id,
        grant.version,
    )
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(AutomationDecisionModel)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(RevisionAcceptanceDecisionModel)) == 0


@pytest.mark.parametrize("field", ["exceptions_offered", "findings_open"])
async def test_story_findings_without_their_quality_record_cannot_be_accepted(manuscript_bound_run, field):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, _, _, manifest, subject, _ = manuscript_bound_run
    manifest = manifest.model_copy(update={field: ("unresolved",)})
    subject = subject.model_copy(update={"subject_digest": manifest.digest()})
    with pytest.raises(NarrativeDecisionAuthorizationError, match="UNRESOLVED_STORY_FINDINGS"):
        await AutomaticNarrativeAuthority.bind(
            sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
        )
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(AutomationDecisionModel)) == 0


def _quality(severity: str) -> tuple[bytes, str]:
    import hashlib
    import json

    record = json.dumps({"findings": [{"id": "F001", "severity": severity}], "packaging": None}).encode()
    return record, "sha256:" + hashlib.sha256(record).hexdigest()


@pytest.mark.parametrize("severity", ["STYLISTIC", "NARRATIVE_CRITICAL", "LOCAL_MODEL_LIMIT"])
async def test_recorded_story_findings_are_accepted_as_is_only_with_their_exact_record(manuscript_bound_run, severity):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, _, _, manifest, subject, _ = manuscript_bound_run
    accepted, accepted_digest = _quality(severity)
    hard, hard_digest = _quality("HARD_INTEGRITY")
    exceptions = ("F001",) if severity != "STYLISTIC" else ()

    def bound(digest: str, offered: tuple[str, ...] = exceptions, open_: tuple[str, ...] = ("F001",)):
        changed = manifest.model_copy(
            update={"findings_open": open_, "exceptions_offered": offered, "quality_record_digest": digest}
        )
        return changed, subject.model_copy(update={"subject_digest": changed.digest()})

    refused = (
        (accepted, hard_digest, exceptions, ("F001",)),
        (None, accepted_digest, exceptions, ("F001",)),
        (hard, hard_digest, exceptions, ("F001",)),
        (accepted, accepted_digest, ("F002",), ("F001",)),
    )
    for record, digest, offered, open_ in refused:
        refused_manifest, refused_subject = bound(digest, offered, open_)
        with pytest.raises(NarrativeDecisionAuthorizationError, match="UNRESOLVED_STORY_FINDINGS"):
            await AutomaticNarrativeAuthority.bind(
                sessions=sessions,
                authority=issuer.authority(),
                subject=refused_subject,
                manifest=refused_manifest,
                quality_record=record,
            )
    accepted_manifest, accepted_subject = bound(accepted_digest)
    narrative = await AutomaticNarrativeAuthority.bind(
        sessions=sessions,
        authority=issuer.authority(),
        subject=accepted_subject,
        manifest=accepted_manifest,
        quality_record=accepted,
    )
    assert narrative.actor_id.startswith("automation:")


async def test_manifest_subject_digest_cannot_be_substituted(manuscript_bound_run):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, _, _, manifest, subject, _ = manuscript_bound_run
    with pytest.raises(NarrativeDecisionAuthorizationError, match="MANIFEST_BINDING_MISMATCH"):
        await AutomaticNarrativeAuthority.bind(
            sessions=sessions,
            authority=issuer.authority(),
            subject=subject.model_copy(update={"subject_digest": "sha256:" + "f" * 64}),
            manifest=manifest,
        )


@pytest.mark.parametrize("change", ["actor", "revision", "decision"])
async def test_projection_refuses_another_actor_or_owner_command(manuscript_bound_run, change):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, grant, _, manifest, subject, _ = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    entry = manifest.scenes[0]
    command = acceptance_command(entry.revision, decision_id=entry.decision_id, actor_id=grant.principal)
    updates = {
        "actor": {"actor_id": "actor"},
        "revision": {"selected_revision_id": "other"},
        "decision": {"decision_id": "other"},
    }
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await adapter.authorize_initial_decision(grant.principal, command.model_copy(update=updates[change]))


async def test_default_owner_uow_cannot_replace_adapter_bound_transaction(manuscript_bound_run):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, grant, _, manifest, subject, _ = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    entry = manifest.scenes[0]
    command = acceptance_command(entry.revision, decision_id=entry.decision_id, actor_id=grant.principal)
    async with narrative_lifecycle_uow_factory(sessions)() as uow:
        with pytest.raises(NarrativeDecisionAuthorizationError, match="OWNING_TRANSACTION_REQUIRED"):
            await adapter.require_current_in_owner(uow, command)


async def test_unbound_constructor_cannot_replace_validated_manifest_binding(manuscript_bound_run):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, _, _, manifest, subject, _ = manuscript_bound_run
    authority = issuer.authority()
    async with sessions() as session, session.begin():
        proof = await authority.require_locked(session, subject=subject)
    with pytest.raises(NarrativeDecisionAuthorizationError, match="VALIDATED_MANIFEST_BINDING_REQUIRED"):
        AutomaticNarrativeAuthority(
            sessions=sessions, authority=authority, subject=subject, manifest=manifest, proof=proof
        )


async def test_real_canon_and_plan_owners_keep_automatic_actor_and_replay(manuscript_bound_run):
    from lib.db.models.canon import CanonVersionModel
    from lib.db.models.narrative_plan import NarrativePlanVersionModel
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, grant, _, manifest, subject, _ = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    canon = await adapter.commit_canon()
    plan = await adapter.commit_plan()
    assert canon.version.canon_version_id == manifest.canon_version_id
    assert canon.accepted_delta.approval.approved_by == grant.principal
    assert canon.accepted_delta.approval.approval_ref.startswith("automation:v1:")
    assert plan.plan.committed_by == grant.principal
    assert plan.plan.approval_ref.startswith("automation:v1:")
    assert await adapter.commit_canon() == canon
    assert await adapter.commit_plan() == plan
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(CanonVersionModel)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(NarrativePlanVersionModel)) == 1


async def test_manifest_owner_run_id_cannot_be_swapped(manuscript_bound_run):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, _, _, manifest, subject, _ = manuscript_bound_run
    manifest = manifest.model_copy(update={"run_id": "different-story-run"})
    subject = subject.model_copy(update={"subject_digest": manifest.digest()})
    with pytest.raises(NarrativeDecisionAuthorizationError, match="MANIFEST_BINDING_MISMATCH"):
        await AutomaticNarrativeAuthority.bind(
            sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
        )


async def test_scene_acceptance_uses_committed_context_and_separate_automatic_role(manuscript_bound_run):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority
    from tests.integration.server.story_authoring.test_narrative import BIBLE

    issuer, sessions, grant, _, manifest, subject, _ = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    await adapter.commit_canon()
    await adapter.commit_plan()
    receipts = []
    for entry in manifest.scenes:
        receipt = await adapter.accept_scene(entry.decision_id, bible=BIBLE)
        receipts.append(receipt)
        async with sessions() as session:
            stored = await session.get(RevisionAcceptanceDecisionModel, entry.decision_id)
            assert stored is not None
            assert stored.authorization_authority_role == "RUN_AUTOMATION"
            assert stored.authorization_actor_id == grant.principal
        assert await adapter.accept_scene(entry.decision_id, bible=BIBLE) == receipt
    assert len(receipts) == len(manifest.scenes)
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(RevisionAcceptanceDecisionModel)) == len(
            manifest.scenes
        )


@pytest.mark.parametrize("step", ["canon", "plan", "replay"])
async def test_revoked_prepared_authority_cannot_commit_or_replay(manuscript_bound_run, step):
    from lib.db.models.canon import CanonVersionModel
    from lib.db.models.narrative_plan import NarrativePlanVersionModel
    from server.auth import create_token
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, grant, run, manifest, subject, _ = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    if step != "canon":
        await adapter.commit_canon()
    if step == "replay":
        await adapter.commit_plan()
    await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)
    operation = adapter.commit_canon if step == "canon" else adapter.commit_plan
    with pytest.raises(NarrativeDecisionAuthorizationError, match="AUTOMATION_AUTHORITY_NOT_CURRENT"):
        await operation()
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(CanonVersionModel)) == (
            0 if step == "canon" else 1
        )
        assert await session.scalar(sa.select(sa.func.count()).select_from(NarrativePlanVersionModel)) == (
            1 if step == "replay" else 0
        )


async def test_revocation_after_plan_head_write_rolls_back_entire_owner_transaction(manuscript_bound_run, monkeypatch):
    from lib.db.models.narrative_plan import NarrativePlanModel, NarrativePlanVersionModel
    from lib.db.repositories.narrative_plan import NarrativePlanRepository
    from server.auth import create_token
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, grant, run, manifest, subject, _ = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    await adapter.commit_canon()
    original = NarrativePlanRepository.advance_head

    async def revoke_after_write(repo, **kwargs):
        result = await original(repo, **kwargs)
        await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)
        return result

    monkeypatch.setattr(NarrativePlanRepository, "advance_head", revoke_after_write)
    with pytest.raises(NarrativeDecisionAuthorizationError, match="AUTOMATION_AUTHORITY_NOT_CURRENT"):
        await adapter.commit_plan()
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(NarrativePlanVersionModel)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(NarrativePlanModel)) == 0


async def test_plan_basis_cannot_name_another_canon_version(manuscript_bound_run):
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority

    issuer, sessions, _, _, manifest, subject, _ = manuscript_bound_run
    basis = manifest.plan.proposed_content.canon_basis.model_copy(update={"canon_version_id": "different-version"})
    content = manifest.plan.proposed_content.model_copy(update={"canon_basis": basis})
    manifest = manifest.model_copy(update={"plan": manifest.plan.model_copy(update={"proposed_content": content})})
    subject = subject.model_copy(update={"subject_digest": manifest.digest()})
    with pytest.raises(NarrativeDecisionAuthorizationError, match="MANIFEST_BINDING_MISMATCH"):
        await AutomaticNarrativeAuthority.bind(
            sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
        )


async def test_newer_real_plan_revision_blocks_stale_replay_and_scene_evidence(manuscript_bound_run):
    from lib.db.models.narrative_lifecycle import NarrativeDraftCandidateModel
    from lib.db.narrative_plan_uow import narrative_plan_uow_factory
    from r2.contracts import NarrativePlanApproval
    from r2.narrative_plan.hashing import compute_plan_content_hash_dispatch
    from r2.narrative_plan.service import NarrativePlanService
    from server.production_run.narrative_authority import AutomaticNarrativeAuthority
    from server.story_authoring.narrative import committed_canon_reader
    from tests.integration.server.story_authoring.test_narrative import BIBLE

    issuer, sessions, _, _, manifest, subject, identity = manuscript_bound_run
    adapter = await AutomaticNarrativeAuthority.bind(
        sessions=sessions, authority=issuer.authority(), subject=subject, manifest=manifest
    )
    await adapter.commit_canon()
    await adapter.commit_plan()
    content = manifest.plan.proposed_content.model_copy(
        update={"parent_version": 1, "story_frame": "A changed narrative frame."}
    )
    successor = manifest.plan.model_copy(
        update={
            "expected_version": 1,
            "plan_revision_id": "successor-plan",
            "proposed_content": content,
            "content_hash": compute_plan_content_hash_dispatch(content),
        }
    )
    await NarrativePlanService(narrative_plan_uow_factory(sessions), committed_canon_reader(sessions)).commit_revision(
        proposal=successor,
        approval=NarrativePlanApproval(
            approval_ref="human-successor",
            plan_revision_id=successor.plan_revision_id,
            plan_id=successor.plan_id,
            expected_version=1,
            content_hash=successor.content_hash,
            user_id=identity.user_id,
            project_name=identity.project_name,
            approved_by="human-operator",
            approved_at=commit_fixtures.NOW,
        ),
        user_id=identity.user_id,
        project_name=identity.project_name,
        now=commit_fixtures.NOW,
    )
    with pytest.raises(NarrativeDecisionAuthorizationError, match="PLAN_BASIS_MOVED"):
        await adapter.commit_plan()
    with pytest.raises(NarrativeDecisionAuthorizationError, match="PLAN_BASIS_MOVED"):
        await adapter.accept_scene(manifest.scenes[0].decision_id, bible=BIBLE)
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(NarrativeDraftCandidateModel)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(RevisionAcceptanceDecisionModel)) == 0
