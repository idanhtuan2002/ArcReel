"""The spatial prompt is pinned and model output is parsed as exactly one JSON object."""

from __future__ import annotations

import pytest

from r2.advanced_creative.spatial import SpatialNormalizationError
from r2.advanced_creative.spatial_prompt import (
    MAX_SPATIAL_RESPONSE_BYTES,
    build_spatial_prompt,
    parse_spatial_response,
    spatial_prompt_digest,
)


def test_prompt_is_deterministic_and_names_both_source_refs() -> None:
    prompt = build_spatial_prompt("  Lobby  ")
    assert prompt == build_spatial_prompt("Lobby")
    assert "Scene: Lobby" in prompt
    assert '"r2-spatial-response-v1"' in prompt
    assert 'source_ref "master"' in prompt
    assert 'source_ref "reverse"' in prompt
    assert spatial_prompt_digest(prompt) != spatial_prompt_digest(build_spatial_prompt("Hall"))


def test_prompt_requires_a_scene_name() -> None:
    with pytest.raises(SpatialNormalizationError):
        build_spatial_prompt("   ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b'{"a": 1}', {"a": 1}),
        (b'```json\n{"a": 1}\n```', {"a": 1}),
        (b'  ```\n{"a": 1}```  ', {"a": 1}),
    ],
    ids=["plain", "json_fence", "bare_fence"],
)
def test_parse_accepts_one_object_with_optional_fence(raw: bytes, expected: dict[str, object]) -> None:
    assert parse_spatial_response(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b'Here is the JSON: {"a": 1}',
        b'{"a": 1} trailing',
        b"\xff\xfe",
        b"{" + b" " * MAX_SPATIAL_RESPONSE_BYTES + b"}",
    ],
    ids=["empty", "array", "prose_prefix", "trailing_text", "not_utf8", "too_large"],
)
def test_parse_rejects_anything_but_one_object(raw: bytes) -> None:
    with pytest.raises(SpatialNormalizationError):
        parse_spatial_response(raw)
