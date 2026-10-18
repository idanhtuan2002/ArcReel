"""Scene repair: deterministic fixes, span patches with length guard, targeted length normalizing."""

from __future__ import annotations

import json

import httpx

from lib.text_backends.ollama import OllamaChatClient
from server.story_authoring.checks import Finding, SceneLengthWindow, Severity, count_syllables
from server.story_authoring.contracts import StoryDecoding, StoryLimits, StoryModelSelection, StoryScope
from server.story_authoring.generation import AuthoringTextGateway
from server.story_authoring.repair import (
    PatchResponse,
    build_conflict_excerpt_block,
    deterministic_fixes,
    normalize_length,
    span_repair,
)

MODEL = "ornith-32k:9b"
SCOPE = StoryScope(user_id="u", project_name="p", actor_id="u")
SELECTION = StoryModelSelection.create(
    provider_id="c", endpoint="ollama-chat", base_url="http://h:1", model_id=MODEL, has_credential=False
)
LIMITS = StoryLimits(input_tokens_max=10**6, output_tokens_max=10**6, wall_clock_max_seconds=10**5)
DECODING = StoryDecoding(temperature=0.3, seed=1)

TEXT = (
    "Trời vừa hửng sáng thì Minh đẩy cánh cổng, bản lề kêu lên một tiếng dài.\n\n"
    "Lan ngẩng lên từ bên giếng, chiếc thùng gỗ trong tay khẽ chao, nước đổ xuống phiến đá xanh.\n\n"
    "“Anh về rồi.” Cô nói, giọng rất khẽ."
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


def _gateway(content: str) -> tuple[AuthoringTextGateway, list[dict]]:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        reply = "{" if body["options"]["num_predict"] == 1 else content
        reason = "length" if body["options"]["num_predict"] == 1 else "stop"
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "message": {"role": "assistant", "content": reply},
                "done": True,
                "done_reason": reason,
                "prompt_eval_count": 500,
                "eval_count": 50,
            },
        )

    client = OllamaChatClient(base_url="http://h:1", transport=httpx.MockTransport(handler))
    return AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=_Sink()), bodies


FINDING = Finding("CONTINUITY", Severity.NARRATIVE_CRITICAL, "s", "Lan không cầm thùng gỗ", "chiếc thùng gỗ trong tay")


async def _repair(response: dict) -> tuple[object, list[dict]]:
    gateway, bodies = _gateway(json.dumps(response, ensure_ascii=False))
    outcome = await span_repair(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="repair-1",
        context_digest="sha256:" + "0" * 64,
        decoding=DECODING,
        text=TEXT,
        findings=[FINDING],
        context_block="Lan đang phơi áo.",
        attempt_history=["lần 1: sửa sai chỗ"],
    )
    return outcome, bodies


async def test_a_located_patch_changes_only_its_span():
    outcome, bodies = await _repair(
        {"patches": [{"before": "chiếc thùng gỗ trong tay khẽ chao", "after": "tấm áo trong tay khẽ bay"}], "notes": ""}
    )

    assert outcome.accepted
    assert outcome.text == TEXT.replace("chiếc thùng gỗ trong tay khẽ chao", "tấm áo trong tay khẽ bay")
    prompt = bodies[-1]["messages"][1]["content"]
    assert "Lan đang phơi áo." in prompt
    assert "lần 1: sửa sai chỗ" in prompt
    assert prompt.rstrip().endswith(TEXT)
    assert bodies[-1]["format"]["properties"]["patches"]["maxItems"] == 6


async def test_an_unlocated_or_unmatched_patch_is_rejected():
    empty, _ = await _repair({"patches": [], "notes": "không định vị được"})
    unmatched, _ = await _repair(
        {"patches": [{"before": "câu không có thật trong văn bản", "after": "x"}], "notes": ""}
    )

    assert (empty.accepted, unmatched.accepted) == (False, False)
    assert empty.text == unmatched.text == TEXT
    assert unmatched.skipped == 1


async def test_a_patch_that_moves_the_length_too_far_is_rejected():
    outcome, _ = await _repair(
        {
            "patches": [{"before": "“Anh về rồi.” Cô nói, giọng rất khẽ.", "after": "Lan im lặng " * 30 + "."}],
            "notes": "",
        }
    )

    assert not outcome.accepted
    assert "length ratio" in outcome.reason
    assert outcome.text == TEXT


