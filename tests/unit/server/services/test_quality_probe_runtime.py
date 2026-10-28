"""The supervisor's fixed unit envelope, manager parsing and failure classification are exact and fail closed."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from r2.quality.errors import (
    OperationalEnvelopeExceededError,
    ProbeFailedError,
    ReferenceInvalidError,
    RequiredEvidenceMissingError,
)
from server.services import quality_probe_runtime as runtime

ENVELOPE = {"memory_max": 536870912, "swap_max": 0, "tasks_max": 32, "cpu_quota_us": 100000, "cpu_period_us": 100000}


def test_service_envelope_is_the_admitted_fixed_property_set() -> None:
    properties = runtime.service_properties(125000)
    pairs = dict(value.split("=", 1) for value in properties[1::2])
    assert properties[0::2] == ("-p",) * len(pairs)
    assert pairs == {
        "MemoryMax": "536870912",
        "MemorySwapMax": "0",
        "TasksMax": "32",
        "CPUQuota": "100%",
        "RuntimeMaxSec": "125000ms",
        "TimeoutStopSec": "1s",
        "KillMode": "control-group",
        "NoNewPrivileges": "yes",
        "LimitCORE": "0",
        "LimitFSIZE": "67108864",
        "UMask": "0077",
        "SystemCallErrorNumber": "EPERM",
        "SystemCallFilter": "~@network-io @debug ptrace process_vm_readv process_vm_writev kcmp "
        "io_uring_setup io_uring_enter io_uring_register",
    }


def summary(result: str, code: str = "exited", status: str = "0/SUCCESS") -> bytes:
    return (
        "Running as unit: m10-probe-x.service; invocation ID: 1\n"
        f"          Finished with result: {result}\n"
        f"Main processes terminated with: code={code}, status={status}\n"
        "               Service runtime: 20ms\n"
    ).encode()


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (summary("success"), ("SUCCESS", 0)),
        (summary("exit-code", status="68/NOHOST"), ("EXIT_CODE", 68)),
        (summary("oom-kill", "killed", "9/KILL"), ("OOM_KILL", -9)),
        (summary("timeout", "killed", "15/TERM"), ("TIMEOUT", -15)),
        (summary("signal", "killed", "11/SEGV"), ("SIGNAL", -11)),
        (b"Failed to connect to user scope bus via local transport\n", ("STARTUP_FAILED", -1)),
        (b"", ("STARTUP_FAILED", -1)),
    ],
)
def test_manager_summary_maps_each_unit_outcome(stderr: bytes, expected: tuple[str, int]) -> None:
    assert runtime.parse_manager_summary(stderr) == expected


def test_manager_summary_uses_the_trailing_systemd_run_block() -> None:
    forged = summary("success") + summary("oom-kill", "killed", "9/KILL")
    assert runtime.parse_manager_summary(forged) == ("OOM_KILL", -9)


def test_scratch_inodes_are_exactly_three_private_regular_files_removed_afterwards() -> None:
    with runtime.scratch_files() as paths:
        assert len(set(paths)) == 3
        directory = paths[0].parent
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        for path in paths:
            info = path.lstat()
            assert stat.S_ISREG(info.st_mode)
            assert stat.S_IMODE(info.st_mode) == 0o600
            assert info.st_size == 0
            assert path.parent == directory
    assert not directory.exists()


def outcome(**changes: object) -> runtime.WorkerOutcome:
    body = {
        "schema": "m10.probe-worker-output.v1",
        "status": "OK",
        "facts": {"kind": "DECODE", "stream_indices": [0], "complete": True},
        "envelope": dict(ENVELOPE),
        "landlock_abi": 6,
        "kernel": {"release": "r", "version": "v", "machine": "x86_64"},
        "accounting": {"peak_memory_bytes": 1, "peak_tasks": 1, "oom_kill": 0},
    }
    body.update(changes.pop("body", {}))  # pyright: ignore[reportCallIssue]
    values: dict[str, object] = {
        "stdout": (json.dumps(body) + "\n").encode(),
        "stderr_bytes": 10,
        "exit_code": 0,
        "manager_result": "SUCCESS",
        "deadline_exceeded": False,
        "output_exceeded": False,
        "group_cleanup_verified": True,
        "wall_elapsed_ms": 5,
        "scratch_sizes": (0, 0, 0),
    } | changes
    return runtime.WorkerOutcome(**values)


def test_only_a_verified_zero_exit_ok_report_is_returned() -> None:
    assert runtime._report(outcome())["status"] == "OK"


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"group_cleanup_verified": False}, RequiredEvidenceMissingError),
        ({"output_exceeded": True}, OperationalEnvelopeExceededError),
        ({"deadline_exceeded": True}, OperationalEnvelopeExceededError),
        ({"manager_result": "TIMEOUT", "exit_code": -15}, OperationalEnvelopeExceededError),
        ({"manager_result": "OOM_KILL", "exit_code": -9}, OperationalEnvelopeExceededError),
        ({"manager_result": "STARTUP_FAILED", "exit_code": -1, "stdout": b""}, RequiredEvidenceMissingError),
        ({"manager_result": "SIGNAL", "exit_code": -11}, ProbeFailedError),
        ({"exit_code": 1, "manager_result": "EXIT_CODE"}, ProbeFailedError),
        ({"stdout": b'{"a":1}\n{"b":2}\n'}, ProbeFailedError),
        ({"stdout": b'{"schema":"m10.probe-worker-output.v1","schema":"x"}\n'}, ProbeFailedError),
        ({"body": {"status": "ISOLATION_UNAVAILABLE"}}, RequiredEvidenceMissingError),
        ({"body": {"status": "ENVELOPE_MISMATCH"}}, RequiredEvidenceMissingError),
        ({"body": {"status": "TOOL_UNQUALIFIED"}}, RequiredEvidenceMissingError),
        ({"body": {"status": "RECIPE_UNAVAILABLE"}}, RequiredEvidenceMissingError),
        ({"body": {"status": "REFERENCE_INVALID"}}, ReferenceInvalidError),
        ({"body": {"status": "OUTPUT_EXCEEDED"}}, OperationalEnvelopeExceededError),
        ({"body": {"status": "DEADLINE_EXCEEDED"}}, OperationalEnvelopeExceededError),
        ({"body": {"status": "TOOL_FAILED"}}, ProbeFailedError),
        ({"body": {"envelope": ENVELOPE | {"tasks_max": 64}}}, RequiredEvidenceMissingError),
        ({"body": {"landlock_abi": 5}}, RequiredEvidenceMissingError),
        (
            {"body": {"accounting": {"peak_memory_bytes": 1, "peak_tasks": 1, "oom_kill": 1}}},
            RequiredEvidenceMissingError,
        ),
    ],
)
def test_failures_are_classified_by_cause_and_never_become_success(changes: dict[str, object], error) -> None:
    with pytest.raises(error):
        runtime._report(outcome(**changes))


def test_missing_or_changed_host_tool_refuses_before_launch(tmp_path: Path) -> None:
    from tests.unit.r2.quality.test_probes import recipe_config

    config = recipe_config("DECODE")
    with pytest.raises(RequiredEvidenceMissingError):
        runtime.QualityProbeRuntime(runtime.ProbeHost(tools={}))._tools(config)
    fake = tmp_path / "ffmpeg"
    fake.write_bytes(b"not the pinned bytes")
    with pytest.raises(RequiredEvidenceMissingError):
        runtime.QualityProbeRuntime(runtime.ProbeHost(tools={"ffmpeg": fake, "ffprobe": fake}))._tools(config)
    linked = tmp_path / "linked"
    linked.symlink_to(fake)
    with pytest.raises(RequiredEvidenceMissingError):
        runtime.QualityProbeRuntime(runtime.ProbeHost(tools={"ffmpeg": linked, "ffprobe": linked}))._tools(config)


def test_manager_environment_carries_no_inherited_secrets(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    environment = runtime._manager_environment()
    assert "DATABASE_URL" not in environment
    assert set(environment) <= {"PATH", "LC_ALL", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}


def test_effective_limits_are_the_tightest_of_published_rule_config_and_host() -> None:
    from r2.quality.ports import ProbeRequest
    from tests.unit.r2.quality.test_probes import probe_request_data, recipe_config

    config = recipe_config("DECODE")
    data = probe_request_data(config)
    data["rule"].update(max_runtime_ms=1, max_output_bytes=1)
    for rule in data["profile"]["policy"]["probe_rules"]:
        rule.update(max_runtime_ms=1, max_output_bytes=1)
    from r2.quality.digests import compute_digest

    data["profile"]["policy_digest"] = compute_digest("m10.quality-policy.v1", data["profile"]["policy"])
    data["profile"]["profile_digest"] = compute_digest("m10.quality-profile.v1", data["profile"])
    request = ProbeRequest.model_validate(data)
    assert runtime.effective_limits(request, config) == (1, 1)
    loose = ProbeRequest.model_validate(probe_request_data(config))
    assert runtime.effective_limits(loose, config) == (
        min(loose.rule.max_runtime_ms, 120000),
        min(loose.rule.max_output_bytes, 1048576),
    )


CONTROL = "sha256:" + "c" * 64


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"exit_code": 70, "manager_result": "EXIT_CODE", "body": {"status": "TOOL_FAILED", "facts": None}},
            ("EXIT_CODE", 70, False, False),
        ),
        (
            {"manager_result": "TIMEOUT", "exit_code": -9, "deadline_exceeded": True},
            ("TIMEOUT", -9, True, False),
        ),
        ({"output_exceeded": True}, ("SUCCESS", 0, False, True)),
    ],
)
def test_failed_launch_after_tool_start_keeps_its_bounded_resource_accounting(
    changes: dict[str, object], expected: tuple[str, int, bool, bool]
) -> None:
    from tests.unit.r2.quality.test_probes import recipe_config

    config = recipe_config("DECODE")
    evidence = runtime._failure_resources(outcome(**changes), CONTROL, config)
    assert evidence is not None
    assert (evidence.manager_result, evidence.exit_code, evidence.deadline_exceeded, evidence.output_exceeded) == (
        expected
    )
    assert (evidence.memory_max_bytes, evidence.swap_max_bytes, evidence.tasks_max) == (
        runtime.MEMORY_MAX_BYTES,
        runtime.SWAP_MAX_BYTES,
        runtime.TASKS_MAX,
    )
    assert (evidence.peak_memory_bytes, evidence.peak_tasks, evidence.group_cleanup_verified) == (1, 1, True)
    assert evidence.control_identity_digest == CONTROL


@pytest.mark.parametrize(
    "changes",
    [
        {"group_cleanup_verified": False},
        {"manager_result": "STARTUP_FAILED", "exit_code": -1, "stdout": b""},
        {"stdout": b"not json\n"},
        {"body": {"envelope": ENVELOPE | {"tasks_max": 64}}},
        {"body": {"accounting": None}},
        {"body": {"accounting": {"peak_memory_bytes": -1, "peak_tasks": 1, "oom_kill": 0}}},
    ],
)
def test_failure_without_a_confined_cleaned_up_report_carries_no_resource_claim(changes: dict[str, object]) -> None:
    from tests.unit.r2.quality.test_probes import recipe_config

    assert runtime._failure_resources(outcome(**changes), CONTROL, recipe_config("DECODE")) is None


def test_failure_resources_reads_only_a_typed_attached_evidence() -> None:
    error = ProbeFailedError()
    assert runtime.failure_resources(error) is None
    error.resources = "forged"
    assert runtime.failure_resources(error) is None


def fake_run(monkeypatch, launched: runtime.WorkerOutcome):
    from types import SimpleNamespace

    from tests.unit.r2.quality.test_probes import recipe_config

    config = recipe_config("DECODE")

    async def launch(self, payload: bytes, **_: object) -> runtime.WorkerOutcome:
        return launched

    monkeypatch.setattr(runtime, "probe_request_digest", lambda request: CONTROL)
    monkeypatch.setattr(runtime, "effective_limits", lambda request, config: (1, 1))
    monkeypatch.setattr(runtime.QualityProbeRuntime, "control_identity_digest", lambda self: CONTROL)
    monkeypatch.setattr(runtime.QualityProbeRuntime, "worker_config", lambda self, *args: {})
    monkeypatch.setattr(runtime.QualityProbeRuntime, "launch", launch)
    inputs = SimpleNamespace(config=config, input_digests=())
    return runtime.QualityProbeRuntime(runtime.ProbeHost(tools={})).run(object(), inputs, config)


@pytest.mark.parametrize(
    ("changes", "error", "oom"),
    [
        (
            {"exit_code": 70, "manager_result": "EXIT_CODE", "body": {"status": "TOOL_FAILED", "facts": None}},
            ProbeFailedError,
            False,
        ),
        ({"manager_result": "OOM_KILL", "exit_code": -9}, OperationalEnvelopeExceededError, True),
        (
            {"body": {"accounting": {"peak_memory_bytes": 1, "peak_tasks": 1, "oom_kill": 1}}},
            RequiredEvidenceMissingError,
            True,
        ),
    ],
)
async def test_run_attaches_failure_resources_to_the_raised_typed_error(
    monkeypatch, changes: dict[str, object], error, oom: bool
) -> None:
    with pytest.raises(error) as raised:
        await fake_run(monkeypatch, outcome(**changes))
    evidence = runtime.failure_resources(raised.value)
    assert evidence is not None
    assert evidence.oom_killed is oom
    assert str(raised.value) == raised.value.code


async def test_run_attaches_nothing_when_cleanup_is_unverified(monkeypatch) -> None:
    with pytest.raises(RequiredEvidenceMissingError) as raised:
        await fake_run(monkeypatch, outcome(group_cleanup_verified=False))
    assert runtime.failure_resources(raised.value) is None


async def test_invalid_facts_on_an_ok_report_escape_untyped_without_resources(monkeypatch) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        await fake_run(monkeypatch, outcome(body={"facts": {"kind": "DECODE"}}))
    assert runtime.failure_resources(raised.value) is None
