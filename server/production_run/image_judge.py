"""A ranking-only judge that picks which storyboard version best shows its narration line (ADR-0112).

The judge never accepts or rejects output. Each candidate is scored alone; one picture per question has no candidate
order to be biased by. A judge method is one of:

- ``yes-probability``: the probability that the judge answers "yes" to whether the picture shows its line (the first
  token's probability mass of "yes" against "no"); needs an endpoint that returns token log probabilities;
- ``rating``: the judge's own 0-10 rating of how well the picture shows its line, divided by 10; for models whose
  endpoint returns no log probabilities.

Each method has its own prompt digest; a qualification and a launch profile pin one digest, and the run uses the
method of the pinned digest. The judge reaches its model through the route's provider endpoint (Ollama,
OpenAI-compatible or Gemini). A later candidate replaces the first only with a strictly higher score; a missing
score or any error keeps the first, so a failing judge degrades to one storyboard per segment.
"""

from __future__ import annotations

import io
import re
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image

from r2.automation.identity import digest_value
from r2.contracts.automation import ModelRoute
from r2.contracts.common import ensure_json_value
from server.production_run.evaluators import first_token_probability
from server.production_run.vision_chat import AccessFor, ollama_access, vision_chat

JUDGE_QUESTION = (
    "Does this picture show what this narration line of a Vietnamese short video says — the right people, their "
    "action and the place?\n«{line}»\nAnswer yes or no."
)
RATING_QUESTION = (
    "How well does this picture show what this narration line of a Vietnamese short video says — the right people, "
    "their action and the place?\n«{line}»\nAnswer with one whole number from 0 (not at all) to 10 (exactly)."
)
YES_PROBABILITY = "yes-probability"
RATING = "rating"
JUDGE_METHODS = (YES_PROBABILITY, RATING)
JUDGE_CONTEXT_TOKENS = 8192
#: Room for a reasoning model to think before its number; the answer is the first whole number in the reply.
RATING_MAX_TOKENS = 512
JUDGE_IMAGE_WIDTH = 384

type Score = Callable[[str, bytes], Awaitable[float | None]]


def judge_prompt_digest(method: str = YES_PROBABILITY) -> str:
    """The digest of what the judge is asked and how its answers are combined."""
    question = {YES_PROBABILITY: JUDGE_QUESTION, RATING: RATING_QUESTION}[method]
    return digest_value(
        "r2.production-image-judge.v2",
        ensure_json_value({"question": question, "method": method, "tie": "keep-first", "width": JUDGE_IMAGE_WIDTH}),
    )


def judge_method(prompt_digest: str | None) -> str:
    """The method whose prompt digest is ``prompt_digest``; the original method when none was pinned."""
    if prompt_digest is None:
        return YES_PROBABILITY
    for method in JUDGE_METHODS:
        if judge_prompt_digest(method) == prompt_digest:
            return method
    raise ValueError("UNKNOWN_JUDGE_PROMPT")


def rating(text: str) -> float | None:
    """The first whole number 0-10 of a rating answer, as a score in 0..1."""
    match = re.search(r"\d+", text)
    if match is None or int(match.group()) > 10:
        return None
    return int(match.group()) / 10


def judge_view(picture: bytes) -> bytes:
    """The candidate as the judge sees it: a JPEG ``JUDGE_IMAGE_WIDTH`` pixels wide."""
    with Image.open(io.BytesIO(picture)) as image:
        rgb = image.convert("RGB")
        height = max(1, round(rgb.height * JUDGE_IMAGE_WIDTH / rgb.width))
        out = io.BytesIO()
        rgb.resize((JUDGE_IMAGE_WIDTH, height)).save(out, format="JPEG", quality=90)
    return out.getvalue()


@dataclass
class Choice:
    """The chosen candidate's index and every candidate's score, for the selection evidence."""

    index: int
    scores: list[float | None] = field(default_factory=list)


async def _safe(score: Score, line: str, picture: bytes) -> float | None:
    try:
        return await score(line, picture)
    except (httpx.HTTPError, KeyError, ValueError):
        return None


