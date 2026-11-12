"""Render one episode's exact presentations into a verified final MP4 with a subtitle sidecar.

Input is a snapshot of already-selected media: each unit names its video file and window, an optional narration
file placed inside that window, and the unit's subtitle cues. Nothing is chosen again from file names. Each unit is
encoded to the output contract (H.264/AAC, exact size and frame rate) with structured FFmpeg argv, the units are
concatenated, and the final is decoded in full and probed: streams, size, frame rate, duration against the sum of
the units, and audible audio where narration was placed. Before verification the concatenated audio is mastered to
the contract's loudness: a measuring pass, then a linear ``loudnorm`` pass with the measured values and a true-peak
ceiling, picture copied untouched; the before/after loudness is recorded in the manifest. Source files are hashed
before and after and must not change. Everything is written in a staging directory and moved into place only after verification; a failed or
cancelled render leaves no final behind.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

MICROSECONDS = 1_000_000
DURATION_TOLERANCE_SECONDS = 0.12
SILENCE_DB = -60.0
AUDIO_RATE = 48_000
#: Below this integrated loudness the final is treated as silent and is not mastered.
MASTER_FLOOR_LUFS = -70.0


class RenderRefused(ValueError):
    """The snapshot cannot form the contracted film; ``code`` is stable."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class RenderCue:
    start_us: int
    end_us: int
    text: str


@dataclass(frozen=True)
class RenderUnit:
    unit_id: str
    video_path: Path
    video_start_us: int
    duration_us: int
    video_audio: bool
    video_gain: float
    narration_path: Path | None = None
    narration_start_us: int = 0
    narration_duration_us: int = 0
    narration_gain: float = 1.0
    cues: tuple[RenderCue, ...] = ()


@dataclass(frozen=True)
class RenderContract:
    width: int
    height: int
    fps: int
    min_seconds: float
    max_seconds: float
    requires_narration: bool = True
    requires_subtitles: bool = True
    #: Integrated loudness target of the final (EBU R128 / ITU-R BS.1770); ``None`` leaves the mix as made.
    loudness_lufs: float | None = -14.0
    true_peak_db: float = -1.0
    loudness_range: float = 20.0


@dataclass(frozen=True)
class RenderInput:
    episode: int
    units: tuple[RenderUnit, ...]


