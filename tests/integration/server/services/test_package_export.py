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
from server.services.package_export import PackageExportService, archive_ref, sweep_work
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


def test_only_unowned_work_directories_are_swept(tmp_path: Path) -> None:
    import fcntl
    import os

    store = tmp_path / "exports"
    for name in (".work-active", ".work-orphan", ".work-creating"):
        (store / name).mkdir(parents=True)
    for name in (".work-active", ".work-orphan"):
        (store / name / "owner.lock").write_bytes(b"")
        (store / name / "archive.partial").write_bytes(b"x")
    (store / "keep.zip").write_bytes(b"k")
    for name in (".work-active", ".work-orphan"):
        os.utime(store / name / "owner.lock", (1, 1))
    (store / ".work-recent").mkdir()
    (store / ".work-recent" / "owner.lock").write_bytes(b"")
    held = os.open(store / ".work-active" / "owner.lock", os.O_RDWR)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        assert sweep_work(tmp_path) == 1
    finally:
        os.close(held)
    assert sorted(entry.name for entry in store.iterdir()) == [
        ".work-active",
        ".work-creating",
        ".work-recent",
        "keep.zip",
    ]


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


async def test_an_exports_link_out_of_the_project_is_refused(selected_host, tmp_path: Path) -> None:
    import os

    env = selected_host
    outside = tmp_path / "outside"
    os.mkdir(outside)
    os.symlink(outside, env["project"] / "exports")
    with pytest.raises(ExportIntegrityFailedError):
        await exporter(env).export(export_request(env))
    assert os.listdir(outside) == []
    assert await _attempt_states(env) == []


@pytest.mark.parametrize("locales", [["en", "EN"], ["metadata"]])
async def test_colliding_metadata_paths_never_overwrite_each_other(ready_host, locales: list[str]) -> None:
    from tests.integration.server.services.test_quality_packaging import append_candidate, candidate_for, check_request
    from tests.integration.server.services.test_quality_packaging import service as check_service

    env = ready_host
    localized = [
        {
            "locale": locale,
            "title": "A history of the river",
            "description": "How the river shaped the valley.",
            "tags": ["history"],
            "hashtags": [],
            "chapters": [],
        }
        for locale in locales
    ]
    candidate = await append_candidate(env, candidate_for(env, localization_variants=localized), revision=2)
    env["candidate"] = candidate
    env["observation"] = await check_service(env).check(check_request(env, candidate, command_id="check-2"))
    env["selection"] = await select(env, selection_request(env, await preview(env)))
    with pytest.raises(ExportIntegrityFailedError):
        await exporter(env).export(export_request(env))
    assert await _attempt_states(env) == []


class ScriptedRuntime:
    """A runtime whose worker reports a fixed status, standing in for a failed or lost confined unit."""

    def __init__(self, status: str) -> None:
        self.status = status
        self.launches = 0

    async def launch(self, payload: bytes, **_: object):
        import json

        from server.services.quality_probe_runtime import WorkerOutcome

        self.launches += 1
        body = json.dumps({"schema": "m10.export-worker-output.v1", "status": self.status, "digest": None}).encode()
        return WorkerOutcome(body, 0, 1, "EXIT_CODE", False, False, True, 1, (0,))


def scripted(env, status: str) -> tuple[PackageExportService, ScriptedRuntime]:
    runtime = ScriptedRuntime(status)
    service = PackageExportService(
        sessions=env["factory"],
        grant_reader=env["reader"],
        project_root=env["project"],
        interactive_token=auth.create_token(ACTOR),
        runtime=runtime,
    )
    return service, runtime


async def test_a_known_worker_refusal_fails_the_attempt_and_leaves_no_scratch(selected_host) -> None:
    import os

    env = selected_host
    service, runtime = scripted(env, "INTEGRITY_FAILED")
    request = export_request(env)
    with pytest.raises(ExportIntegrityFailedError):
        await service.export(request)
    assert await _attempt_states(env) == ["FAILED_BEFORE_ACCEPTANCE"]
    assert os.listdir(env["project"] / "exports") == []
    with pytest.raises(ExportIntegrityFailedError):
        await service.export(request)
    assert runtime.launches == 1


async def test_an_unknown_worker_outcome_is_never_rebuilt_but_a_new_command_recovers(selected_host) -> None:
    env = selected_host
    service, runtime = scripted(env, "WORKER_FAILED")
    request = export_request(env)
    with pytest.raises(RequiredEvidenceMissingError):
        await service.export(request)
    assert await _attempt_states(env) == ["SUBMIT_OUTCOME_UNKNOWN"]
    with pytest.raises(RequiredEvidenceMissingError):
        await service.export(request)
    assert runtime.launches == 1
    receipt = await exporter(env).export(export_request(env, command_id="export-2"))
    assert receipt.status == "EXPORTED"


