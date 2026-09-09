"""Clean-room Python port of the seven selected pure exports from the Huohuo
``novel-change-record.ts`` change-record parser/normalizer.

Donor pin: ``appolloqin/huohuo-drama@f104b853b3563e124d9cde25f9331d323fb483b9``
``workbench-server/src/common/novel/novel-change-record.ts`` (source SHA-256
``dd3a310e1d83f80fca132a6ea64380c3d953c780054d0ea93e9f865c09fb5088``). Behaviour is
matched branch-for-branch and verified against the unmodified source through the Node
parity harness (``tests/integration/donor_parity``). This module is pure: it
parses/normalizes a raw change-record string into proposal-only structured evidence. It
is not a ``NarrativeChangeSet`` and carries no lineage, decision, or Canon identity.

ECMAScript whitespace differs from Python defaults: the JS ``\\s`` class and
``String.prototype.trim()`` INCLUDE U+FEFF (BOM) and EXCLUDE the C0 information
separators U+001C-U+001F and NEL U+0085. Every ``\\s`` is replaced with the explicit
JS class ``_W`` and every ``str.strip()`` with ``_js_trim`` so the two engines agree
byte for byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Exact ECMAScript WhiteSpace + LineTerminator code points (no ``u`` flag): TAB LF VT FF
# CR SP NBSP OGHAM-SPACE, U+2000..U+200A, LS PS NNBSP MMSP IDEOGRAPHIC-SPACE, U+FEFF.
_JS_WS_CODEPOINTS: tuple[int, ...] = (
    0x09,
    0x0A,
    0x0B,
    0x0C,
    0x0D,
    0x20,
    0xA0,
    0x1680,
    *range(0x2000, 0x200B),
    0x2028,
    0x2029,
    0x202F,
    0x205F,
    0x3000,
    0xFEFF,
)
_JS_WS_CHARS = "".join(chr(cp) for cp in _JS_WS_CODEPOINTS)
_W = "[" + _JS_WS_CHARS + "]"
_N = "[^" + _JS_WS_CHARS + "]"


def _js_trim(value: str) -> str:
    return value.strip(_JS_WS_CHARS)


_CHANGE_RECORD_RE = re.compile("^【变更记录】", re.MULTILINE)
_CHANGE_RECORD_SPLIT_RE = re.compile("(?=^【变更记录】)", re.MULTILINE)
_STRUCTURED_CHANGE_RE = re.compile(rf"(?:^|\n){_W}*[-*]{_W}*[^:：\n]+[:：][^\n]+\n{_W}*因果{_W}*[:：]{_W}*{_N}{{4,}}")

_CANONICALIZE_RE = re.compile(
    r"(^|\n)[ \t]*(?:#{1,3}[ \t]*)?(?:\*{1,2}[ \t]*)?【[ \t]*变更记录[ \t]*】(?:[ \t]*\*{1,2})?[ \t]*(?=\r?\n|\Z)"
)
_META_BULLET_FIELD_RE = re.compile(rf"^[-*]{_W}*[^:：\n]+[:：]")
_META_NO_CHANGE_RE = re.compile(rf"^[-*]{_W}*.*无状态变化")
_META_FIELD_LINE_RE = re.compile(rf"^(因果|触发|代价|感知|耗时){_W}*[:：]")
_CAUSE_MIN_RE = re.compile(rf"因果{_W}*[:：]{_W}*{_N}{{4,}}")
_NO_STATE_CHANGE_RE = re.compile("无状态变化")
_HEADER_PREFIX_RE = re.compile(rf"^【变更记录】{_W}*", re.MULTILINE)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_HARD_WORDCOUNT_RE = re.compile(r"^【硬性字数】[^\n]*\n+", re.MULTILINE)
_NO_WATER_RE = re.compile(rf"^在原线索上加场面与反应，禁止注水。{_W}*", re.MULTILINE)
_ECHO_MARKER_RE = re.compile("【待补写正文】|【待压缩正文】")


@dataclass(frozen=True)
class ParsedChangeRecord:
    """Frozen result of ``normalize_change_record_artifacts`` -- proposal evidence only."""

    prose: str
    change_block: str | None
    reclaimed_fake_blocks: int


def canonicalize_change_record_headers(text: str | None) -> str:
    return _CANONICALIZE_RE.sub(r"\1【变更记录】", text or "")


def _is_change_record_meta_line(line: str) -> bool:
    t = _js_trim(line)
    if not t:
        return True
    if _META_BULLET_FIELD_RE.search(t):
        return True
    if _META_NO_CHANGE_RE.search(t):
        return True
    return bool(_META_FIELD_LINE_RE.search(t))


def _looks_like_change_entry_start(line: str) -> bool:
    t = _js_trim(line)
    return bool(_META_BULLET_FIELD_RE.search(t) or _META_NO_CHANGE_RE.search(t))


def _ensure_change_record_header(block: str) -> str:
    t = _js_trim(block or "")
    if not t:
        return t
    if _CHANGE_RECORD_RE.search(t):
        return t
    return f"【变更记录】\n{t}"


def _strip_change_record_header(block: str) -> str:
    return _js_trim(_HEADER_PREFIX_RE.sub("", canonicalize_change_record_headers(block), count=1))


def split_structured_block_and_trailing_prose(block: str | None) -> tuple[str, str]:
    """Return ``(change_block, trailing_prose)``: the structured metadata versus the
    story prose that follows it inside one ``【变更记录】`` block."""
    raw = _js_trim(block or "")
    if not raw:
        return "", ""

    lines = re.split(r"\r?\n", raw)
    i = 0
    if _CHANGE_RECORD_RE.search(_js_trim(lines[0] if lines else "")):
        i = 1

    last_meta_idx = i - 1
    while i < len(lines):
        if _is_change_record_meta_line(lines[i]):
            if _js_trim(lines[i]):
                last_meta_idx = i
            i += 1
            continue
        break

    if i >= len(lines):
        return _ensure_change_record_header(raw), ""

    change_lines = lines[: max(last_meta_idx + 1, 1)]
    trailing_lines = lines[last_meta_idx + 1 :]
    while trailing_lines and not _js_trim(trailing_lines[0]):
        trailing_lines.pop(0)

    return (
        _ensure_change_record_header(_js_trim("\n".join(change_lines))),
        _js_trim("\n".join(trailing_lines)),
    )


def is_structured_change_record_block(block: str | None) -> bool:
    b = canonicalize_change_record_headers(block or "")
    if _STRUCTURED_CHANGE_RE.search(b):
        return True
    return bool(_NO_STATE_CHANGE_RE.search(b) and _CAUSE_MIN_RE.search(b))


def peel_orphaned_structured_from_prose(prose: str | None) -> tuple[str, list[str]]:
    """Strip runs of orphaned ``- 维: / 因果:`` metadata lines that a model inlined into
    prose without a ``【变更记录】`` header. Returns ``(prose, change_blocks)``."""
    raw = _js_trim(prose or "")
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
            if _js_trim(lines[j]):
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
    return _js_trim(_MULTI_BLANK_RE.sub("\n\n", "\n".join(out))), change_blocks


def normalize_change_record_artifacts(full_text: str | None) -> ParsedChangeRecord:
    """Correct bolded headers, headerless entries, and change records wedged into the
    middle of prose. Structured blocks become metadata (last block wins); prose after a
    block and fake blocks are reclaimed into the story prose."""
    trimmed = _js_trim(canonicalize_change_record_headers(full_text or ""))
    if not trimmed:
        return ParsedChangeRecord(prose="", change_block=None, reclaimed_fake_blocks=0)

    prose_parts: list[str] = []
    structured: str | None = None
    reclaimed_fake_blocks = 0

    if _CHANGE_RECORD_RE.search(trimmed):
        parts = _CHANGE_RECORD_SPLIT_RE.split(trimmed)
        for part in parts:
            t = _js_trim(part)
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

    prose = _js_trim("\n\n".join(prose_parts))
    peeled_prose, peeled_blocks = peel_orphaned_structured_from_prose(prose)
    if peeled_blocks:
        prose = peeled_prose
        reclaimed_fake_blocks += len(peeled_blocks)
        if not structured:
            structured = peeled_blocks[-1]

    return ParsedChangeRecord(prose=prose, change_block=structured, reclaimed_fake_blocks=reclaimed_fake_blocks)


def split_prose_and_change_record(full_text: str | None) -> tuple[str, str | None]:
    """The persistence/review split: always via ``normalize_change_record_artifacts``."""
    parsed = normalize_change_record_artifacts(full_text)
    return parsed.prose, parsed.change_block


def _utf16_length(value: str) -> int:
    """UTF-16 code-unit count of ``value`` -- what a JavaScript string index counts."""
    return len(value.encode("utf-16-le")) // 2


def strip_length_adjust_instruction_echo(text: str | None) -> str:
    """Remove an echoed length-adjust system prompt from the top of the prose. Genre
    agnostic: only recognises the system-instruction markers."""
    t = _js_trim(text or "")
    if not t:
        return t
    marker = _ECHO_MARKER_RE.search(t)
    # JS compares ``marker.index`` (a UTF-16 code-unit offset) against 360.
    if marker is not None and _utf16_length(t[: marker.start()]) < 360:
        t = _js_trim(t[marker.end() :])
    t = _js_trim(_HARD_WORDCOUNT_RE.sub("", t))
    return _js_trim(_NO_WATER_RE.sub("", t, count=1))
