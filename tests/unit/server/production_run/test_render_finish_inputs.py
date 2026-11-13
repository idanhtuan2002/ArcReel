"""What the render step asks the renderer for: a camera move per held picture and the project's grade."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from lib.music_bed import MusicUnavailable
from lib.presentation_renderer import RenderInput, RenderUnit
from server.production_run.render_adapter import MUSIC_DIR, RenderAdapter, _planned_moves, film_grade


def test_each_segment_gets_the_move_its_planned_camera_motion_allows():
    script = {
        "content_mode": "narration",
        "segments": [
            {"segment_id": "E1S01", "video_prompt": {"camera_motion": "Push In"}},
            {"segment_id": "E1S02", "video_prompt": {"camera_motion": "Orbit"}},
            {"segment_id": "E1S03", "video_prompt": "free text prompt"},
        ],
    }

    assert _planned_moves(script) == {"E1S01": "push_in", "E1S02": "drift", "E1S03": "static"}


def test_the_grade_comes_from_the_overview_and_falls_back_to_neutral():
    assert film_grade({"overview": {"color_grade": "moody_dark"}}) == "moody_dark"
    assert film_grade({"overview": {"color_grade": "sepia"}}) == "neutral"
    assert film_grade({}) == "neutral"


class _Music:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.cues = fail, []

    async def render(self, cue, output):
        self.cues.append(cue)
        if self.fail:
            raise MusicUnavailable("down")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"wav")
        return output


PROJECT = {"overview": {"music_caption": "slow piano", "music_bpm": 70}}
SNAPSHOT = RenderInput(
    episode=1,
    units=(
        RenderUnit(
            unit_id="E1S01",
            video_path=Path("v.mp4"),
            video_start_us=0,
            duration_us=40_000_000,
            video_audio=False,
            video_gain=1.0,
        ),
    ),
)


@pytest.mark.asyncio
async def test_the_episode_gets_its_music_bed_from_the_cue(tmp_path: Path):
    music = _Music()
    adapter = RenderAdapter(
        cast(Any, None), authority=cast(Any, None), projects=cast(Any, None), music=cast(Any, music)
    )

    snapshot = await adapter._with_music(tmp_path, PROJECT, SNAPSHOT)

    assert snapshot.music_path == tmp_path / MUSIC_DIR / f"{music.cues[0].digest()}.wav"
    assert music.cues[0].seconds == 44.0


@pytest.mark.asyncio
async def test_a_music_failure_renders_without_music(tmp_path: Path):
    adapter = RenderAdapter(
        cast(Any, None), authority=cast(Any, None), projects=cast(Any, None), music=cast(Any, _Music(fail=True))
    )

    assert (await adapter._with_music(tmp_path, PROJECT, SNAPSHOT)).music_path is None
    assert (await adapter._with_music(tmp_path, {}, SNAPSHOT)).music_path is None