async def test_a_published_archive_changed_before_finalize_is_refused(selected_host, monkeypatch) -> None:
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
    (archive,) = (env["project"] / "exports").glob("*.zip")
    data = bytearray(_read(archive))
    data[len(data) // 2] ^= 0xFF
    _write(archive, bytes(data))
    with pytest.raises(ExportIntegrityFailedError):
        await exporter(env).export(request)
    assert await _attempt_states(env) == ["ACCEPTED"]


def test_the_worker_refuses_to_build_when_it_is_not_confined(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    from server.services import package_export_worker

    config = {
        "schema": "m10.export-worker-config.v1",
        "envelope": {},
        "read_files": [],
        "exec_files": [],
        "read_dirs": [],
        "scratch": [],
        "members": [],
        "manifest": "/dev/null",
        "output": str(tmp_path / "out"),
    }
    launcher = (
        "import importlib.util as u,sys;s=u.spec_from_file_location('w',sys.argv[1]);"
        "m=u.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);raise SystemExit(m.main())"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", launcher, package_export_worker.__file__],
        input=json.dumps(config).encode(),
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] != "OK"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("role", "variant", "media", "path"),
    [
        ("video", None, "video/mp4", "video/output.mp4"),
        ("thumbnail", "T2", "image/png", "thumbnails/t2.png"),
        ("captions-en", None, "application/x-subrip", "captions/en.srt"),
        ("captions-zh-Hans", None, "application/x-subrip", "captions/zh-hans.srt"),
        ("poster", "a", "image/jpeg", "assets/poster-a.jpg"),
    ],
)
def test_the_bundle_layout_maps_roles_to_fixed_paths(role: str, variant: str | None, media: str, path: str) -> None:
    from server.services.package_export import member_path

    assert member_path(role, variant, media) == path


class SwappingRuntime:
    """Delegates to the real confined runtime after replacing the precreated output with a foreign inode."""

    def __init__(self, real) -> None:
        self.real = real
        self.foreign: Path | None = None

    async def launch(self, payload: bytes, **kwargs):
        import json
        import os

        output = Path(json.loads(payload)["output"])
        os.unlink(output)
        _write(output, b"")
        self.foreign = output
        return await self.real.launch(payload, **kwargs)


async def test_a_swapped_output_inode_is_never_written_by_the_confined_worker(selected_host) -> None:
    from server.services.package_export_worker import __file__ as worker_file
    from server.services.quality_probe_runtime import ProbeHost, QualityProbeRuntime

    env = selected_host
    swapping = SwappingRuntime(QualityProbeRuntime(ProbeHost(tools={}, worker=Path(worker_file))))
    service = PackageExportService(
        sessions=env["factory"],
        grant_reader=env["reader"],
        project_root=env["project"],
        interactive_token=auth.create_token(ACTOR),
        runtime=swapping,
    )
    with pytest.raises(ExportIntegrityFailedError):
        await service.export(export_request(env))
    assert await _attempt_states(env) == ["FAILED_BEFORE_ACCEPTANCE"]
    assert not list((env["project"] / "exports").glob("*.zip"))


class RaisingRuntime:
    async def launch(self, payload: bytes, **_: object):
        raise RuntimeError("supervisor lost the unit")


class UncleanRuntime(ScriptedRuntime):
    async def launch(self, payload: bytes, **kwargs: object):
        import dataclasses

        outcome = await super().launch(payload, **kwargs)
        return dataclasses.replace(outcome, group_cleanup_verified=False)


@pytest.mark.parametrize("runtime", ["raising", "unclean"])
async def test_an_unverified_worker_end_is_unknown_and_keeps_its_scratch(selected_host, runtime: str) -> None:
    env = selected_host
    service = PackageExportService(
        sessions=env["factory"],
        grant_reader=env["reader"],
        project_root=env["project"],
        interactive_token=auth.create_token(ACTOR),
        runtime=RaisingRuntime() if runtime == "raising" else UncleanRuntime("INTEGRITY_FAILED"),
    )
    with pytest.raises(RequiredEvidenceMissingError):
        await service.export(export_request(env))
    assert await _attempt_states(env) == ["SUBMIT_OUTCOME_UNKNOWN"]
    assert [entry.name.startswith(".work-") for entry in (env["project"] / "exports").iterdir()] == [True]


async def test_captions_export_under_their_locale_paths(ready_host) -> None:
    from tests.integration.server.services.test_quality_packaging import append_candidate, candidate_for, check_request
    from tests.integration.server.services.test_quality_packaging import service as check_service

    env = ready_host
    payload = candidate_for(env)
    assets = [payload.assets[0].model_dump(mode="python")]
    for locale, text in (("en", "River"), ("vi", "Dòng sông")):
        data = f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n".encode()
        _write(env["project"] / f"captions-{locale}.srt", data)
        assets.append(
            {
                "role": f"captions-{locale}",
                "variant_id": None,
                "source_ref": f"captions-{locale}.srt",
                "content_digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                "media_type": "application/x-subrip",
                "byte_size": len(data),
                "constraint_rule_id": "asset-thumbnail",
            }
        )
    candidate = await append_candidate(env, candidate_for(env, assets=assets), revision=2)
    env["candidate"] = candidate
    env["observation"] = await check_service(env).check(check_request(env, candidate, command_id="check-2"))
    assert env["observation"].status.value == "PASS", env["observation"].findings
    env["selection"] = await select(env, selection_request(env, await preview(env)))
    receipt = await exporter(env).export(export_request(env))
    with zipfile.ZipFile(env["project"] / archive_ref(receipt.archive_digest)) as bundle:
        assert bundle.read("captions/vi.srt") == _read(env["project"] / "captions-vi.srt")
        assert {"captions/en.srt", "captions/vi.srt"} <= set(bundle.namelist())
    entries = {e.path: e.content_digest for e in receipt.manifest.entries}
    assert (
        entries["captions/en.srt"] == "sha256:" + hashlib.sha256(_read(env["project"] / "captions-en.srt")).hexdigest()
    )


class CancelledRuntime:
    async def launch(self, payload: bytes, **_: object):
        raise asyncio.CancelledError


async def test_a_cancelled_launch_keeps_its_scratch_for_the_sweep(selected_host) -> None:
    env = selected_host
    service = PackageExportService(
        sessions=env["factory"],
        grant_reader=env["reader"],
        project_root=env["project"],
        interactive_token=auth.create_token(ACTOR),
        runtime=CancelledRuntime(),
    )
    with pytest.raises(asyncio.CancelledError):
        await service.export(export_request(env))
    assert [entry.name.startswith(".work-") for entry in (env["project"] / "exports").iterdir()] == [True]


class ForeignBuilderRuntime:
    """Runs the real confined worker but reports it as a builder other than the admitted one."""

    def __init__(self, real) -> None:
        self.real = real

    async def launch(self, payload: bytes, **kwargs):
        import dataclasses
        import json

        outcome = await self.real.launch(payload, **kwargs)
        report = json.loads(outcome.stdout)
        report["worker"] = {"package_export_worker.py": "sha256:" + "0" * 64}
        return dataclasses.replace(outcome, stdout=json.dumps(report).encode())


async def test_a_worker_other_than_the_admitted_builder_is_never_published(selected_host) -> None:
    from server.services.package_export_worker import __file__ as worker_file
    from server.services.quality_probe_runtime import ProbeHost, QualityProbeRuntime

    env = selected_host
    service = PackageExportService(
        sessions=env["factory"],
        grant_reader=env["reader"],
        project_root=env["project"],
        interactive_token=auth.create_token(ACTOR),
        runtime=ForeignBuilderRuntime(QualityProbeRuntime(ProbeHost(tools={}, worker=Path(worker_file)))),
    )
    with pytest.raises(RequiredEvidenceMissingError):
        await service.export(export_request(env))
    assert await _attempt_states(env) == ["SUBMIT_OUTCOME_UNKNOWN"]
    assert not list((env["project"] / "exports").glob("*.zip"))


@pytest.mark.parametrize("column", ["route_json", "request_digest"])
async def test_an_accepted_attempt_bound_to_another_route_or_request_is_not_finalized(
    selected_host, monkeypatch, column: str
) -> None:
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
    value = (
        "jsonb_set(route_json::jsonb, '{backend_model_id}', '\"other\"')::json"
        if column == "route_json"
        else "'sha256:' || repeat('0', 64)"
    )
    async with env["factory"]() as session, session.begin():
        await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            sa.text(f"UPDATE execution_attempts SET {column} = {value} WHERE task_id LIKE 'm10b-export:%'")
        )
    with pytest.raises(RequiredEvidenceMissingError):
        await exporter(env).export(request)


