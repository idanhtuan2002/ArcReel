"""Deterministic shot-grammar checks over an episode's narration segments.

They mirror the grammar the visual prompt asks for (AIVPE's director review: open a scene wide, keep a close-up,
vary sizes): a scene that does not open wide, more than two shots of one size in a row, an episode of four or more
shots without a close-up, and camera moves the video models execute worst (orbit, shake). Findings are advice for the
script's reader and later reviewers; they never block a script.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

WIDE = frozenset({"Long Shot", "Extreme Long Shot"})
CLOSE = frozenset({"Close-up", "Extreme Close-up", "Medium Close-up"})
UNRELIABLE_MOVES = frozenset({"Orbit", "Shake"})
MAX_SAME_SIZE_RUN = 2


def _composition(segment: Mapping[str, Any]) -> Mapping[str, Any]:
    prompt = segment.get("image_prompt")
    composition = prompt.get("composition") if isinstance(prompt, Mapping) else None
    return composition if isinstance(composition, Mapping) else {}


def _move(segment: Mapping[str, Any]) -> object:
    prompt = segment.get("video_prompt")
    return prompt.get("camera_motion") if isinstance(prompt, Mapping) else None


def shot_grammar_issues(segments: Sequence[Mapping[str, Any]], *, id_field: str = "segment_id") -> list[str]:
    """Readable findings, in segment order."""
    issues: list[str] = []
    sizes = [_composition(segment).get("shot_type") for segment in segments]
    run = 0
    for index, segment in enumerate(segments):
        unit = str(segment.get(id_field))
        size = sizes[index]
        if (index == 0 or segment.get("segment_break") is True) and isinstance(size, str) and size not in WIDE:
            issues.append(f"{unit}: scene opens on {size}, not a wide shot")
        run = run + 1 if index > 0 and size == sizes[index - 1] else 1
        if run == MAX_SAME_SIZE_RUN + 1:
            issues.append(f"{unit}: {size} for more than {MAX_SAME_SIZE_RUN} shots in a row")
        if _move(segment) in UNRELIABLE_MOVES:
            issues.append(f"{unit}: camera move {_move(segment)} is unreliable for video models")
    if len(segments) >= 4 and not any(size in CLOSE for size in sizes):
        issues.append("episode has no close-up")
    return issues


__all__ = ["shot_grammar_issues"]
