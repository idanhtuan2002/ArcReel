"""Request-bound Human observation recording and run completion over re-verified stored evidence.

Both services re-authenticate the interactive JWT, use PostgreSQL as the only authority and replay a
stored receipt before activating live governance authority. New writes take the scoped command lock, then
the sorted master authority rows, then the profile, then the run head, and revalidate under those guards.
Human qualification is a current signed HUMAN_SHOWRUNNER grant. Metadata and content-basis authority is
the file manifest projection (ADR-0096), cross-checked against the database master head.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.artifact_manifest import ProjectArtifactManifestAdapter
from lib.db.models.quality import QualityProfileHeadModel
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_runs import QualityRunRepository, RunCommandKey
from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.exploration import uuid7
from r2.contracts.artifact_metadata import R2ArtifactMetadata
from r2.governance.grant_transition import GrantScopeV1
from r2.host_hardening.master_resolver import DatabaseMasterResolver, MasterDivergedError
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.errors import M10Error, ProfileStaleError, RequiredEvidenceMissingError, SubjectStaleError
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
from server.services.master_authority import MasterSupersededError, file_master_projection, lock_current_master_rows

HUMAN_ASSESSOR_VERSION = "m10.human-rubric.v1"

type GrantReaderFactory = Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]


async def _require_actor(token: str | None, user_id: str, actor_id: str) -> None:
    try:
        user = await get_current_interactive_user(token)
    except HTTPException:
        raise RequiredEvidenceMissingError() from None
    if (user.id, user.sub) != (user_id, actor_id):
        raise RequiredEvidenceMissingError()


def _require_postgresql_transaction(session: AsyncSession) -> None:
    if session.get_bind().dialect.name != "postgresql" or not session.in_transaction():
        raise RequiredEvidenceMissingError()


def _heads(subject: q.AssessedSubject) -> tuple[q.MasterHeadSnapshot, ...]:
    binding = subject.master_binding
    return tuple(sorted((binding.root, *binding.dependency_heads), key=lambda head: head.artifact_key))


async def _lock_masters(session: AsyncSession, subject: q.AssessedSubject) -> None:
    """Hold the sorted master authority rows of every consumed head through commit."""
    binding = subject.master_binding
    try:
        await lock_current_master_rows(
            session,
            user_id=binding.user_id,
            project_name=binding.project_name,
            artifact_keys=[head.artifact_key for head in _heads(subject)],
        )
    except MasterSupersededError:
        raise SubjectStaleError() from None


def _manifest_metadata(project_root: Path) -> Mapping[str, object]:
    entries = ProjectArtifactManifestAdapter(project_root).snapshot_entries()
    return {key.encode(): entry.r2 for key, entry in entries.items()}


async def _subject_authoritative(session: AsyncSession, project_root: Path, subject: q.AssessedSubject) -> bool:
    """Every head is the database master (with the manifest projection agreeing) and every embedded
    metadata body equals the manifest's semantic metadata for that artifact."""
    binding = subject.master_binding
    manifest = await asyncio.to_thread(_manifest_metadata, project_root)
    for snapshot in binding.metadata_snapshots:
        stored = manifest.get(snapshot.artifact_key)
        try:
            if stored is None or R2ArtifactMetadata.model_validate(stored) != R2ArtifactMetadata.model_validate(
                snapshot.body.model_dump(mode="python")
            ):
                return False
        except ValidationError:
            return False
    resolver = DatabaseMasterResolver(
        authorities=MasterAuthorityRepository(session), legacy_projection=file_master_projection(project_root, session)
    )
    for head in _heads(subject):
        try:
            current = await resolver.get_exact(
                user_id=binding.user_id, project_name=binding.project_name, artifact_key=head.artifact_key
            )
        except MasterDivergedError:
            return False
        if current is None or canonical_json_bytes(current) != canonical_json_bytes(head):
            return False
    return True


async def _require_profile(session: AsyncSession, profile: q.QualityProfileRevision) -> None:
    stored = await QualityProfileRepository(session).get_revision(
        user_id=profile.user_id,
        project_name=profile.project_name,
        profile_id=profile.profile_id,
        revision=profile.revision,
    )
    if stored is None or canonical_json_bytes(stored) != canonical_json_bytes(profile):
        raise ProfileStaleError()


async def _grant(reader: CheckpointedShowrunnerGrantReader, session: AsyncSession, scope: GrantScopeV1) -> str:
    try:
        event = await reader.require_current_locked(session, scope=scope)
    except ShowrunnerGrantUnavailableError:
        raise RequiredEvidenceMissingError() from None
    return event.event_digest


def _same_profile(profile: q.QualityProfileRevision, profile_id: str, revision: int, digest: str) -> bool:
    return (profile.profile_id, profile.revision, profile.profile_digest) == (profile_id, revision, digest)


