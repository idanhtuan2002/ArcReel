"""Pick a VieNeu preset for every character and the narrator (ASSEMBLY_PLAN D9, D18).

Rule: same gender; the story's region first (``vn`` stories: the region the story names, default north; ``original``:
north), then the others; story-reading styles for the narrator; distinct presets for distinct characters while presets
remain, then reuse in order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from assembly.voices.catalog import Voice

_NARRATOR_STYLES = ("doc_truyen", "tu_nhien", "tin_tuc")


@dataclass(frozen=True)
class CastMember:
    name: str
    gender: str  # free text from DramaClaw ("male"/"female"/"男"/"女"/"nam"/"nữ")
    region: str | None = None  # "north" | "central" | "south" when the story marks it


def normalize_gender(raw: str) -> str:
    text = (raw or "").strip().lower()
    return "female" if any(t in text for t in ("female", "女", "nữ", "woman", "girl")) else "male"


def _ranked(voices: Iterable[Voice], gender: str, region: str, styles: Sequence[str] = ()) -> list[Voice]:
    def key(v: Voice) -> tuple[int, int, str]:
        style_rank = styles.index(v.style) if v.style in styles else len(styles)
        return (0 if v.region == region else 1, style_rank, v.name)

    return sorted((v for v in voices if v.gender == gender), key=key)


def cast(
    members: Sequence[CastMember],
    voices: Sequence[Voice],
    *,
    story_region: str = "north",
    narrator_gender: str = "male",
) -> dict[str, str]:
    """Return ``{character name: preset}`` plus ``{"__narrator__": preset}``."""
    chosen: dict[str, str] = {}
    narrator = _ranked(voices, narrator_gender, story_region, _NARRATOR_STYLES)
    if not narrator:
        raise ValueError(f"no VieNeu preset of gender {narrator_gender!r}")
    chosen["__narrator__"] = narrator[0].name
    used = {narrator[0].name}
    for member in members:
        gender = normalize_gender(member.gender)
        ranked = _ranked(voices, gender, member.region or story_region)
        if not ranked:
            raise ValueError(f"no VieNeu preset of gender {gender!r} for {member.name}")
        fresh = [v for v in ranked if v.name not in used]
        pick = (fresh or ranked)[0]
        chosen[member.name] = pick.name
        used.add(pick.name)
    return chosen
