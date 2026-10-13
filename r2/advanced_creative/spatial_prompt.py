"""Versioned two-view spatial prompt and strict model-response parsing.

The coordinate contract and analysis rules follow the pinned DramaClaw
``scene_spatial_contract.build_prompt``; the response shape is the R2
``r2-spatial-response-v1`` schema, which requires image spans for visible
items and bounded confidence for inferred items.
"""

from __future__ import annotations

import hashlib
import json
import re

from r2.advanced_creative.spatial import SpatialNormalizationError

SPATIAL_PROMPT_VERSION = "spatial-prompt-v1"
SPATIAL_RESPONSE_SCHEMA_VERSION = "r2-spatial-response-v1"
MASTER_SOURCE_REF = "master"
REVERSE_SOURCE_REF = "reverse"
MAX_SPATIAL_RESPONSE_BYTES = 256 * 1024

_FENCE_OPEN = re.compile(r"\A```(?:json)?\s*")
_FENCE_CLOSE = re.compile(r"\s*```\Z")


def build_spatial_prompt(scene_name: str) -> str:
    if not scene_name.strip():
        raise SpatialNormalizationError("scene name is required")
    return f"""
You are a spatial set-continuity analyst for a 360 panorama pipeline.
Scene: {scene_name.strip()}

This is NOT image generation. Analyze the two attached images and return strict JSON only.
Image 1 is MASTER (source_ref "{MASTER_SOURCE_REF}"). Image 2 is REVERSE (source_ref "{REVERSE_SOURCE_REF}").

Coordinate assumptions:
- MASTER is the front-facing reference from one fixed camera point.
- REVERSE is the back-facing reference from the same camera point, yaw-rotated 180 degrees.
- The panorama uses a SAFE-SEAM raw canvas layout. x=0% and x=100% = low-detail LEFT SIDE seam,
  where MASTER left side meets REVERSE screen-right side. x=25% = MASTER front center.
  x=50% = RIGHT SIDE join, where MASTER right side meets REVERSE screen-left side.
  x=75% = REVERSE back center.
- REVERSE screen-left content maps to x=50%..75%; REVERSE screen-right content maps to x=75%..100%;
  REVERSE center content maps around x=75%, not across the x=0%/100% seam.
- The images may be ordinary wide-angle references, not perfect 180-degree wall elevations.
  Separate directly visible facts from inferred areas and gaps.

Return JSON with this schema:
{{
  "schema_version": "{SPATIAL_RESPONSE_SCHEMA_VERSION}",
  "coverage_assessment": {{
    "coverage_gaps": [{{"description": "...", "source_refs": ["{MASTER_SOURCE_REF}"]}}]
  }},
  "walls": {{
    "front": {{"must_preserve": [VISIBLE], "shared_overlap": [], "inferred_fill": [INFERRED]}},
    "back": {{"must_preserve": [], "shared_overlap": [], "inferred_fill": []}},
    "left": {{"must_preserve": [], "shared_overlap": [VISIBLE], "inferred_fill": []}},
    "right": {{"must_preserve": [], "shared_overlap": [], "inferred_fill": []}}
  }},
  "joins": [
    {{"id": "left_side_join", "merge_once": ["..."], "continue_smoothly": ["..."], "do_not_duplicate": ["..."]}},
    {{"id": "right_side_join", "merge_once": [], "continue_smoothly": [], "do_not_duplicate": []}}
  ],
  "must_not_transform": [{{"source_object": "...", "forbidden_transform": "...", "reason": "..."}}],
  "direction_exclusion_locks": [
    {{"name": "...", "required_direction": "front|back", "required_panorama_zone": "x=25%|x=75%",
      "must_not_appear_in": "...", "reason": "..."}}
  ]
}}
VISIBLE = {{"name": "...", "type": "door|opening|display_panel|cabinet|sign|light|wall_surface|fixture|furniture|other",
  "count": 1, "source_view": "master|reverse|both", "size_lock": "tiny|small|medium|large|full_height|full_width|wall_dominant|unknown",
  "source_spans": [{{"source_ref": "{MASTER_SOURCE_REF}|{REVERSE_SOURCE_REF}", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}}]}}
INFERRED = {{"name": "...", "relation": "...", "confidence": 0.0, "source_refs": ["{MASTER_SOURCE_REF}"]}}

Rules:
- Every VISIBLE item needs at least one source_span: a normalized box (0..1, x0<x1, y0<y1) on the image
  named by source_ref where the item is actually visible. Never give a span for something you did not see.
- An item you did not see but expect is INFERRED with a confidence between 0 and 1.
- If an area is not visible enough, list it in coverage_gaps instead of inventing a confident wall.
- Direction locks are critical: large or wall-dominant front-center objects belong around x=25% only;
  large or wall-dominant reverse-center/back objects belong around x=75% only. Do not use back-center
  furniture or wall fixtures to fill the x=50% right-side join.
- Keep the JSON compact: prefer at most 8 must_preserve items per wall.
""".strip()


def spatial_prompt_digest(prompt: str) -> str:
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def parse_spatial_response(raw: bytes) -> dict[str, object]:
    """Decode one JSON object; only a single surrounding Markdown fence is removed."""
    if not raw or len(raw) > MAX_SPATIAL_RESPONSE_BYTES:
        raise SpatialNormalizationError("spatial model response is empty or too large")
    try:
        text = raw.decode("utf-8").strip()
        if text.startswith("```"):
            text = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text))
        parsed = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpatialNormalizationError("spatial model response is not one JSON object") from exc
    if not isinstance(parsed, dict):
        raise SpatialNormalizationError("spatial model response is not one JSON object")
    return parsed


__all__ = [
    "MASTER_SOURCE_REF",
    "MAX_SPATIAL_RESPONSE_BYTES",
    "REVERSE_SOURCE_REF",
    "SPATIAL_PROMPT_VERSION",
    "SPATIAL_RESPONSE_SCHEMA_VERSION",
    "build_spatial_prompt",
    "parse_spatial_response",
    "spatial_prompt_digest",
]