@dataclass(frozen=True)
class RenderReceipt:
    final_path: Path
    final_sha256: str
    final_size: int
    subtitle_path: Path
    subtitle_sha256: str
    manifest_path: Path
    manifest_sha256: str
    duration_seconds: float
    source_hashes: dict[str, str] = field(default_factory=dict)
    tool_version: str = ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(argv: Sequence[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise RenderRefused("RENDER_TIMEOUT", argv[0]) from None
    if completed.returncode != 0:
        raise RenderRefused("RENDER_TOOL_FAILED", completed.stderr[-2000:])
    return completed


def _seconds(us: int) -> str:
    return f"{us / MICROSECONDS:.6f}"


def _timestamp(us: int) -> str:
    total_ms = round(us / 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _validate(episode: RenderInput, contract: RenderContract) -> None:
    if not episode.units:
        raise RenderRefused("NO_PRESENTATIONS")
    total = 0
    for unit in episode.units:
        if unit.duration_us <= 0 or unit.video_start_us < 0:
            raise RenderRefused("INVALID_UNIT_WINDOW", unit.unit_id)
        if not unit.video_path.is_file():
            raise RenderRefused("SOURCE_MEDIA_MISSING", unit.unit_id)
        if unit.narration_path is not None:
            if not unit.narration_path.is_file():
                raise RenderRefused("SOURCE_MEDIA_MISSING", unit.unit_id)
            end = unit.narration_start_us + unit.narration_duration_us
            if unit.narration_start_us < 0 or unit.narration_duration_us <= 0 or end > unit.duration_us:
                raise RenderRefused("NARRATION_EXCEEDS_UNIT", unit.unit_id)
        for cue in unit.cues:
            if not 0 <= cue.start_us < cue.end_us <= unit.duration_us or not cue.text.strip():
                raise RenderRefused("SUBTITLE_OUTSIDE_UNIT", unit.unit_id)
        total += unit.duration_us
    seconds = total / MICROSECONDS
    if not contract.min_seconds <= seconds <= contract.max_seconds:
        raise RenderRefused("DURATION_OUTSIDE_CONTRACT", f"{seconds:.3f}s")
    if contract.requires_narration and not any(u.narration_path is not None for u in episode.units):
        raise RenderRefused("NARRATION_MISSING")
    if contract.requires_subtitles and not any(u.cues for u in episode.units):
        raise RenderRefused("SUBTITLES_MISSING")


def _unit_argv(unit: RenderUnit, output: Path, contract: RenderContract, ffmpeg: str) -> list[str]:
    duration = _seconds(unit.duration_us)
    argv = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    argv += ["-ss", _seconds(unit.video_start_us), "-t", duration, "-i", str(unit.video_path)]
    if unit.narration_path is not None:
        argv += ["-i", str(unit.narration_path)]
    video = (
        f"[0:v]scale={contract.width}:{contract.height}:force_original_aspect_ratio=decrease,"
        f"pad={contract.width}:{contract.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={contract.fps},"
        f"format=yuv420p,trim=duration={duration},setpts=PTS-STARTPTS[v]"
    )
    silence = f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=duration={duration}[base]"
    parts = [video, silence]
    mix = ["[base]"]
    if unit.video_audio and _has_audio(unit.video_path, ffmpeg):
        parts.append(
            f"[0:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo,volume={unit.video_gain:.4f},"
            f"atrim=duration={duration},asetpts=PTS-STARTPTS[va]"
        )
        mix.append("[va]")
    if unit.narration_path is not None:
        delay = round(unit.narration_start_us / 1000)
        parts.append(
            f"[1:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo,volume={unit.narration_gain:.4f},"
            f"atrim=duration={_seconds(unit.narration_duration_us)},adelay={delay}|{delay},asetpts=PTS-STARTPTS[na]"
        )
        mix.append("[na]")
    parts.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,atrim=duration={duration}[a]")
    argv += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]"]
    argv += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(contract.fps), "-pix_fmt", "yuv420p"]
    argv += ["-c:a", "aac", "-b:a", "160k", "-ar", str(AUDIO_RATE), "-ac", "2", "-t", duration]
    argv += ["-movflags", "+faststart", str(output)]
    return argv


def _has_audio(path: Path, ffmpeg: str) -> bool:
    ffprobe = str(Path(ffmpeg).with_name("ffprobe")) if os.sep in ffmpeg else "ffprobe"
    completed = _run(
        [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(path)],
        timeout=60,
    )
    return bool(json.loads(completed.stdout or "{}").get("streams"))


def _probe(path: Path, ffprobe: str) -> dict:
    completed = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        timeout=120,
    )
    return json.loads(completed.stdout or "{}")


def _mean_volume(path: Path, ffmpeg: str, start_us: int, duration_us: int) -> float:
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-ss",
            _seconds(start_us),
            "-t",
            _seconds(duration_us),
            "-i",
            str(path),
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    match = re.search(r"mean_volume:\s*(-?[0-9.]+|-inf) dB", completed.stderr)
    if completed.returncode != 0 or match is None:
        raise RenderRefused("AUDIO_PROBE_FAILED")
    value = match.group(1)
    return -math.inf if value == "-inf" else float(value)


