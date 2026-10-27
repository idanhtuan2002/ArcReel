"""The fixed worker parses bounded host configuration and refuses absent or drifted isolation."""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from server.services import quality_probe_worker as worker

ENVELOPE = {"memory_max": 536870912, "swap_max": 0, "tasks_max": 32, "cpu_quota_us": 100000, "cpu_period_us": 100000}


def config_data(tmp_path: Path) -> dict[str, object]:
    return {
        "schema": "m10.probe-worker-config.v1",
        "envelope": dict(ENVELOPE),
        "read_files": ["/etc/ld.so.cache"],
        "exec_files": ["/usr/bin/ffmpeg"],
        "read_dirs": ["/usr/lib"],
        "scratch": [str(tmp_path / name) for name in ("a", "b", "c")],
        "tools": [
            {
                "name": "ffmpeg",
                "path": "/usr/bin/ffmpeg",
                "executable_digest": "sha256:" + "1" * 64,
                "build_digest": "sha256:" + "2" * 64,
                "model_path": None,
                "model_digest": None,
            }
        ],
        "recipe": {
            "kind": "DECODE",
            "parameters": {},
            "budget_ms": 1000,
            "output_cap": 4096,
            "inputs": {"target": str(tmp_path / "target"), "caption": None, "reference": None},
        },
    }


def status_of(call) -> str:
    with pytest.raises(worker.WorkerError) as raised:
        call()
    return raised.value.status


def test_configuration_is_bounded_exact_and_duplicate_free(tmp_path: Path) -> None:
    data = config_data(tmp_path)
    assert worker.read_config(io.BytesIO(json.dumps(data).encode())) == data
    raw = json.dumps(data).encode()
    assert status_of(lambda: worker.read_config(io.BytesIO(raw[:-1] + b',"schema":"x"}'))) == "CONFIG_INVALID"
    assert status_of(lambda: worker.read_config(io.BytesIO(b" " * (worker.MAX_CONFIG_BYTES + 1)))) == "CONFIG_INVALID"
    assert status_of(lambda: worker.read_config(io.BytesIO(b'{"a": NaN}'))) == "CONFIG_INVALID"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(command=["/bin/sh"]),
        lambda d: d["read_dirs"].append("relative/lib"),
        lambda d: d["scratch"].pop(),
        lambda d: d["scratch"].__setitem__(2, d["scratch"][0]),
        lambda d: d["tools"][0].update(name="sh"),
        lambda d: d["tools"][0].update(model_path="/m.json"),
        lambda d: d["recipe"].update(budget_ms=120001),
        lambda d: d["recipe"].update(output_cap=0),
        lambda d: d["recipe"]["inputs"].update(target="t"),
        lambda d: d["envelope"].update(tasks_max=0),
        lambda d: d["envelope"].pop("swap_max"),
    ],
)
def test_configuration_rejects_commands_relative_paths_and_incomplete_envelopes(tmp_path: Path, change) -> None:
    data = config_data(tmp_path)
    change(data)
    assert status_of(lambda: worker.read_config(io.BytesIO(json.dumps(data).encode()))) == "CONFIG_INVALID"


def fake_host(tmp_path: Path, **files: str) -> tuple[Path, Path]:
    proc = tmp_path / "proc"
    group = tmp_path / "cgroup" / "app.slice" / "unit.service"
    (proc / "task" / "1").mkdir(parents=True)
    group.mkdir(parents=True)
    (proc / "cgroup").write_text("0::/app.slice/unit.service\n", encoding="utf-8")
    (proc / "status").write_text("Name:\tpython3\nNoNewPrivs:\t1\nSeccomp:\t2\n", encoding="utf-8")
    values = {
        "memory.max": "536870912",
        "memory.swap.max": "0",
        "pids.max": "32",
        "cpu.max": "100000 100000",
    } | {name.replace("_", "."): value for name, value in files.items()}
    for name, value in values.items():
        if value != "ABSENT":
            (group / name).write_text(value + "\n", encoding="utf-8")
    return (proc, tmp_path / "cgroup")


def test_effective_cgroup_envelope_must_match_exactly(tmp_path: Path) -> None:
    proc, root = fake_host(tmp_path)
    envelope, group = worker.observe_envelope(dict(ENVELOPE), proc=proc, cgroup_root=root)
    assert envelope == ENVELOPE
    assert group == root / "app.slice" / "unit.service"


