"""Isolated fixed-recipe probe worker; one bounded host configuration arrives on stdin, never caller code.

The supervisor launches this file with the system interpreter inside an owned systemd service. The worker
checks the effective cgroup envelope and kernel controls, installs its Landlock policy, verifies tool bytes
and build output under that policy, and only then lets a fixed recipe touch untrusted media. It writes one
JSON line to stdout and nothing to stderr.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CONFIG_SCHEMA = "m10.probe-worker-config.v1"
OUTPUT_SCHEMA = "m10.probe-worker-output.v1"
MAX_CONFIG_BYTES = 1048576
EXIT_CODES = {
    "OK": 0,
    "CONFIG_INVALID": 64,
    "ENVELOPE_MISMATCH": 65,
    "ISOLATION_UNAVAILABLE": 66,
    "TOOL_UNQUALIFIED": 67,
    "RECIPE_UNAVAILABLE": 68,
    "REFERENCE_INVALID": 69,
    "TOOL_FAILED": 70,
    "OUTPUT_EXCEEDED": 71,
    "DEADLINE_EXCEEDED": 72,
    "WORKER_FAILED": 73,
}
_CONFIG_KEYS = frozenset({"schema", "envelope", "read_files", "exec_files", "read_dirs", "scratch", "tools", "recipe"})
_ENVELOPE_KEYS = frozenset({"memory_max", "swap_max", "tasks_max", "cpu_quota_us", "cpu_period_us"})
_TOOL_KEYS = frozenset({"name", "path", "executable_digest", "build_digest", "model_path", "model_digest"})
_RECIPE_KEYS = frozenset({"kind", "parameters", "budget_ms", "output_cap", "inputs"})
_INPUT_KEYS = frozenset({"target", "caption", "reference"})
_VERSION_FLAGS = {"ffmpeg": "-version", "ffprobe": "-version", "vmaf": "--version"}
_TOOL_ENV = {"LC_ALL": "C", "TZ": "UTC"}

# Landlock ABI>=6 syscall numbers (x86_64) and access rights.
_SYS_CREATE_RULESET = 444
_SYS_ADD_RULE = 445
_SYS_RESTRICT_SELF = 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_FS_EXECUTE = 1
_FS_WRITE_FILE = 2
_FS_READ_FILE = 4
_FS_READ_DIR = 8
_FS_TRUNCATE = 1 << 14
_FS_HANDLED = (1 << 16) - 1
_NET_HANDLED = 3
_SCOPED = 3
_PR_SET_NO_NEW_PRIVS = 38
_MIN_LANDLOCK_ABI = 6


class WorkerError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class _RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


class _PathBeneathAttr(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


@dataclass(frozen=True)
class Confinement:
    envelope: dict[str, int]
    landlock_abi: int
    kernel: dict[str, str]
    memory_peak_fd: int
    pids_peak_fd: int
    memory_events_fd: int


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerError("CONFIG_INVALID")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise WorkerError("CONFIG_INVALID")


def _absolute(value: object) -> str:
    if type(value) is not str or not value.startswith("/") or "\0" in value or len(value.encode()) > 4096:
        raise WorkerError("CONFIG_INVALID")
    return value


def _paths(value: object) -> list[str]:
    if type(value) is not list or len(value) > 64:
        raise WorkerError("CONFIG_INVALID")
    return [_absolute(item) for item in value]


def _positive(value: object, *, maximum: int) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise WorkerError("CONFIG_INVALID")
    return value


def read_config(stream: object) -> dict[str, object]:
    """Parse one bounded, duplicate-free host configuration; values are structure-checked, not trusted policy."""
    read = getattr(stream, "read", None)
    if read is None:
        raise WorkerError("CONFIG_INVALID")
    raw = read(MAX_CONFIG_BYTES + 1)
    if type(raw) is not bytes or len(raw) > MAX_CONFIG_BYTES:
        raise WorkerError("CONFIG_INVALID")
    try:
        config = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise WorkerError("CONFIG_INVALID") from None
    if type(config) is not dict or frozenset(config) != _CONFIG_KEYS or config["schema"] != CONFIG_SCHEMA:
        raise WorkerError("CONFIG_INVALID")
    envelope = config["envelope"]
    if type(envelope) is not dict or frozenset(envelope) != _ENVELOPE_KEYS:
        raise WorkerError("CONFIG_INVALID")
    for key, value in envelope.items():
        if type(value) is not int or value < 0 or (value == 0 and key != "swap_max"):
            raise WorkerError("CONFIG_INVALID")
    for key in ("read_files", "exec_files", "read_dirs"):
        _paths(config[key])
    scratch = _paths(config["scratch"])
    if len(scratch) != 3 or len(set(scratch)) != 3:
        raise WorkerError("CONFIG_INVALID")
    tools = config["tools"]
    if type(tools) is not list or not 0 < len(tools) <= 3:
        raise WorkerError("CONFIG_INVALID")
    for tool in tools:
        if type(tool) is not dict or frozenset(tool) != _TOOL_KEYS or tool["name"] not in _VERSION_FLAGS:
            raise WorkerError("CONFIG_INVALID")
        _absolute(tool["path"])
        if (tool["model_path"] is None) != (tool["name"] != "vmaf") or (tool["model_path"] is None) != (
            tool["model_digest"] is None
        ):
            raise WorkerError("CONFIG_INVALID")
        if tool["model_path"] is not None:
            _absolute(tool["model_path"])
    recipe = config["recipe"]
    if type(recipe) is not dict or frozenset(recipe) != _RECIPE_KEYS or type(recipe["kind"]) is not str:
        raise WorkerError("CONFIG_INVALID")
    _positive(recipe["budget_ms"], maximum=120000)
    _positive(recipe["output_cap"], maximum=1048576)
    inputs = recipe["inputs"]
    if type(inputs) is not dict or frozenset(inputs) != _INPUT_KEYS or type(recipe["parameters"]) is not dict:
        raise WorkerError("CONFIG_INVALID")
    _absolute(inputs["target"])
    for key in ("caption", "reference"):
        if inputs[key] is not None:
            _absolute(inputs[key])
    return config


def _read_int(path: Path) -> int | None:
    text = path.read_text(encoding="utf-8").strip()
    return None if text == "max" else int(text)


def observe_envelope(
    expected: dict[str, int], *, proc: Path | None = None, cgroup_root: Path | None = None
) -> tuple[dict[str, int], Path]:
    """Read the effective cgroup v2 limits of this service; any absent controller or drift refuses execution."""
    proc = proc or Path("/proc/self")
    cgroup_root = cgroup_root or Path("/sys/fs/cgroup")
    try:
        lines = (proc / "cgroup").read_text(encoding="utf-8").splitlines()
        if len(lines) != 1 or not lines[0].startswith("0::/"):
            raise WorkerError("ISOLATION_UNAVAILABLE")
        group = cgroup_root / lines[0][4:]
        quota, period = (group / "cpu.max").read_text(encoding="utf-8").split()
        observed = {
            "memory_max": _read_int(group / "memory.max"),
            "swap_max": _read_int(group / "memory.swap.max"),
            "tasks_max": _read_int(group / "pids.max"),
            "cpu_quota_us": None if quota == "max" else int(quota),
            "cpu_period_us": int(period),
        }
    except (OSError, ValueError):
        raise WorkerError("ISOLATION_UNAVAILABLE") from None
    if observed != expected:
        raise WorkerError("ENVELOPE_MISMATCH")
    return (dict(expected), group)


def check_kernel_controls(*, proc: Path | None = None) -> None:
    """Require the manager-installed seccomp filter, no-new-privileges and a single thread."""
    proc = proc or Path("/proc/self")
    try:
        status = dict(
            line.split(":", 1) for line in (proc / "status").read_text(encoding="utf-8").splitlines() if ":" in line
        )
        threads = os.listdir(proc / "task")
    except OSError:
        raise WorkerError("ISOLATION_UNAVAILABLE") from None
    if status.get("Seccomp", "").strip() != "2" or status.get("NoNewPrivs", "").strip() != "1" or len(threads) != 1:
        raise WorkerError("ISOLATION_UNAVAILABLE")


def _libc() -> ctypes.CDLL:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def landlock_abi(libc: ctypes.CDLL) -> int:
    return int(libc.syscall(_SYS_CREATE_RULESET, None, ctypes.c_size_t(0), ctypes.c_uint32(_CREATE_RULESET_VERSION)))


def install_landlock(config: dict[str, object], *, libc: ctypes.CDLL | None = None) -> int:
    """Restrict this process tree to exact read/exec/scratch paths and scoped signals/abstract sockets."""
    libc = libc or _libc()
    abi = landlock_abi(libc)
    if abi < _MIN_LANDLOCK_ABI:
        raise WorkerError("ISOLATION_UNAVAILABLE")
    rules: list[tuple[str, int]] = [(path, _FS_READ_FILE) for path in _paths(config["read_files"])]
    rules += [(path, _FS_READ_FILE | _FS_EXECUTE) for path in _paths(config["exec_files"])]
    rules += [(path, _FS_READ_FILE | _FS_READ_DIR | _FS_EXECUTE) for path in _paths(config["read_dirs"])]
    rules += [(path, _FS_READ_FILE | _FS_WRITE_FILE | _FS_TRUNCATE) for path in _paths(config["scratch"])]
    rules.append(("/dev/null", _FS_READ_FILE | _FS_WRITE_FILE))
    attr = _RulesetAttr(_FS_HANDLED, _NET_HANDLED, _SCOPED)
    ruleset = int(libc.syscall(_SYS_CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(ctypes.sizeof(attr)), 0))
    if ruleset < 0:
        raise WorkerError("ISOLATION_UNAVAILABLE")
    try:
        for path, rights in rules:
            try:
                descriptor = os.open(path, os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW)
            except OSError:
                raise WorkerError("ISOLATION_UNAVAILABLE") from None
            try:
                rule = _PathBeneathAttr(rights, descriptor)
                if libc.syscall(_SYS_ADD_RULE, ruleset, _RULE_PATH_BENEATH, ctypes.byref(rule), 0) != 0:
                    raise WorkerError("ISOLATION_UNAVAILABLE")
            finally:
                os.close(descriptor)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise WorkerError("ISOLATION_UNAVAILABLE")
        if libc.syscall(_SYS_RESTRICT_SELF, ruleset, 0) != 0:
            raise WorkerError("ISOLATION_UNAVAILABLE")
    finally:
        os.close(ruleset)
    try:
        os.listdir("/")
    except PermissionError:
        return abi
    raise WorkerError("ISOLATION_UNAVAILABLE")


def confine(config: dict[str, object], *, proc: Path | None = None, cgroup_root: Path | None = None) -> Confinement:
    """Verify the envelope and kernel controls, keep accounting handles, then irreversibly restrict the process."""
    os.environ.clear()
    os.closerange(3, 65536)
    expected = config["envelope"]
    if type(expected) is not dict:
        raise WorkerError("CONFIG_INVALID")
    envelope, group = observe_envelope(expected, proc=proc, cgroup_root=cgroup_root)
    check_kernel_controls(proc=proc)
    try:
        peaks = [
            os.open(group / name, os.O_RDONLY | os.O_CLOEXEC) for name in ("memory.peak", "pids.peak", "memory.events")
        ]
    except OSError:
        raise WorkerError("ISOLATION_UNAVAILABLE") from None
    uname = os.uname()
    abi = install_landlock(config)
    return Confinement(
        envelope,
        abi,
        {"release": uname.release, "version": uname.version, "machine": uname.machine},
        peaks[0],
        peaks[1],
        peaks[2],
    )


def _pread_text(descriptor: int) -> str:
    return os.pread(descriptor, 4096, 0).decode("utf-8")


def accounting(confinement: Confinement) -> dict[str, object]:
    events = dict(line.split() for line in _pread_text(confinement.memory_events_fd).splitlines() if line.strip())
    return {
        "peak_memory_bytes": int(_pread_text(confinement.memory_peak_fd).strip()),
        "peak_tasks": int(_pread_text(confinement.pids_peak_fd).strip()),
        "oom_kill": int(events.get("oom_kill", "0")),
    }


def run_tool(argv: list[str], *, deadline: float, output_cap: int) -> tuple[int, bytes, bytes]:
    """Run one fixed tool argv with a clean environment, a shared deadline and a combined stream ceiling."""
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(_TOOL_ENV),
            close_fds=True,
            start_new_session=True,
        )
    except OSError:
        raise WorkerError("TOOL_UNQUALIFIED") from None
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    if process.stdout is None or process.stderr is None:
        raise WorkerError("TOOL_FAILED")
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    failure: str | None = None
    code = -1
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = "DEADLINE_EXCEEDED"
                break
            for key, _ in selector.select(timeout=remaining):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                streams[key.data] += chunk
                if len(streams["stdout"]) + len(streams["stderr"]) > output_cap:
                    failure = "OUTPUT_EXCEEDED"
                    break
            if failure:
                break
        if failure is None:
            remaining = deadline - time.monotonic()
            try:
                code = process.wait(timeout=max(remaining, 0))
            except subprocess.TimeoutExpired:
                failure = "DEADLINE_EXCEEDED"
    finally:
        selector.close()
        if failure is not None or process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        process.stdout.close()
        process.stderr.close()
    if failure is not None:
        raise WorkerError(failure)
    return (code, bytes(streams["stdout"]), bytes(streams["stderr"]))


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        while chunk := os.read(descriptor, 1048576):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def verify_tools(config: dict[str, object], *, deadline: float) -> None:
    """Bind executable bytes, model bytes and version/build output under the installed policy."""
    tools = config["tools"]
    recipe = config["recipe"]
    if type(tools) is not list or type(recipe) is not dict:
        raise WorkerError("CONFIG_INVALID")
    for tool in tools:
        try:
            if _file_digest(tool["path"]) != tool["executable_digest"]:
                raise WorkerError("TOOL_UNQUALIFIED")
            if tool["model_path"] is not None and _file_digest(tool["model_path"]) != tool["model_digest"]:
                raise WorkerError("TOOL_UNQUALIFIED")
        except OSError:
            raise WorkerError("TOOL_UNQUALIFIED") from None
        code, output, _ = run_tool(
            [tool["path"], _VERSION_FLAGS[tool["name"]]], deadline=deadline, output_cap=recipe["output_cap"]
        )
        if code != 0 or "sha256:" + hashlib.sha256(output).hexdigest() != tool["build_digest"]:
            raise WorkerError("TOOL_UNQUALIFIED")


RECIPES: dict[str, Callable[[dict[str, object], float], dict[str, object]]] = {}


def _emit(body: dict[str, object]) -> None:
    remaining = memoryview((json.dumps(body, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8"))
    while remaining:
        written = os.write(1, remaining)
        remaining = remaining[written:]


def main() -> int:
    devnull = os.open("/dev/null", os.O_WRONLY | os.O_CLOEXEC)
    os.dup2(devnull, 2)
    os.close(devnull)
    confinement: Confinement | None = None
    try:
        config = read_config(sys.stdin.buffer)
        recipe = config["recipe"]
        if type(recipe) is not dict:
            raise WorkerError("CONFIG_INVALID")
        confinement = confine(config)
        deadline = time.monotonic() + recipe["budget_ms"] / 1000
        verify_tools(config, deadline=deadline)
        handler = RECIPES.get(recipe["kind"])
        if handler is None:
            raise WorkerError("RECIPE_UNAVAILABLE")
        facts = handler(config, deadline)
        status = "OK"
    except WorkerError as error:
        (facts, status) = (None, error.status)
    except Exception:
        (facts, status) = (None, "WORKER_FAILED")
    body: dict[str, object] = {"schema": OUTPUT_SCHEMA, "status": status, "facts": facts}
    if confinement is not None:
        body.update(
            envelope=confinement.envelope,
            landlock_abi=confinement.landlock_abi,
            kernel=confinement.kernel,
            accounting=accounting(confinement),
        )
    _emit(body)
    return EXIT_CODES[status]
