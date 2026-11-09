"""Whether a text attests a name or a quote, compared on letters and digits (ADR-0114, asset extraction).

Model output often re-spaces or re-punctuates what it copies; comparing the lower-case letters and digits keeps
the check strict about words while tolerant of punctuation. A name must appear as whole words (``Ann`` is not
written by ``annual``); scripts without spaces between words (CJK) are matched as text.
"""

from __future__ import annotations

import bisect
import unicodedata

from lib.cjk_ranges import CJK_RANGES

_CJK_STARTS = [start for start, _ in CJK_RANGES]


def skeleton(text: str) -> tuple[str, list[int]]:
    """Lower-case letters and digits of ``text`` (accents kept) with each one's offset in ``text``."""
    chars, offsets = [], []
    for index, char in enumerate(unicodedata.normalize("NFC", text)):
        if char.isalnum():
            chars.append(char.lower())
            offsets.append(index)
    return "".join(chars), offsets


def has_cjk(text: str) -> bool:
    for char in text:
        code = ord(char)
        position = bisect.bisect_right(_CJK_STARTS, code) - 1
        if position >= 0 and code <= CJK_RANGES[position][1]:
            return True
    return False


def _words(text: str) -> str:
    """Lower-case words of ``text`` separated by single spaces, with spaces at both ends."""
    words = "".join(char.lower() if char.isalnum() else " " for char in unicodedata.normalize("NFC", text)).split()
    return " " + " ".join(words) + " "


def named_in(name: str, source: str) -> bool:
    """Whether ``source`` writes ``name``: as whole words, or as text in a CJK source. A name of punctuation only
    names nobody."""
    letters = skeleton(name)[0]
    if not letters:
        return False
    if has_cjk(source):
        return letters in skeleton(source)[0]
    return _words(name) in _words(source)


__all__ = ["has_cjk", "named_in", "skeleton"]
