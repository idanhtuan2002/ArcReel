"""Bounded, span-local repair of one scene: deterministic fixes first, then model patches, then length normalizing.

Span repair ports Huohuo ``workbench-server/src/services/novel/novel-continuity-patch.ts`` (pin ``f104b853``, source
sha256 ``4311e814…65b2``): the model returns ``before``/``after`` pairs copied from the text, everything else stays
byte-identical, and a result whose length moves outside 0.85–1.15 of the original is rejected.
``apply_continuity_patches`` and ``build_conflict_excerpt_block`` are clean-room ports verified against the
unmodified source under ``DONOR_PUNCTUATION`` (``tests/integration/donor_parity/test_huohuo_continuity_patch.py``).
Recorded deviations: the patch prompt is Vietnamese and genre-neutral (the donor's cultivation-genre layers are
dropped); the response is a grammar-constrained schema instead of fenced-JSON parsing; quote hints also accept
Vietnamese quotation marks and fallback words keep every Unicode letter (the donor's ``[^\\u4e00-\\u9fa5a-zA-Z0-9]``
splits Vietnamese words); length is counted in syllables.

Length normalizing takes Shenbi ``skills/shenbi-length-normalizing/SKILL.md`` (sha256 ``7b9ee8af…30ce``): never
change narrative content, keep the voice, expand by inner life, senses, subtext and transitions, compress by
merging repeated description and trimming modifiers, and stay inside the surface-edit range. Only the selected
paragraphs are rewritten; the others stay byte-identical.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from server.story_authoring.checks import (
    VIETNAMESE_PUNCTUATION,
    Finding,
    PunctuationProfile,
    SceneLengthWindow,
    count_syllables,
    ends_cleanly,
    strip_copied_sentences,
    strip_markup,
    strip_meta_narration,
    strip_replayed_sentences,
    trim_unterminated_tail,
)
from server.story_authoring.contracts import (
    OutputMode,
    StoryDecoding,
    StoryModelSelection,
    StoryScope,
    StoryStepKind,
    StoryStepRequest,
)
from server.story_authoring.generation import AuthoringTextGateway

PATCH_LENGTH_RATIO = (0.85, 1.15)
# Surface compression only: Shenbi's length skill treats 15-20% as safe and rejects below 25% of the original.
COMPRESSION_FLOOR = 0.7
MAX_LENGTH_REWRITES = 6
MAX_PATCHES = 6

# --- JS String.prototype.replace(string, string) ---------------------------------------------------


def _js_replace_first(content: str, before: str, after: str) -> str:
    """``content.replace(before, after)`` with a string pattern, including GetSubstitution's ``$`` patterns."""
    index = content.find(before)
    if index < 0:
        return content
    out: list[str] = []
    i = 0
    while i < len(after):
        ch = after[i]
        if ch == "$" and i + 1 < len(after):
            nxt = after[i + 1]
            if nxt == "$":
                out.append("$")
                i += 2
                continue
            if nxt == "&":
                out.append(before)
                i += 2
                continue
            if nxt == "`":
                out.append(content[:index])
                i += 2
                continue
            if nxt == "'":
                out.append(content[index + len(before) :])
                i += 2
                continue
        out.append(ch)
        i += 1
    return content[:index] + "".join(out) + content[index + len(before) :]


@dataclass(frozen=True)
class ContinuityPatch:
    before: str
    after: str


def _replace_once(content: str, before: str, after: str) -> str | None:
    if not before or before == after:
        return None
    if before in content:
        return _js_replace_first(content, before, after)
    anchor = before[: min(20, len(before))]
    if len(anchor) < 6:
        return None
    idx = content.find(anchor)
    if idx < 0:
        return None
    end = min(len(content), idx + len(before) + 40)
    chunk = content[idx:end]
    if not chunk.startswith(anchor):
        return None
    chunk_end = len(before) if len(chunk) >= len(before) else len(chunk)
    old_slice = content[idx : idx + chunk_end]
    return content[:idx] + after + content[idx + len(old_slice) :]


def apply_continuity_patches(content: str, patches: Sequence[ContinuityPatch]) -> tuple[str, int, int]:
    result = content
    applied = skipped = 0
    for patch in patches:
        hit = _replace_once(result, patch.before, patch.after)
        if hit is not None:
            result = hit
            applied += 1
        else:
            skipped += 1
    return result, applied, skipped


