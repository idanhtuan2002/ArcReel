"""Natural paragraphs for the exported story (stage-by-stage F2).

The writer returns scenes as blocks of a bounded length, which keeps scene length under control but packs dialogue
into long blocks. The export lays each scene out again, in code and with no model call (donor huohuo
``novel-paragraph-format.ts``: quote-aware sentence split, narration paragraphs of one to three sentences, a dialogue
line starting its own paragraph, orphans merged; donor shenbi 02d3381 warns against the opposite failure, a paragraph
per sentence, so narration keeps up to three sentences and a dialogue line keeps its attribution and one action
sentence). The text is unchanged: only the breaks between paragraphs move, never across a scene.
"""

from __future__ import annotations

import re

_END = ".!?…"
_CLOSERS = '”"»)’'
_OPENERS = '“"«'
_DASHES = ("—", "–", "- ")
#: Sentences per narration paragraph, in turn, so paragraphs vary in length.
_NARRATION_TARGETS = (2, 3, 1, 3, 2)
#: A sentence this short (in words) joins the paragraph after it rather than standing alone.
_ORPHAN_WORDS = 3


def sentences(text: str) -> list[str]:
    """The text's sentences in order, never split inside a quotation."""
    flat = " ".join(text.split())
    found: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(flat):
        ch = flat[i]
        closed_after_end = False
        if ch == "“" or ch == "«":
            depth += 1
        elif (ch == "”" or ch == "»") and depth:
            depth -= 1
            closed_after_end = depth == 0 and i > 0 and flat[i - 1] in _END
        elif ch == '"':
            depth = 0 if depth else 1
        if (ch in _END and depth == 0) or closed_after_end:
            j = i + 1
            while j < len(flat) and (flat[j] in _END or flat[j] in _CLOSERS):
                j += 1
            if j >= len(flat) or (flat[j] == " " and j + 1 < len(flat) and _starts_sentence(flat[j + 1 :])):
                found.append(flat[start:j].strip())
                start = j
                i = j
                continue
        i += 1
    tail = flat[start:].strip()
    if tail:
        found.append(tail)
    return found


def _starts_sentence(rest: str) -> bool:
    head = rest[:1]
    return head.isupper() or head in _OPENERS or rest.startswith(_DASHES)


def is_dialogue(sentence: str) -> bool:
    return sentence.startswith(_DASHES) or any(q in sentence for q in _OPENERS)


def natural_paragraphs(text: str) -> str:
    """The scene with narration in paragraphs of one to three sentences and each dialogue line starting its own
    paragraph with its attribution and at most one action sentence after it."""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    turn = 0
    for sentence in sentences(text):
        if is_dialogue(sentence):
            if current:
                paragraphs.append(current)
            current = [sentence]
            continue
        if current and is_dialogue(current[0]):
            # One action sentence may follow a dialogue line in its paragraph.
            if len(current) == 1 and len(sentence.split()) <= 25:
                current.append(sentence)
                paragraphs.append(current)
                current = []
                continue
            paragraphs.append(current)
            current = []
        current.append(sentence)
        target = _NARRATION_TARGETS[turn % len(_NARRATION_TARGETS)]
        if len(current) >= target and len(current[-1].split()) > _ORPHAN_WORDS:
            paragraphs.append(current)
            current = []
            turn += 1
    if current:
        paragraphs.append(current)
    return "\n\n".join(" ".join(p) for p in paragraphs)


def same_text(a: str, b: str) -> bool:
    """Whether two layouts hold the same words in the same order."""
    return re.sub(r"\s+", " ", a).strip() == re.sub(r"\s+", " ", b).strip()


__all__ = ["is_dialogue", "natural_paragraphs", "same_text", "sentences"]
