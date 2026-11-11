"""Deterministic checks across a manuscript's chapters (ADR-0117): long-span repetition, monotonous openings and a
continuation's voice drift. None calls a model; every finding is stylistic, because the thresholds are not
calibrated on Vietnamese text, and each quotes the manuscript verbatim.

Donor surfaces: shenbi ``review-long-span`` (n-gram reuse against earlier chapters), ``chapter-pattern``
(structural monotony) and ``sequel-writing`` step 4 (drift of the first new chapters against the text continued).
"""

from __future__ import annotations

import itertools
import re
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from server.story_authoring.checks import Finding, Severity

SHINGLE = 4
REPETITION_SHARE = 0.12
SAME_OPENING_RUN = 3
PARAGRAPH_OPENING_SHARE = 0.4
DRIFT = 0.5
_WORD = re.compile(r"\w+", re.UNICODE)
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]+")
_DIALOGUE = re.compile(r"^\s*[—–-]|“|\"")


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def _shingles(words: Sequence[str]) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)]


def _sentence_with(text: str, phrase: Sequence[str]) -> str:
    """The first sentence of ``text`` that holds ``phrase``, verbatim."""
    for sentence in _SENTENCE.findall(text):
        if " ".join(phrase) in " ".join(_words(sentence)):
            return sentence.strip()
    return ""


def long_span_findings(chapters: Sequence[tuple[str, str]]) -> tuple[Finding, ...]:
    """``(node, chapter text)`` in order: a chapter whose four-word phrases are more than 12 % reused from earlier
    chapters."""
    findings: list[Finding] = []
    seen: set[tuple[str, ...]] = set()
    for node, text in chapters:
        shingles = _shingles(_words(text))
        if seen and shingles:
            reused = [s for s in shingles if s in seen]
            share = len(reused) / len(shingles)
            if share > REPETITION_SHARE:
                phrase, _ = Counter(reused).most_common(1)[0]
                findings.append(
                    Finding(
                        "LONG_SPAN_REPETITION",
                        Severity.STYLISTIC,
                        node,
                        f"{share:.0%} of the chapter's four-word phrases repeat earlier chapters (most: "
                        f"'{' '.join(phrase)}')",
                        _sentence_with(text, phrase),
                    )
                )
        seen.update(shingles)
    return tuple(findings)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def opening_findings(chapters: Sequence[tuple[str, str]]) -> tuple[Finding, ...]:
    """Three chapters in a row opening with the same two words; a chapter whose paragraphs mostly start alike."""
    findings: list[Finding] = []
    openings = []
    for node, text in chapters:
        paragraphs = _paragraphs(text)
        first = _words(paragraphs[0])[:2] if paragraphs else []
        openings.append((node, tuple(first), paragraphs[0] if paragraphs else ""))
        starts = [w[0] for w in (_words(p) for p in paragraphs) if w]
        if len(starts) >= 5:
            word, count = Counter(starts).most_common(1)[0]
            if count / len(starts) > PARAGRAPH_OPENING_SHARE:
                quote = next(p for p in paragraphs if _words(p)[:1] == [word])
                findings.append(
                    Finding(
                        "MONOTONOUS_PARAGRAPH_OPENINGS",
                        Severity.STYLISTIC,
                        node,
                        f"{count} of {len(starts)} paragraphs start with '{word}'",
                        _SENTENCE.findall(quote)[0].strip() if _SENTENCE.findall(quote) else "",
                    )
                )
    for i in range(SAME_OPENING_RUN - 1, len(openings)):
        run = openings[i - SAME_OPENING_RUN + 1 : i + 1]
        if run[0][1] and all(o[1] == run[0][1] for o in run):
            node, words, paragraph = openings[i]
            findings.append(
                Finding(
                    "MONOTONOUS_CHAPTER_OPENINGS",
                    Severity.STYLISTIC,
                    node,
                    f"{SAME_OPENING_RUN} chapters in a row open with '{' '.join(words)}'",
                    _SENTENCE.findall(paragraph)[0].strip() if _SENTENCE.findall(paragraph) else "",
                )
            )
    return tuple(findings)


@dataclass(frozen=True)
class VoiceStats:
    sentence_words: float
    paragraph_words: float
    dialogue_share: float


def voice_stats(text: str) -> VoiceStats | None:
    paragraphs = _paragraphs(text)
    sentences = _SENTENCE.findall(text)
    if len(paragraphs) < 3 or len(sentences) < 5:
        return None
    return VoiceStats(
        sentence_words=statistics.mean(len(_words(s)) for s in sentences),
        paragraph_words=statistics.mean(len(_words(p)) for p in paragraphs),
        dialogue_share=sum(1 for p in paragraphs if _DIALOGUE.search(p)) / len(paragraphs),
    )


