"""should_retry_paid_sdk_submit：付费 SDK 提交只在「确定未送达」或供应商明示可重试时重发。"""

from __future__ import annotations

import grpc
import httpx
import openai
import pytest
from google.genai import errors as genai_errors
from grpc.aio import AioRpcError, Metadata

from lib.retry import NonRetryableError
from lib.video_backends.base import should_retry_paid_sdk_submit

_REQUEST = httpx.Request("POST", "https://provider.example/v1/generate")


def _raised_from(outer: Exception, cause: BaseException) -> Exception:
    try:
        try:
            raise cause
        except BaseException as inner:
            raise outer from inner
    except Exception as exc:
        return exc


def _openai_status(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    return cls("provider says no", response=httpx.Response(status, request=_REQUEST), body=None)


def _grpc(code: grpc.StatusCode) -> AioRpcError:
    return AioRpcError(code, Metadata(), Metadata(), details="rpc failed")


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        # 连接期失败：请求确定未送达，重发不会重复扣费
        pytest.param(httpx.ConnectError("refused", request=_REQUEST), True, id="httpx-connect-error"),
        pytest.param(
            _raised_from(openai.APITimeoutError(request=_REQUEST), httpx.ConnectTimeout("connect", request=_REQUEST)),
            True,
            id="sdk-timeout-during-connect",
        ),
        pytest.param(
            _raised_from(openai.APIConnectionError(request=_REQUEST), httpx.ConnectError("dns", request=_REQUEST)),
            True,
            id="sdk-connection-error-before-send",
        ),
        # 供应商明示的状态
        pytest.param(_openai_status(openai.RateLimitError, 429), True, id="openai-429"),
        pytest.param(_openai_status(openai.InternalServerError, 503), True, id="openai-503"),
        pytest.param(_openai_status(openai.BadRequestError, 400), False, id="openai-400"),
        pytest.param(genai_errors.ServerError(503, {"error": {"code": 503}}), True, id="genai-503"),
        pytest.param(genai_errors.ClientError(400, {"error": {"code": 400}}), False, id="genai-400"),
        pytest.param(_grpc(grpc.StatusCode.RESOURCE_EXHAUSTED), True, id="grpc-resource-exhausted"),
        # 歧义态：请求可能已被处理，不自动重发
        pytest.param(httpx.ReadTimeout("read", request=_REQUEST), False, id="httpx-read-timeout"),
        pytest.param(
            _raised_from(openai.APITimeoutError(request=_REQUEST), httpx.ReadTimeout("read", request=_REQUEST)),
            False,
            id="sdk-timeout-after-send",
        ),
        pytest.param(
            _raised_from(
                openai.APIConnectionError(request=_REQUEST),
                httpx.RemoteProtocolError("peer closed", request=_REQUEST),
            ),
            False,
            id="sdk-connection-dropped-mid-request",
        ),
        pytest.param(_grpc(grpc.StatusCode.UNAVAILABLE), False, id="grpc-unavailable"),
        pytest.param(_grpc(grpc.StatusCode.DEADLINE_EXCEEDED), False, id="grpc-deadline"),
        pytest.param(TimeoutError("timed out"), False, id="bare-timeout"),
        # 不按报文子串兜底：消息里带 "503" 的业务异常不是瞬态错误
        pytest.param(RuntimeError("upstream said 503 timeout"), False, id="message-digits"),
        pytest.param(NonRetryableError("destination rejected"), False, id="non-retryable"),
    ],
)
def test_paid_sdk_submit_retries_only_unsent_or_provider_declared_failures(exc: Exception, expected: bool) -> None:
    assert should_retry_paid_sdk_submit(exc) is expected


def test_every_provider_retry_decorator_names_a_reviewed_predicate() -> None:
    """付费提交不得靠缺省的字符串/超时兜底重试：每个供应商代码里的 ``@with_retry_async`` 都要显式
    ``retry_if=`` 一个审过的谓词。提交用 should_retry_submit / should_retry_paid_sdk_submit，轮询取件用
    should_retry_poll（幂等 GET）。"""
    import ast
    from pathlib import Path

    lib_root = Path(__file__).resolve().parents[4] / "lib"
    scanned = [
        *lib_root.glob("image_backends/*.py"),
        *lib_root.glob("video_backends/*.py"),
        *lib_root.glob("text_backends/*.py"),
        *lib_root.glob("audio_backends/*.py"),
        *lib_root.glob("custom_provider/**/*.py"),
        lib_root / "kling_backend_base.py",
    ]
    reviewed = {"should_retry_submit", "should_retry_paid_sdk_submit", "should_retry_poll"}
    # 写库而非调供应商：job id / api_call id 落库的 DB 瞬态重试
    database_retries = {"_persist_with_retry", "_persist_api_call_id_with_retry"}
    offenders = []
    for path in scanned:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name in database_retries:
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and getattr(decorator.func, "id", None) == "with_retry_async"):
                    continue
                predicate = next((k.value for k in decorator.keywords if k.arg == "retry_if"), None)
                if not (isinstance(predicate, ast.Name) and predicate.id in reviewed):
                    offenders.append(f"{path.relative_to(lib_root)}:{node.name}")
    assert offenders == []
