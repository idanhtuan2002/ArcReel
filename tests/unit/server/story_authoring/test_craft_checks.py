"""Cross-chapter checks in code (ADR-0117): repetition, monotonous openings, a continuation's voice drift."""

from __future__ import annotations

from server.story_authoring.audits import AuditDimension, AuditIssue, verified_findings
from server.story_authoring.checks import Severity
from server.story_authoring.craft_checks import drift_findings, long_span_findings, opening_findings


def _chapter(*paragraphs: str) -> str:
    return "\n\n".join(paragraphs)


def test_a_chapter_that_reuses_earlier_phrases_is_recorded_with_a_verbatim_sentence():
    first = _chapter("Minh đẩy cánh cổng gỗ cũ kỹ ra và bước vào sân. Lan đứng chờ dưới giàn mướp khô.")
    second = _chapter("Minh đẩy cánh cổng gỗ cũ kỹ ra và bước vào sân lần nữa. Trời đã tối.")
    fresh = _chapter("Con đò rời bến lúc trời còn mờ sương. Ông lái đò im lặng chèo.")

    findings = long_span_findings([("c1", first), ("c2", second), ("c3", fresh)])

    assert [(f.code, f.node_id, f.severity) for f in findings] == [("LONG_SPAN_REPETITION", "c2", Severity.STYLISTIC)]
    assert findings[0].quote in second


def test_three_chapters_opening_alike_and_paragraphs_starting_alike_are_recorded():
    same = _chapter("Minh nhìn ra sông. Gió lạnh.", "Lan nấu cơm.", "Trời mưa.")
    other = _chapter("Đêm xuống rất nhanh. Không ai nói gì.", "Lan nấu cơm.", "Trời mưa.")
    alike = _chapter(*(f"Minh làm việc thứ {i}. Rồi nghỉ." for i in range(6)))

    chapters = [("c1", same), ("c2", same), ("c3", same), ("c4", other), ("c5", alike)]
    codes = sorted((f.code, f.node_id) for f in opening_findings(chapters))

    assert codes == [("MONOTONOUS_CHAPTER_OPENINGS", "c3"), ("MONOTONOUS_PARAGRAPH_OPENINGS", "c5")]


def test_a_continuation_whose_sentences_or_dialogue_change_sharply_is_recorded():
    reference = _chapter(
        *(f"Ông lái đò chèo chậm qua khúc sông rộng lần thứ {i} trong buổi sớm mờ sương." for i in range(6))
    )
    short = _chapter(*(f"“Đi.” “Ừ.” “Nhanh lên {i}.”" for i in range(6)))

    codes = [f.code for f in drift_findings(reference, short, node="c1")]

    assert codes
    assert set(codes) == {"VOICE_DRIFT"}
    assert drift_findings(reference, reference, node="c1") == ()


def test_a_critical_safety_finding_is_a_hard_integrity_defect_and_minor_craft_is_stylistic():
    scene = [("s1", "Minh kể lại cách làm thuốc nổ từng bước.")]
    issue = {
        "issue_type": "weapon",
        "description": "hướng dẫn chế tạo",
        "suggested_fix": "bỏ",
        "quote": "Minh kể lại cách làm thuốc nổ từng bước.",
    }
    safety, _ = verified_findings(
        [AuditIssue(severity="critical", **issue)], dimension=AuditDimension.SAFETY, scenes=scene
    )
    craft, _ = verified_findings([AuditIssue(severity="minor", **issue)], dimension=AuditDimension.CRAFT, scenes=scene)

    assert safety[0].severity is Severity.HARD_INTEGRITY
    assert craft[0].severity is Severity.STYLISTIC
