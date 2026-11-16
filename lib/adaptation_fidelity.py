"""Whether an adapted episode keeps its source's words and speakers (ADR-0114 fidelity checks).

An adaptation may cut and compress, but a line a character speaks must be that character's: when the line repeats a
quote of the source, its speaker is the one the source names for the quote; nobody speaks who is not in the episode.
In a narration script every dialogue line is a quote of the source and no long narration line is made of words the
source does not use. Speakers are read from the source only where it says so plainly (a name next to a speech verb
beside the quote); a quote whose speaker the text leaves to the reader is not judged.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lib.text_attestation import has_cjk, named_in, skeleton

#: The share of a dialogue line that must be found in the source, in pieces of at least ``_min_block`` letters.
QUOTE_COVERAGE_MIN = 0.7
#: A narration line of at least this many words is refused when more than ``NOVEL_WORDS_MAX`` of them are absent
#: from the source.
NOVEL_LINE_MIN_WORDS = 8
NOVEL_WORDS_MAX = 0.5
#: Letters between a quote and the attribution that names its speaker.
_ATTRIBUTION_REACH = 40
#: Letters between a speaker's name and the speech verb that makes it an attribution.
_VERB_REACH = 8

_PAIRS = {"“": "”", "«": "»", "「": "」", "『": "』", "„": "“"}
_SPEECH_VERBS = (
    # vi
    "nói", "hỏi", "đáp", "bảo", "kêu", "gọi", "hét", "quát", "thì thầm", "lẩm bẩm", "thốt", "cười", "khẽ",
    # en
    "said", "says", "asked", "asks", "replied", "replies", "answered", "whispered", "shouted", "cried", "muttered",
    # zh
    "说", "說", "道", "问", "問", "答", "喊", "叫", "笑道",
)  # fmt: skip


@dataclass(frozen=True)
class Quote:
    start: int  # the opening mark
    end: int  # just past the closing mark


def quotes(source: str) -> list[Quote]:
    """The quoted spans of ``source`` in order; a straight double quote left open closes at the line's end."""
    text = unicodedata.normalize("NFC", source)
    found: list[Quote] = []
    open_at: int | None = None
    closing = ""
    for index, char in enumerate(text):
        if open_at is None:
            if char in _PAIRS:
                open_at, closing = index, _PAIRS[char]
            elif char == '"':
                open_at, closing = index, '"'
        elif char == closing:
            found.append(Quote(open_at, index + 1))
            open_at = None
        elif char == "\n" and closing == '"':
            open_at = None
    return found


def _names_with_verb(segment: str, names: Iterable[str]) -> set[str]:
    """The names ``segment`` writes next to a speech verb (``Hải nói``, ``said Ann``, ``林说``)."""
    lowered = segment.lower()
    speakers: set[str] = set()
    for name in names:
        key = name.strip().lower()
        if not key or not named_in(name, segment):
            continue
        for match in re.finditer(re.escape(key), lowered):
            before = lowered[max(0, match.start() - _VERB_REACH) : match.start()]
            after = lowered[match.end() : match.end() + _VERB_REACH]
            if any(verb in before or verb in after for verb in _SPEECH_VERBS):
                speakers.add(name)
                break
    return speakers


def source_speaker(source: str, spans: Sequence[Quote], index: int, names: Iterable[str]) -> str | None:
    """Who ``source`` says speaks quote ``index``: the one name beside a speech verb in the attribution after the
    quote, else before it; a quote that continues one attributed in the same paragraph (``"A," Hải nói, "B."``)
    shares its speaker. ``None`` when the text does not say."""
    text = unicodedata.normalize("NFC", source)
    names = list(names)
    quote = spans[index]
    following = spans[index + 1].start if index + 1 < len(spans) else len(text)
    after = text[quote.end : min(following, quote.end + _ATTRIBUTION_REACH)].split("\n", 1)[0]
    found = _names_with_verb(after, names)
    if len(found) == 1:
        return found.pop()
    preceding = spans[index - 1].end if index > 0 else 0
    before = text[max(preceding, quote.start - _ATTRIBUTION_REACH) : quote.start].rsplit("\n", 1)[-1]
    found = _names_with_verb(before, names)
    if len(found) == 1:
        return found.pop()
    return None


