"""Story cloud transport: one counted SDK call per durable attempt, without retries."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from google import genai
from google.genai import types

from lib.text_backends.base import resolve_schema
from lib.text_backends.gemini import _to_response_schema
from server.story_authoring.contracts import (
    AttemptKind,
    OutputMode,
    StoryFailureCode,
    StoryLimits,
    StoryModelSelection,
    StoryScope,
    StoryStepOutput,
    StoryStepRequest,
    sha256_digest,
)
from server.story_authoring.generation import (
    AttemptSink,
    AuthoringTextGateway,
    StoryStepError,
    prose_schema,
    validate_story_content,
)

CLOUD_ENDPOINT = "gemini-generate"
GEMINI_STORY_MODELS = frozenset({"gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash"})


def _schema(request: StoryStepRequest) -> dict[str, Any]:
    if request.output_mode is OutputMode.PROSE:
        schema = prose_schema(
            min_paragraphs=request.min_paragraphs,
            max_paragraphs=request.max_paragraphs,
            min_paragraph_chars=request.min_paragraph_chars,
            max_paragraph_chars=request.max_paragraph_chars,
        )
    else:
        assert request.response_model is not None
        schema = resolve_schema(request.response_model)
    normalized = _to_response_schema(schema)

    def strip(node: Any, *, properties: bool = False) -> Any:
        if isinstance(node, list):
            return [strip(value) for value in node]
        if not isinstance(node, dict):
            return node
        if properties:
            return {key: strip(value) for key, value in node.items()}
        return {
            key: value if key in {"enum", "default", "examples"} else strip(value, properties=key == "properties")
            for key, value in node.items()
            if key not in {"pattern", "minLength", "maxLength", "additionalProperties"}
        }

    return strip(normalized)


@dataclass(frozen=True)
class CloudReply:
    content: str
    finish_reason: str
    input_tokens: int
    output_tokens: int


class GeminiStoryClient:
    def __init__(self, *, api_key: str, base_url: str):
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                base_url=base_url,
                httpx_async_client=httpx.AsyncClient(timeout=180, follow_redirects=False),
                timeout=180_000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    @staticmethod
    def config(request: StoryStepRequest) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=request.system_prompt,
            response_mime_type="application/json",
            response_schema=_schema(request),
            max_output_tokens=request.max_output_tokens,
            temperature=request.decoding.temperature,
            top_p=request.decoding.top_p,
            top_k=request.decoding.top_k,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def count(self, request: StoryStepRequest) -> int:
        config = self.config(request)
        wire = {
            "model": f"models/{request.selection.model_id}",
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": types.Schema.model_validate(_schema(request)).model_dump(
                    mode="json", by_alias=False, exclude_none=True
                ),
                "maxOutputTokens": config.max_output_tokens,
                "temperature": config.temperature,
                "topP": config.top_p,
                "topK": config.top_k,
            },
        }
        response = await self._client._api_client.async_request(
            "post", f"models/{request.selection.model_id}:countTokens", {"generateContentRequest": wire}
        )
        result = json.loads(response.body or "{}").get("totalTokens")
        if type(result) is not int or result <= 0:
            raise ValueError("missing input count")
        return result

    async def generate(self, request: StoryStepRequest) -> CloudReply:
        response = await self._client.aio.models.generate_content(
            model=request.selection.model_id, contents=request.prompt, config=self.config(request)
        )
        usage = response.usage_metadata
        if usage is None or usage.prompt_token_count is None or usage.candidates_token_count is None:
            raise ValueError("missing generation usage")
        thoughts = usage.thoughts_token_count or 0

        def tokens(value: object) -> int:
            if type(value) is not int or value < 0:
                raise ValueError("invalid generation usage")
            return value

        quantities = [tokens(usage.prompt_token_count), tokens(usage.candidates_token_count), tokens(thoughts)]
        candidates = response.candidates or []
        if len(candidates) != 1:
            raise ValueError("missing generation candidate")
        candidate = candidates[0]
        content = candidate.content
        text = "".join(part.text or "" for part in content.parts or [] if not part.thought) if content else ""
        reason = candidate.finish_reason.value if candidate.finish_reason is not None else "UNKNOWN"
        return CloudReply(text, reason, quantities[0], quantities[1] + quantities[2])

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


class CloudStoryGateway(AuthoringTextGateway):
    """Same story contract and acceptance policy, with the qualified cloud transport."""

    def __init__(
        self,
        *,
        selection: StoryModelSelection,
        limits: StoryLimits,
        client: GeminiStoryClient,
        sink: AttemptSink,
        revalidate: Callable[[], Awaitable[None]],
    ):
        if selection.endpoint != CLOUD_ENDPOINT or selection.model_id not in GEMINI_STORY_MODELS:
            raise ValueError("unsupported cloud story route")
        if limits.currency != "USD" or limits.cloud_prices is None:
            raise ValueError("cloud story requests require an approved USD budget")
        self._selection = selection
        self._limits = limits
        self._cloud_client = client
        self._sink = sink
        self._revalidate = revalidate

    async def _send_cloud(self, attempt: str, request: StoryStepRequest, *, count: bool) -> tuple[Any, int]:
        try:
            await self._revalidate()
        except Exception:
            await self._sink.failed(
                attempt, code=StoryFailureCode.SELECTION_CHANGED, detail="cloud route changed before dispatch"
            )
            raise StoryStepError(
                StoryFailureCode.SELECTION_CHANGED, "cloud route changed before dispatch", step_id=request.step_id
            ) from None
        await self._sink.dispatched(attempt)
        started = time.monotonic()
        try:
            result = await self._cloud_client.count(request) if count else await self._cloud_client.generate(request)
        except Exception:
            await self._sink.unknown(attempt, detail="cloud request outcome or usage is unknown")
            raise StoryStepError(
                StoryFailureCode.OUTCOME_UNKNOWN, "cloud request outcome or usage is unknown", step_id=request.step_id
            ) from None
        return result, int((time.monotonic() - started) * 1000)

    async def generate(self, *, scope: StoryScope, request: StoryStepRequest) -> StoryStepOutput:
        step = request.step_id
        if request.selection != self._selection:
            raise StoryStepError(StoryFailureCode.SELECTION_CHANGED, "the step names another route", step_id=step)
        if request.max_output_tokens > self._limits.max_output_tokens:
            raise StoryStepError(
                StoryFailureCode.INPUT_OVER_LIMIT, "output limit exceeds the approved cap", step_id=step
            )
        digest = sha256_digest(
            {
                "profile": "gemini-story-v1",
                "selection": request.selection.model_dump(mode="json"),
                "prompt": request.prompt,
                "config": self._cloud_client.config(request).model_dump(mode="json", exclude_none=True),
            }
        )
        count_attempt = await self._sink.reserve(
            scope=scope,
            step_id=step,
            kind=AttemptKind.COUNT,
            request_digest=digest,
            reserved_input_tokens=self._limits.server_context_tokens,
            reserved_output_tokens=0,
        )
        counted, duration = await self._send_cloud(count_attempt, request, count=True)
        await self._sink.completed(
            count_attempt, input_tokens=counted, output_tokens=0, done_reason="count", duration_ms=duration
        )
        bound = (
            counted
            + len(json.dumps(_schema(request), ensure_ascii=False).encode("utf-8"))
            + max(256, math.ceil(counted / 10))
        )
        if bound > self._limits.max_input_tokens:
            raise StoryStepError(
                StoryFailureCode.INPUT_OVER_LIMIT, "count plus safety margin exceeds input cap", step_id=step
            )
        attempt = await self._sink.reserve(
            scope=scope,
            step_id=step,
            kind=AttemptKind.GENERATE,
            request_digest=digest,
            reserved_input_tokens=bound,
            reserved_output_tokens=request.max_output_tokens,
        )
        response, duration = await self._send_cloud(attempt, request, count=False)
        await self._sink.completed(
            attempt,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            done_reason=response.finish_reason,
            duration_ms=duration,
        )
        code = None
        detail = ""
        text = ""
        if response.input_tokens > bound or response.output_tokens > request.max_output_tokens:
            code, detail = StoryFailureCode.COUNT_MISMATCH, "reported usage exceeds the reserved token bound"
        elif response.finish_reason == "MAX_TOKENS":
            code, detail = StoryFailureCode.OUTPUT_TRUNCATED, "cloud output was truncated"
        elif response.finish_reason != "STOP":
            code, detail = StoryFailureCode.OUTPUT_INVALID, "cloud output did not stop normally"
        else:
            code, detail, text = validate_story_content(request, response.content)
        if code is not None:
            raise StoryStepError(code, detail, step_id=step)
        return StoryStepOutput(
            step_id=step,
            text=text,
            provider_id=self._selection.provider_id,
            model_id=self._selection.model_id,
            finish_reason="stop",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            request_digest=digest,
            response_digest=sha256_digest({"content": response.content}),
            count_attempt_id=count_attempt,
            generate_attempt_id=attempt,
        )
