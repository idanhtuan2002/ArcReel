"""SSE stream for the M7-A execution/attempt/candidate/master/usage event
table (M7-C Task C1). Distinct from ``server.routers.project_events``
(filesystem watch/diff broadcasting); see
``server.services.execution_events`` for why the two share the "project
events" name without being the same system.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from lib.db.base import DEFAULT_USER_ID
from server.services.execution_events import DurableEventStreamService

logger = logging.getLogger(__name__)

router = APIRouter()

EXECUTION_EVENTS_SSE_IDLE_SECONDS = 15.0


def get_execution_event_stream_service(request: Request) -> DurableEventStreamService:
    return request.app.state.execution_event_stream_service


@router.get(
    "/projects/{project_name}/execution-events/stream",
    response_class=EventSourceResponse,
)
async def stream_execution_events(
    project_name: str,
    request: Request,
    cursor: int | None = Query(default=None, ge=0),
) -> AsyncIterator[ServerSentEvent]:
    # A negative cursor is rejected by FastAPI's own Query(ge=0) validation
    # (HTTP 422) before this body runs; there is no separate domain error to
    # raise here.
    service = get_execution_event_stream_service(request)
    async with service.stream(
        user_id=DEFAULT_USER_ID,
        project_name=project_name,
        cursor=cursor,
        idle_timeout=EXECUTION_EVENTS_SSE_IDLE_SECONDS,
    ) as stream:
        async for event in stream:
            if await request.is_disconnected():
                break
            if event is None:
                yield ServerSentEvent(event="_idle", data="{}")
                continue
            yield ServerSentEvent(
                event=event.event_type.value,
                id=str(event.event_id),
                data=event.model_dump_json(),
            )