def _min_block(source: str) -> int:
    return 3 if has_cjk(source) else 6


def attestation(line: str, source: str) -> tuple[float, int | None]:
    """The share of ``line``'s letters found in ``source`` in order, in pieces long enough to be words rather than
    coincidences, and the offset in ``source`` of the middle of its longest piece (``None`` when nothing is found)."""
    line_letters, _ = skeleton(line)
    source_letters, offsets = skeleton(source)
    if not line_letters:
        return 0.0, None
    matcher = difflib.SequenceMatcher(None, line_letters, source_letters, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size >= _min_block(source)]
    if not blocks:
        return 0.0, None
    longest = max(blocks, key=lambda block: block.size)
    return sum(block.size for block in blocks) / len(line_letters), offsets[longest.b + longest.size // 2]


def _words(text: str) -> list[str]:
    return "".join(char.lower() if char.isalnum() else " " for char in unicodedata.normalize("NFC", text)).split()


def novel_share(line: str, source: str) -> float:
    """The share of ``line``'s words that ``source`` never uses."""
    vocabulary = set(_words(source))
    words = _words(line)
    return sum(word not in vocabulary for word in words) / max(1, len(words))


@dataclass(frozen=True)
class SpokenLine:
    scene: int
    kind: str
    speaker: str
    text: str


def fidelity_problems(
    lines: Sequence[SpokenLine], *, mode: str, source: str, previous_tail: str, names: Iterable[str]
) -> list[str]:
    """The fidelity checks ``lines`` fail, as sentences the writer can act on."""
    problems: list[str] = []
    names = sorted({name for name in names if name.strip()}, key=len, reverse=True)
    spans = quotes(source)
    present = source + "\n" + previous_tail
    for line in lines:
        if line.kind not in {"dialogue", "voiceover"} or not line.speaker.strip():
            continue
        speaker = line.speaker.strip()
        if not named_in(speaker, present):
            problems.append(
                f"scene {line.scene}: {speaker!r} speaks but is not in this episode's source; give the line to the "
                f"character the source names, or cut it: {line.text[:80]!r}"
            )
            continue
        coverage, at = attestation(line.text, source)
        if coverage >= QUOTE_COVERAGE_MIN and at is not None:
            index = next((i for i, quote in enumerate(spans) if quote.start <= at < quote.end), None)
            said_by = source_speaker(source, spans, index, names) if index is not None else None
            if said_by is not None and skeleton(said_by)[0] != skeleton(speaker)[0]:
                problems.append(
                    f"scene {line.scene}: in the source {said_by!r} says {line.text[:80]!r}, not {speaker!r}; keep "
                    "every quoted line with the character who says it"
                )
        elif mode == "narration":
            problems.append(
                f"scene {line.scene}: the dialogue line {line.text[:80]!r} is not in the source; quote what the "
                "character says in the source word for word, or tell it as narration"
            )
    if mode == "narration" and not has_cjk(source):
        for line in lines:
            if line.kind != "narration" or len(_words(line.text)) < NOVEL_LINE_MIN_WORDS:
                continue
            if novel_share(line.text, present + "\n" + " ".join(names)) > NOVEL_WORDS_MAX:
                problems.append(
                    f"scene {line.scene}: the narration {line.text[:80]!r} says what the source does not; tell only "
                    "what happens in the source"
                )
    return problems


__all__ = [
    "NOVEL_LINE_MIN_WORDS",
    "NOVEL_WORDS_MAX",
    "QUOTE_COVERAGE_MIN",
    "Quote",
    "SpokenLine",
    "attestation",
    "fidelity_problems",
    "novel_share",
    "quotes",
    "source_speaker",
]
