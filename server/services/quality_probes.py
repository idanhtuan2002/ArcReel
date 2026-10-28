"""Request-bound interactive probe observation through existing M7 attempt custody.

The service prepares under PostgreSQL, runs the isolated probe with no database transaction open, stages
the result in M7's own acceptance commit, and finalizes the observation in a fresh transaction. A stored
receipt is replayed only after the complete request/result/M7/observation chain verifies. There is no
public router or default app registration.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.repositories.host_hardening import ExecutionAttemptRepository, MasterAuthorityRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_probes import QualityProbeRepository, StoredProbeInvocation
from lib.video_backends.base import AmbiguousSubmitError
from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.exploration import uuid7
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ExecutionAttemptState,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.host_submit import AttemptSubmitter, ProviderSubmitReceipt
from r2.host_hardening.paid_routes import current_release_mode
from r2.host_hardening.route_inventory import (
    HOST_QUALITY_ADAPTER_VERSION,
    QUALITY_PROBE_SUBMIT_FAMILIES,
    require_submit_route,
)
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    OperationalEnvelopeExceededError,
    ProbeFailedError,
    ProfileStaleError,
    ReferenceInvalidError,
    RequiredEvidenceMissingError,
    SubjectStaleError,
)
from r2.quality.ports import ProbeRequest
from r2.quality.probes import (
    ProbeCatalog,
    ProbeConfig,
    ProbeExecutionResult,
    config_digest,
    execution_result_digest,
    facts_digest,
    measurement_digest,
    probe_request_digest,
    tool_identity_digest,
    validate_probe_envelope,
)
from server.auth import get_current_interactive_user
from server.services.execution_attempts import build_execution_attempt_service, capability_resolver
from server.services.quality_probe_inputs import ProbeInputs, snapshot_probe_inputs
from server.services.quality_probe_runtime import QualityProbeRuntime, failure_resources

ASSESSOR_IDENTITY = "host-quality-probe"
INDEPENDENCE_GROUP = "host-deterministic-probe"
MEASUREMENT_SCHEMA_ID = "m10.probe-measurement.v1"
_FAMILY = QUALITY_PROBE_SUBMIT_FAMILIES[0]
_KNOWN_FAILURES = (ProbeFailedError, ReferenceInvalidError, OperationalEnvelopeExceededError)

type SubmitterFactory = Callable[[AsyncSession, str, str, str], AttemptSubmitter]


def attempt_submitter(session: AsyncSession, user_id: str, project_name: str, execution_id: str) -> AttemptSubmitter:
    """Existing M7 submitter whose new attempt uses the execution id reserved by the staged invocation."""
    resolver = capability_resolver()
    return AttemptSubmitter(
        repository=ExecutionAttemptRepository(session, capability_resolver=resolver),
        service=build_execution_attempt_service(session, adapter_registry={}),
        capability_resolver=resolver,
        user_id=user_id,
        project_name=project_name,
        usage_binder=None,
        execution_id_factory=lambda: execution_id,
    )


def probe_task_id(request: ProbeRequest) -> str:
    """Bounded M7 task identity derived from the scoped full command key, never from caller route data."""
    scoped = canonical_json_bytes(
        {
            "domain": "m10.probe-task.v1",
            "user_id": request.user_id,
            "project_name": request.project_name,
            "actor_id": request.actor_id,
            "execution_ref": request.execution_ref,
        }
    )
    return "m10-probe:" + hashlib.sha256(scoped).hexdigest()


def probe_route(config: ProbeConfig) -> ProviderRouteSnapshot:
    return ProviderRouteSnapshot(
        provider_id=_FAMILY.key.provider_id,
        provider_account_ref="local",
        provider_model_id=config.recipe,
        backend_model_id=tool_identity_digest(config),
        endpoint_id=_FAMILY.key.endpoint_id,
        submitted_base_url="local://quality-probe",
        adapter_version=HOST_QUALITY_ADAPTER_VERSION,
        capability_profile_ref=_FAMILY.capability_profile_ref,
    )


def probe_provider_request(
    request: ProbeRequest, config: ProbeConfig, *, catalog_digest: str, input_digests: tuple[str, ...]
) -> ProviderRequest:
    task_id = probe_task_id(request)
    return ProviderRequest(
        id=f"{task_id}:probe",
        host_task_ref=task_id,
        provider=_FAMILY.key.provider_id,
        model=config.recipe,
        endpoint=_FAMILY.key.endpoint_id,
        payload={
            "schema": "m10.probe-provider-request.v1",
            "request_digest": probe_request_digest(request),
            "config_digest": config_digest(config),
            "catalog_digest": catalog_digest,
            "tool_identity_digest": tool_identity_digest(config),
            "input_digests": list(input_digests),
        },
        adapter_version=HOST_QUALITY_ADAPTER_VERSION,
    )


def build_observation(
    invocation: StoredProbeInvocation, result: ProbeExecutionResult, *, observed_at: datetime
) -> q.TechnicalObservation:
    """Project the exact stored result into the A1 technical observation; it issues no disposition."""
    request = invocation.request
    slot = next(
        slot
        for requirement in request.profile.policy.assessment_requirements
        if requirement.requirement_id == request.requirement_id
        for slot in requirement.slots
        if slot.slot_id == request.slot_id
    )
    measurement = result.measurement
    result_digest = execution_result_digest(result)
    return q.TechnicalObservation(
        observation_id=invocation.observation_id,
        observation_type=q.ObservationType.TECHNICAL,
        requirement_id=request.requirement_id,
        slot_id=request.slot_id,
        assessor_identity=ASSESSOR_IDENTITY,
        assessor_version=HOST_QUALITY_ADAPTER_VERSION,
        assessor_qualification_ref=slot.qualification_policy_id,
        assessor_qualification_digest=slot.qualification_policy_digest,
        independence_group=INDEPENDENCE_GROUP,
        producer_conflict=False,
        config_digest=request.rule.config_digest,
        subject_digest=compute_digest("m10.assessed-subject.v1", request.subject),
        status=q.ObservationStatus(measurement.status),
        findings=tuple(
            q.QualityFinding(
                finding_id=uuid7(),
                rule_id=finding.rule_id,
                severity=finding.severity,
                subject_locator=finding.subject_locator,
                evidence_digest=finding.evidence_digest,
            )
            for finding in measurement.findings
        ),
        evidence_refs=(invocation.execution_id,),
        evidence_digest=result_digest,
        observed_at=observed_at,
        rule_id=request.rule.rule_id,
        probe_receipt_ref=invocation.execution_id,
        probe_receipt_digest=result_digest,
        tool_identity_digest=measurement.tool_identity_digest,
        measurement_schema_id=MEASUREMENT_SCHEMA_ID,
        measurement_digest=measurement_digest(measurement),
        interval_evidence_digest=facts_digest(measurement.facts) if measurement.recipe == "INTERVALS" else None,
    )


class QualityProbeService:
    """A bound authenticated request wrapper; catalog, runtime and roots are host configuration."""

    def __init__(
        self,
        request: ProbeRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        project_root: Path,
        catalog: ProbeCatalog,
        runtime: QualityProbeRuntime,
        submitter_for: SubmitterFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        validate_probe_envelope(request)
        self._request = ProbeRequest.model_validate(request)
        self._binding = canonical_json_bytes(self._request)
        self._sessions = sessions
        self._token = interactive_token
        self._project_root = project_root
        self._catalog = ProbeCatalog.model_validate(catalog)
        self._runtime = runtime
        self._submitter_for = submitter_for or attempt_submitter
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    async def for_request(
        cls,
        request: ProbeRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        project_root: Path,
        catalog: ProbeCatalog,
        runtime: QualityProbeRuntime,
        submitter_for: SubmitterFactory | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> Self:
        """Bind the exact request and verify its JWT without touching the database or media."""
        service = cls(
            request,
            sessions,
            interactive_token=interactive_token,
            project_root=project_root,
            catalog=catalog,
            runtime=runtime,
            submitter_for=submitter_for,
            clock=clock,
        )
        await service.require_actor(request)
        return service

    async def require_actor(self, request: ProbeRequest) -> None:
        """Revalidate the interactive JWT and the original exact request binding."""
        validate_probe_envelope(request)
        normalized = ProbeRequest.model_validate(request)
        if canonical_json_bytes(normalized) != self._binding:
            raise RequiredEvidenceMissingError()
        try:
            user = await get_current_interactive_user(self._token)
        except HTTPException:
            raise RequiredEvidenceMissingError() from None
        if (user.id, user.sub) != (normalized.user_id, normalized.actor_id):
            raise RequiredEvidenceMissingError()

    async def observe(self, request: ProbeRequest) -> q.TechnicalObservation:
        await self.require_actor(request)
        request = self._request
        # Receipt-first: a stored chain replays before any live catalog, media, tool or authority check.
        async with self._sessions() as session, session.begin():
            repository = QualityProbeRepository(session)
            await repository.lock_command(request)
            replayed = await repository.replay(request)
            invocation = await repository.invocation(request)
            state = None if invocation is None else (await repository.attempt_witness(invocation))[0]
            recorded = (
                await repository.failure(invocation)
                if invocation is not None and state == ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE.value
                else None
            )
        if replayed is not None:
            await self.require_actor(request)
            return replayed
        if invocation is not None and state == ExecutionAttemptState.ACCEPTED.value:
            return await self._finalize(invocation)
        if invocation is not None and state == ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE.value:
            raise recorded if recorded is not None else ProbeFailedError()
        if invocation is not None and state != ExecutionAttemptState.PLANNED.value:
            # Pending, unknown or operator-review outcomes are never re-run under the same reference.
            raise RequiredEvidenceMissingError()
        config = self._catalog.resolve(request)
        require_submit_route(
            _FAMILY.key.provider_id,
            _FAMILY.key.endpoint_id,
            HOST_QUALITY_ADAPTER_VERSION,
            release_mode=current_release_mode(),
            now=self._clock(),
        )
        self._runtime.preflight(config)
        async with self._sessions() as session:
            await self._require_current_authority(session, request)
        async with snapshot_probe_inputs(
            request, project_root=self._project_root, catalog=self._catalog, work_root=self._runtime.host.work_root
        ) as inputs:
            return await self._submit(request, config, inputs, invocation)

    async def _require_current_authority(self, session: AsyncSession, request: ProbeRequest) -> None:
        """Exact stored profile revision and approved root; changed authority is stale, never re-bound."""
        profile = await QualityProfileRepository(session).get_revision(
            user_id=request.user_id,
            project_name=request.project_name,
            profile_id=request.profile.profile_id,
            revision=request.profile.revision,
        )
        if profile is None or canonical_json_bytes(profile) != canonical_json_bytes(request.profile):
            raise ProfileStaleError()
        root = request.subject.master_binding.root
        current = await MasterAuthorityRepository(session).get_current(
            user_id=request.user_id, project_name=request.project_name, artifact_key=root.artifact_key
        )
        if current is None or canonical_json_bytes(current) != canonical_json_bytes(root):
            raise SubjectStaleError()

    async def _submit(
        self,
        request: ProbeRequest,
        config: ProbeConfig,
        inputs: ProbeInputs,
        existing: StoredProbeInvocation | None,
    ) -> q.TechnicalObservation:
        catalog_digest = self._catalog.digest()
        failures: list[BaseException] = []
        async with self._sessions() as session:
            repository = QualityProbeRepository(session)
            try:
                # The command lock is held until M7 commits PLANNED together with the staged invocation.
                await repository.lock_command(request)
                await self._require_current_authority(session, request)
                current = await repository.invocation(request)
                if (current is None) != (existing is None):
                    raise RequiredEvidenceMissingError()
                if current is None:
                    invocation = StoredProbeInvocation(
                        request=request,
                        request_digest=probe_request_digest(request),
                        execution_id=uuid7(),
                        task_id=probe_task_id(request),
                        observation_id=uuid7(),
                        route=probe_route(config),
                        provider_request=probe_provider_request(
                            request, config, catalog_digest=catalog_digest, input_digests=inputs.input_digests
                        ),
                        config_digest=config_digest(config),
                        catalog_digest=catalog_digest,
                        tool_identity_digest=tool_identity_digest(config),
                        input_digests=inputs.input_digests,
                        prepared_at=self._clock(),
                    )
                    await repository.prepare(invocation)
                else:
                    invocation = current
                    if (invocation.input_digests, invocation.catalog_digest) != (inputs.input_digests, catalog_digest):
                        raise RequiredEvidenceMissingError()
            except BaseException:
                await session.rollback()
                raise
            submitter = self._submitter_for(session, request.user_id, request.project_name, invocation.execution_id)

            async def submit(attempt: AttemptSnapshot) -> ProviderSubmitReceipt[ProbeExecutionResult]:
                if attempt.execution_id != invocation.execution_id:
                    failures.append(RequiredEvidenceMissingError())
                    raise AmbiguousSubmitError(
                        provider=_FAMILY.key.provider_id, message="[create_ambiguous] quality probe outcome unknown"
                    )
                try:
                    result = await self._runtime.run(request, inputs, config)
                except _KNOWN_FAILURES as error:
                    try:
                        # M7 commits this row together with FAILED_BEFORE_ACCEPTANCE.
                        await repository.stage_failure(invocation, error, failure_resources(error), self._clock())
                    except Exception as staging:
                        await session.rollback()
                        failures.append(RequiredEvidenceMissingError())
                        raise AmbiguousSubmitError(
                            provider=_FAMILY.key.provider_id, message="[create_ambiguous] quality probe outcome unknown"
                        ) from staging
                    failures.append(error)
                    raise
                except Exception as error:
                    failures.append(RequiredEvidenceMissingError())
                    raise AmbiguousSubmitError(
                        provider=_FAMILY.key.provider_id, message="[create_ambiguous] quality probe outcome unknown"
                    ) from error
                try:
                    await repository.stage_result(invocation, result)
                    digest = execution_result_digest(result)
                    job_id = f"{attempt.execution_id}:{digest}"
                    return ProviderSubmitReceipt(
                        observation=ProviderObservation(
                            observation_id=f"{attempt.execution_id}:accepted",
                            kind=ProviderObservationKind.ACCEPTED,
                            observed_at=self._clock(),
                            provider_job_id=job_id,
                            evidence_digest=digest,
                        ),
                        value=result,
                    )
                except Exception as error:
                    # Nothing staged after a possible tool start may commit as an ordinary failure.
                    await session.rollback()
                    failures.append(RequiredEvidenceMissingError())
                    raise AmbiguousSubmitError(
                        provider=_FAMILY.key.provider_id, message="[create_ambiguous] quality probe outcome unknown"
                    ) from error

            outcome = await submitter.submit(
                task_id=invocation.task_id,
                api_call_id=None,
                route=invocation.route,
                request=invocation.provider_request,
                submit=submit,
            )
        if outcome.execution_id != invocation.execution_id:
            raise RequiredEvidenceMissingError()
        state = outcome.snapshot.state
        if state is ExecutionAttemptState.ACCEPTED:
            return await self._finalize(invocation)
        if state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE:
            known = [error for error in failures if isinstance(error, _KNOWN_FAILURES)]
            if known:
                raise known[-1]
            async with self._sessions() as session:
                recorded = await QualityProbeRepository(session).failure(invocation)
            raise recorded if recorded is not None else ProbeFailedError()
        if state is ExecutionAttemptState.SUCCEEDED:
            return await self.observe(request)
        raise RequiredEvidenceMissingError()

    async def _finalize(self, invocation: StoredProbeInvocation) -> q.TechnicalObservation:
        """Reauthenticate, verify the stored chain and current authority, then commit SUCCEEDED with the observation."""
        request = invocation.request
        async with self._sessions() as session, session.begin():
            repository = QualityProbeRepository(session)
            await repository.lock_command(request)
            replayed = await repository.replay(request)
            if replayed is not None:
                await self.require_actor(request)
                return replayed
            result = await repository.result(invocation)
            attempts = ExecutionAttemptRepository(session, capability_resolver=capability_resolver())
            attempt = await attempts.get_exact(
                user_id=request.user_id, project_name=request.project_name, execution_id=invocation.execution_id
            )
            if result is None or attempt is None:
                raise RequiredEvidenceMissingError()
            digest = execution_result_digest(result)
            job_id = f"{invocation.execution_id}:{digest}"
            witness_state, witness_job = await repository.attempt_witness(invocation)
            if (
                attempt.state is not ExecutionAttemptState.ACCEPTED
                or attempt.provider_job_id != job_id
                or (witness_state, witness_job) != (ExecutionAttemptState.ACCEPTED.value, job_id)
            ):
                raise RequiredEvidenceMissingError()
            await self._require_current_authority(session, request)
            await self.require_actor(request)
            succeeded = await attempts.apply_provider_observation(
                user_id=request.user_id,
                project_name=request.project_name,
                execution_id=invocation.execution_id,
                expected_version=attempt.state_version,
                observation=ProviderObservation(
                    observation_id=f"{invocation.execution_id}:succeeded",
                    kind=ProviderObservationKind.SUCCEEDED,
                    observed_at=self._clock(),
                    provider_job_id=job_id,
                    evidence_digest=digest,
                ),
            )
            if succeeded.state is not ExecutionAttemptState.SUCCEEDED:
                raise RequiredEvidenceMissingError()
            observation = build_observation(invocation, result, observed_at=self._clock())
            return await repository.finalize(invocation, observation)


__all__ = [
    "QualityProbeService",
    "attempt_submitter",
    "build_observation",
    "probe_provider_request",
    "probe_route",
    "probe_task_id",
]
