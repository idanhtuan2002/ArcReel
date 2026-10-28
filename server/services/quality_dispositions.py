"""Human showrunner dispositions over exact current sealed runs, and the recomputed readiness projection.

Authorization follows the A3 publication custody: an interactive JWT, governance-activated startup, a
current signed HUMAN_SHOWRUNNER grant and a persisted lease of at most 30 seconds issued and admitted on
PostgreSQL time. Issuance replays a stored receipt first, then locks command, grant, master rows, profile
head, run head and disposition head in that order and revalidates everything before one atomic append.
There is no router, default registration, repair mutation or export here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Self

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.models.quality_runs import QualityRunHeadModel
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_dispositions import DispositionKey, QualityDispositionRepository
from lib.db.repositories.quality_runs import QualityRunRepository
from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.exploration import uuid7
from r2.governance.grant_transition import GrantScopeV1
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.dispositions import Readiness, evaluate_decision, project_readiness
from r2.quality.errors import DispositionStaleError, DispositionUnauthorizedError, M10Error, StaleHeadError
from r2.quality.runs import run_digest
from server.auth import get_current_interactive_user
from server.services.governance_grants import CheckpointedShowrunnerGrantReader, ShowrunnerGrantUnavailableError
from server.services.governance_startup import GovernanceStartupUnavailable, verify_governance_activated_startup
from server.services.quality_runs import lock_profile_head, lock_subject_masters, validity_in

DISPOSITION_POLICY_ID = "m10.disposition.interactive-human.v1"
DISPOSITION_POLICY_VERSION = "1"
_LEASE_SECONDS = 30

type GrantReaderFactory = Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]


def _key(request: q.DispositionAuthorizationRequest) -> DispositionKey:
    command = request.command
    return DispositionKey(command.user_id, command.project_name, command.actor_id, command.command_id)


class DispositionCustodian:
    """A request-bound authenticated wrapper; it is not itself an authorization."""

    def __init__(
        self,
        request: q.DispositionAuthorizationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        read_directory: Path,
        socket_directory: Path,
        expected_uid: int,
        expected_gid: int,
    ) -> None:
        try:
            verify_caches(request)
        except ValueError:
            raise DispositionUnauthorizedError() from None
        self._request = q.DispositionAuthorizationRequest.model_validate(request)
        self._binding = canonical_json_bytes(self._request)
        self._sessions = sessions
        self._token = interactive_token
        self._read_directory = read_directory
        self._socket_directory = socket_directory
        self._expected_uid = expected_uid
        self._expected_gid = expected_gid
        self._reader: CheckpointedShowrunnerGrantReader | None = None

    @classmethod
    async def for_request(
        cls,
        request: q.DispositionAuthorizationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        read_directory: Path,
        socket_directory: Path,
        expected_uid: int,
        expected_gid: int,
    ) -> Self:
        custodian = cls(
            request,
            sessions,
            interactive_token=interactive_token,
            read_directory=read_directory,
            socket_directory=socket_directory,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        await custodian.require_actor(request)
        return custodian

    async def require_actor(self, request: q.DispositionAuthorizationRequest) -> None:
        normalized = q.DispositionAuthorizationRequest.model_validate(request)
        if canonical_json_bytes(normalized) != self._binding:
            raise DispositionUnauthorizedError()
        try:
            user = await get_current_interactive_user(self._token)
        except HTTPException:
            raise DispositionUnauthorizedError() from None
        if (user.id, user.sub) != (normalized.command.user_id, normalized.command.actor_id):
            raise DispositionUnauthorizedError()

    @property
    def reader(self) -> CheckpointedShowrunnerGrantReader:
        if self._reader is None:
            raise DispositionUnauthorizedError()
        return self._reader

    async def authorize_disposition(
        self, request: q.DispositionAuthorizationRequest
    ) -> q.DispositionAuthorizationLease:
        """Activate governance, read the current grant and persist a DB-time lease of at most 30 seconds."""
        await self.require_actor(request)
        try:
            reader = await verify_governance_activated_startup(
                self._read_directory,
                self._socket_directory,
                session_factory=self._sessions,
                expected_uid=self._expected_uid,
                expected_gid=self._expected_gid,
            )
        except GovernanceStartupUnavailable:
            raise DispositionUnauthorizedError() from None
        if type(reader) is not CheckpointedShowrunnerGrantReader:
            raise DispositionUnauthorizedError()
        self._reader = reader
        command = request.command
        async with self._sessions() as session, session.begin():
            repository = QualityDispositionRepository(session)
            try:
                grant = await reader.require_current_locked(
                    session, scope=GrantScopeV1(command.user_id, command.project_name, command.actor_id)
                )
            except ShowrunnerGrantUnavailableError:
                raise DispositionUnauthorizedError() from None
            await self.require_actor(request)
            issued_at = await repository.database_now()
            deadline = issued_at + timedelta(seconds=_LEASE_SECONDS)
            if grant.body.expires_at is not None:
                deadline = min(deadline, datetime.fromisoformat(grant.body.expires_at))
            if deadline <= issued_at:
                raise DispositionUnauthorizedError()
            lease = q.DispositionAuthorizationLease(
                authorization_id=uuid7(),
                action="QUALITY_DISPOSITION",
                user_id=command.user_id,
                project_name=command.project_name,
                actor_id=command.actor_id,
                command_id=command.command_id,
                request_digest=command.request_digest,
                subject_digest=compute_digest("m10.disposition-subject.v1", request.subject),
                policy_id=DISPOSITION_POLICY_ID,
                policy_version=DISPOSITION_POLICY_VERSION,
                evidence_digest=grant.event_digest,
                issued_at=issued_at,
                admit_not_after=deadline,
            )
            await repository.record_authorization(lease, grant_sequence=grant.body.sequence)
        return lease

    async def admit(
        self, session: AsyncSession, request: q.DispositionAuthorizationRequest, lease: q.DispositionAuthorizationLease
    ) -> datetime:
        """Under the write transaction: the stored lease, the same current grant and the window on DB time."""
        await self.require_actor(request)
        lease = q.DispositionAuthorizationLease.model_validate(lease)
        command = request.command
        repository = QualityDispositionRepository(session)
        stored = await repository.load_authorization(
            user_id=command.user_id, project_name=command.project_name, authorization_id=lease.authorization_id
        )
        if (
            stored is None
            or stored[0] != lease
            or (lease.policy_id, lease.policy_version)
            != (
                DISPOSITION_POLICY_ID,
                DISPOSITION_POLICY_VERSION,
            )
        ):
            raise DispositionUnauthorizedError()
        if (lease.command_id, lease.request_digest, lease.subject_digest) != (
            command.command_id,
            command.request_digest,
            compute_digest("m10.disposition-subject.v1", request.subject),
        ):
            raise DispositionUnauthorizedError()
        try:
            grant = await self.reader.require_current_locked(
                session, scope=GrantScopeV1(command.user_id, command.project_name, command.actor_id)
            )
        except ShowrunnerGrantUnavailableError:
            raise DispositionUnauthorizedError() from None
        if (grant.body.sequence, grant.event_digest) != (stored[1], lease.evidence_digest):
            raise DispositionUnauthorizedError()
        now = await repository.database_now()
        if not lease.issued_at <= now <= lease.admit_not_after:
            raise DispositionUnauthorizedError()
        return now


class DispositionService:
    """Issues one Human disposition; nothing in the request is trusted beyond its bound identity."""

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, custodian: DispositionCustodian, project_root: Path
    ) -> None:
        self._sessions = sessions
        self._custodian = custodian
        self._project_root = project_root

    async def issue(self, request: q.DispositionAuthorizationRequest) -> q.QualityDisposition:
        await self._custodian.require_actor(request)
        key = _key(request)
        digest = request.command.request_digest
        async with self._sessions() as session, session.begin():
            repository = QualityDispositionRepository(session)
            await repository.lock_command(key)
            replayed = await repository.receipt(key, digest)
        if replayed is not None:
            return replayed
        lease = await self._custodian.authorize_disposition(request)
        subject = request.subject
        async with self._sessions() as session, session.begin():
            repository = QualityDispositionRepository(session)
            await repository.lock_command(key)
            replayed = await repository.receipt(key, digest)
            if replayed is not None:
                return replayed
            now = await self._custodian.admit(session, request, lease)
            run = await QualityRunRepository(session).run(
                user_id=subject.user_id, project_name=subject.project_name, run_id=subject.quality_run_id
            )
            if run is None or run_digest(run) != subject.quality_run_digest:
                raise DispositionStaleError()
            await lock_subject_masters(session, run.subject)
            await lock_profile_head(
                session, user_id=subject.user_id, project_name=subject.project_name, profile_id=subject.profile_id
            )
            head_run = (
                await session.execute(
                    select(QualityRunHeadModel.current_run_id)
                    .filter_by(
                        user_id=subject.user_id,
                        project_name=subject.project_name,
                        subject_digest=run.subject_digest,
                        profile_id=run.profile_id,
                    )
                    .with_for_update(read=True)
                )
            ).scalar_one_or_none()
            current, version = await repository.lock_head(
                user_id=subject.user_id,
                project_name=subject.project_name,
                subject_digest=run.subject_digest,
                profile_id=run.profile_id,
            )
            if head_run != run.run_id:
                raise DispositionStaleError()
            validity = await validity_in(
                session,
                self._custodian.reader,
                project_root=self._project_root,
                user_id=subject.user_id,
                project_name=subject.project_name,
                run_id=run.run_id,
            )
            if validity.state != "CURRENT":
                raise DispositionStaleError()
            profile = await QualityProfileRepository(session).get_revision(
                user_id=subject.user_id,
                project_name=subject.project_name,
                profile_id=run.profile_id,
                revision=run.profile_revision,
            )
            if profile is None:
                raise DispositionStaleError()
            evaluate_decision(profile, run, subject, now=now)
            if subject.expected_disposition_version != version:
                raise StaleHeadError()
            await self._custodian.require_actor(request)
            disposition = q.QualityDisposition(
                disposition_id=uuid7(),
                subject_digest=run.subject_digest,
                quality_run_id=run.run_id,
                quality_run_digest=subject.quality_run_digest,
                profile_digest=run.profile_digest,
                decision=subject.decision,
                waiver_bindings=subject.waiver_bindings,
                issuer_id=subject.actor_id,
                custodian_authorization_id=lease.authorization_id,
                custodian_policy_id=lease.policy_id,
                custodian_policy_version=lease.policy_version,
                custodian_evidence_digest=lease.evidence_digest,
                custodian_admitted_at=now,
                reason=subject.reason,
                issued_at=now,
                expires_at=subject.requested_expires_at,
                supersedes_disposition_id=current,
                profile_id=run.profile_id,
                profile_revision=run.profile_revision,
            )
            await repository.append(
                key, digest, disposition, authorization_id=lease.authorization_id, expected_version=version
            )
            return disposition


async def quality_readiness(
    sessions: async_sessionmaker[AsyncSession],
    grant_reader: GrantReaderFactory,
    *,
    project_root: Path,
    user_id: str,
    project_name: str,
    subject_digest: str,
    profile_id: str,
) -> Readiness:
    """Recompute readiness at database time from the head disposition, the head run and its validity."""
    reader = await grant_reader()
    async with sessions() as session, session.begin():
        dispositions = QualityDispositionRepository(session)
        runs = QualityRunRepository(session)
        now = await dispositions.database_now()
        head_run_id = await runs.head(
            user_id=user_id, project_name=project_name, subject_digest=subject_digest, profile_id=profile_id
        )
        try:
            disposition = await dispositions.head_disposition(
                user_id=user_id, project_name=project_name, subject_digest=subject_digest, profile_id=profile_id
            )
        except M10Error:
            return Readiness("NOT_READY", ("DISPOSITION_NOT_INTACT",), ())
        run_id = disposition.quality_run_id if disposition is not None else head_run_id
        if run_id is None:
            return Readiness("NOT_READY", ("NO_RUN",), ())
        run = await runs.run(user_id=user_id, project_name=project_name, run_id=run_id)
        profile = (
            None
            if run is None
            else await QualityProfileRepository(session).get_revision(
                user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=run.profile_revision
            )
        )
        if run is None or profile is None:
            return Readiness("NOT_READY", ("RUN_NOT_INTACT",), ())
        validity = await validity_in(
            session, reader, project_root=project_root, user_id=user_id, project_name=project_name, run_id=run.run_id
        )
        return project_readiness(
            disposition, profile, run, run_state=validity.state, run_is_head=head_run_id == run.run_id, now=now
        )


__all__ = [
    "DISPOSITION_POLICY_ID",
    "DISPOSITION_POLICY_VERSION",
    "DispositionCustodian",
    "DispositionService",
    "quality_readiness",
]
