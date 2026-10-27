"""Real systemd/cgroup/Landlock/seccomp confinement of the probe worker on the qualification host.

Each case starts an owned transient user service. Hostile cases load the real worker module, register an
attack as the recipe, and let the real `main` confine itself first; the attack then reports what the kernel
allowed. These cases must execute on the qualification host; they are not skipped when isolation is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from r2.quality.errors import OperationalEnvelopeExceededError, ProbeFailedError, RequiredEvidenceMissingError
from server.services import quality_probe_runtime as runtime
from server.services.quality_probe_inputs import snapshot_probe_inputs
from tests.unit.server.services.test_quality_probe_inputs import bound_request, catalog

WORKER = Path(runtime.__file__).with_name("quality_probe_worker.py")
TOOLS = {"ffmpeg": Path("/usr/bin/ffmpeg"), "ffprobe": Path("/usr/bin/ffprobe")}
HOSTILE = """\
import ctypes, importlib.util, json, os, signal, socket, subprocess, sys, time
spec = importlib.util.spec_from_file_location("m10_real_probe_worker", {worker!r})
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
def _links():
    found = []
    for name in os.listdir("/proc/self/fd"):
        try:
            found.append(os.readlink("/proc/self/fd/" + name)) if int(name) > 2 else None
        except FileNotFoundError:
            pass
    return sorted(found)
BEFORE = {{"env": sorted(os.environ), "fds": _links()}}
def attack(config, deadline):
{body}
for kind in ("CONTAINER_STREAM", "DECODE", "INTERVALS", "LOUDNESS", "CAPTIONS", "REFERENCE_VMAF"):
    m.RECIPES[kind] = attack
