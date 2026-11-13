"""What the render step asks the renderer for: a camera move per held picture and the project's grade."""

from __future__ import annotations

from server.production_run.render_adapter import _planned_moves, film_grade


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