@pytest.mark.parametrize(
    ("files", "status"),
    [
        ({"memory_max": "max"}, "ENVELOPE_MISMATCH"),
        ({"memory_swap_max": "max"}, "ENVELOPE_MISMATCH"),
        ({"pids_max": "64"}, "ENVELOPE_MISMATCH"),
        ({"cpu_max": "max 100000"}, "ENVELOPE_MISMATCH"),
        ({"memory_max": "ABSENT"}, "ISOLATION_UNAVAILABLE"),
        ({"pids_max": "ABSENT"}, "ISOLATION_UNAVAILABLE"),
    ],
)
def test_missing_controller_or_drifted_limit_refuses_before_media(tmp_path: Path, files, status: str) -> None:
    proc, root = fake_host(tmp_path, **files)
    assert status_of(lambda: worker.observe_envelope(dict(ENVELOPE), proc=proc, cgroup_root=root)) == status


def test_cgroup_v1_membership_is_unavailable_isolation(tmp_path: Path) -> None:
    proc, root = fake_host(tmp_path)
    (proc / "cgroup").write_text("12:pids:/user.slice\n0::/app.slice/unit.service\n", encoding="utf-8")
    assert status_of(lambda: worker.observe_envelope(dict(ENVELOPE), proc=proc, cgroup_root=root)) == (
        "ISOLATION_UNAVAILABLE"
    )


@pytest.mark.parametrize(
    "status_text",
    ["NoNewPrivs:\t1\nSeccomp:\t0\n", "NoNewPrivs:\t0\nSeccomp:\t2\n", "Name:\tpython3\n"],
)
def test_absent_seccomp_or_no_new_privileges_is_unavailable_isolation(tmp_path: Path, status_text: str) -> None:
    proc, _ = fake_host(tmp_path)
    worker.check_kernel_controls(proc=proc)
    (proc / "status").write_text(status_text, encoding="utf-8")
    assert status_of(lambda: worker.check_kernel_controls(proc=proc)) == "ISOLATION_UNAVAILABLE"


def test_additional_thread_is_unavailable_isolation(tmp_path: Path) -> None:
    proc, _ = fake_host(tmp_path)
    (proc / "task" / "2").mkdir()
    assert status_of(lambda: worker.check_kernel_controls(proc=proc)) == "ISOLATION_UNAVAILABLE"


class OldKernel:
    def syscall(self, *args: object) -> int:
        return 5


def test_landlock_abi_below_six_refuses_without_partial_policy(tmp_path: Path) -> None:
    assert status_of(lambda: worker.install_landlock(config_data(tmp_path), libc=OldKernel())) == (
        "ISOLATION_UNAVAILABLE"
    )


def test_tool_runner_returns_bounded_streams_with_a_clean_environment(monkeypatch) -> None:
    monkeypatch.setenv("M10_SECRET_TOKEN", "leak")
    code, out, err = worker.run_tool(
        [sys.executable, "-c", "import os,sys;print(sorted(os.environ));sys.stderr.write('e')"],
        deadline=time.monotonic() + 10,
        output_cap=4096,
    )
    assert code == 0
    assert out.decode().strip() == "['LC_ALL', 'TZ']"
    assert err == b"e"


def test_tool_output_flood_and_deadline_kill_the_whole_tool_group(tmp_path: Path) -> None:
    flood = [sys.executable, "-c", "import os\nwhile True: os.write(1, b'x' * 65536)"]
    assert status_of(lambda: worker.run_tool(flood, deadline=time.monotonic() + 10, output_cap=100000)) == (
        "OUTPUT_EXCEEDED"
    )
    marker = tmp_path / "child.pid"
    sleeper = [
        sys.executable,
        "-c",
        f"import os,subprocess,time;p=subprocess.Popen(['sleep','30']);open({str(marker)!r},'w').write(str(p.pid));"
        "time.sleep(30)",
    ]
    started = time.monotonic()
    assert status_of(lambda: worker.run_tool(sleeper, deadline=time.monotonic() + 1, output_cap=4096)) == (
        "DEADLINE_EXCEEDED"
    )
    assert time.monotonic() - started < 5
    child = int(marker.read_text(encoding="utf-8"))
    for _ in range(50):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("tool descendant survived the deadline")
