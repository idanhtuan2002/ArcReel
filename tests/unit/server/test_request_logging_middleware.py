"""验证 request_logging_middleware 对高频轮询接口的静默策略。"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from server.app import request_logging_middleware

_ACCESS_LOG_FMT = "%s %s %d %.0fms"


def _access_log_records(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [r for r in records if r.name == "server.app" and r.msg == _ACCESS_LOG_FMT]


def _build_app_with_ok_routes() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(request_logging_middleware)

    # 以下路由桩由装饰器就地注册，函数体内无其它引用；basedpyright 把函数作用域内的符号一律
    # 判为私有，逐个标注的 reportUnusedFunction 均为工具误报。
    @app.get("/api/v1/tasks")
    async def _tasks() -> dict:  # pyright: ignore[reportUnusedFunction]
        return {"tasks": []}

    @app.get("/api/v1/tasks/stats")
    async def _tasks_stats() -> dict:  # pyright: ignore[reportUnusedFunction]
        return {"stats": {}}

    @app.get("/api/v1/projects")
    async def _projects() -> dict:  # pyright: ignore[reportUnusedFunction]
        return {"projects": []}

    return app


@pytest.mark.asyncio
async def test_quiet_endpoint_fast_200_is_debug(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="server.app")
    app = _build_app_with_ok_routes()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp_list = await client.get("/api/v1/tasks")
        resp_stats = await client.get("/api/v1/tasks/stats")

    assert resp_list.status_code == 200
    assert resp_stats.status_code == 200

    records = _access_log_records(caplog.records)
    assert len(records) == 2
    assert all(r.levelno == logging.DEBUG for r in records)


@pytest.mark.asyncio
async def test_quiet_endpoint_5xx_still_info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="server.app")
    app = FastAPI()
    app.middleware("http")(request_logging_middleware)

    # 以下路由桩由装饰器就地注册，函数体内无其它引用；basedpyright 把函数作用域内的符号一律
    # 判为私有，逐个标注的 reportUnusedFunction 均为工具误报。
    @app.get("/api/v1/tasks")
    async def _tasks_error() -> dict:  # pyright: ignore[reportUnusedFunction]
        raise HTTPException(status_code=500, detail="boom")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/tasks")

    assert resp.status_code == 500
    records = _access_log_records(caplog.records)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO


@pytest.mark.asyncio
async def test_non_quiet_endpoint_200_still_info(caplog: pytest.LogCaptureFixture) -> None:
    """回归保护：非静默路径的行为不变。"""
    caplog.set_level(logging.DEBUG, logger="server.app")
    app = _build_app_with_ok_routes()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/projects")

    assert resp.status_code == 200
    records = _access_log_records(caplog.records)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO


def _build_app_with_request_id_probe() -> FastAPI:
    from lib.request_context import current_request_id
    from server.app import request_id_middleware

    app = FastAPI()
    app.middleware("http")(request_id_middleware)

    @app.get("/probe")
    async def _probe() -> dict:  # pyright: ignore[reportUnusedFunction]
        return {"request_id": current_request_id()}

    return app


@pytest.mark.asyncio
async def test_request_id_middleware_binds_and_echoes_a_minted_id() -> None:
    app = _build_app_with_request_id_probe()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/probe")

    minted = resp.headers["X-Request-ID"]
    assert minted.startswith("req_")
    assert resp.json() == {"request_id": minted}


@pytest.mark.asyncio
async def test_request_id_middleware_reuses_well_formed_caller_id_and_replaces_malformed() -> None:
    app = _build_app_with_request_id_probe()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reused = await client.get("/probe", headers={"X-Request-ID": "4bf92f3577b34da6a3ce929d0e0e4736"})
        replaced = await client.get("/probe", headers={"X-Request-ID": "Bearer sk-live-secret"})

    assert reused.headers["X-Request-ID"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert reused.json() == {"request_id": "4bf92f3577b34da6a3ce929d0e0e4736"}
    assert replaced.headers["X-Request-ID"] != "Bearer sk-live-secret"
    assert replaced.json() == {"request_id": replaced.headers["X-Request-ID"]}
