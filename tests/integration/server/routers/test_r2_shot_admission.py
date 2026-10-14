"""One Take-derived spatial shot admitted to the Wan two-view profile, with an exact submit identity."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.video_backends.dashscope import DashScopeVideoBackend
from lib.video_backends.execution_adapter import provider_payload_digest
from r2.contracts.shot_generation import R2ExecutionProfileV1
from r2.production_intelligence.shot_identity import host_request_digest, verify_task_evidence
from r2.production_intelligence.shot_profiles import IMAGE_ROLE_LINE, WAN27_TWO_VIEW_PROFILE
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.r2_shot_generation import R2ShotAdmissionRefused, R2ShotCommand, derive_shot_admission
from tests.integration.server.routers.spatial_approval_support import promoted_target
from tests.integration.server.routers.test_gates_export import PROJECT, USER

type Factory = async_sessionmaker[AsyncSession]


async def _builder(profile: R2ExecutionProfileV1) -> DashScopeVideoBackend:
    return DashScopeVideoBackend(api_key="sk-offline", model=profile.backend_model_id)


async def _admissible_shot(
    client: AsyncClient, project_dir: Path, factory: Factory, monkeypatch: pytest.MonkeyPatch, *, duration: float = 5.0
) -> R2ShotCommand:
    target_id = await promoted_target(client, project_dir, factory, monkeypatch, shot_duration=duration)
    snapshot = await CurrentLocationBindingSnapshotReader(
        session_factory=factory, project_dir=project_dir
    ).read_current(user_id=USER.id, project_name=PROJECT, target_id=target_id)
    return R2ShotCommand(
        user_id=USER.id,
        project_name=PROJECT,
        target_id=target_id,
        command_id="shot-1",
        expected_target_registry_version=snapshot.body.target_versions[1].registry_version,
        expected_binding_snapshot_digest=snapshot.digest,
        execution_profile_ref=WAN27_TWO_VIEW_PROFILE.profile_ref,
    )


@pytest.mark.asyncio
async def test_an_admitted_shot_has_a_deterministic_exact_identity(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = await _admissible_shot(gate_export_client, project_dir, session_factory, monkeypatch)

    first = await derive_shot_admission(
        command, session_factory=session_factory, project_dir=project_dir, payload_builder_for=_builder
    )
    again = await derive_shot_admission(
        command, session_factory=session_factory, project_dir=project_dir, payload_builder_for=_builder
    )

    assert first.evidence == again.evidence
    verify_task_evidence(first.evidence, WAN27_TWO_VIEW_PROFILE)
    payload = first.video_request.captured_payload
    assert payload is not None
    assert payload["model"] == "wan2.7-r2v-2026-06-12"
    assert payload["parameters"] == {
        "resolution": "720P",
        "duration": 5,
        "watermark": False,
        "ratio": "16:9",
        "prompt_extend": False,
    }
    assert payload["input"]["prompt"].splitlines()[0] == IMAGE_ROLE_LINE
    assert "Keep the red fire extinguisher cabinet on the front wall." in payload["input"]["prompt"]
    assert [item["type"] for item in payload["input"]["media"]] == ["reference_image", "reference_image"]
    assert first.evidence.provider_payload_digest == provider_payload_digest(payload)
    assert first.evidence.host_request_digest == host_request_digest(first.host_request)
    assert first.host_request.host_task_ref == first.evidence.task_id
    assert first.host_request.execution_options["provider_payload_digest"] == first.evidence.provider_payload_digest
    assert [frame.view for frame in first.evidence.ordered_source_frames] == ["MASTER", "REVERSE"]


@pytest.mark.asyncio
async def test_a_stale_snapshot_or_target_is_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from lib.db.repositories.production_binding import ProductionBindingIntegrityError

    command = await _admissible_shot(gate_export_client, project_dir, session_factory, monkeypatch)

    with pytest.raises(ProductionBindingIntegrityError, match="stale"):
        await derive_shot_admission(
            replace(command, expected_binding_snapshot_digest="sha256:" + "0" * 64),
            session_factory=session_factory,
            project_dir=project_dir,
            payload_builder_for=_builder,
        )
    with pytest.raises(R2ShotAdmissionRefused, match="r2_shot_target_stale"):
        await derive_shot_admission(
            replace(command, expected_target_registry_version=command.expected_target_registry_version + 1),
            session_factory=session_factory,
            project_dir=project_dir,
            payload_builder_for=_builder,
        )


@pytest.mark.asyncio
async def test_a_thirty_second_take_shot_is_refused_by_the_five_second_profile(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = await _admissible_shot(gate_export_client, project_dir, session_factory, monkeypatch, duration=30.0)

    with pytest.raises(R2ShotAdmissionRefused) as refused:
        await derive_shot_admission(
            command, session_factory=session_factory, project_dir=project_dir, payload_builder_for=_builder
        )
    assert refused.value.reasons == ("profile_duration_mismatch",)


@pytest.mark.asyncio
async def test_changed_pinned_source_bytes_are_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = await _admissible_shot(gate_export_client, project_dir, session_factory, monkeypatch)
    first = await derive_shot_admission(
        command, session_factory=session_factory, project_dir=project_dir, payload_builder_for=_builder
    )
    pinned = first.video_request.reference_images[0]
    pinned.write_bytes(b"changed")

    with pytest.raises(R2ShotAdmissionRefused, match="r2_shot_source_changed"):
        await derive_shot_admission(
            command, session_factory=session_factory, project_dir=project_dir, payload_builder_for=_builder
        )
