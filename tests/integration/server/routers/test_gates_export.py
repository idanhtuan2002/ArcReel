"""The O2a export through the real Gate C/D routes: Gate C approves the composed final, its byte
copy lands in ``output/``, Gate D binds that digest, and the single-file download serves it."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from functools import cache
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKey
from lib.db.repositories.gates import FinalCutReceiptRepository
from lib.version_manager import VersionManager
from server.auth import CurrentUserInfo, create_download_token, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import gates
from tests.auth_deps import AUTH_DEPENDENCIES

type Factory = async_sessionmaker[AsyncSession]

USER = CurrentUserInfo(id="default", sub="operator-1", role="admin")
PROJECT = "demo-project"
BASIS = {"basis_type": "FACTUAL", "basis_version": "v1", "refs": ["research:RP-1"]}


class _FakeProjectManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def get_project_path(self, project_name: str) -> Path:
        path = self.project_root / project_name
        path.mkdir(parents=True, exist_ok=True)
        return path


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    path = tmp_path / "projects" / PROJECT
    (path / "production").mkdir(parents=True)
    return path


@pytest.fixture
async def gate_export_client(monkeypatch: pytest.MonkeyPatch, session_factory: Factory, project_dir: Path):
    monkeypatch.setattr(gates, "async_session_factory", session_factory)
    monkeypatch.setattr(gates, "get_project_manager", lambda: _FakeProjectManager(project_dir.parent))
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.include_router(gates.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    app.include_router(gates.self_auth_router, prefix="/api/v1")
    register_error_handlers(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@cache
def _media(tag: bytes, *, tone: bool = False) -> bytes:
    """A real one-second MP4 whose bytes are unique per ``tag``: silent, or with an audible tone."""
    audio_in = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"] if tone else []
    audio_out = ["-c:a", "aac", "-shortest"] if tone else []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "media.mp4"
        subprocess.run(
            [
                *("ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x36:d=1", *audio_in),
                *("-metadata", f"comment={tag.hex()}", "-c:v", "libx264", "-pix_fmt", "yuv420p", *audio_out, str(out)),
            ],
            check=True,
        )
        return out.read_bytes()


def _body(target_ref: str, data: bytes, **produced: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "method": "DETERMINISTIC",
        "relative_path": f"{target_ref}.mp4",
        "sha256": _sha(data),
        "duration_seconds": 5.0,
        "execution_fingerprint": hashlib.sha256(data + b"exec").hexdigest(),
        "tool": "remotion",
        "tool_version": "4.0.0",
        "wall_time_seconds": 1.0,
        "external_provider_cost": "0",
    }
    fields.update(produced)
    return {
        "resource_type": "videos",
        "episode": 1,
        "target_ref": target_ref,
        "content_fingerprint": hashlib.sha256(target_ref.encode() + data).hexdigest(),
        "content_basis": BASIS,
        "direct_dependencies": [],
        "contract_version": 1,
        "contract_schema_version": "1",
        "produced": fields,
        "approval_record": f"APR-{target_ref}-{hashlib.sha256(data).hexdigest()[:12]}",
    }


async def _approve_shot(gate_export_client: AsyncClient, project_dir: Path, shot: str, data: bytes) -> str:
    (project_dir / "production" / f"{shot}.mp4").write_bytes(data)
    response = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body(shot, data))
    assert response.status_code == 200, response.text
    master = response.json()["approved_master"]
    return f"{shot}:{master['selected_candidate_id']}:{master['host_version_ref']}"


async def _approve_final(
    gate_export_client: AsyncClient, project_dir: Path, data: bytes, sources: list[str], **extra: object
):
    (project_dir / "production" / "FINAL.mp4").write_bytes(data)
    body = _body("FINAL", data, method="COMPOSITE", tool="ffmpeg", tool_version="ffmpeg 7", source_master_refs=sources)
    body["audio_decision"] = "MUTE"
    body.update(extra)
    return await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=body)


async def _publish(gate_export_client: AsyncClient, digest: str, action: str = "APPROVE_PUBLISH"):
    return await gate_export_client.post(
        f"/api/v1/projects/{PROJECT}/gates/publish-approval",
        json={"deliverable_digest": digest, "platform": "youtube", "visibility": "unlisted", "action": action},
    )


async def _download(gate_export_client: AsyncClient, digest: str, token: str | None = None):
    token = token or create_download_token(USER.sub, PROJECT)
    return await gate_export_client.get(
        f"/api/v1/projects/{PROJECT}/export/deliverable", params={"download_token": token, "digest": digest}
    )


async def test_an_approved_composite_final_is_exported_bound_at_gate_d_and_downloadable(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, s, s.encode() * 64) for s in ("SH01", "SH02")]
    final = _media(b"composed final cut bytes" * 32)

    approved = await _approve_final(gate_export_client, project_dir, final, sources)

    assert approved.status_code == 200, approved.text
    export = approved.json()["export"]
    assert export == {"relative_path": "output/ep1-FINAL.mp4", "sha256": _sha(final)}
    assert (project_dir / export["relative_path"]).read_bytes() == final

    listing = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/export/deliverable/token")
    assert listing.status_code == 200
    assert listing.json()["deliverables"] == [{"episode": 1, "target_ref": "FINAL", "sha256": _sha(final)}]

    downloaded = await _download(gate_export_client, _sha(final), listing.json()["download_token"])
    assert downloaded.status_code == 200
    assert downloaded.content == final
    assert downloaded.headers["x-content-sha256"] == _sha(final)

    assert (await _publish(gate_export_client, _sha(final))).status_code == 200
    assert (await _publish(gate_export_client, _sha(b"something else"))).status_code == 409


async def test_gate_c_refuses_a_file_whose_bytes_do_not_match_the_claimed_digest(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    (project_dir / "production" / "SH01.mp4").write_bytes(b"real bytes")

    response = await gate_export_client.post(
        f"/api/v1/projects/{PROJECT}/gates/final-cut", json=_body("SH01", b"real bytes", sha256=_sha(b"other"))
    )

    assert response.status_code == 400
    assert "sha256" in response.json()["detail"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_ref", "/tmp/V1O2A_ESCAPE"),
        ("target_ref", "../../escape"),
        ("target_ref", "SH:01"),
        ("resource_type", "audio"),
    ],
)
async def test_gate_c_rejects_unsafe_target_or_resource_type_before_writing(
    gate_export_client: AsyncClient, project_dir: Path, field: str, value: str
) -> None:
    (project_dir / "production" / "FINAL.mp4").write_bytes(b"final")
    body = _body("FINAL", b"final")
    body[field] = value
    response = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=body)

    assert response.status_code == 422
    assert not (project_dir / ".arcreel_artifacts.json").exists()
    assert not (project_dir / "r2_m3_current").exists()


async def test_a_composite_final_takes_its_dependencies_from_its_masters_not_the_caller(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    forged = [{"ref": "artifact:SH01", "version": "1", "fingerprint": "f" * 64}]

    response = await _approve_final(
        gate_export_client, project_dir, _media(b"final"), sources, direct_dependencies=forged
    )

    assert response.status_code == 400


@pytest.mark.parametrize("source", ["SH01:CAND-SH01-V9:9", "SH09:CAND-SH09-V1:1", "garbage"])
async def test_a_composite_final_must_name_current_approved_masters(
    gate_export_client: AsyncClient, project_dir: Path, source: str
) -> None:
    await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")

    response = await _approve_final(gate_export_client, project_dir, _media(b"final"), [source])

    assert response.status_code == 409
    assert not (project_dir / "output").exists()


async def test_a_tampered_shot_master_cannot_authorize_a_composite_final(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    source = await _approve_shot(gate_export_client, project_dir, "SH01", b"approved shot")
    (project_dir / "r2_m3_current" / "SH01.mp4").write_bytes(b"unapproved shot")

    response = await _approve_final(gate_export_client, project_dir, _media(b"final"), [source])

    assert response.status_code == 409
    assert not (project_dir / "output").exists()


async def test_a_reapproved_shot_master_makes_the_final_stale_so_it_cannot_be_published_or_downloaded(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one v1")]
    final = _media(b"final from v1")
    assert (await _approve_final(gate_export_client, project_dir, final, sources)).status_code == 200

    await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one v2")

    listing = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/export/deliverable/token")
    assert listing.json()["deliverables"] == []
    assert (await _publish(gate_export_client, _sha(final))).status_code == 409
    assert (await _download(gate_export_client, _sha(final))).status_code == 404
    assert (await _publish(gate_export_client, _sha(final), action="REVOKE")).status_code == 200


async def test_a_tampered_export_copy_is_neither_publishable_nor_served(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    final = _media(b"approved final")
    assert (await _approve_final(gate_export_client, project_dir, final, sources)).status_code == 200

    (project_dir / "output" / "ep1-FINAL.mp4").write_bytes(b"swapped by another tool")

    assert (await _publish(gate_export_client, _sha(final))).status_code == 409
    assert (await _publish(gate_export_client, _sha(b"swapped by another tool"))).status_code == 409
    assert (await _download(gate_export_client, _sha(final))).status_code == 404


async def test_the_download_needs_a_valid_token_for_this_project(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    final = _media(b"approved final")
    assert (await _approve_final(gate_export_client, project_dir, final, sources)).status_code == 200

    assert (await _download(gate_export_client, _sha(final), token="not-a-token")).status_code == 401
    other = create_download_token(USER.sub, "other-project")
    assert (await _download(gate_export_client, _sha(final), token=other)).status_code == 403


async def test_retry_after_export_failure_reuses_the_approved_version_and_receipt(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    original = gates.write_export_copy
    calls = 0

    def fail_once(host, target_ref):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected export failure")
        return original(host, target_ref)

    monkeypatch.setattr(gates, "write_export_copy", fail_once)
    first = await _approve_final(gate_export_client, project_dir, _media(b"final"), sources)
    assert first.status_code == 503
    assert first.json()["detail"]["code"] == "GATE_C_RETRY_SAME_APPROVAL_RECORD"

    second = await _approve_final(gate_export_client, project_dir, _media(b"final"), sources)
    assert second.status_code == 200, second.text
    assert len(VersionManager(project_dir).get_versions("videos", "FINAL")["versions"]) == 1
    async with session_factory() as session:
        receipts = await FinalCutReceiptRepository(session).list_for_artifact(
            user_id=USER.id,
            project_name=PROJECT,
            artifact_key=ArtifactKey.episode_video(1, "FINAL").encode(),
        )
    assert len(receipts) == 1


async def test_retry_after_receipt_failure_and_duplicate_success_are_idempotent(
    gate_export_client: AsyncClient,
    project_dir: Path,
    session_factory: Factory,
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    calls = 0

    def fail_once(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal calls
        if "INSERT INTO gate_final_cut_receipts" in statement:
            calls += 1
        if calls == 1 and "INSERT INTO gate_final_cut_receipts" in statement:
            raise OSError("injected receipt failure")

    engine = session_factory.kw["bind"]
    event.listen(engine.sync_engine, "before_cursor_execute", fail_once)
    try:
        first = await _approve_final(gate_export_client, project_dir, _media(b"final"), sources)
        assert first.status_code == 503
        assert first.json()["detail"]["code"] == "GATE_C_RETRY_SAME_APPROVAL_RECORD"
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_once)

    second = await _approve_final(gate_export_client, project_dir, _media(b"final"), sources)
    third = await _approve_final(gate_export_client, project_dir, _media(b"final"), sources)
    assert second.status_code == 200, second.text
    assert third.status_code == 200, third.text
    assert len(VersionManager(project_dir).get_versions("videos", "FINAL")["versions"]) == 1
    async with session_factory() as session:
        receipts = await FinalCutReceiptRepository(session).list_for_artifact(
            user_id=USER.id,
            project_name=PROJECT,
            artifact_key=ArtifactKey.episode_video(1, "FINAL").encode(),
        )
    assert len(receipts) == 1


async def test_reusing_approval_record_for_changed_final_is_rejected(
    gate_export_client: AsyncClient, project_dir: Path
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    assert (await _approve_final(gate_export_client, project_dir, _media(b"final v1"), sources)).status_code == 200
    previous_record = _body("FINAL", _media(b"final v1"))["approval_record"]
    response = await _approve_final(
        gate_export_client, project_dir, _media(b"final v2"), sources, approval_record=previous_record
    )
    assert response.status_code == 409
    assert len(VersionManager(project_dir).get_versions("videos", "FINAL")["versions"]) == 1


async def test_a_composite_final_needs_an_audio_decision_that_matches_its_track(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory
) -> None:
    sources = [await _approve_shot(gate_export_client, project_dir, "SH01", b"shot one")]
    silent, toned = _media(b"silent final"), _media(b"toned final", tone=True)

    missing = await _approve_final(gate_export_client, project_dir, silent, sources, audio_decision=None)
    muted_but_audible = await _approve_final(gate_export_client, project_dir, toned, sources, audio_decision="MUTE")
    audible_but_silent = await _approve_final(gate_export_client, project_dir, silent, sources, audio_decision="AUDIO")
    not_media = await _approve_final(gate_export_client, project_dir, b"not a video", sources)
    approved = await _approve_final(gate_export_client, project_dir, toned, sources, audio_decision="AUDIO")

    assert [r.status_code for r in (missing, muted_but_audible, audible_but_silent, not_media)] == [400] * 4
    assert approved.status_code == 200, approved.text
    assert approved.json()["receipt"]["audio_decision"] == "AUDIO"
    async with session_factory() as session:
        [receipt] = await FinalCutReceiptRepository(session).list_for_artifact(
            user_id=USER.id, project_name=PROJECT, artifact_key=ArtifactKey.episode_video(1, "FINAL").encode()
        )
    assert receipt.audio_decision == "AUDIO"


async def test_a_shot_approval_carries_no_audio_decision(gate_export_client: AsyncClient, project_dir: Path) -> None:
    (project_dir / "production" / "SH01.mp4").write_bytes(b"shot")
    body = _body("SH01", b"shot")
    body["audio_decision"] = "MUTE"

    response = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/final-cut", json=body)

    assert response.status_code == 400


async def test_a_factual_script_lock_is_recorded_in_the_gate_history(gate_export_client: AsyncClient) -> None:
    body = {"source_digest": "sha256:" + "a" * 64, "script_digest": "sha256:" + "b" * 64, "action": "LOCK"}

    locked = await gate_export_client.post(f"/api/v1/projects/{PROJECT}/gates/script-lock", json=body)
    revoked = await gate_export_client.post(
        f"/api/v1/projects/{PROJECT}/gates/script-lock", json={**body, "action": "REVOKE"}
    )
    history = (await gate_export_client.get(f"/api/v1/projects/{PROJECT}/gates")).json()["script_lock"]

    assert (locked.status_code, revoked.status_code) == (200, 200)
    assert [(d["action"], d["sequence"], d["script_digest"]) for d in history] == [
        ("LOCK", 1, body["script_digest"]),
        ("REVOKE", 2, body["script_digest"]),
    ]
    assert history[0]["authorization"]["authenticated_principal"] == USER.sub
