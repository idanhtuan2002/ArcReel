"""The BytePlus adapter lifts DramaClaw's 1K image sizes to Seedream 4.5's minimum, keeping the ratio."""

from __future__ import annotations

from assembly.image_adapter.app import adjust_image_body, raised_size


def test_small_sizes_are_raised_to_the_minimum_with_the_same_ratio() -> None:
    w, h = raised_size(768, 1024, 3686400)
    assert w * h >= 3686400
    assert abs(w / h - 768 / 1024) < 0.01
    assert w % 2 == 0
    assert h % 2 == 0


def test_large_sizes_pass_unchanged() -> None:
    assert raised_size(1440, 2560, 3686400) == (1440, 2560)


def test_size_string_and_width_height_are_both_adjusted() -> None:
    body = adjust_image_body({"size": "1024x1024", "width": 1024, "height": 1024, "prompt": "x"}, 3686400)
    assert body["size"] == "1920x1920"
    assert (body["width"], body["height"]) == (1920, 1920)
    assert body["prompt"] == "x"
