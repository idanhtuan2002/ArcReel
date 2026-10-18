"""L2 specialist audits of a chapter, the L3 manuscript critic and the blind pairwise judge.

Donor surfaces (``R2_STORY_DONOR_BASELINE.json``):

- S05 Novel Studio ``src/lib/ai/prompts.ts`` (sha256 ``e112fbc8…a2f4``) ``continuityPrompt``: issue fields
  severity / type / description / evidence / suggested fix, issue types (character who should be absent,
  location, knowledge leak, relationship, item ownership, timeline, outline deviation, style drift), block on
  high or critical. Its deterministic ``hardRules`` port (``r2/narrative_lifecycle/continuity_rules.py``) reads
  Novel Studio's own context-pack fields, which a story run does not carry; it is not applied here.
- S06 Shenbi review skills (hashes in the baseline): one dimension per call; an independent evaluator that
  sees only the text and what it is judged against; memo compliance (the task happens, required changes
  happen, withheld cards stay hidden, the do-not list is respected); character (out-of-character behaviour,
  voice, characters made foolish to serve the plot); motivation (every action has a reason the reader can
  derive); continuity (time only moves forward, places need transitions, causes precede effects); anti-AI
  (deterministic checks first, then judgment).

Every model finding must quote the audited text verbatim (after whitespace normalization); a finding whose
quote is absent is discarded and counted, never kept. Quotes also place each finding in its scene, so repair
targets the right node. Recorded deviations: Vietnamese prompts; grammar-constrained schemas; four L2
dimensions per chapter (continuity, memo compliance, character with motivation, anti-AI) to fit the call
budget; severity is mapped onto the amendment's five classes.
"""

from __future__ import annotations

import json
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from server.story_authoring.checks import Finding, Severity, count_syllables
from server.story_authoring.contracts import (
    OutputMode,
    StoryDecoding,
    StoryModelSelection,
    StoryScope,
    StoryStepKind,
    StoryStepRequest,
)
from server.story_authoring.generation import AuthoringTextGateway
from server.story_authoring.prompts.schemas import ChapterPlan, ShortOutline

AUDIT_SYSTEM = (
    "Bạn là người thẩm định độc lập cho truyện ngắn tiếng Việt. Bạn không viết lại truyện; bạn chỉ chỉ ra lỗi. "
    "Mỗi lỗi phải kèm một câu trích NGUYÊN VĂN từ văn bản được thẩm định. Không có lỗi thì trả danh sách rỗng."
)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuditIssue(_Out):
    severity: Literal["critical", "major", "minor"]
    issue_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    suggested_fix: str = Field(min_length=1)


class AuditReport(_Out):
    issues: list[AuditIssue] = Field(max_length=6)


class CriticReport(_Out):
    ending_resolves_conflict: bool
    ending_quote: str = Field(min_length=1)
    issues: list[AuditIssue] = Field(max_length=6)


class PairwiseReason(_Out):
    side: Literal["A", "B"]
    reason: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class PairwiseJudgment(_Out):
    preferred: Literal["A", "B", "tie"]
    reasons: list[PairwiseReason] = Field(min_length=1, max_length=4)


class AuditDimension(StrEnum):
    CONTINUITY = "CONTINUITY"
    MEMO_COMPLIANCE = "MEMO_COMPLIANCE"
    CHARACTER = "CHARACTER"
    ANTI_AI = "ANTI_AI"


CHAPTER_DIMENSIONS = tuple(AuditDimension)

