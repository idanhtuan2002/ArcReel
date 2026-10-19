"""Quote-verified L2 audits, the L3 critic, the blind pairwise judge and deterministic anti-AI checks."""

from __future__ import annotations

import json
from typing import Literal

import httpx

from lib.text_backends.ollama import OllamaChatClient
from server.story_authoring.audits import (
    AuditDimension,
    AuditIssue,
    CriticReport,
    anti_ai_findings,
    audit_chapter,
    critic_manuscript,
    pairwise_judge,
    unfaithful_blurbs,
    verified_findings,
)
from server.story_authoring.checks import Severity
from server.story_authoring.contracts import StoryDecoding, StoryLimits, StoryModelSelection, StoryScope
from server.story_authoring.generation import AuthoringTextGateway
from server.story_authoring.prompts.schemas import ChapterPlan, OutlineChapter, PlannedScene, ShortOutline

MODEL = "ornith-32k:9b"
SCOPE = StoryScope(user_id="u", project_name="p", actor_id="u")
SELECTION = StoryModelSelection.create(
    provider_id="c", endpoint="ollama-chat", base_url="http://h:1", model_id=MODEL, has_credential=False
)
LIMITS = StoryLimits(input_tokens_max=10**6, output_tokens_max=10**6, wall_clock_max_seconds=10**5)
DECODING = StoryDecoding(temperature=0.2, seed=1)
DIGEST = "sha256:" + "0" * 64

SCENES = (
    ("scene_draft[1,1]", "Minh đẩy cánh cổng gỗ. Lan đứng bên giếng, tay cầm chiếc thùng."),
    ("scene_draft[1,2]", "Bữa cơm im lặng. Minh gọi Lan là chị, rồi lại gọi là em."),
)


class _Sink:
    async def reserve(self, **_):
        return "a"

    async def dispatched(self, _):
        return None

    async def completed(self, _, **__):
        return None

    async def failed(self, _, **__):
        return None

    async def unknown(self, _, **__):
        return None


def _gateway(payload: dict, *later: dict) -> tuple[AuthoringTextGateway, list[dict]]:
    """Answers each generation with the next payload; the last one repeats."""
    bodies: list[dict] = []
    answers = [payload, *later]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        counting = body["options"]["num_predict"] == 1
        answer = answers.pop(0) if not counting and len(answers) > 1 else answers[0]
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "message": {
                    "role": "assistant",
                    "content": "{" if counting else json.dumps(answer, ensure_ascii=False),
                },
                "done": True,
                "done_reason": "length" if counting else "stop",
                "prompt_eval_count": 700,
                "eval_count": 80,
            },
        )

    client = OllamaChatClient(base_url="http://h:1", transport=httpx.MockTransport(handler))
    return AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=_Sink()), bodies


def _issue(quote: str, severity: Literal["critical", "major", "minor"] = "major") -> AuditIssue:
    return AuditIssue(severity=severity, issue_type="xung_ho", description="d", quote=quote, suggested_fix="f")


def _plan() -> ChapterPlan:
    scene = PlannedScene(
        summary="s",
        location="l",
        pov="Minh",
        characters=["Minh"],
        beats=["a", "b"],
        emotional_turn="e",
        plot_function="p",
        dialogue_required=False,
    )
    return ChapterPlan(
        chapter_goal="Minh về nhà",
        reader_expectation="r",
        withheld_cards=["món nợ"],
        required_changes_by_end=["Minh tìm thấy cuốn sổ"],
        do_not=["kể lể"],
        scenes=[scene, scene, scene],
    )


def test_only_quoted_findings_survive_and_are_placed_in_their_scene():
    findings, discarded = verified_findings(
        [_issue("Minh gọi  Lan là chị"), _issue("một câu bịa ra"), _issue("Lan đứng bên giếng", "minor")],
        dimension=AuditDimension.CHARACTER,
        scenes=SCENES,
    )
    assert discarded == 1
    assert [(f.node_id, f.severity) for f in findings] == [
        ("scene_draft[1,2]", Severity.NARRATIVE_CRITICAL),
        ("scene_draft[1,1]", Severity.STYLISTIC),
    ]
    assert findings[0].code == "CHARACTER:xung_ho"


def test_severity_follows_the_dimension():
    quote = "Bữa cơm im lặng."
    memo, _ = verified_findings([_issue(quote, "critical")], dimension=AuditDimension.MEMO_COMPLIANCE, scenes=SCENES)
    anti, _ = verified_findings([_issue(quote, "critical")], dimension=AuditDimension.ANTI_AI, scenes=SCENES)
    assert memo[0].severity is Severity.HARD_STRUCTURAL
    assert anti[0].severity is Severity.STYLISTIC


