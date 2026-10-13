"""One bounded M7 spatial execution becomes exactly one evidence-bound M8 revision, or nothing."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.advanced_creative import M8CandidateRevisionModel
from lib.db.models.host_hardening import ExecutionAttemptModel
from lib.db.models.spatial_source import SpatialExecutionEvidenceModel
from lib.db.repositories.spatial_execution import SpatialExecutionEvidenceRepository
from lib.db.repositories.spatial_source import _receipt_digest
from lib.video_backends.base import AmbiguousSubmitError
from r2.advanced_creative.errors import CandidateConflictError, CommandConflictError, PromotionTargetUnavailableError
from r2.contracts.advanced_creative import (
    EvidenceClass,
    ExplorationKind,
    LineageBinding,
    PromotionTarget,
    PromotionTargetKind,
)
from r2.contracts.host_hardening import ExecutionAttemptState, ProviderRouteSnapshot
from r2.host_hardening.route_inventory import HOST_SPATIAL_ADAPTER_VERSION
from r2.m3.host_integration import GoldenAHostIntegration
from server.services.advanced_creative import exploration_service
from server.services.execution_attempts import build_attempt_submitter
from server.services.spatial_execution import (
    SpatialExecutionCommand,
    SpatialExecutionService,
    SpatialExecutionUnavailableError,
    SpatialFrameRef,
)
from server.services.spatial_source import FrameDerivationService
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _body

type Factory = async_sessionmaker[AsyncSession]

ROUTE = ProviderRouteSnapshot(
    provider_id="gemini",
    provider_account_ref="default",
    provider_model_id="gemini-spatial-fixture",
    backend_model_id="gemini-spatial-fixture",
    endpoint_id="gemini-generate",
    submitted_base_url="https://generativelanguage.googleapis.com",
    adapter_version=HOST_SPATIAL_ADAPTER_VERSION,
    capability_profile_ref="gemini-generate-spatial@host-spatial-v1",
)
LINEAGE = LineageBinding(
    project_name=PROJECT,
    content_basis_digest="sha256:" + "1" * 64,
    approved_master_id=None,
    approved_master_digest=None,
    creative_profile_id="western",
    creative_profile_version="v1",
    policy_digest="sha256:" + "2" * 64,
)


@cache
def _colored_media(color: str) -> bytes:
    """A real one-second MP4 whose frames are a solid ``color``."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "shot.mp4"
        subprocess.run(
            [
                *("ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=64x36:d=1"),
                *("-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)),
            ],
            check=True,
        )
        return out.read_bytes()


async def _approve_shot(client: AsyncClient, project_dir: Path, shot: str, color: str) -> None:
    data = _colored_media(color)
    (project_dir / "production" / f"{shot}.mp4").write_bytes(data)
    response = await client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body(shot, data))
    assert response.status_code == 200, response.text


def _response() -> dict[str, Any]:
    return {
        "schema_version": "r2-spatial-response-v1",
        "walls": {
            "front": {
                "must_preserve": [
                    {
                        "name": "red fire extinguisher cabinet",
                        "type": "cabinet",
                        "source_view": "master",
                        "size_lock": "large",
                        "source_spans": [{"source_ref": "master", "x0": 0.05, "y0": 0.2, "x1": 0.2, "y1": 0.8}],
                    }
                ],
                "inferred_fill": [
                    {
                        "name": "hidden corridor",
                        "relation": "may continue",
                        "confidence": 0.4,
                        "source_refs": ["master"],
                    }
                ],
            },
            "back": {
                "must_preserve": [
                    {
                        "name": "blue exit door",
                        "type": "door",
                        "source_view": "reverse",
                        "size_lock": "large",
                        "source_spans": [{"source_ref": "reverse", "x0": 0.7, "y0": 0.2, "x1": 0.9, "y1": 0.8}],
                    }
                ]
            },
            "left": {"shared_overlap": []},
            "right": {"shared_overlap": []},
        },
        "joins": [],
        "coverage_assessment": {
            "coverage_gaps": [{"description": "left rear corner unseen", "source_refs": ["reverse"]}]
        },
    }


class _Vision:
    def __init__(self, raw: bytes | None = None, error: Exception | None = None) -> None:
        self.raw = json.dumps(_response()).encode() if raw is None else raw
        self.error = error
        self.calls: list[tuple[str, bytes, bytes]] = []
        self.before_return: Any = None

    async def __call__(self, *, prompt: str, master_png: bytes, reverse_png: bytes) -> bytes:
        self.calls.append((prompt, master_png, reverse_png))
        if self.before_return is not None:
            await self.before_return()
        if self.error is not None:
            raise self.error
        return self.raw


def _service(
    factory: Factory,
    project_dir: Path,
    vision: _Vision,
    evidence_store: type[SpatialExecutionEvidenceRepository] = SpatialExecutionEvidenceRepository,
) -> SpatialExecutionService:
    async def lineage(_project: str, _episode: int) -> LineageBinding:
        return LINEAGE

    return SpatialExecutionService(
        session_factory=factory,
        project_dir=project_dir,
        route=ROUTE,
        vision=vision,
        submitter_for=lambda session, user_id, project_name: build_attempt_submitter(
            session, user_id=user_id, project_name=project_name, usage_binder=None
        ),
        lineage_for=lineage,
        evidence_store=evidence_store,
    )


