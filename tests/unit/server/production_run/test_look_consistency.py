"""A storyboard lit or coloured unlike the rest of its scene is found by numbers, not by a model."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from server.production_run.media_adapter import MediaAdapter
from server.production_run.unit_checks import look_outliers, look_stats

LOOK = {
    "time_of_day": "night",
    "key_light": "lamp",
    "palette": ["#111111", "#ddaa55"],
    "palette_note": "n",
    "mood": "m",
}


def _picture(path: Path, rgb: tuple[int, int, int]) -> Path:
    Image.new("RGB", (64, 112), rgb).save(path)
    return path


def test_a_shot_far_from_its_scene_is_an_outlier_and_short_scenes_are_not_judged():
    scenes = {
        "S1": [("a", (90.0, 0.10)), ("b", (95.0, 0.12)), ("c", (160.0, 0.11)), ("d", (92.0, -0.10))],
        "S5": [("e", (20.0, 0.5)), ("f", (200.0, -0.5))],
    }

    assert look_outliers(scenes) == ["c", "d"]


def test_look_stats_reads_brightness_and_warmth(tmp_path: Path):
    luma, warmth = look_stats(_picture(tmp_path / "w.png", (200, 120, 40))) or (0, 0)

    assert 120 < luma < 150
    assert warmth > 0.6
    assert look_stats(tmp_path / "missing.png") is None


def test_only_shots_carrying_a_scene_look_are_grouped_by_scene(tmp_path: Path):
    items = []
    for sid, rgb, scene_break, look in (
        ("E1S01", (90, 80, 70), False, LOOK),
        ("E1S02", (92, 82, 72), False, LOOK),
        ("E1S03", (240, 240, 250), False, LOOK),
        ("E1S04", (240, 240, 250), True, None),
    ):
        _picture(tmp_path / f"{sid}.png", rgb)
        items.append(
            {
                "segment_id": sid,
                "segment_break": scene_break,
                "image_prompt": {"scene": "s", "look": look},
                "generated_assets": {"storyboard_image": f"{sid}.png"},
            }
        )

    assert MediaAdapter._look_outliers(tmp_path, items, "segment_id") == ["E1S03"]
