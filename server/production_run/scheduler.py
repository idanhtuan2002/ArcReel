"""Periodic database scan that claims due production runs and ticks them.

The database is the recovery path: task events may only ``wake()`` an earlier scan. Stopping the scheduler
leaves every logical run durable; a lease left by a stopped or crashed host expires and is claimed again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_runs import ProductionRunConflict, ProductionRunRepository
from server.production_run.controller import ProductionController

logger = logging.getLogger(__name__)


class ProductionScheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        controller: ProductionController,
        *,
        owner_id: str,
        lease_seconds: int = 120,
        interval_seconds: float = 15.0,
        max_runs_per_scan: int = 16,
    ) -> None:
        self._sessions = sessions
        self._controller = controller
        self._owner_id = owner_id
        self._lease_seconds = lease_seconds
        self._interval_seconds = interval_seconds
        self._max_runs_per_scan = max_runs_per_scan
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def scan_once(self) -> int:
        """Claim and tick due runs; returns how many runs this scan claimed."""
        claimed = 0
        while claimed < self._max_runs_per_scan:
            async with self._sessions() as session, session.begin():
                run = await ProductionRunRepository(session).claim_due(
                    owner_id=self._owner_id, lease_seconds=self._lease_seconds
                )
            if run is None:
                break
            claimed += 1
            try:
                await self._controller.tick(run_id=run.run_id, owner_id=self._owner_id)
            except ProductionRunConflict as error:
                logger.info("production run %s tick ended: %s", run.run_id, error)
            except Exception:
                # The lease expires and a later scan replays the run from its durable intent.
                logger.exception("production run %s tick failed", run.run_id)
        return claimed

    def wake(self) -> None:
        self._wake_event.set()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="production-run-scan")

    async def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            self._wake_event.clear()
            try:
                await self.scan_once()
            except Exception:
                logger.exception("production run scan failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake_event.wait(), timeout=self._interval_seconds)


__all__ = ["ProductionScheduler"]
