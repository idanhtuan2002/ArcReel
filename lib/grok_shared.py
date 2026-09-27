"""
Grok (xAI) 共享工具模块

供 text_backends / image_backends / video_backends 复用。

包含：
- create_grok_client — xAI AsyncClient 客户端工厂
- grok_should_retry — gRPC 感知的重试谓词
"""

from __future__ import annotations

import json

from lib.retry import BASE_RETRYABLE_ERRORS, _should_retry

# gRPC 瞬态状态码（等价于 HTTP 429/500/502/503/504）
_GRPC_RETRYABLE_CODES: set | None = None

try:
    import grpc

    _GRPC_RETRYABLE_CODES = {
        grpc.StatusCode.UNAVAILABLE,  # 503 — 连接中断 / Socket closed
        grpc.StatusCode.DEADLINE_EXCEEDED,  # 504 — 超时
        grpc.StatusCode.RESOURCE_EXHAUSTED,  # 429 — 限流
        grpc.StatusCode.ABORTED,  # 冲突重试
    }
except ImportError:
    pass  # grpc is optional; fall back to pattern-based retry below


def grok_should_retry(exc: Exception) -> bool:
    """Grok 专用重试谓词：精确匹配 gRPC 瞬态状态码，其余回退默认模式匹配。"""
    if _GRPC_RETRYABLE_CODES is not None:
        try:
            from grpc.aio import AioRpcError

            if isinstance(exc, AioRpcError):
                return exc.code() in _GRPC_RETRYABLE_CODES
        except ImportError:
            pass  # grpc available at module level but aio submodule missing; fall through
    return _should_retry(exc, BASE_RETRYABLE_ERRORS)


def resolve_grok_api_key(api_key: str | None = None) -> str:
    if api_key is None or not api_key.strip():
        raise ValueError("请到系统配置页填写 xAI API Key")
    return api_key.strip()


#: 关掉 xai_sdk 缺省的 gRPC 自动重试（缺省 service config 对 UNAVAILABLE 重发至多 5 次）：连接在响应头
#: 之前断开也报 UNAVAILABLE，请求可能已被受理并扣费。付费提交是否重发只由调用方谓词决定（ADR-0078）。
GROK_CHANNEL_OPTIONS: list[tuple[str, object]] = [
    ("grpc.enable_retries", 0),
    ("grpc.service_config", json.dumps({"methodConfig": [{"name": [{}]}]})),
]


def create_grok_client(*, api_key: str | None = None):
    """创建 xAI AsyncClient，统一校验和构造；SDK 内置的自动重发被关闭。"""
    import xai_sdk

    return xai_sdk.AsyncClient(api_key=resolve_grok_api_key(api_key), channel_options=list(GROK_CHANNEL_OPTIONS))
