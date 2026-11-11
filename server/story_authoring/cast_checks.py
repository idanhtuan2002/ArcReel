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
_QUOTED = re.compile(r"[“\"«][^”\"»]*[”\"»]|[‘'][^’'\n]*[’']")
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


def _character(cast: Sequence[SeedCharacter], name: str | None) -> SeedCharacter | None:
    return next((c for c in cast if name is not None and _fold(c.name) == _fold(name)), None)


def pov_findings(cast: Sequence[SeedCharacter], pov: str | None, text: str, *, node_id: str) -> tuple[Finding, ...]:
    """A scene that never names its point-of-view character, and narration that calls someone “em” when the
    narration calls no character so: a reader cannot tell who acts, and the voice slips into another person."""
    findings: list[Finding] = []
    character = _character(cast, pov)
    folded = _fold(text)
    if character is not None and not _names_in(folded, _fold(character.name)):
        findings.append(
            Finding(
                "UNNAMED_POV",
                Severity.NARRATIVE_CRITICAL,
                node_id,
                f"cảnh không gọi tên {character.name} (nhân vật điểm nhìn) lần nào; gọi tên ở câu đầu nhân vật xuất hiện",
                folded.strip()[:80],
            )
        )
    if cast and not any((c.address or "").casefold() == "em" for c in cast):
        for paragraph in folded.split("\n\n"):
            hit = next(
                (
                    s.strip()
                    for s in _SENTENCE.findall(_narration(paragraph))
                    if re.match(r"em(?!\w)", s.strip().casefold())
                ),
                None,
            )
            if hit is not None:
                findings.append(
                    Finding(
                        "NARRATION_EM",
                        Severity.NARRATIVE_CRITICAL,
                        node_id,
                        "lời kể gọi một nhân vật là “em” trong khi lời kể không gọi ai như vậy; dùng tên hoặc cách gọi đã định",
                        hit,
                    )
                )
                break
    return tuple(findings)


#: Narration "tôi" a third-person scene may carry (a remembered phrase, an unquoted thought) before it counts as a
#: slip into the first person; the committed real stories carry at most one, the drifted scenes 16 and 24.
THIRD_PERSON_TOI_MAX = 2
_TOI = re.compile(r"(?<!\w)tôi(?!\w)", re.IGNORECASE)


def pov_person_findings(pov: str | None, text: str, *, node_id: str, syllables: int) -> tuple[Finding, ...]:
    """A scene narrated in another person than the story's point of view (donor shenbi POV invariant, counted on
    narration with dialogue removed)."""
    if not pov:
        return ()
    folded = _fold(text)
    narration = "\n".join(_narration(p) for p in folded.split("\n\n"))
    hits = list(_TOI.finditer(narration))
    first_person = "thứ nhất" in pov.casefold()
    if not first_person and len(hits) > THIRD_PERSON_TOI_MAX:
        quote = next((s.strip() for s in _SENTENCE.findall(narration) if _TOI.search(s)), "")
        return (
            Finding(
                "POV_PERSON",
                Severity.NARRATIVE_CRITICAL,
                node_id,
                f"truyện kể ở {pov} nhưng lời kể cảnh này xưng “tôi” {len(hits)} lần; kể lại ở {pov}",
                quote,
            ),
        )
    if first_person and not hits and syllables >= 600:
        return (
            Finding(
                "POV_PERSON",
                Severity.NARRATIVE_CRITICAL,
                node_id,
                f"truyện kể ở {pov} nhưng lời kể cảnh này không xưng “tôi” lần nào; kể lại ở {pov}",
                folded.strip()[:80],
            ),
        )
    return ()


def name_pov(cast: Sequence[SeedCharacter], pov: str | None, text: str) -> str:
    """The text with the first narration sentence opening with the point-of-view character's own address opened
    with their name instead, when the scene never names them (the one place the right word is certain)."""
    character = _character(cast, pov)
    if character is None or not character.address or _names_in(_fold(text), _fold(character.name)):
        return text
    text = _fold(text)
    address = _fold(character.address).casefold()
    paragraphs = text.split("\n\n")
    for i, paragraph in enumerate(paragraphs):
        for match in _SENTENCE.finditer(paragraph):
            sentence = match.group(0)
            body = sentence.lstrip()
            start, end = match.end() - len(body), match.end()
            if body[:1] in "“\"«‘'-–—":
                continue
            if re.match(rf"{re.escape(address)}(?!\w)(?! ấy)", body.casefold()):
                paragraphs[i] = paragraph[:start] + character.name + body[len(address) :] + paragraph[end:]
                return "\n\n".join(paragraphs)
    return text


