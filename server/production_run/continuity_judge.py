"""Continuity judge of one storyboard frame against its references and the previous frame (ADR-0134).

The judge looks at the pictures, not the prompt: the frame, the reference sheets of the characters, location and props
it should show, and the previous frame of the same scene. It checks, in a fixed order, identity, wardrobe, props,
location, lighting, screen direction (180° rule), eyeline, staging, readable text, framing and image-model artifacts,
and returns a 0–100 score, issues with a severity, and a short fix to add to the image prompt. The verdict is computed
in code from the model's answer: any high-severity issue caps the score at 69, so a frame with such an issue is
always a drift. A model or transport failure is ``None``; the caller keeps the frame (the judge never blocks a run).
The checks and their order follow the AI Video Production Editor continuity rubric (research 2026-11-13).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from r2.automation.identity import digest_value
from r2.contracts.automation import ModelRoute
from r2.contracts.common import ensure_json_value
from server.production_run.vision_chat import AccessFor, vision_chat

CATEGORIES = (
    "identity",
    "wardrobe",
    "props",
    "location",
    "lighting",
    "screen_direction",
    "eyeline",
    "staging",
    "text",
    "framing",
    "artifacts",
)
SEVERITIES = ("low", "medium", "high")
ALIGNED_SCORE = 90
DRIFT_BELOW = 70
HIGH_SEVERITY_CAP = 69
MAX_PROMPT_FIX_CHARS = 400
JUDGE_MAX_TOKENS = 2048

type Status = Literal["aligned", "watch", "drift"]

PROMPT = """You are the script supervisor and editor of a Vietnamese short film. Judge ONE storyboard frame for \
continuity by looking at the images, not by trusting the description.

Images:
{images}

Shot {label}: {description}
Intended framing: {framing}
In frame: {cast}{location}{props}
{previous}

Check, in this order:
1. identity - every character matches their reference sheet: face, hair, age, build, gender.
2. wardrobe - clothes, colours and accessories match the reference and the previous shot of the same scene.
3. props - the right props, in the right hands, consistent with the previous shot.
4. location - the same place and layout as the location reference and the previous shot of the scene.
5. lighting - the same time of day, light direction and colour as the previous shot of the scene.
6. screen_direction - the 180 degree rule: characters keep their left/right sides across the cut.
7. eyeline - characters look at who or what they should, given positions and heights.
8. staging - the action and blocking the description asks for (who stands where, who holds what).
9. text - any readable text says exactly what it should; no stray or garbled letters.
10. framing - shot size and angle match the intended framing; the vertical composition works.
11. artifacts - image-model defects: ghosted or merged bodies, extra or missing limbs or fingers, warped faces, \
duplicated people. Any of these is high severity.

Scoring: 90-100 aligned (cuts cleanly), 70-89 watch (minor issues), below 70 drift (a viewer would notice).
prompt_fix: one or two short sentences to ADD to the image prompt that fix the issues concretely (positions as \
"on the left/right of frame", colours, counts). Empty when aligned.
Return JSON only."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "message": {"type": "string"},
                },
                "required": ["category", "severity", "message"],
            },
        },
        "prompt_fix": {"type": "string"},
    },
    "required": ["score", "issues", "prompt_fix"],
}


@dataclass(frozen=True)
class Shot:
    """What the frame should show; ``references`` are ``(label, picture)`` pairs, the previous frame excluded."""

    label: str
    description: str
    characters: tuple[str, ...] = ()
    location: str = ""
    props: tuple[str, ...] = ()
    framing: str = ""
    references: tuple[tuple[str, bytes], ...] = ()
    previous_description: str = ""
    previous_frame: bytes | None = None


@dataclass(frozen=True)
class Issue:
    category: str
    severity: str
    message: str


@dataclass(frozen=True)
class Verdict:
    score: int
    status: Status
    issues: tuple[Issue, ...] = field(default_factory=tuple)
    prompt_fix: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "status": self.status,
            "issues": [issue.__dict__ for issue in self.issues],
            "prompt_fix": self.prompt_fix,
        }


def prompt_digest() -> str:
    """The digest of what the continuity judge is asked; a qualification and a launch profile pin it."""
    return digest_value(
        "r2.production-continuity-judge.v1",
        ensure_json_value({"prompt": PROMPT, "schema": SCHEMA, "drift_below": DRIFT_BELOW, "cap": HIGH_SEVERITY_CAP}),
    )


