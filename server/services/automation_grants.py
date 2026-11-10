"""Activated Governance custody for scoped production actors, separate from Human grants."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_run import ProductionRunModel
from lib.db.repositories.automation_grants import AutomationGrantRepository
from lib.db.repositories.autopilot import AutopilotRepository
from r2.automation.authorization import authorization_subject_digest, automation_principal, grant_request_digest
from r2.automation.identity import policy_digest
from r2.contracts.automation import (
    AuthorizationSubject,
    AutomationAuthorizationV1,
    AutomationGrant,
    AutomationMode,
    GrantRequest,
    RunScope,
    RunSnapshot,
    RunStatus,
)
from r2.contracts.autopilot import AutopilotDelegation, FilmAutopilot, StoryAutopilot, autopilot_command_id
from r2.governance.grant_signature import VerifiedGrantEventV1
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


async def _issue_first(
    repository: AutomationGrantRepository,
    request: GrantRequest,
    parent: VerifiedGrantEventV1,
    previous: AutomationGrant | None,
    run: RunSnapshot,
    now: datetime,
) -> AutomationGrant:
    """The run's first grant under the locked parent, or its identical replay."""
    digest = grant_request_digest(request)
    if (
        parent.body.expires_at is None
        or not now < request.expires_at <= datetime.fromisoformat(parent.body.expires_at)
        or (parent.body.sequence, parent.event_digest)
        != (
            previous.parent_sequence if previous else parent.body.sequence,
            previous.parent_event_digest if previous else parent.event_digest,
        )
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


class RunAutomationAuthority:
    """Owner lock order: owner heads, signed parent, child head, run, decision."""

    def __init__(self, reader: CheckpointedShowrunnerGrantReader, *, activation: object) -> None:
        if activation is not _ACTIVATED or type(reader) is not CheckpointedShowrunnerGrantReader:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        self._reader = reader

    @property
    def reader(self) -> CheckpointedShowrunnerGrantReader:
        """The activated signed grant reader owners re-verify Human evidence with."""
        return self._reader

    async def require_queued_task_current(self, session: AsyncSession, *, scope: RunScope) -> None:
        """A queued task of the run may execute: the run is active, its grant unexpired and still bound to the
        issuer's current, unexpired signed parent and to the run's input and policy."""
        observed = await AutomationGrantRepository(session).head(scope)
        if observed is None:
            raise PermissionError("AUTOMATION_GRANT_UNAVAILABLE")
        parent = await self._reader.require_current_locked(
            session, scope=GrantScopeV1(scope.user_id, scope.project_name, observed.issuer_id)
        )
        grant = await AutomationGrantRepository(session).head(scope, lock=True)
        if grant is None or grant != observed:
            raise PermissionError("AUTOMATION_GRANT_MOVED")
        _row, run = await _run_locked(session, scope)
        now = await _now(session)
        if (
            grant.state != "ACTIVE"
            or not grant.issued_at <= now < grant.expires_at
            or parent.body.expires_at is None
            or now >= datetime.fromisoformat(parent.body.expires_at)
            or (parent.body.sequence, parent.event_digest) != (grant.parent_sequence, grant.parent_event_digest)
            or (grant.input_digest, grant.policy_digest) != (run.input_digest, policy_digest(run.policy))
            or run.status not in {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_TASK}
        ):
            raise PermissionError("AUTOMATION_AUTHORITY_NOT_CURRENT")

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
        self._activation = asyncio.Lock()

    async def activate(self) -> None:
        """Re-verify custody; concurrent commands share one verification and keep the last verified reader."""
        async with self._activation:
            try:
                reader = await verify_governance_activated_startup(
                    self._read_directory,
                    self._socket_directory,
                    session_factory=self._sessions,
                    expected_uid=self._expected_uid,
                    expected_gid=self._expected_gid,
                )
            except BaseException:
                self._reader = None
                raise
            if type(reader) is not CheckpointedShowrunnerGrantReader:
                self._reader = None
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
        if row.start_command_id != request.command_id:
            raise PermissionError("AUTOMATION_DELEGATION_SCOPE_MISMATCH")
        return await _issue_first(repository, request, parent, previous, run, now)

    async def _delegation_parent_locked(
        self, session: AsyncSession, delegation: AutopilotDelegation
    ) -> VerifiedGrantEventV1:
        if self._reader is None:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        await _now(session)
        parent = await self._reader.require_current_locked(
            session, scope=GrantScopeV1(delegation.user_id, delegation.project_name, delegation.issuer_id)
        )
        current = await AutopilotRepository(session).current(delegation.user_id, delegation.project_name, lock=True)
        if (
            current != delegation
            or delegation.state != "ENABLED"
            or (parent.body.sequence, parent.event_digest)
            != (delegation.parent_sequence, delegation.parent_event_digest)
            or parent.body.expires_at is None
        ):
            raise PermissionError("AUTOMATION_DELEGATION_NOT_CURRENT")
        return parent

    async def require_delegation_locked(self, session: AsyncSession, *, delegation: AutopilotDelegation) -> datetime:
        """Lock the delegation's signed parent, then the delegation; returns the parent's expiry. A start creates its
        run after this, in the same transaction."""
        parent = await self._delegation_parent_locked(session, AutopilotDelegation.model_validate(delegation))
        assert parent.body.expires_at is not None
        return datetime.fromisoformat(parent.body.expires_at)

    async def issue_delegated_locked(
        self, session: AsyncSession, *, delegation: AutopilotDelegation, request: GrantRequest
    ) -> AutomationGrant:
        """ADR-0124: a run the autopilot scheduler starts under the project's enabled delegation, without a session.

        Lock order: signed parent, delegation, child head, run. The delegation must still be the project's current
        enabled version, its issuer, policy and parent grant event must still hold, and the run's start command must
        be one of the delegation's own."""
        request = GrantRequest.model_validate(request)
        delegation = AutopilotDelegation.model_validate(delegation)
        parent = await self._delegation_parent_locked(session, delegation)
        scope = RunScope(user_id=request.user_id, project_name=request.project_name, run_id=request.run_id)
        repository = AutomationGrantRepository(session)
        previous = await repository.head(scope, lock=True)
        row, run = await _run_locked(session, scope)
        now = await _now(session)
        if (
            (request.user_id, request.project_name, request.issuer_id)
            != (delegation.user_id, delegation.project_name, delegation.issuer_id)
            or request.policy_digest != delegation.policy_digest
            or not request.command_id.startswith(autopilot_command_id(delegation, 0).removesuffix("0"))
            or row.start_command_id != request.command_id
        ):
            raise PermissionError("AUTOMATION_DELEGATION_SCOPE_MISMATCH")
        return await _issue_first(repository, request, parent, previous, run, now)

    async def set_autopilot_locked(
        self,
        session: AsyncSession,
        *,
        interactive_token: str | None,
        user_id: str,
        project_name: str,
        command_id: str,
        enabled: bool,
        kind: Literal["story", "film"],
        mode: AutomationMode,
        policy_digest: str,
        story: StoryAutopilot | None = None,
        film: FilmAutopilot | None = None,
    ) -> AutopilotDelegation | None:
        """ADR-0124: the interactive Showrunner turns a project's autopilot on (under a current project or workspace
        grant, whose event the delegation records) or off (always allowed to the project's owner). The same command
        replays its version; turning off a project that is not on changes nothing."""
        try:
            actor = await get_current_interactive_user(interactive_token)
        except HTTPException:
            raise PermissionError("AUTOMATION_INTERACTIVE_SHOWRUNNER_REQUIRED") from None
        if actor.id != user_id:
            raise PermissionError("AUTOMATION_INTERACTIVE_SHOWRUNNER_REQUIRED")
        if self._reader is None:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        now = await _now(session)
        parent = (
            await self._reader.require_current_locked(session, scope=GrantScopeV1(user_id, project_name, actor.sub))
            if enabled
            else None
        )
        repository = AutopilotRepository(session)
        previous = await repository.current(user_id, project_name, lock=True)
        if previous is not None and previous.command_id == command_id:
            if previous.state != ("ENABLED" if enabled else "DISABLED") or previous.issuer_id != actor.sub:
                raise PermissionError("AUTOMATION_DELEGATION_REPLAY_CONFLICT")
            return previous
        if parent is None:
            if previous is None or previous.state == "DISABLED":
                return previous
            delegation = previous.model_copy(
                update={
                    "version": previous.version + 1,
                    "state": "DISABLED",
                    "issuer_id": actor.sub,
                    "command_id": command_id,
                    "created_at": now,
                }
            )
        else:
            delegation = AutopilotDelegation(
                user_id=user_id,
                project_name=project_name,
                version=1 if previous is None else previous.version + 1,
                state="ENABLED",
                kind=kind,
                issuer_id=actor.sub,
                command_id=command_id,
                parent_sequence=parent.body.sequence,
                parent_event_digest=parent.event_digest,
                mode=mode,
                policy_digest=policy_digest,
                story=story,
                film=film,
                created_at=now,
            )
        delegation = AutopilotDelegation.model_validate(delegation.model_dump())
        await self._actor(interactive_token, user_id, actor.sub)
        await repository.append(delegation, previous=previous)
        return delegation

    async def require_issuer_locked(
        self, session: AsyncSession, *, interactive_token: str | None, user_id: str, project_name: str
    ) -> tuple[str, datetime]:
        """Lock the interactive actor's current Showrunner grant; returns the issuer and its expiry."""
        try:
            actor = await get_current_interactive_user(interactive_token)
        except HTTPException:
            raise PermissionError("AUTOMATION_INTERACTIVE_SHOWRUNNER_REQUIRED") from None
        if actor.id != user_id:
            raise PermissionError("AUTOMATION_INTERACTIVE_SHOWRUNNER_REQUIRED")
        if self._reader is None:
            raise PermissionError("AUTOMATION_GOVERNANCE_NOT_ACTIVATED")
        await _now(session)
        parent = await self._reader.require_current_locked(
            session, scope=GrantScopeV1(user_id, project_name, actor.sub)
        )
        if parent.body.expires_at is None:
            raise PermissionError("AUTOMATION_DELEGATION_SCOPE_MISMATCH")
        return actor.sub, datetime.fromisoformat(parent.body.expires_at)

    async def renew_locked(
        self, session: AsyncSession, *, interactive_token: str | None, request: GrantRequest
    ) -> AutomationGrant:
        """Rebind the run's active delegation to its current policy and input after a user command."""
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
        _row, run = await _run_locked(session, scope)
        now = await _now(session)
        if previous is None or previous.state != "ACTIVE":
            raise PermissionError("AUTOMATION_GRANT_UNAVAILABLE")
        digest = grant_request_digest(request)
        if previous.request_digest == digest:
            return previous
        if (
            parent.body.expires_at is None
            or not now < request.expires_at <= datetime.fromisoformat(parent.body.expires_at)
            or (request.input_digest, request.policy_digest) != (run.input_digest, policy_digest(run.policy))
            or request.expected_run_version != run.version
            or not request.operations <= previous.operations
        ):
            raise PermissionError("AUTOMATION_DELEGATION_SCOPE_MISMATCH")
        renewed = previous.model_copy(
            update={
                "version": previous.version + 1,
                "issuer_id": request.issuer_id,
                "request_digest": digest,
                "parent_sequence": parent.body.sequence,
                "parent_event_digest": parent.event_digest,
                "policy_digest": request.policy_digest,
                "input_digest": request.input_digest,
                "operations": request.operations,
                "issued_at": now,
                "expires_at": request.expires_at,
            }
        )
        await repository.append(AutomationGrant.model_validate(renewed.model_dump()), previous=previous)
        return renewed

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