async def _frames(client: AsyncClient, project_dir: Path, factory: Factory) -> tuple[SpatialFrameRef, SpatialFrameRef]:
    refs = []
    derive = FrameDerivationService(session_factory=factory, project_dir=project_dir)
    for shot, color in (("SH01", "red"), ("SH02", "blue")):
        await _approve_shot(client, project_dir, shot, color)
        key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        receipt = await derive.derive(
            user_id=USER.id,
            project_name=PROJECT,
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id=f"frame-{shot}",
        )
        refs.append(SpatialFrameRef(receipt_id=receipt.frame_candidate_id, receipt_digest=_receipt_digest(receipt)))
    return refs[0], refs[1]


def _command(master: SpatialFrameRef, reverse: SpatialFrameRef, **overrides: Any) -> SpatialExecutionCommand:
    values: dict[str, Any] = {
        "user_id": USER.id,
        "project_name": PROJECT,
        "command_id": "spatial-1",
        "candidate_id": "spatial-candidate-1",
        "expected_head_version": None,
        "episode": 1,
        "scene_name": "Lobby",
        "master": master,
        "reverse": reverse,
    }
    values.update(overrides)
    return SpatialExecutionCommand(**values)


async def _counts(factory: Factory) -> tuple[int, int]:
    async with factory() as session:
        revisions = (
            await session.execute(
                select(func.count())
                .select_from(M8CandidateRevisionModel)
                .where(M8CandidateRevisionModel.kind == ExplorationKind.SPATIAL.value)
            )
        ).scalar_one()
        evidence = (await session.execute(select(func.count()).select_from(SpatialExecutionEvidenceModel))).scalar_one()
    return revisions, evidence


async def _attempt_states(factory: Factory) -> list[str]:
    async with factory() as session:
        return list((await session.execute(select(ExecutionAttemptModel.state))).scalars())


