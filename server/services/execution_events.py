"""Durable SSE fanout for the M7-A execution/attempt/candidate/master/usage
event table (M7-C Task C1).

Distinct from :mod:`server.services.project_events` (filesystem watch/diff
broadcasting on ``/projects/{name}/events/stream``): that is a pre-existing,
unrelated, already-live system that happens to share the "project events"
name. This service is a durable replay over ``project_events`` (spec section
7); the in-memory :class:`~server.sse_channel.SseChannel` here is only a
wake-up hint, never the source of truth -- ``notify`` may be skipped, dropped,
duplicated or arrive before or after the row it announces is durable, and the
stream always converges to the true state by re-querying the database.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from lib.db.engine import safe_session_factory
from lib.db.repositories.host_hardening import ProjectEventRepository
from r2.contracts.host_hardening import DurableProjectEvent
from server.sse_channel import IDLE, DropSubscriber, SseChannel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

DURABLE_EVENT_REPLAY_LIMIT = 500


class DurableEventStreamService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] = safe_session_factory,
        replay_limit: int = DURABLE_EVENT_REPLAY_LIMIT,
    ) -> None:
        self._session_factory = session_factory
        self._replay_limit = replay_limit
        self._channels: dict[tuple[str, str], SseChannel] = {}

    def notify(self, *, user_id: str, project_name: str) -> None:
        """Wake up any subscriber for this scope. Safe to call with none
        subscribed (a no-op); safe to call more than once for one durable
        write (the stream drains the same durable rows either way)."""

        channel = self._channels.get((user_id, project_name))
        if channel is not None:
            channel.broadcast(None)

    def _channel_for(self, user_id: str, project_name: str) -> SseChannel:
        key = (user_id, project_name)
        channel = self._channels.get(key)
        if channel is None:
            channel = SseChannel(
                overflow=DropSubscriber(),
                on_last_subscriber=lambda: self._forget_if_idle(key),
            )
            self._channels[key] = channel
        return channel

    async def _forget_if_idle(self, key: tuple[str, str]) -> None:
        channel = self._channels.get(key)
        if channel is not None and not channel.has_subscribers:
            del self._channels[key]

    async def _drain(
        self, *, user_id: str, project_name: str, cursor: int | None
    ) -> tuple[list[DurableProjectEvent], int | None]:
        async with self._session_factory() as session:
            events = await ProjectEventRepository(session).replay_after(
                user_id=user_id, project_name=project_name, cursor=cursor, limit=self._replay_limit
            )
        if events:
            cursor = events[-1].event_id
        return events, cursor

    @contextlib.asynccontextmanager
    async def stream(
        self, *, user_id: str, project_name: str, cursor: int | None, idle_timeout: float = 15.0
    ) -> AsyncGenerator[AsyncIterator[DurableProjectEvent | None]]:
        """Yield an async iterator of durable events after *cursor*, then live
        events as they land, with ``None`` standing in for an idle heartbeat.

        Subscribes to the wake-up channel before the first database drain, so
        a write that lands between subscribing and draining is never missed:
        its ``notify`` call is already queued and the wait loop below re-drains
        immediately instead of idling. Every re-drain reads from the exact
        last event_id yielded, so a duplicate wake-up costs one empty query,
        never a gap or a repeat.
        """

        channel = self._channel_for(user_id, project_name)
        queue = channel.subscribe()

        async def _iter() -> AsyncIterator[DurableProjectEvent | None]:
            nonlocal cursor
            events, cursor = await self._drain(user_id=user_id, project_name=project_name, cursor=cursor)
            for event in events:
                yield event
            async for item in channel.iterate(queue, idle_timeout=idle_timeout):
                if item is IDLE:
                    yield None
                    continue
                events, cursor = await self._drain(user_id=user_id, project_name=project_name, cursor=cursor)
                for event in events:
                    yield event

        try:
            yield _iter()
        finally:
            await channel.unsubscribe(queue)


__all__ = ["DURABLE_EVENT_REPLAY_LIMIT", "DurableEventStreamService"]