_INSTRUCTIONS: dict[AuditDimension, str] = {
    AuditDimension.CONTINUITY: (
        "Thẩm định TÍNH LIÊN TỤC. Loại lỗi: nhân vật xuất hiện khi không thể có mặt, mâu thuẫn địa điểm, nhân vật biết "
        "điều chưa thể biết, mâu thuẫn quan hệ hoặc cách xưng hô, mâu thuẫn đồ vật thuộc về ai, thời gian chạy ngược "
        "hoặc nhảy vô lý, chuyển địa điểm không có chuyển cảnh, sự kiện thiếu nguyên nhân, lệch khỏi kế hoạch chương. "
        "So với [Sự thật đã khóa] và [Tóm tắt trước đó]."
    ),
    AuditDimension.MEMO_COMPLIANCE: (
        "Thẩm định việc THỰC HIỆN GHI CHÚ CHƯƠNG. Lỗi nghiêm trọng: nhiệm vụ của chương không xảy ra; một thay đổi bắt "
        "buộc cuối chương không xảy ra; một lá bài phải giữ kín lại bị hé lộ; một điều trong danh sách 'không làm' bị vi "
        "phạm. Với thay đổi bị thiếu, trích câu cuối của chương làm bằng chứng."
    ),
    AuditDimension.CHARACTER: (
        "Thẩm định NHÂN VẬT VÀ ĐỘNG CƠ. Lỗi: hành động hoặc lời nói trái tính cách đã xây dựng; giọng nói hoặc cách xưng "
        "hô đổi đột ngột; nhân vật phụ bị làm ngốc đi để đẩy cốt truyện; hành động không có lý do mà người đọc suy ra "
        "được từ mong muốn, nỗi sợ hay niềm tin của nhân vật; chuỗi hành động - hậu quả - phản ứng bị đứt."
    ),
    AuditDimension.ANTI_AI: (
        "Thẩm định GIỌNG VĂN MÁY. Lỗi: người kể kết luận thay người đọc; câu kiểu 'anh cảm thấy...' thay vì hành động; "
        "phản ứng tập thể chung chung kiểu 'tất cả đều sững sờ'; ngôn ngữ báo cáo hoặc lời bình về chính câu chuyện; "
        "cụm từ sáo lặp lại; câu đối lập 'không phải... mà là...' lặp lại."
    ),
}


def _normalize(text: str) -> str:
    return " ".join(text.split())


@dataclass(frozen=True)
class AuditResult:
    dimension: str
    findings: tuple[Finding, ...]
    discarded_unquoted: int


def _severity(dimension: AuditDimension | Literal["CRITIC"], level: str) -> Severity:
    if level == "minor" or dimension is AuditDimension.ANTI_AI:
        return Severity.STYLISTIC
    if dimension is AuditDimension.MEMO_COMPLIANCE and level == "critical":
        return Severity.HARD_STRUCTURAL
    return Severity.NARRATIVE_CRITICAL


def _place(quote: str, scenes: Sequence[tuple[str, str]]) -> str | None:
    target = _normalize(quote)
    for node_id, text in scenes:
        if target and target in _normalize(text):
            return node_id
    return None


def verified_findings(
    issues: Sequence[AuditIssue],
    *,
    dimension: AuditDimension | Literal["CRITIC"],
    scenes: Sequence[tuple[str, str]],
) -> tuple[tuple[Finding, ...], int]:
    """Findings whose quote occurs verbatim in a scene, placed in that scene; the count of discarded ones."""
    kept: list[Finding] = []
    discarded = 0
    name = dimension.value if isinstance(dimension, AuditDimension) else dimension
    for issue in issues:
        node = _place(issue.quote, scenes)
        if node is None:
            discarded += 1
            continue
        kept.append(
            Finding(
                code=f"{name}:{issue.issue_type}",
                severity=_severity(dimension, issue.severity),
                node_id=node,
                message=f"{issue.description} Gợi ý: {issue.suggested_fix}",
                quote=issue.quote,
            )
        )
    return tuple(kept), discarded


def _memo_block(plan: ChapterPlan) -> str:
    return json.dumps(
        {
            "chapter_goal": plan.chapter_goal,
            "withheld_cards": plan.withheld_cards,
            "required_changes_by_end": plan.required_changes_by_end,
            "do_not": plan.do_not,
            "scenes": [{"summary": s.summary, "beats": s.beats} for s in plan.scenes],
        },
        ensure_ascii=False,
        indent=2,
    )