def measure_loudness(
    path: Path, *, ffmpeg: str = "ffmpeg", target: tuple[float, float, float] = (-14.0, -1.0, 20.0)
) -> dict[str, str]:
    """``loudnorm`` measurement of ``path``'s audio: integrated LUFS, true peak, range and threshold (strings as
    ffmpeg prints them, ``-inf`` for silence)."""
    integrated, peak, lra = target
    completed = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-i",
            str(path),
            "-vn",
            "-af",
            f"loudnorm=I={integrated}:TP={peak}:LRA={lra}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    start = completed.stderr.rfind("{")
    if completed.returncode != 0 or start < 0:
        raise RenderRefused("AUDIO_PROBE_FAILED", "loudness measurement")
    try:
        values = json.loads(completed.stderr[start : completed.stderr.rfind("}") + 1])
    except ValueError as error:
        raise RenderRefused("AUDIO_PROBE_FAILED", "loudness measurement") from error
    return {key: str(values[key]) for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


def _lufs(value: str) -> float:
    return -math.inf if value.strip().lower() in {"-inf", "inf", "nan"} else float(value)


def _master(final: Path, mastered: Path, contract: RenderContract, *, ffmpeg: str) -> dict[str, float | bool] | None:
    """Master ``final``'s audio into ``mastered`` (picture copied); ``None`` when the contract asks for no mastering
    or the audio is silent."""
    if contract.loudness_lufs is None:
        return None
    target = (contract.loudness_lufs, contract.true_peak_db, contract.loudness_range)
    before = measure_loudness(final, ffmpeg=ffmpeg, target=target)
    if _lufs(before["input_i"]) <= MASTER_FLOOR_LUFS:
        return None
    integrated, peak, lra = target
    audio = (
        f"loudnorm=I={integrated}:TP={peak}:LRA={lra}:linear=true:"
        f"measured_I={before['input_i']}:measured_TP={before['input_tp']}:measured_LRA={before['input_lra']}:"
        f"measured_thresh={before['input_thresh']}:offset={before['target_offset']},aresample={AUDIO_RATE}"
    )
    _run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(final),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "copy",
            "-af",
            audio,
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            str(AUDIO_RATE),
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(mastered),
        ],
        timeout=900,
    )
    after = measure_loudness(mastered, ffmpeg=ffmpeg, target=target)
    return {
        "target_lufs": integrated,
        "true_peak_ceiling_db": peak,
        "input_lufs": _lufs(before["input_i"]),
        "input_true_peak_db": _lufs(before["input_tp"]),
        "output_lufs": _lufs(after["input_i"]),
        "output_true_peak_db": _lufs(after["input_tp"]),
    }


