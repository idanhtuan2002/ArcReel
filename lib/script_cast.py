"""Registered characters a segment's narration names but its ``characters_in_segment`` does not list.

A storyboard attaches reference sheets only for the listed characters, so a character who appears but is not listed
drifts in identity, and it shows only after the picture is made (DramaClaw blocks a render until every beat has an
explicit identity state, ``generators/render_identity_guard.py`` at b299bfd). Being named is not appearing — a memory
or a letter names people who are not in the shot — so callers report it and never refuse on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from lib.text_attestation import named_in


@dataclass(frozen=True)
class UnlistedCast:
    index: int
    segment_id: str
    names: tuple[str, ...]


def unlisted_cast(segments: Sequence[Mapping[str, object]], characters: Iterable[str]) -> list[UnlistedCast]:
    """For each segment that names registered characters it does not list, which ones."""
    names = [str(name) for name in characters if str(name).strip()]
    found: list[UnlistedCast] = []
    for index, segment in enumerate(segments):
        raw = segment.get("characters_in_segment")
        listed = {str(name) for name in raw} if isinstance(raw, list) else set()
        text = str(segment.get("novel_text") or "")
        absent = tuple(name for name in names if name not in listed and named_in(name, text))
        if absent:
            found.append(UnlistedCast(index, str(segment.get("segment_id") or ""), absent))
    return found


__all__ = ["UnlistedCast", "unlisted_cast"]
