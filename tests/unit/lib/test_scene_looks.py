"""Which scene each shot belongs to, which looks an authoring writes, and how they reach the shots."""

from __future__ import annotations

from lib.scene_looks import apply_looks, kept_look, looks_to_write, scene_starts

PLAN = [
    {"segment_id": "E1S01"},
    {"segment_id": "E1S02", "segment_break": False},
    {"segment_id": "E1S03", "segment_break": True},
    {"segment_id": "E1S04"},
]
STARTS = {"E1S01": "E1S01", "E1S02": "E1S01", "E1S03": "E1S03", "E1S04": "E1S03"}


def test_a_scene_runs_from_its_break_to_the_next():
    assert scene_starts(PLAN) == STARTS


def test_only_rewritten_scene_starts_or_lookless_kept_scenes_are_written():
    assert looks_to_write(STARTS, ["E1S02", "E1S04"], {"E1S01": {"mood": "a"}}) == ["E1S03"]
    assert looks_to_write(STARTS, ["E1S01", "E1S02"], {"E1S01": {"mood": "a"}}) == ["E1S01"]
    assert looks_to_write(STARTS, ["E1S02"], {}) == ["E1S01"]


def test_written_looks_win_over_kept_ones_and_reach_every_shot_of_the_scene():
    segments = [{"segment_id": sid, "image_prompt": {"scene": sid}} for sid in ("E1S02", "E1S03", "E1S04")]

    apply_looks(segments, STARTS, {"E1S03": {"mood": "new"}}, {"E1S01": {"mood": "kept"}, "E1S03": {"mood": "old"}})

    assert [kept_look(segment) for segment in segments] == [{"mood": "kept"}, {"mood": "new"}, {"mood": "new"}]
