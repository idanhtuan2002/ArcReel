"""A ranking-only judge that picks which storyboard version best shows its narration line (ADR-0112).

The judge never accepts or rejects output: it compares two candidates, A and B, and is asked twice with the order
swapped to cancel position bias. Only an answer that names the same picture in both orders counts; anything else —
disagreement, an unreadable answer, an error — keeps the earlier candidate, so a failing judge degrades to one
storyboard per segment. Three candidates are compared as a short ladder: the winner of the first two meets the third.
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

JUDGE_PROMPT = (
    "Two pictures, A (first) and B (second), are candidate illustrations for this narration line of a Vietnamese "
    "short video:\n«{line}»\n"
    "Pick the picture that shows what the line says more faithfully: the right people and how many, their action, "
    "the place and the time of day. Prefer a clean picture without text, borders, extra limbs or broken shapes. "
    "Do not judge beauty. Answer with one letter only: A or B."
)
JUDGE_CONTEXT_TOKENS = 8192
JUDGE_IMAGE_WIDTH = 384

type Compare = Callable[[str, bytes, bytes], Awaitable[str | None]]


def judge_prompt_digest() -> str:
    """The digest of what the judge is asked and how its answers are combined."""
    return digest_value(
        "r2.production-image-judge.v1",
        ensure_json_value(
            {"prompt": JUDGE_PROMPT, "orders": "both", "disagreement": "keep-earlier", "width": JUDGE_IMAGE_WIDTH}
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


def letter(text: str) -> str | None:
    cleaned = text.strip().strip("*\"'.() ").upper()
    return cleaned[:1] if cleaned[:1] in {"A", "B"} and (len(cleaned) == 1 or not cleaned[1].isalpha()) else None


@dataclass
class Choice:
    """The chosen candidate's index and each comparison's answers, for the selection evidence."""

    index: int
    rounds: list[dict[str, object]] = field(default_factory=list)


async def prefer(compare: Compare, line: str, earlier: bytes, later: bytes) -> tuple[bool, list[str | None]]:
    """Whether the later candidate wins in both orders, with the two answers."""
    try:
        forward = await compare(line, earlier, later)
        backward = await compare(line, later, earlier)
    except (httpx.HTTPError, KeyError, ValueError):
        return False, [None, None]
    return forward == "B" and backward == "A", [forward, backward]


async def choose(compare: Compare, line: str, candidates: list[bytes]) -> Choice:
    """The index of the candidate the judge prefers; the first one unless a later one wins in both orders."""
    choice = Choice(index=0)
    for index in range(1, len(candidates)):
        wins, answers = await prefer(compare, line, candidates[choice.index], candidates[index])
        choice.rounds.append({"between": [choice.index, index], "answers": answers, "later_wins": wins})
        if wins:
            choice.index = index
    return choice


class OllamaImageJudge:
    """The ranking judge served by an Ollama chat endpoint that accepts several images per message."""

    def __init__(
        self,
        *,
        base_url_for: Callable[[str], Awaitable[str]],
        timeout_seconds: float = 300,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url_for, self._timeout, self._transport = base_url_for, timeout_seconds, transport

    async def choose(self, route: ModelRoute, line: str, candidates: list[bytes]) -> Choice:
        async with self.comparer(route) as compare:
            return await choose(compare, line, [judge_view(candidate) for candidate in candidates])

    @asynccontextmanager
    async def comparer(self, route: ModelRoute) -> AsyncGenerator[Compare]:
        """One admitted device job in which ``compare(line, a, b)`` asks the judge about two judge views."""
        url = normalize_ollama_base_url(await self._base_url_for(route.provider_id))
        async with (
            device_job(local_job(url, route.model_id)),
            httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client,
        ):

            async def compare(text: str, first: bytes, second: bytes) -> str | None:
                reply = await client.post(
                    url + "/api/chat",
                    json={
                        "model": route.model_id,
                        "stream": False,
                        "think": False,
                        "truncate": False,
                        "messages": [
                            {
                                "role": "user",
                                "content": JUDGE_PROMPT.format(line=text[:1500]),
                                "images": [base64.b64encode(first).decode(), base64.b64encode(second).decode()],
                            }
                        ],
                        "options": {"temperature": 0, "num_predict": 4, "num_ctx": JUDGE_CONTEXT_TOKENS},
                    },
                )
                reply.raise_for_status()
                return letter(str(reply.json()["message"].get("content") or ""))

            yield compare


MIN_QUALIFICATION_PAIRS = 30
MAX_WRONG_RATE = 0.10


async def qualify_judge(compare: Compare, pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Score the judge on pairs of a segment's own storyboard against another segment's, in both orders.

    Each pair is ``{"pair_id", "line", "own": bytes, "other": bytes}`` (judge views). An answer naming the other
    storyboard, no answer or an error counts as wrong; the judge qualifies with at least
    ``MIN_QUALIFICATION_PAIRS`` pairs and at most ``MAX_WRONG_RATE`` wrong in each order."""
    results = []
    for pair in pairs:
        answers: dict[str, str | None] = {}
        for order, (first, second) in (
            ("own_first", (pair["own"], pair["other"])),
            ("own_second", (pair["other"], pair["own"])),
        ):
            try:
                answers[order] = await compare(pair["line"], first, second)
            except (httpx.HTTPError, KeyError, ValueError):
                answers[order] = None
        results.append(
            {
                "pair_id": pair["pair_id"],
                "answers": answers,
                "own_first_right": answers["own_first"] == "A",
                "own_second_right": answers["own_second"] == "B",
            }
        )
    total = len(results)
    wrong = {order: sum(1 for r in results if not r[f"{order}_right"]) for order in ("own_first", "own_second")}
    qualified = total >= MIN_QUALIFICATION_PAIRS and all(count <= MAX_WRONG_RATE * total for count in wrong.values())
    return {
        "pairs": total,
        "wrong": wrong,
        "max_wrong_rate": MAX_WRONG_RATE,
        "qualified": qualified,
        "results": results,
    }


__all__ = [
    "Choice",
    "OllamaImageJudge",
    "choose",
    "judge_prompt_digest",
    "judge_view",
    "letter",
    "prefer",
    "qualify_judge",
]