def _verify(final: Path, episode: RenderInput, contract: RenderContract, *, ffmpeg: str, ffprobe: str) -> float:
    _run(
        [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-i", str(final), "-f", "null", "-"], timeout=900
    )
    probe = _probe(final, ffprobe)
    streams = probe.get("streams") or []
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise RenderRefused("FINAL_STREAMS_INVALID")
    video, audio = videos[0], audios[0]
    if (video.get("codec_name"), audio.get("codec_name")) != ("h264", "aac"):
        raise RenderRefused("FINAL_CODEC_INVALID")
    if (video.get("width"), video.get("height")) != (contract.width, contract.height):
        raise RenderRefused("FINAL_SIZE_INVALID")
    numerator, _, denominator = str(video.get("r_frame_rate", "0/1")).partition("/")
    if abs(int(numerator) / max(1, int(denominator or 1)) - contract.fps) > 0.01:
        raise RenderRefused("FINAL_FPS_INVALID")
    duration = float((probe.get("format") or {}).get("duration") or 0)
    expected = sum(u.duration_us for u in episode.units) / MICROSECONDS
    if abs(duration - expected) > DURATION_TOLERANCE_SECONDS:
        raise RenderRefused("FINAL_DURATION_MISMATCH", f"{duration:.3f}s vs {expected:.3f}s")
    offset = 0
    for unit in episode.units:
        if unit.narration_path is not None:
            start = offset + unit.narration_start_us
            if _mean_volume(final, ffmpeg, start, unit.narration_duration_us) <= SILENCE_DB:
                raise RenderRefused("NARRATION_INAUDIBLE", unit.unit_id)
        offset += unit.duration_us
    return duration


def _subtitles(episode: RenderInput) -> str:
    lines: list[str] = []
    offset = 0
    index = 1
    for unit in episode.units:
        for cue in unit.cues:
            lines += [
                str(index),
                f"{_timestamp(offset + cue.start_us)} --> {_timestamp(offset + cue.end_us)}",
                cue.text.strip(),
                "",
            ]
            index += 1
        offset += unit.duration_us
    return "\n".join(lines)


def _sources(episode: RenderInput) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for unit in episode.units:
        for path in (unit.video_path, unit.narration_path):
            if path is not None and str(path) not in hashes:
                hashes[str(path)] = sha256_file(path)
    return hashes


def render_presentations(
    *,
    episode: RenderInput,
    output_dir: Path,
    contract: RenderContract,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> RenderReceipt:
    _validate(episode, contract)
    before = _sources(episode)
    version = _run([ffmpeg, "-hide_banner", "-version"], timeout=30).stdout.splitlines()[0]
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = output_dir / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    try:
        segments: list[Path] = []
        for index, unit in enumerate(episode.units):
            segment = staging / f"unit_{index:04d}.mp4"
            _run(_unit_argv(unit, segment, contract, ffmpeg), timeout=max(120.0, unit.duration_us / MICROSECONDS * 30))
            segments.append(segment)
        listing = staging / "concat.txt"
        listing.write_text("".join(f"file '{segment.name}'\n" for segment in segments), encoding="utf-8")
        final = staging / f"episode_{episode.episode}.mp4"
        _run(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(final),
            ],
            timeout=600,
        )
        mastered = staging / f"mastered_{episode.episode}.mp4"
        loudness = _master(final, mastered, contract, ffmpeg=ffmpeg)
        if loudness is not None:
            os.replace(mastered, final)
        duration = _verify(final, episode, contract, ffmpeg=ffmpeg, ffprobe=ffprobe)
        if _sources(episode) != before:
            raise RenderRefused("SOURCE_MEDIA_CHANGED")
        subtitle = staging / f"episode_{episode.episode}.srt"
        subtitle.write_text(_subtitles(episode), encoding="utf-8")
        manifest_body = {
            "schema": "r2.production-render-manifest.v1",
            "episode": episode.episode,
            "contract": asdict(contract),
            "tool_version": version,
            "duration_seconds": duration,
            "final_sha256": sha256_file(final),
            "loudness": loudness,
            "subtitle_sha256": sha256_file(subtitle),
            "units": [
                {
                    "unit_id": unit.unit_id,
                    "video": {
                        "path": str(unit.video_path),
                        "sha256": before[str(unit.video_path)],
                        "start_us": unit.video_start_us,
                        "duration_us": unit.duration_us,
                    },
                    "narration": None
                    if unit.narration_path is None
                    else {
                        "path": str(unit.narration_path),
                        "sha256": before[str(unit.narration_path)],
                        "start_us": unit.narration_start_us,
                        "duration_us": unit.narration_duration_us,
                    },
                    "cues": [asdict(cue) for cue in unit.cues],
                }
                for unit in episode.units
            ],
        }
        manifest = staging / f"episode_{episode.episode}.manifest.json"
        manifest.write_text(json.dumps(manifest_body, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        placed: list[Path] = []
        for staged in (final, subtitle, manifest):
            target = output_dir / staged.name
            os.replace(staged, target)
            placed.append(target)
        final_path, subtitle_path, manifest_path = placed
        return RenderReceipt(
            final_path=final_path,
            final_sha256=sha256_file(final_path),
            final_size=final_path.stat().st_size,
            subtitle_path=subtitle_path,
            subtitle_sha256=sha256_file(subtitle_path),
            manifest_path=manifest_path,
            manifest_sha256=sha256_file(manifest_path),
            duration_seconds=duration,
            source_hashes=before,
            tool_version=version,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


__all__ = [
    "RenderContract",
    "RenderCue",
    "RenderInput",
    "RenderReceipt",
    "RenderRefused",
    "RenderUnit",
    "measure_loudness",
    "render_presentations",
    "sha256_file",
]
