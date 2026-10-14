"""The format projection FFmpeg invocation on real media (M8-E E2)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from r2.advanced_creative.format_render import execution_identity, materialize, pixel_geometry, render_argv
from r2.advanced_creative.formats import Box, FormatInvalidError, ReframeKind, build_plan, reframe_decision
from tests.unit.r2.advanced_creative.test_formats import DIGEST, overlay, profile

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def make_source(path: Path, *, width: int = 1280, height: int = 720, audio: bool = True, seconds: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s={width}x{height}:d={seconds}:r=30",
    ]
    if audio:
        argv += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    argv += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1"]
    argv += ["-c:a", "aac", "-shortest"] if audio else ["-an"]
    subprocess.run([*argv, str(path)], check=True, capture_output=True)
    return path


def probe(path: Path) -> dict:
    raw = subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    return json.loads(raw)


def plan_for(width: int, height: int, kind: ReframeKind, focal: Box | None = None, source=(1280, 720)):
    target = profile(width, height, profile_ref=f"p-{width}x{height}")
    decision = reframe_decision(
        decision_id="r1", kind=kind, source_size=source, profile=target, focal=focal, rationale="fixture"
    )
    return build_plan(
        plan_id=f"plan-{width}x{height}-{kind}",
        source_master_id="episode_video:1@v1",
        source_master_digest=DIGEST,
        profile=target,
        overlay=overlay(),
        decisions=(decision,),
    )


def render(plan, source: Path, output: Path, *, audio: bool = True) -> Path:
    argv = render_argv(plan, source_width=1280, source_height=720, has_audio=audio)
    subprocess.run(materialize(argv, source=str(source), output=str(output)), check=True, capture_output=True)
    return output


@pytest.mark.parametrize(
    ("width", "height", "kind"),
    [
        (1920, 1080, ReframeKind.PAD),
        (1080, 1920, ReframeKind.PAD),
        (1080, 1920, ReframeKind.COVER_CENTER),
        (1080, 1080, ReframeKind.COVER_CENTER),
    ],
)
def test_every_v1_ratio_renders_at_the_exact_profile(
    tmp_path: Path, width: int, height: int, kind: ReframeKind
) -> None:
    source = make_source(tmp_path / "in.mp4")
    out = render(plan_for(width, height, kind), source, tmp_path / "out.mp4")

    facts = probe(out)
    video = next(s for s in facts["streams"] if s["codec_type"] == "video")
    audio = [s for s in facts["streams"] if s["codec_type"] == "audio"]
    assert (video["width"], video["height"], video["codec_name"], video["pix_fmt"]) == (
        width,
        height,
        "h264",
        "yuv420p",
    )
    assert Fraction(video["r_frame_rate"]) == 30
    assert [s["codec_name"] for s in audio] == ["aac"]
    assert abs(float(facts["format"]["duration"]) - 2.0) < 0.1


def test_the_same_inputs_render_identical_bytes_and_identity(tmp_path: Path) -> None:
    source = make_source(tmp_path / "in.mp4")
    plan = plan_for(
        1080, 1920, ReframeKind.COVER_FOCAL, focal=Box(Fraction(1, 20), Fraction(1, 4), Fraction(1, 5), Fraction(3, 4))
    )
    first = render(plan, source, tmp_path / "a.mp4")
    second = render(plan, source, tmp_path / "b.mp4")

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    argv = render_argv(plan, source_width=1280, source_height=720, has_audio=True)
    identity = execution_identity(plan, source_digest=DIGEST, argv=argv, ffmpeg_version="8.0.1")
    assert identity == execution_identity(plan, source_digest=DIGEST, argv=argv, ffmpeg_version="8.0.1")
    assert identity != execution_identity(plan, source_digest=DIGEST, argv=argv, ffmpeg_version="7.1")
    assert identity != execution_identity(plan, source_digest="sha256:" + "e" * 64, argv=argv, ffmpeg_version="8.0.1")


def test_focal_cover_keeps_the_focal_side_of_the_frame() -> None:
    focal = Box(Fraction(1, 20), Fraction(1, 4), Fraction(1, 5), Fraction(3, 4))
    left = pixel_geometry(
        plan_for(1080, 1920, ReframeKind.COVER_FOCAL, focal=focal), source_width=1280, source_height=720
    )
    center = pixel_geometry(plan_for(1080, 1920, ReframeKind.COVER_CENTER), source_width=1280, source_height=720)
    assert (left.crop_x, left.crop_width, left.crop_height) == (0, 404, 720)
    assert center.crop_x == 438
    pad = pixel_geometry(plan_for(1080, 1920, ReframeKind.PAD), source_width=1280, source_height=720)
    assert (pad.scaled_width, pad.scaled_height, pad.pad_x, pad.pad_y) == (1080, 608, 0, 656)


def test_a_silent_source_renders_without_audio_and_sizes_must_match(tmp_path: Path) -> None:
    source = make_source(tmp_path / "in.mp4", audio=False)
    out = render(plan_for(1080, 1080, ReframeKind.PAD), source, tmp_path / "out.mp4", audio=False)
    assert [s["codec_type"] for s in probe(out)["streams"]] == ["video"]
    with pytest.raises(FormatInvalidError, match="another source size"):
        render_argv(plan_for(1080, 1080, ReframeKind.PAD), source_width=1920, source_height=1080, has_audio=False)
    with pytest.raises(FormatInvalidError, match="allows none"):
        render_argv(
            plan_for(1080, 1080, ReframeKind.PAD).model_copy(
                update={"output_profile": profile(1080, 1080, audio_codec=None)}
            ),
            source_width=1280,
            source_height=720,
            has_audio=True,
        )
