"""Request-bound Human observation recording and run completion over re-verified stored evidence.

Both services re-authenticate the interactive JWT, use PostgreSQL as the only authority and replay a
stored receipt before any live check. Human qualification is a current signed HUMAN_SHOWRUNNER grant read
through governance-activated startup. No router, default registration or Factual Authority exists here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Self

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.models.quality import QualityProfileHeadModel
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_runs import QualityRunRepository, RunCommandKey
from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.exploration import uuid7
from r2.governance.grant_transition import GrantScopeV1
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.errors import ProfileStaleError, RequiredEvidenceMissingError, SubjectStaleError
from r2.quality.runs import (
    HUMAN_SHOWRUNNER_POLICY_ID,
    AdmittedObservation,
    HumanObservationRequest,
    RunValidity,
    ValidityInputs,
    close_run,
    human_request_digest,
    human_showrunner_policy_digest,
    project_validity,
)
from server.auth import get_current_interactive_user
from server.services.governance_grants import CheckpointedShowrunnerGrantReader, ShowrunnerGrantUnavailableError

HUMAN_ASSESSOR_VERSION = "m10.human-rubric.v1"

type GrantReaderFactory = Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]


async def _require_actor(token: str | None, user_id: str, actor_id: str) -> None:
    try:
        user = await get_current_interactive_user(token)
    except HTTPException:
        raise RequiredEvidenceMissingError() from None
    if (user.id, user.sub) != (user_id, actor_id):
        raise RequiredEvidenceMissingError()


async def _require_postgresql_transaction(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "postgresql" or not session.in_transaction():
        raise RequiredEvidenceMissingError()


async def _require_profile(session: AsyncSession, profile: q.QualityProfileRevision) -> None:
    stored = await QualityProfileRepository(session).get_revision(
        user_id=profile.user_id,
        project_name=profile.project_name,
        profile_id=profile.profile_id,
        revision=profile.revision,
    )
    if stored is None or canonical_json_bytes(stored) != canonical_json_bytes(profile):
        raise ProfileStaleError()


async def _subject_current(session: AsyncSession, subject: q.AssessedSubject) -> bool:
    """The approved root and every dependency head are still the authority's current versions."""
    binding = subject.master_binding
    repository = MasterAuthorityRepository(session)
    for head in sorted((binding.root, *binding.dependency_heads), key=lambda item: item.artifact_key):
        current = await repository.get_current(
            user_id=binding.user_id, project_name=binding.project_name, artifact_key=head.artifact_key
        )
        if current is None or canonical_json_bytes(current) != canonical_json_bytes(head):
            return False
    return True


async def _grant(reader: CheckpointedShowrunnerGrantReader, session: AsyncSession, scope: GrantScopeV1) -> str:
    try:
        event = await reader.require_current_locked(session, scope=scope)
    except ShowrunnerGrantUnavailableError:
        raise RequiredEvidenceMissingError() from None
    return event.event_digest


