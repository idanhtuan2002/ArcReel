"""M10-B deterministic export through one M7 attempt on real PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import zipfile
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from lib.db.models.host_hardening import ExecutionAttemptModel
from lib.db.models.quality_packaging import ExportReceiptModel
from lib.db.repositories.quality_packaging import ExportRepository
from r2.contracts import packaging as p
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    DispositionStaleError,
    ExportIntegrityFailedError,
    RequiredEvidenceMissingError,
    StaleHeadError,
)
from server import auth
from server.services.package_export import PackageExportService, archive_ref, sweep_partials
from tests.integration.server.services.test_quality_dispositions import issue
from tests.integration.server.services.test_quality_dispositions import request_for as disposition_request
from tests.integration.server.services.test_quality_package_selection import (
    Gate,
    assert_blocked,
    preview,
    preview_request,
    select,
    selection_request,
)
from tests.integration.server.services.test_quality_package_selection import (
    ready_host as ready_host,
)
from tests.integration.server.services.test_quality_packaging import packaging_host as packaging_host
from tests.integration.server.services.test_quality_probes import ACTOR


@pytest.fixture
async def selected_host(ready_host):
    env = ready_host
    env["selection"] = await select(env, selection_request(env, await preview(env)))
    return env


def export_request(env, selection: p.PackageSelection | None = None, *, command_id: str = "export-1"):
    selection = selection or env["selection"]
    body: dict[str, Any] = {
        "command": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "operation": "EXPORT_PACKAGE",
            "command_id": command_id,
            "request_digest": "sha256:" + "0" * 64,
        },
        "subject": {
            "user_id": "default",
            "project_name": "project",
            "actor_id": ACTOR,
            "slot": selection.preview.slot.model_dump(mode="json"),
            "selection_id": selection.selection_id,
            "selection_digest": compute_digest("m10.package-selection.v1", selection),
        },
    }
    body["command"]["request_digest"] = compute_digest("m10.export-request.v1", body)
    return p.ExportRequest.model_validate(body)


def exporter(env, *, token: str | None = "default") -> PackageExportService:
    return PackageExportService(
        sessions=env["factory"],
        grant_reader=env["reader"],
        project_root=env["project"],
        interactive_token=auth.create_token(ACTOR) if token == "default" else token,
    )


def _read(path: str | Path) -> bytes:
    return Path(path).read_bytes()


def _write(path: str | Path, data: bytes) -> None:
    Path(path).write_bytes(data)


async def _attempt_states(env) -> list[str]:
    async with env["factory"]() as session:
        rows = await session.execute(
            sa.select(ExecutionAttemptModel.state).where(ExecutionAttemptModel.task_id.like("m10b-export:%"))
        )
        return sorted(rows.scalars().all())


async def test_a_selected_package_exports_a_verified_archive_and_replays(selected_host) -> None:
    env = selected_host
    request = export_request(env)
    receipt = await exporter(env).export(request)
    assert receipt.status == "EXPORTED"
    archive = env["project"] / archive_ref(receipt.archive_digest)
    data = _read(archive)
    assert receipt.archive_digest == "sha256:" + hashlib.sha256(data).hexdigest()
    assert receipt.archive_byte_size == len(data)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert names == sorted(names, key=str.encode)
        assert {"manifest.json", "metadata/metadata.json", "video/output.mp4"} <= set(names)
        assert bundle.read("video/output.mp4") == _read(env["root"].object_ref)
    assert {e.path for e in receipt.manifest.entries} | {"manifest.json"} == set(names)
    assert await exporter(env).export(request) == receipt
    assert await _attempt_states(env) == ["SUCCEEDED"]


async def test_a_second_command_rebuilds_byte_identical_bytes(selected_host) -> None:
    env = selected_host
    first = await exporter(env).export(export_request(env))
    second = await exporter(env).export(export_request(env, command_id="export-2"))
    assert first.archive_digest == second.archive_digest
    assert first.execution_id != second.execution_id
    assert first.manifest == second.manifest


async def test_only_the_bound_interactive_actor_can_export(selected_host) -> None:
    env = selected_host
    for token in (None, "not-a-token", auth.create_token("someone-else")):
        with pytest.raises(RequiredEvidenceMissingError):
            await exporter(env, token=token).export(export_request(env))
    assert await _attempt_states(env) == []


async def test_a_replaced_selection_is_not_exportable(selected_host) -> None:
    env = selected_host
    old = env["selection"]
    await select(
        env,
        selection_request(env, await preview(env, preview_request(env, command_id="preview-2")), command_id="select-2"),
    )
    with pytest.raises(StaleHeadError):
        await exporter(env).export(export_request(env, old))
    assert await _attempt_states(env) == []


async def test_a_superseded_disposition_is_not_exportable(selected_host) -> None:
    env = selected_host
    await issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1))
    with pytest.raises(DispositionStaleError):
        await exporter(env).export(export_request(env))


async def test_drifted_source_bytes_are_never_exported(selected_host) -> None:
    env = selected_host
    master = env["root"].object_ref
    original = _read(master)
    _write(master, original[:-1] + bytes([original[-1] ^ 0xFF]))
    try:
        with pytest.raises(ExportIntegrityFailedError):
            await exporter(env).export(export_request(env))
    finally:
        _write(master, original)
    assert not list((env["project"] / "exports").glob("*.zip"))


async def test_a_crash_before_finalize_is_completed_by_the_same_command(selected_host, monkeypatch) -> None:
    env = selected_host
    request = export_request(env)
    real = ExportRepository.stage_receipt
    failed = {"once": True}

    async def crash_once(self, **kwargs):
        if failed.pop("once", False):
            raise RuntimeError("crash between acceptance and the receipt")
        return await real(self, **kwargs)

    monkeypatch.setattr(ExportRepository, "stage_receipt", crash_once)
    with pytest.raises(RuntimeError):
        await exporter(env).export(request)
    assert await _attempt_states(env) == ["ACCEPTED"]
    receipt = await exporter(env).export(request)
    assert receipt.status == "EXPORTED"
    assert await _attempt_states(env) == ["SUCCEEDED"]
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(ExportReceiptModel))).scalar_one() == 1


def test_orphaned_partials_and_snapshots_are_swept(tmp_path: Path) -> None:
    store = tmp_path / "exports"
    (store / ".snapshot-abc").mkdir(parents=True)
    (store / ".partial-x.zip").write_bytes(b"x")
    (store / "keep.zip").write_bytes(b"k")
    assert sweep_partials(tmp_path) == 2
    assert [entry.name for entry in store.iterdir()] == ["keep.zip"]


async def test_a_disposition_issued_during_export_prepare_waits_for_it(selected_host, monkeypatch) -> None:
    from server.services import package_export as module

    env = selected_host
    gate = Gate()
    monkeypatch.setattr(module, "readiness_in", gate.wrap(module.readiness_in))
    exporting = asyncio.create_task(exporter(env).export(export_request(env)))
    await asyncio.wait_for(gate.entered.wait(), 30)
    issuing = asyncio.create_task(
        issue(env, disposition_request(env["run"], "REWORK", command_id="decide-2", version=1))
    )
    await assert_blocked(env, gate, "r2_showrunner_grant_heads", "master_authorities")
    assert not issuing.done()
    gate.release.set()
    disposition = await asyncio.wait_for(issuing, 60)
    assert disposition.supersedes_disposition_id == env["disposition"].disposition_id
    # The disposition landed after PLANNED; finalize re-verifies currentness and refuses to receipt the bundle.
    with pytest.raises(DispositionStaleError):
        await asyncio.wait_for(exporting, 120)
    assert await _attempt_states(env) == ["ACCEPTED"]
    async with env["factory"]() as session:
        assert (await session.execute(sa.select(sa.func.count()).select_from(ExportReceiptModel))).scalar_one() == 0


async def test_a_selection_during_export_prepare_waits_and_the_export_still_finalizes(
    selected_host, monkeypatch
) -> None:
    from server.services import package_export as module

    env = selected_host
    replacement = selection_request(
        env, await preview(env, preview_request(env, command_id="preview-2")), command_id="select-2"
    )
    gate = Gate()
    monkeypatch.setattr(module, "readiness_in", gate.wrap(module.readiness_in))
    exporting = asyncio.create_task(exporter(env).export(export_request(env)))
    await asyncio.wait_for(gate.entered.wait(), 30)
    selecting = asyncio.create_task(select(env, replacement))
    await assert_blocked(env, gate, "master_authorities", "r2_showrunner_grant_heads")
    gate.release.set()
    replaced = await asyncio.wait_for(selecting, 60)
    assert replaced.head_version == 2
    # The new selection committed after PLANNED; finalize sees the slot head moved and refuses the receipt.
    with pytest.raises(StaleHeadError):
        await asyncio.wait_for(exporting, 120)