raise SystemExit(m.main())
"""


def alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def tool(name: str) -> dict[str, object]:
    path = TOOLS[name]
    output = subprocess.run(
        [str(path), "-version"], capture_output=True, env={"LC_ALL": "C", "TZ": "UTC"}, check=True, timeout=10
    ).stdout
    version = re.search(rb"version (\d+\.\d+\.\d+)", output)
    assert version is not None
    return {
        "name": name,
        "version": version.group(1).decode(),
        "executable_digest": sha(path.read_bytes()),
        "build_digest": sha(output),
        "model_digest": None,
    }


def real_config(**changes: object):
    from r2.quality.probes import ProbeConfig
    from tests.unit.r2.quality.test_probes import config_data

    data = config_data()
    data["tools"] = [tool("ffmpeg"), tool("ffprobe")]
    data.update(changes)
    return ProbeConfig.model_validate(data)


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    root.mkdir(mode=0o700)
    master = root / "master.mp4"
    master.write_bytes(b"master-bytes-for-isolation")
    return (root, master)


def hostile(tmp_path: Path, body: str) -> Path:
    script = tmp_path / f"hostile-{time.monotonic_ns()}.py"
    script.write_text(HOSTILE.format(worker=str(WORKER), body=textwrap.indent(textwrap.dedent(body), "    ")))
    return script


async def launch(project: tuple[Path, Path], script: Path, config=None) -> tuple[runtime.WorkerOutcome, dict]:
    root, master = project
    config = config or real_config()
    _, request = bound_request(config, master)
    probe = runtime.QualityProbeRuntime(runtime.ProbeHost(tools=TOOLS, worker=script))
    async with snapshot_probe_inputs(request, project_root=root, catalog=catalog(config)) as inputs:
        with runtime.scratch_files() as scratch:
            payload = json.dumps(probe.worker_config(request, inputs, config, scratch)).encode()
            outcome = await probe.launch(payload, budget_ms=config.max_runtime_ms, output_cap=1048576, scratch=scratch)
    if outcome.output_exceeded or not outcome.stdout.endswith(b"\n"):
        return (outcome, {})
    return (outcome, json.loads(outcome.stdout.splitlines()[-1]))


async def run(project: tuple[Path, Path], script: Path | None, config=None):
    root, master = project
    config = config or real_config()
    _, request = bound_request(config, master)
    probe = runtime.QualityProbeRuntime(runtime.ProbeHost(tools=TOOLS, worker=script))
    async with snapshot_probe_inputs(request, project_root=root, catalog=catalog(config)) as inputs:
        return await probe.run(request, inputs, config)


DECODED = 'return {"kind": "DECODE", "stream_indices": [0], "complete": True}'


async def test_confined_recipe_returns_a_bounded_verified_execution_result(project, tmp_path: Path) -> None:
    result = await run(project, hostile(tmp_path, DECODED))
    assert result.measurement.status == "PASS"
    assert result.measurement.input_digests == (sha(project[1].read_bytes()),)
    resources = result.resources
    assert (resources.memory_max_bytes, resources.swap_max_bytes, resources.tasks_max) == (536870912, 0, 32)
    assert (resources.cpu_quota_us, resources.cpu_period_us) == (100000, 100000)
    assert resources.group_cleanup_verified
    assert resources.manager_result == "SUCCESS"
    assert resources.peak_memory_bytes is not None
    assert 0 < resources.peak_memory_bytes <= 536870912
    assert resources.peak_tasks is not None
    assert resources.scratch_sizes == (0, 0, 0)


async def test_unchanged_real_worker_verifies_tools_then_refuses_non_media_input(project) -> None:
    outcome, report = await launch(project, WORKER)
    assert report["status"] == "INPUT_INVALID"
    assert report["landlock_abi"] >= 6
    assert report["envelope"] == {
        "memory_max": 536870912,
        "swap_max": 0,
        "tasks_max": 32,
        "cpu_quota_us": 100000,
        "cpu_period_us": 100000,
    }
    assert outcome.group_cleanup_verified
    with pytest.raises(ProbeFailedError):
        await run(project, None)


async def test_changed_tool_build_output_is_unqualified_under_confinement(project, tmp_path: Path) -> None:
    changed = [tool("ffmpeg") | {"build_digest": sha(b"other build")}, tool("ffprobe")]
    config = real_config(tools=changed)
    _, report = await launch(project, hostile(tmp_path, DECODED), config)
    assert report["status"] == "TOOL_UNQUALIFIED"
    assert report["facts"] is None
    with pytest.raises(RequiredEvidenceMissingError):
        await run(project, hostile(tmp_path, DECODED), config)


@pytest.fixture
def protected():
    process = subprocess.Popen(["/usr/bin/sleep", "30"])
    yield process
    process.terminate()
    process.wait(timeout=5)


async def test_escape_network_signal_and_process_memory_attempts_are_denied(
    project, tmp_path: Path, monkeypatch, protected
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("host secret")
    writable = tmp_path / "writable.txt"
    writable.write_text("unchanged")
    monkeypatch.setenv("M10_DATABASE_URL", "postgresql://secret")
    inherited = os.open(secret, os.O_RDONLY)
    os.set_inheritable(inherited, True)
    body = f"""
    r = {{"before": BEFORE, "env_after": sorted(os.environ)}}
    def attempt(name, action):
        try:
            action()
            r[name] = "allowed"
        except OSError as error:
            r[name] = error.errno
    attempt("read_outside", lambda: open({str(secret)!r}, "rb").read())
    attempt("write_outside", lambda: open({str(writable)!r}, "r+b").write(b"x"))
    attempt("read_root_listing", lambda: os.listdir("/"))
    attempt("create_beside_scratch", lambda: open(os.path.dirname(config["scratch"][0]) + "/new", "wb").close())
    attempt("write_scratch", lambda: open(config["scratch"][0], "r+b").write(b"ok"))
    attempt("read_input", lambda: open(config["recipe"]["inputs"]["target"], "rb").read())
    attempt("socket_inet", lambda: socket.socket(socket.AF_INET).close())
    attempt("socket_unix", lambda: socket.socket(socket.AF_UNIX).close())
    attempt("signal_outside", lambda: os.kill({protected.pid}, signal.SIGCONT))
    attempt("exec_unlisted", lambda: subprocess.run(["/usr/bin/true"], check=False))
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    ctypes.set_errno(0)
    r["process_vm_readv"] = [libc.syscall(310, {protected.pid}, None, 0, None, 0, 0), ctypes.get_errno()]
    ctypes.set_errno(0)
    r["ptrace_attach"] = [libc.ptrace(16, {protected.pid}, None, None), ctypes.get_errno()]
    return r
    """
    try:
        outcome, report = await launch(project, hostile(tmp_path, body))
    finally:
        os.close(inherited)
    facts = report["facts"]
    assert report["status"] == "OK", report
    assert "M10_DATABASE_URL" not in facts["before"]["env"]
    assert facts["env_after"] == []
    assert str(secret) not in facts["before"]["fds"]
    assert not any(target.startswith(str(tmp_path)) for target in facts["before"]["fds"])
    assert facts["read_outside"] == 13
    assert facts["write_outside"] == 13
    assert facts["read_root_listing"] == 13
    assert facts["create_beside_scratch"] == 13
    assert facts["write_scratch"] == "allowed"
    assert facts["read_input"] == "allowed"
    assert facts["socket_inet"] == 1
    assert facts["socket_unix"] == 1
    assert facts["signal_outside"] == 1
    assert facts["exec_unlisted"] == 13
    assert facts["process_vm_readv"] == [-1, 1]
    assert facts["ptrace_attach"] == [-1, 1]
    assert writable.read_text() == "unchanged"
    assert outcome.scratch_sizes == (2, 0, 0)
    assert outcome.group_cleanup_verified


async def test_fork_exhaustion_is_capped_by_the_task_limit_and_cleaned_up(project, tmp_path: Path) -> None:
    body = """
    children = []
    denied = None
    for _ in range(64):
        try:
            pid = os.fork()
        except OSError as error:
            denied = error.errno
            break
        if pid == 0:
            time.sleep(60)
            os._exit(0)
        children.append(pid)
    return {"children": children, "denied": denied}
    """
    outcome, report = await launch(project, hostile(tmp_path, body))
    facts = report["facts"]
    assert facts["denied"] == 11
    assert len(facts["children"]) < 32
    assert report["accounting"]["peak_tasks"] <= 32
    assert outcome.group_cleanup_verified
    assert not any(alive(pid) for pid in facts["children"])


async def test_memory_pressure_is_an_oom_kill_not_a_result(project, tmp_path: Path) -> None:
    script = hostile(tmp_path, 'blob = bytearray(700 * 1024 * 1024)\nreturn {"allocated": len(blob)}')
    outcome, _ = await launch(project, script)
    assert outcome.manager_result == "OOM_KILL"
    assert outcome.group_cleanup_verified
    with pytest.raises(OperationalEnvelopeExceededError):
        await run(project, script)


async def test_output_flood_is_stopped_at_the_stream_ceiling(project, tmp_path: Path) -> None:
    script = hostile(tmp_path, 'while True:\n    os.write(1, b"x" * 65536)')
    outcome, _ = await launch(project, script)
    assert outcome.output_exceeded
    assert len(outcome.stdout) <= 1048576
    assert outcome.group_cleanup_verified
    with pytest.raises(OperationalEnvelopeExceededError):
        await run(project, script)


@pytest.mark.timeout(60)
async def test_runtime_deadline_kills_the_whole_unit(project, tmp_path: Path) -> None:
    script = hostile(tmp_path, "time.sleep(120)\nreturn {}")
    config = real_config(max_runtime_ms=1000)
    started = time.monotonic()
    with pytest.raises(OperationalEnvelopeExceededError):
        await run(project, script, config)
    assert time.monotonic() - started < 1 + 5 + 3 + 5 + 2


async def test_surviving_descendant_is_removed_with_the_control_group(project, tmp_path: Path) -> None:
    body = """
    pid = os.fork()
    if pid == 0:
        os.setsid()
        time.sleep(60)
        os._exit(0)
    return {"kind": "DECODE", "stream_indices": [pid], "complete": True}
    """
    result = await run(project, hostile(tmp_path, body))
    descendant = result.measurement.facts.stream_indices[0]
    assert result.resources.group_cleanup_verified
    assert not alive(descendant)


async def test_missing_user_manager_never_falls_back_to_unisolated_execution(
    project, tmp_path: Path, monkeypatch
) -> None:
    import asyncio

    launched: list[str] = []
    original = asyncio.create_subprocess_exec

    async def spy(program, *args, **kwargs):
        launched.append(str(program))
        return await original(program, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    with pytest.raises(RequiredEvidenceMissingError):
        await run(project, hostile(tmp_path, DECODED))
    assert launched
    assert set(launched) <= {runtime.SYSTEMD_RUN, runtime.SYSTEMCTL}


def probe_units(*states: str) -> str:
    argv = ["/usr/bin/systemctl", "--user", "list-units", "--all", "--no-legend"]
    argv += [f"--state={','.join(states)}"] if states else []
    return subprocess.run([*argv, "m10-probe-*"], capture_output=True, text=True, check=False, timeout=10).stdout


@pytest.mark.timeout(60)
async def test_cancellation_kills_and_reaps_the_owned_unit(project, tmp_path: Path) -> None:
    import asyncio

    task = asyncio.create_task(run(project, hostile(tmp_path, "time.sleep(60)\nreturn {}")))
    await asyncio.sleep(2)
    assert "m10-probe-" in await asyncio.to_thread(probe_units)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await asyncio.to_thread(probe_units, "active", "activating")).strip() == ""
