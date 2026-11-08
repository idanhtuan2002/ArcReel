"""Story cloud transport: one counted call per durable attempt, without retries.

The transport follows the route's endpoint, never its model name: ``gemini-generate`` uses the Gemini API (exact
``countTokens``), ``openai-chat`` any OpenAI-compatible Chat Completions server (counted by a local bound).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from google import genai
from google.genai import types

from lib.config.url_utils import ensure_google_base_url, is_official_openai_base_url
from lib.openai_shared import create_openai_client
from lib.text_backends.base import resolve_schema
from lib.text_backends.gemini import _to_response_schema
from server.story_authoring.contracts import (
    AttemptKind,
    OutputMode,
    StoryAdapterVersion,
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
OPENAI_ENDPOINT = "openai-chat"
#: Adapter version of each cloud endpoint; it names the request shape in request digests and route bindings.
CLOUD_ADAPTERS: dict[str, StoryAdapterVersion] = {CLOUD_ENDPOINT: "gemini-story-v1", OPENAI_ENDPOINT: "openai-story-v1"}


def _schema(request: StoryStepRequest, *, gemini: bool = True) -> dict[str, Any]:
    """The step's output schema without the keywords cloud schema decoders reject; the reply is still validated
    against the full schema. Gemini's dialect also turns ``const`` and non-string enums into string enums."""
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
    normalized = _to_response_schema(schema) if gemini else resolve_schema(schema)

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


class StoryCloudClient(Protocol):
    adapter_version: str

    def wire_config(self, request: StoryStepRequest) -> dict[str, Any]: ...

    async def count(self, request: StoryStepRequest) -> int: ...

    async def generate(self, request: StoryStepRequest) -> CloudReply: ...

    async def close(self) -> None: ...


class GeminiStoryClient:
    adapter_version = CLOUD_ADAPTERS[CLOUD_ENDPOINT]

    def __init__(self, *, api_key: str, base_url: str):
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                base_url=ensure_google_base_url(base_url),
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

    def wire_config(self, request: StoryStepRequest) -> dict[str, Any]:
        return self.config(request).model_dump(mode="json", exclude_none=True)

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


#: An OpenAI-compatible server has no count endpoint, so the input is bounded before dispatch by its UTF-8 size: every
#: token of a byte-level BPE or byte-fallback SentencePiece vocabulary covers at least one byte, so the byte count
#: never undercounts the text. The chat template adds a bounded number of tokens per message and per request.
OPENAI_MESSAGE_OVERHEAD = 16
OPENAI_REQUEST_OVERHEAD = 64
#: Per-step input cap of a brief with an OpenAI-compatible route, in the byte-bound units above (four times the
#: default token cap, since UTF-8 Vietnamese text runs several bytes per token).
OPENAI_MAX_INPUT_BOUND = 4 * 24576


class OpenAIStoryClient:
    """Any OpenAI-compatible Chat Completions server: JSON-schema output, usage from the response."""

    adapter_version = CLOUD_ADAPTERS[OPENAI_ENDPOINT]

    def __init__(self, *, api_key: str, base_url: str):
        self._client = create_openai_client(api_key=api_key, base_url=base_url, max_retries=0)
        # Official endpoints reject max_tokens for reasoning models; compatible servers may not know the new name.
        self._token_param = "max_completion_tokens" if is_official_openai_base_url(base_url) else "max_tokens"

    def wire_config(self, request: StoryStepRequest) -> dict[str, Any]:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "story_step", "strict": False, "schema": _schema(request, gemini=False)},
            },
            self._token_param: request.max_output_tokens,
            "temperature": request.decoding.temperature,
            "top_p": request.decoding.top_p,
            "seed": request.decoding.seed,
        }

    @staticmethod
    def messages(request: StoryStepRequest) -> list[dict[str, str]]:
        return [{"role": "system", "content": request.system_prompt}, {"role": "user", "content": request.prompt}]

    async def count(self, request: StoryStepRequest) -> int:
        messages = self.messages(request)
        size = sum(len(message["content"].encode("utf-8")) for message in messages)
        return size + OPENAI_MESSAGE_OVERHEAD * len(messages) + OPENAI_REQUEST_OVERHEAD

    async def generate(self, request: StoryStepRequest) -> CloudReply:
        body: dict[str, Any] = {
            "model": request.selection.model_id,
            "messages": self.messages(request),
            **self.wire_config(request),
        }
        response = await self._client.chat.completions.create(**body)
        usage = response.usage
        if usage is None or type(usage.prompt_tokens) is not int or type(usage.completion_tokens) is not int:
            raise ValueError("missing generation usage")
        if usage.prompt_tokens < 0 or usage.completion_tokens < 0 or len(response.choices) != 1:
            raise ValueError("invalid generation reply")
        choice = response.choices[0]
        reason = {"stop": "STOP", "length": "MAX_TOKENS"}.get(str(choice.finish_reason), str(choice.finish_reason))
        return CloudReply(choice.message.content or "", reason, usage.prompt_tokens, usage.completion_tokens)

    async def close(self) -> None:
        await self._client.close()


def story_cloud_client(selection: StoryModelSelection, *, api_key: str) -> StoryCloudClient:
    """The transport of a cloud story route, chosen by its endpoint."""
    if selection.endpoint == CLOUD_ENDPOINT:
        return GeminiStoryClient(api_key=api_key, base_url=selection.base_url)
    if selection.endpoint == OPENAI_ENDPOINT:
        return OpenAIStoryClient(api_key=api_key, base_url=selection.base_url)
    raise ValueError("unsupported cloud story endpoint")


class CloudStoryGateway(AuthoringTextGateway):
    """Same story contract and acceptance policy, with the qualified cloud transport."""

    def __init__(
        self,
        *,
        selection: StoryModelSelection,
        limits: StoryLimits,
        client: StoryCloudClient,
        sink: AttemptSink,
        revalidate: Callable[[], Awaitable[None]],
    ):
        if CLOUD_ADAPTERS.get(selection.endpoint) != client.adapter_version:
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
                "profile": self._cloud_client.adapter_version,
                "selection": request.selection.model_dump(mode="json"),
                "prompt": request.prompt,
                "config": self._cloud_client.wire_config(request),
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
            await self._sink.failed(
                attempt,
                code=code,
                detail=detail,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                done_reason=response.finish_reason,
                duration_ms=duration,
            )
            raise StoryStepError(code, detail, step_id=step)
        await self._sink.completed(
            attempt,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            done_reason=response.finish_reason,
            duration_ms=duration,
        )
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
