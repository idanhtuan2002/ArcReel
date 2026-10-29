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
import re
import selectors
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
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


_MP4_FORMAT = "mov,mp4,m4a,3gp,3g2,mj2"
# H.264 4:2:0 in limited or full range; ffprobe names full-range 4:2:0 `yuvj420p`.
_PIXEL_FORMATS = frozenset({"yuv420p", "yuvj420p"})
_PROBE_ENTRIES = (
    "format=format_name,duration:stream=index,codec_type,codec_name,width,height,pix_fmt,sample_rate,channels,"
    "avg_frame_rate,time_base,duration_ts,start_time"
)
_DECIMAL = r"-?[0-9]+(?:\.[0-9]+)?"
_MAX_CAPTION_BYTES = 262144
_MAX_ENTRIES = 10000
_MAX_VMAF_PIXELS = 2073600


def _recipe(config: dict[str, object]) -> tuple[dict[str, object], dict[str, object], int]:
    recipe = config["recipe"]
    if type(recipe) is not dict:
        raise WorkerError("CONFIG_INVALID")
    parameters, inputs, cap = recipe["parameters"], recipe["inputs"], recipe["output_cap"]
    if type(parameters) is not dict or type(inputs) is not dict or type(cap) is not int:
        raise WorkerError("CONFIG_INVALID")
    return (parameters, inputs, cap)


def _tool_path(config: dict[str, object], name: str) -> str:
    tools = config["tools"]
    if type(tools) is not list:
        raise WorkerError("CONFIG_INVALID")
    for tool in tools:
        if tool["name"] == name:
            return tool["path"]
    raise WorkerError("TOOL_UNQUALIFIED")


def _vmaf_model(config: dict[str, object]) -> tuple[str, str]:
    tools = config["tools"]
    if type(tools) is not list:
        raise WorkerError("CONFIG_INVALID")
    for tool in tools:
        if tool["name"] == "vmaf" and tool["model_path"] is not None:
            return (tool["model_path"], tool["model_digest"])
    raise WorkerError("TOOL_UNQUALIFIED")


