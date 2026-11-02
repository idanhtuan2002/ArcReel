"""build_narration_visual_model：视觉层对齐锚 segment_id 被 script_plan 分镜表枚举硬约束。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lib.script_models import build_narration_visual_model


def _segment_id_schema(model) -> dict:
    schema = model.model_json_schema()
    segment = next(d for d in schema["$defs"].values() if "image_prompt" in d.get("properties", {}))
    return segment["properties"]["segment_id"]


def test_segment_ids_render_as_enum_and_single_as_const():
    assert _segment_id_schema(build_narration_visual_model(["E1S01", "E1S02", "E1S01"]))["enum"] == ["E1S01", "E1S02"]
    assert _segment_id_schema(build_narration_visual_model(["E1S01"]))["const"] == "E1S01"


def test_an_invented_segment_id_is_rejected():
    model = build_narration_visual_model(["E1S01"])
    with pytest.raises(ValidationError) as caught:
        model.model_validate({"title": "t", "segments": [{"segment_id": "E1S27"}]})
    assert any(error["loc"][-1] == "segment_id" for error in caught.value.errors())


def test_empty_segment_ids_are_refused():
    with pytest.raises(ValueError, match="segment_ids"):
        build_narration_visual_model([])
