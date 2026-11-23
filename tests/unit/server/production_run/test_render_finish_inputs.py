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


def test_an_episode_has_a_title_card_and_a_next_card_only_when_another_episode_follows(tmp_path):
    import json

    from lib.episode_adaptation import adaptation_record_relpath
    from server.production_run.render_adapter import episode_cards

    project = {"source_language": "vi", "episodes": [{"episode": 1, "title": "Bến sông"}, {"episode": 2}]}
    record = tmp_path / adaptation_record_relpath(1)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"draft": {"cliffhanger": "Vị khách cuối là ai?"}}), encoding="utf-8")

    assert episode_cards(project, tmp_path, 1) == ("Tập 1 · Bến sông", "Tập sau: Vị khách cuối là ai?")
    assert episode_cards(project, tmp_path, 2) == ("Tập 2", None)
    assert episode_cards({**project, "source_language": "en"}, tmp_path, 1)[0] == "Episode 1 · Bến sông"


def test_a_unit_plays_to_the_end_of_its_speech_and_a_silent_unit_holds_briefly():
    # drama smoke run b961dc0a: two silent 5 s clips opened the episode, first word at 10.1 s; the values follow the
    # donors (DramaClaw and huohuo-drama end a shot with its speech; OpenMontage holds a static shot at most 3 s)
    from server.production_run.render_adapter import SILENT_HOLD_US, SPEECH_TAIL_US, played_duration_us

    assert played_duration_us(5_041_667, 0) == SILENT_HOLD_US
    assert played_duration_us(2_000_000, 0) == 2_000_000
    assert played_duration_us(6_041_667, 2_720_000) == 2_720_000 + SPEECH_TAIL_US
    assert played_duration_us(4_000_000, 4_200_000) == 4_000_000
