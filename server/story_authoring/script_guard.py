"""The one CJK detector shared by runtime validation, export and acceptance.

The range table is generated from the Unicode data files vendored under ``data/unicode/<version>/`` and
committed in ``_cjk_ranges.py``; it never depends on the interpreter's ``unicodedata`` version. A code point
is CJK when its script is one of :data:`CJK_SCRIPTS`, or when it lies in one of :data:`CJK_BLOCKS` (CJK
punctuation, fullwidth forms, radicals and other Common-script characters of CJK typography).
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass

from server.story_authoring._cjk_ranges import CJK_RANGES

CJK_SCRIPTS = frozenset({"Han", "Hiragana", "Katakana", "Hangul", "Bopomofo"})
CJK_BLOCKS = frozenset(
    {
        "CJK Radicals Supplement",
        "Kangxi Radicals",
        "Ideographic Description Characters",
        "CJK Symbols and Punctuation",
        "Kanbun",
        "CJK Strokes",
        "Enclosed CJK Letters and Months",
        "CJK Compatibility",
        "Vertical Forms",
        "CJK Compatibility Forms",
        "Halfwidth and Fullwidth Forms",
        "Ideographic Symbols and Punctuation",
        "Enclosed Ideographic Supplement",
    }
)

_STARTS = tuple(start for start, _ in CJK_RANGES)
_BMP_END = 0xFFFF


@dataclass(frozen=True)
class CjkHit:
    index: int
    char: str


def is_cjk(char: str) -> bool:
    code = ord(char)
    position = bisect.bisect_right(_STARTS, code) - 1
    return position >= 0 and code <= CJK_RANGES[position][1]


def find_cjk(text: str) -> tuple[CjkHit, ...]:
    return tuple(CjkHit(index, char) for index, char in enumerate(text) if is_cjk(char))


def has_cjk(text: str) -> bool:
    return any(is_cjk(char) for char in text)


def no_cjk_pattern(*, include_astral: bool = True) -> str:
    """A JSON-schema ``pattern`` for grammar-constrained JSON strings that cannot carry CJK.

    Ollama applies a string ``pattern`` to the raw characters between the quotes, replacing the default
    JSON-string grammar. The pattern therefore also excludes ``"``, ``\\`` and control characters, and admits
    only the short JSON escapes; ``\\u`` escapes are excluded so that no CJK can be spelled as an escape.
    ``include_astral=False`` drops the supplementary-plane ranges, for grammar engines that reject them.
    """
    parts = []
    for start, end in CJK_RANGES:
        if start > _BMP_END and not include_astral:
            continue
        parts.append(_escape(start) if start == end else f"{_escape(start)}-{_escape(end)}")
    return '^([^"\\\\\\u0000-\\u001f' + "".join(parts) + ']|\\\\["\\\\/bfnrt])*$'


def _escape(code: int) -> str:
    return f"\\u{code:04x}" if code <= _BMP_END else chr(code)


_SCRIPT_LINE = re.compile(r"^([0-9A-F]{4,6})(?:\.\.([0-9A-F]{4,6}))?\s*;\s*([A-Za-z_]+)")
_BLOCK_LINE = re.compile(r"^([0-9A-F]{4,6})\.\.([0-9A-F]{4,6})\s*;\s*(.+?)\s*$")


def build_cjk_ranges(scripts_txt: str, blocks_txt: str) -> tuple[tuple[int, int], ...]:
    """Generate the merged range table from ``Scripts.txt`` and ``Blocks.txt`` contents."""
    ranges: list[tuple[int, int]] = []
    for line in scripts_txt.splitlines():
        match = _SCRIPT_LINE.match(line)
        if match and match.group(3).replace("_", " ") in CJK_SCRIPTS:
            start = int(match.group(1), 16)
            ranges.append((start, int(match.group(2), 16) if match.group(2) else start))
    for line in blocks_txt.splitlines():
        match = _BLOCK_LINE.match(line)
        if match and match.group(3) in CJK_BLOCKS:
            ranges.append((int(match.group(1), 16), int(match.group(2), 16)))
    return _merge(ranges)


def _merge(ranges: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)
