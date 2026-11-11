"""Deterministic cast checks: the narration keeps each character's gender.

Donor surface: shenbi ``src/shenbi/gates/g4/cross_chapter.py`` invariant 5 (pin 10efa7cc) — a character card states
its gender; a paragraph that names a male character and opens a sentence with the female pronoun is a finding,
repaired by redrafting. The Vietnamese equivalent reads sentence openings: in a paragraph whose named characters are
all of one gender, a narration sentence that opens with a word of the other gender ("Cô", "Nàng", "Anh", "Chàng"...)
refers to one of them with the wrong gender. Dialogue is left out: a speaker addresses others by any word.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from server.story_authoring.checks import Finding, Severity
from server.story_authoring.prompts.schemas import SeedCharacter

#: Sentence openings that refer to a woman or to a man; each counts only as a whole word at a sentence start.
OPENINGS: dict[str, tuple[str, ...]] = {
    "nữ": ("cô gái", "cô ấy", "cô", "nàng", "chị ấy", "người phụ nữ", "người đàn bà", "thiếu nữ", "bà ấy"),
    "nam": ("chàng trai", "anh ấy", "anh ta", "anh", "chàng", "gã", "hắn", "người đàn ông", "ông ấy"),
}
_QUOTED = re.compile(r"[“\"«][^”\"»]*[”\"»]")
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]*")


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _narration(paragraph: str) -> str:
    lines = [line for line in paragraph.splitlines() if not line.lstrip().startswith(("-", "–", "—"))]
    return _QUOTED.sub(" ", "\n".join(lines))


def _names_in(text: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def _opening(sentence: str, gender: str) -> str | None:
    head = sentence.strip().casefold()
    for word in OPENINGS[gender]:
        if re.match(rf"{re.escape(word)}(?!\w)", head):
            return sentence.strip()
    return None


def gender_findings(cast: Sequence[SeedCharacter], scenes: Sequence[tuple[str, str]]) -> tuple[Finding, ...]:
    """One finding per scene paragraph that names only characters of one gender and opens a narration sentence with
    a word of the other gender; quoted as that sentence so a repair finds it."""
    genders = {_fold(c.name): c.gender for c in cast if c.gender is not None}
    findings: list[Finding] = []
    for node, text in scenes:
        for paragraph in _fold(text).split("\n\n"):
            narration = _narration(paragraph)
            present = {name: gender for name, gender in genders.items() if _names_in(narration, name)}
            if not present or len(set(present.values())) != 1:
                continue
            gender = next(iter(present.values()))
            other = "nữ" if gender == "nam" else "nam"
            for sentence in _SENTENCE.findall(narration):
                quote = _opening(sentence, other)
                if quote is not None:
                    names = ", ".join(sorted(present))
                    findings.append(
                        Finding(
                            "CAST_GENDER",
                            Severity.NARRATIVE_CRITICAL,
                            node,
                            f"{names} là {gender} nhưng lời kể gọi bằng từ chỉ người {other}; sửa cách gọi cho đúng",
                            quote,
                        )
                    )
                    break
    return tuple(findings)


__all__ = ["OPENINGS", "gender_findings"]
