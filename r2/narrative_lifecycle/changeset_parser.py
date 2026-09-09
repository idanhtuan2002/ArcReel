"""Clean-room Python port of the seven selected pure exports from the Huohuo
``novel-change-record.ts`` change-record parser/normalizer.

Donor pin: ``appolloqin/huohuo-drama@f104b853b3563e124d9cde25f9331d323fb483b9``
``workbench-server/src/common/novel/novel-change-record.ts`` (source SHA-256
``dd3a310e1d83f80fca132a6ea64380c3d953c780054d0ea93e9f865c09fb5088``). Behaviour is
matched branch-for-branch and verified against the unmodified source through the Node
parity harness (``tests/donor_parity``). This module is pure: it parses/normalizes a raw
change-record string into proposal-only structured evidence. It is not a
``NarrativeChangeSet`` and carries no lineage, decision, or Canon identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CHANGE_RECORD_RE = re.compile(r"^【变更记录】", re.MULTILINE)
_CHANGE_RECORD_SPLIT_RE = re.compile(r"(?=^【变更记录】)", re.MULTILINE)
_STRUCTURED_CHANGE_RE = re.compile(r"(?:^|\n)\s*[-*]\s*[^:：\n]+[:：][^\n]+\n\s*因果\s*[:：]\s*\S{4,}")

_CANONICALIZE_RE = re.compile(
    r"(^|\n)[ \t]*(?:#{1,3}[ \t]*)?(?:\*{1,2}[ \t]*)?【[ \t]*变更记录[ \t]*】(?:[ \t]*\*{1,2})?[ \t]*(?=\r?\n|\Z)"
)
_META_BULLET_FIELD_RE = re.compile(r"^[-*]\s*[^:：\n]+[:：]")
_META_NO_CHANGE_RE = re.compile(r"^[-*]\s*.*无状态变化")
_META_FIELD_LINE_RE = re.compile(r"^(因果|触发|代价|感知|耗时)\s*[:：]")
_CAUSE_MIN_RE = re.compile(r"因果\s*[:：]\s*\S{4,}")
_NO_STATE_CHANGE_RE = re.compile(r"无状态变化")
_HEADER_PREFIX_RE = re.compile(r"^【变更记录】\s*", re.MULTILINE)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_HARD_WORDCOUNT_RE = re.compile(r"^【硬性字数】[^\n]*\n+", re.MULTILINE)
_NO_WATER_RE = re.compile(r"^在原线索上加场面与反应，禁止注水。\s*", re.MULTILINE)
_ECHO_MARKER_RE = re.compile(r"【待补写正文】|【待压缩正文】")


@dataclass(frozen=True)
class ParsedChangeRecord:
    """Frozen result of :func:`normalize_change_record_artifacts` — proposal evidence only."""

    prose: str
    change_block: str | None
    reclaimed_fake_blocks: int


def canonicalize_change_record_headers(text: str | None) -> str:
    return _CANONICALIZE_RE.sub(r"\1【变更记录】", text or "")


def _is_change_record_meta_line(line: str) -> bool:
    t = line.strip()
    if not t:
        return True
    if _META_BULLET_FIELD_RE.search(t):
        return True
    if _META_NO_CHANGE_RE.search(t):
        return True
    return bool(_META_FIELD_LINE_RE.search(t))


def _looks_like_change_entry_start(line: str) -> bool:
    t = line.strip()
    return bool(_META_BULLET_FIELD_RE.search(t) or _META_NO_CHANGE_RE.search(t))


def _ensure_change_record_header(block: str) -> str:
    t = (block or "").strip()
    if not t:
        return t
    if _CHANGE_RECORD_RE.search(t):
        return t
    return f"【变更记录】\n{t}"


def _strip_change_record_header(block: str) -> str:
    return _HEADER_PREFIX_RE.sub("", canonicalize_change_record_headers(block), count=1).strip()


def split_structured_block_and_trailing_prose(block: str | None) -> tuple[str, str]:
    """Return ``(change_block, trailing_prose)``: the structured metadata versus the
    story prose that follows it inside one ``【变更记录】`` block."""
    raw = (block or "").strip()
    if not raw:
        return "", ""

    lines = re.split(r"\r?\n", raw)
    i = 0
    if _CHANGE_RECORD_RE.search((lines[0] if lines else "").strip()):
        i = 1

    last_meta_idx = i - 1
    while i < len(lines):
        if _is_change_record_meta_line(lines[i]):
            if lines[i].strip():
                last_meta_idx = i
            i += 1
            continue
        break

    if i >= len(lines):
        return _ensure_change_record_header(raw), ""

    change_lines = lines[: max(last_meta_idx + 1, 1)]
    trailing_lines = lines[last_meta_idx + 1 :]
    while trailing_lines and not trailing_lines[0].strip():
        trailing_lines.pop(0)

    return (
        _ensure_change_record_header("\n".join(change_lines).strip()),
        "\n".join(trailing_lines).strip(),
    )


def is_structured_change_record_block(block: str | None) -> bool:
    b = canonicalize_change_record_headers(block or "")
    if _STRUCTURED_CHANGE_RE.search(b):
        return True
    return bool(_NO_STATE_CHANGE_RE.search(b) and _CAUSE_MIN_RE.search(b))


def peel_orphaned_structured_from_prose(prose: str | None) -> tuple[str, list[str]]:
    """Strip runs of orphaned ``- 维: / 因果:`` metadata lines that a model inlined into
    prose without a ``【变更记录】`` header. Returns ``(prose, change_blocks)``."""
    raw = (prose or "").strip()
    if not raw:
        return "", []
    if not _STRUCTURED_CHANGE_RE.search(raw) and not (_NO_STATE_CHANGE_RE.search(raw) and _CAUSE_MIN_RE.search(raw)):
        return raw, []

    lines = re.split(r"\r?\n", raw)
    keep = [True] * len(lines)
    change_blocks: list[str] = []
    i = 0
    while i < len(lines):
        if not _looks_like_change_entry_start(lines[i]):
            i += 1
            continue
        j = i
        last_non_empty = i
        while j < len(lines) and _is_change_record_meta_line(lines[j]):
            if lines[j].strip():
                last_non_empty = j
            j += 1
        chunk = "\n".join(lines[i : last_non_empty + 1])
        if is_structured_change_record_block(chunk) or is_structured_change_record_block(
            _ensure_change_record_header(chunk)
        ):
            change_blocks.append(_ensure_change_record_header(chunk))
            for k in range(i, last_non_empty + 1):
                keep[k] = False
            i = last_non_empty + 1
            continue
        i += 1

    if not change_blocks:
        return raw, []

    out = [lines[k] for k in range(len(lines)) if keep[k]]
    return _MULTI_BLANK_RE.sub("\n\n", "\n".join(out)).strip(), change_blocks


def normalize_change_record_artifacts(full_text: str | None) -> ParsedChangeRecord:
    """Correct bolded headers, headerless entries, and change records wedged into the
    middle of prose. Structured blocks become metadata (last block wins); prose after a
    block and fake blocks are reclaimed into the story prose."""
    trimmed = canonicalize_change_record_headers(full_text or "").strip()
    if not trimmed:
        return ParsedChangeRecord(prose="", change_block=None, reclaimed_fake_blocks=0)

    prose_parts: list[str] = []
    structured: str | None = None
    reclaimed_fake_blocks = 0

    if _CHANGE_RECORD_RE.search(trimmed):
        parts = _CHANGE_RECORD_SPLIT_RE.split(trimmed)
        for part in parts:
            t = part.strip()
            if not t:
                continue
            if not _CHANGE_RECORD_RE.search(t):
                prose_parts.append(t)
                continue
            if is_structured_change_record_block(t):
                change_block, trailing_prose = split_structured_block_and_trailing_prose(t)
                if structured:
                    prose_parts.append(_strip_change_record_header(structured))
                    reclaimed_fake_blocks += 1
                structured = change_block
                if trailing_prose:
                    prose_parts.append(trailing_prose)
                    reclaimed_fake_blocks += 1
            else:
                body = _strip_change_record_header(t)
                if body:
                    prose_parts.append(body)
                reclaimed_fake_blocks += 1
    else:
        prose_parts.append(trimmed)

    prose = "\n\n".join(prose_parts).strip()
    peeled_prose, peeled_blocks = peel_orphaned_structured_from_prose(prose)
    if peeled_blocks:
        prose = peeled_prose
        reclaimed_fake_blocks += len(peeled_blocks)
        if not structured:
            structured = peeled_blocks[-1]

    return ParsedChangeRecord(prose=prose, change_block=structured, reclaimed_fake_blocks=reclaimed_fake_blocks)


def split_prose_and_change_record(full_text: str | None) -> tuple[str, str | None]:
    """The persistence/review split: always via :func:`normalize_change_record_artifacts`."""
    parsed = normalize_change_record_artifacts(full_text)
    return parsed.prose, parsed.change_block


def strip_length_adjust_instruction_echo(text: str | None) -> str:
    """Remove an echoed length-adjust system prompt from the top of the prose. Genre
    agnostic: only recognises the system-instruction markers."""
    t = (text or "").strip()
    if not t:
        return t
    marker = _ECHO_MARKER_RE.search(t)
    if marker is not None and marker.start() < 360:
        t = t[marker.end() :].strip()
    t = _HARD_WORDCOUNT_RE.sub("", t).strip()
    return _NO_WATER_RE.sub("", t, count=1).strip()