@pytest.mark.asyncio
async def test_execution_appends_one_revision_with_exact_evidence(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    vision = _Vision()
    head = await _service(session_factory, project_dir, vision).execute(_command(master, reverse))

    assert (head.current_revision, head.head_version) == (1, 1)
    assert len(vision.calls) == 1
    prompt, master_png, reverse_png = vision.calls[0]
    assert "Scene: Lobby" in prompt
    assert master_png.startswith(b"\x89PNG")
    assert master_png != reverse_png
    async with session_factory() as session:
        stored = await SpatialExecutionEvidenceRepository(session).get_by_command(
            user_id=USER.id, project_name=PROJECT, command_id="spatial-1"
        )
        revision = await exploration_service(session).get_exact(
            user_id=USER.id, project_name=PROJECT, candidate_id="spatial-candidate-1", revision=1
        )
    assert stored is not None
    assert stored.raw_response == vision.raw
    assert [frame.frame_receipt_id for frame in stored.evidence.ordered_source_frames] == [
        master.receipt_id,
        reverse.receipt_id,
    ]
    assert stored.evidence.overlap_response is None
    spatial = revision.payload.spatial
    assert spatial.execution_id == stored.evidence.execution_id
    classes = {assertion.evidence_class for assertion in spatial.assertions}
    assert classes == {EvidenceClass.VISIBLE, EvidenceClass.INFERRED, EvidenceClass.GAP}
    assert await _attempt_states(session_factory) == [ExecutionAttemptState.SUCCEEDED.value]

    with pytest.raises(PromotionTargetUnavailableError):
        async with session_factory() as session:
            await exploration_service(session).create_preview(
                user_id=USER.id,
                project_name=PROJECT,
                candidate_id="spatial-candidate-1",
                revision=1,
                target=PromotionTarget(
                    kind=PromotionTargetKind.PRODUCTION_BINDING, target_ref="binding-1", expected_target_version=0
                ),
                command_id="preview-1",
            )
    assert await _counts(session_factory) == (1, 1)


@pytest.mark.asyncio
async def test_exact_replay_returns_head_without_a_second_call_and_changed_body_conflicts(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    vision = _Vision()
    service = _service(session_factory, project_dir, vision)
    first = await service.execute(_command(master, reverse))
    assert await service.execute(_command(master, reverse)) == first
    assert len(vision.calls) == 1

    for changed in (
        _command(master, reverse, scene_name="Hall"),
        _command(reverse, master),
        _command(master, reverse, candidate_id="other-candidate"),
        _command(master, reverse, episode=2),
    ):
        with pytest.raises(CommandConflictError):
            await service.execute(changed)
    assert len(vision.calls) == 1
    assert await _counts(session_factory) == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b'Here is the JSON: {"schema_version": "r2-spatial-response-v1"}',
        json.dumps({**_response(), "schema_version": "v0"}).encode(),
        json.dumps({key: value for key, value in _response().items() if key != "walls"}).encode(),
        json.dumps(
            {
                **_response(),
                "walls": {
                    **_response()["walls"],
                    "front": {"must_preserve": [{"name": "door", "source_view": "master", "source_spans": []}]},
                },
            }
        ).encode(),
    ],
    ids=["malformed", "prose_wrapped", "wrong_schema", "partial_walls", "visible_without_span"],
)
async def test_unusable_model_output_creates_no_revision(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, raw: bytes
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    with pytest.raises(SpatialExecutionUnavailableError):
        await _service(session_factory, project_dir, _Vision(raw=raw)).execute(_command(master, reverse))
    assert await _counts(session_factory) == (0, 0)
    assert await _attempt_states(session_factory) == [ExecutionAttemptState.SUCCEEDED.value]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "state"),
    [
        (RuntimeError("provider rejected"), ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE),
        (
            AmbiguousSubmitError(provider="gemini", message="connection reset"),
            ExecutionAttemptState.SUBMIT_OUTCOME_UNKNOWN,
        ),
    ],
    ids=["definite_failure", "ambiguous"],
)
async def test_provider_failure_creates_no_revision(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    error: Exception,
    state: ExecutionAttemptState,
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    service = _service(session_factory, project_dir, _Vision(error=error))
    with pytest.raises(SpatialExecutionUnavailableError):
        await service.execute(_command(master, reverse))
    with pytest.raises(SpatialExecutionUnavailableError):
        await service.execute(_command(master, reverse))
    assert await _counts(session_factory) == (0, 0)
    assert await _attempt_states(session_factory) == [state.value]


@pytest.mark.asyncio
async def test_stale_or_identical_sources_deny_before_the_provider(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    vision = _Vision()
    service = _service(session_factory, project_dir, vision)
    with pytest.raises(SpatialExecutionUnavailableError):
        await service.execute(
            _command(SpatialFrameRef(receipt_id=master.receipt_id, receipt_digest="sha256:" + "0" * 64), reverse)
        )
    with pytest.raises(CandidateConflictError):
        await service.execute(_command(master, master))
    assert vision.calls == []
    assert await _counts(session_factory) == (0, 0)


@pytest.mark.asyncio
async def test_source_advance_during_the_call_rolls_back_everything(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    vision = _Vision()

    async def advance_master() -> None:
        await _approve_shot(gate_export_client, project_dir, "SH01", "green")

    vision.before_return = advance_master
    with pytest.raises(SpatialExecutionUnavailableError):
        await _service(session_factory, project_dir, vision).execute(_command(master, reverse))
    assert await _counts(session_factory) == (0, 0)


@pytest.mark.asyncio
async def test_candidate_head_conflict_rolls_back_the_evidence(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    with pytest.raises(CandidateConflictError):
        await _service(session_factory, project_dir, _Vision()).execute(
            _command(master, reverse, expected_head_version=3)
        )
    assert await _counts(session_factory) == (0, 0)


@pytest.mark.asyncio
async def test_pg_concurrent_identical_commands_write_one_revision(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    if session_factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("concurrent attempt admission requires PostgreSQL")
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    vision = _Vision()
    service = _service(session_factory, project_dir, vision)
    results = await asyncio.gather(
        service.execute(_command(master, reverse)),
        service.execute(_command(master, reverse)),
        return_exceptions=True,
    )
    heads = [result for result in results if not isinstance(result, BaseException)]
    errors = [result for result in results if isinstance(result, BaseException)]
    assert heads
    assert all(isinstance(error, SpatialExecutionUnavailableError) for error in errors)
    assert len(vision.calls) == 1
    assert await _counts(session_factory) == (1, 1)


@pytest.mark.asyncio
async def test_evidence_write_failure_after_the_revision_rolls_back_both(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    master, reverse = await _frames(gate_export_client, project_dir, session_factory)

    class _FailingEvidence(SpatialExecutionEvidenceRepository):
        async def stage(self, **_kwargs: Any) -> None:
            raise OSError("evidence storage unavailable")

    with pytest.raises(OSError, match="evidence storage"):
        await _service(session_factory, project_dir, _Vision(), _FailingEvidence).execute(_command(master, reverse))
    assert await _counts(session_factory) == (0, 0)
    assert await _attempt_states(session_factory) == [ExecutionAttemptState.ACCEPTED.value]


@pytest.mark.asyncio
async def test_release_mode_refuses_the_unqualified_spatial_route_before_the_provider(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from r2.host_hardening.paid_routes import RELEASE_MODE_ENV

    master, reverse = await _frames(gate_export_client, project_dir, session_factory)
    monkeypatch.setenv(RELEASE_MODE_ENV, "PRODUCTION_CANDIDATE")
    vision = _Vision()
    with pytest.raises(SpatialExecutionUnavailableError, match="route"):
        await _service(session_factory, project_dir, vision).execute(_command(master, reverse))
    assert vision.calls == []
    assert await _counts(session_factory) == (0, 0)
    assert await _attempt_states(session_factory) == []
