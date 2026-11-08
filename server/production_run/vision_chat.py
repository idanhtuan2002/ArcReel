"""One transport for the automatic run's vision models (frame reviewers, the image judge), chosen by endpoint.

A route's provider says which API its model speaks; the model name never does. A custom-provider model speaks its
endpoint (``ollama-chat``, ``openai-chat`` for any OpenAI-compatible server, ``gemini-generate``); the built-in
``gemini-aistudio`` and ``openai`` providers speak Gemini and OpenAI. Every protocol takes one user message with
text and pictures and returns the reply text and, when asked and served, the first tokens' top log probabilities in
one shape (``[{"token", "logprob", "top_logprobs": [{"token", "logprob"}]}]``). Requests are temperature 0. A cloud
answer of 429 or 503 (not processed) is retried with capped exponential backoff; anything else fails the call.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.config.resolver import ConfigResolver
from lib.config.url_utils import ensure_google_base_url, is_official_openai_base_url
from lib.custom_provider import is_custom_provider, parse_provider_id
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.generation_resources import device_job, local_job
from lib.text_backends.ollama import normalize_ollama_base_url

type Protocol = Literal["ollama", "openai", "gemini"]

ENDPOINT_PROTOCOLS: dict[str, Protocol] = {
    "ollama-chat": "ollama",
    "openai-chat": "openai",
    "gemini-generate": "gemini",
}
BUILTIN_PROTOCOLS: dict[str, Protocol] = {"gemini-aistudio": "gemini", "openai": "openai"}
DEFAULT_BASE_URLS: dict[Protocol, str] = {
    "ollama": "http://127.0.0.1:11434",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com",
}
#: Answers that mean the request was not processed (rate limited, overloaded), so a retry cannot bill twice. Other
#: 5xx answers may come after the provider did the work; the call fails instead (the review is then FAILED).
TRANSIENT_STATUSES = frozenset({429, 503})
TRANSIENT_ATTEMPTS = 6
MAX_BACKOFF_SECONDS = 120
#: OpenAI's Chat Completions accepts at most 20 alternatives per token.
MAX_TOP_LOGPROBS = 20


@dataclass(frozen=True)
class ModelAccess:
    protocol: Protocol
    base_url: str
    api_key: str = field(default="", repr=False)


type AccessFor = Callable[[str, str], Awaitable[ModelAccess]]


def model_access(sessions: async_sessionmaker[AsyncSession]) -> AccessFor:
    """How to reach ``(provider_id, model_id)``, read when a request is sent so a changed key or URL applies."""

    async def access(provider_id: str, model_id: str) -> ModelAccess:
        if is_custom_provider(provider_id):
            async with sessions() as session:
                repo = CustomProviderRepository(session)
                provider = await repo.get_provider(parse_provider_id(provider_id))
                model = await repo.get_model_by_ids(provider.id, model_id) if provider is not None else None
            if provider is None or model is None or model.endpoint not in ENDPOINT_PROTOCOLS:
                raise KeyError(provider_id)
            protocol = ENDPOINT_PROTOCOLS[model.endpoint]
            return ModelAccess(protocol, provider.base_url or DEFAULT_BASE_URLS[protocol], provider.api_key or "")
        protocol = BUILTIN_PROTOCOLS.get(provider_id)
        if protocol is None:
            raise KeyError(provider_id)
        async with ConfigResolver(sessions).session() as resolver:
            config = await resolver.provider_config(provider_id)
        return ModelAccess(protocol, config.get("base_url") or DEFAULT_BASE_URLS[protocol], config.get("api_key") or "")

    return access


def ollama_access(base_url_for: Callable[[str], Awaitable[str]]) -> AccessFor:
    """Every route served by the Ollama at its provider's base URL (local reviewers and tests)."""

    async def access(provider_id: str, _model_id: str) -> ModelAccess:
        return ModelAccess("ollama", await base_url_for(provider_id))

    return access


@dataclass(frozen=True)
class Reply:
    text: str
    logprobs: list[dict[str, Any]] | None = None


