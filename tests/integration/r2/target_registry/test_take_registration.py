"""Persisted admissions drive one scoped, replay-safe Take target bundle."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from lib.db.models.production_target import (
    ProductionTargetCommandModel,
    ProductionTargetHeadModel,
    ProductionTargetVersionModel,
)
from lib.db.repositories.production_target import (
    ProductionTargetCommandConflictError,
    ProductionTargetIntegrityError,
    ProductionTargetRepository,
)
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.evaluation import ProfileEvaluationService, report_ref_of
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.production_intelligence.director import DirectorRouteUnavailable
from r2.target_registry.service import RegisterTakeTargetsCommand, TakeTargetRegistrationService
from tests.integration.r2.adaptation._fakes import FakeAuthority
from tests.integration.r2.adaptation.test_screenplay_admission import (
    _admit_command,
    _screenplay_ref,
    _seed_admissible_proposal,
)

type Factory = async_sessionmaker[AsyncSession]
USER = "u1"
PROJECT = "project-a"
PRINCIPAL = "human:anhtuan"


async def _admit(
    factory: Factory,
    *,
    branch_id: str = "branch-1",
    map_id: str = "map-1",
    screenplay_id: str = "sp-1",
    decision_id: str = "d-admit-1",
):
    evidence = AdaptationEvidenceService(adaptation_uow_factory(factory))
    authority = AdaptationAuthorityService(adaptation_uow_factory(factory), FakeAuthority())
    evaluation = ProfileEvaluationService(adaptation_uow_factory(factory))
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        evidence, authority, evaluation, branch_id=branch_id, map_id=map_id, screenplay_id=screenplay_id
    )
    admit = _admit_command(
        decision_id=decision_id,
        branch_id=branch_id,
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    receipt = await authority.admit_screenplay_for_direction(admit, authenticated_principal=PRINCIPAL)
    ref = AdmittedScreenplayRef(
        screenplay_ref=_screenplay_ref(admit.admitted_screenplay),
        admission_ref=receipt.decision_ref,
        profile_ref=branch.profile_ref,
    )
    return ref, branch, map_receipt, proposal, admit, evidence, authority, evaluation, report


def _command(
    ref: AdmittedScreenplayRef, *, command_id: str = "take-1", project_name: str = PROJECT, user_id: str = USER
):
    return RegisterTakeTargetsCommand(
        user_id=user_id,
        project_name=project_name,
        principal=PRINCIPAL,
        command_id=command_id,
        admitted_screenplay_ref=ref,
    )


async def test_register_and_exact_replay_write_one_complete_bundle(session_factory: Factory) -> None:
    ref, *_ = await _admit(session_factory)
    service = TakeTargetRegistrationService(session_factory)
    command = _command(ref)
    first = await service.register(command)
    assert len(first.scene_targets) == len(first.shot_targets) == 1
    assert first.scene_targets[0].registry_version == 1
    assert first.shot_targets[0].registry_version == 1
    assert await service.register(command) == first
    another = await service.register(_command(ref, command_id="take-same-admission"))
    assert another.scene_targets == first.scene_targets
    assert another.shot_targets == first.shot_targets
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(ProductionTargetCommandModel)) == 2


async def test_changed_command_conflicts_and_wrong_scope_or_profile_creates_no_bundle(session_factory: Factory) -> None:
    ref, *_ = await _admit(session_factory)
    service = TakeTargetRegistrationService(session_factory)
    first = await service.register(_command(ref))
    changed = ref.model_copy(
        update={"profile_ref": ref.profile_ref.model_copy(update={"policy_pack_digest": "sha256:" + "f" * 64})}
    )
    with pytest.raises(ProductionTargetCommandConflictError):
        await service.register(_command(changed))
    with pytest.raises(DirectorRouteUnavailable):
        await service.register(_command(changed, command_id="forged"))
    with pytest.raises(DirectorRouteUnavailable):
        await service.register(_command(ref, command_id="wrong-scope", project_name="foreign"))
    with pytest.raises(DirectorRouteUnavailable):
        await service.register(_command(ref, command_id="wrong-user", user_id="foreign"))
    assert await service.register(_command(ref)) == first
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 2
        assert await session.scalar(select(func.count()).select_from(ProductionTargetCommandModel)) == 1


async def test_new_admission_advances_versions_and_stale_replay_fails(session_factory: Factory) -> None:
    ref, branch, map_receipt, proposal, first_admit, evidence, authority, evaluation, _ = await _admit(session_factory)
    service = TakeTargetRegistrationService(session_factory)
    first = await service.register(_command(ref))
    changed_scene = proposal.scenes[0].model_copy(update={"purpose": "changed stakes"})
    next_draft = proposal.model_copy(
        update={
            "version": first_admit.admitted_screenplay.version + 1,
            "scenes": [changed_scene],
            "content_hash": "pending",
        }
    )
    next_proposal = await evidence.append_screenplay(
        next_draft.model_copy(update={"content_hash": compute_adaptation_hash(next_draft)}),
        user_id=USER,
        project_name=PROJECT,
    )
    next_report = await evaluation.evaluate(
        artifact_ref=_screenplay_ref(next_proposal), profile_ref=branch.profile_ref, user_id=USER, project_name=PROJECT
    )
    next_admit = _admit_command(
        decision_id="d-admit-next",
        proposal=next_proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(next_report)],
        expected_predecessor_id=first_admit.decision_id,
    )
    next_receipt = await authority.admit_screenplay_for_direction(next_admit, authenticated_principal=PRINCIPAL)
    next_ref = AdmittedScreenplayRef(
        screenplay_ref=_screenplay_ref(next_admit.admitted_screenplay),
        admission_ref=next_receipt.decision_ref,
        profile_ref=branch.profile_ref,
    )
    with pytest.raises(DirectorRouteUnavailable):
        await service.register(_command(ref))
    second = await service.register(_command(next_ref, command_id="take-2"))
    assert second.scene_targets[0].target_id == first.scene_targets[0].target_id
    assert second.shot_targets[0].target_id == first.shot_targets[0].target_id
    assert second.scene_targets[0].registry_version == 2
    assert second.shot_targets[0].registry_version == 2
    assert second.scene_targets[0].version_digest != first.scene_targets[0].version_digest
    assert second.shot_targets[0].version_digest != first.shot_targets[0].version_digest
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 4
        shot = await session.get(
            ProductionTargetVersionModel,
            (USER, PROJECT, "SHOT", second.shot_targets[0].target_id, 2),
        )
        assert shot is not None
        assert shot.scene_registry_version == second.scene_targets[0].registry_version
        assert shot.scene_version_digest == second.scene_targets[0].version_digest


async def test_replay_rejects_corrupt_receipt_before_target_read(session_factory: Factory) -> None:
    ref, *_ = await _admit(session_factory)
    service = TakeTargetRegistrationService(session_factory)
    await service.register(_command(ref))
    async with session_factory() as session:
        await session.execute(update(ProductionTargetCommandModel).values(result_digest="sha256:" + "f" * 64))
        await session.commit()
    with pytest.raises(ProductionTargetIntegrityError):
        await service.register(_command(ref))


async def test_replay_rejects_corrupt_target_body(session_factory: Factory) -> None:
    ref, *_ = await _admit(session_factory)
    service = TakeTargetRegistrationService(session_factory)
    await service.register(_command(ref))
    async with session_factory() as session:
        shot = await session.get(ProductionTargetVersionModel, (USER, PROJECT, "SHOT", "scene-1-TAKE-1", 1))
        assert shot is not None
        shot.target_body_json = shot.target_body_json | {"purpose": "forged"}
        await session.commit()
    with pytest.raises(ProductionTargetIntegrityError):
        await service.register(_command(ref))


async def test_shot_append_failure_rolls_back_scene_head_version_and_receipt(
    session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref, *_ = await _admit(session_factory)
    original = ProductionTargetRepository.append_version

    async def fail_on_shot(self, *, head, body, target):
        if body.target_type.value == "SHOT":
            raise RuntimeError("injected Shot append failure")
        return await original(self, head=head, body=body, target=target)

    monkeypatch.setattr(ProductionTargetRepository, "append_version", fail_on_shot)
    with pytest.raises(RuntimeError, match="injected Shot append failure"):
        await TakeTargetRegistrationService(session_factory).register(_command(ref))
    async with session_factory() as session:
        for model in (ProductionTargetHeadModel, ProductionTargetVersionModel, ProductionTargetCommandModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