def test_the_patch_schema_forbids_extra_fields():
    assert PatchResponse.model_json_schema()["additionalProperties"] is False


def test_near_duplicates_are_fixed_without_a_model():
    sentences = [
        "Trời vừa hửng sáng thì Minh đẩy cánh cổng, bản lề kêu lên một tiếng dài và khàn.",
        "Anh đứng trên bậc thềm nhìn rất lâu, cây táo ngoài sân đã cao hơn trong trí nhớ.",
        "Mẹ nhóm lửa trong bếp, khói chậm rãi bốc lên qua khe mái ngói rồi tan vào sương.",
        "Lan ngẩng lên từ bên giếng, chiếc thùng gỗ trong tay khẽ chao, nước đổ xuống đá.",
    ]
    text = " ".join([*sentences, *sentences[1:3]])
    finding = Finding("NEAR_DUPLICATE", Severity.NARRATIVE_CRITICAL, "s", "a passage repeats")

    cleaned, notes = deterministic_fixes(text, [finding])

    assert cleaned == " ".join(sentences)
    assert notes
    assert deterministic_fixes(text, [FINDING]) == (text, ())


def test_vietnamese_quote_hints_pick_the_conflicting_paragraph_and_its_neighbours():
    excerpt = build_conflict_excerpt_block(TEXT, ["Mâu thuẫn: “chiếc thùng gỗ trong tay”"])
    assert excerpt == TEXT


def test_vietnamese_fallback_words_keep_diacritics():
    excerpt = build_conflict_excerpt_block("Câu một.\n\nCâu hai có giếng.\n\nCâu ba.\n\nCâu bốn.", ["bên giếng sai"])
    assert excerpt == "Câu một.\n\nCâu hai có giếng.\n\nCâu ba."


async def test_length_normalizing_rewrites_only_the_selected_paragraphs():
    paragraphs = ["Đoạn một ngắn.", "Đoạn hai dài hơn một chút nữa ở đây.", "Đoạn ba."]
    text = "\n\n".join(paragraphs)
    longer = "Đoạn ba được mở rộng với nội tâm của Minh và tiếng gió thổi qua mái ngói cũ."
    gateway, bodies = _gateway(
        json.dumps(
            {"rewrites": [{"index": 2, "text": longer}, {"index": 9, "text": "ngoài phạm vi"}]}, ensure_ascii=False
        )
    )

    outcome = await normalize_length(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="len-1",
        context_digest="sha256:" + "0" * 64,
        decoding=DECODING,
        text=text,
        window=SceneLengthWindow(minimum=40, maximum=60, hard_maximum=80),
    )

    assert outcome.accepted
    assert outcome.text == "\n\n".join([paragraphs[0], paragraphs[1], longer])
    assert count_syllables(outcome.text) > count_syllables(text)
    assert "MỞ RỘNG" in bodies[-1]["messages"][1]["content"]


async def test_length_normalizing_rejects_a_compression_below_the_floor():
    text = "\n\n".join(["Một hai ba bốn năm sáu bảy tám chín mười."] * 4)
    gateway, _ = _gateway(json.dumps({"rewrites": [{"index": 0, "text": "Một."}]}, ensure_ascii=False))

    outcome = await normalize_length(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="len-2",
        context_digest="sha256:" + "0" * 64,
        decoding=DECODING,
        text=text,
        window=SceneLengthWindow(minimum=20, maximum=30, hard_maximum=60),
    )

    assert not outcome.accepted
    assert outcome.text == text


async def test_a_scene_inside_the_window_is_left_alone_without_a_call():
    gateway, bodies = _gateway("{}")
    outcome = await normalize_length(
        gateway,
        scope=SCOPE,
        selection=SELECTION,
        step_id="len-3",
        context_digest="sha256:" + "0" * 64,
        decoding=DECODING,
        text=TEXT,
        window=SceneLengthWindow(minimum=1, maximum=500),
    )
    assert (outcome.accepted, outcome.text, bodies) == (True, TEXT, [])