class SecondCallGate(Gate):
    """Pauses only the second call through the seam (export finalize, after prepare)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def wrap(self, real):
        inner = super().wrap(real)

        async def counted(session, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                return await inner(session, *args, **kwargs)
            return await real(session, *args, **kwargs)

        return counted


async def test_a_run_sealed_during_export_finalize_waits_for_it(selected_host, monkeypatch) -> None:
    from server.services import package_export as module
    from tests.integration.server.services.test_quality_runs import completion, human, human_request, seal, technical

    env = selected_host
    probe = await technical(env)
    review = await human(env, human_request(env, command_id="human-2"))
    gate = SecondCallGate()
    monkeypatch.setattr(module, "readiness_in", gate.wrap(module.readiness_in))
    exporting = asyncio.create_task(exporter(env).export(export_request(env)))
    await asyncio.wait_for(gate.entered.wait(), 60)
    sealing = asyncio.create_task(seal(env, completion(env, [probe, review], command_id="seal-2")))
    await assert_blocked(env, gate, "master_authorities", "r2_showrunner_grant_heads")
    assert not sealing.done()
    gate.release.set()
    receipt = await asyncio.wait_for(exporting, 120)
    assert receipt.status == "EXPORTED"
    assert (await asyncio.wait_for(sealing, 60)).run_id != env["run"].run_id
