"""The current LOCATION binding snapshot verifies the spatial constraint set its envelope names."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_binding import ProductionBindingHeadModel, ProductionBindingVersionModel
from lib.db.models.spatial_pair import SpatialConstraintSetModel
from lib.db.repositories.production_binding import ProductionBindingIntegrityError
from lib.db.repositories.spatial_constraint import SpatialConstraintSetRepository
from lib.db.repositories.spatial_source import _receipt_digest
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.contracts.spatial_constraint import SpatialConstraintSetV1, SpatialSourceBindingV1
from r2.m3.host_integration import GoldenAHostIntegration
from r2.production_binding.digests import binding_envelope_digest
from r2.production_binding.spatial_set import (
    derive_spatial_constraint_set,
    spatial_constraint_set_digest,
    spatial_constraint_set_id,
)
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.target_registry.service import TakeTargetRegistrationService
from server.services.location_binding import BindingSourceConflictError, LocationBindingCreationService
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.spatial_source import FrameDerivationService
from tests.integration.r2.adaptation import test_screenplay_admission as admission_helpers
from tests.integration.r2.target_registry import test_take_registration as target_helpers
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _approve_shot
from tests.unit.r2.production_binding import spatial_constraint_fixture as fixture

type Factory = async_sessionmaker[AsyncSession]


async def _current_binding(
    client: AsyncClient,
    project_dir: Path,
    factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    shot_duration: float | None = None,
) -> tuple[str, str]:
    """Register a Take Shot whose Scene has a location, then create its LOCATION binding from two frames."""
    monkeypatch.setattr(admission_helpers, "USER", USER.id)
    monkeypatch.setattr(admission_helpers, "PROJECT", PROJECT)
    admission, *_ = await target_helpers._admit(factory)
    original_direct = TakeDirectorAdapter.direct

    async def direct_with_location(self, ref):
        result = await original_direct(self, ref)
        shots = result.shots
        if shot_duration is not None:
            shots = tuple(shot.model_copy(update={"target_duration": shot_duration}) for shot in shots)
        return replace(
            result,
            scenes=tuple(scene.model_copy(update={"location_ref": "location:room-1"}) for scene in result.scenes),
            shots=shots,
        )

    monkeypatch.setattr(TakeDirectorAdapter, "direct", direct_with_location)
    registered = await TakeTargetRegistrationService(factory).register(
        target_helpers._command(admission, user_id=USER.id, project_name=PROJECT)
    )
    derived = []
    for shot, tag in (("SH01", b"constraint-parent-a"), ("SH02", b"constraint-parent-b")):
        await _approve_shot(client, project_dir, shot, tag)
        key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        derived.append(
            await FrameDerivationService(session_factory=factory, project_dir=project_dir).derive(
                user_id=USER.id,
                project_name=PROJECT,
                parent_artifact_key=key,
                expected_master_version=1,
                decoded_frame_index=0,
                command_id=f"constraint-frame-{shot}",
            )
        )
    derived.sort(key=lambda receipt: receipt.frame_candidate_id)
    command = BindingCreateCommandV1.model_validate(
        {
            "user_id": USER.id,
            "project_name": PROJECT,
            "principal": USER.sub,
            "command_id": "constraint-binding-1",
            "expected_target_ref": registered.shot_targets[0].model_dump(mode="json"),
            "ordered_frame_receipts": [
                {"receipt_id": receipt.frame_candidate_id, "receipt_digest": _receipt_digest(receipt)}
                for receipt in derived
            ],
        }
    )
    created = await LocationBindingCreationService(session_factory=factory, project_dir=project_dir).create(command)
    return created.result.binding_id, registered.shot_targets[0].target_id


def attached_id(constraint_set: SpatialConstraintSetV1) -> str:
    return spatial_constraint_set_id(spatial_constraint_set_digest(constraint_set.model_dump(mode="json")))


async def _envelope(factory: Factory, binding_id: str) -> dict:
    async with factory() as session:
        row = (
            await session.execute(
                select(ProductionBindingVersionModel).where(ProductionBindingVersionModel.binding_id == binding_id)
            )
        ).scalar_one()
        return dict(row.envelope_json)


def _sources(envelope: dict, **master_overrides: object) -> tuple[SpatialSourceBindingV1, SpatialSourceBindingV1]:
    def source(view: str, claim: dict, overrides: dict) -> SpatialSourceBindingV1:
        return SpatialSourceBindingV1.model_validate(
            {
                "view": view,
                "parent_artifact_key": claim["parent_artifact_key"],
                "parent_master_version": claim["parent_master_version"],
                "parent_candidate_id": claim["parent_candidate_id"],
                "parent_content_digest": claim["parent_content_digest"],
                "frame_derivation_receipt_id": claim["receipt_id"],
                "frame_derivation_receipt_digest": claim["receipt_digest"],
                "frame_candidate_id": claim["frame_candidate_id"],
                "frame_content_digest": claim["frame_content_digest"],
                **overrides,
            }
        )

    first, second = envelope["ordered_claims"]
    return source("MASTER", first, master_overrides), source("REVERSE", second, {})


def _set(binding_id: str, sources: tuple[SpatialSourceBindingV1, SpatialSourceBindingV1]) -> SpatialConstraintSetV1:
    revision = fixture.revision(
        master_digest=sources[0].frame_content_digest,
        reverse_digest=sources[1].frame_content_digest,
        project_name=PROJECT,
    )
    visible = [a.assertion_id for a in revision.payload.spatial.assertions if a.evidence_class.value == "VISIBLE"]
    return derive_spatial_constraint_set(
        user_id=USER.id,
        project_name=PROJECT,
        binding_id=binding_id,
        revision=revision,
        selected_assertion_ids=visible,
        pair_id=fixture.PAIR_ID,
        pair_version=1,
        pair_decision_digest=fixture.PAIR_DECISION_DIGEST,
        ordered_sources=sources,
    )


async def _attach(
    factory: Factory, binding_id: str, constraint_set: SpatialConstraintSetV1, *, stage: bool = True
) -> str:
    """Stand in for the packet-3 promotion writer: stage the set and name it in the current envelope."""
    digest = spatial_constraint_set_digest(constraint_set.model_dump(mode="json"))
    async with factory() as session:
        await SpatialConstraintSetRepository(session).stage(constraint_set)
        row = (
            await session.execute(
                select(ProductionBindingVersionModel).where(ProductionBindingVersionModel.binding_id == binding_id)
            )
        ).scalar_one()
        envelope = {
            **row.envelope_json,
            "spatial_set_id": spatial_constraint_set_id(digest),
            "spatial_set_digest": digest,
        }
        envelope_digest = binding_envelope_digest(envelope)
        row.envelope_json = envelope
        row.envelope_digest = envelope_digest
        await session.execute(
            update(ProductionBindingHeadModel)
            .where(ProductionBindingHeadModel.binding_id == binding_id)
            .values(current_envelope_digest=envelope_digest)
        )
        await session.commit()
    return digest


@pytest.mark.asyncio
async def test_the_snapshot_carries_and_verifies_the_named_spatial_set(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding_id, target_id = await _current_binding(gate_export_client, project_dir, session_factory, monkeypatch)
    reader = CurrentLocationBindingSnapshotReader(session_factory=session_factory, project_dir=project_dir)
    plain = await reader.read_current(user_id=USER.id, project_name=PROJECT, target_id=target_id)
    assert plain.spatial_set is None

    constraint_set = _set(binding_id, _sources(await _envelope(session_factory, binding_id)))
    await _attach(session_factory, binding_id, constraint_set)
    async with session_factory() as session:
        assert await SpatialConstraintSetRepository(session).stage(constraint_set) == attached_id(constraint_set)

    attached = await reader.read_current(user_id=USER.id, project_name=PROJECT, target_id=target_id)
    assert attached.spatial_set == constraint_set
    assert attached.digest != plain.digest


@pytest.mark.asyncio
async def test_a_tampered_or_missing_set_fails_closed(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding_id, target_id = await _current_binding(gate_export_client, project_dir, session_factory, monkeypatch)
    reader = CurrentLocationBindingSnapshotReader(session_factory=session_factory, project_dir=project_dir)
    constraint_set = _set(binding_id, _sources(await _envelope(session_factory, binding_id)))
    await _attach(session_factory, binding_id, constraint_set)

    async with session_factory() as session:
        row = (await session.execute(select(SpatialConstraintSetModel))).scalar_one()
        body = dict(row.body_json)
        body["normalizer_version"] = "tampered"
        row.body_json = body
        await session.commit()
    with pytest.raises(ProductionBindingIntegrityError, match="spatial set"):
        await reader.read_current(user_id=USER.id, project_name=PROJECT, target_id=target_id)

    async with session_factory() as session:
        await session.delete((await session.execute(select(SpatialConstraintSetModel))).scalar_one())
        await session.commit()
    with pytest.raises(ProductionBindingIntegrityError, match="spatial set"):
        await reader.read_current(user_id=USER.id, project_name=PROJECT, target_id=target_id)


@pytest.mark.asyncio
async def test_a_set_whose_sources_differ_from_the_frame_claims_is_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding_id, target_id = await _current_binding(gate_export_client, project_dir, session_factory, monkeypatch)
    reader = CurrentLocationBindingSnapshotReader(session_factory=session_factory, project_dir=project_dir)
    envelope = await _envelope(session_factory, binding_id)
    foreign = _set(binding_id, _sources(envelope, parent_candidate_id="candidate-from-elsewhere"))
    await _attach(session_factory, binding_id, foreign)

    with pytest.raises(BindingSourceConflictError, match="spatial set sources"):
        await reader.read_current(user_id=USER.id, project_name=PROJECT, target_id=target_id)
