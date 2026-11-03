"""A reviewer route served by the Gemini API: the model watches the final (picture and narration audio).

The final is sent inline with the review prompt; the answer follows the same JSON schema and scoring anchors as the
local reviewers, and the deterministic subtitle and picture checks are added to its findings. Credentials come from
the route's custom provider (``gemini-generate`` endpoint), read when a review is sent.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.custom_provider import parse_provider_id
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from r2.automation.assessment import AssessmentFinding, ModelAssessment
from r2.automation.profiles import route_digest
from r2.contracts.automation import ModelRoute, RunStage
from server.production_run.evaluators import (
    SCHEMA,
    WATCH,
    WATCH_PROMPT,
    FinalEvidence,
    QualifiedEvaluator,
    evidence_digest,
    prompt_digest,
    review_method,
)
from server.production_run.final_checks import picture_findings, subtitle_findings

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
#: Inline request data limit of the Gemini API; larger finals would need the Files API.
MAX_INLINE_BYTES = 20 * 1024 * 1024
#: Overload and rate-limit answers are retried with capped exponential backoff before the review fails; Gemini
#: Flash models answer 503 under load for minutes at a time.
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
TRANSIENT_ATTEMPTS = 6
MAX_BACKOFF_SECONDS = 120

type Credentials = Callable[[str], Awaitable[tuple[str, str]]]


class GeminiReviewer:
    """Reviews a final with one ``generateContent`` call: the mp4 inline, temperature 0, JSON answer."""

    def __init__(
        self,
        *,
        credentials_for: Credentials,
        timeout_seconds: float = 600,
        backoff_seconds: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._credentials_for = credentials_for
        self._backoff = backoff_seconds
        self._timeout = timeout_seconds
        self._transport = transport

    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment:
        base = {
            "reviewer_route_digest": route_digest(route),
            "model_identity": route.model_identity,
            "prompt_digest": prompt_digest(WATCH),
            "subject_digest": evidence.subject_digest,
            "evidence_digest": evidence_digest(evidence),
        }
        try:
            subtitles = evidence.subtitle_path.read_text(encoding="utf-8")
            video = await asyncio.to_thread(evidence.final_path.read_bytes)
            if len(video) > MAX_INLINE_BYTES:
                return ModelAssessment.model_validate({**base, "outcome": "FAILED"})
            checks = subtitle_findings(subtitles, evidence.narration_text, unit_key=evidence.unit_key)
            checks += await asyncio.to_thread(picture_findings, evidence.final_path, unit_key=evidence.unit_key)
            base_url, api_key = await self._credentials_for(route.provider_id)
            body = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "inline_data": {
                                    "mime_type": "video/mp4",
                                    "data": base64.b64encode(video).decode("ascii"),
                                }
                            },
                            {
                                "text": WATCH_PROMPT.format(
                                    subtitles=subtitles[:6000], narration=evidence.narration_text[:6000]
                                )
                            },
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": SCHEMA,
                },
            }
            url = f"{(base_url or DEFAULT_BASE_URL).rstrip('/')}/v1beta/models/{route.model_id}:generateContent"
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
                for attempt in range(1, TRANSIENT_ATTEMPTS):
                    if response.status_code not in TRANSIENT_STATUSES:
                        break
                    await asyncio.sleep(min(self._backoff * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS))
                    response = await client.post(url, json=body, headers={"x-goog-api-key": api_key})
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            answer = json.loads("".join(str(part.get("text", "")) for part in parts))
            return ModelAssessment.model_validate(
                {
                    **base,
                    "outcome": "COMPLETED",
                    "language": str(answer["language"]).strip().lower()[:8],
                    "scores": answer["scores"],
                    "findings": [
                        *checks,
                        *(
                            AssessmentFinding(
                                code=str(f["code"]).upper()[:64] or "UNSPECIFIED",
                                severity=f["severity"],
                                unit_key=evidence.unit_key,
                                repair_stage=RunStage(f["repair_stage"]) if f.get("repair_stage") else None,
                                detail=str(f.get("detail", ""))[:500],
                            )
                            for f in answer["findings"]
                        ),
                    ],
                }
            )
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, subprocess.SubprocessError):
            return ModelAssessment.model_validate({**base, "outcome": "FAILED"})


class RoutedReviewer:
    """Sends each review to the reviewer that serves the route's review method."""

    def __init__(self, *, local: QualifiedEvaluator, gemini: QualifiedEvaluator) -> None:
        self._local, self._gemini = local, gemini

    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment:
        reviewer = self._gemini if review_method(route) == WATCH else self._local
        return await reviewer.assess(route=route, evidence=evidence)


def provider_credentials(sessions: async_sessionmaker[AsyncSession]) -> Credentials:
    """The base URL and API key of a custom provider, read at the moment a review is sent."""

    async def credentials(provider_id: str) -> tuple[str, str]:
        async with sessions() as session:
            provider = await CustomProviderRepository(session).get_provider(parse_provider_id(provider_id))
        if provider is None or not provider.api_key:
            raise KeyError(provider_id)
        return provider.base_url, provider.api_key

    return credentials


__all__ = ["GeminiReviewer", "RoutedReviewer", "provider_credentials"]