def chapter_audit_prompt(
    dimension: AuditDimension,
    *,
    chapter_number: int,
    chapter_text: str,
    plan: ChapterPlan,
    facts: str,
    previous_summary: str,
) -> str:
    return f"""{_INSTRUCTIONS[dimension]}

Trả về "issues": mỗi lỗi có severity (critical/major/minor), issue_type (tên ngắn của loại lỗi), description,
quote (một câu chép nguyên văn từ chương), suggested_fix. Tối đa 6 lỗi, ưu tiên lỗi nặng.

[Sự thật đã khóa]
{facts}

[Tóm tắt trước đó]
{previous_summary or "(đây là chương đầu)"}

[Ghi chú chương {chapter_number}]
{_memo_block(plan)}

[Chương {chapter_number} cần thẩm định]
{chapter_text}"""


async def _structured[T: BaseModel](
    gateway: AuthoringTextGateway,
    *,
    scope: StoryScope,
    selection: StoryModelSelection,
    step_id: str,
    kind: StoryStepKind,
    context_digest: str,
    decoding: StoryDecoding,
    prompt: str,
    model: type[T],
    max_output_tokens: int,
) -> T:
    output = await gateway.generate(
        scope=scope,
        request=StoryStepRequest(
            step_id=step_id,
            kind=kind,
            context_digest=context_digest,
            selection=selection,
            system_prompt=AUDIT_SYSTEM,
            prompt=prompt,
            output_mode=OutputMode.STRUCTURED,
            response_model=model,
            decoding=decoding,
            max_output_tokens=max_output_tokens,
        ),
    )
    return model.model_validate_json(output.text)


async def audit_chapter(
    gateway: AuthoringTextGateway,
    *,
    scope: StoryScope,
    selection: StoryModelSelection,
    step_id: str,
    context_digest: str,
    decoding: StoryDecoding,
    dimension: AuditDimension,
    chapter_number: int,
    scenes: Sequence[tuple[str, str]],
    plan: ChapterPlan,
    facts: str,
    previous_summary: str,
    max_output_tokens: int = 2048,
) -> AuditResult:
    chapter_text = "\n\n".join(text for _, text in scenes)
    report = await _structured(
        gateway,
        scope=scope,
        selection=selection,
        step_id=step_id,
        kind=StoryStepKind.CHAPTER_REVIEW,
        context_digest=context_digest,
        decoding=decoding,
        prompt=chapter_audit_prompt(
            dimension,
            chapter_number=chapter_number,
            chapter_text=chapter_text,
            plan=plan,
            facts=facts,
            previous_summary=previous_summary,
        ),
        model=AuditReport,
        max_output_tokens=max_output_tokens,
    )
    findings, discarded = verified_findings(report.issues, dimension=dimension, scenes=scenes)
    return AuditResult(dimension.value, findings, discarded)


@dataclass(frozen=True)
class CriticResult:
    ending_resolves_conflict: bool
    ending_quote_verified: bool
    findings: tuple[Finding, ...]
    discarded_unquoted: int


async def critic_manuscript(
    gateway: AuthoringTextGateway,
    *,
    scope: StoryScope,
    selection: StoryModelSelection,
    step_id: str,
    context_digest: str,
    decoding: StoryDecoding,
    scenes: Sequence[tuple[str, str]],
    outline: ShortOutline,
    max_output_tokens: int = 2048,
) -> CriticResult:
    manuscript = "\n\n".join(text for _, text in scenes)
    prompt = f"""Thẩm định toàn bộ truyện ngắn như một biên tập viên xuất bản.

1. ending_resolves_conflict: chương cuối có giải quyết trọn vẹn xung đột trung tâm không; ending_quote: chép nguyên văn
   câu thể hiện rõ nhất kết thúc.
2. issues: tối đa 6 lỗi lớn nhất của cả truyện (mạch truyện đứt, nhân vật mâu thuẫn, kết thúc hụt, nhịp quá chậm/vội),
   mỗi lỗi kèm quote nguyên văn.

[Dàn ý đã duyệt]
{json.dumps(outline.model_dump(), ensure_ascii=False, indent=2)}

[Truyện]
{manuscript}"""
    report = await _structured(
        gateway,
        scope=scope,
        selection=selection,
        step_id=step_id,
        kind=StoryStepKind.MANUSCRIPT_REVIEW,
        context_digest=context_digest,
        decoding=decoding,
        prompt=prompt,
        model=CriticReport,
        max_output_tokens=max_output_tokens,
    )
    findings, discarded = verified_findings(report.issues, dimension="CRITIC", scenes=scenes)
    quote_ok = _place(report.ending_quote, scenes[-3:]) is not None
    if not (report.ending_resolves_conflict and quote_ok):
        findings = (
            *findings,
            Finding(
                "NO_ENDING",
                Severity.HARD_STRUCTURAL,
                scenes[-1][0],
                "the last chapter does not resolve the central conflict",
                report.ending_quote if quote_ok else "",
            ),
        )
    return CriticResult(report.ending_resolves_conflict, quote_ok, findings, discarded)