#: Openings that describe rather than name a person, and the same description of the other gender.
_COUNTERPART = {
    "cô gái": "chàng trai",
    "thiếu nữ": "chàng trai",
    "người phụ nữ": "người đàn ông",
    "người đàn bà": "người đàn ông",
    "chàng trai": "cô gái",
    "người đàn ông": "người phụ nữ",
}


def _opening_word(sentence: str, gender: str) -> str | None:
    head = sentence.lstrip().casefold()
    for word in OPENINGS[gender]:
        if re.match(rf"{re.escape(word)}(?!\w)", head):
            return word
    return None


def fix_gender_openings(cast: Sequence[SeedCharacter], text: str) -> str:
    """The text with each narration sentence that opens with a word of the wrong gender, in a paragraph naming one
    character only, opened with that character's own address, or with the same description of the right gender
    ("Cô gái trẻ" → "Chàng trai trẻ"). Dialogue and
    paragraphs naming several characters are left to the model repair (donor huohuo applies deterministic local
    fixes only where the right word is certain)."""
    by_name = {_fold(c.name): c for c in cast if c.gender is not None}
    paragraphs = _fold(text).split("\n\n")
    fixed: list[str] = []
    for paragraph in paragraphs:
        present = [c for name, c in by_name.items() if _names_in(_narration(paragraph), name)]
        if len(present) != 1:
            fixed.append(paragraph)
            continue
        character = present[0]
        other = "nữ" if character.gender == "nam" else "nam"
        out: list[str] = []
        for sentence in _SENTENCE.findall(paragraph):
            body = sentence.lstrip()
            lead = sentence[: len(sentence) - len(body)]
            word = None if body[:1] in '“"«-–—' else _opening_word(body, other)
            if word is None:
                out.append(sentence)
                continue
            if word in _COUNTERPART:
                counterpart = _COUNTERPART[word]
                replacement = counterpart[:1].upper() + counterpart[1:]
            elif not character.address:
                replacement = character.name
            else:
                replacement = character.address[:1].upper() + character.address[1:]
                if word.endswith(" ấy"):
                    replacement += " ấy"
            out.append(lead + replacement + body[len(word) :])
        fixed.append("".join(out))
    return "\n\n".join(fixed)


def fix_near_names(text: str, allowed: set[str]) -> str:
    """The text with each name one letter from a character's replaced by that character's name."""
    from server.story_authoring.checks import near_name, unknown_names

    for name in unknown_names(text, allowed):
        right = near_name(name, allowed)
        if right is not None:
            text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", right, text)
    return text


PROTAGONIST_MARK = "chính là nhân vật chính"


def seed_problems(seed: StorySeed) -> list[str]:
    """What a seed lacks as a foundation, every problem at once (donor shenbi 19f192e seed structural validation,
    foundation review): one protagonist, a conflict and an ending of their own rather than the premise restated,
    and characters who do not all speak alike."""
    problems: list[str] = []
    leads = [c.name for c in seed.characters if PROTAGONIST_MARK in _fold(c.relation_to_protagonist).casefold()]
    if len(leads) != 1:
        problems.append(f"đúng một nhân vật ghi relation_to_protagonist là “{PROTAGONIST_MARK}”")
    premise = _content_words(seed.premise)
    for field, text in (("central_conflict", seed.central_conflict), ("ending_direction", seed.ending_direction)):
        own = _content_words(text)
        if premise and own and len(premise & own) / len(premise | own) >= 0.8:
            problems.append(f"{field} phải cụ thể hơn, không chép lại premise")
    voices = [(c.name, _content_words(c.voice)) for c in seed.characters if c.voice]
    for i, (name, words) in enumerate(voices):
        for other, other_words in voices[i + 1 :]:
            if words and other_words and len(words & other_words) / len(words | other_words) >= 0.6:
                problems.append(f"giọng nói của {name} và {other} phải khác nhau")
    return problems


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


__all__ = [
    "CONFLICT_OVERLAP",
    "OPENINGS",
    "fix_gender_openings",
    "fix_near_names",
    "gender_findings",
    "idea_names",
    "missing_idea_names",
    "name_pov",
    "plan_conflicts",
    "pov_findings",
    "pov_person_findings",
    "seed_problems",
]
