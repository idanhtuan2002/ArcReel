"""Activated Governance custody for scoped production actors, separate from Human grants."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_run import ProductionRunModel
from lib.db.repositories.automation_grants import AutomationGrantRepository
from r2.automation.authorization import authorization_subject_digest, automation_principal, grant_request_digest
from r2.automation.identity import policy_digest
from r2.contracts.automation import (
    AuthorizationSubject,
    AutomationAuthorizationV1,
    AutomationGrant,
    GrantRequest,
    RunScope,
    RunSnapshot,
    RunStatus,
)
from r2.governance.grant_transition import GrantScopeV1
from server.auth import get_current_interactive_user
from server.services.governance_grants import CheckpointedShowrunnerGrantReader
from server.services.governance_startup import verify_governance_activated_startup

_ACTIVATED = object()


async def _now(session: AsyncSession) -> datetime:
    if session.get_bind().dialect.name != "postgresql" or not session.in_transaction():
        raise PermissionError("AUTOMATION_POSTGRESQL_TRANSACTION_REQUIRED")
    now = await session.scalar(select(func.clock_timestamp()))
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise PermissionError("AUTOMATION_DATABASE_TIME_UNAVAILABLE")
    return now


async def _run_locked(session: AsyncSession, scope: RunScope) -> tuple[ProductionRunModel, RunSnapshot]:
    row = (
        await session.execute(
            select(ProductionRunModel)
            .where(
                ProductionRunModel.user_id == scope.user_id,
                ProductionRunModel.project_name == scope.project_name,
                ProductionRunModel.run_id == scope.run_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise PermissionError("AUTOMATION_RUN_UNAVAILABLE")
    run = RunSnapshot.model_validate_json(row.snapshot_json)
    if (
        run.user_id,
        run.project_name,
        run.run_id,
        run.version,
        run.generation,
        run.fencing_epoch,
        run.status.value,
        run.stage.value,
        run.input_digest,
        policy_digest(run.policy),
    ) != (
        row.user_id,
        row.project_name,
        row.run_id,
        row.version,
        row.generation,
        row.fencing_epoch,
        row.status,
        row.stage,
        row.input_digest,
        row.policy_digest,
    ):
        raise PermissionError("AUTOMATION_RUN_INTEGRITY_FAILED")
    return row, run


class RunAutomationAuthority:
    """Owner lock order: owner heads, signed parent, child head, run, decision."""

    def __init__(self, reader: CheckpointedShowrunnerGrantReader, *, activation: object) -> None:
        if activation is not _ACTIVATED or type(reader) is not CheckpointedShowrunnerGrantReader:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        self._reader = reader

    async def require_locked(
        self, session: AsyncSession, *, subject: AuthorizationSubject
    ) -> AutomationAuthorizationV1:
        subject = AuthorizationSubject.model_validate(subject)
        await _now(session)
        scope = RunScope(user_id=subject.user_id, project_name=subject.project_name, run_id=subject.run_id)
        repository = AutomationGrantRepository(session)
        observed = await repository.head(scope)
        if observed is None:
            raise PermissionError("AUTOMATION_GRANT_UNAVAILABLE")
        parent = await self._reader.require_current_locked(
            session, scope=GrantScopeV1(subject.user_id, subject.project_name, observed.issuer_id)
        )
        grant = await repository.head(scope, lock=True)
        if grant is None or grant != observed:
            raise PermissionError("AUTOMATION_GRANT_MOVED")
        row, run = await _run_locked(session, scope)
        await repository.require_intent(subject)
        now = await _now(session)
        if (
            grant.state != "ACTIVE"
            or not grant.issued_at <= now < grant.expires_at
            or parent.body.expires_at is None
            or now >= datetime.fromisoformat(parent.body.expires_at)
            or (parent.body.sequence, parent.event_digest) != (grant.parent_sequence, grant.parent_event_digest)
            or (subject.grant_id, subject.grant_version) != (grant.grant_id, grant.version)
            or subject.operation not in grant.operations
            or subject.operation.value != run.stage.value
            or row.lease_owner is None
            or row.lease_until is None
            or row.lease_until <= now
            or (subject.expected_run_version, subject.generation, subject.input_digest, subject.policy_digest)
            != (run.version, run.generation, run.input_digest, policy_digest(run.policy))
            or (grant.input_digest, grant.policy_digest) != (run.input_digest, policy_digest(run.policy))
            or run.status not in {RunStatus.RUNNING, RunStatus.WAITING_TASK}
        ):
            raise PermissionError("AUTOMATION_AUTHORITY_NOT_CURRENT")
        return await repository.record(
            AutomationAuthorizationV1(
                principal=grant.principal,
                subject=subject,
                request_digest=authorization_subject_digest(subject),
                parent_sequence=grant.parent_sequence,
                parent_event_digest=grant.parent_event_digest,
                admitted_at=now,
            )
        )


class AutomationGrantCustodian:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        read_directory: Path,
        socket_directory: Path,
        expected_uid: int,
        expected_gid: int,
    ) -> None:
        self._sessions = sessions
        self._read_directory, self._socket_directory = read_directory, socket_directory
        self._expected_uid, self._expected_gid = expected_uid, expected_gid
        self._reader: CheckpointedShowrunnerGrantReader | None = None

    async def activate(self) -> None:
        self._reader = None
        reader = await verify_governance_activated_startup(
            self._read_directory,
            self._socket_directory,
            session_factory=self._sessions,
            expected_uid=self._expected_uid,
            expected_gid=self._expected_gid,
        )
        if type(reader) is not CheckpointedShowrunnerGrantReader:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        self._reader = reader

    def authority(self) -> RunAutomationAuthority:
        if self._reader is None:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        return RunAutomationAuthority(self._reader, activation=_ACTIVATED)

    async def _actor(self, token: str | None, user_id: str, issuer_id: str) -> None:
        try:
            actor = await get_current_interactive_user(token)
        except HTTPException:
            raise PermissionError("AUTOMATION_INTERACTIVE_SHOWRUNNER_REQUIRED") from None
        if (actor.id, actor.sub) != (user_id, issuer_id):
            raise PermissionError("AUTOMATION_INTERACTIVE_SHOWRUNNER_REQUIRED")

    async def issue(self, *, interactive_token: str | None, request: GrantRequest) -> AutomationGrant:
        request = GrantRequest.model_validate(request)
        await self._actor(interactive_token, request.user_id, request.issuer_id)
        await self.activate()
        async with self._sessions() as session, session.begin():
            return await self.issue_locked(session, interactive_token=interactive_token, request=request)

    async def issue_locked(
        self, session: AsyncSession, *, interactive_token: str | None, request: GrantRequest
    ) -> AutomationGrant:
        """Start callers lock the parent before creating the run in this same transaction."""
        request = GrantRequest.model_validate(request)
        await self._actor(interactive_token, request.user_id, request.issuer_id)
        if self._reader is None:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        await _now(session)
        parent = await self._reader.require_current_locked(
            session, scope=GrantScopeV1(request.user_id, request.project_name, request.issuer_id)
        )
        scope = RunScope(user_id=request.user_id, project_name=request.project_name, run_id=request.run_id)
        repository = AutomationGrantRepository(session)
        previous = await repository.head(scope, lock=True)
        row, run = await _run_locked(session, scope)
        now = await _now(session)
        await self._actor(interactive_token, request.user_id, request.issuer_id)
        digest = grant_request_digest(request)
        if (
            parent.body.expires_at is None
            or not now < request.expires_at <= datetime.fromisoformat(parent.body.expires_at)
            or (parent.body.sequence, parent.event_digest)
            != (
                previous.parent_sequence if previous else parent.body.sequence,
                previous.parent_event_digest if previous else parent.event_digest,
            )
            or row.start_command_id != request.command_id
            or (request.input_digest, request.policy_digest) != (run.input_digest, policy_digest(run.policy))
        ):
            raise PermissionError("AUTOMATION_DELEGATION_SCOPE_MISMATCH")
        if previous is not None:
            if previous.request_digest != digest or previous.state != "ACTIVE" or now >= previous.expires_at:
                raise PermissionError("AUTOMATION_DELEGATION_REPLAY_CONFLICT")
            return previous
        if request.expected_run_version != run.version or run.status is not RunStatus.PENDING:
            raise PermissionError("AUTOMATION_START_MOVED")
        grant = AutomationGrant(
            user_id=run.user_id,
            project_name=run.project_name,
            run_id=run.run_id,
            grant_id=str(uuid5(NAMESPACE_URL, "r2.automation-grant.v1:" + run.run_id)),
            version=1,
            state="ACTIVE",
            principal=automation_principal(run.run_id),
            issuer_id=request.issuer_id,
            start_command_id=request.command_id,
            request_digest=digest,
            parent_sequence=parent.body.sequence,
            parent_event_digest=parent.event_digest,
            policy_digest=request.policy_digest,
            input_digest=request.input_digest,
            operations=request.operations,
            issued_at=now,
            expires_at=request.expires_at,
        )
        await repository.append(grant, previous=None)
        return grant

    async def revoke(self, *, interactive_token: str | None, run_id: str, expected_version: int) -> AutomationGrant:
        try:
            actor = await get_current_interactive_user(interactive_token)
        except HTTPException:
            raise PermissionError("AUTOMATION_INTERACTIVE_SHOWRUNNER_REQUIRED") from None
        await self.activate()
        if self._reader is None:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(ProductionRunModel).where(
                        ProductionRunModel.run_id == run_id, ProductionRunModel.user_id == actor.id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise PermissionError("AUTOMATION_RUN_UNAVAILABLE")
            await self._reader.require_current_locked(
                session, scope=GrantScopeV1(actor.id, row.project_name, actor.sub)
            )
            scope = RunScope(user_id=actor.id, project_name=row.project_name, run_id=run_id)
            repository = AutomationGrantRepository(session)
            grant = await repository.head(scope, lock=True)
            await self._actor(interactive_token, actor.id, actor.sub)
            if grant is None or grant.issuer_id != actor.sub or grant.version != expected_version:
                raise PermissionError("AUTOMATION_GRANT_MOVED")
            if grant.state == "REVOKED":
                return grant
            revoked = grant.model_copy(update={"version": grant.version + 1, "state": "REVOKED"})
            await repository.append(revoked, previous=grant)
            return revoked