@dataclass(frozen=True)
class PairwiseResult:
    preferred: Literal["A", "B", "tie"] | None
    verified_reasons: int
    discarded_reasons: int


def pairwise_prompt(text_a: str, text_b: str, criteria: str) -> str:
    return f"""So sánh hai văn bản A và B theo tiêu chí: {criteria}
Chọn preferred (A, B hoặc tie) và nêu 1–4 lý do; mỗi lý do ghi side (A hoặc B) và quote chép NGUYÊN VĂN một câu từ
văn bản của side đó.

[A]
{text_a}

[B]
{text_b}"""


async def pairwise_judge(
    gateway: AuthoringTextGateway,
    *,
    scope: StoryScope,
    selection: StoryModelSelection,
    step_id: str,
    context_digest: str,
    decoding: StoryDecoding,
    text_a: str,
    text_b: str,
    criteria: str,
    max_output_tokens: int = 1024,
) -> PairwiseResult:
    """Blind A/B preference; a judgment with no verified reason is discarded (``preferred`` is None)."""
    judgment = await _structured(
        gateway,
        scope=scope,
        selection=selection,
        step_id=step_id,
        kind=StoryStepKind.MANUSCRIPT_REVIEW,
        context_digest=context_digest,
        decoding=decoding,
        prompt=pairwise_prompt(text_a, text_b, criteria),
        model=PairwiseJudgment,
        max_output_tokens=max_output_tokens,
    )
    sides = {"A": _normalize(text_a), "B": _normalize(text_b)}
    verified = sum(1 for r in judgment.reasons if _normalize(r.quote) and _normalize(r.quote) in sides[r.side])
    discarded = len(judgment.reasons) - verified
    return PairwiseResult(judgment.preferred if verified else None, verified, discarded)


# --- deterministic anti-AI checks (Shenbi anti-ai-reference, Vietnamese equivalents) ---------------

STOCK_PHRASES = ("dường như", "như thể", "bất giác", "khẽ mỉm cười", "ánh mắt thoáng", "không khỏi", "nhẹ nhàng")
_NOT_BUT = re.compile(r"không phải[^.!?…]{1,60}mà là", re.IGNORECASE)


def anti_ai_findings(text: str, *, node_id: str) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    lowered = text.lower()
    for phrase in STOCK_PHRASES:
        count = lowered.count(phrase)
        if count > 1:
            findings.append(
                Finding("STOCK_PHRASE", Severity.STYLISTIC, node_id, f"'{phrase}' used {count} times", phrase)
            )
    contrasts = _NOT_BUT.findall(text)
    if len(contrasts) > 1:
        findings.append(
            Finding(
                "NOT_BUT_PATTERN",
                Severity.STYLISTIC,
                node_id,
                f"'không phải... mà là' used {len(contrasts)} times",
                contrasts[0],
            )
        )
    lengths = [count_syllables(p) for p in text.split("\n\n") if p.strip()]
    if (
        len(lengths) >= 5
        and statistics.mean(lengths) > 0
        and statistics.pstdev(lengths) / statistics.mean(lengths) < 0.15
    ):
        findings.append(
            Finding("UNIFORM_PARAGRAPHS", Severity.STYLISTIC, node_id, "paragraph lengths are nearly equal")
        )
    return tuple(findings)
