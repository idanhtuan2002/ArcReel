"""M8-C end to end: an approved frame pair becomes a promoted spatial binding, a generated shot and a Gate C master.

One offline chain on real persisted rows and bytes, with fake vision and video providers. Each step uses the
same service or route the application uses; no step writes the next step's input directly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKey
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository
from lib.generation_queue import GenerationQueue
from r2.contracts.shot_generation import R2ShotGenerationTaskV1
from r2.production_intelligence.shot_profiles import WAN27_TWO_VIEW_PROFILE
from server.services.advanced_creative import exploration_service
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.master_authority import verify_masters
from server.services.spatial_execution import SpatialFrameRef
from server.services.spatial_pair_current_v2 import CurrentApprovedSpatialPairReaderV2
from server.services.spatial_promotion import SpatialPreviewCommand, SpatialPromotionService
from tests.fakes import bind_safe_session_factory
from tests.http_capture import capture_http, request_json
from tests.integration.server.routers.spatial_approval_support import approved_location, distinct_parent_media
from tests.integration.server.routers.test_gates_export import PROJECT, USER, _media
from tests.integration.server.routers.test_r2_shot_worker import SUBMIT_URL, _run
from tests.integration.server.routers.test_spatial_execution import _command, _service, _Vision
from tests.integration.server.routers.test_spatial_promotion import _authorization

type Factory = async_sessionmaker[AsyncSession]

VIDEO = _media(b"m8c-vertical-shot")
VISIBLE_SUBJECTS = ("red fire extinguisher cabinet", "blue exit door")


async def _pair_frames(factory: Factory, project_dir: Path, approved) -> dict[str, SpatialFrameRef]:
    current = await CurrentApprovedSpatialPairReaderV2(
        session_factory=factory, project_dir=project_dir, grants=approved.grants
    ).read_current(user_id=USER.id, project_name=PROJECT, target_id=approved.target_id)
    frames = {}
    async with factory() as session:
        for view in current.body.command.views:
            receipt = await SpatialFrameReceiptRepository(session).get_exact(
                user_id=USER.id, project_name=PROJECT, receipt_id=view.receipt_id
            )
            assert receipt is not None
            frames[view.role] = SpatialFrameRef(receipt_id=view.receipt_id, receipt_digest=view.receipt_digest)
    return frames


async def _snapshot(factory: Factory, project_dir: Path, target_id: str):
    return await CurrentLocationBindingSnapshotReader(session_factory=factory, project_dir=project_dir).read_current(
        user_id=USER.id, project_name=PROJECT, target_id=target_id
    )


def _generate_body(snapshot, command_id: str) -> dict[str, object]:
    return {
        "command_id": command_id,
        "expected_target_registry_version": snapshot.body.target_versions[1].registry_version,
        "expected_binding_snapshot_digest": snapshot.digest,
        "execution_profile_ref": WAN27_TWO_VIEW_PROFILE.profile_ref,
    }


@pytest.mark.asyncio
async def test_an_approved_pair_reaches_an_approved_generated_shot_master(
    gate_export_client: AsyncClient,
    shots_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind_safe_session_factory(monkeypatch, session_factory)

    distinct_parent_media(monkeypatch)
    # 1. A human-reviewed APPROVE of the exact MASTER/REVERSE frames of a LOCATION binding (version 1).
    approved = await approved_location(gate_export_client, project_dir, session_factory, monkeypatch, shot_duration=5.0)
    frames = await _pair_frames(session_factory, project_dir, approved)

    # 2. The bounded vision execution analyzes those frames into one evidence-bound spatial candidate revision.
    vision = _Vision()
    head = await _service(session_factory, project_dir, vision).execute(_command(frames["MASTER"], frames["REVERSE"]))
    assert head.head_version == 1
    assert len(vision.calls) == 1

    # 3. A typed preview selects the VISIBLE assertions; the human authorization promotes binding version 2.
    assertions = await _candidate_assertions(session_factory)
    service = SpatialPromotionService(session_factory=session_factory, project_dir=project_dir, grants=approved.grants)
    preview = await service.create_preview(
        SpatialPreviewCommand(
            user_id=USER.id,
            project_name=PROJECT,
            candidate_id="spatial-candidate-1",
            candidate_revision=1,
            target_id=approved.target_id,
            expected_binding_version=1,
            selected_assertion_ids=tuple(assertions[subject] for subject in VISIBLE_SUBJECTS),
            command_id="spatial-preview-1",
        )
    )
    receipt = await service.promote(
        user_id=USER.id,
        project_name=PROJECT,
        authorization=_authorization(preview),
        expected_candidate_head_version=1,
    )
    assert receipt.result.binding_version == 2
    snapshot = await _snapshot(session_factory, project_dir, approved.target_id)
    assert snapshot.spatial_set is not None

    # 4. The shot route admits the promoted snapshot and queues one task bound to it.
    url = f"/api/v1/projects/{PROJECT}/r2/shots/{approved.target_id}/generate"
    queued = await shots_client.post(url, json=_generate_body(snapshot, "vertical-shot-1"))
    assert queued.status_code == 200, queued.text
    queue = GenerationQueue(session_factory=session_factory)
    monkeypatch.setattr("lib.generation_queue.get_generation_queue", lambda: queue)
    claimed = await queue.claim_next_task("video")
    assert claimed is not None
    evidence = R2ShotGenerationTaskV1.model_validate(claimed["payload"])
    assert evidence.binding_snapshot_digest == snapshot.digest

    # 5. The worker submits the compiled prompt, which carries only the promoted VISIBLE constraints.
    with capture_http() as router, patch("lib.retry.asyncio.sleep", new_callable=AsyncMock):
        submit = router.post(SUBMIT_URL).mock(
            return_value=httpx.Response(200, json={"output": {"task_id": "job-v", "task_status": "PENDING"}})
        )
        router.get("https://dashscope.aliyuncs.com/api/v1/tasks/job-v").mock(
            return_value=httpx.Response(
                200,
                json={
                    "output": {"task_status": "SUCCEEDED", "video_url": "https://x/vertical.mp4"},
                    "usage": {"duration": 5, "output_video_duration": 5},
                },
            )
        )
        router.get("https://x/vertical.mp4").mock(return_value=httpx.Response(200, content=VIDEO))
        result = await _run(evidence, session_factory, project_dir)
    assert submit.call_count == 1
    prompt = request_json(submit.calls[0].request)["input"]["prompt"]
    for subject in VISIBLE_SUBJECTS:
        assert subject in prompt
    assert "hidden corridor" not in prompt
    assert await queue.mark_task_succeeded(evidence.task_id, result) == 1

    # 6. Gate C approves the sealed output as the target's episode-video master.
    approval = await gate_export_client.post(
        f"/api/v1/projects/{PROJECT}/gates/r2-shots/{approved.target_id}",
        json={"task_id": evidence.task_id, "approval_record": "APR-m8c-vertical"},
    )
    assert approval.status_code == 200, approval.text
    key = ArtifactKey.episode_video(1, approved.target_id).encode()
    assert approval.json()["receipt"]["artifact_key"] == key

    # 7. The new master is a verified head that spatial frame sources can read.
    async with session_factory() as session:
        heads = await verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)
    assert (key, 1) in {(artifact_key, version) for artifact_key, version, _candidate in heads}

    # 8. A generation against the pre-promotion snapshot is refused; the stale identity cannot queue.
    stale = await shots_client.post(
        url,
        json=_generate_body(snapshot, "vertical-shot-2") | {"expected_binding_snapshot_digest": "sha256:" + "0" * 64},
    )
    assert stale.status_code == 409


async def _candidate_assertions(factory: Factory) -> dict[str, str]:
    """The subject → assertion ID map of the executed candidate's first revision."""
    async with factory() as session:
        revision = await exploration_service(session).get_exact(
            user_id=USER.id, project_name=PROJECT, candidate_id="spatial-candidate-1", revision=1
        )
    return {
        assertion.subject_refs[0]: assertion.assertion_id
        for assertion in revision.payload.spatial.assertions
        if assertion.subject_refs
    }
