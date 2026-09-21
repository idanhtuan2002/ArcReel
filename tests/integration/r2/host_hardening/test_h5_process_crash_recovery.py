"""M7-C Task D5: real SIGKILL recovery tests.

Every other H5 test in this repo simulates "the worker died" by directly
manipulating a repository in-process (an already-expired lease constructed by
hand). This file instead spawns a real, separate OS process
(``_crash_worker.py``) that durably commits an attempt to a specific state
and then blocks forever, SIGKILLs it -- the only way to prove a process death
mid-flight, not a simulation of one -- and verifies the H5 recovery scan
(``ExecutionAttemptServiceImpl.reconcile_expired`` /
``realize_pending_cancels``, run from this test process, i.e. a different,
live process) resolves the durable state left behind exactly as the
in-process tests already prove it should.

Uses a real, file-backed SQLite database (not ``:memory:``, which cannot be
shared across processes) so both the killed worker and this test process see
the same durable state. No real network call, no real provider, no real
money at risk -- the worker only ever reaches PLANNED/SUBMITTING or
ACCEPTED/CANCEL_REQUESTED against a fake Kling route.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from r2.contracts.host_hardening import ExecutionAttemptState
from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile
from server.services.execution_attempts import build_execution_attempt_service

type Factory = async_sessionmaker[AsyncSession]

USER = "u1"
PROJECT = "demo"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_WORKER_SENTINEL_TIMEOUT_SECONDS = 15.0
_WORKER_POLL_INTERVAL_SECONDS = 0.05


def _capability_resolver(ref: str):
    return load_capability_profile(ref, registry_path=DEFAULT_REGISTRY_PATH)


def _repo(session: AsyncSession) -> ExecutionAttemptRepository:
    return ExecutionAttemptRepository(session, capability_resolver=_capability_resolver)


def _spawn_crash_worker(
    *, db_url: str, execution_id: str, task_id: str, target_state: str, sentinel_path: Path
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.integration.r2.host_hardening._crash_worker",
            db_url,
            execution_id,
            task_id,
            target_state,
            str(sentinel_path),
        ],
        cwd=_REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _wait_for_sentinel(sentinel_path: Path, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + _WORKER_SENTINEL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if sentinel_path.exists():
            return
        if proc.poll() is not None:
            output = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
            raise AssertionError(f"crash worker exited early (code={proc.returncode}):\n{output}")
        time.sleep(_WORKER_POLL_INTERVAL_SECONDS)
    proc.kill()
    raise AssertionError("crash worker never reached its target state in time")


def _sigkill_and_reap(proc: subprocess.Popen[bytes]) -> None:
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10.0)
    assert proc.returncode is not None
    assert proc.returncode != 0  # a real, hard kill -- never a clean exit


@pytest.fixture
async def crash_db(file_session_factory: Factory) -> tuple[str, Factory]:
    # file_session_factory is always a real, file-backed SQLite database
    # regardless of DATABASE_URL (never :memory:, which cannot be shared
    # across processes) -- exactly what a real, separate OS process needs to
    # see the same durable state as this test.
    async with file_session_factory() as session:
        db_url = str(session.get_bind().url)
    return db_url, file_session_factory


@pytest.mark.sqlite_only
async def test_sigkill_mid_submitting_is_recovered_to_needs_operator(
    crash_db: tuple[str, Factory],
) -> None:
    db_url, session_factory = crash_db
    sentinel = _rel_tmp_sentinel(db_url)
    proc = _spawn_crash_worker(
        db_url=db_url,
        execution_id="exec-crash-1",
        task_id="task-crash-1",
        target_state="SUBMITTING",
        sentinel_path=sentinel,
    )
    try:
        _wait_for_sentinel(sentinel, proc)
        async with session_factory() as session:
            mid_flight = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-crash-1")
        assert mid_flight is not None
        assert mid_flight.state is ExecutionAttemptState.SUBMITTING
        assert mid_flight.lease_owner == "crash-worker"

        _sigkill_and_reap(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    # The worker's lease TTL is 2s; give real wall-clock time to actually
    # pass it -- reconcile_expired checks the real lease_expires_at, not a
    # caller-supplied "pretend now".
    await asyncio.sleep(2.5)

    async with session_factory() as session:
        service = build_execution_attempt_service(session, adapter_registry={}, default_to_unsupported=True)
        results = await service.reconcile_expired()

    assert len(results) == 1
    assert results[0].execution_id == "exec-crash-1"
    assert results[0].state is ExecutionAttemptState.NEEDS_OPERATOR

    async with session_factory() as session:
        durable = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-crash-1")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.NEEDS_OPERATOR
    assert durable.lease_owner != "crash-worker"


@pytest.mark.sqlite_only
async def test_sigkill_right_after_cancel_request_leaves_intent_intact(
    crash_db: tuple[str, Factory],
) -> None:
    db_url, session_factory = crash_db
    sentinel = _rel_tmp_sentinel(db_url)
    proc = _spawn_crash_worker(
        db_url=db_url,
        execution_id="exec-crash-2",
        task_id="task-crash-2",
        target_state="ACCEPTED_CANCEL_REQUESTED",
        sentinel_path=sentinel,
    )
    try:
        _wait_for_sentinel(sentinel, proc)
        async with session_factory() as session:
            mid_flight = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-crash-2")
        assert mid_flight is not None
        assert mid_flight.state is ExecutionAttemptState.CANCEL_REQUESTED

        _sigkill_and_reap(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    async with session_factory() as session:
        service = build_execution_attempt_service(session, adapter_registry={}, default_to_unsupported=True)
        # Kling declares supports_cancel: false, so the fallback adapter's
        # cancel() fails the same way a real one would -- the crash must not
        # have lost, nor falsely resolved, the recorded cancel intent.
        results = await service.realize_pending_cancels()

    assert results == []
    async with session_factory() as session:
        durable = await _repo(session).get_exact(user_id=USER, project_name=PROJECT, execution_id="exec-crash-2")
    assert durable is not None
    assert durable.state is ExecutionAttemptState.CANCEL_REQUESTED


def _rel_tmp_sentinel(db_url: str) -> Path:
    # sqlite+aiosqlite:///<abs path>/crash.db -> sibling sentinel file in the
    # same tmp_path, unique per test since crash_db is function-scoped.
    db_path = Path(db_url.removeprefix("sqlite+aiosqlite:///"))
    return db_path.parent / f"sentinel-{db_path.stem}"