async def choose(score: Score, line: str, candidates: list[bytes]) -> Choice:
    """The candidate with the strictly highest score; the first one when any score is missing or none is higher."""
    scores = [await _safe(score, line, candidate) for candidate in candidates]
    choice = Choice(index=0, scores=scores)
    known = [value for value in scores if value is not None]
    if len(known) != len(scores) or not known:
        return choice
    best = max(range(len(known)), key=lambda index: (known[index], -index))
    if known[best] > known[0]:
        choice.index = best
    return choice


class ImageJudge:
    """The ranking judge, served by the route's provider endpoint."""

    def __init__(
        self,
        *,
        access_for: AccessFor,
        timeout_seconds: float = 300,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_seconds: float = 10,
    ) -> None:
        self._access_for, self._timeout, self._transport = access_for, timeout_seconds, transport
        self._backoff = backoff_seconds

    async def choose(
        self, route: ModelRoute, line: str, candidates: list[bytes], *, prompt_digest: str | None = None
    ) -> Choice:
        async with self.scorer(route, method=judge_method(prompt_digest)) as score:
            return await choose(score, line, [judge_view(candidate) for candidate in candidates])

    @asynccontextmanager
    async def scorer(self, route: ModelRoute, *, method: str = YES_PROBABILITY) -> AsyncGenerator[Score]:
        """One conversation (a device job for a local model) in which ``score(line, view)`` asks about one view."""
        access = await self._access_for(route.provider_id, route.model_id)
        async with vision_chat(
            access,
            route.model_id,
            timeout_seconds=self._timeout,
            transport=self._transport,
            backoff_seconds=self._backoff,
        ) as chat:

            async def score(text: str, picture: bytes) -> float | None:
                if method == RATING:
                    reply = await chat.ask(
                        RATING_QUESTION.format(line=text[:1500]),
                        [picture],
                        max_tokens=RATING_MAX_TOKENS,
                        context_tokens=JUDGE_CONTEXT_TOKENS,
                    )
                    return rating(reply.text)
                reply = await chat.ask(
                    JUDGE_QUESTION.format(line=text[:1500]),
                    [picture],
                    max_tokens=1,
                    top_logprobs=10,
                    context_tokens=JUDGE_CONTEXT_TOKENS,
                )
                return first_token_probability(reply.logprobs, yes="yes", no="no")

            yield score


class OllamaImageJudge(ImageJudge):
    """A judge whose every route is served by the Ollama at its provider's base URL."""

    def __init__(
        self,
        *,
        base_url_for: Callable[[str], Awaitable[str]],
        timeout_seconds: float = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(access_for=ollama_access(base_url_for), timeout_seconds=timeout_seconds, transport=transport)


MIN_QUALIFICATION_PAIRS = 30
MAX_WRONG_RATE = 0.10


async def qualify_judge(score: Score, pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Score the judge on pairs of a segment's own storyboard against another segment's.

    Each pair is ``{"pair_id", "line", "own": bytes, "other": bytes}`` (judge views). A pair is right only when the
    own storyboard scores strictly higher; a missing score or an error is wrong. The judge qualifies with at least
    ``MIN_QUALIFICATION_PAIRS`` pairs and at most ``MAX_WRONG_RATE`` of them wrong."""
    results = []
    for pair in pairs:
        own = await _safe(score, pair["line"], pair["own"])
        other = await _safe(score, pair["line"], pair["other"])
        right = own is not None and other is not None and own > other
        results.append({"pair_id": pair["pair_id"], "own": own, "other": other, "right": right})
    total = len(results)
    wrong = sum(1 for result in results if not result["right"])
    qualified = total >= MIN_QUALIFICATION_PAIRS and wrong <= MAX_WRONG_RATE * total
    return {
        "pairs": total,
        "wrong": wrong,
        "max_wrong_rate": MAX_WRONG_RATE,
        "qualified": qualified,
        "results": results,
    }


__all__ = [
    "JUDGE_METHODS",
    "RATING",
    "YES_PROBABILITY",
    "Choice",
    "ImageJudge",
    "OllamaImageJudge",
    "choose",
    "judge_method",
    "judge_prompt_digest",
    "judge_view",
    "qualify_judge",
    "rating",
]
