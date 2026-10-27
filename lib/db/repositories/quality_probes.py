"""Scoped append-only probe custody on PostgreSQL; callers own transactions and stage methods never commit."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import r2.contracts.quality as q
from lib.db.models.host_hardening import ExecutionAttemptModel
from lib.db.models.quality_probes import (
    QualityProbeInvocationModel,
    QualityProbeObservationModel,
    QualityProbeResultModel,
)
from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import ProviderRouteSnapshot
from r2.quality.digests import compute_digest
from r2.quality.errors import CommandReplayConflictError, RequiredEvidenceMissingError
from r2.quality.ports import ProbeRequest, validate_probe_result_binding
from r2.quality.probes import (
    ProbeExecutionResult,
    execution_result_digest,
    measurement_digest,
    probe_request_digest,
    validate_probe_envelope,
)

MAX_JSON_BYTES = 1048576


@dataclass(frozen=True)
class StoredProbeInvocation:
    """The complete frozen identity later phases need; it grants no execution or disposition authority."""

    request: ProbeRequest
    request_digest: str
    execution_id: str
    task_id: str
    observation_id: str
    route: ProviderRouteSnapshot
    provider_request: ProviderRequest
    config_digest: str
    catalog_digest: str
    tool_identity_digest: str
    input_digests: tuple[str, ...]
    prepared_at: datetime


def observation_digest(observation: q.TechnicalObservation) -> str:
    return compute_digest("m10.technical-observation.v1", q.TechnicalObservation.model_validate(observation))


def _bounded(value: object) -> object:
    if len(canonical_json_bytes(value)) > MAX_JSON_BYTES:
        raise RequiredEvidenceMissingError()
    return value


def _key(request: ProbeRequest) -> dict[str, str]:
    return {
        "user_id": request.user_id,
        "project_name": request.project_name,
        "actor_id": request.actor_id,
        "execution_ref": request.execution_ref,
    }


class QualityProbeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _require_postgresql(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RequiredEvidenceMissingError()

    async def lock_command(self, request: ProbeRequest) -> None:
        """Serialize every writer of one full command key; a hash collision only serializes, never merges."""
        self._require_postgresql()
        validate_probe_envelope(request)
        scoped = canonical_json_bytes({"domain": "m10.probe-command-lock.v1", "key": _key(request)})
        lock = int.from_bytes(hashlib.sha256(scoped).digest()[:8], "big", signed=True)
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    async def invocation(self, request: ProbeRequest) -> StoredProbeInvocation | None:
        """The stored invocation of this full key; a different canonical request under it conflicts."""
        request = ProbeRequest.model_validate(request)
        row = await self.session.get(
            QualityProbeInvocationModel,
            (request.user_id, request.project_name, request.actor_id, request.execution_ref),
        )
        if row is None:
            return None
        stored = self._stored(row)
        if canonical_json_bytes(stored.request) != canonical_json_bytes(request):
            raise CommandReplayConflictError()
        return stored

    def _stored(self, row: QualityProbeInvocationModel) -> StoredProbeInvocation:
        try:
            request = ProbeRequest.model_validate(row.request_json)
            if probe_request_digest(request) != row.request_digest:
                raise RequiredEvidenceMissingError()
            if (request.user_id, request.project_name, request.actor_id, request.execution_ref) != (
                row.user_id,
                row.project_name,
                row.actor_id,
                row.execution_ref,
            ):
                raise RequiredEvidenceMissingError()
            inputs = tuple(row.input_digests_json)
            if not inputs or any(type(item) is not str for item in inputs):
                raise RequiredEvidenceMissingError()
            return StoredProbeInvocation(
                request=request,
                request_digest=row.request_digest,
                execution_id=row.execution_id,
                task_id=row.task_id,
                observation_id=row.observation_id,
                route=ProviderRouteSnapshot.model_validate(row.route_json),
                provider_request=ProviderRequest.model_validate(row.provider_request_json),
                config_digest=row.config_digest,
                catalog_digest=row.catalog_digest,
                tool_identity_digest=row.tool_identity_digest,
                input_digests=inputs,
                prepared_at=row.prepared_at,
            )
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None

    async def prepare(self, invocation: StoredProbeInvocation) -> StoredProbeInvocation:
        """Stage the invocation in the caller's transaction, committed together with the PLANNED attempt."""
        self._require_postgresql()
        request = ProbeRequest.model_validate(invocation.request)
        if probe_request_digest(request) != invocation.request_digest or request.rule.config_digest != (
            invocation.config_digest
        ):
            raise RequiredEvidenceMissingError()
        self.session.add(
            QualityProbeInvocationModel(
                **_key(request),
                request_digest=invocation.request_digest,
                request_json=_bounded(request.model_dump(mode="json")),
                execution_id=invocation.execution_id,
                task_id=invocation.task_id,
                observation_id=invocation.observation_id,
                route_json=_bounded(invocation.route.model_dump(mode="json")),
                provider_request_json=_bounded(invocation.provider_request.model_dump(mode="json")),
                config_digest=invocation.config_digest,
                catalog_digest=invocation.catalog_digest,
                tool_identity_digest=invocation.tool_identity_digest,
                input_digests_json=list(invocation.input_digests),
                prepared_at=invocation.prepared_at,
            )
        )
        await self.session.flush()
        return invocation

    async def stage_result(self, invocation: StoredProbeInvocation, result: ProbeExecutionResult) -> None:
        """Flush the exact bounded result for M7 to commit atomically with its acceptance; never commits."""
        result = ProbeExecutionResult.model_validate(result)
        if (
            result.request_digest != invocation.request_digest
            or result.measurement.input_digests != invocation.input_digests
            or result.measurement.config_digest != invocation.config_digest
            or result.measurement.tool_identity_digest != invocation.tool_identity_digest
        ):
            raise RequiredEvidenceMissingError()
        self.session.add(
            QualityProbeResultModel(
                user_id=invocation.request.user_id,
                project_name=invocation.request.project_name,
                execution_id=invocation.execution_id,
                result_digest=execution_result_digest(result),
                measurement_digest=measurement_digest(result.measurement),
                result_json=_bounded(result.model_dump(mode="json")),
                staged_at=result.finished_at,
            )
        )
        await self.session.flush()

    async def result(self, invocation: StoredProbeInvocation) -> ProbeExecutionResult | None:
        """The stored result, recomputed from its complete body; cached digest drift refuses."""
        row = await self.session.get(
            QualityProbeResultModel,
            (invocation.request.user_id, invocation.request.project_name, invocation.execution_id),
        )
        if row is None:
            return None
        try:
            result = ProbeExecutionResult.model_validate(row.result_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        if (
            execution_result_digest(result) != row.result_digest
            or measurement_digest(result.measurement) != row.measurement_digest
            or result.request_digest != invocation.request_digest
            or result.measurement.input_digests != invocation.input_digests
            or result.measurement.config_digest != invocation.config_digest
            or result.measurement.tool_identity_digest != invocation.tool_identity_digest
        ):
            raise RequiredEvidenceMissingError()
        return result

    async def attempt_witness(self, invocation: StoredProbeInvocation) -> tuple[str, str | None]:
        """The independent M7 attempt state and accepted job id (``<execution id>:<result digest>``)."""
        row = (
            await self.session.execute(
                sa.select(ExecutionAttemptModel).where(
                    ExecutionAttemptModel.user_id == invocation.request.user_id,
                    ExecutionAttemptModel.project_name == invocation.request.project_name,
                    ExecutionAttemptModel.execution_id == invocation.execution_id,
                )
            )
        ).scalar_one_or_none()
        if row is None or row.task_id != invocation.task_id:
            raise RequiredEvidenceMissingError()
        return (str(row.state), row.provider_job_id)

    async def finalize(
        self, invocation: StoredProbeInvocation, observation: q.TechnicalObservation
    ) -> q.TechnicalObservation:
        """Append the observation bound to this invocation's exact result; the caller commits it with M7 SUCCEEDED."""
        result = await self.result(invocation)
        if result is None:
            raise RequiredEvidenceMissingError()
        observation = validate_probe_result_binding(invocation.request, observation)
        self._require_binding(invocation, result, observation)
        self.session.add(
            QualityProbeObservationModel(
                user_id=invocation.request.user_id,
                project_name=invocation.request.project_name,
                observation_id=observation.observation_id,
                actor_id=invocation.request.actor_id,
                execution_ref=invocation.request.execution_ref,
                execution_id=invocation.execution_id,
                observation_digest=observation_digest(observation),
                observation_json=_bounded(observation.model_dump(mode="json")),
                finalized_at=observation.observed_at,
            )
        )
        await self.session.flush()
        return observation

    @staticmethod
    def _require_binding(
        invocation: StoredProbeInvocation, result: ProbeExecutionResult, observation: q.TechnicalObservation
    ) -> None:
        if (
            observation.observation_id != invocation.observation_id
            or observation.probe_receipt_ref != invocation.execution_id
            or observation.probe_receipt_digest != execution_result_digest(result)
            or observation.evidence_digest != execution_result_digest(result)
            or observation.measurement_digest != measurement_digest(result.measurement)
            or observation.tool_identity_digest != result.measurement.tool_identity_digest
            or observation.status.value != result.measurement.status
        ):
            raise RequiredEvidenceMissingError()

    async def replay(self, request: ProbeRequest) -> q.TechnicalObservation | None:
        """Verify the entire stored request/result/M7/observation chain before returning a historical receipt."""
        invocation = await self.invocation(request)
        if invocation is None:
            return None
        row = (
            await self.session.execute(
                sa.select(QualityProbeObservationModel).filter_by(
                    user_id=invocation.request.user_id,
                    project_name=invocation.request.project_name,
                    actor_id=invocation.request.actor_id,
                    execution_ref=invocation.request.execution_ref,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        result = await self.result(invocation)
        try:
            observation = q.TechnicalObservation.model_validate(row.observation_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        if result is None or observation_digest(observation) != row.observation_digest:
            raise RequiredEvidenceMissingError()
        try:
            observation = validate_probe_result_binding(invocation.request, observation)
        except ValueError:
            raise RequiredEvidenceMissingError() from None
        self._require_binding(invocation, result, observation)
        state, job_id = await self.attempt_witness(invocation)
        if state != "SUCCEEDED" or job_id != f"{invocation.execution_id}:{execution_result_digest(result)}":
            raise RequiredEvidenceMissingError()
        return observation


__all__ = ["MAX_JSON_BYTES", "QualityProbeRepository", "StoredProbeInvocation", "observation_digest"]
