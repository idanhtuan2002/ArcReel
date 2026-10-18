from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from server.story_authoring.contracts import (
    OutputMode,
    StoryDecoding,
    StoryLimits,
    StoryModelSelection,
    StoryStepKind,
    StoryStepRequest,
)


def _limits(**overrides) -> StoryLimits:
    fields = {"input_tokens_max": 3_000_000, "output_tokens_max": 600_000, "wall_clock_max_seconds": 36_000}
    fields.update(overrides)
    return StoryLimits(**fields)


def _selection(**overrides) -> StoryModelSelection:
    fields = {
        "provider_id": "custom-1",
        "endpoint": "ollama-chat",
        "base_url": "http://localhost:11434",
        "model_id": "ornith-32k:9b",
        "has_credential": False,
    }
    fields.update(overrides)
    return StoryModelSelection.create(**fields)


def test_default_limits_are_the_amendment_defaults():
    limits = _limits()
    assert (limits.max_input_tokens, limits.max_output_tokens, limits.server_context_tokens) == (24576, 4096, 32768)
    assert (limits.generate_calls_max, limits.count_calls_max, limits.total_http_calls_max) == (132, 132, 264)
    assert (limits.max_repairs, limits.max_scene_attempts, limits.currency) == (2, 6, "LOCAL")


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_input_tokens": 0},
        {"max_output_tokens": -1},
        {"generate_calls_max": 0},
        {"input_tokens_max": 0},
        {"wall_clock_max_seconds": 0},
        {"max_repairs": -1},
        {"max_input_tokens": 30000},
        {"max_cost_minor_units": 5},
        {"currency": "USD"},
        {"max_input_tokens": 1.5},
        {"unexpected": 1},
    ],
)
def test_invalid_limits_are_refused(overrides):
    with pytest.raises(ValidationError):
        _limits(**overrides)


def test_zero_repairs_is_allowed_and_a_priced_currency_needs_a_money_ceiling():
    assert _limits(max_repairs=0).max_repairs == 0
    assert _limits(currency="USD", max_cost_minor_units=500).max_cost_minor_units == 500


def test_the_selection_digest_covers_every_routing_field_and_no_credential():
    base = _selection()
    assert base.config_digest.startswith("sha256:")
    for field, value in (
        ("model_id", "ornith:9b"),
        ("base_url", "http://other:11434"),
        ("endpoint", "openai-chat"),
        ("provider_id", "custom-2"),
        ("has_credential", True),
    ):
        assert _selection(**{field: value}).config_digest != base.config_digest
    assert "api_key" not in StoryModelSelection.model_fields


def test_a_selection_with_a_stale_digest_is_refused():
    data = _selection().model_dump()
    data["model_id"] = "other:1b"
    with pytest.raises(ValidationError):
        StoryModelSelection(**data)


class _Shape(BaseModel):
    title: str


def _step(**overrides) -> StoryStepRequest:
    fields = {
        "step_id": "scene_draft[1,1]#0",
        "kind": StoryStepKind.SCENE_DRAFT,
        "context_digest": "sha256:" + "0" * 64,
        "selection": _selection(),
        "system_prompt": "Bạn là người viết văn tiếng Việt.",
        "prompt": "Viết cảnh 1.",
        "output_mode": OutputMode.PROSE,
        "decoding": StoryDecoding(temperature=0.7, seed=1),
        "max_output_tokens": 4096,
    }
    fields.update(overrides)
    return StoryStepRequest(**fields)


def test_output_mode_and_response_model_must_agree():
    assert _step().response_model is None
    assert _step(output_mode=OutputMode.STRUCTURED, response_model=_Shape).response_model is _Shape
    with pytest.raises(ValidationError):
        _step(output_mode=OutputMode.STRUCTURED)
    with pytest.raises(ValidationError):
        _step(response_model=_Shape)


def test_paragraph_bounds_must_be_ordered():
    assert (_step(min_paragraphs=3, max_paragraphs=3).min_paragraphs) == 3
    with pytest.raises(ValidationError):
        _step(min_paragraphs=4, max_paragraphs=3)
    with pytest.raises(ValidationError):
        _step(min_paragraphs=0)


def test_a_step_needs_a_system_prompt():
    with pytest.raises(ValidationError):
        _step(system_prompt="")
