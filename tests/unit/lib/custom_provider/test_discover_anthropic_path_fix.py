"""回归：_discover_anthropic 在 base_url 带 anthropic 子路径时也走根 + /v1/models。"""

from __future__ import annotations

import httpx
import pytest

from lib.artifact_download_guard import ArtifactDestinationRejectedError
from tests.http_capture import capture_http, only_request


@pytest.mark.asyncio
async def test_discover_strips_anthropic_suffix() -> None:
    from lib.custom_provider.discovery import _discover_anthropic

    with capture_http() as router:
        route = router.get("https://api.deepseek.com/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "claude-x", "display_name": "X"}]})
        )
        models = await _discover_anthropic("https://api.deepseek.com/anthropic", "sk")

    only_request(route)
    assert models[0]["model_id"] == "claude-x"


@pytest.mark.asyncio
async def test_discover_keeps_root_when_no_suffix() -> None:
    from lib.custom_provider.discovery import _discover_anthropic

    with capture_http() as router:
        route = router.get("https://api.anthropic.com/v1/models").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        await _discover_anthropic("https://api.anthropic.com", "sk")

    only_request(route)


@pytest.mark.asyncio
async def test_discover_retries_with_bearer_after_401() -> None:
    """只认 Authorization 的网关（火山方舟）：x-api-key 拿 401 后换 Bearer 重试。"""
    from lib.custom_provider.discovery import _discover_anthropic

    with capture_http() as router:
        route = router.get("https://ark.cn-beijing.volces.com/v1/models").mock(
            side_effect=[
                httpx.Response(401, text="unauthorized"),
                httpx.Response(200, json={"data": [{"id": "doubao-seed-evolving"}]}),
            ]
        )
        models = await _discover_anthropic("https://ark.cn-beijing.volces.com/api/plan", "sk")

    assert [m["model_id"] for m in models] == ["doubao-seed-evolving"]
    assert route.call_count == 2
    assert route.calls[0].request.headers["x-api-key"] == "sk"
    assert route.calls[1].request.headers["authorization"] == "Bearer sk"
    assert "x-api-key" not in route.calls[1].request.headers


@pytest.mark.asyncio
async def test_discover_refuses_a_link_local_base_url() -> None:
    """模型发现与产物下载同一道出站目的地校验：链路本地 / 云元数据地址不发请求。"""
    from lib.custom_provider.discovery import _discover_anthropic

    with capture_http() as router:
        route = router.get("http://169.254.169.254/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
        with pytest.raises(ArtifactDestinationRejectedError):
            await _discover_anthropic("http://169.254.169.254", "sk")

    assert route.call_count == 0
