"""The ranking judge keeps the first storyboard unless a later one scores strictly higher on its own."""

from __future__ import annotations

import io
import json

import httpx
import pytest
from PIL import Image

from r2.contracts.automation import ModelRoute
from server.production_run.image_judge import (
    RATING,
    YES_PROBABILITY,
    ImageJudge,
    choose,
    judge_method,
    judge_prompt_digest,
    judge_view,
    qualify_judge,
    rating,
)
from server.production_run.vision_chat import ModelAccess


def _scores(values: dict[bytes, float | None], *, broken: bool = False):
    async def score(line, picture):
        if broken:
            raise httpx.ConnectError("down")
        return values[picture]

    return score


async def test_a_strictly_higher_later_candidate_is_chosen():
    choice = await choose(_scores({b"a": 0.4, b"b": 0.9, b"c": 0.7}), "line", [b"a", b"b", b"c"])

    assert (choice.index, choice.scores) == (1, [0.4, 0.9, 0.7])


async def test_ties_missing_scores_or_errors_keep_the_first_candidate():
    assert (await choose(_scores({b"a": 0.6, b"b": 0.6}), "line", [b"a", b"b"])).index == 0
    assert (await choose(_scores({b"a": 0.1, b"b": None}), "line", [b"a", b"b"])).index == 0
    assert (await choose(_scores({}, broken=True), "line", [b"a", b"b"])).index == 0


def test_the_judge_sees_a_384_pixel_wide_jpeg():
    picture = io.BytesIO()
    Image.new("RGB", (576, 1024), (10, 120, 200)).save(picture, format="PNG")

    with Image.open(io.BytesIO(judge_view(picture.getvalue()))) as seen:
        assert (seen.format, seen.size) == ("JPEG", (384, 683))


def test_the_prompt_digest_is_stable():
    assert judge_prompt_digest() == judge_prompt_digest()
    assert judge_prompt_digest().startswith("sha256:")


def _pairs(count: int) -> list[dict]:
    return [
        {"pair_id": f"p{i}", "line": f"line {i}", "own": f"own{i}".encode(), "other": f"other{i}".encode()}
        for i in range(count)
    ]


def _judge(misses: int):
    async def score(line, picture):
        index = int(line.split()[1])
        own = picture.startswith(b"own")
        return (0.2 if own else 0.8) if index < misses else (0.8 if own else 0.2)

    return score


async def test_a_judge_scoring_each_segments_own_storyboard_higher_qualifies():
    report = await qualify_judge(_judge(0), _pairs(30))

    assert (report["pairs"], report["wrong"], report["qualified"]) == (30, 0, True)
    assert report["results"][0] == {"pair_id": "p0", "own": 0.8, "other": 0.2, "right": True}


async def test_three_wrong_pairs_in_thirty_qualify_but_four_or_too_few_pairs_do_not():
    assert (await qualify_judge(_judge(3), _pairs(30)))["qualified"] is True
    assert (await qualify_judge(_judge(4), _pairs(30)))["qualified"] is False
    assert (await qualify_judge(_judge(0), _pairs(29)))["qualified"] is False


async def test_an_unanswered_pair_counts_as_wrong():
    async def silent(line, picture):
        return None

    assert (await qualify_judge(silent, _pairs(30)))["wrong"] == 30


def _picture() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 112), (120, 80, 40)).save(out, format="PNG")
    return out.getvalue()


ROUTE = ModelRoute(
    role="reviewer_a",
    provider_id="custom-4",
    model_id="vision-without-logprobs",
    model_identity="cloud/vision-without-logprobs",
    config_digest="sha256:" + "5" * 64,
    local=False,
    paid=True,
    currency="USD",
    max_cost_per_call=3,
)


async def test_a_rating_judge_on_a_cloud_endpoint_ranks_by_its_number():
    asked: list[dict] = []
    answers = iter(["Score: 3", "8", "8/10"])

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": next(answers)}}]})

    async def access(_provider: str, _model: str) -> ModelAccess:
        return ModelAccess("openai", "https://judge.example.test/v1", "k")

    judge = ImageJudge(access_for=access, transport=httpx.MockTransport(handler))
    choice = await judge.choose(
        ROUTE, "Hai đứa trẻ thả diều", [_picture()] * 3, prompt_digest=judge_prompt_digest(RATING)
    )
    assert (choice.index, choice.scores) == (1, [0.3, 0.8, 0.8])
    assert all("0 (not at all) to 10" in body["messages"][0]["content"][0]["text"] for body in asked)
    assert all("logprobs" not in body for body in asked)


def test_each_method_has_its_own_digest_and_an_unknown_digest_is_refused():
    assert judge_method(None) == YES_PROBABILITY
    assert judge_method(judge_prompt_digest(RATING)) == RATING
    assert judge_prompt_digest(RATING) != judge_prompt_digest(YES_PROBABILITY)
    with pytest.raises(ValueError, match="UNKNOWN_JUDGE_PROMPT"):
        judge_method("sha256:" + "0" * 64)
    assert [rating(text) for text in ("7", "10/10", "eleven", "42")] == [0.7, 1.0, None, None]
