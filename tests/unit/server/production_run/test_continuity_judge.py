"""The continuity judge computes its verdict in code and never blocks on a failing model."""

from __future__ import annotations

import json

import httpx
import pytest

from r2.contracts.automation import ModelRoute
from scripts.r2.qualify_continuity_judge import derive_swaps
from server.production_run.continuity_judge import (
    ContinuityJudge,
    Shot,
    build_request,
    parse_verdict,
    prompt_digest,
    qualify_continuity,
)
from server.production_run.vision_chat import ModelAccess

ROUTE = ModelRoute(
    role="reviewer_a",
    provider_id="gemini-aistudio",
    model_id="vision-model",
    model_identity="cloud/vision-model",
    config_digest="sha256:" + "5" * 64,
    local=False,
    paid=True,
    currency="USD",
    max_cost_per_call=3,
)
SHOT = Shot(
    label="S3",
    description="Lan đưa chiếc hộp gỗ cho ông lão bên bờ sông.",
    characters=("Lan", "Ông lão"),
    location="bờ sông",
    framing="medium shot",
    references=(("character Lan", b"lan"), ("character Ông lão", b"old")),
    previous_description="Ông lão kéo lưới lên.",
    previous_frame=b"prev",
)


def _answer(score: float, issues: list[dict], fix: str = "Lan on the left of frame.") -> str:
    return json.dumps({"score": score, "issues": issues, "prompt_fix": fix})


@pytest.mark.parametrize(
    ("score", "issues", "status", "expected_score"),
    [
        (95, [], "aligned", 95),
        (82, [{"category": "lighting", "severity": "low", "message": "warmer"}], "watch", 82),
        (88, [{"category": "identity", "severity": "high", "message": "Lan has short hair"}], "drift", 69),
        (40, [{"category": "artifacts", "severity": "medium", "message": "extra finger"}], "drift", 40),
        (140, [], "aligned", 100),
    ],
)
def test_the_verdict_is_computed_from_score_and_severity(score, issues, status, expected_score) -> None:
    verdict = parse_verdict(_answer(score, issues))

    assert (verdict.status, verdict.score) == (status, expected_score)
    assert verdict.prompt_fix == ("" if status == "aligned" else "Lan on the left of frame.")


def test_unknown_categories_are_dropped_and_prose_around_the_json_is_ignored() -> None:
    answer = "Here: " + _answer(75, [{"category": "vibes", "severity": "high", "message": "x"}]) + " done"

    verdict = parse_verdict(answer)

    assert (verdict.status, verdict.issues) == ("watch", ())


@pytest.mark.parametrize("answer", ["no json", '{"issues": []}', '{"score": true, "issues": []}', "[1]"])
def test_an_unusable_answer_is_refused(answer: str) -> None:
    with pytest.raises(ValueError, match=r"JSON|score|object"):
        parse_verdict(answer)


def test_the_request_names_every_picture_in_order() -> None:
    text, pictures = build_request(SHOT, b"frame")

    assert pictures == [b"frame", b"lan", b"old", b"prev"]
    assert "Image 1: the frame to judge (shot S3)" in text
    assert "Image 4: the previous frame of the same scene" in text
    assert "Previous shot of the same scene: Ông lão kéo lưới lên." in text
    assert "In frame: Lan, Ông lão - location: bờ sông" in text


def test_a_first_shot_says_so() -> None:
    text, pictures = build_request(Shot(label="S1", description="Bờ sông lúc bình minh."), b"frame")

    assert pictures == [b"frame"]
    assert "This is the first shot of its scene." in text


async def test_a_cloud_judge_returns_a_verdict_and_a_failure_returns_none() -> None:
    bodies: list[dict] = []
    replies = iter(
        [
            httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": _answer(60, [], "Both hands empty.")}]}}]},
            ),
            httpx.Response(400, json={"error": "bad"}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return next(replies)

    async def access(_provider: str, _model: str) -> ModelAccess:
        return ModelAccess("gemini", "https://gemini.example.test", "k")

    judge = ContinuityJudge(access_for=access, transport=httpx.MockTransport(handler), backoff_seconds=0)

    verdict = await judge.judge(ROUTE, SHOT, b"frame")
    assert verdict is not None
    assert (verdict.status, verdict.prompt_fix) == ("drift", "Both hands empty.")
    assert bodies[0]["generationConfig"]["responseMimeType"] == "application/json"
    assert len(bodies[0]["contents"][0]["parts"]) == 5
    assert await judge.judge(ROUTE, SHOT, b"frame") is None


def test_the_prompt_digest_is_stable() -> None:
    assert prompt_digest() == prompt_digest()
    assert prompt_digest().startswith("sha256:")


def _verdicts(status: str, count: int):
    score = {"drift": 50, "ok": 95}[status]
    return [parse_verdict(_answer(score, [])) for _ in range(count)]


def test_a_judge_qualifies_only_above_every_bar() -> None:
    good = [("drift", v) for v in _verdicts("drift", 27)] + [("drift", v) for v in _verdicts("ok", 3)]
    good += [("ok", v) for v in _verdicts("ok", 28)] + [("ok", v) for v in _verdicts("drift", 2)]

    assert qualify_continuity(good)["qualified"] is True
    assert qualify_continuity(good[:-5])["qualified"] is False
    missed = [("drift", v) for v in _verdicts("drift", 20)] + [("drift", v) for v in _verdicts("ok", 10)]
    assert qualify_continuity(missed + good[30:])["drift_recall"] < 0.8
    assert qualify_continuity(missed + good[30:])["qualified"] is False
    silent = good[:-4] + [("ok", None)] * 4
    assert qualify_continuity(silent)["qualified"] is False


def test_swapped_identity_cases_are_derived_from_other_stories() -> None:
    cases = [
        {"case_id": "a1", "story": "a", "expected": "ok", "references": [{"label": "character Lan", "path": "a.png"}]},
        {"case_id": "b1", "story": "b", "expected": "ok", "references": [{"label": "character Tú", "path": "b.png"}]},
        {"case_id": "c1", "story": "c", "expected": "ok", "references": [{"label": "location sông", "path": "c.png"}]},
    ]

    derived = derive_swaps(cases)

    swaps = {case["case_id"]: case for case in derived if case["case_id"].endswith(":swap")}
    assert set(swaps) == {"a1:swap", "b1:swap"}
    assert swaps["a1:swap"]["references"] == [{"label": "character Lan", "path": "b.png"}]
    assert swaps["a1:swap"]["expected"] == "drift"
    assert cases[0]["references"] == [{"label": "character Lan", "path": "a.png"}]