def build_request(shot: Shot, frame: bytes) -> tuple[str, list[bytes]]:
    """The question and the pictures in the order the question names them."""
    pictures = [frame]
    labels = [f"Image 1: the frame to judge (shot {shot.label})"]
    for label, picture in shot.references:
        pictures.append(picture)
        labels.append(f"Image {len(pictures)}: reference - {label}")
    if shot.previous_frame is not None:
        pictures.append(shot.previous_frame)
        labels.append(f"Image {len(pictures)}: the previous frame of the same scene")
    previous = (
        f"Previous shot of the same scene: {shot.previous_description}"
        if shot.previous_frame is not None or shot.previous_description
        else "This is the first shot of its scene."
    )
    text = PROMPT.format(
        images="\n".join(labels),
        label=shot.label,
        description=shot.description.strip()[:2400],
        framing=shot.framing or "not specified",
        cast=", ".join(shot.characters) or "no characters",
        location=f" - location: {shot.location}" if shot.location else "",
        props=f" - props: {', '.join(shot.props)}" if shot.props else "",
        previous=previous,
    )
    return text, pictures


def parse_verdict(answer: str) -> Verdict:
    """The verdict of a model answer; raises ``ValueError`` when the answer is not a usable verdict."""
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object")
    data = json.loads(answer[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("verdict is not an object")
    raw_score = data.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, int | float):
        raise ValueError("score is not a number")
    issues = tuple(
        Issue(str(item["category"]), str(item["severity"]), str(item.get("message", "")).strip())
        for item in data.get("issues") or []
        if isinstance(item, dict) and item.get("category") in CATEGORIES and item.get("severity") in SEVERITIES
    )
    score = max(0, min(100, round(float(raw_score))))
    if any(issue.severity == "high" for issue in issues):
        score = min(score, HIGH_SEVERITY_CAP)
    status: Status = "aligned" if score >= ALIGNED_SCORE else "watch" if score >= DRIFT_BELOW else "drift"
    fix = " ".join(str(data.get("prompt_fix") or "").split())[:MAX_PROMPT_FIX_CHARS]
    return Verdict(score=score, status=status, issues=issues, prompt_fix="" if status == "aligned" else fix)


MIN_CASES_PER_CLASS = 30
MIN_DRIFT_RECALL = 0.8
MAX_FALSE_DRIFT = 0.15
MAX_UNANSWERED = 0.05


def qualify_continuity(results: list[tuple[str, Verdict | None]]) -> dict[str, Any]:
    """The qualification report of ``(expected, verdict)`` results, ``expected`` being ``drift`` or ``ok``.

    Qualified when each class has at least 30 cases, at least 80% of drift cases are judged drift, at most 15% of ok
    cases are judged drift, and at most 5% of all cases got no usable answer (an unanswered drift case counts as
    missed, an unanswered ok case as not flagged)."""
    drift = [verdict for expected, verdict in results if expected == "drift"]
    ok = [verdict for expected, verdict in results if expected == "ok"]
    unanswered = sum(1 for _, verdict in results if verdict is None)
    caught = sum(1 for verdict in drift if verdict is not None and verdict.status == "drift")
    false = sum(1 for verdict in ok if verdict is not None and verdict.status == "drift")
    recall = caught / len(drift) if drift else 0.0
    false_rate = false / len(ok) if ok else 1.0
    unanswered_rate = unanswered / len(results) if results else 1.0
    qualified = (
        len(drift) >= MIN_CASES_PER_CLASS
        and len(ok) >= MIN_CASES_PER_CLASS
        and recall >= MIN_DRIFT_RECALL
        and false_rate <= MAX_FALSE_DRIFT
        and unanswered_rate <= MAX_UNANSWERED
    )
    return {
        "drift_cases": len(drift),
        "ok_cases": len(ok),
        "drift_recall": round(recall, 4),
        "false_drift_rate": round(false_rate, 4),
        "unanswered_rate": round(unanswered_rate, 4),
        "qualified": qualified,
    }


class ContinuityJudge:
    """The continuity judge, served by the route's provider endpoint."""

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

    async def judge(self, route: ModelRoute, shot: Shot, frame: bytes) -> Verdict | None:
        """The verdict on ``frame``; ``None`` when the model or the transport fails."""
        text, pictures = build_request(shot, frame)
        try:
            access = await self._access_for(route.provider_id, route.model_id)
            async with vision_chat(
                access,
                route.model_id,
                timeout_seconds=self._timeout,
                transport=self._transport,
                backoff_seconds=self._backoff,
            ) as chat:
                reply = await chat.ask(text, pictures, max_tokens=JUDGE_MAX_TOKENS, schema=SCHEMA)
            return parse_verdict(reply.text)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None


__all__ = [
    "CATEGORIES",
    "SCHEMA",
    "ContinuityJudge",
    "Issue",
    "Shot",
    "Verdict",
    "build_request",
    "parse_verdict",
    "prompt_digest",
    "qualify_continuity",
]
