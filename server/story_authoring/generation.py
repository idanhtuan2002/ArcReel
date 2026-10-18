"""The only application-level generation seam of story authoring.

One :meth:`AuthoringTextGateway.generate` is exactly two HTTP requests on the frozen route:

1. ``COUNT``: the exact request with ``num_predict: 1``. The server's ``prompt_eval_count`` is the exact
   input size; it enforces the authored input limit before any generation.
2. ``GENERATE``: the same request with the real ``num_predict``. Its output is accepted only when
   ``done`` is true, ``done_reason`` is ``stop``, the reported input equals the counted input, the body is
   the declared JSON shape, and the shared detector finds no CJK.

Every request is reserved, marked dispatched and settled through the :class:`AttemptSink` before and
after it is sent. Nothing here retries, falls back or re-resolves another model; repair and regeneration
are separate, counted steps decided by the caller.
"""

from __future__ import annotations

import copy
import time
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from lib.text_backends.base import resolve_schema
from lib.text_backends.ollama import (
    OllamaChatClient,
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaError,
    OllamaOutcomeUnknownError,
    OllamaOverContextError,
    OllamaUnavailableError,
)
from server.story_authoring.contracts import (
    OLLAMA_CHAT_ENDPOINT,
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
from server.story_authoring.script_guard import find_cjk, no_cjk_pattern

COUNT_ACCEPTED_DONE_REASONS = frozenset({"stop", "length"})


class StoryStepError(Exception):
    def __init__(self, code: StoryFailureCode, detail: str, *, step_id: str) -> None:
        self.code = code
        self.detail = detail
        self.step_id = step_id
        super().__init__(f"{code.value} at {step_id}: {detail}")


class AttemptSink(Protocol):
    """Durable attempt ledger and budget. ``reserve`` raises :class:`StoryStepError` (BUDGET_EXHAUSTED) to refuse."""

    async def reserve(
        self,
        *,
        scope: StoryScope,
        step_id: str,
        kind: AttemptKind,
        request_digest: str,
        reserved_input_tokens: int,
        reserved_output_tokens: int,
    ) -> str: ...

    async def dispatched(self, attempt_id: str) -> None: ...

    async def completed(
        self, attempt_id: str, *, input_tokens: int, output_tokens: int, done_reason: str, duration_ms: int
    ) -> None: ...

    async def failed(
        self, attempt_id: str, *, code: StoryFailureCode, detail: str, input_tokens: int | None = None
    ) -> None: ...

    async def unknown(self, attempt_id: str, *, detail: str) -> None: ...


class ProseEnvelope(BaseModel):
    model_config = {"extra": "forbid"}
    text: str


def prose_envelope_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1, "pattern": no_cjk_pattern()}},
        "required": ["text"],
        "additionalProperties": False,
    }


