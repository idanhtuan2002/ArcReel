"""Standalone process for M7-C's real SIGKILL recovery tests.

Not a pytest module (no ``test_`` prefix): the test spawns this as a real
subprocess via ``subprocess.Popen`` and SIGKILLs it after it reaches a
requested attempt state, to prove the H5 recovery scan survives a genuine
process death, not just an in-process simulated one.

Usage: ``python -m tests.integration.r2.host_hardening._crash_worker <db_url>
<execution_id> <task_id> <target_state> <sentinel_path>``

``target_state`` is one of ``SUBMITTING`` (dies holding the lease right after
entering it, before any provider call would have happened) or
``ACCEPTED_CANCEL_REQUESTED`` (dies immediately after recording a cancel
intent, before anything could act on it). Once the requested durable state is
committed, the sentinel file is written (parent polls for it) and the process
blocks forever until killed -- it never exits on its own.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from r2.contracts.host_hardening import (
    AttemptLeaseFence,
    ExecutionAttemptState,
    PlannedExecutionAttempt,
    ProviderCapabilityProfile,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)

USER = "u1"
PROJECT = "demo"

ROUTE = ProviderRouteSnapshot(
    provider_id="kling",
    provider_account_ref="default",
    provider_model_id="kling-v2-5-turbo",
    backend_model_id="kling-v2-5-turbo",
    endpoint_id="videos.text2video",
    submitted_base_url="https://api-beijing.klingai.com/v1",
    adapter_version="host-video-v1",
    capability_profile_ref="kling-videos-text2video@host-video-v1",
)


def _capability_resolver(ref: str) -> ProviderCapabilityProfile:
    from r2.host_hardening.provider_capabilities import DEFAULT_REGISTRY_PATH, load_capability_profile

    return load_capability_profile(ref, registry_path=DEFAULT_REGISTRY_PATH)


async def _run(db_url: str, execution_id: str, task_id: str, target_state: str, sentinel_path: str) -> None:
    engine = create_async_engine(db_url)
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    async with session_factory() as session:
        repo = ExecutionAttemptRepository(session, capability_resolver=_capability_resolver)
        planned = await repo.plan(
            user_id=USER,
            project_name=PROJECT,
            attempt=PlannedExecutionAttempt(
                execution_id=execution_id,
                task_id=task_id,
                attempt_no=1,
                request_digest="sha256:" + "b" * 64,
                route=ROUTE,
                client_token=execution_id,
                trace_id_at_creation=None,
                created_at=now,
            ),
        )
        leased = await repo.acquire_lease(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=planned.state_version,
            owner="crash-worker",
            expires_at=now + timedelta(seconds=2),
        )
        fence = AttemptLeaseFence(owner="crash-worker", token=leased.lease_token or 0)
        submitting = await repo.transition_worker(
            user_id=USER,
            project_name=PROJECT,
            execution_id=planned.execution_id,
            expected_version=leased.state_version,
            expected_states=frozenset({ExecutionAttemptState.PLANNED}),
            new_state=ExecutionAttemptState.SUBMITTING,
            fence=fence,
        )

        if target_state == "ACCEPTED_CANCEL_REQUESTED":
            accepted = await repo.apply_provider_observation(
                user_id=USER,
                project_name=PROJECT,
                execution_id=planned.execution_id,
                expected_version=submitting.state_version,
                observation=ProviderObservation(
                    observation_id="obs-crash",
                    kind=ProviderObservationKind.ACCEPTED,
                    observed_at=now,
                    provider_sequence=None,
                    provider_job_id="remote-crash",
                    reason_code=None,
                    evidence_digest="sha256:" + "c" * 64,
                ),
            )
            await repo.request_cancel(
                user_id=USER,
                project_name=PROJECT,
                execution_id=planned.execution_id,
                expected_version=accepted.state_version,
                actor_scope="user:alice",
                command_id="crash-cancel",
                command_digest="sha256:" + "1" * 64,
            )
        elif target_state != "SUBMITTING":
            raise ValueError(f"unknown target_state {target_state!r}")

        await session.commit()

    # The parent polls for this file's existence -- writing is the very last
    # thing this process does before it must be killed to prove anything.
    await asyncio.to_thread(Path(sentinel_path).write_text, "ready")

    await asyncio.Event().wait()  # blocks forever; the test SIGKILLs this process


def main() -> None:
    _, db_url, execution_id, task_id, target_state, sentinel_path = sys.argv
    asyncio.run(_run(db_url, execution_id, task_id, target_state, sentinel_path))


if __name__ == "__main__":
    main()