def _mime(picture: bytes) -> str:
    if picture.startswith(b"\x89PNG"):
        return "image/png"
    if picture[:4] == b"RIFF" and picture[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _b64(picture: bytes) -> str:
    return base64.b64encode(picture).decode("ascii")


class VisionChat:
    """Questions to one vision model; open it with :func:`vision_chat`."""

    def __init__(self, access: ModelAccess, model_id: str, client: httpx.AsyncClient, *, backoff: float) -> None:
        self.access, self.model_id, self._client, self._backoff = access, model_id, client, backoff

    async def ask(
        self,
        text: str,
        pictures: list[bytes],
        *,
        max_tokens: int | None = None,
        top_logprobs: int | None = None,
        schema: dict[str, Any] | None = None,
        context_tokens: int | None = None,
        think: bool | None = False,
        shift: bool | None = None,
    ) -> Reply:
        """One user message; ``think``/``shift``/``context_tokens`` apply to Ollama only."""
        if self.access.protocol == "ollama":
            return await self._ollama(text, pictures, max_tokens, top_logprobs, schema, context_tokens, think, shift)
        if self.access.protocol == "openai":
            return await self._openai(text, pictures, max_tokens, top_logprobs, schema)
        return await self._gemini(text, pictures, max_tokens, top_logprobs, schema)

    async def _post(self, url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        response = await self._client.post(url, json=body, headers=headers)
        if self.access.protocol != "ollama":
            for attempt in range(1, TRANSIENT_ATTEMPTS):
                if response.status_code not in TRANSIENT_STATUSES:
                    break
                await asyncio.sleep(min(self._backoff * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS))
                response = await self._client.post(url, json=body, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _ollama(
        self,
        text: str,
        pictures: list[bytes],
        max_tokens: int | None,
        top_logprobs: int | None,
        schema: dict[str, Any] | None,
        context_tokens: int | None,
        think: bool | None,
        shift: bool | None,
    ) -> Reply:
        body: dict[str, Any] = {"model": self.model_id, "stream": False}
        if think is not None:
            body["think"] = think
        body["truncate"] = False
        if shift is not None:
            body["shift"] = shift
        if schema is not None:
            body["format"] = schema
        if top_logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = top_logprobs
        body["messages"] = [{"role": "user", "content": text, "images": [_b64(p) for p in pictures]}]
        options: dict[str, Any] = {"temperature": 0}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if context_tokens is not None:
            options["num_ctx"] = context_tokens
        body["options"] = options
        data = await self._post(normalize_ollama_base_url(self.access.base_url) + "/api/chat", body)
        return Reply(str(data["message"].get("content") or ""), data.get("logprobs"))

    async def _openai(
        self,
        text: str,
        pictures: list[bytes],
        max_tokens: int | None,
        top_logprobs: int | None,
        schema: dict[str, Any] | None,
    ) -> Reply:
        base = self.access.base_url.rstrip("/")
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content += [{"type": "image_url", "image_url": {"url": f"data:{_mime(p)};base64,{_b64(p)}"}} for p in pictures]
        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
        }
        if max_tokens is not None:
            body["max_completion_tokens" if is_official_openai_base_url(base) else "max_tokens"] = max_tokens
        if top_logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = min(top_logprobs, MAX_TOP_LOGPROBS)
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "strict": False, "schema": schema},
            }
        headers = {"Authorization": f"Bearer {self.access.api_key}"} if self.access.api_key else None
        data = await self._post(base + "/chat/completions", body, headers)
        choice = data["choices"][0]
        logprobs = (choice.get("logprobs") or {}).get("content")
        return Reply(str(choice["message"].get("content") or ""), logprobs)

    async def _gemini(
        self,
        text: str,
        pictures: list[bytes],
        max_tokens: int | None,
        top_logprobs: int | None,
        schema: dict[str, Any] | None,
    ) -> Reply:
        base = (ensure_google_base_url(self.access.base_url) or DEFAULT_BASE_URLS["gemini"]).rstrip("/")
        parts: list[dict[str, Any]] = [{"inline_data": {"mime_type": _mime(p), "data": _b64(p)}} for p in pictures]
        parts.append({"text": text})
        config: dict[str, Any] = {"temperature": 0}
        if max_tokens is not None:
            config["maxOutputTokens"] = max_tokens
        if top_logprobs:
            config["responseLogprobs"] = True
            config["logprobs"] = min(top_logprobs, MAX_TOP_LOGPROBS)
        if schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = schema
        body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": config}
        data = await self._post(
            f"{base}/v1beta/models/{self.model_id}:generateContent", body, {"x-goog-api-key": self.access.api_key}
        )
        candidate = data["candidates"][0]
        answer = "".join(str(part.get("text", "")) for part in candidate.get("content", {}).get("parts", []))
        steps = (candidate.get("logprobsResult") or {}).get("topCandidates") or []
        logprobs = [
            {
                "top_logprobs": [
                    {"token": c.get("token", ""), "logprob": c.get("logProbability", float("-inf"))}
                    for c in step.get("candidates") or []
                ]
            }
            for step in steps
        ]
        return Reply(answer, logprobs or None)


@asynccontextmanager
async def vision_chat(
    access: ModelAccess,
    model_id: str,
    *,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
    backoff_seconds: float = 10,
) -> AsyncGenerator[VisionChat]:
    """A conversation with one model; a local Ollama model is admitted as one device job first."""
    local = (
        device_job(local_job(normalize_ollama_base_url(access.base_url), model_id))
        if access.protocol == "ollama"
        else nullcontext()
    )
    async with local, httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        yield VisionChat(access, model_id, client, backoff=backoff_seconds)


__all__ = [
    "ENDPOINT_PROTOCOLS",
    "AccessFor",
    "ModelAccess",
    "Reply",
    "VisionChat",
    "model_access",
    "ollama_access",
    "vision_chat",
]