def constrain_strings(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy of a JSON schema in which every string without its own ``pattern`` excludes CJK."""
    constrained = copy.deepcopy(schema)

    def visit(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "string" and "pattern" not in node and "enum" not in node:
                node["pattern"] = no_cjk_pattern()
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(constrained)
    return constrained


class AuthoringTextGateway:
    def __init__(
        self,
        *,
        selection: StoryModelSelection,
        limits: StoryLimits,
        client: OllamaChatClient,
        sink: AttemptSink,
        keep_alive: str | None = None,
    ) -> None:
        if selection.endpoint != OLLAMA_CHAT_ENDPOINT:
            raise StoryStepError(
                StoryFailureCode.PROVIDER_NOT_QUALIFIED,
                f"endpoint {selection.endpoint!r} is not qualified for story authoring",
                step_id="-",
            )
        self._selection = selection
        self._limits = limits
        self._client = client
        self._sink = sink
        self._keep_alive = keep_alive

    async def generate(self, *, scope: StoryScope, request: StoryStepRequest) -> StoryStepOutput:
        step = request.step_id
        if request.selection != self._selection:
            raise StoryStepError(StoryFailureCode.SELECTION_CHANGED, "the step names another route", step_id=step)
        if request.max_output_tokens > self._limits.max_output_tokens:
            raise StoryStepError(
                StoryFailureCode.INPUT_OVER_LIMIT,
                f"max_output_tokens {request.max_output_tokens} exceeds {self._limits.max_output_tokens}",
                step_id=step,
            )
        generate_request = self._chat_request(request, num_predict=request.max_output_tokens)
        count_request = self._chat_request(request, num_predict=1)
        request_digest = sha256_digest(generate_request.payload())

        counted, count_attempt = await self._count(scope, step, count_request, request_digest)
        if counted > self._limits.max_input_tokens:
            raise StoryStepError(
                StoryFailureCode.INPUT_OVER_LIMIT,
                f"counted input {counted} exceeds {self._limits.max_input_tokens}",
                step_id=step,
            )

        attempt = await self._sink.reserve(
            scope=scope,
            step_id=step,
            kind=AttemptKind.GENERATE,
            request_digest=request_digest,
            reserved_input_tokens=counted,
            reserved_output_tokens=request.max_output_tokens,
        )
        response, duration_ms = await self._send(attempt, step, generate_request)
        text = await self._accept_generation(attempt, step, request, response, counted)
        await self._sink.completed(
            attempt,
            input_tokens=counted,
            output_tokens=response.eval_count or 0,
            done_reason="stop",
            duration_ms=duration_ms,
        )
        return StoryStepOutput(
            step_id=step,
            text=text,
            provider_id=self._selection.provider_id,
            model_id=self._selection.model_id,
            finish_reason="stop",
            input_tokens=counted,
            output_tokens=response.eval_count or 0,
            request_digest=request_digest,
            response_digest=sha256_digest({"content": response.content}),
            count_attempt_id=count_attempt,
            generate_attempt_id=attempt,
        )

    def _chat_request(self, request: StoryStepRequest, *, num_predict: int) -> OllamaChatRequest:
        if request.output_mode is OutputMode.PROSE:
            schema = prose_envelope_schema()
        else:
            assert request.response_model is not None
            schema = constrain_strings(resolve_schema(request.response_model))
        return OllamaChatRequest(
            model=self._selection.model_id,
            messages=(("system", request.system_prompt), ("user", request.prompt)),
            num_ctx=self._limits.server_context_tokens,
            num_predict=num_predict,
            format=schema,
            options=request.decoding.options(),
            keep_alive=self._keep_alive,
        )

    async def _count(
        self, scope: StoryScope, step: str, count_request: OllamaChatRequest, request_digest: str
    ) -> tuple[int, str]:
        attempt = await self._sink.reserve(
            scope=scope,
            step_id=step,
            kind=AttemptKind.COUNT,
            request_digest=request_digest,
            reserved_input_tokens=self._limits.server_context_tokens,
            reserved_output_tokens=1,
        )
        response, duration_ms = await self._send(attempt, step, count_request)
        counted = response.prompt_eval_count
        problem = None
        if not response.done or response.done_reason not in COUNT_ACCEPTED_DONE_REASONS:
            problem = f"count probe ended with done={response.done} done_reason={response.done_reason!r}"
        elif counted is None or counted <= 0:
            problem = "count probe reported no prompt_eval_count"
        elif response.model != self._selection.model_id:
            problem = f"count probe answered as model {response.model!r}"
        if problem is not None or counted is None:
            await self._sink.failed(attempt, code=StoryFailureCode.OUTPUT_INVALID, detail=problem or "")
            raise StoryStepError(StoryFailureCode.OUTPUT_INVALID, problem or "", step_id=step)
        await self._sink.completed(
            attempt,
            input_tokens=counted,
            output_tokens=response.eval_count or 0,
            done_reason=response.done_reason or "",
            duration_ms=duration_ms,
        )
        return counted, attempt

    async def _send(self, attempt: str, step: str, chat: OllamaChatRequest) -> tuple[OllamaChatResponse, int]:
        await self._sink.dispatched(attempt)
        started = time.monotonic()
        try:
            response = await self._client.chat(chat)
        except OllamaOverContextError as exc:
            await self._sink.failed(
                attempt, code=StoryFailureCode.INPUT_OVER_CONTEXT, detail=str(exc), input_tokens=exc.prompt_tokens
            )
            raise StoryStepError(StoryFailureCode.INPUT_OVER_CONTEXT, str(exc), step_id=step) from exc
        except OllamaUnavailableError as exc:
            await self._sink.failed(attempt, code=StoryFailureCode.MODEL_UNAVAILABLE, detail=str(exc))
            raise StoryStepError(StoryFailureCode.MODEL_UNAVAILABLE, str(exc), step_id=step) from exc
        except OllamaOutcomeUnknownError as exc:
            await self._sink.unknown(attempt, detail=str(exc))
            raise StoryStepError(StoryFailureCode.OUTCOME_UNKNOWN, str(exc), step_id=step) from exc
        except OllamaError as exc:
            await self._sink.failed(attempt, code=StoryFailureCode.PROVIDER_ERROR, detail=str(exc))
            raise StoryStepError(StoryFailureCode.PROVIDER_ERROR, str(exc), step_id=step) from exc
        return response, int((time.monotonic() - started) * 1000)

    async def _accept_generation(
        self,
        attempt: str,
        step: str,
        request: StoryStepRequest,
        response: OllamaChatResponse,
        counted: int,
    ) -> str:
        code, detail, text = self._judge(request, response, counted)
        if code is not None:
            await self._sink.failed(attempt, code=code, detail=detail, input_tokens=response.prompt_eval_count)
            raise StoryStepError(code, detail, step_id=step)
        return text

    def _judge(
        self, request: StoryStepRequest, response: OllamaChatResponse, counted: int
    ) -> tuple[StoryFailureCode | None, str, str]:
        if response.prompt_eval_count != counted:
            return (
                StoryFailureCode.COUNT_MISMATCH,
                f"generation reported {response.prompt_eval_count} input tokens, count probe {counted}",
                "",
            )
        if not response.done:
            return StoryFailureCode.OUTPUT_INVALID, "response not done", ""
        if response.done_reason == "length":
            return StoryFailureCode.OUTPUT_TRUNCATED, f"output stopped at {response.eval_count} tokens", ""
        if response.done_reason != "stop":
            return StoryFailureCode.OUTPUT_INVALID, f"done_reason {response.done_reason!r}", ""
        hits = find_cjk(response.content)
        if hits:
            sample = "".join(hit.char for hit in hits[:10])
            return StoryFailureCode.CJK_IN_OUTPUT, f"{len(hits)} CJK code points ({sample})", ""
        try:
            if request.output_mode is OutputMode.PROSE:
                text = ProseEnvelope.model_validate_json(response.content, strict=True).text
                if not text.strip():
                    return StoryFailureCode.OUTPUT_INVALID, "empty prose", ""
                return None, "", text
            assert request.response_model is not None
            request.response_model.model_validate_json(response.content, strict=True)
        except ValidationError as exc:
            return StoryFailureCode.OUTPUT_INVALID, f"{exc.error_count()} schema errors", ""
        return None, "", response.content
