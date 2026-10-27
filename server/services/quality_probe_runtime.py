"""Host supervisor running one admitted probe recipe in an owned, resource-bounded and isolated systemd service.

There is no unisolated fallback: a missing user manager, controller, Landlock ABI or seccomp filter means no
tool executes and the call fails with required evidence missing. Database transactions must not be open
while `run` awaits the service.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import stat
import tempfile
import time
import uuid
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from r2.quality.errors import (
    OperationalEnvelopeExceededError,
    ProbeFailedError,
    ReferenceInvalidError,
    RequiredEvidenceMissingError,
)
from r2.quality.ports import ProbeRequest
from r2.quality.probes import (
    CaptionFacts,
    ContainerFacts,
    DecodeFacts,
    IntervalFacts,
    LoudnessFacts,
    ProbeConfig,
    ProbeExecutionResult,
    ResourceEvidence,
    VmafFacts,
    build_probe_measurement,
    probe_request_digest,
    tool_identity_digest,
)
from server.services.quality_probe_inputs import ProbeInputs

MEMORY_MAX_BYTES = 536870912
SWAP_MAX_BYTES = 0
TASKS_MAX = 32
CPU_QUOTA_US = 100000
CPU_PERIOD_US = 100000
SCRATCH_MAX_BYTES = 67108864
MAX_RUNTIME_MS = 120000
MAX_OUTPUT_BYTES = 1048576
MAX_MANAGER_BYTES = 65536
STARTUP_ALLOWANCE_MS = 5000
HOST_GRACE_MS = 3000
CLEANUP_DEADLINE_S = 5.0
SYSTEM_CALL_FILTER = (
    "~@network-io @debug ptrace process_vm_readv process_vm_writev kcmp io_uring_setup io_uring_enter io_uring_register"
)
SYSTEMD_RUN = "/usr/bin/systemd-run"
SYSTEMCTL = "/usr/bin/systemctl"
PYTHON = "/usr/bin/python3"
READ_DIRS = ("/usr/lib", "/usr/lib64")
READ_FILES = ("/etc/ld.so.cache",)
# Fixed launcher: loads the configured worker file by absolute path under `python3 -I`.
LAUNCHER = (
    "import importlib.util as u,sys;s=u.spec_from_file_location('m10_probe_worker',sys.argv[1]);"
    "m=u.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m);raise SystemExit(m.main())"
)
_FACTS = {
    "CONTAINER_STREAM": ContainerFacts,
    "DECODE": DecodeFacts,
    "INTERVALS": IntervalFacts,
    "LOUDNESS": LoudnessFacts,
    "CAPTIONS": CaptionFacts,
    "REFERENCE_VMAF": VmafFacts,
}
_MANAGER_RESULTS = {
    "success": "SUCCESS",
    "exit-code": "EXIT_CODE",
    "timeout": "TIMEOUT",
    "oom-kill": "OOM_KILL",
    "signal": "SIGNAL",
    "core-dump": "SIGNAL",
}
_MISSING = frozenset(
    {"CONFIG_INVALID", "ENVELOPE_MISMATCH", "ISOLATION_UNAVAILABLE", "TOOL_UNQUALIFIED", "RECIPE_UNAVAILABLE"}
)
_EXCEEDED = frozenset({"OUTPUT_EXCEEDED", "DEADLINE_EXCEEDED"})
_ENVELOPE = {
    "memory_max": MEMORY_MAX_BYTES,
    "swap_max": SWAP_MAX_BYTES,
    "tasks_max": TASKS_MAX,
    "cpu_quota_us": CPU_QUOTA_US,
    "cpu_period_us": CPU_PERIOD_US,
}


@dataclass(frozen=True)
class ProbeHost:
    """Host-owned tool locations; never derived from a request payload."""

    tools: Mapping[str, Path]
    vmaf_model: Path | None = None
    worker: Path | None = None


@dataclass(frozen=True)
class WorkerOutcome:
    stdout: bytes
    stderr_bytes: int
    exit_code: int
    manager_result: str
    deadline_exceeded: bool
    output_exceeded: bool
    group_cleanup_verified: bool
    wall_elapsed_ms: int
    scratch_sizes: tuple[int, int, int]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RequiredEvidenceMissingError()
        while chunk := os.read(descriptor, 1048576):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def _canonical_digest(body: object) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def service_properties(runtime_max_ms: int) -> tuple[str, ...]:
    """Exact admitted unit envelope; effective values are re-read by the worker before any media parsing."""
    properties = (
        f"MemoryMax={MEMORY_MAX_BYTES}",
        f"MemorySwapMax={SWAP_MAX_BYTES}",
        f"TasksMax={TASKS_MAX}",
        "CPUQuota=100%",
        f"RuntimeMaxSec={runtime_max_ms}ms",
        "TimeoutStopSec=1s",
        "KillMode=control-group",
        "NoNewPrivileges=yes",
        "LimitCORE=0",
        f"LimitFSIZE={SCRATCH_MAX_BYTES}",
        "UMask=0077",
        "SystemCallErrorNumber=EPERM",
        "SystemCallFilter=" + SYSTEM_CALL_FILTER,
    )
    return tuple(item for value in properties for item in ("-p", value))


def parse_manager_summary(stderr: bytes) -> tuple[str, int]:
    """Map the trailing systemd-run summary to a manager result; absent summary means the unit never started."""
    text = stderr.decode("utf-8", "replace")
    results = re.findall(r"^\s*Finished with result: ([a-z-]+)\s*$", text, re.MULTILINE)
    exits = re.findall(r"^Main processes terminated with: code=([a-z]+), status=(\d+)", text, re.MULTILINE)
    if not results or not exits or "Running as unit:" not in text:
        return ("STARTUP_FAILED", -1)
    code, status = exits[-1]
    return (_MANAGER_RESULTS.get(results[-1], "SIGNAL"), int(status) if code == "exited" else -int(status))


@contextmanager
def scratch_files() -> Generator[tuple[Path, Path, Path], None, None]:
    """Precreate exactly three private regular scratch inodes; the restricted worker may not create files."""
    directory = Path(tempfile.mkdtemp(prefix="m10-probe-scratch-"))
    paths: list[Path] = []
    try:
        for index in range(3):
            path = directory / f"scratch-{index}"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            os.close(descriptor)
            paths.append(path)
        yield (paths[0], paths[1], paths[2])
    finally:
        for path in paths:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        os.rmdir(directory)


class QualityProbeRuntime:
    def __init__(self, host: ProbeHost) -> None:
        self._host = host

    def _worker(self) -> Path:
        return self._host.worker or Path(__file__).with_name("quality_probe_worker.py")

    def _tools(self, config: ProbeConfig) -> list[dict[str, object]]:
        tools: list[dict[str, object]] = []
        for tool in config.tools:
            path = self._host.tools.get(tool.name)
            model = self._host.vmaf_model if tool.name == "vmaf" else None
            try:
                if path is None or _sha256_file(path) != tool.executable_digest:
                    raise RequiredEvidenceMissingError()
                if (tool.model_digest is None) != (model is None) or (
                    model is not None and _sha256_file(model) != tool.model_digest
                ):
                    raise RequiredEvidenceMissingError()
            except OSError:
                raise RequiredEvidenceMissingError() from None
            tools.append(
                {
                    "name": tool.name,
                    "path": str(path),
                    "executable_digest": tool.executable_digest,
                    "build_digest": tool.build_digest,
                    "model_path": None if model is None else str(model),
                    "model_digest": tool.model_digest,
                }
            )
        return tools

    def worker_config(
        self, inputs: ProbeInputs, config: ProbeConfig, scratch: tuple[Path, Path, Path]
    ) -> dict[str, object]:
        """Schema-shaped host configuration for the fixed worker; it carries no command or filter text."""
        tools = self._tools(config)
        companions = [item for item in (inputs.caption, inputs.reference) if item is not None]
        models = [tool["model_path"] for tool in tools if tool["model_path"] is not None]
        return {
            "schema": "m10.probe-worker-config.v1",
            "envelope": dict(_ENVELOPE),
            "read_files": [*READ_FILES, str(inputs.target.path), *(str(item.path) for item in companions), *models],
            "exec_files": [tool["path"] for tool in tools],
            "read_dirs": list(READ_DIRS),
            "scratch": [str(path) for path in scratch],
            "tools": tools,
            "recipe": {
                "kind": config.recipe,
                "parameters": config.parameters.model_dump(mode="json"),
                "budget_ms": min(config.max_runtime_ms, MAX_RUNTIME_MS),
                "output_cap": min(config.max_output_bytes, MAX_OUTPUT_BYTES),
                "inputs": {
                    "target": str(inputs.target.path),
                    "caption": None if inputs.caption is None else str(inputs.caption.path),
                    "reference": None if inputs.reference is None else str(inputs.reference.path),
                },
            },
        }

    def control_identity_digest(self) -> str:
        return _canonical_digest(
            {
                "systemd_run": _sha256_file(Path(SYSTEMD_RUN).resolve()),
                "python": [str(Path(PYTHON).resolve()), _sha256_file(Path(PYTHON).resolve())],
                "worker": _sha256_file(self._worker()),
                "launcher": LAUNCHER,
                "properties": service_properties(0),
                "read_dirs": READ_DIRS,
                "read_files": READ_FILES,
            }
        )

    async def _systemctl(self, *args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            SYSTEMCTL,
            "--user",
            "--no-ask-password",
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_manager_environment(),
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=CLEANUP_DEADLINE_S)
        except TimeoutError:
            process.kill()
            await process.wait()
            return b""
        return output

    async def _verify_cleanup(self, unit: str) -> bool:
        deadline = time.monotonic() + CLEANUP_DEADLINE_S
        while True:
            shown = await self._systemctl("show", unit, "-p", "LoadState", "-p", "ActiveState")
            if sorted(shown.decode("utf-8", "replace").split()) == ["ActiveState=inactive", "LoadState=not-found"]:
                return True
            if time.monotonic() > deadline:
                return False
            await self._systemctl("kill", "--signal=SIGKILL", unit)
            await self._systemctl("stop", unit)
            await self._systemctl("reset-failed", unit)
            await asyncio.sleep(0.1)

    async def launch(
        self, payload: bytes, *, budget_ms: int, output_cap: int, scratch: tuple[Path, Path, Path]
    ) -> WorkerOutcome:
        """Start the fixed worker in a fresh owned unit, bound its streams and deadline, and verify group cleanup."""
        if not 0 < budget_ms <= MAX_RUNTIME_MS or not 0 < output_cap <= MAX_OUTPUT_BYTES:
            raise OperationalEnvelopeExceededError()
        unit = f"m10-probe-{uuid.uuid4().hex}.service"
        runtime_max_ms = budget_ms + STARTUP_ALLOWANCE_MS
        argv = (
            SYSTEMD_RUN,
            "--user",
            "--no-ask-password",
            "--wait",
            "--pipe",
            "--collect",
            "--service-type=exec",
            "--expand-environment=no",
            "--working-directory=/",
            f"--unit={unit}",
            *service_properties(runtime_max_ms),
            PYTHON,
            "-I",
            "-B",
            "-c",
            LAUNCHER,
            str(self._worker()),
        )
        started = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_manager_environment(),
                close_fds=True,
                start_new_session=True,
            )
        except OSError:
            raise RequiredEvidenceMissingError() from None
        stdout = bytearray()
        stderr = bytearray()
        exceeded = asyncio.Event()

        async def pump(stream: asyncio.StreamReader | None, sink: bytearray, cap: int) -> None:
            if stream is None:
                return
            # Keep draining after the ceiling so the transport observes EOF once the unit is killed.
            while chunk := await stream.read(65536):
                if exceeded.is_set() or len(sink) + len(chunk) > cap:
                    exceeded.set()
                    continue
                sink.extend(chunk)

        async def feed() -> None:
            if process.stdin is None:
                return
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                process.stdin.write(payload)
                await process.stdin.drain()
            process.stdin.close()

        work = asyncio.gather(
            feed(),
            pump(process.stdout, stdout, output_cap),
            pump(process.stderr, stderr, MAX_MANAGER_BYTES),
            process.wait(),
        )
        watcher = asyncio.ensure_future(exceeded.wait())
        host_deadline = (runtime_max_ms + HOST_GRACE_MS) / 1000
        done, _ = await asyncio.wait({work, watcher}, timeout=host_deadline, return_when=asyncio.FIRST_COMPLETED)
        deadline_exceeded = not done
        watcher.cancel()
        if work not in done:
            await self._systemctl("kill", "--signal=SIGKILL", unit)
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(work, CLEANUP_DEADLINE_S)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        cleanup = await self._verify_cleanup(unit)
        manager_result, exit_code = parse_manager_summary(bytes(stderr))
        if exceeded.is_set() or deadline_exceeded:
            manager_result = "TIMEOUT" if deadline_exceeded else manager_result
        sizes = tuple(os.stat(path, follow_symlinks=False).st_size for path in scratch)
        return WorkerOutcome(
            stdout=bytes(stdout),
            stderr_bytes=len(stderr),
            exit_code=exit_code,
            manager_result=manager_result,
            deadline_exceeded=deadline_exceeded,
            output_exceeded=exceeded.is_set(),
            group_cleanup_verified=cleanup,
            wall_elapsed_ms=elapsed_ms,
            scratch_sizes=(sizes[0], sizes[1], sizes[2]),
        )

    async def run(self, request: ProbeRequest, inputs: ProbeInputs, config: ProbeConfig) -> ProbeExecutionResult:
        """Execute one admitted recipe against exact copied inputs; any incomplete bounded success raises."""
        config = ProbeConfig.model_validate(config)
        if inputs.config != config:
            raise RequiredEvidenceMissingError()
        request_digest = probe_request_digest(request)
        control = self.control_identity_digest()
        started_at = datetime.now(UTC)
        with scratch_files() as scratch:
            payload = json.dumps(self.worker_config(inputs, config, scratch), separators=(",", ":")).encode("utf-8")
            outcome = await self.launch(
                payload,
                budget_ms=min(config.max_runtime_ms, MAX_RUNTIME_MS),
                output_cap=min(config.max_output_bytes, MAX_OUTPUT_BYTES),
                scratch=scratch,
            )
        finished_at = datetime.now(UTC)
        report = _report(outcome)
        facts = _FACTS[config.recipe].model_validate(report["facts"])
        measurement = build_probe_measurement(config, input_digests=inputs.input_digests, facts=facts)
        accounting = report["accounting"]
        kernel = report["kernel"]
        if type(accounting) is not dict or type(kernel) is not dict:
            raise ProbeFailedError()
        resources = ResourceEvidence(
            schema_id="m10.probe-resources.v1",
            memory_max_bytes=MEMORY_MAX_BYTES,
            swap_max_bytes=SWAP_MAX_BYTES,
            tasks_max=TASKS_MAX,
            cpu_quota_us=CPU_QUOTA_US,
            cpu_period_us=CPU_PERIOD_US,
            wall_elapsed_ms=outcome.wall_elapsed_ms,
            peak_memory_bytes=accounting.get("peak_memory_bytes"),
            peak_tasks=accounting.get("peak_tasks"),
            stdout_bytes=len(outcome.stdout),
            stderr_bytes=outcome.stderr_bytes,
            scratch_sizes=outcome.scratch_sizes,
            exit_code=outcome.exit_code,
            manager_result="SUCCESS",
            oom_killed=False,
            deadline_exceeded=False,
            output_exceeded=False,
            group_cleanup_verified=True,
            kernel_identity_digest=_canonical_digest({"kernel": kernel, "landlock_abi": report["landlock_abi"]}),
            control_identity_digest=control,
            tool_identity_digest=tool_identity_digest(config),
        )
        return ProbeExecutionResult(
            schema_id="m10.probe-execution-result.v1",
            request_digest=request_digest,
            execution_id=uuid.uuid4().hex,
            measurement=measurement,
            resources=resources,
            started_at=started_at,
            finished_at=finished_at,
        )


def _manager_environment() -> dict[str, str]:
    """Only what systemctl/systemd-run need to reach the user manager; no database or token variables."""
    names = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
    return {"PATH": "/usr/bin:/bin", "LC_ALL": "C"} | {name: os.environ[name] for name in names if name in os.environ}


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProbeFailedError()
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ProbeFailedError()


def _report(outcome: WorkerOutcome) -> dict[str, object]:
    """Classify a finished launch by cause; only a verified, bounded, zero-exit OK report is returned."""
    if not outcome.group_cleanup_verified:
        raise RequiredEvidenceMissingError()
    if outcome.output_exceeded or outcome.deadline_exceeded or outcome.manager_result in {"TIMEOUT", "OOM_KILL"}:
        raise OperationalEnvelopeExceededError()
    if outcome.manager_result == "STARTUP_FAILED":
        raise RequiredEvidenceMissingError()
    lines = outcome.stdout.split(b"\n")
    if len(lines) != 2 or lines[1] != b"":
        raise ProbeFailedError()
    try:
        report = json.loads(lines[0].decode("utf-8"), object_pairs_hook=_strict_pairs, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ProbeFailedError() from None
    if type(report) is not dict or report.get("schema") != "m10.probe-worker-output.v1":
        raise ProbeFailedError()
    status = report.get("status")
    if status in _MISSING:
        raise RequiredEvidenceMissingError()
    if status == "REFERENCE_INVALID":
        raise ReferenceInvalidError()
    if status in _EXCEEDED:
        raise OperationalEnvelopeExceededError()
    if status != "OK" or outcome.exit_code != 0 or outcome.manager_result != "SUCCESS":
        raise ProbeFailedError()
    accounting = report.get("accounting")
    if report.get("envelope") != _ENVELOPE or type(accounting) is not dict or accounting.get("oom_kill") != 0:
        raise RequiredEvidenceMissingError()
    abi = report.get("landlock_abi")
    if type(abi) is not int or abi < 6:
        raise RequiredEvidenceMissingError()
    return report