class HumanObservationService:
    """Records one qualified showrunner rubric observation; caller identities and digests are not trusted."""

    def __init__(
        self,
        request: HumanObservationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        verify_caches(request.subject)
        verify_caches(request.profile)
        self._request = HumanObservationRequest.model_validate(request)
        self._sessions = sessions
        self._token = interactive_token
        self._grant_reader = grant_reader
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    async def for_request(
        cls,
        request: HumanObservationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> Self:
        service = cls(request, sessions, interactive_token=interactive_token, grant_reader=grant_reader, clock=clock)
        await _require_actor(interactive_token, service._request.user_id, service._request.actor_id)
        return service

    def _slot(self) -> q.AssessmentSlot:
        request = self._request
        slot = next(
            (
                slot
                for requirement in request.profile.policy.assessment_requirements
                if requirement.requirement_id == request.requirement_id
                for slot in requirement.slots
                if slot.slot_id == request.slot_id
            ),
            None,
        )
        if (
            slot is None
            or (slot.kind, slot.assessor_class) != (q.AssessorKind.NARRATIVE, q.AssessorClass.HUMAN)
            or (slot.qualification_policy_id, slot.qualification_policy_digest)
            != (HUMAN_SHOWRUNNER_POLICY_ID, human_showrunner_policy_digest())
            or request.status not in slot.allowed_applicability_states
            or request.status == q.ObservationStatus.INAPPLICABLE
        ):
            raise RequiredEvidenceMissingError()
        return slot

    async def record(self, request: HumanObservationRequest) -> q.NarrativeObservation:
        request = HumanObservationRequest.model_validate(request)
        if canonical_json_bytes(request) != canonical_json_bytes(self._request):
            raise RequiredEvidenceMissingError()
        await _require_actor(self._token, request.user_id, request.actor_id)
        digest = human_request_digest(request)
        key = RunCommandKey(
            request.user_id, request.project_name, request.actor_id, "RECORD_HUMAN_OBSERVATION", request.command_id
        )
        reader = await self._grant_reader()
        async with self._sessions() as session, session.begin():
            await _require_postgresql_transaction(session)
            repository = QualityRunRepository(session)
            await repository.lock_command(key)
            stored = await repository.receipt(key, digest)
            if stored is not None:
                found = await repository.human_observation(
                    user_id=request.user_id, project_name=request.project_name, observation_id=stored.result_ref
                )
                if found is None or found[1] != stored.result_digest:
                    raise RequiredEvidenceMissingError()
                return found[0]
            self._slot()
            await _require_profile(session, request.profile)
            if not await _subject_current(session, request.subject):
                raise SubjectStaleError()
            grant = await _grant(reader, session, GrantScopeV1(request.user_id, request.project_name, request.actor_id))
            await _require_actor(self._token, request.user_id, request.actor_id)
            now = self._clock()
            observation = q.NarrativeObservation(
                observation_id=uuid7(),
                observation_type=q.ObservationType.NARRATIVE,
                requirement_id=request.requirement_id,
                slot_id=request.slot_id,
                assessor_identity=request.actor_id,
                assessor_version=HUMAN_ASSESSOR_VERSION,
                assessor_qualification_ref=HUMAN_SHOWRUNNER_POLICY_ID,
                assessor_qualification_digest=grant,
                independence_group="human:" + request.actor_id,
                producer_conflict=False,
                config_digest=request.rubric_digest,
                subject_digest=compute_digest("m10.assessed-subject.v1", request.subject),
                status=request.status,
                findings=request.findings,
                evidence_refs=request.evidence_refs,
                evidence_digest=request.evidence_digest,
                observed_at=now,
                rubric_id=request.rubric_id,
                rubric_digest=request.rubric_digest,
                segment_closure_digest=request.segment_closure_digest,
                reviewer_evidence_digest=request.reviewer_evidence_digest,
            )
            await repository.append_human_observation(
                key, digest, observation, grant_event_digest=grant, recorded_at=now
            )
            return observation


class QualityRunService:
    """Seals a run from stored evidence named by the completion command; nothing in the command is trusted."""

    def __init__(
        self,
        command: q.CompleteRunCommand,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        verify_caches(command)
        self._command = q.CompleteRunCommand.model_validate(command)
        self._sessions = sessions
        self._token = interactive_token
        self._grant_reader = grant_reader
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    async def for_request(
        cls,
        command: q.CompleteRunCommand,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> Self:
        service = cls(command, sessions, interactive_token=interactive_token, grant_reader=grant_reader, clock=clock)
        await _require_actor(interactive_token, command.subject.user_id, command.subject.actor_id)
        return service

    async def _admitted(
        self, session: AsyncSession, reader: CheckpointedShowrunnerGrantReader, subject: q.RunCompletionSubject
    ) -> list[AdmittedObservation]:
        repository = QualityRunRepository(session)
        admitted: list[AdmittedObservation] = []
        for binding in subject.observations:
            scope = (subject.user_id, subject.project_name)
            if binding.observation_type == q.ObservationType.TECHNICAL:
                observation = await repository.technical_observation(
                    user_id=scope[0], project_name=scope[1], observation_id=binding.observation_id
                )
                if observation is None:
                    raise RequiredEvidenceMissingError()
                digest = compute_digest("m10.technical-observation.v1", observation)
                admitted.append(AdmittedObservation(observation, q.AssessorClass.DETERMINISTIC))
            elif binding.observation_type == q.ObservationType.NARRATIVE:
                found = await repository.human_observation(
                    user_id=scope[0], project_name=scope[1], observation_id=binding.observation_id
                )
                if found is None:
                    raise RequiredEvidenceMissingError()
                observation, digest, grant_digest = found
                current = await _grant(reader, session, GrantScopeV1(scope[0], scope[1], observation.assessor_identity))
                if current != grant_digest:
                    raise RequiredEvidenceMissingError()
                admitted.append(AdmittedObservation(observation, q.AssessorClass.HUMAN))
            else:
                raise RequiredEvidenceMissingError()
            if digest != binding.observation_digest or (binding.requirement_id, binding.slot_id) != (
                observation.requirement_id,
                observation.slot_id,
            ):
                raise RequiredEvidenceMissingError()
        return admitted

    async def complete(self, command: q.CompleteRunCommand) -> q.QualityRun:
        command = q.CompleteRunCommand.model_validate(command)
        if canonical_json_bytes(command) != canonical_json_bytes(self._command):
            raise RequiredEvidenceMissingError()
        subject = command.subject
        await _require_actor(self._token, subject.user_id, subject.actor_id)
        key = RunCommandKey(
            subject.user_id, subject.project_name, subject.actor_id, "COMPLETE_RUN", command.command.command_id
        )
        digest = command.command.request_digest
        reader = await self._grant_reader()
        async with self._sessions() as session, session.begin():
            await _require_postgresql_transaction(session)
            repository = QualityRunRepository(session)
            await repository.lock_command(key)
            stored = await repository.receipt(key, digest)
            if stored is not None:
                run = await repository.run(
                    user_id=subject.user_id, project_name=subject.project_name, run_id=stored.result_ref
                )
                if run is None:
                    raise RequiredEvidenceMissingError()
                return run
            await repository.lock_head(
                user_id=subject.user_id,
                project_name=subject.project_name,
                subject_digest=subject.subject_digest,
                profile_id=subject.profile_id,
            )
            profile = await QualityProfileRepository(session).get_revision(
                user_id=subject.user_id,
                project_name=subject.project_name,
                profile_id=subject.profile_id,
                revision=subject.profile_revision,
            )
            if profile is None or profile.profile_digest != subject.profile_digest:
                raise ProfileStaleError()
            if not await _subject_current(session, subject.subject):
                raise SubjectStaleError()
            run = close_run(
                profile,
                subject.subject,
                await self._admitted(session, reader, subject),
                run_id=subject.run_id,
                completed_at=self._clock(),
            )
            if (
                run.subject_digest,
                run.observation_closure_digest,
                run.requirements_digest,
                run.execution_refs,
            ) != (
                subject.subject_digest,
                subject.observation_closure_digest,
                subject.requirements_digest,
                tuple(sorted(subject.execution_refs, key=lambda item: item.encode("utf-8"))),
            ):
                raise RequiredEvidenceMissingError()
            await _require_actor(self._token, subject.user_id, subject.actor_id)
            current = await repository.head(
                user_id=subject.user_id,
                project_name=subject.project_name,
                subject_digest=run.subject_digest,
                profile_id=run.profile_id,
            )
            await repository.append_run(key, digest, run, expected_run_id=current, sealed_at=run.completed_at)
            return run


async def run_validity(
    sessions: async_sessionmaker[AsyncSession],
    grant_reader: GrantReaderFactory,
    *,
    user_id: str,
    project_name: str,
    run_id: str,
    now: datetime,
) -> RunValidity:
    """Recompute a sealed run's operational validity; the historical run itself never changes."""
    reader = await grant_reader()
    async with sessions() as session, session.begin():
        await _require_postgresql_transaction(session)
        repository = QualityRunRepository(session)
        run = await repository.run(user_id=user_id, project_name=project_name, run_id=run_id)
        if run is None:
            raise RequiredEvidenceMissingError()
        profile = await QualityProfileRepository(session).get_revision(
            user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=run.profile_revision
        )
        if profile is None:
            raise RequiredEvidenceMissingError()
        observations: list[q.TechnicalObservation | q.NarrativeObservation] = []
        intact = True
        for result in run.slot_results:
            for observation_id, expected in zip(result.observation_refs, result.observation_digests, strict=True):
                try:
                    technical = await repository.technical_observation(
                        user_id=user_id, project_name=project_name, observation_id=observation_id
                    )
                    if technical is not None:
                        intact &= compute_digest("m10.technical-observation.v1", technical) == expected
                        observations.append(technical)
                        continue
                    found = await repository.human_observation(
                        user_id=user_id, project_name=project_name, observation_id=observation_id
                    )
                    if found is None:
                        intact = False
                        continue
                    grant = await _grant(
                        reader, session, GrantScopeV1(user_id, project_name, found[0].assessor_identity)
                    )
                    intact &= found[1] == expected and grant == found[2]
                    observations.append(found[0])
                except RequiredEvidenceMissingError:
                    intact = False
        head = await repository.head(
            user_id=user_id, project_name=project_name, subject_digest=run.subject_digest, profile_id=run.profile_id
        )
        current_profile = (
            await session.execute(
                select(QualityProfileHeadModel.current_revision).filter_by(
                    user_id=user_id, project_name=project_name, profile_id=run.profile_id
                )
            )
        ).scalar_one_or_none()
        reevaluates = False
        if current_profile is not None and current_profile > run.profile_revision:
            newest = await QualityProfileRepository(session).get_revision(
                user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=current_profile
            )
            reevaluates = newest is not None and newest.supersession_effect == q.SupersessionEffect.REEVALUATE_CURRENT
        inputs = ValidityInputs(
            evidence_intact=intact,
            subject_current=await _subject_current(session, run.subject),
            newer_run=head != run.run_id,
            newer_profile_reevaluates=reevaluates,
        )
        return project_validity(run, profile, observations, inputs, now=now)


__all__ = ["HUMAN_ASSESSOR_VERSION", "HumanObservationService", "QualityRunService", "run_validity"]
