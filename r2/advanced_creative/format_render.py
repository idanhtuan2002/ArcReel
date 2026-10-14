"""Deterministic FFmpeg invocation for one format projection plan (M8-E E2).

The plan's reframe spans become exact pixel geometry: a crop window (COVER_*) or an inner placement
(PAD), always on even pixel boundaries. Encoding is pinned (libx264 yuv420p, single thread, bitexact
flags, no metadata) so the same source bytes, plan and FFmpeg version give the same execution
identity. The identity binds the source digest, the plan digest (which covers profile, overlay and
reframe), the argv template, the FFmpeg version and this adapter's version.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from fractions import Fraction

from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.formats import Box, FormatInvalidError, ReframeKind
from r2.contracts.advanced_creative import FormatProjectionPlan

ADAPTER_VERSION = "ffmpeg-format-projection@1"
SOURCE_TOKEN = "{source}"
OUTPUT_TOKEN = "{output}"


def _even(value: Fraction) -> int:
    """Round to the nearest even pixel count (ties go down), never below 2."""
    pixels = int(value) // 2 * 2
    if value - pixels > 1:
        pixels += 2
    return max(pixels, 2)


@dataclass(frozen=True)
class PixelGeometry:
    crop_width: int
    crop_height: int
    crop_x: int
    crop_y: int
    scaled_width: int
    scaled_height: int
    pad_x: int
    pad_y: int
    target_width: int
    target_height: int


def pixel_geometry(plan: FormatProjectionPlan, *, source_width: int, source_height: int) -> PixelGeometry:
    """The exact even-pixel crop, scale and pad the plan's single reframe decision describes."""
    decision = plan.reframe_decisions[0]
    source = decision.source_span.model_dump(mode="python")
    target = decision.target_span.model_dump(mode="python")
    if (source.get("width"), source.get("height")) != (source_width, source_height):
        raise FormatInvalidError("the plan was built for another source size")
    window = Box.parse(source)
    placed = Box.parse(target)
    out_w, out_h = plan.output_profile.width, plan.output_profile.height
    crop_w = _even((window.x1 - window.x0) * source_width)
    crop_h = _even((window.y1 - window.y0) * source_height)
    crop_x = min(_even(window.x0 * source_width) if window.x0 else 0, source_width - crop_w)
    crop_y = min(_even(window.y0 * source_height) if window.y0 else 0, source_height - crop_h)
    scaled_w = _even((placed.x1 - placed.x0) * out_w)
    scaled_h = _even((placed.y1 - placed.y0) * out_h)
    pad_x = (out_w - scaled_w) // 2 // 2 * 2 if ReframeKind(decision.kind) is ReframeKind.PAD else 0
    pad_y = (out_h - scaled_h) // 2 // 2 * 2 if ReframeKind(decision.kind) is ReframeKind.PAD else 0
    return PixelGeometry(crop_w, crop_h, crop_x, crop_y, scaled_w, scaled_h, pad_x, pad_y, out_w, out_h)


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
