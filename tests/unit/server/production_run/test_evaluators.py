from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from r2.contracts.automation import ModelRoute
from server.production_run.evaluators import (
    CONTEXT_TOKENS,
    FRAME_COUNT,
    PROBABILITIES,
    QUESTIONS,
    FinalEvidence,
    OllamaReviewer,
    cue_at,
    first_token_probability,
    frame_answer_findings,
    frame_times,
    illustration_findings,
    prompt_digest,
    review_method,
    upright_letter,
    yes_no,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

ROUTE = ModelRoute(
    role="reviewer_a",
    provider_id="custom-1",
    model_id="gemma3:4b",
    model_identity="ollama/gemma3:4b",
    config_digest="sha256:" + "1" * 64,
    local=True,
    paid=False,
    currency="USD",
    max_cost_per_call=None,
)
ANSWER = {
    "language": "vi",
    "scores": {"story": 4, "visual": 5, "audio": 4, "continuity": 4, "pacing": 4},
    "findings": [{"code": "soft_focus", "severity": "MINOR", "repair_stage": None, "detail": "cảnh 2 hơi mờ"}],
}


def _evidence(tmp_path: Path) -> FinalEvidence:
    final = tmp_path / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=576x1024:r=24:d=4", str(final)],
        check=True,
    )
    subtitles = tmp_path / "final.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:02,000\nXin chào\n", encoding="utf-8")
    return FinalEvidence(
        unit_key="episode:1",
        final_path=final,
        subtitle_path=subtitles,
        narration_text="Xin chào",
        subject_digest="sha256:" + "2" * 64,
    )


async def _base_url(_provider_id: str) -> str:
    return "http://reviewer.test:11434"


