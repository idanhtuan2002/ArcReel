"""Gate C promotes the database master head and projects the file master (ADR-0096)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import hashlib
import subprocess
import time
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.host_hardening import MasterHeadVersionModel, ProjectEventModel, PromotionReceiptModel
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from r2.host_hardening.master_authority import scoped_m7_candidate_id
from r2.m3.host_integration import GoldenAHostIntegration
from server.routers import gates
from server.services.master_authority import master_authority_unit, projected_masters, verify_masters
from tests.integration.server.routers.test_gates_export import (
    PROJECT,
    USER,
    _approve_final,
    _approve_shot,
    _body,
    _download,
    _media,
    _publish,
    _sha,
)

type Factory = async_sessionmaker[AsyncSession]


def _rogue_version(project_dir: Path) -> Path:
    other = project_dir / "videos" / "versions" / "SH01_rogue.mp4"
    other.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=64x36:d=0.2", "-y", str(other)], check=True
    )
    return other.resolve()


async def _count(factory: Factory, model) -> int:
    async with factory() as session:
        return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def _database_head(factory: Factory, artifact_key: str):
    async with factory() as session:
        return await MasterAuthorityRepository(session).get_current(
            user_id=USER.id, project_name=PROJECT, artifact_key=artifact_key
        )


async def test_gate_c_writes_the_database_head_and_its_projection(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")

    projected = projected_masters(project_dir)
    ((key, generation_id),) = projected.items()
    head = await _database_head(session_factory, key)
    assert head is not None
    assert (head.master_version, head.candidate_id) == (1, scoped_m7_candidate_id(USER.id, PROJECT, key, generation_id))
    assert await _count(session_factory, PromotionReceiptModel) == 1
    assert await _count(session_factory, ProjectEventModel) >= 1


async def test_two_gate_c_video_masters_have_distinct_current_heads(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    first = await _approve_shot(gate_export_client, project_dir, "SH01", b"video parent one")
    second = await _approve_shot(gate_export_client, project_dir, "SH02", b"video parent two")

    keys = {
        shot: GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
        for shot in ("SH01", "SH02")
    }
    projected = projected_masters(project_dir)
    assert set(projected) == set(keys.values())
    heads = {shot: await _database_head(session_factory, key) for shot, key in keys.items()}
    for shot, head in heads.items():
        assert head is not None
        assert head.master_version == 1
        assert head.candidate_id == scoped_m7_candidate_id(USER.id, PROJECT, keys[shot], projected[keys[shot]])
    assert heads["SH01"].content_digest != heads["SH02"].content_digest
    assert first != second
    async with session_factory() as session:
        await verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)

    await _approve_shot(gate_export_client, project_dir, "SH01", b"video parent one replaced")
    latest_first = await _database_head(session_factory, keys["SH01"])
    latest_second = await _database_head(session_factory, keys["SH02"])
    assert latest_first is not None
    assert latest_second is not None
    assert latest_first.master_version == 2
    assert latest_first.candidate_id != heads["SH01"].candidate_id
    assert latest_second == heads["SH02"]
    async with session_factory() as session:
        await verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)


async def test_a_retry_after_a_failed_projection_converges(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_approve = GoldenAHostIntegration.approve
    calls = {"n": 0}

    def flaky_approve(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("manifest write failed")
        return real_approve(self, *args, **kwargs)

    monkeypatch.setattr(GoldenAHostIntegration, "approve", flaky_approve)
    with pytest.raises(OSError, match="manifest write failed"):
        await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")
    assert projected_masters(project_dir) == {}

    await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")

    ((key, generation_id),) = projected_masters(project_dir).items()
    head = await _database_head(session_factory, key)
    assert head is not None
    assert head.candidate_id == scoped_m7_candidate_id(USER.id, PROJECT, key, generation_id)
    assert await _count(session_factory, MasterHeadVersionModel) == 1


async def test_a_diverged_master_is_refused_by_every_consuming_route(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    final = _media(b"approved final")
    assert (await _approve_final(gate_export_client, project_dir, final, sources)).status_code == 200
    export_digest = _sha(final)
    listing = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/export/deliverable/token")
    issued_token = listing.json()["download_token"]

    # Another writer moves the SH01 head without projecting it.
    shot_key = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for("SH01")
    assert shot_key in projected_masters(project_dir)
    other = await asyncio.to_thread(_rogue_version, project_dir)
    root = await asyncio.to_thread(project_dir.resolve)
    async with session_factory() as session:
        await master_authority_unit(session).promote_staged(
            user_id=USER.id,
            project_name=PROJECT,
            project_dir=root,
            artifact_key=shot_key,
            generation_candidate_id="CAND-SH01-V99",
            version_file=other,
            expected_content_digest=_sha(await asyncio.to_thread(other.read_bytes)),
            approval_record="APR-rogue",
            command_id="rogue",
        )

    publish = await _publish(gate_export_client, export_digest)
    token = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/export/deliverable/token")
    download = await _download(gate_export_client, export_digest, issued_token)
    composite = await _approve_final(gate_export_client, project_dir, _media(b"another final"), sources)

    for response in (publish, token, download, composite):
        assert response.status_code == 409, response.text
        assert "master_diverged" in response.text


async def test_a_refused_projection_check_writes_no_database_head(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self, registered, semantic_state=None):
        raise ValueError("candidate content_fingerprint does not match current semantic state")

    monkeypatch.setattr(GoldenAHostIntegration, "check_approvable", refuse)
    data = _media(b"shot one")
    (project_dir / "production" / "SH01.mp4").write_bytes(data)
    response = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body("SH01", data))

    assert response.status_code == 409
    assert "master_conflict" in response.text
    assert await _count(session_factory, MasterHeadVersionModel) == 0


async def test_a_projection_refused_after_the_commit_asks_for_a_retry_that_converges(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_approve = GoldenAHostIntegration.approve
    calls = {"n": 0}

    def refuse_once(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("candidate content_fingerprint does not match current semantic state")
        return real_approve(self, *args, **kwargs)

    monkeypatch.setattr(GoldenAHostIntegration, "approve", refuse_once)
    data = _media(b"shot one")
    (project_dir / "production" / "SH01.mp4").write_bytes(data)
    body = _body("SH01", data)

    refused = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=body)
    retried = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=body)

    assert refused.status_code == 503
    assert "GATE_C_RETRY_SAME_APPROVAL_RECORD" in refused.text
    assert retried.status_code == 200, retried.text
    assert await _count(session_factory, MasterHeadVersionModel) == 1
    async with session_factory() as session:
        await verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)


async def test_an_approval_superseded_before_its_projection_writes_nothing(
    concurrent_gate_client: AsyncClient,
    project_dir: Path,
    concurrent_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [await _approve_shot(concurrent_gate_client, project_dir, "SH01", b"shot one")]
    older, newer = _media(b"older final"), _media(b"newer final")
    real_project_if_current = gates.project_if_current
    injected = {"done": False}

    async def newer_approval_first(*args, **kwargs):
        # Between the older approval's promotion and its projection, a newer one runs completely.
        if not injected["done"] and (project_dir / "production" / "FINAL.mp4").read_bytes() == older:
            injected["done"] = True
            response = await _approve_final(concurrent_gate_client, project_dir, newer, sources)
            assert response.status_code == 200, response.text
        return await real_project_if_current(*args, **kwargs)

    monkeypatch.setattr(gates, "project_if_current", newer_approval_first)

    stale = await _approve_final(concurrent_gate_client, project_dir, older, sources)

    assert injected["done"]
    assert stale.status_code == 409
    assert "master_superseded" in stale.text
    assert (project_dir / "output" / "ep1-FINAL.mp4").read_bytes() == newer
    async with concurrent_session_factory() as session:
        await verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)


async def test_overlapping_gate_c_approvals_of_one_artifact_end_consistent(
    concurrent_gate_client: AsyncClient,
    project_dir: Path,
    concurrent_session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_stage = GoldenAHostIntegration.stage_candidate

    def slow_stage(self, *args, **kwargs):
        time.sleep(0.2)
        return real_stage(self, *args, **kwargs)

    monkeypatch.setattr(GoldenAHostIntegration, "stage_candidate", slow_stage)

    async def approve(data: bytes):
        name = f"SH01-{hashlib.sha256(data).hexdigest()[:8]}.mp4"
        (project_dir / "production" / name).write_bytes(data)
        body = _body("SH01", data)
        produced = body["produced"]
        assert isinstance(produced, dict)
        produced["relative_path"] = name
        return await concurrent_gate_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=body)

    for round_ in range(3):
        responses = await asyncio.gather(
            approve(_media(b"shot one %d" % round_)), approve(_media(b"shot one again %d" % round_))
        )

        # The newest promotion wins; an approval superseded before its projection writes nothing.
        # Either way the database head and its projection agree.
        assert 200 in [r.status_code for r in responses], [r.text for r in responses]
        for response in responses:
            assert response.status_code == 200 or (
                response.status_code == 409 and "master_superseded" in response.text
            ), response.text
        async with concurrent_session_factory() as session:
            await verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)


async def test_a_final_whose_promotion_fails_after_staging_leaves_the_old_final_stale(
    gate_export_client: AsyncClient, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from r2.host_hardening.master_authority import MasterAuthorityUnit

    old_sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one v1")]
    old_final = _media(b"final from v1")
    assert (await _approve_final(gate_export_client, project_dir, old_final, old_sources)).status_code == 200
    new_sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one v2")]
    assert (await _publish(gate_export_client, _sha(old_final))).status_code == 409  # stale after v2

    real_promote = MasterAuthorityUnit.promote_staged

    async def fail_final(self, **kwargs):
        if kwargs["generation_candidate_id"].startswith("CAND-FINAL-"):
            raise RuntimeError("database unavailable")
        return await real_promote(self, **kwargs)

    monkeypatch.setattr(MasterAuthorityUnit, "promote_staged", fail_final)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await _approve_final(gate_export_client, project_dir, _media(b"final from v2"), new_sources)

    # The failed stage did not make the old final look current against the new shot master.
    assert (await _publish(gate_export_client, _sha(old_final))).status_code == 409


async def test_no_manifest_write_pairs_the_old_master_with_the_new_semantic_state(
    gate_export_client: AsyncClient, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lib.artifact_manifest import ProjectArtifactManifestAdapter

    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one v1")]
    first = await _approve_final(gate_export_client, project_dir, _media(b"final one"), sources)
    assert first.status_code == 200
    old_master = first.json()["approved_master"]["selected_candidate_id"]
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one v2")]
    written: list[dict] = []
    real_replace = ProjectArtifactManifestAdapter.replace_entries_if_matches_atomically

    def record(self, *, expected, replacements):
        written.extend(entry.r2 for entry in replacements.values() if entry.r2 is not None)
        return real_replace(self, expected=expected, replacements=replacements)

    monkeypatch.setattr(ProjectArtifactManifestAdapter, "replace_entries_if_matches_atomically", record)
    new_final = _media(b"final two")
    second = await _approve_final(gate_export_client, project_dir, new_final, sources)

    assert second.status_code == 200, second.text
    new_fingerprint = _body("FINAL", new_final)["content_fingerprint"]
    assert written
    for metadata in written:
        approved = metadata.get("approved_master") or {}
        assert not (
            approved.get("selected_candidate_id") == old_master and metadata["content_fingerprint"] == new_fingerprint
        ), metadata


async def test_a_head_committed_while_gate_d_reads_refuses_the_decision(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lib.db.models.gates import PublishApprovalDecisionModel

    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    final = _media(b"approved final")
    assert (await _approve_final(gate_export_client, project_dir, final, sources)).status_code == 200
    loop = asyncio.get_running_loop()
    real_read = gates.exportable_deliverable

    def read_while_an_approval_lands(*args, **kwargs):
        # The read sees the final as current; a complete, consistent Gate C approval of its source
        # shot lands before the read returns.
        deliverable = real_read(*args, **kwargs)
        future = asyncio.run_coroutine_threadsafe(
            _approve_shot(gate_export_client, project_dir, "SH01", b"shot one again"), loop
        )
        future.result(timeout=60)
        return deliverable

    monkeypatch.setattr(gates, "exportable_deliverable", read_while_an_approval_lands)

    response = await _publish(gate_export_client, _sha(final))

    assert response.status_code == 409, response.text
    assert "master_moving" in response.text
    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(PublishApprovalDecisionModel))).scalar_one()
    assert count == 0


async def test_a_head_committed_after_gate_d_read_refuses_the_decision(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lib.db.models.gates import PublishApprovalDecisionModel

    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    final = _media(b"approved final")
    assert (await _approve_final(gate_export_client, project_dir, final, sources)).status_code == 200
    real_serialized = gates.serialized_artifacts
    injected = {"done": False}

    def approval_lands_before_the_decision_lock(*args, **kwargs):
        @contextlib.asynccontextmanager
        async def locked():
            if not injected["done"]:
                # Both reads agreed; a consistent Gate C of the source shot commits first.
                injected["done"] = True
                await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one again")
            async with real_serialized(*args, **kwargs) as session:
                yield session

        return locked()

    monkeypatch.setattr(gates, "serialized_artifacts", approval_lands_before_the_decision_lock)

    response = await _publish(gate_export_client, _sha(final))

    assert response.status_code == 409, response.text
    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(PublishApprovalDecisionModel))).scalar_one()
    assert count == 0


async def test_a_composite_holds_its_source_shots_while_it_stages_and_promotes(
    concurrent_gate_client: AsyncClient, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On PostgreSQL this proves the source row lock; SQLite's write lock covers the whole database.
    sources = [await _approve_shot(concurrent_gate_client, project_dir, "SH01", b"shot one")]
    loop = asyncio.get_running_loop()
    real_stage = GoldenAHostIntegration.stage_candidate
    order: list[str] = []
    shot_approval: dict[str, object] = {}

    def stage(self, **kwargs):
        if kwargs["target_ref"] == "FINAL" and "started" not in shot_approval:
            # While the final stages, a Gate C of its source shot starts and must wait for it.
            shot_approval["started"] = asyncio.run_coroutine_threadsafe(
                _approve_shot(concurrent_gate_client, project_dir, "SH01", b"shot one again"), loop
            )
            time.sleep(1.5)
            started = shot_approval["started"]
            assert isinstance(started, concurrent.futures.Future)
            order.append("shot-still-waiting" if not started.done() else "shot-finished-early")
        return real_stage(self, **kwargs)

    monkeypatch.setattr(GoldenAHostIntegration, "stage_candidate", stage)

    final = await _approve_final(concurrent_gate_client, project_dir, _media(b"final"), sources)
    order.append("final-done")
    started = shot_approval["started"]
    assert isinstance(started, concurrent.futures.Future)
    await asyncio.wrap_future(started)

    assert final.status_code == 200, final.text
    assert order == ["shot-still-waiting", "final-done"]


async def test_a_second_project_of_the_same_user_approves_the_same_shot(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"first project")
    other = project_dir.parent / "second-project"
    (other / "production").mkdir(parents=True)
    data = _media(b"second project")
    (other / "production" / "SH01.mp4").write_bytes(data)

    response = await gate_export_client.post("/api/v1/projects/second-project/gates/final-cut", json=_body("SH01", data))

    assert response.status_code == 200, response.text
    key, generation_id = next(iter(projected_masters(other).items()))
    async with session_factory() as session:
        head = await MasterAuthorityRepository(session).get_current(
            user_id=USER.id, project_name="second-project", artifact_key=key
        )
    assert head is not None
    assert head.candidate_id == scoped_m7_candidate_id(USER.id, "second-project", key, generation_id)
    assert head.candidate_id != (await _database_head(session_factory, key)).candidate_id