async def test_a_chapter_audit_sends_one_dimension_with_the_memo_and_verifies_quotes():
    gateway, bodies = _gateway(
        {
            "issues": [
                {
                    "severity": "critical",
                    "issue_type": "xung_ho",
                    "description": "Minh gọi Lan hai cách",
                    "quote": "Minh gọi Lan là chị",
                    "suggested_fix": "giữ 'em'",
                },
                {
                    "severity": "major",
                    "issue_type": "bịa",
                    "description": "x",
                    "quote": "Không có câu này",
                    "suggested_fix": "y",
                },
            ]
        }
    )

    result = await audit_chapter(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="review-1",
        context_digest=DIGEST,
        decoding=DECODING,
        dimension=AuditDimension.CONTINUITY,
        chapter_number=1,
        scenes=SCENES,
        plan=_plan(),
        facts="- Lan: em gái Minh",
        previous_summary="",
    )

    assert (len(result.findings), result.discarded_unquoted) == (1, 1)
    assert result.findings[0].node_id == "scene_draft[1,2]"
    prompt = bodies[-1]["messages"][1]["content"]
    assert "TÍNH LIÊN TỤC" in prompt
    assert "Minh tìm thấy cuốn sổ" in prompt
    assert "- Lan: em gái Minh" in prompt
    assert bodies[-1]["messages"][0]["content"].startswith("Bạn là người thẩm định độc lập")


def _outline() -> ShortOutline:
    return ShortOutline(
        story_arc="a",
        opening="o",
        confrontation="c",
        resolution="r",
        chapters=[OutlineChapter(core_task=t, threads_advanced="x", turning_point="y") for t in "abc"],
        ending="e",
        final_image="f",
    )


async def _critic(payload: dict):
    gateway, _ = _gateway(payload)
    return await critic_manuscript(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="critic",
        context_digest=DIGEST,
        decoding=DECODING,
        scenes=SCENES,
        outline=_outline(),
    )


async def test_a_resolved_and_quoted_ending_passes_the_critic():
    result = await _critic({"ending_resolves_conflict": True, "ending_quote": "Bữa cơm im lặng.", "issues": []})
    assert (result.ending_resolves_conflict, result.ending_quote_verified, result.findings) == (True, True, ())


def test_the_critic_quotes_its_ending_evidence_before_its_verdict():
    assert list(CriticReport.model_json_schema()["properties"])[:2] == ["ending_quote", "ending_resolves_conflict"]


async def test_an_unresolved_or_unquoted_ending_is_hard_structural():
    unresolved = await _critic({"ending_resolves_conflict": False, "ending_quote": "Bữa cơm im lặng.", "issues": []})
    unquoted = await _critic(
        {"ending_resolves_conflict": True, "ending_quote": "Họ sống hạnh phúc mãi mãi.", "issues": []}
    )
    for result in (unresolved, unquoted):
        assert [f.code for f in result.findings] == ["NO_ENDING"]
        assert result.findings[0].severity is Severity.HARD_STRUCTURAL


async def _judge(reasons: list[dict], preferred: str = "A"):
    gateway, bodies = _gateway({"preferred": preferred, "reasons": reasons})
    result = await pairwise_judge(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="pair",
        context_digest=DIGEST,
        decoding=DECODING,
        text_a="Minh mở cửa. Gió thổi.",
        text_b="Lan nấu cơm. Trời mưa.",
        criteria="chất lượng văn",
    )
    return result, bodies


async def test_a_pairwise_judgment_needs_at_least_one_verified_reason():
    kept, bodies = await _judge(
        [{"side": "A", "reason": "sinh động", "quote": "Gió thổi."}, {"side": "B", "reason": "x", "quote": "Gió thổi."}]
    )
    dropped, _ = await _judge([{"side": "B", "reason": "bịa", "quote": "Không có."}])

    assert (kept.preferred, kept.verified_reasons, kept.discarded_reasons) == ("A", 1, 1)
    assert (dropped.preferred, dropped.verified_reasons) == (None, 0)
    assert "[A]\nMinh mở cửa. Gió thổi." in bodies[-1]["messages"][1]["content"]