def _time(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _decimal(value: object, failure: str) -> Fraction:
    if type(value) is not str or len(value) > 64 or re.fullmatch(_DECIMAL, value) is None:
        raise WorkerError(failure)
    return Fraction(value)


def _rational(value: object, failure: str) -> Fraction:
    match = re.fullmatch(r"(-?[0-9]{1,18})/([0-9]{1,18})", value) if type(value) is str else None
    if match is None or int(match.group(2)) == 0:
        raise WorkerError(failure)
    return Fraction(int(match.group(1)), int(match.group(2)))


def _parameter_decimal(parameters: dict[str, object], key: str) -> str:
    value = parameters.get(key)
    _decimal(value, "CONFIG_INVALID")
    return str(value)


def _seconds(parameters: dict[str, object], key: str) -> str:
    value = parameters.get(key)
    if type(value) is not int or not 0 < value <= 120000:
        raise WorkerError("CONFIG_INVALID")
    whole, rest = divmod(value, 1000)
    return f"{whole}.{rest:03d}"


def _strict_output(raw: bytes, failure: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise WorkerError(failure)
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise WorkerError(failure)

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=str, parse_constant=constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise WorkerError(failure) from None


def _media_argv(config: dict[str, object], path: str, *, level: str) -> list[str]:
    return [
        _tool_path(config, "ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-v",
        level,
        "-threads",
        "1",
        "-protocol_whitelist",
        "file",
        "-f",
        "mov",
        "-i",
        path,
    ]


@dataclass(frozen=True)
class VideoShape:
    width: int
    height: int
    rate: Fraction
    start: Fraction


@dataclass(frozen=True)
class MediaFacts:
    duration: Fraction
    streams: list[dict[str, object]]
    video: VideoShape | None
    audio: bool


def _input(inputs: dict[str, object], key: str) -> str | None:
    value = inputs.get(key)
    if value is not None and type(value) is not str:
        raise WorkerError("CONFIG_INVALID")
    return value


def probe_media(config: dict[str, object], path: str, *, deadline: float, failure: str) -> MediaFacts:
    """Fixed FFprobe whitelist over the forced MP4 demuxer; anything outside the qualified surface fails closed."""
    _, _, cap = _recipe(config)
    argv = [
        _tool_path(config, "ffprobe"),
        "-v",
        "error",
        "-protocol_whitelist",
        "file",
        "-f",
        "mov",
        "-show_entries",
        _PROBE_ENTRIES,
        "-of",
        "json",
        path,
    ]
    code, output, _ = run_tool(argv, deadline=deadline, output_cap=cap)
    if code != 0:
        raise WorkerError(failure)
    data = _strict_output(output, failure)
    if type(data) is not dict or type(data.get("format")) is not dict or type(data.get("streams")) is not list:
        raise WorkerError(failure)
    unsupported = "UNSUPPORTED_INPUT" if failure == "INPUT_INVALID" else failure
    if data["format"].get("format_name") != _MP4_FORMAT:
        raise WorkerError(unsupported)
    duration = _decimal(data["format"].get("duration"), failure)
    streams: list[dict[str, object]] = []
    video: VideoShape | None = None
    audio = False
    for stream in data["streams"]:
        if type(stream) is not dict or type(stream.get("index")) is not int:
            raise WorkerError(failure)
        time_base = _rational(stream.get("time_base"), failure)
        length = stream.get("duration_ts")
        stream_duration = _time(length * time_base) if type(length) is int and length >= 0 else "UNKNOWN"
        kind = stream.get("codec_type")
        if kind == "video" and video is None:
            pixel_format = stream.get("pix_fmt")
            if stream.get("codec_name") != "h264" or pixel_format not in _PIXEL_FORMATS:
                raise WorkerError(unsupported)
            width, height = stream.get("width"), stream.get("height")
            rate = _rational(stream.get("avg_frame_rate"), unsupported)
            if type(width) is not int or type(height) is not int or rate <= 0:
                raise WorkerError(unsupported)
            start = _decimal(stream.get("start_time"), failure)
            video = VideoShape(width, height, rate, start)
            streams.append(
                {
                    "index": stream["index"],
                    "kind": "VIDEO",
                    "codec": "h264",
                    "width": width,
                    "height": height,
                    "pixel_format": pixel_format,
                    "frame_rate": _time(rate),
                    "time_base": _time(time_base),
                    "duration": stream_duration,
                }
            )
        elif kind == "audio" and not audio:
            rate_text, channels = stream.get("sample_rate"), stream.get("channels")
            if stream.get("codec_name") != "aac" or type(channels) is not int:
                raise WorkerError(unsupported)
            if type(rate_text) is not str or re.fullmatch(r"[1-9][0-9]{0,5}", rate_text) is None:
                raise WorkerError(unsupported)
            audio = True
            streams.append(
                {
                    "index": stream["index"],
                    "kind": "AUDIO",
                    "codec": "aac",
                    "sample_rate": int(rate_text),
                    "channels": channels,
                    "time_base": _time(time_base),
                    "duration": stream_duration,
                }
            )
        else:
            raise WorkerError(unsupported)
    if not streams:
        raise WorkerError(unsupported)
    return MediaFacts(duration, streams, video, audio)


def _target(config: dict[str, object]) -> str:
    _, inputs, _ = _recipe(config)
    target = _input(inputs, "target")
    if target is None:
        raise WorkerError("CONFIG_INVALID")
    return target


def container_recipe(config: dict[str, object], deadline: float) -> dict[str, object]:
    media = probe_media(config, _target(config), deadline=deadline, failure="INPUT_INVALID")
    return {
        "kind": "CONTAINER_STREAM",
        "format": "MP4",
        "duration": _time(media.duration),
        "streams": media.streams,
    }


def decode_recipe(config: dict[str, object], deadline: float) -> dict[str, object]:
    parameters, _, cap = _recipe(config)
    media = probe_media(config, _target(config), deadline=deadline, failure="INPUT_INVALID")
    if (parameters.get("require_video") is True and media.video is None) or (
        parameters.get("require_audio") is True and not media.audio
    ):
        raise WorkerError("INPUT_INVALID")
    argv = _media_argv(config, _target(config), level="error")
    argv[6:6] = ["-xerror"]
    argv += ["-map", "0:v?", "-map", "0:a?", "-filter_threads", "1", "-f", "null", "-"]
    code, output, errors = run_tool(argv, deadline=deadline, output_cap=cap)
    indices = sorted(int(str(stream["index"])) for stream in media.streams)
    return {"kind": "DECODE", "stream_indices": indices, "complete": code == 0 and output == b"" and errors == b""}


_INTERVAL_KEYS = {
    "lavfi.black_start": ("BLACK", True),
    "lavfi.black_end": ("BLACK", False),
    "lavfi.freezedetect.freeze_start": ("FREEZE", True),
    "lavfi.freezedetect.freeze_end": ("FREEZE", False),
    "lavfi.silence_start": ("SILENCE", True),
    "lavfi.silence_end": ("SILENCE", False),
}
_IGNORED_KEYS = frozenset({"lavfi.freezedetect.freeze_duration", "lavfi.silence_duration"})


def parse_intervals(texts: list[str], duration: Fraction) -> list[dict[str, object]]:
    """Exact detector boundaries from per-graph frame metadata files; an interval still open at EOF closes at the
    independently measured duration and carries the EOF marker."""
    found: list[tuple[Fraction, Fraction, str, bool]] = []
    for text in texts:
        opened: dict[str, Fraction] = {}

        def close(kind: str, start: Fraction, end: Fraction) -> None:
            eof = end >= duration
            end = min(end, duration)
            if start < 0 or start > end:
                raise WorkerError("TOOL_FAILED")
            found.append((start, end, kind, eof))

        for line in text.splitlines():
            if re.fullmatch(rf"frame:[0-9]+ +pts:-?[0-9]+ +pts_time:{_DECIMAL}", line):
                continue
            key, separator, value = line.partition("=")
            if not separator or (key not in _INTERVAL_KEYS and key not in _IGNORED_KEYS):
                raise WorkerError("TOOL_FAILED")
            if key in _IGNORED_KEYS:
                continue
            kind, opening = _INTERVAL_KEYS[key]
            moment = _decimal(value, "TOOL_FAILED")
            if opening:
                if kind in opened:
                    raise WorkerError("TOOL_FAILED")
                opened[kind] = moment
            elif kind in opened:
                close(kind, opened.pop(kind), moment)
            else:
                raise WorkerError("TOOL_FAILED")
        for kind, start in opened.items():
            close(kind, start, duration)
    ordered = sorted(set(found), key=lambda item: (item[0], item[1], item[2]))
    if len(ordered) > _MAX_ENTRIES:
        raise WorkerError("OUTPUT_EXCEEDED")
    return [
        {"kind": kind, "start": _time(start), "end": _time(end), "ended_at_eof": eof}
        for start, end, kind, eof in ordered
    ]


def _filter_path(path: str) -> str:
    if re.fullmatch(r"/[A-Za-z0-9/_.-]+", path) is None:
        raise WorkerError("CONFIG_INVALID")
    return path


def intervals_recipe(config: dict[str, object], deadline: float) -> dict[str, object]:
    parameters, _, cap = _recipe(config)
    kinds = parameters.get("interval_kinds")
    if type(kinds) is not list or not set(kinds) <= {"BLACK", "FREEZE", "SILENCE"} or not kinds:
        raise WorkerError("CONFIG_INVALID")
    scratch = _paths(config["scratch"])
    media = probe_media(config, _target(config), deadline=deadline, failure="INPUT_INVALID")
    video_filters = []
    if "BLACK" in kinds:
        video_filters.append(
            f"blackdetect=d={_seconds(parameters, 'black_min_duration_ms')}"
            f":pic_th={_parameter_decimal(parameters, 'black_picture_ratio')}"
            f":pix_th={_parameter_decimal(parameters, 'black_pixel_threshold')}"
        )
    if "FREEZE" in kinds:
        video_filters.append(
            f"freezedetect=n={_parameter_decimal(parameters, 'freeze_noise_db')}dB"
            f":d={_seconds(parameters, 'freeze_min_duration_ms')}"
        )
    if (video_filters and media.video is None) or ("SILENCE" in kinds and not media.audio):
        raise WorkerError("INPUT_INVALID")
    argv = _media_argv(config, _target(config), level="error")
    files: list[str] = []
    if video_filters:
        files.append(scratch[0])
        video_filters.append(f"metadata=mode=print:file={_filter_path(scratch[0])}")
        argv += ["-map", "0:v:0", "-vf", ",".join(video_filters)]
    if "SILENCE" in kinds:
        files.append(scratch[1])
        argv += [
            "-map",
            "0:a:0",
            "-af",
            f"silencedetect=n={_parameter_decimal(parameters, 'silence_noise_db')}dB"
            f":d={_seconds(parameters, 'silence_min_duration_ms')},"
            f"ametadata=mode=print:file={_filter_path(scratch[1])}",
        ]
    argv += ["-filter_threads", "1", "-f", "null", "-"]
    code, _, errors = run_tool(argv, deadline=deadline, output_cap=cap)
    if code != 0 or errors:
        raise WorkerError("TOOL_FAILED")
    texts = [_read_bounded(path, cap, "OUTPUT_EXCEEDED").decode("utf-8", "replace") for path in files]
    intervals = parse_intervals(texts, media.duration)
    return {"kind": "INTERVALS", "measured_duration": _time(media.duration), "intervals": intervals}


def parse_loudness(text: str) -> dict[str, object]:
    """Read only the final ebur128 summary; gate-floor or -inf peak is SILENT, non-finite values UNMEASURABLE."""
    marker = text.rfind("] Summary:")
    if marker < 0:
        raise WorkerError("TOOL_FAILED")
    summary = text[marker:]
    integrated = re.search(r"^\s+I:\s+(\S+) LUFS$", summary, re.MULTILINE)
    peak = re.search(r"^\s+Peak:\s+(\S+) dBFS$", summary, re.MULTILINE)
    if integrated is None or peak is None:
        raise WorkerError("TOOL_FAILED")
    lufs, dbfs = integrated.group(1), peak.group(1)
    if dbfs == "-inf" or lufs == "-70.0":
        return {"kind": "LOUDNESS", "state": "SILENT", "integrated_lufs": None, "true_peak_dbfs": None}
    if re.fullmatch(_DECIMAL, lufs) is None or re.fullmatch(_DECIMAL, dbfs) is None:
        return {"kind": "LOUDNESS", "state": "UNMEASURABLE", "integrated_lufs": None, "true_peak_dbfs": None}
    return {"kind": "LOUDNESS", "state": "FINITE", "integrated_lufs": lufs, "true_peak_dbfs": dbfs}


def loudness_recipe(config: dict[str, object], deadline: float) -> dict[str, object]:
    _, _, cap = _recipe(config)
    media = probe_media(config, _target(config), deadline=deadline, failure="INPUT_INVALID")
    if not media.audio:
        return {"kind": "LOUDNESS", "state": "UNMEASURABLE", "integrated_lufs": None, "true_peak_dbfs": None}
    argv = _media_argv(config, _target(config), level="info")
    argv += ["-map", "0:a:0", "-af", "ebur128=peak=true:framelog=verbose", "-filter_threads", "1", "-f", "null", "-"]
    code, _, errors = run_tool(argv, deadline=deadline, output_cap=cap)
    if code != 0:
        raise WorkerError("TOOL_FAILED")
    return parse_loudness(errors.decode("utf-8", "replace"))


def _cue_time(hours: str | None, minutes: str, seconds: str, millis: str) -> Fraction:
    return Fraction(int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)) + Fraction(int(millis), 1000)


def parse_captions(raw: bytes, caption_format: object) -> list[tuple[Fraction, Fraction]]:
    """Strict UTF-8 SRT/WebVTT timing parser; caption text is never retained."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkerError("INPUT_INVALID") from None
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if "\r" in text or "\0" in text:
        raise WorkerError("INPUT_INVALID")
    blocks = [block for block in re.split(r"\n{2,}", text.strip("\n")) if block]
    cues: list[tuple[Fraction, Fraction]] = []
    if caption_format == "SRT":
        timing = (
            r"([0-9]{2,}):([0-5][0-9]):([0-5][0-9]),([0-9]{3}) --> ([0-9]{2,}):([0-5][0-9]):([0-5][0-9]),([0-9]{3})"
        )
        for block in blocks:
            lines = block.split("\n")
            match = re.fullmatch(timing, lines[1]) if len(lines) >= 3 else None
            if match is None or re.fullmatch(r"[0-9]+", lines[0]) is None:
                raise WorkerError("INPUT_INVALID")
            cues.append((_cue_time(*match.groups()[:4]), _cue_time(*match.groups()[4:])))
    elif caption_format == "WEBVTT":
        if not blocks or re.fullmatch(r"WEBVTT(?:[ \t][^\n]*)?", blocks[0].split("\n")[0]) is None:
            raise WorkerError("INPUT_INVALID")
        stamp = r"(?:([0-9]{2,}):)?([0-5][0-9]):([0-5][0-9])\.([0-9]{3})"
        for block in blocks[1:]:
            lines = block.split("\n")
            if re.match(r"(?:NOTE|STYLE|REGION)(?:[ \t]|$)", lines[0]):
                continue
            line = lines[0] if "-->" in lines[0] else (lines[1] if len(lines) > 1 else "")
            match = re.fullmatch(rf"{stamp} --> {stamp}(?:[ \t][^\n]*)?", line)
            if match is None:
                raise WorkerError("INPUT_INVALID")
            cues.append((_cue_time(*match.groups()[:4]), _cue_time(*match.groups()[4:])))
    else:
        raise WorkerError("CONFIG_INVALID")
    if len(cues) > _MAX_ENTRIES:
        raise WorkerError("INPUT_INVALID")
    return cues


def _read_bounded(path: str, limit: int, failure: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            raw = os.read(descriptor, limit + 1)
        finally:
            os.close(descriptor)
    except OSError:
        raise WorkerError(failure) from None
    if len(raw) > limit:
        raise WorkerError(failure)
    return raw


def captions_recipe(config: dict[str, object], deadline: float) -> dict[str, object]:
    parameters, inputs, _ = _recipe(config)
    caption = _input(inputs, "caption")
    if caption is None:
        raise WorkerError("CONFIG_INVALID")
    media = probe_media(config, _target(config), deadline=deadline, failure="INPUT_INVALID")
    duration = media.duration
    cues = sorted(
        parse_captions(_read_bounded(caption, _MAX_CAPTION_BYTES, "INPUT_INVALID"), parameters.get("caption_format"))
    )
    covered = Fraction(0)
    right = Fraction(0)
    overlaps = 0
    for start, end in cues:
        if not 0 <= start < end or end > duration:
            raise WorkerError("INPUT_INVALID")
        overlaps += int(start < right)
        covered += max(Fraction(0), end - max(start, right))
        right = max(right, end)
    return {
        "kind": "CAPTIONS",
        "format": parameters.get("caption_format"),
        "measured_duration": _time(duration),
        "cue_count": len(cues),
        "cue_times": [{"start": _time(start), "end": _time(end)} for start, end in cues],
        "union_coverage": _time(covered),
        "overlap_count": overlaps,
    }


def _member(value: object, key: str) -> object:
    if type(value) is not dict or key not in value:
        raise WorkerError("TOOL_FAILED")
    return value[key]


def vmaf_recipe(config: dict[str, object], deadline: float) -> dict[str, object]:
    """Pinned VMAF over exactly the first five decoded frames of comparable, zero-offset 8-bit 4:2:0 sources."""
    _, inputs, cap = _recipe(config)
    reference_path = _input(inputs, "reference")
    scratch = [str(path) for path in _paths(config["scratch"])]
    if reference_path is None:
        raise WorkerError("REFERENCE_INVALID")
    target = probe_media(config, _target(config), deadline=deadline, failure="INPUT_INVALID")
    reference = probe_media(config, reference_path, deadline=deadline, failure="REFERENCE_INVALID")
    video, other = target.video, reference.video
    if video is None or other is None:
        raise WorkerError("REFERENCE_INVALID")
    width, height, rate = video.width, video.height, video.rate
    if (
        (width, height, rate) != (other.width, other.height, other.rate)
        or video.start != 0
        or other.start != 0
        or width % 2
        or height % 2
        or width * height > _MAX_VMAF_PIXELS
        or not 1 <= rate <= 60
    ):
        raise WorkerError("REFERENCE_INVALID")
    expected = width * height * 3 // 2 * 5
    for source, destination, failure in (
        (_target(config), scratch[0], "INPUT_INVALID"),
        (reference_path, scratch[1], "REFERENCE_INVALID"),
    ):
        argv = _media_argv(config, source, level="error")
        argv[6:6] = ["-xerror"]
        argv += [
            "-map",
            "0:v:0",
            "-frames:v",
            "5",
            "-filter_threads",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p",
            "-y",
            destination,
        ]
        code, _, _ = run_tool(argv, deadline=deadline, output_cap=cap)
        if code != 0:
            raise WorkerError(failure)
        if os.stat(destination).st_size != expected:
            raise WorkerError("REFERENCE_INVALID")
    model, model_digest = _vmaf_model(config)
    argv = [
        _tool_path(config, "vmaf"),
        "--reference",
        scratch[1],
        "--distorted",
        scratch[0],
        "--width",
        str(width),
        "--height",
        str(height),
        "--pixel_format",
        "420",
        "--bitdepth",
        "8",
        "--model",
        "path=" + model,
        "--output",
        scratch[2],
        "--json",
        "--threads",
        "1",
        "--cpumask",
        "4294967295",
        "--frame_cnt",
        "5",
        "--quiet",
    ]
    code, _, _ = run_tool(argv, deadline=deadline, output_cap=cap)
    if code != 0:
        raise WorkerError("TOOL_FAILED")
    report = _strict_output(_read_bounded(scratch[2], cap, "OUTPUT_EXCEEDED"), "TOOL_FAILED")
    frames = _member(report, "frames")
    if type(frames) is not list or len(frames) != 5:
        raise WorkerError("TOOL_FAILED")
    if [_member(frame, "frameNum") for frame in frames] != [0, 1, 2, 3, 4]:
        raise WorkerError("TOOL_FAILED")
    scores = [_member(_member(frame, "metrics"), "vmaf") for frame in frames]
    mean = _member(_member(_member(report, "pooled_metrics"), "vmaf"), "mean")
    if any(type(score) is not str for score in scores) or type(mean) is not str:
        raise WorkerError("TOOL_FAILED")
    return {
        "kind": "REFERENCE_VMAF",
        "span": "FIRST_5_FRAMES",
        "width": width,
        "height": height,
        "frame_rate": _time(rate),
        "model_digest": model_digest,
        "frames": [{"index": index, "score": score} for index, score in enumerate(scores)],
        "mean": mean,
    }


RECIPES: dict[str, Callable[[dict[str, object], float], dict[str, object]]] = {
    "CONTAINER_STREAM": container_recipe,
    "DECODE": decode_recipe,
    "INTERVALS": intervals_recipe,
    "LOUDNESS": loudness_recipe,
    "CAPTIONS": captions_recipe,
    "REFERENCE_VMAF": vmaf_recipe,
}


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
