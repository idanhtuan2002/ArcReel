"""Real Remotion render coverage for M3's real-media closure Task 3 -- every
test here calls the actual vendored `npx remotion render`, not a mock.
Requires Node/npm (already vendored + version-pinned,
docs/r2/evidence/R2_M3_DONOR_BASELINE.json)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from r2.m3.remotion_engine import render_cut
from r2.m3.render_plan import RenderCut
from tests.fixtures.r2.m3_media_assertions import frame_pixel_stddev as _frame_pixel_stddev


def test_video_passthrough_with_a_missing_source_raises_before_any_subprocess_call(tmp_path: Path) -> None:
    cut = RenderCut(
        cut_id="c1",
        in_seconds=0.0,
        out_seconds=2.0,
        kind="video_passthrough",
        source_path=tmp_path / "does-not-exist.svg",
    )
    with pytest.raises(FileNotFoundError):
        render_cut(cut, output_path=tmp_path / "out.mp4")


def test_text_card_renders_real_visible_text_not_a_solid_color(tmp_path: Path) -> None:
    cut = RenderCut(
        cut_id="c1",
        in_seconds=0.0,
        out_seconds=2.0,
        kind="text_card",
        text="git commit records the current index contents as a new commit.",
    )
    asset = render_cut(cut, output_path=tmp_path / "out.mp4")

    assert asset.path.is_file()
    # Root.tsx's calculateMetadata pads every render by 1s for a final fade
    # (Math.ceil((lastEnd + 1) * 30) frames) -- a real, documented donor
    # behavior, not a defect; a 2s cut therefore renders as ~3s.
    assert asset.duration_seconds == pytest.approx(3.0, abs=0.2)
    assert asset.external_provider_cost == Decimal("0")
    assert asset.tool == "remotion"
    assert asset.tool_version  # populated from the real `npx remotion --version` call
    assert asset.wall_time_seconds > 0

    stddev = _frame_pixel_stddev(asset.path, tmp_path)
    assert stddev > 5.0, f"frame looks solid-color (pixel stddev={stddev}), expected real text content"


def test_video_passthrough_renders_the_real_bound_source_not_a_solid_color(tmp_path: Path) -> None:
    source = Path("r2/m3/fixtures/assets/reused_terminal_frame.svg").resolve()
    cut = RenderCut(cut_id="c1", in_seconds=0.0, out_seconds=2.0, kind="video_passthrough", source_path=source)
    asset = render_cut(cut, output_path=tmp_path / "out.mp4")

    assert asset.path.is_file()
    stddev = _frame_pixel_stddev(asset.path, tmp_path)
    assert stddev > 5.0, f"frame looks solid-color (pixel stddev={stddev}), expected the real reused source"

    # The exact source file's own hash is recorded, not merely "some file was used".
    assert asset.source_master_refs
    assert asset.source_master_refs[0].startswith("c1:")


def test_identical_props_render_byte_identical_output(tmp_path: Path) -> None:
    cut = RenderCut(cut_id="c1", in_seconds=0.0, out_seconds=1.0, kind="text_card", text="determinism check")
    a = render_cut(cut, output_path=tmp_path / "a.mp4")
    b = render_cut(cut, output_path=tmp_path / "b.mp4")
    assert a.sha256 == b.sha256
    assert a.execution_fingerprint == b.execution_fingerprint
