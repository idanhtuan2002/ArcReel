"""M7-C Task D4: periodic host-hardening recovery scan.

Runs ``ExecutionAttemptServiceImpl.reconcile_expired`` (H5: a worker that died
mid-``SUBMITTING`` leaves a lease that will expire and never be renewed) and
``realize_pending_cancels`` (a fresh ``CANCEL_REQUESTED`` intent nothing has
attempted against the provider yet) on a fixed interval, independent of
:class:`lib.generation_worker.GenerationWorker`: these scans only ever touch
``execution_attempts``, never the legacy ``tasks`` table, so there is no
shared state to coordinate and no reason to couple their lifecycle to the
worker's own start/stop.

Every currently registered capability profile declares ``idempotency_mode:
NONE`` and ``supports_cancel: false`` (``r2/provider_capabilities/registry.json``),
so ``reconcile()``'s qualified-lookup path never reaches an adapter at all
today, and a real ``cancel()`` would fail exactly like the safe fallback
adapter already does. Scheduling with an empty adapter registry
(``default_to_unsupported=True``) is therefore behaviorally identical to
having a fully wired adapter for everything currently registered, not a
shortcut -- see ``docs/research/2026-09-20-r2-m7c-poll-download-cancel-design.md``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from lib.db import safe_session_factory
from server.services.execution_attempts import AdapterRegistry, build_execution_attempt_service

logger = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL_SECONDS = 60.0


class ExecutionRecoveryScheduler:
    def __init__(
        self,
        *,
        session_factory=safe_session_factory,
        adapter_registry: AdapterRegistry | None = None,
        interval_seconds: float = DEFAULT_SCAN_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._adapter_registry: AdapterRegistry = adapter_registry if adapter_registry is not None else {}
        self._interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="host-hardening-recovery-scan")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.scan_once()
            except Exception:
                logger.exception("host-hardening recovery scan failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)

    async def scan_once(self) -> None:
        async with self._session_factory() as session:
            service = build_execution_attempt_service(
                session,
                adapter_registry=self._adapter_registry,
                default_to_unsupported=True,
            )
            expired = await service.reconcile_expired()
            cancels = await service.realize_pending_cancels()
            if expired or cancels:
                logger.info(
                    "host-hardening recovery scan: reconciled=%d realized_cancels=%d",
                    len(expired),
                    len(cancels),
                )


__all__ = ["DEFAULT_SCAN_INTERVAL_SECONDS", "ExecutionRecoveryScheduler"]
