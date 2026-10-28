"""PostgreSQL custody of M10-B package-scoped packaging observations."""

from __future__ import annotations

import hashlib
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.quality_packaging import PackagingObservationModel
from lib.db.models.quality_probes import QualityProbeResultModel
from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts import packaging as p
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.errors import CommandReplayConflictError, RequiredEvidenceMissingError
from r2.quality.probes import ProbeExecutionResult, execution_result_digest


def packaging_observation_digest(observation: p.PackagingObservation) -> str:
    return compute_digest("m10.packaging-observation.v1", observation)


class PackagingObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _require_postgresql(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RequiredEvidenceMissingError()

    async def lock_command(self, request: p.PackageCheckRequest) -> None:
        """Serialize every writer of one full command key; a hash collision only serializes, never merges."""
        self._require_postgresql()
        command = request.command
        key = [command.user_id, command.project_name, command.actor_id, command.operation, command.command_id]
        scoped = canonical_json_bytes({"domain": "m10.package-check-command-lock.v1", "key": key})
        lock = int.from_bytes(hashlib.sha256(scoped).digest()[:8], "big", signed=True)
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    async def replay(self, request: p.PackageCheckRequest) -> p.PackagingObservation | None:
        """The observation this exact command recorded; another request under the same command id conflicts."""
        command = request.command
        row = (
            await self.session.execute(
                sa.select(PackagingObservationModel).filter_by(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    actor_id=command.actor_id,
                    command_id=command.command_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.request_digest != compute_digest("m10.package-check-request.v1", request):
            raise CommandReplayConflictError()
        return self._verified(row)

    async def get(self, *, user_id: str, project_name: str, observation_id: str) -> p.PackagingObservation | None:
        row = await self.session.get(PackagingObservationModel, (user_id, project_name, observation_id))
        return None if row is None else self._verified(row)

    @staticmethod
    def _verified(row: PackagingObservationModel) -> p.PackagingObservation:
        try:
            observation = p.PackagingObservation.model_validate(row.observation_json)
            verify_caches(observation)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        subject = observation.packaging_subject
        if (
            packaging_observation_digest(observation) != row.observation_digest
            or observation.observation_id != row.observation_id
            or (subject.packaging_candidate_id, subject.packaging_candidate_revision)
            != (row.candidate_id, row.candidate_revision)
            or subject.packaging_candidate_digest != row.candidate_payload_digest
            or observation.constraint_snapshot_digest != row.constraint_snapshot_digest
            or observation.status.value != row.status
        ):
            raise RequiredEvidenceMissingError()
        return observation

    async def stage(
        self, request: p.PackageCheckRequest, observation: p.PackagingObservation, recorded_at: datetime
    ) -> None:
        """Flush one observation for the caller's transaction; never commits."""
        self._require_postgresql()
        subject = request.subject
        self.session.add(
            PackagingObservationModel(
                user_id=subject.user_id,
                project_name=subject.project_name,
                observation_id=observation.observation_id,
                actor_id=subject.actor_id,
                command_id=request.command.command_id,
                request_digest=compute_digest("m10.package-check-request.v1", request),
                candidate_id=subject.candidate_id,
                candidate_revision=subject.candidate_revision,
                candidate_payload_digest=subject.candidate_payload_digest,
                quality_run_id=subject.quality_run_id,
                constraint_snapshot_digest=observation.constraint_snapshot_digest,
                status=observation.status.value,
                observation_digest=packaging_observation_digest(observation),
                observation_json=observation.model_dump(mode="json"),
                recorded_at=recorded_at,
            )
        )
        await self.session.flush()

    async def probe_result(
        self, *, user_id: str, project_name: str, execution_id: str, expected_digest: str
    ) -> ProbeExecutionResult:
        """A stored probe result whose recomputed digest is exactly the one an observation names."""
        row = await self.session.get(QualityProbeResultModel, (user_id, project_name, execution_id))
        if row is None:
            raise RequiredEvidenceMissingError()
        try:
            result = ProbeExecutionResult.model_validate(row.result_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        digest = execution_result_digest(result)
        if digest != row.result_digest or digest != expected_digest:
            raise RequiredEvidenceMissingError()
        return result


__all__ = ["PackagingObservationRepository", "packaging_observation_digest"]
