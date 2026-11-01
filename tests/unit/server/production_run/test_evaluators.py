from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from r2.contracts.automation import ModelRoute
from server.production_run.evaluators import (
    CONTEXT_TOKENS,
    FRAME_COUNT,
    OBSERVATIONS,
    QUESTIONS,
    FinalEvidence,
    OllamaReviewer,
    cue_at,
    frame_answer_findings,
    frame_times,
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


OBSERVING = ROUTE.model_copy(update={"model_id": "qwen2.5vl:7b", "model_identity": "ollama/qwen2.5vl:7b"})


def _observed(*, defect: str = "NONE", matches: bool = True, upside_down: bool = False) -> dict:
    frame = {"content": "cảnh", "matches_narration": matches, "upside_down": upside_down, "defect": defect}
    return {**ANSWER, "frames": [frame] * FRAME_COUNT}


async def test_an_observing_reviewer_asks_orientation_per_frame_then_observes_while_scoring(tmp_path: Path) -> None:
    sent: list[dict] = []

    review = await _reviewer(_observed(), sent=sent).assess(route=OBSERVING, evidence=_evidence(tmp_path))

    assert review_method(OBSERVING) == OBSERVATIONS
    assert review.prompt_digest == prompt_digest(OBSERVATIONS) != prompt_digest(QUESTIONS)
    assert review.accepts()
    assert len(sent) == FRAME_COUNT + 1
    assert "frames" in sent[-1]["format"]["required"]


@pytest.mark.parametrize(
    ("answer", "upright", "code"),
    [
        (_observed(defect="NOISE"), "A", "OBSERVED_BROKEN_FRAMES"),
        (_observed(upside_down=True), "A", "OBSERVED_UPSIDE_DOWN"),
        (_observed(matches=False), "A", "OBSERVED_UNRELATED_FRAMES"),
        (_observed(), "B", "FRAME_UPSIDE_DOWN"),
    ],
)
async def test_an_observing_reviewer_rejects_what_it_observed(
    tmp_path: Path, answer: dict, upright: str, code: str
) -> None:
    review = await _reviewer(answer, upright=upright).assess(route=OBSERVING, evidence=_evidence(tmp_path))

    assert [f.code for f in review.findings if f.severity == "CRITICAL"] == [code]
