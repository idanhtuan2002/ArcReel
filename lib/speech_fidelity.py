"""Whether a film says its narration: a transcript of its sound against the script's words (OpenMontage's final review).

OpenMontage transcribes the rendered narration and compares it with the script — word accuracy of at least 0.9, and
punctuation the TTS read aloud (``tools/video/video_compose.py`` at 08e2151). A misread or skipped word passes every
signal check (the line decodes, is loud enough, has no long silence) and is heard only by a viewer.

Words are compared lower-cased with punctuation removed, so a transcript's own punctuation and capitals never count.
Accuracy is ``1 - word edit distance / reference words`` (one minus the word error rate), floored at 0.
"""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass

#: OpenMontage's pass mark for transcript word accuracy.
MIN_WORD_ACCURACY = 0.9
#: Words a TTS says when it reads a symbol aloud instead of skipping it.
SPOKEN_SYMBOLS = {
    "vi": ("dấu sao", "dấu thăng", "dấu gạch chéo", "dấu ngoặc", "dấu hai chấm", "gạch dưới", "a còng", "hashtag"),
    "en": ("asterisk", "hashtag", "underscore", "slash", "backslash", "open bracket", "close bracket"),
    "zh": ("星号", "井号", "下划线", "斜杠", "反斜杠"),
}


def words(text: str) -> list[str]:
    """``text`` as lower-case words without punctuation; a script without spaces (CJK) is compared by character."""
    normalized = unicodedata.normalize("NFC", text).lower()
    cleaned = "".join(char if char.isalnum() else " " for char in normalized)
    split = cleaned.split()
    if any(_is_cjk(char) for char in cleaned):
        return [char for word in split for char in word]
    return split


def _is_cjk(char: str) -> bool:
    return "㐀" <= char <= "鿿" or "豈" <= char <= "﫿"


@dataclass(frozen=True)
class SpeechComparison:
    accuracy: float
    #: Script words the transcript lacks or has as other words, in order, at most a few.
    misheard: tuple[str, ...]
    #: Symbol names the transcript says and the script does not.
    spoken_symbols: tuple[str, ...]


def compare(script: str, transcript: str, *, language: str = "vi", sample: int = 8) -> SpeechComparison:
    reference, heard = words(script), words(transcript)
    matcher = difflib.SequenceMatcher(None, reference, heard, autojunk=False)
    errors = 0
    misheard: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        errors += max(i2 - i1, j2 - j1)
        misheard.extend(reference[i1:i2])
    accuracy = max(0.0, 1 - errors / len(reference)) if reference else 1.0
    said, written = " ".join(heard), " ".join(reference)
    symbols = tuple(
        name for name in SPOKEN_SYMBOLS.get(language.split("-")[0], ()) if name in said and name not in written
    )
    return SpeechComparison(round(accuracy, 3), tuple(misheard[:sample]), symbols)


__all__ = ["MIN_WORD_ACCURACY", "SPOKEN_SYMBOLS", "SpeechComparison", "compare", "words"]
