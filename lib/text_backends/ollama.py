"""Ollama 原生 ``/api/chat`` 文本后端。

一次 :meth:`OllamaChatClient.chat` 恰好是一次 HTTP 请求：本层不重试、不降级、不换模型，
重试与预算由调用方显式计数。请求固定 ``stream=false``、``truncate=false``、``shift=false``：
输入超过服务端上下文时，Ollama 返回 HTTP 400 ``exceed_context_size_error`` 并给出精确 token 数，
不会像 ``/v1/chat/completions`` 那样静默截断输入。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from lib.retry import NonRetryableError
from lib.text_backends.base import (
    StructuredOutputExhaustedError,
    TextCapability,
    TextGenerationRequest,
    TextGenerationResult,
    check_truncation,
    resolve_schema,
    summarize_validation_error,
)

logger = logging.getLogger(__name__)

OLLAMA_CHAT_PATH = "/api/chat"
PROVIDER_OLLAMA = "ollama"
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=1800.0, write=60.0, pool=10.0)

_OVER_CONTEXT_MESSAGE = re.compile(r"request \((\d+) tokens\) exceeds the available context size \((\d+) tokens\)")


class OllamaError(NonRetryableError):
    """Ollama 调用失败的基类；均不可由本层重试。"""


class OllamaUnavailableError(OllamaError):
    """连接不上服务端：请求未送达，未产生任何生成。"""


class OllamaOutcomeUnknownError(OllamaError):
    """请求已发出但未拿到完整响应（读超时、连接中断）：服务端可能仍在生成。"""


class OllamaOverContextError(OllamaError):
    """输入超过服务端上下文；``prompt_tokens`` 是服务端给出的精确输入 token 数。"""

    def __init__(self, *, prompt_tokens: int, context_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.context_tokens = context_tokens
        super().__init__(f"输入 {prompt_tokens} tokens 超过服务端上下文 {context_tokens} tokens")


class OllamaHTTPError(OllamaError):
    def __init__(self, *, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Ollama HTTP {status_code}: {message}")


class OllamaProtocolError(OllamaError):
    """HTTP 200 但响应不是预期形态（非 JSON、缺字段、类型不符）。"""


@dataclass(frozen=True)
class OllamaChatRequest:
    model: str
    messages: tuple[tuple[str, str], ...]
    num_ctx: int
    num_predict: int
    format: Mapping[str, Any] | None = None
    options: Mapping[str, Any] = field(default_factory=dict)
    keep_alive: str | None = None

    def payload(self) -> dict[str, Any]:
        """发往 ``/api/chat`` 的完整请求体；同一请求对象的字节恒定，可做请求摘要。"""
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "think": False,
            "truncate": False,
            "shift": False,
            "messages": [{"role": role, "content": content} for role, content in self.messages],
            "options": {**self.options, "num_ctx": self.num_ctx, "num_predict": self.num_predict},
        }
        if self.format is not None:
            body["format"] = dict(self.format)
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        return body


@dataclass(frozen=True)
class OllamaChatResponse:
    model: str
    content: str
    done: bool
    done_reason: str | None
    prompt_eval_count: int | None
    eval_count: int | None
    total_duration_ns: int | None
    prompt_eval_duration_ns: int | None
    eval_duration_ns: int | None


def normalize_ollama_base_url(url: str) -> str:
    """去掉末尾 ``/`` 与 OpenAI 兼容路径 ``/v1``：同一个 Ollama 服务常以兼容地址登记。"""
    stripped = url.strip().rstrip("/")
    if stripped.endswith("/v1"):
        stripped = stripped[: -len("/v1")]
    return stripped


class OllamaChatClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = normalize_ollama_base_url(base_url) + OLLAMA_CHAT_PATH
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._timeout = timeout
        self._transport = transport

    async def chat(self, request: OllamaChatRequest) -> OllamaChatResponse:
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            try:
                response = await client.post(self._url, json=request.payload(), headers=self._headers)
            except httpx.ConnectError as exc:
                raise OllamaUnavailableError(f"无法连接 Ollama：{type(exc).__name__}") from exc
            except httpx.ConnectTimeout as exc:
                raise OllamaUnavailableError("连接 Ollama 超时") from exc
            except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError, httpx.ReadError) as exc:
                raise OllamaOutcomeUnknownError(f"请求已发出但响应不完整：{type(exc).__name__}") from exc
        if response.status_code != 200:
            raise _http_error(response)
        return _parse_response(response.content)


def _http_error(response: httpx.Response) -> OllamaError:
    message = response.text
    try:
        outer = response.json()
        message = str(outer.get("error", message))
        inner = json.loads(message)
        detail = inner.get("error", {})
        if detail.get("type") == "exceed_context_size_error":
            return OllamaOverContextError(
                prompt_tokens=int(detail["n_prompt_tokens"]), context_tokens=int(detail["n_ctx"])
            )
    except (ValueError, TypeError, KeyError, AttributeError):
        pass
    match = _OVER_CONTEXT_MESSAGE.search(message)
    if response.status_code == 400 and match:
        return OllamaOverContextError(prompt_tokens=int(match.group(1)), context_tokens=int(match.group(2)))
    return OllamaHTTPError(status_code=response.status_code, message=message[:300])


def _parse_response(raw: bytes) -> OllamaChatResponse:
    try:
        data = json.loads(raw)
        message = data["message"]
        content = message["content"]
        done = data["done"]
    except (ValueError, TypeError, KeyError) as exc:
        raise OllamaProtocolError(f"响应缺少必需字段：{type(exc).__name__}") from exc
    if not isinstance(content, str) or not isinstance(done, bool):
        raise OllamaProtocolError("响应字段类型不符：message.content 须为字符串、done 须为布尔")
    return OllamaChatResponse(
        model=str(data.get("model", "")),
        content=content,
        done=done,
        done_reason=_optional_str(data.get("done_reason")),
        prompt_eval_count=_optional_int(data.get("prompt_eval_count")),
        eval_count=_optional_int(data.get("eval_count")),
        total_duration_ns=_optional_int(data.get("total_duration")),
        prompt_eval_duration_ns=_optional_int(data.get("prompt_eval_duration")),
        eval_duration_ns=_optional_int(data.get("eval_duration")),
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


class OllamaChatTextBackend:
    """通用 ``TextBackend`` 适配：结构化输出用服务端 grammar（``format``）约束，不做 Instructor 降级。"""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        num_ctx: int = 32768,
        default_max_output_tokens: int = 4096,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = OllamaChatClient(base_url=base_url, api_key=api_key, transport=transport)
        self._model = model
        self._num_ctx = num_ctx
        self._default_max_output_tokens = default_max_output_tokens

    @property
    def name(self) -> str:
        return PROVIDER_OLLAMA

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[TextCapability]:
        return {TextCapability.TEXT_GENERATION, TextCapability.STRUCTURED_OUTPUT}

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        if request.images:
            raise OllamaProtocolError("ollama-chat 端点不接受图片输入")
        messages: list[tuple[str, str]] = []
        if request.system_prompt:
            messages.append(("system", request.system_prompt))
        messages.append(("user", request.prompt))
        schema = resolve_schema(request.response_schema) if request.response_schema else None
        response = await self._client.chat(
            OllamaChatRequest(
                model=self._model,
                messages=tuple(messages),
                num_ctx=self._num_ctx,
                num_predict=request.max_output_tokens or self._default_max_output_tokens,
                format=schema,
            )
        )
        check_truncation(
            response.done_reason,
            provider=PROVIDER_OLLAMA,
            model=self._model,
            structured=request.response_schema is not None,
            output_tokens=response.eval_count,
        )
        if isinstance(request.response_schema, type) and issubclass(request.response_schema, BaseModel):
            try:
                request.response_schema.model_validate_json(response.content)
            except ValidationError as exc:
                raise StructuredOutputExhaustedError(
                    provider=PROVIDER_OLLAMA, model=self._model, reason=summarize_validation_error(exc)
                ) from exc
        return TextGenerationResult(
            text=response.content,
            provider=PROVIDER_OLLAMA,
            model=self._model,
            input_tokens=response.prompt_eval_count,
            output_tokens=response.eval_count,
            finish_reason=response.done_reason,
        )
