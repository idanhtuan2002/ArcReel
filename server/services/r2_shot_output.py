"""The sealed output of an R2 shot task: the M7 attempt's ``SUCCEEDED`` fact carries the output byte digest.

The worker applies the observation ``<execution_id>:output`` with ``evidence_digest`` equal to the
downloaded file's digest. The attempt is then terminal, so the queue's legacy outcome mirror leaves it
alone, and Gate C reads this observation as the only authority for which bytes the task produced.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.async_thread import run_noninterruptible_sync
from lib.db.base import utc_now
from lib.db.models.host_hardening import ProviderObservationModel
from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ExecutionAttemptState,
    ProviderObservation,
    ProviderObservationKind,
)
from r2.contracts.shot_generation import R2ShotGenerationTaskV1
from server.services.execution_attempts import capability_resolver
from server.services.r2_shot_generation import R2_SHOT_EVIDENCE_DIR

_SEALABLE = frozenset({ExecutionAttemptState.ACCEPTED, ExecutionAttemptState.RUNNING})


class R2ShotOutputUnavailable(ValueError):
    """The task has no sealed output, or its file no longer matches the sealed digest."""


def output_observation_id(execution_id: str) -> str:
    return f"{execution_id}:output"


def output_path_for(project_dir: Path, task_id: str) -> Path:
    return Path(project_dir) / R2_SHOT_EVIDENCE_DIR / task_id / "output.mp4"


def file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return "sha256:" + hashlib.file_digest(handle, "sha256").hexdigest()


async def sealed_output_digest(session: AsyncSession, attempt: AttemptSnapshot) -> str | None:
    """The output digest sealed on ``attempt``, or None when it was never sealed by the worker."""
    if attempt.state is not ExecutionAttemptState.SUCCEEDED:
        return None
    row = await session.scalar(
        select(ProviderObservationModel).where(
            ProviderObservationModel.execution_id == attempt.execution_id,
            ProviderObservationModel.observation_id == output_observation_id(attempt.execution_id),
            ProviderObservationModel.kind == ProviderObservationKind.SUCCEEDED.value,
        )
    )
    return None if row is None else row.evidence_digest


async def seal_r2_shot_output(
    session_factory: async_sessionmaker[AsyncSession], evidence: R2ShotGenerationTaskV1, output_path: Path
) -> str:
    """Bind the downloaded bytes to the task's attempt; an exact repeat returns the same digest."""
    digest = await run_noninterruptible_sync(lambda: file_digest(output_path))
    async with session_factory() as session, session.begin():
        repository = ExecutionAttemptRepository(session, capability_resolver=capability_resolver())
        attempt = await repository.get_for_task_attempt(
            user_id=evidence.user_id, project_name=evidence.project_name, task_id=evidence.task_id, attempt_no=1
        )
        if attempt is None or attempt.request_digest != evidence.host_request_digest:
            raise R2ShotOutputUnavailable("r2 shot attempt is not the admitted request")
        if attempt.state is ExecutionAttemptState.SUCCEEDED:
            sealed = await sealed_output_digest(session, attempt)
            if sealed != digest:
                raise R2ShotOutputUnavailable("r2 shot attempt already sealed different output")
            return digest
        if attempt.state not in _SEALABLE:
            raise R2ShotOutputUnavailable(f"r2 shot attempt cannot be sealed from {attempt.state.value}")
        succeeded = await repository.apply_provider_observation(
            user_id=evidence.user_id,
            project_name=evidence.project_name,
            execution_id=attempt.execution_id,
            expected_version=attempt.state_version,
            observation=ProviderObservation(
                observation_id=output_observation_id(attempt.execution_id),
                kind=ProviderObservationKind.SUCCEEDED,
                observed_at=utc_now(),
                provider_job_id=attempt.provider_job_id,
                evidence_digest=digest,
            ),
        )
        if succeeded.state is not ExecutionAttemptState.SUCCEEDED:
            raise R2ShotOutputUnavailable("r2 shot attempt could not reach SUCCEEDED")
    return digest


__all__ = [
    "R2ShotOutputUnavailable",
    "file_digest",
    "output_observation_id",
    "output_path_for",
    "seal_r2_shot_output",
    "sealed_output_digest",
]
