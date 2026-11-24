from __future__ import annotations

from pathlib import Path

from assembly import finish
from assembly.connector.film import RunState


def test_cues_follow_each_beats_audio_scaled_to_the_film() -> None:
    beats = [
        {"narration_segment": "Một.", "audio_duration_seconds": 2.0},
        {"narration_segment": "", "audio_duration_seconds": 1.0},
        {"narration_segment": "Ba.", "audio_duration_seconds": 1.0},
    ]
    cues = finish.caption_cues(beats, film_seconds=2.0)
    assert [(c.start_us, c.end_us, c.text) for c in cues] == [(0, 1_000_000, "Một."), (1_500_000, 2_000_000, "Ba.")]


def test_no_audio_lengths_give_no_cues() -> None:
    assert finish.caption_cues([{"narration_segment": "x"}], film_seconds=3.0) == ()


def test_a_state_file_keeps_its_finish_results(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    RunState(project_id="P", title="t", spine="narrated", finished={"1": {"final": "/f.mp4"}}).save(path)
    assert RunState.load(path).finished == {"1": {"final": "/f.mp4"}}
