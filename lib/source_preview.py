"""A preview of a project's story sources before a run reads them (ADR-0118): the chapters each file's headings
mark, its size, and what may go wrong. Nothing here calls a model.

Donor surface: DramaClaw's import format check (``cognee/chapter_detector.py``: chapter headings with numerals or
words, single-chapter fallback; ``utils/screenplay_quality.py``: issues shown before ``start``), extended with
Vietnamese and English headings.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from lib.episode_ledger import SourceDoc
from lib.text_attestation import has_cjk

#: ``Chương 1``, ``CHƯƠNG XII``, ``Chapter 3``, ``Hồi 2``, ``Phần một``, ``第3章``, or a Markdown heading.
_HEADING = re.compile(
    r"^\s*(?:#{1,3}\s+.+|(?:chương|chuong|chapter|hồi|hoi|phần|phan|quyển|quyen)\s+[\w.]+.*|第\s*[0-9一二三四五六七八九十百千零两]+\s*[章回节].*)$",
    re.IGNORECASE | re.MULTILINE,
)
LONG_CHAPTER_CHARS = 40_000
HEADINGS_SHOWN = 40


@dataclass(frozen=True)
class SourcePreview:
    rel_path: str
    chars: int
    chapters: int
    headings: tuple[str, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


def preview_source(doc: SourceDoc) -> SourcePreview:
    text = doc.text
    matches = list(_HEADING.finditer(text))
    warnings: list[str] = []
    if not text.strip():
        warnings.append("EMPTY")
    elif not matches:
        warnings.append("NO_CHAPTER_HEADINGS")
    if has_cjk(text):
        warnings.append("CJK_TEXT")
    bounds = [m.start() for m in matches] + [len(text)]
    if any(b - a > LONG_CHAPTER_CHARS for a, b in zip([0, *bounds[:-1]], bounds, strict=True)):
        warnings.append("LONG_CHAPTER")
    return SourcePreview(
        rel_path=doc.rel_path,
        chars=len(text),
        chapters=max(1, len(matches)) if text.strip() else 0,
        headings=tuple(m.group(0).strip()[:120] for m in matches[:HEADINGS_SHOWN]),
        warnings=tuple(warnings),
    )


def preview_sources(docs: Sequence[SourceDoc]) -> list[SourcePreview]:
    return [preview_source(doc) for doc in docs]


__all__ = ["SourcePreview", "preview_source", "preview_sources"]