_VI_HINT = re.compile(r"「([^」]{2,80})」|“([^”]{2,80})”|\"([^\"]{2,80})\"")
_DONOR_NON_WORD = re.compile(r"[^一-龥a-zA-Z0-9]")
_VI_NON_WORD = re.compile(r"[^\w]|_")
_JS_WS_CHARS = "".join(
    chr(cp)
    for cp in (
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
)
_JS_WS_RUN = re.compile("[" + re.escape(_JS_WS_CHARS) + "]+")
_DONOR_HINT = re.compile("「([^」]{2,80})」|摘录[：:][" + re.escape(_JS_WS_CHARS) + "]*「([^」]{2,80})」")


def _extract_quoted_hints(conflicts: Sequence[str], profile: PunctuationProfile) -> list[str]:
    pattern = _DONOR_HINT if profile.name == "donor" else _VI_HINT
    hints: dict[str, None] = {}
    for conflict in conflicts:
        for match in pattern.finditer(conflict):
            quote = next((group for group in match.groups() if group), None)
            if quote:
                hints[quote] = None
    return list(hints)


def build_conflict_excerpt_block(
    content: str,
    conflicts: Sequence[str],
    max_chars: int = 3500,
    *,
    profile: PunctuationProfile = VIETNAMESE_PUNCTUATION,
) -> str:
    """The paragraphs a conflict list points at, each with its neighbours, for the patch prompt."""
    hints = _extract_quoted_hints(conflicts, profile)
    paragraphs = [p.strip(_JS_WS_CHARS) for p in re.split(r"\n+", content)]
    paragraphs = [p for p in paragraphs if p]
    picked: set[int] = set()
    for hint in hints:
        picked.update(i for i, p in enumerate(paragraphs) if hint in p)
    if not picked:
        non_word = _DONOR_NON_WORD if profile.name == "donor" else _VI_NON_WORD
        for conflict in conflicts[:4]:
            words = [w for w in _JS_WS_RUN.split(non_word.sub(" ", conflict)) if len(w) >= 2]
            for word in words[:6]:
                picked.update(i for i, p in enumerate(paragraphs) if word in p)
    blocks: list[str] = []
    for i in sorted(picked):
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(paragraphs) and paragraphs[j] not in blocks:
                blocks.append(paragraphs[j])
    excerpt = "\n\n".join(blocks) if blocks else content[: min(len(content), max_chars)]
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + "…"
    return excerpt


# --- model repair ----------------------------------------------------------------------------------

PATCH_SYSTEM = """Bạn là biên tập viên tính liên tục của truyện ngắn tiếng Việt. Nhiệm vụ: CHỈ sửa những câu, lời thoại hoặc lời kể nằm trong danh sách lỗi; mọi phần còn lại của văn bản phải giữ nguyên từng chữ.

Trả về JSON đúng schema:
- "patches": danh sách các bản sửa, mỗi bản có "before" (đoạn chép NGUYÊN VĂN từ văn bản cần sửa, khớp chính xác kể cả dấu câu, nên dài 20–200 ký tự) và "after" (đoạn đã sửa thay vào đúng vị trí đó);
- "notes": ghi chú ngắn, có thể để trống.

Quy tắc:
- "before" phải chép nguyên văn từ phần [Văn bản cần sửa], kể cả dấu câu.
- Mỗi bản sửa chỉ sửa một chỗ; độ dài "after" chênh không quá 30% so với "before"; giữ nguyên xuống dòng và đoạn văn.
- Lỗi về tình tiết, địa điểm, hành động nhân vật: lấy sự thật đã khóa trong bối cảnh làm chuẩn và sửa trọn đoạn liên quan, không được chỉ đổi một từ mà để lại mâu thuẫn.
- Nếu cần sửa nhiều chỗ mới nhất quán, trả về 2–4 bản sửa; nếu không định vị được thì trả "patches" rỗng.
- Chỉ viết tiếng Việt; không thêm nhân vật, sự kiện hay tên riêng mới."""


class _PatchItem(BaseModel):
    model_config = {"extra": "forbid"}
    before: str
    after: str


class PatchResponse(BaseModel):
    model_config = {"extra": "forbid"}
    patches: list[_PatchItem] = Field(max_length=MAX_PATCHES)
    notes: str


class _ParagraphRewrite(BaseModel):
    model_config = {"extra": "forbid"}
    index: int
    text: str


class LengthResponse(BaseModel):
    model_config = {"extra": "forbid"}
    rewrites: list[_ParagraphRewrite] = Field(max_length=MAX_LENGTH_REWRITES)


@dataclass(frozen=True)
class RepairOutcome:
    text: str
    accepted: bool
    reason: str
    applied: int = 0
    skipped: int = 0


def deterministic_fixes(
    text: str, findings: Sequence[Finding], *, earlier: Sequence[str] = ()
) -> tuple[str, tuple[str, ...]]:
    """Fixes that need no model: an unfinished last sentence is cut, markdown emphasis and narration about the story itself are dropped, sentences copied
    from earlier scenes and repeated passages are removed by the dedupe core."""
    codes = {f.code for f in findings}
    notes: list[str] = []
    if "PARAGRAPH_CUT" in codes:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        trimmed = [trim_unterminated_tail(p) for p in paragraphs[:-1]] + paragraphs[-1:]
        kept = [p for i, p in enumerate(trimmed) if ends_cleanly(p) or i == len(trimmed) - 1]
        if kept != paragraphs:
            text = "\n\n".join(kept)
            notes.append("cut the unfinished end of paragraphs that stopped mid-sentence")
    if "UNTERMINATED" in codes:
        trimmed = trim_unterminated_tail(text)
        if trimmed != text and ends_cleanly(trimmed):
            text = trimmed
            notes.append("removed an unfinished last sentence")
    if "MARKUP" in codes:
        text = strip_markup(text)
        notes.append("removed markdown emphasis")
    if "META_NARRATION" in codes:
        text, removed = strip_meta_narration(text)
        notes.extend(f"removed narration about the story itself: {r[:56]}" for r in removed)
    if "CROSS_SCENE_REPLAY" in codes:
        text, copied = strip_copied_sentences(text, earlier)
        notes.extend(f"removed sentence copied from an earlier scene: {c[:56]}" for c in copied)
    if "NEAR_DUPLICATE" in codes:
        text, hits = strip_replayed_sentences(text)
        notes.extend(f"removed repeated passage: {hit.excerpt}" for hit in hits)
    return text, tuple(notes)


def _conflict_lines(findings: Sequence[Finding]) -> list[str]:
    return [f"{f.code}: {f.message}" + (f" — “{f.quote}”" if f.quote else "") for f in findings]


async def span_repair(
    gateway: AuthoringTextGateway,
    *,
    scope: StoryScope,
    selection: StoryModelSelection,
    step_id: str,
    context_digest: str,
    decoding: StoryDecoding,
    text: str,
    findings: Sequence[Finding],
    context_block: str,
    attempt_history: Sequence[str] = (),
    max_output_tokens: int = 4096,
    system_prompt: str = PATCH_SYSTEM,
) -> RepairOutcome:
    """One span-local patch call; ``system_prompt`` is the editor instruction (the differential swaps in the donor's)."""
    conflicts = _conflict_lines(findings)
    history = "\n".join(f"- {line}" for line in attempt_history)
    prompt = "\n".join(
        part
        for part in (
            f"[Bối cảnh đã khóa]\n{context_block}" if context_block else "",
            "[Danh sách lỗi cần sửa]\n" + "\n".join(f"- {c}" for c in conflicts),
            f"[Các lần sửa trước chưa đạt]\n{history}" if history else "",
            "[Đoạn liên quan]\n" + build_conflict_excerpt_block(text, conflicts),
            "[Văn bản cần sửa — 'before' phải chép nguyên văn từ đây]\n" + text,
        )
        if part
    )
    output = await gateway.generate(
        scope=scope,
        request=StoryStepRequest(
            step_id=step_id,
            kind=StoryStepKind.REPAIR,
            context_digest=context_digest,
            selection=selection,
            system_prompt=system_prompt,
            prompt=prompt,
            output_mode=OutputMode.STRUCTURED,
            response_model=PatchResponse,
            decoding=decoding,
            max_output_tokens=max_output_tokens,
        ),
    )
    response = PatchResponse.model_validate_json(output.text)
    patches = [ContinuityPatch(p.before.strip(), p.after.strip()) for p in response.patches]
    patches = [p for p in patches if p.before and p.after and p.before != p.after]
    if not patches:
        return RepairOutcome(text, False, "the model located no patch")
    patched, applied, skipped = apply_continuity_patches(text, patches)
    if applied == 0:
        return RepairOutcome(text, False, "no patch matched the text", 0, skipped)
    ratio = count_syllables(patched) / max(1, count_syllables(text))
    low, high = PATCH_LENGTH_RATIO
    if not low <= ratio <= high:
        return RepairOutcome(text, False, f"length ratio {ratio:.2f} outside {low}-{high}", applied, skipped)
    return RepairOutcome(patched, True, "patched", applied, skipped)


LENGTH_SYSTEM = """Bạn là biên tập viên điều chỉnh độ dài cho truyện ngắn tiếng Việt.

Nguyên tắc cứng:
- Không thay đổi nội dung truyện: không thêm, bớt sự kiện; không đổi hành động nhân vật; không động tới chi tiết cài cắm.
- Giữ nguyên giọng văn; không đưa vào câu sáo rỗng kiểu văn máy.
- Chỉ viết lại đúng những đoạn được chỉ định bằng số thứ tự; các đoạn khác giữ nguyên.

Khi MỞ RỘNG: triển khai nội tâm nhân vật, làm giàu chi tiết cảm giác của bối cảnh, đào sâu ẩn ý trong lời thoại, thêm câu chuyển cảnh, kéo dài khoảnh khắc ra quyết định.
Khi NÉN: gộp các miêu tả trùng chức năng, cắt bổ ngữ thừa (bỏ tính từ, không bỏ thông tin), rút gọn đoạn chuyển tiếp.

Trả về JSON: "rewrites" là danh sách {"index": số thứ tự đoạn, "text": đoạn đã viết lại}. Chỉ viết tiếng Việt."""


def _paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


async def normalize_length(
    gateway: AuthoringTextGateway,
    *,
    scope: StoryScope,
    selection: StoryModelSelection,
    step_id: str,
    context_digest: str,
    decoding: StoryDecoding,
    text: str,
    window: SceneLengthWindow,
    max_output_tokens: int = 4096,
    system_prompt: str = LENGTH_SYSTEM,
) -> RepairOutcome:
    """Rewrite the longest (or shortest) paragraphs toward the nearest edge of the window, each to a stated
    syllable count in proportion to its length; ``system_prompt`` as in :func:`span_repair`."""
    original = count_syllables(text)
    if window.minimum <= original <= window.maximum:
        return RepairOutcome(text, True, "already inside the window")
    paragraphs = _paragraphs(text)
    sizes = [count_syllables(p) for p in paragraphs]
    expand = original < window.minimum
    if expand:
        goal = min(window.maximum, round(window.minimum * 1.1))
    else:
        goal = max(window.minimum, round(window.maximum * 0.95), math.ceil(original * COMPRESSION_FLOOR))
    order = sorted(range(len(paragraphs)), key=lambda i: sizes[i], reverse=not expand)
    targets = sorted(order[:MAX_LENGTH_REWRITES])
    selected = sum(sizes[i] for i in targets) or 1
    wanted = {i: max(1, round(sizes[i] + (goal - original) * sizes[i] / selected)) for i in targets}
    plan = "\n".join(f"- đoạn [{i}]: hiện {sizes[i]} âm tiết → viết lại khoảng {wanted[i]} âm tiết" for i in targets)
    numbered = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(paragraphs))
    prompt = (
        f"Văn bản hiện có {original} âm tiết; cần khoảng {goal} âm tiết (khoảng cho phép {window.minimum}–"
        f"{window.maximum}). Hãy {'MỞ RỘNG' if expand else 'NÉN'} đúng các đoạn sau, mỗi đoạn tới số âm tiết ghi "
        f"kèm:\n{plan}\n\n{numbered}"
    )
    output = await gateway.generate(
        scope=scope,
        request=StoryStepRequest(
            step_id=step_id,
            kind=StoryStepKind.REPAIR,
            context_digest=context_digest,
            selection=selection,
            system_prompt=system_prompt,
            prompt=prompt,
            output_mode=OutputMode.STRUCTURED,
            response_model=LengthResponse,
            decoding=decoding,
            max_output_tokens=max_output_tokens,
        ),
    )
    rewrites = {r.index: r.text.strip() for r in LengthResponse.model_validate_json(output.text).rewrites}
    allowed = {i: t for i, t in rewrites.items() if i in targets and t}
    if not allowed:
        return RepairOutcome(text, False, "no rewrite of a selected paragraph")
    result = "\n\n".join(allowed.get(i, p) for i, p in enumerate(paragraphs))
    length = count_syllables(result)
    if expand and (length <= original or length > window.hard_maximum):
        return RepairOutcome(text, False, f"expansion produced {length} syllables", len(allowed))
    if not expand and (length >= original or length < max(window.minimum, original * COMPRESSION_FLOOR)):
        return RepairOutcome(text, False, f"compression produced {length} syllables", len(allowed))
    return RepairOutcome(result, True, f"{original} -> {length} syllables", len(allowed))