class HumanObservationService:
    """Records one qualified showrunner rubric observation; caller identities and digests are not trusted."""

    def __init__(
        self,
        request: HumanObservationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        project_root: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        try:
            verify_caches(request.subject)
            verify_caches(request.profile)
        except ValueError:
            raise RequiredEvidenceMissingError() from None
        self._request = HumanObservationRequest.model_validate(request)
        self._sessions = sessions
        self._token = interactive_token
        self._grant_reader = grant_reader
        self._project_root = project_root
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    async def for_request(
        cls,
        request: HumanObservationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        project_root: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> Self:
        service = cls(
            request,
            sessions,
            interactive_token=interactive_token,
            grant_reader=grant_reader,
            project_root=project_root,
            clock=clock,
        )
        await _require_actor(interactive_token, service._request.user_id, service._request.actor_id)
        return service

    def _require_slot(self) -> None:
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

    async def _replayed(self, repository: QualityRunRepository, key: RunCommandKey, digest: str):
        stored = await repository.receipt(key, digest)
        if stored is None:
            return None
        found = await repository.human_observation(
            user_id=key.user_id, project_name=key.project_name, observation_id=stored.result_ref
        )
        if found is None or found.digest != stored.result_digest:
            raise RequiredEvidenceMissingError()
        return found.observation

    async def record(self, request: HumanObservationRequest) -> q.NarrativeObservation:
        request = HumanObservationRequest.model_validate(request)
        if canonical_json_bytes(request) != canonical_json_bytes(self._request):
            raise RequiredEvidenceMissingError()
        await _require_actor(self._token, request.user_id, request.actor_id)
        digest = human_request_digest(request)
        key = RunCommandKey(
            request.user_id, request.project_name, request.actor_id, "RECORD_HUMAN_OBSERVATION", request.command_id
        )
        async with self._sessions() as session, session.begin():
            _require_postgresql_transaction(session)
            repository = QualityRunRepository(session)
            await repository.lock_command(key)
            replayed = await self._replayed(repository, key, digest)
        if replayed is not None:
            return replayed
        self._require_slot()
        reader = await self._grant_reader()
        async with self._sessions() as session, session.begin():
            _require_postgresql_transaction(session)
            repository = QualityRunRepository(session)
            await repository.lock_command(key)
            replayed = await self._replayed(repository, key, digest)
            if replayed is not None:
                return replayed
            await _lock_masters(session, request.subject)
            await _require_profile(session, request.profile)
            if not await _subject_authoritative(session, self._project_root, request.subject):
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
                key, digest, observation, grant_event_digest=grant, profile=request.profile, recorded_at=now
            )
            return observation


async def _admit(
    session: AsyncSession,
    reader: CheckpointedShowrunnerGrantReader,
    *,
    user_id: str,
    project_name: str,
    profile: q.QualityProfileRevision,
    binding: q.ObservationBinding,
) -> AdmittedObservation:
    """Re-verify one named observation and require it was produced under exactly this profile revision."""
    repository = QualityRunRepository(session)
    if binding.observation_type == q.ObservationType.TECHNICAL:
        found = await repository.technical_observation(
            user_id=user_id, project_name=project_name, observation_id=binding.observation_id
        )
        if found is None:
            raise RequiredEvidenceMissingError()
        observation, probe = found
        if canonical_json_bytes(probe.profile) != canonical_json_bytes(profile):
            raise RequiredEvidenceMissingError()
        digest = compute_digest("m10.technical-observation.v1", observation)
        admitted = AdmittedObservation(observation, q.AssessorClass.DETERMINISTIC)
    elif binding.observation_type == q.ObservationType.NARRATIVE:
        stored = await repository.human_observation(
            user_id=user_id, project_name=project_name, observation_id=binding.observation_id
        )
        if stored is None or not _same_profile(
            profile, stored.profile_id, stored.profile_revision, stored.profile_digest
        ):
            raise RequiredEvidenceMissingError()
        current = await _grant(
            reader, session, GrantScopeV1(user_id, project_name, stored.observation.assessor_identity)
        )
        if current != stored.grant_event_digest:
            raise RequiredEvidenceMissingError()
        observation, digest = stored.observation, stored.digest
        admitted = AdmittedObservation(observation, q.AssessorClass.HUMAN)
    else:
        raise RequiredEvidenceMissingError()
    if digest != binding.observation_digest or (binding.requirement_id, binding.slot_id) != (
        observation.requirement_id,
        observation.slot_id,
    ):
        raise RequiredEvidenceMissingError()
    return admitted


class QualityRunService:
    """Seals a run from stored evidence named by the completion command; nothing in the command is trusted."""

    def __init__(
        self,
        command: q.CompleteRunCommand,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        project_root: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        try:
            verify_caches(command)
        except ValueError:
            raise RequiredEvidenceMissingError() from None
        self._command = q.CompleteRunCommand.model_validate(command)
        self._sessions = sessions
        self._token = interactive_token
        self._grant_reader = grant_reader
        self._project_root = project_root
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    async def for_request(
        cls,
        command: q.CompleteRunCommand,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        grant_reader: GrantReaderFactory,
        project_root: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> Self:
        service = cls(
            command,
            sessions,
            interactive_token=interactive_token,
            grant_reader=grant_reader,
            project_root=project_root,
            clock=clock,
        )
        await _require_actor(interactive_token, command.subject.user_id, command.subject.actor_id)
        return service

    @staticmethod
    async def _replayed(repository: QualityRunRepository, key: RunCommandKey, digest: str) -> q.QualityRun | None:
        stored = await repository.receipt(key, digest)
        if stored is None:
            return None
        run = await repository.run(user_id=key.user_id, project_name=key.project_name, run_id=stored.result_ref)
        if run is None or (run.run_id, stored.result_digest) != (stored.result_ref, stored.result_digest):
            raise RequiredEvidenceMissingError()
        return run

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
        async with self._sessions() as session, session.begin():
            _require_postgresql_transaction(session)
            repository = QualityRunRepository(session)
            await repository.lock_command(key)
            replayed = await self._replayed(repository, key, digest)
        if replayed is not None:
            return replayed
        reader = await self._grant_reader()
        async with self._sessions() as session, session.begin():
            _require_postgresql_transaction(session)
            repository = QualityRunRepository(session)
            await repository.lock_command(key)
            replayed = await self._replayed(repository, key, digest)
            if replayed is not None:
                return replayed
            await _lock_masters(session, subject.subject)
            profile = await QualityProfileRepository(session).get_revision(
                user_id=subject.user_id,
                project_name=subject.project_name,
                profile_id=subject.profile_id,
                revision=subject.profile_revision,
            )
            if profile is None or profile.profile_digest != subject.profile_digest:
                raise ProfileStaleError()
            await repository.lock_head(
                user_id=subject.user_id,
                project_name=subject.project_name,
                subject_digest=subject.subject_digest,
                profile_id=subject.profile_id,
            )
            if not await _subject_authoritative(session, self._project_root, subject.subject):
                raise SubjectStaleError()
            admitted = [
                await _admit(
                    session,
                    reader,
                    user_id=subject.user_id,
                    project_name=subject.project_name,
                    profile=profile,
                    binding=binding,
                )
                for binding in subject.observations
            ]
            run = close_run(profile, subject.subject, admitted, run_id=subject.run_id, completed_at=self._clock())
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
    project_root: Path,
    user_id: str,
    project_name: str,
    run_id: str,
) -> RunValidity:
    """Recompute a sealed run's operational validity at database time; the historical run never changes."""
    reader = await grant_reader()
    async with sessions() as session, session.begin():
        _require_postgresql_transaction(session)
        now = (await session.execute(select(func.now()))).scalar_one()
        repository = QualityRunRepository(session)
        run = await repository.run(user_id=user_id, project_name=project_name, run_id=run_id)
        if run is None:
            raise RequiredEvidenceMissingError()
        profiles = QualityProfileRepository(session)
        try:
            profile = await profiles.get_revision(
                user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=run.profile_revision
            )
        except (M10Error, ValueError):
            profile = None
        if profile is None or profile.profile_digest != run.profile_digest:
            return RunValidity("INVALIDATED", ("PROFILE_NOT_INTACT",))
        kinds = {
            (requirement.requirement_id, slot.slot_id): slot.kind
            for requirement in profile.policy.assessment_requirements
            for slot in requirement.slots
        }
        types = {
            q.AssessorKind.TECHNICAL: q.ObservationType.TECHNICAL,
            q.AssessorKind.NARRATIVE: q.ObservationType.NARRATIVE,
        }
        observations: list[q.TechnicalObservation | q.NarrativeObservation] = []
        intact = True
        for result in run.slot_results:
            observation_type = types.get(kinds.get((result.requirement_id, result.slot_id)))  # pyright: ignore[reportArgumentType]
            for observation_id, expected in zip(result.observation_refs, result.observation_digests, strict=True):
                if observation_type is None:
                    intact = False
                    continue
                binding = q.ObservationBinding(
                    observation_id=observation_id,
                    observation_type=observation_type,
                    observation_digest=expected,
                    requirement_id=result.requirement_id,
                    slot_id=result.slot_id,
                )
                try:
                    admitted = await _admit(
                        session, reader, user_id=user_id, project_name=project_name, profile=profile, binding=binding
                    )
                    observations.append(admitted.observation)
                except M10Error:
                    intact = False
        head = await repository.head(
            user_id=user_id, project_name=project_name, subject_digest=run.subject_digest, profile_id=run.profile_id
        )
        current_revision = (
            await session.execute(
                select(QualityProfileHeadModel.current_revision).filter_by(
                    user_id=user_id, project_name=project_name, profile_id=run.profile_id
                )
            )
        ).scalar_one_or_none()
        reevaluates = False
        for revision in range(run.profile_revision + 1, (current_revision or 0) + 1):
            later = await profiles.get_revision(
                user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=revision
            )
            if later is None or later.supersession_effect == q.SupersessionEffect.REEVALUATE_CURRENT:
                reevaluates = True
                break
        inputs = ValidityInputs(
            evidence_intact=intact,
            subject_current=await _subject_authoritative(session, project_root, run.subject),
            newer_run=head != run.run_id,
            newer_profile_reevaluates=reevaluates,
        )
        return project_validity(run, profile, observations, inputs, now=now)


__all__ = ["HUMAN_ASSESSOR_VERSION", "HumanObservationService", "QualityRunService", "run_validity"]
