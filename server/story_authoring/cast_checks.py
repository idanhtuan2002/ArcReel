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
from server.story_authoring.prompts.schemas import ChapterPlan, SeedCharacter, StorySeed

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


#: Word overlap at or above which a required change restates a ban or a secret.
CONFLICT_OVERLAP = 0.5
_STOP = frozenset(
    [
        "và",
        "của",
        "là",
        "có",
        "không",
        "được",
        "cho",
        "với",
        "một",
        "những",
        "các",
        "trong",
        "khi",
        "đã",
        "sẽ",
        "đang",
        "thì",
        "mà",
        "này",
        "đó",
        "để",
        "từ",
        "ra",
        "vào",
        "lên",
        "về",
        "bị",
    ]
)


def _content_words(text: str) -> frozenset[str]:
    words = re.findall(r"\w+", _fold(text).casefold())
    return frozenset(w for w in words if len(w) > 1 and w not in _STOP)


def plan_conflicts(plan: ChapterPlan) -> list[str]:
    """Required changes that restate a do-not item or a withheld card, named for the plan's revision: such a plan
    cannot be written without breaking itself (donor shenbi chapter-planning gates)."""
    problems: list[str] = []
    for required in plan.required_changes_by_end:
        need = _content_words(required)
        for kind, items in (("điều cấm (do_not)", plan.do_not), ("bài giữ kín (withheld_cards)", plan.withheld_cards)):
            for item in items:
                other = _content_words(item)
                if need and other and len(need & other) / len(need | other) >= CONFLICT_OVERLAP:
                    problems.append(
                        f"Thay đổi bắt buộc “{required}” trùng với {kind} “{item}”: bỏ hoặc viết lại một trong hai."
                    )
    return problems


#: Capitalised words of an idea that are not names: sentence openers, pronouns and kinship words.
_NOT_NAMES = frozenset(
    [
        "một",
        "trong",
        "từ",
        "khi",
        "sau",
        "nếu",
        "rồi",
        "nhưng",
        "và",
        "vì",
        "có",
        "là",
        "đây",
        "đó",
        "này",
        "người",
        "cô",
        "anh",
        "ông",
        "bà",
        "chị",
        "em",
        "hắn",
        "nàng",
        "tôi",
        "ta",
        "chúng",
        "họ",
        "mọi",
        "cả",
        "các",
        "những",
        "mỗi",
        "trước",
        "giữa",
        "lúc",
        "ngày",
        "đêm",
        "năm",
        "cuối",
        "đầu",
        "bỗng",
        "tại",
        "ở",
        "với",
        "cho",
        "đến",
        "theo",
        "vợ",
        "chồng",
        "con",
        "cha",
        "mẹ",
    ]
)


def idea_names(idea: str) -> list[str]:
    """The names an idea gives its characters: runs of capitalised words, minus openers and kinship words."""
    names: list[str] = []
    run: list[str] = []

    def close() -> None:
        words = [w for w in run if w.casefold() not in _NOT_NAMES]
        if words and " ".join(words) not in names:
            names.append(" ".join(words))
        run.clear()

    for match in re.finditer(r"\w+|[^\w\s]", _fold(idea)):
        token = match.group(0)
        if token[0].isalpha() and token[0].isupper():
            run.append(token)
        else:
            close()
    close()
    return names


def missing_idea_names(idea: str, seed: StorySeed) -> list[str]:
    """The idea's names no seed character or place carries (a name may be part of a fuller one: "Minh" in "Lê Minh")."""
    carried = " | ".join(_fold(entry.name) for entry in (*seed.characters, *seed.locations))
    return [name for name in idea_names(idea) if not _names_in(carried, name)]


__all__ = ["CONFLICT_OVERLAP", "OPENINGS", "gender_findings", "idea_names", "missing_idea_names", "plan_conflicts"]
