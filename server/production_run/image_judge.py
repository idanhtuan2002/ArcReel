"""A ranking-only judge that picks which storyboard version best shows its narration line (ADR-0112).

The judge never accepts or rejects output. Each candidate is scored alone, as the probability that the judge answers
"yes" to whether the picture shows its line (the first token's probability mass of "yes" against "no"); one picture
per question has no candidate order to be biased by. A later candidate replaces the first only with a strictly
higher score; a missing score or any error keeps the first, so a failing judge degrades to one storyboard per segment.
"""

from __future__ import annotations

import base64
import io
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image

from lib.generation_resources import device_job, local_job
from lib.text_backends.ollama import normalize_ollama_base_url
from r2.automation.identity import digest_value
from r2.contracts.automation import ModelRoute
from r2.contracts.common import ensure_json_value
from server.production_run.evaluators import first_token_probability

JUDGE_QUESTION = (
    "Does this picture show what this narration line of a Vietnamese short video says — the right people, their "
    "action and the place?\n«{line}»\nAnswer yes or no."
)
JUDGE_CONTEXT_TOKENS = 8192
JUDGE_IMAGE_WIDTH = 384

type Score = Callable[[str, bytes], Awaitable[float | None]]


def judge_prompt_digest() -> str:
    """The digest of what the judge is asked and how its answers are combined."""
    return digest_value(
        "r2.production-image-judge.v2",
        ensure_json_value(
            {"question": JUDGE_QUESTION, "method": "yes-probability", "tie": "keep-first", "width": JUDGE_IMAGE_WIDTH}
        ),
    )


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


class OllamaImageJudge:
    """The ranking judge served by an Ollama chat endpoint that returns token log probabilities."""

    def __init__(
        self,
        *,
        base_url_for: Callable[[str], Awaitable[str]],
        timeout_seconds: float = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url_for, self._timeout, self._transport = base_url_for, timeout_seconds, transport

    async def choose(self, route: ModelRoute, line: str, candidates: list[bytes]) -> Choice:
        async with self.scorer(route) as score:
            return await choose(score, line, [judge_view(candidate) for candidate in candidates])

    @asynccontextmanager
    async def scorer(self, route: ModelRoute) -> AsyncGenerator[Score]:
        """One admitted device job in which ``score(line, view)`` asks the judge about one judge view."""
        url = normalize_ollama_base_url(await self._base_url_for(route.provider_id))
        async with (
            device_job(local_job(url, route.model_id)),
            httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client,
        ):

            async def score(text: str, picture: bytes) -> float | None:
                reply = await client.post(
                    url + "/api/chat",
                    json={
                        "model": route.model_id,
                        "stream": False,
                        "think": False,
                        "truncate": False,
                        "logprobs": True,
                        "top_logprobs": 10,
                        "messages": [
                            {
                                "role": "user",
                                "content": JUDGE_QUESTION.format(line=text[:1500]),
                                "images": [base64.b64encode(picture).decode()],
                            }
                        ],
                        "options": {"temperature": 0, "num_predict": 1, "num_ctx": JUDGE_CONTEXT_TOKENS},
                    },
                )
                reply.raise_for_status()
                return first_token_probability(reply.json().get("logprobs"), yes="yes", no="no")

            yield score


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


__all__ = ["Choice", "OllamaImageJudge", "choose", "judge_prompt_digest", "judge_view", "qualify_judge"]
