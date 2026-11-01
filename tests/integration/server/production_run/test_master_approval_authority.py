"""Shared master owner fencing, using real media and delegated PostgreSQL authority.

These fixtures exercise the internal owner seam, not upstream generation or launch qualification.
"""

from decimal import Decimal

import pytest
import sqlalchemy as sa

from lib.db.models.host_hardening import MasterHeadVersionModel, PromotionReceiptModel
from lib.db.repositories.production_runs import ProductionRunRepository
from r2.contracts.automation import RunStage
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ProductionMethod
from r2.m3.render_plan import RenderedCutAsset
from server.routers import gates
from server.services.master_authority import projected_masters
from tests.integration.lib.db.repositories.test_production_runs import intent_for
from tests.integration.server.routers.test_gates_export import _media, _sha
from tests.integration.server.services.test_automation_grants import delegated_host as delegated_host
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env
from tests.integration.server.services.test_automation_grants import subject_for


@pytest.fixture
async def master_owner_run(delegated_host, tmp_path):
    issuer, sessions, _, grant, run, *_ = delegated_host
    async with sessions() as session, session.begin():
        repo = ProductionRunRepository(session)
        await repo.transition(
            expected=run,
            updated=run.model_copy(update={"stage": RunStage.MASTER, "version": run.version + 1}),
            fencing_epoch=run.fencing_epoch,
        )
    async with sessions() as session, session.begin():
        repo = ProductionRunRepository(session)
        run = await repo.claim_due(owner_id="master-worker", lease_seconds=30)
        await repo.stage_intent(run=run, intent=intent_for(run))
    project_dir = tmp_path / "projects" / run.project_name
    production = project_dir / "production"
    production.mkdir(parents=True)
    data = _media(b"automatic-master-owner")
    output = production / "SH01.mp4"
    output.write_bytes(data)
    cut = gates.CutApproval(
        resource_type="videos",
        episode=1,
        target_ref="SH01",
        content_fingerprint="shot-semantic-fingerprint",
        content_basis=ContentBasis(basis_type="FACTUAL", basis_version="v1", refs=["research:RP-1"]),
        direct_dependencies=[],
        contract_version=1,
        contract_schema_version="1",
        approval_record="automation-owner-test",
        audio_decision=None,
        request_digest=_sha(data),
        produced=RenderedCutAsset(
            target_ref="SH01",
            method=ProductionMethod.DETERMINISTIC,
            path=output,
            sha256=_sha(data),
            duration_seconds=1.0,
            execution_fingerprint="render-fingerprint",
            tool="ffmpeg",
            tool_version="test-fixture",
            wall_time_seconds=0.0,
            external_provider_cost=Decimal(0),
            source_master_refs=(),
        ),
    )
    return issuer, sessions, grant, run, subject_for(run, grant), project_dir, cut


async def test_shared_master_core_keeps_actual_actor_and_revalidates_exact_retry(master_owner_run):
    from server.auth import create_token
    from server.routers.gates import CutApprovalActor, approve_cut_core

    issuer, sessions, grant, run, subject, project_dir, cut = master_owner_run

    async def guard(session):
        assert await session.scalar(sa.select(sa.func.count()).select_from(MasterHeadVersionModel)) == 1
        await issuer.authority().require_locked(session, subject=subject)

    actor = CutApprovalActor(user_id=run.user_id, principal=grant.principal)
    result = await approve_cut_core(
        actor=actor,
        project_name=run.project_name,
        project_dir=project_dir,
        approval=cut,
        sessions=sessions,
        authority_guard=guard,
    )
    master = result["approved_master"]
    receipt = result["receipt"]
    assert isinstance(master, dict)
    assert isinstance(receipt, dict)
    assert master["selected_by"] == grant.principal
    assert receipt["selected_by"] == grant.principal
    replay = await approve_cut_core(
        actor=actor,
        project_name=run.project_name,
        project_dir=project_dir,
        approval=cut,
        sessions=sessions,
        authority_guard=guard,
    )
    assert replay == result
    await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)
    with pytest.raises(PermissionError):
        await approve_cut_core(
            actor=actor,
            project_name=run.project_name,
            project_dir=project_dir,
            approval=cut,
            sessions=sessions,
            authority_guard=guard,
        )
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(MasterHeadVersionModel)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(PromotionReceiptModel)) == 1


async def test_revocation_after_master_owner_writes_rolls_back_promotion(master_owner_run, monkeypatch):
    from r2.host_hardening.master_authority import MasterAuthorityUnit
    from server.auth import create_token
    from server.routers.gates import CutApprovalActor, approve_cut_core

    issuer, sessions, grant, run, subject, project_dir, cut = master_owner_run
    original = MasterAuthorityUnit.promote_staged

    async def revoke_after_promote(owner, **kwargs):
        head = await original(owner, **kwargs)
        await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)
        return head

    monkeypatch.setattr(MasterAuthorityUnit, "promote_staged", revoke_after_promote)

    async def guard(session):
        await issuer.authority().require_locked(session, subject=subject)

    with pytest.raises(PermissionError):
        await approve_cut_core(
            actor=CutApprovalActor(user_id=run.user_id, principal=grant.principal),
            project_name=run.project_name,
            project_dir=project_dir,
            approval=cut,
            sessions=sessions,
            authority_guard=guard,
        )
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(MasterHeadVersionModel)) == 0
        assert await session.scalar(sa.select(sa.func.count()).select_from(PromotionReceiptModel)) == 0
    assert projected_masters(project_dir) == {}


