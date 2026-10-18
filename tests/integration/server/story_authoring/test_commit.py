"""Touchpoint-2 commit protocol on the real R2 owners with a real signed Showrunner grant.

Runs on PostgreSQL when DATABASE_URL points at one (per-test schema), otherwise on a WAL SQLite file.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.canon import CanonBranchModel, CanonVersionModel
from lib.db.models.narrative_lifecycle import RevisionAcceptanceDecisionModel
from lib.db.models.narrative_plan import NarrativePlanVersionModel
from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
from r2.contracts import NarrativePlanApproval
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from r2.narrative_plan.service import NarrativePlanService
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.commit import (
    STEP_CANON,
    STEP_PLAN,
    CommitRefusal,
    CommitRefused,
    ManuscriptCommitManifest,
    ManuscriptCommitter,
    provisional_acceptances,
    scene_entry,
)
from server.story_authoring.contracts import StoryLimits
from server.story_authoring.narrative import (
    StoryOutlineInput,
    acceptance_command,
    build_genesis_delta,
    build_plan_proposal,
    committed_readers,
    compile_scene_context,
    genesis_canon_version_id,
    provisional_canon_view,
    provisional_plan,
    provisional_readers,
    scene_contract,
    scene_refs,
)
from server.story_authoring.runtime import RunPhase, RunStateStore, new_run_state
from tests.integration.server.routers.spatial_approval_support import showrunner_grants
from tests.integration.server.story_authoring.test_narrative import BIBLE, IDENTITY, NOW, OUTLINE, PROSE

type Factory = async_sessionmaker[AsyncSession]

SPONSOR = "sponsor"
SCENES = scene_refs(OUTLINE)


async def _manifest(
    *,
    prose: tuple[str, ...] = PROSE,
    tamper: int | None = None,
    predecessor: str | None = None,
    prefix: tuple[str, ...] = (),
    exceptions: tuple[str, ...] = (),
) -> ManuscriptCommitManifest:
    delta = build_genesis_delta(IDENTITY, BIBLE, created_by="run1", created_at=NOW)
    canon_version = genesis_canon_version_id(delta)
    proposal = build_plan_proposal(IDENTITY, OUTLINE, canon_version_id=canon_version, created_by="run1", created_at=NOW)
    plan = provisional_plan(proposal, approval_ref="provisional", committed_by="provisional", committed_at=NOW)
    entries = []
    for scene, text in zip(SCENES, prose, strict=True):
        readers = provisional_readers(
            IDENTITY,
            BIBLE,
            canon_view=provisional_canon_view(delta),
            plan=plan,
            acceptances=provisional_acceptances(entries),
        )
        contract = scene_contract(proposal, scene)
        pack = await compile_scene_context(
            readers,
            IDENTITY,
            scene,
            contract=contract,
            canon_version_id=canon_version,
            plan_version=1,
            recent_decision_ids=[entry.decision_id for entry in entries],
        )
        entry = scene_entry(
            IDENTITY,
            scene,
            pack=pack,
            canon_version_id=canon_version,
            scene_contract_version=contract.version,
            prose=text,
            model="ornith-32k:9b",
            writer_version="w1",
            created_by="run1",
            created_at=NOW,
        )
        if tamper == scene.global_index:
            entry = entry.model_copy(update={"context_pack_id": "ncp:tampered"})
        entries.append(entry)
    return ManuscriptCommitManifest(
        run_id=IDENTITY.run_id,
        brief_digest="sha256:" + "b" * 64,
        gate_a_decision_id="gate-a-1",
        predecessor_manifest_digest=predecessor,
        committed_prefix=prefix,
        canon_genesis=delta,
        canon_version_id=canon_version,
        plan=proposal,
        scenes=tuple(entries),
        exceptions_offered=exceptions,
        export_digest="sha256:" + "e" * 64,
    )


async def _store(factory: Factory) -> RunStateStore:
    async with factory() as session:
        task = await TaskRepository(session).enqueue(
            project_name=IDENTITY.project_name, task_type=STORY_RUN_TASK_TYPE, media_type="text", resource_id="run1"
        )
    store = RunStateStore(factory, task_id=task["task_id"])
    limits = StoryLimits(input_tokens_max=10**6, output_tokens_max=10**6, wall_clock_max_seconds=10**5)
    await store.initialize(new_run_state(run_id=IDENTITY.run_id, limits=limits, now=NOW))
    return store


@pytest.fixture
async def grants(concurrent_session_factory: Factory) -> CurrentShowrunnerGrantReader:
    """One signed grant import per test: a second import in another second would be a different event."""
    return await showrunner_grants(
        concurrent_session_factory, user_id=IDENTITY.user_id, project_name=IDENTITY.project_name, principal=SPONSOR
    )


def _committer(
    factory: Factory,
    store: RunStateStore,
    blobs: Path,
    grants: CurrentShowrunnerGrantReader,
    *,
    cls: type[ManuscriptCommitter] = ManuscriptCommitter,
    **kwargs: object,
) -> ManuscriptCommitter:
    return cls(
        identity=IDENTITY,
        bible=BIBLE,
        store=store,
        blobs=StoryBlobStore(blobs),
        session_factory=factory,
        authority=GrantNarrativeShowrunnerAuthority(factory, grants),
        **kwargs,
    )


async def _count(factory: Factory, model) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_one_approval_records_genesis_plan_and_every_scene(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    store = await _store(factory)
    committer = _committer(factory, store, tmp_path, grants)
    manifest = await _manifest()
    digest = await committer.offer(manifest)

    state = await committer.approve(principal=SPONSOR, manifest_digest_seen=digest, accepted_exceptions=())

    assert state.phase is RunPhase.COMMITTED, state.block_reason
    assert state.commit is not None
    assert state.commit.completed_steps == manifest.steps()
    assert state.commit.approval is not None
    assert state.commit.approval.actor_id == SPONSOR
    assert await _count(factory, CanonVersionModel) == 1
    assert await _count(factory, NarrativePlanVersionModel) == 1
    assert await _count(factory, RevisionAcceptanceDecisionModel) == len(SCENES)
    async with factory() as session:
        decision = (
            await session.execute(
                select(RevisionAcceptanceDecisionModel).where(
                    RevisionAcceptanceDecisionModel.decision_id == manifest.scenes[-1].decision_id
                )
            )
        ).scalar_one()
    assert decision.actor_id == SPONSOR


async def test_a_principal_without_a_grant_changes_nothing(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    store = await _store(factory)
    committer = _committer(factory, store, tmp_path, grants)
    digest = await committer.offer(await _manifest())

    with pytest.raises(NarrativeDecisionAuthorizationError):
        await committer.approve(principal="intruder", manifest_digest_seen=digest, accepted_exceptions=())

    assert (await store.load()).phase is RunPhase.READY_FOR_APPROVAL
    assert await _count(factory, CanonBranchModel) == 0


async def test_an_ungranted_deployment_denies_every_story_decision(concurrent_session_factory: Factory):
    factory = concurrent_session_factory
    authority = GrantNarrativeShowrunnerAuthority(factory, None)
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await authority.require_showrunner(SPONSOR, user_id=IDENTITY.user_id, project_name=IDENTITY.project_name)


async def test_a_stale_or_unticked_approval_is_refused(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    store = await _store(factory)
    committer = _committer(factory, store, tmp_path, grants)
    digest = await committer.offer(await _manifest(exceptions=("finding-critical-1",)))

    with pytest.raises(CommitRefused) as stale:
        await committer.approve(principal=SPONSOR, manifest_digest_seen="sha256:" + "0" * 64, accepted_exceptions=())
    with pytest.raises(CommitRefused) as unticked:
        await committer.approve(principal=SPONSOR, manifest_digest_seen=digest, accepted_exceptions=())

    assert stale.value.code is CommitRefusal.STALE_MANIFEST
    assert unticked.value.code is CommitRefusal.EXCEPTIONS_NOT_ACCEPTED
    state = await committer.approve(
        principal=SPONSOR, manifest_digest_seen=digest, accepted_exceptions=("finding-critical-1",)
    )
    assert state.phase is RunPhase.COMMITTED
    assert state.commit is not None
    assert state.commit.approval is not None
    assert state.commit.approval.accepted_exceptions == ("finding-critical-1",)


async def test_two_concurrent_approvals_run_one_sequence(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    store = await _store(factory)
    first = _committer(factory, store, tmp_path, grants)
    second = _committer(factory, RunStateStore(factory, task_id=store.task_id), tmp_path, grants)
    digest = await first.offer(await _manifest())

    outcomes = await asyncio.gather(
        first.approve(principal=SPONSOR, manifest_digest_seen=digest, accepted_exceptions=()),
        second.approve(principal=SPONSOR, manifest_digest_seen=digest, accepted_exceptions=()),
        return_exceptions=True,
    )

    refused = [o for o in outcomes if isinstance(o, CommitRefused)]
    assert len(refused) == 1
    assert refused[0].code in {CommitRefusal.ALREADY_APPROVING, CommitRefusal.NOT_READY}
    assert (await store.load()).phase is RunPhase.COMMITTED
    assert await _count(factory, RevisionAcceptanceDecisionModel) == len(SCENES)


class _Crash(Exception):
    pass


class _CrashAfter(ManuscriptCommitter):
    """Dies after a step reached the owner and before the run recorded it."""

    def __init__(self, *args, crash_after: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._crash_after = crash_after

    async def _run_step(self, step, manifest, approval, digest) -> None:
        await super()._run_step(step, manifest, approval, digest)
        if step == self._crash_after:
            raise _Crash(step)


@pytest.mark.parametrize("crash_after", [STEP_CANON, STEP_PLAN, SCENES[0].node_id, SCENES[-1].node_id])
async def test_a_crash_after_any_step_resumes_without_duplicates(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader, crash_after: str
):
    factory = concurrent_session_factory
    store = await _store(factory)
    crashing = _committer(factory, store, tmp_path, grants, cls=_CrashAfter, crash_after=crash_after)
    digest = await crashing.offer(await _manifest())
    with pytest.raises(_Crash):
        await crashing.approve(principal=SPONSOR, manifest_digest_seen=digest, accepted_exceptions=())
    interrupted = await store.load()
    assert interrupted.phase in {RunPhase.APPROVING, RunPhase.PARTIALLY_COMMITTED}

    restarted = _committer(factory, RunStateStore(factory, task_id=store.task_id), tmp_path, grants)
    with pytest.raises(CommitRefused) as stranger:
        await restarted.resume(principal="someone-else")
    state = await restarted.resume(principal=SPONSOR)

    assert stranger.value.code is CommitRefusal.NOT_THE_APPROVER
    assert state.phase is RunPhase.COMMITTED, state.block_reason
    assert await _count(factory, CanonVersionModel) == 1
    assert await _count(factory, NarrativePlanVersionModel) == 1
    assert await _count(factory, RevisionAcceptanceDecisionModel) == len(SCENES)


async def test_a_concurrent_plan_change_blocks_before_any_scene(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    store = await _store(factory)
    committer = _committer(factory, store, tmp_path, grants)
    manifest = await _manifest()
    digest = await committer.offer(manifest)
    # Someone else commits version 1 of the same plan id with other content after the binding proof.
    other = build_plan_proposal(
        IDENTITY,
        StoryOutlineInput.model_validate({**OUTLINE.model_dump(), "story_frame": "Khung khác."}),
        canon_version_id=manifest.canon_version_id,
        created_by="other",
        created_at=NOW,
    ).model_copy(update={"plan_revision_id": "foreign-revision"})
    crashing = _committer(factory, store, tmp_path, grants, cls=_CrashAfter, crash_after=STEP_CANON)
    with pytest.raises(_Crash):
        await crashing.approve(principal=SPONSOR, manifest_digest_seen=digest, accepted_exceptions=())
    readers = committed_readers(IDENTITY, BIBLE, session_factory=factory)
    await NarrativePlanService(narrative_plan_uow_factory(factory), readers.canon_reader).commit_revision(
        proposal=other,
        approval=NarrativePlanApproval(
            approval_ref="foreign-approval",
            plan_revision_id=other.plan_revision_id,
            plan_id=other.plan_id,
            expected_version=None,
            content_hash=other.content_hash,
            project_name=IDENTITY.project_name,
            user_id=IDENTITY.user_id,
            approved_by="someone",
            approved_at=NOW,
        ),
        project_name=IDENTITY.project_name,
        user_id=IDENTITY.user_id,
        now=NOW,
    )

    state = await committer.resume(principal=SPONSOR)

    assert state.phase is RunPhase.COMMIT_BLOCKED
    assert state.commit is not None
    assert state.commit.blocked_step == STEP_PLAN
    assert state.commit.completed_steps == (STEP_CANON,)
    assert await _count(factory, RevisionAcceptanceDecisionModel) == 0


async def test_a_successor_with_an_unchanged_prefix_completes_a_blocked_run(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    store = await _store(factory)
    committer = _committer(factory, store, tmp_path, grants)
    first = await _manifest(tamper=2)
    blocked = await committer.approve(
        principal=SPONSOR, manifest_digest_seen=await committer.offer(first), accepted_exceptions=()
    )
    assert blocked.phase is RunPhase.COMMIT_BLOCKED
    assert blocked.commit is not None
    prefix = blocked.commit.completed_steps
    assert prefix == (STEP_CANON, STEP_PLAN, SCENES[0].node_id, SCENES[1].node_id)

    successor = await _manifest(predecessor=first.digest(), prefix=prefix)
    state = await committer.approve(
        principal=SPONSOR, manifest_digest_seen=await committer.offer(successor), accepted_exceptions=()
    )

    assert state.phase is RunPhase.COMMITTED, state.block_reason
    assert await _count(factory, RevisionAcceptanceDecisionModel) == len(SCENES)


async def test_a_successor_that_changes_a_committed_scene_is_refused_and_the_run_can_be_aborted(
    concurrent_session_factory: Factory, tmp_path: Path, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    store = await _store(factory)
    committer = _committer(factory, store, tmp_path, grants)
    first = await _manifest(tamper=2)
    blocked = await committer.approve(
        principal=SPONSOR, manifest_digest_seen=await committer.offer(first), accepted_exceptions=()
    )
    assert blocked.commit is not None
    changed = await _manifest(
        prose=("Một đoạn mở đầu khác hẳn.", *PROSE[1:]),
        predecessor=first.digest(),
        prefix=blocked.commit.completed_steps,
    )

    with pytest.raises(CommitRefused) as refused:
        await committer.offer(changed)
    aborted = await committer.abort(principal=SPONSOR)

    assert refused.value.code is CommitRefusal.SUCCESSOR_REFUSED
    assert "scene_draft[1,1]" in refused.value.detail
    assert aborted.phase is RunPhase.ABORTED_PARTIAL
    assert await _count(factory, RevisionAcceptanceDecisionModel) == 2
    with pytest.raises(CommitRefused) as again:
        await committer.abort(principal=SPONSOR)
    assert again.value.code is CommitRefusal.NOT_ABORTABLE


def test_the_manifest_digest_covers_its_payload_only():
    manifest = asyncio.run(_manifest())
    assert manifest.digest() == manifest.model_copy().digest()
    assert manifest.digest() != manifest.model_copy(update={"export_digest": "sha256:" + "f" * 64}).digest()


def test_rebuilding_from_the_same_inputs_gives_the_same_manifest():
    """Every id and context binding is derived from content, so an unchanged earlier scene never changes a later
    scene's context identity; no rebase revision is ever needed."""
    first, second = asyncio.run(_manifest()), asyncio.run(_manifest())
    assert first.digest() == second.digest()
    changed_last = asyncio.run(_manifest(prose=(*PROSE[:-1], "Một kết thúc khác.")))
    assert changed_last.scenes[:-1] == first.scenes[:-1]
    assert changed_last.scenes[-1].decision_id != first.scenes[-1].decision_id


async def test_a_command_naming_another_actor_is_refused_even_with_a_grant(
    concurrent_session_factory: Factory, grants: CurrentShowrunnerGrantReader
):
    factory = concurrent_session_factory
    authority = GrantNarrativeShowrunnerAuthority(factory, grants)
    manifest = await _manifest()
    forged = acceptance_command(
        manifest.scenes[0].revision, decision_id=manifest.scenes[0].decision_id, actor_id="someone-else"
    )

    with pytest.raises(NarrativeDecisionAuthorizationError):
        await authority.authorize_initial_decision(SPONSOR, forged)

    granted = await authority.authorize_initial_decision(
        SPONSOR,
        acceptance_command(manifest.scenes[0].revision, decision_id=manifest.scenes[0].decision_id, actor_id=SPONSOR),
    )
    assert (granted.actor_id, granted.authority_role) == (SPONSOR, "HUMAN_SHOWRUNNER")
    assert granted.authenticated_via.startswith("governance-grant:")
