"""Gate C promotes the database master head and projects the file master (ADR-0096)."""

from __future__ import annotations

import asyncio
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
from r2.host_hardening.master_authority import m7_candidate_id
from r2.m3.host_integration import GoldenAHostIntegration
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
    assert (head.master_version, head.candidate_id) == (1, m7_candidate_id(key, generation_id))
    assert await _count(session_factory, PromotionReceiptModel) == 1
    assert await _count(session_factory, ProjectEventModel) >= 1


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
    assert head.candidate_id == m7_candidate_id(key, generation_id)
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
    def refuse(self, registered):
        raise ValueError("candidate content_fingerprint does not match current semantic state")

    monkeypatch.setattr(GoldenAHostIntegration, "check_approvable", refuse)
    data = _media(b"shot one")
    (project_dir / "production" / "SH01.mp4").write_bytes(data)
    response = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body("SH01", data))

    assert response.status_code == 409
    assert "master_conflict" in response.text
    assert await _count(session_factory, MasterHeadVersionModel) == 0


async def test_a_projection_refused_after_promotion_is_a_conflict_not_a_server_error(
    gate_export_client: AsyncClient, project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self, *args, **kwargs):
        raise ValueError("candidate content_fingerprint does not match current semantic state")

    monkeypatch.setattr(GoldenAHostIntegration, "approve", refuse)
    data = _media(b"shot one")
    (project_dir / "production" / "SH01.mp4").write_bytes(data)
    response = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body("SH01", data))

    assert response.status_code == 409
    assert "master_projection_refused" in response.text


async def test_overlapping_gate_c_approvals_of_one_artifact_end_consistent(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
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
        return await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=body)

    responses = await asyncio.gather(approve(_media(b"shot one")), approve(_media(b"shot one again")))

    assert 200 in [r.status_code for r in responses]
    assert all(r.status_code in (200, 409) for r in responses)
    async with session_factory() as session:
        await verify_masters(session, user_id=USER.id, project_name=PROJECT, project_dir=project_dir)