@pytest.mark.parametrize("completed_phase", [1, 2])
async def test_revocation_between_committed_phases_blocks_projection_or_receipt(
    master_owner_run, monkeypatch, completed_phase
):
    from contextlib import asynccontextmanager

    from lib.db.models.gates import FinalCutReceiptModel
    from server.auth import create_token
    from server.routers.gates import CutApprovalActor, approve_cut_core

    issuer, sessions, grant, run, subject, project_dir, cut = master_owner_run
    original = gates.serialized_artifacts
    phases = 0

    @asynccontextmanager
    async def revoke_between_phases(*args, **kwargs):
        nonlocal phases
        phases += 1
        current = phases
        async with original(*args, **kwargs) as session:
            yield session
        if current == completed_phase:
            await issuer.revoke(
                interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version
            )

    monkeypatch.setattr(gates, "serialized_artifacts", revoke_between_phases)

    async def guard(session):
        await issuer.authority().require_locked(session, subject=subject)

    with pytest.raises(PermissionError):
        await approve_cut_core(
            actor=CutApprovalActor(user_id=run.user_id, principal=grant.principal),
            project_name=run.project_name,
            project_dir=project_dir,
            approval=cut,
            sessions=sessions,
            authority_guard=guard,
        )
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(MasterHeadVersionModel)) == 1
        assert await session.scalar(sa.select(sa.func.count()).select_from(FinalCutReceiptModel)) == 0
    assert bool(projected_masters(project_dir)) == (completed_phase == 2)


async def test_an_actual_newer_master_prevents_old_projection_and_receipt(master_owner_run, monkeypatch):
    from contextlib import asynccontextmanager
    from dataclasses import replace

    from fastapi import HTTPException

    from lib.db.models.gates import FinalCutReceiptModel
    from server.routers.gates import CutApprovalActor, approve_cut_core

    issuer, sessions, grant, run, subject, project_dir, cut = master_owner_run
    actor = CutApprovalActor(user_id=run.user_id, principal=grant.principal)
    data = _media(b"competing-master-owner")
    path = project_dir / "production" / "SH01-successor.mp4"
    path.write_bytes(data)
    successor = replace(
        cut,
        produced=replace(cut.produced, path=path, sha256=_sha(data)),
        request_digest=_sha(data),
        approval_record="competing-owner-command",
    )
    original = gates.serialized_artifacts
    first = True

    @asynccontextmanager
    async def move_between_phases(*args, **kwargs):
        nonlocal first
        advance = first
        first = False
        async with original(*args, **kwargs) as session:
            yield session
        if advance:
            await approve_cut_core(
                actor=actor,
                project_name=run.project_name,
                project_dir=project_dir,
                approval=successor,
                sessions=sessions,
            )

    monkeypatch.setattr(gates, "serialized_artifacts", move_between_phases)

    async def guard(session):
        await issuer.authority().require_locked(session, subject=subject)

    with pytest.raises(HTTPException, match="master_superseded"):
        await approve_cut_core(
            actor=actor,
            project_name=run.project_name,
            project_dir=project_dir,
            approval=cut,
            sessions=sessions,
            authority_guard=guard,
        )
    async with sessions() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(MasterHeadVersionModel)) == 2
        assert await session.scalar(sa.select(sa.func.count()).select_from(FinalCutReceiptModel)) == 1


async def test_receipt_sequence_conflict_fallback_revalidates_revoked_authority(master_owner_run, monkeypatch):
    from lib.db.repositories.gates import FinalCutReceiptRepository, GateSequenceConflictError
    from server.auth import create_token
    from server.routers.gates import CutApprovalActor, approve_cut_core

    issuer, sessions, grant, run, subject, project_dir, cut = master_owner_run
    actor = CutApprovalActor(user_id=run.user_id, principal=grant.principal)

    async def guard(session):
        await issuer.authority().require_locked(session, subject=subject)

    await approve_cut_core(
        actor=actor,
        project_name=run.project_name,
        project_dir=project_dir,
        approval=cut,
        sessions=sessions,
        authority_guard=guard,
    )
    original_get = FinalCutReceiptRepository.get_by_id
    once = True

    async def conflicted_read(repo, receipt_id):
        nonlocal once
        if once:
            once = False
            return None
        return await original_get(repo, receipt_id)

    async def raced_append(repo, receipt, *, receipt_id):
        await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)
        raise GateSequenceConflictError("another receipt writer won the insert")

    monkeypatch.setattr(FinalCutReceiptRepository, "get_by_id", conflicted_read)
    monkeypatch.setattr(FinalCutReceiptRepository, "append", raced_append)
    with pytest.raises(PermissionError):
        await approve_cut_core(
            actor=actor,
            project_name=run.project_name,
            project_dir=project_dir,
            approval=cut,
            sessions=sessions,
            authority_guard=guard,
        )