def _reviewer(
    answer: dict,
    *,
    broken: str = "no",
    flipped: str = "no",
    upright: str = "A",
    illustrates: str = "yes",
    sent: list[dict] | None = None,
):
    """A scripted Ollama: each one-picture question gets its scripted reply, the scoring request ``answer``."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if sent is not None:
            sent.append(body)
        if "format" in body:
            content = json.dumps(answer)
        elif "Which one is upright" in body["messages"][0]["content"]:
            content = upright
        elif "broken" in body["messages"][0]["content"]:
            content = broken
        elif "upside down" in body["messages"][0]["content"]:
            content = flipped
        else:
            content = illustrates
        return httpx.Response(200, json={"message": {"content": content}})

    return OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler))


async def test_review_request_refuses_silent_truncation_and_sends_every_frame(tmp_path: Path) -> None:
    sent: list[dict] = []

    review = await _reviewer(ANSWER, sent=sent).assess(route=ROUTE, evidence=_evidence(tmp_path))

    assert review.outcome == "COMPLETED"
    assert review.language == "vi"
    assert [f.code for f in review.findings] == ["SOFT_FOCUS"]
    assert len(sent) == 4 * FRAME_COUNT + 1
    assert all(len(b["messages"][0]["images"]) == 1 and b["truncate"] is False for b in sent[:-1])
    assert sum("«Xin chào»" in b["messages"][0]["content"] for b in sent[:-1]) == FRAME_COUNT
    body = sent[-1]
    assert f"{FRAME_COUNT} khung hình" in body["messages"][0]["content"]
    assert "Khung 1 (0.2s): «Xin chào»" in body["messages"][0]["content"]
    assert (body["truncate"], body["shift"], body["stream"]) == (False, False, False)
    assert body["options"]["num_ctx"] == CONTEXT_TOKENS
    assert body["model"] == "gemma3:4b"
    assert len(body["messages"][0]["images"]) == FRAME_COUNT


async def test_context_overflow_fails_the_review(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "input length exceeds context length"})

    review = await OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler)).assess(
        route=ROUTE, evidence=_evidence(tmp_path)
    )

    assert review.outcome == "FAILED"


def test_each_frame_is_paired_with_the_subtitle_shown_or_nearest_at_its_moment() -> None:
    srt = "1\n00:00:00,000 --> 00:00:02,000\nMở đầu\n\n2\n00:00:02,000 --> 00:00:04,500\nKết thúc\n"

    assert frame_times(8.0, 4) == [1.0, 3.0, 5.0, 7.0]
    assert [cue_at(srt, t) for t in (1.0, 3.0, 5.0)] == ["Mở đầu", "Kết thúc", "Kết thúc"]
    assert cue_at("", 1.0) == ""


@pytest.mark.parametrize(
    ("broken", "flipped", "upright", "illustrates", "codes"),
    [
        ("yes", "no", "A", "yes", ["FRAME_BROKEN"]),
        ("no", "yes", "A", "yes", ["FRAME_UPSIDE_DOWN"]),
        ("no", "no", "B", "yes", ["FRAME_UPSIDE_DOWN"]),
        ("no", "no", "A", "No.", ["FRAME_NOT_ILLUSTRATING_NARRATION"]),
        ("maybe", "maybe", "maybe", "unclear", []),
    ],
)
async def test_one_picture_answers_reject_broken_upside_down_or_non_illustrating_films(
    tmp_path: Path, broken: str, flipped: str, upright: str, illustrates: str, codes: list[str]
) -> None:
    review = await _reviewer(ANSWER, broken=broken, flipped=flipped, upright=upright, illustrates=illustrates).assess(
        route=ROUTE, evidence=_evidence(tmp_path)
    )

    assert [f.code for f in review.findings if f.severity == "CRITICAL"] == codes


def test_frame_answer_thresholds() -> None:
    assert frame_answer_findings([True, None, False], [False, True, True], [True], unit_key="e") == []
    found = frame_answer_findings([True, True], [False, False, False], [True, True], unit_key="e")
    assert [(f.code, f.severity) for f in found] == [
        ("FRAME_BROKEN", "CRITICAL"),
        ("FRAME_UPSIDE_DOWN", "CRITICAL"),
        ("FRAME_NOT_ILLUSTRATING_NARRATION", "CRITICAL"),
    ]
    assert [yes_no(t) for t in ("Yes.", " no", "**No**", "vâng")] == [True, False, False, None]
    assert [upright_letter(t) for t in ("A", " B.", "**b**", "C")] == [False, True, True, None]


PROBABLE = ROUTE.model_copy(update={"model_id": "qwen2.5vl:7b", "model_identity": "ollama/qwen2.5vl:7b"})


def _probable(*, b: float = 0.05, broken: float = 0.01, illustrates: float = 0.8, sent: list[dict] | None = None):
    """A scripted Ollama returning first-token log-probabilities for each one-picture question."""

    def tops(first: str, p_first: float, second: str) -> dict:
        return {
            "message": {"content": first},
            "logprobs": [
                {
                    "token": first,
                    "logprob": math.log(p_first),
                    "top_logprobs": [
                        {"token": first, "logprob": math.log(p_first)},
                        {"token": second, "logprob": math.log(1 - p_first)},
                    ],
                }
            ],
        }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if sent is not None:
            sent.append(body)
        text = body["messages"][0]["content"]
        if "format" in body:
            return httpx.Response(200, json={"message": {"content": json.dumps(ANSWER)}})
        if "Which one is upright" in text:
            return httpx.Response(200, json=tops("B", b, "A"))
        if "broken" in text:
            return httpx.Response(200, json=tops("yes", broken, "no"))
        return httpx.Response(200, json=tops("yes", illustrates, "no"))

    return OllamaReviewer(base_url_for=_base_url, transport=httpx.MockTransport(handler))


async def test_a_probability_reviewer_reads_first_token_logprobs_per_frame(tmp_path: Path) -> None:
    sent: list[dict] = []

    review = await _probable(sent=sent).assess(route=PROBABLE, evidence=_evidence(tmp_path))

    assert review_method(PROBABLE) == PROBABILITIES
    assert review.prompt_digest == prompt_digest(PROBABILITIES) != prompt_digest(QUESTIONS)
    assert review.accepts()
    assert len(sent) == 3 * FRAME_COUNT + 1
    assert all(b["logprobs"] is True and b["options"]["num_predict"] == 1 for b in sent[:-1])


@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ({"b": 0.9}, "FRAME_UPSIDE_DOWN"),
        ({"broken": 0.9}, "FRAME_BROKEN"),
        ({"illustrates": 0.05}, "FRAMES_NOT_ILLUSTRATING_NARRATION"),
    ],
)
async def test_a_probability_reviewer_rejects_by_calibrated_thresholds(
    tmp_path: Path, answers: dict, code: str
) -> None:
    review = await _probable(**answers).assess(route=PROBABLE, evidence=_evidence(tmp_path))

    assert [f.code for f in review.findings if f.severity == "CRITICAL"] == [code]


def test_first_token_probability_normalises_between_the_two_answers() -> None:
    tops = [{"top_logprobs": [{"token": " Yes", "logprob": math.log(0.6)}, {"token": "no", "logprob": math.log(0.2)}]}]

    assert first_token_probability(tops, yes="yes", no="no") == pytest.approx(0.75)
    assert first_token_probability([{"top_logprobs": [{"token": "maybe", "logprob": 0.0}]}], yes="yes", no="no") is None
    assert first_token_probability(None, yes="yes", no="no") is None
    assert illustration_findings([0.1, 0.1, None], unit_key="e")[0].code == "FRAMES_NOT_ILLUSTRATING_NARRATION"
    assert illustration_findings([0.2, 0.1], unit_key="e") == []


def test_the_questions_method_needs_most_frames_upside_down():
    from server.production_run.evaluators import (
        MIN_FLIPPED_FRAMES_QUESTIONS,
        PROBABILITIES,
        QUESTIONS,
        _min_flipped,
        frame_answer_findings,
    )

    reflections = [False, False, True, False, True, True, False, False]
    flipped_final = [False, True, True, True, True, True, True, True]
    illustrated = [True] * 8

    def codes(flipped: list[bool | None], method: str) -> list[str]:
        found = frame_answer_findings(flipped, illustrated, unit_key="episode:1", min_flipped=_min_flipped(method))
        return [f.code for f in found]

    assert MIN_FLIPPED_FRAMES_QUESTIONS == 5
    assert codes(reflections, QUESTIONS) == []
    assert codes(flipped_final, QUESTIONS) == ["FRAME_UPSIDE_DOWN"]
    assert codes(reflections, PROBABILITIES) == ["FRAME_UPSIDE_DOWN"]
