"""Shot-grammar findings over narration segments."""

from __future__ import annotations

from lib.shot_grammar import shot_grammar_issues


def _segment(sid: str, size: str, *, move: str = "Static", scene_break: bool = False) -> dict:
    return {
        "segment_id": sid,
        "segment_break": scene_break,
        "image_prompt": {"composition": {"shot_type": size}},
        "video_prompt": {"camera_motion": move},
    }


def test_a_well_covered_episode_has_no_findings():
    segments = [
        _segment("S1", "Long Shot"),
        _segment("S2", "Medium Shot"),
        _segment("S3", "Close-up"),
        _segment("S4", "Extreme Long Shot", scene_break=True),
    ]

    assert shot_grammar_issues(segments) == []


def test_findings_name_each_broken_rule():
    segments = [
        _segment("S1", "Medium Shot"),
        _segment("S2", "Medium Shot"),
        _segment("S3", "Medium Shot", move="Orbit"),
        _segment("S4", "Medium Shot", scene_break=True),
    ]

    assert shot_grammar_issues(segments) == [
        "S1: scene opens on Medium Shot, not a wide shot",
        "S3: Medium Shot for more than 2 shots in a row",
        "S3: camera move Orbit is unreliable for video models",
        "S4: scene opens on Medium Shot, not a wide shot",
        "episode has no close-up",
    ]