def drift_findings(reference: str, text: str, *, node: str) -> tuple[Finding, ...]:
    """The new part's voice against the text it continues: sentence length, paragraph length, dialogue share."""
    before, after = voice_stats(reference), voice_stats(text)
    if before is None or after is None:
        return ()
    findings: list[Finding] = []
    for name, old, new in (
        ("sentence length", before.sentence_words, after.sentence_words),
        ("paragraph length", before.paragraph_words, after.paragraph_words),
    ):
        if old > 0 and abs(new - old) / old > DRIFT:
            findings.append(
                Finding("VOICE_DRIFT", Severity.STYLISTIC, node, f"{name} {new:.1f} words against {old:.1f} before", "")
            )
    if abs(after.dialogue_share - before.dialogue_share) > DRIFT:
        findings.append(
            Finding(
                "VOICE_DRIFT",
                Severity.STYLISTIC,
                node,
                f"dialogue in {after.dialogue_share:.0%} of paragraphs against {before.dialogue_share:.0%} before",
                "",
            )
        )
    return tuple(findings)


__all__ = ["drift_findings", "long_span_findings", "opening_findings", "voice_stats"]


#: Share of the declared closing hook's content words the chapter's last two paragraphs must carry (donor shenbi
#: verbatim closing-hook match, loosened for a small writer that rewords).
CLOSING_HOOK_OVERLAP = 0.5


def closing_hook_findings(hook: str | None, last_scene: str, *, node_id: str) -> tuple[Finding, ...]:
    """A chapter whose last scene does not end on the closing hook its plan declared: recorded, never repaired, until
    real chapters set the threshold."""
    if not hook:
        return ()
    tail = "\n\n".join(_paragraphs(last_scene)[-2:])
    wanted = set(_words(hook))
    if not wanted or len(wanted & set(_words(tail))) / len(wanted) >= CLOSING_HOOK_OVERLAP:
        return ()
    last = re.split(r"(?<=[.!?…])\s+", tail.strip())[-1] if tail.strip() else ""
    return (
        Finding(
            "CLOSING_HOOK",
            Severity.STYLISTIC,
            node_id,
            f"chương không kết bằng câu móc đã định: “{hook}”",
            last,
        ),
    )


# --- next-chapter leak (donor huohuo next_chapter_beat_leak) -----------------------------------------

#: Words a beat shares with any prose; a beat bigram made only of them says nothing about the beat.
_LEAK_STOP = frozenset(
    [
        "và",
        "của",
        "là",
        "có",
        "những",
        "một",
        "các",
        "được",
        "cho",
        "với",
        "trong",
        "khi",
        "đã",
        "đang",
        "sẽ",
        "không",
        "này",
        "đó",
        "ấy",
        "thì",
        "mà",
        "rồi",
        "lại",
        "cũng",
        "như",
        "để",
        "từ",
        "ra",
        "vào",
        "lên",
        "xuống",
        "anh",
        "cô",
        "em",
        "ông",
        "bà",
        "nó",
        "họ",
        "mình",
        "tôi",
        "người",
        "việc",
    ]
)
#: Share of a beat's content bigrams the prose must carry for the beat to count as written; on the real-scene
#: fixtures a chapter carries 50-100 % of its own beats and 0-25 % of the next chapter's at this share.
BEAT_WRITTEN_SHARE = 0.5


def _bigrams(text: str) -> set[tuple[str, str]]:
    words = _words(text)
    return {(a, b) for a, b in itertools.pairwise(words) if a not in _LEAK_STOP and b not in _LEAK_STOP}


def beat_written(prose_bigrams: set[tuple[str, str]], beat: str) -> bool:
    wanted = _bigrams(beat)
    return bool(wanted) and len(wanted & prose_bigrams) / len(wanted) >= BEAT_WRITTEN_SHARE


def next_chapter_leak_findings(
    chapter_text: str, beats: Sequence[str], next_beats: Sequence[str], *, node_id: str
) -> tuple[Finding, ...]:
    """A chapter that writes the next chapter's beats (donor huohuo: at least max(2, 45 %) of them). Huohuo also
    excuses a chapter that wrote its own beats; with a beat counted at half its content bigrams a real chapter
    carries at most 25 % of the next one's, so a chapter that wrote both is reported too."""
    if len(next_beats) < 2 or not beats:
        return ()
    prose = _bigrams(chapter_text)
    own = sum(beat_written(prose, b) for b in beats)
    leaked = [b for b in next_beats if beat_written(prose, b)]
    if len(leaked) < max(2, -(-len(next_beats) * 45 // 100)):
        return ()
    wanted = _bigrams(leaked[0])
    sentences = re.split(r"(?<=[.!?…])\s+", chapter_text.strip())
    quote = max(sentences, key=lambda s: len(_bigrams(s) & wanted)) if sentences else ""
    return (
        Finding(
            "NEXT_CHAPTER_LEAK",
            Severity.NARRATIVE_CRITICAL,
            node_id,
            f"chương đã viết trước {len(leaked)}/{len(next_beats)} nhịp của chương sau (như “{leaked[0]}”) "
            f"trong khi mới viết {own}/{len(beats)} nhịp của mình; bỏ phần thuộc chương sau, viết đủ nhịp của chương này",
            quote,
        ),
    )
