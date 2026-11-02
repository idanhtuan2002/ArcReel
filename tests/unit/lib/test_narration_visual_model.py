"""build_narration_visual_model：视觉层以 script_plan 的 segment_id 为必填键，每个分镜恰好一项。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lib.script_models import build_narration_visual_model, narration_visual_segments

VISUAL = {
    "image_prompt": {
        "scene": "画面",
        "composition": {"shot_type": "Medium Shot", "lighting": "光", "ambiance": "氛围"},
    },
    "video_prompt": {"action": "动作", "camera_motion": "Static", "ambiance_audio": "声", "dialogue": []},
}


def _segments_schema(model) -> dict:
    schema = model.model_json_schema()
    return next(d for d in schema["$defs"].values() if d.get("title") == "NarrationVisualSegmentsBySegmentId")


def test_every_segment_id_is_a_required_key_once():
    segments = _segments_schema(build_narration_visual_model(["E1S01", "E1S02", "E1S01"]))

    assert list(segments["properties"]) == ["E1S01", "E1S02"]
    assert segments["required"] == ["E1S01", "E1S02"]
    assert segments["additionalProperties"] is False


def test_a_missing_or_invented_segment_is_rejected():
    model = build_narration_visual_model(["E1S01", "E1S02"])
    with pytest.raises(ValidationError):
        model.model_validate({"title": "t", "segments": {"E1S01": VISUAL}})
    with pytest.raises(ValidationError):
        model.model_validate({"title": "t", "segments": {"E1S01": VISUAL, "E1S02": VISUAL, "E1S27": VISUAL}})


def test_the_keyed_response_converts_to_the_list_shape():
    keyed = {"title": "t", "segments": {"E1S01": VISUAL, "E1S02": VISUAL}}

    listed = narration_visual_segments(keyed)

    assert [s["segment_id"] for s in listed["segments"]] == ["E1S01", "E1S02"]
    assert narration_visual_segments(listed) == listed


def test_empty_segment_ids_are_refused():
    with pytest.raises(ValueError, match="segment_ids"):
        build_narration_visual_model([])
