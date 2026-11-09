"""Deterministic checks across a manuscript's chapters (ADR-0117): long-span repetition, monotonous openings and a
continuation's voice drift. None calls a model; every finding is stylistic, because the thresholds are not
calibrated on Vietnamese text, and each quotes the manuscript verbatim.

Donor surfaces: shenbi ``review-long-span`` (n-gram reuse against earlier chapters), ``chapter-pattern``
(structural monotony) and ``sequel-writing`` step 4 (drift of the first new chapters against the text continued).
"""

from __future__ import annotations

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