def test_deterministic_anti_ai_checks():
    text = "\n\n".join(
        ["Dường như trời mưa, như thể ai khóc. " + "Một hai ba bốn năm sáu bảy." for _ in range(5)]
        + ["Không phải anh buồn mà là anh mệt. Không phải chị giận mà là chị sợ."]
    )
    codes = {f.code for f in anti_ai_findings(text, node_id="s")}
    assert {"STOCK_PHRASE", "NOT_BUT_PATTERN"} <= codes


def test_uniform_paragraphs_are_flagged_and_varied_ones_are_not():
    uniform = "\n\n".join(["một hai ba bốn năm sáu bảy tám"] * 6)
    varied = "\n\n".join(
        ["một hai", "một hai ba bốn năm sáu bảy tám chín mười", "một", "ba bốn năm sáu", "bảy", "tám chín"]
    )
    assert [f.code for f in anti_ai_findings(uniform, node_id="s")] == ["UNIFORM_PARAGRAPHS"]
    assert anti_ai_findings(varied, node_id="s") == ()


def test_a_looping_judgment_is_discarded():
    looping = "Lỗi thực sự là Minh đã đọc sâu hơn vào cuốn sổ của cha. " * 3
    findings, discarded = verified_findings(
        [
            AuditIssue(
                severity="critical", issue_type="x", description=looping, quote="Bữa cơm im lặng.", suggested_fix="f"
            )
        ],
        dimension=AuditDimension.MEMO_COMPLIANCE,
        scenes=SCENES,
    )
    assert (findings, discarded) == ((), 1)


async def test_a_blocking_claim_holds_only_when_the_second_reading_confirms_it_with_a_quote():
    from server.story_authoring.audits import confirm_finding, unconfirmed
    from server.story_authoring.checks import Finding

    claim = Finding("MEMO_COMPLIANCE:x", Severity.HARD_STRUCTURAL, "scene_draft[1,2]", "thiếu", "Bữa cơm im lặng.")
    outcomes = []
    for payload in (
        {"confirmed": True, "quote": "Bữa cơm im lặng."},
        {"confirmed": True, "quote": "Một câu không có."},
        {"confirmed": False, "quote": "Bữa cơm im lặng."},
    ):
        gateway, _ = _gateway(payload)
        outcomes.append(
            await confirm_finding(
                gateway,
                scope=SCOPE,
                selection=SELECTION,
                step_id="v",
                context_digest=DIGEST,
                decoding=DECODING,
                finding=claim,
                scenes=SCENES,
                plan=_plan(),
            )
        )
    assert outcomes == [True, False, False]
    assert unconfirmed(claim).severity is Severity.NARRATIVE_CRITICAL


async def test_a_blurb_claim_counts_only_when_copied_from_the_blurb_and_unsupported_by_the_manuscript():
    gateway, bodies = _gateway(
        {
            "unsupported": [
                {"blurb": 1, "claim": "nhà sắp bị phá dỡ", "reason": "truyện không nói vậy"},
                {"blurb": 2, "claim": "Minh về làng", "reason": "r"},
                {"blurb": 2, "claim": "cha bán đất", "reason": "không có trong bản 2"},
                {"blurb": 3, "claim": "x", "reason": "không có bản 3"},
            ]
        },
        {
            "checks": [
                {"claim": 1, "quote": "Căn nhà sắp bị phá dỡ.", "supported": True},
                {"claim": 2, "quote": "Minh về làng.", "supported": True},
            ]
        },
    )
    claims = await unfaithful_blurbs(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="blurbs",
        context_digest=DIGEST,
        decoding=DECODING,
        blurbs=["Căn nhà sắp bị phá dỡ.", "Minh về làng."],
        manuscript="Minh về làng.",
    )
    assert [(c.blurb, c.claim) for c in claims] == [(1, "nhà sắp bị phá dỡ")]
    review, support = (b["messages"][1]["content"] for b in bodies if b["options"]["num_predict"] != 1)
    assert "[Bản 2]\nMinh về làng." in review
    assert "1. nhà sắp bị phá dỡ\n2. Minh về làng" in support


async def test_blurbs_without_claims_need_no_second_reading():
    gateway, bodies = _gateway({"unsupported": []})
    claims = await unfaithful_blurbs(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="blurbs",
        context_digest=DIGEST,
        decoding=DECODING,
        blurbs=["Minh về làng.", "Một cuốn sổ."],
        manuscript="Minh về làng.",
    )
    assert claims == ()
    assert sum(b["options"]["num_predict"] != 1 for b in bodies) == 1
