"""Deterministic FFmpeg invocation for one format projection plan (M8-E E2).

The plan's reframe spans become exact pixel geometry: a crop window (COVER_*) or an inner placement
(PAD), always on even pixel boundaries. Encoding is pinned (libx264 yuv420p, single thread, bitexact
flags, no metadata) so the same source bytes, plan and FFmpeg version give the same execution
identity. The identity binds the source digest, the plan digest (which covers profile, overlay and
reframe), the argv template, the FFmpeg version and this adapter's version.
"""

from __future__ import annotations

import hashlib
from fractions import Fraction

from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.formats import FormatInvalidError, PixelGeometry, pixel_geometry
from r2.contracts.advanced_creative import FormatProjectionPlan

ADAPTER_VERSION = "ffmpeg-format-projection@1"
SOURCE_TOKEN = "{source}"
OUTPUT_TOKEN = "{output}"


def filter_graph(geometry: PixelGeometry, fps: Fraction) -> str:
    g = geometry
    return (
        f"crop={g.crop_width}:{g.crop_height}:{g.crop_x}:{g.crop_y},"
        f"scale={g.scaled_width}:{g.scaled_height}:flags=lanczos,"
        f"pad={g.target_width}:{g.target_height}:{g.pad_x}:{g.pad_y}:color=black,"
        f"fps={fps.numerator}/{fps.denominator},setsar=1,format=yuv420p"
    )


def render_argv(
    plan: FormatProjectionPlan, *, source_width: int, source_height: int, has_audio: bool
) -> tuple[str, ...]:
    """The FFmpeg argv with ``{source}`` and ``{output}`` placeholders; audio is kept only if present."""
    profile = plan.output_profile
    geometry = pixel_geometry(plan, source_width=source_width, source_height=source_height)
    argv = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-i",
        SOURCE_TOKEN,
        "-map",
        "0:v:0",
        "-vf",
        filter_graph(geometry, profile.fps),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-threads",
        "1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
    ]
    if has_audio:
        if profile.audio_codec is None:
            raise FormatInvalidError("the source has audio but the profile allows none")
        argv += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "160k", "-flags:a", "+bitexact"]
    else:
        argv += ["-an"]
    if profile.duration_limit_seconds is not None:
        argv += ["-t", format(profile.duration_limit_seconds.normalize(), "f")]
    argv += ["-f", "mp4", OUTPUT_TOKEN]
    return tuple(argv)


def execution_identity(
    plan: FormatProjectionPlan, *, source_digest: str, argv: tuple[str, ...], ffmpeg_version: str
) -> str:
    """The render execution id: same inputs, same encoder, same id."""
    key = canonical_json_bytes(
        {
            "adapter_version": ADAPTER_VERSION,
            "plan_digest": plan.plan_digest,
            "source_master_digest": plan.source_master_digest,
            "source_digest": source_digest,
            "argv": list(argv),
            "ffmpeg_version": ffmpeg_version,
        }
    )
    return "fmt-" + hashlib.sha256(key).hexdigest()[:40]


def materialize(argv: tuple[str, ...], *, source: str, output: str) -> list[str]:
    return [source if part == SOURCE_TOKEN else output if part == OUTPUT_TOKEN else part for part in argv]


__all__ = [
    "ADAPTER_VERSION",
    "PixelGeometry",
    "execution_identity",
    "filter_graph",
    "materialize",
    "pixel_geometry",
    "render_argv",
]
