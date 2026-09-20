from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from r2.contracts.host_hardening import DurableProjectEvent, ProjectEventType
from server.routers import execution_events as execution_events_router

NOW = "2026-09-20T12:00:00Z"


class _FakeRequest:
    def __init__(self, app, *, disconnect_after: int | None = None):
        self.app = app
        self._disconnect_after = disconnect_after
        self._calls = 0

    async def is_disconnected(self):
        self._calls += 1
        if self._disconnect_after is None:
            return False
        return self._calls > self._disconnect_after


def _event(event_id: int) -> DurableProjectEvent:
    return DurableProjectEvent(
        event_id=event_id,
        user_id="default",
        project_name="demo",
        event_type=ProjectEventType.MASTER_PROMOTED,
        public_payload={"master_version": event_id},
        payload_schema_version=1,
        dedupe_key=f"master:videos/E1S01:{event_id}",
    )


class _FakeStreamService:
    def __init__(self, items: list[DurableProjectEvent | None]) -> None:
        self._items = items
        self.captured_kwargs: dict[str, object] | None = None

    @contextlib.asynccontextmanager
    async def stream(self, *, user_id: str, project_name: str, cursor: int | None, idle_timeout: float):
        self.captured_kwargs = {
            "user_id": user_id,
            "project_name": project_name,
            "cursor": cursor,
            "idle_timeout": idle_timeout,
        }

        async def _iter():
            for item in self._items:
                yield item

        yield _iter()


async def test_stream_execution_events_emits_a_named_event_per_row():
    service = _FakeStreamService([_event(1), _event(2)])
    app = SimpleNamespace(state=SimpleNamespace(execution_event_stream_service=service))
    request = _FakeRequest(app)

    stream = execution_events_router.stream_execution_events("demo", request, cursor=None)

    first = await anext(stream)
    second = await anext(stream)
    await stream.aclose()

    assert first.event == "MASTER_PROMOTED"
    assert first.id == "1"
    assert second.id == "2"
    assert service.captured_kwargs == {
        "user_id": "default",
        "project_name": "demo",
        "cursor": None,
        "idle_timeout": execution_events_router.EXECUTION_EVENTS_SSE_IDLE_SECONDS,
    }


async def test_stream_execution_events_passes_the_cursor_through():
    service = _FakeStreamService([_event(5)])
    app = SimpleNamespace(state=SimpleNamespace(execution_event_stream_service=service))
    request = _FakeRequest(app)

    stream = execution_events_router.stream_execution_events("demo", request, cursor=3)
    await anext(stream)
    await stream.aclose()

    assert service.captured_kwargs is not None
    assert service.captured_kwargs["cursor"] == 3


async def test_stream_execution_events_maps_idle_heartbeats():
    service = _FakeStreamService([None, _event(1)])
    app = SimpleNamespace(state=SimpleNamespace(execution_event_stream_service=service))
    request = _FakeRequest(app)

    stream = execution_events_router.stream_execution_events("demo", request, cursor=None)
    idle = await anext(stream)
    real = await anext(stream)
    await stream.aclose()

    assert idle.event == "_idle"
    assert real.event == "MASTER_PROMOTED"


async def test_stream_execution_events_stops_on_client_disconnect():
    service = _FakeStreamService([_event(1), _event(2), _event(3)])
    app = SimpleNamespace(state=SimpleNamespace(execution_event_stream_service=service))
    request = _FakeRequest(app, disconnect_after=1)

    stream = execution_events_router.stream_execution_events("demo", request, cursor=None)
    await anext(stream)

    with pytest.raises(StopAsyncIteration):
        await anext(stream)
