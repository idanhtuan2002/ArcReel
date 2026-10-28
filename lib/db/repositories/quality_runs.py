"""Scoped run-closure custody on PostgreSQL; callers own transactions and stage methods never commit."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import r2.contracts.quality as q
from lib.db.models.quality_probes import QualityProbeInvocationModel, QualityProbeObservationModel
from lib.db.models.quality_runs import (
    QualityHumanObservationModel,
    QualityRunCommandModel,
    QualityRunHeadModel,
    QualityRunModel,
)
from lib.db.repositories.quality_probes import QualityProbeRepository
from r2.advanced_creative.digests import canonical_json_bytes
from r2.quality.digests import compute_digest
from r2.quality.errors import CommandReplayConflictError, RequiredEvidenceMissingError, StaleHeadError
from r2.quality.ports import ProbeRequest
from r2.quality.runs import run_digest

MAX_JSON_BYTES = 1048576


@dataclass(frozen=True)
class RunCommandKey:
    user_id: str
    project_name: str
    actor_id: str
    operation: str
    command_id: str


@dataclass(frozen=True)
class StoredReceipt:
    request_digest: str
    result_ref: str
    result_digest: str


def _bounded(value: object) -> object:
    if len(canonical_json_bytes(value)) > MAX_JSON_BYTES:
        raise RequiredEvidenceMissingError()
    return value


class QualityRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _require_postgresql(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RequiredEvidenceMissingError()

    async def lock_command(self, key: RunCommandKey) -> None:
        """Serialize writers of one full command key; a hash collision only serializes, never merges."""
        self._require_postgresql()
        scoped = canonical_json_bytes({"domain": "m10.run-command-lock.v1", "key": key.__dict__})
        lock = int.from_bytes(hashlib.sha256(scoped).digest()[:8], "big", signed=True)
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    async def lock_head(self, *, user_id: str, project_name: str, subject_digest: str, profile_id: str) -> None:
        """Serialize every sealer of one subject/profile head, including creation of an absent head."""
        self._require_postgresql()
        scoped = canonical_json_bytes(
            {"domain": "m10.run-head-lock.v1", "scope": [user_id, project_name, subject_digest, profile_id]}
        )
        lock = int.from_bytes(hashlib.sha256(scoped).digest()[:8], "big", signed=True)
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    async def receipt(self, key: RunCommandKey, request_digest: str) -> StoredReceipt | None:
        """Receipt-first replay: the stored result of this exact key; a changed body conflicts."""
        row = await self.session.get(
            QualityRunCommandModel, (key.user_id, key.project_name, key.actor_id, key.operation, key.command_id)
        )
        if row is None:
            return None
        if row.request_digest != request_digest:
            raise CommandReplayConflictError()
        return StoredReceipt(row.request_digest, row.result_ref, row.result_digest)

    def _stage_receipt(
        self, key: RunCommandKey, request_digest: str, result_ref: str, result_digest: str, at: datetime
    ) -> None:
        self.session.add(
            QualityRunCommandModel(
                **key.__dict__,
                request_digest=request_digest,
                result_ref=result_ref,
                result_digest=result_digest,
                receipt_json=_bounded(
                    {
                        "command": key.__dict__,
                        "request_digest": request_digest,
                        "result_ref": result_ref,
                        "result_digest": result_digest,
                        "committed_at": at.isoformat(),
                    }
                ),
                committed_at=at,
            )
        )

    async def append_human_observation(
        self,
        key: RunCommandKey,
        request_digest: str,
        observation: q.NarrativeObservation,
        *,
        grant_event_digest: str,
        recorded_at: datetime,
    ) -> None:
        self._require_postgresql()
        observation = q.NarrativeObservation.model_validate(observation)
        digest = compute_digest("m10.narrative-observation.v1", observation)
        self.session.add(
            QualityHumanObservationModel(
                user_id=key.user_id,
                project_name=key.project_name,
                observation_id=observation.observation_id,
                actor_id=key.actor_id,
                command_id=key.command_id,
                request_digest=request_digest,
                grant_event_digest=grant_event_digest,
                observation_digest=digest,
                observation_json=_bounded(observation.model_dump(mode="json")),
                recorded_at=recorded_at,
            )
        )
        self._stage_receipt(key, request_digest, observation.observation_id, digest, recorded_at)
        await self.session.flush()

    async def human_observation(
        self, *, user_id: str, project_name: str, observation_id: str
    ) -> tuple[q.NarrativeObservation, str, str] | None:
        """The stored Human observation, its digest and grant digest, recomputed from the complete body."""
        row = await self.session.get(QualityHumanObservationModel, (user_id, project_name, observation_id))
        if row is None:
            return None
        try:
            observation = q.NarrativeObservation.model_validate(row.observation_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        digest = compute_digest("m10.narrative-observation.v1", observation)
        if digest != row.observation_digest or observation.observation_id != observation_id:
            raise RequiredEvidenceMissingError()
        if observation.assessor_identity != row.actor_id:
            raise RequiredEvidenceMissingError()
        return (observation, digest, row.grant_event_digest)

    async def technical_observation(
        self, *, user_id: str, project_name: str, observation_id: str
    ) -> q.TechnicalObservation | None:
        """An A4 observation only after its complete A4 request/result/M7/observation chain replays."""
        row = await self.session.get(QualityProbeObservationModel, (user_id, project_name, observation_id))
        if row is None:
            return None
        invocation = await self.session.get(
            QualityProbeInvocationModel, (user_id, project_name, row.actor_id, row.execution_ref)
        )
        if invocation is None:
            raise RequiredEvidenceMissingError()
        try:
            request = ProbeRequest.model_validate(invocation.request_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        replayed = await QualityProbeRepository(self.session).replay(request)
        if replayed is None or replayed.observation_id != observation_id:
            raise RequiredEvidenceMissingError()
        return replayed

    async def append_run(
        self,
        key: RunCommandKey,
        request_digest: str,
        run: q.QualityRun,
        *,
        expected_run_id: str | None,
        sealed_at: datetime,
    ) -> str:
        """Append the sealed run and its receipt and advance the subject/profile head by CAS."""
        self._require_postgresql()
        run = q.QualityRun.model_validate(run)
        digest = run_digest(run)
        head = (
            await self.session.execute(
                sa.select(QualityRunHeadModel)
                .filter_by(
                    user_id=key.user_id,
                    project_name=key.project_name,
                    subject_digest=run.subject_digest,
                    profile_id=run.profile_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (None if head is None else head.current_run_id) != expected_run_id:
            raise StaleHeadError()
        self.session.add(
            QualityRunModel(
                user_id=key.user_id,
                project_name=key.project_name,
                run_id=run.run_id,
                actor_id=key.actor_id,
                command_id=key.command_id,
                request_digest=request_digest,
                subject_digest=run.subject_digest,
                profile_id=run.profile_id,
                profile_revision=run.profile_revision,
                run_digest=digest,
                run_json=_bounded(run.model_dump(mode="json")),
                sealed_at=sealed_at,
            )
        )
        self._stage_receipt(key, request_digest, run.run_id, digest, sealed_at)
        await self.session.flush()
        if head is None:
            self.session.add(
                QualityRunHeadModel(
                    user_id=key.user_id,
                    project_name=key.project_name,
                    subject_digest=run.subject_digest,
                    profile_id=run.profile_id,
                    current_run_id=run.run_id,
                    current_run_digest=digest,
                    sequence=1,
                )
            )
        else:
            head.current_run_id = run.run_id
            head.current_run_digest = digest
            head.sequence += 1
        await self.session.flush()
        return digest

    async def run(self, *, user_id: str, project_name: str, run_id: str) -> q.QualityRun | None:
        row = await self.session.get(QualityRunModel, (user_id, project_name, run_id))
        if row is None:
            return None
        try:
            run = q.QualityRun.model_validate(row.run_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        if run_digest(run) != row.run_digest or run.run_id != run_id or run.subject_digest != row.subject_digest:
            raise RequiredEvidenceMissingError()
        return run

    async def head(self, *, user_id: str, project_name: str, subject_digest: str, profile_id: str) -> str | None:
        row = await self.session.get(QualityRunHeadModel, (user_id, project_name, subject_digest, profile_id))
        return None if row is None else row.current_run_id


__all__ = ["MAX_JSON_BYTES", "QualityRunRepository", "RunCommandKey", "StoredReceipt"]
