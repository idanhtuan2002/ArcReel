"""Request-bound interactive identity; Human publication authority requires activated issuance."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Self

from fastapi import HTTPException
from sqlalchemy import exc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.repositories.quality import QualityProfileRepository
from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.exploration import uuid7
from r2.governance.grant_transition import GrantScopeV1
from r2.quality.errors import ProfilePublicationUnauthorizedError
from r2.quality.profiles import build_published_profile, publication_bindings, validate_publication_envelope
from server.auth import get_current_interactive_user
from server.services.governance_grants import CheckpointedShowrunnerGrantReader, ShowrunnerGrantUnavailableError
from server.services.governance_startup import GovernanceStartupUnavailable, verify_governance_activated_startup

PUBLICATION_POLICY_ID = "m10.profile-publication.interactive-human.v1"
PUBLICATION_POLICY_VERSION = "1"
_ACTIVATION_SEAL = object()


class InteractiveProfilePublicationCustodian:
    """A bound authenticated request wrapper is not a publication authorization."""

    def __init__(
        self,
        request: q.ProfilePublicationAuthorizationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        read_directory: Path,
        socket_directory: Path,
        expected_uid: int,
        expected_gid: int,
    ) -> None:
        validate_publication_envelope(request)
        self._request = q.ProfilePublicationAuthorizationRequest.model_validate(request)
        self._binding = canonical_json_bytes(self._request)
        self._sessions = sessions
        self._token = interactive_token
        self._read_directory = read_directory
        self._socket_directory = socket_directory
        self._expected_uid = expected_uid
        self._expected_gid = expected_gid
        self._reader: CheckpointedShowrunnerGrantReader | None = None
        self._activation: object | None = None

    @classmethod
    async def for_request(
        cls,
        request: q.ProfilePublicationAuthorizationRequest,
        sessions: async_sessionmaker[AsyncSession],
        *,
        interactive_token: str | None,
        read_directory: Path,
        socket_directory: Path,
        expected_uid: int,
        expected_gid: int,
    ) -> Self:
        """Bind the exact request and verify its JWT without touching database or archive."""
        wrapper = cls(
            request,
            sessions,
            interactive_token=interactive_token,
            read_directory=read_directory,
            socket_directory=socket_directory,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
        )
        await wrapper.require_actor(request)
        return wrapper

    async def require_actor(self, request: q.ProfilePublicationAuthorizationRequest) -> None:
        """Revalidate the current interactive identity and the original exact request binding."""
        validate_publication_envelope(request)
        normalized = q.ProfilePublicationAuthorizationRequest.model_validate(request)
        if canonical_json_bytes(normalized) != self._binding:
            raise ProfilePublicationUnauthorizedError()
        try:
            user = await get_current_interactive_user(self._token)
        except HTTPException:
            raise ProfilePublicationUnauthorizedError() from None
        if (user.id, user.sub) != (normalized.command.user_id, normalized.command.actor_id):
            raise ProfilePublicationUnauthorizedError()

    async def authorize_publication(
        self, request: q.ProfilePublicationAuthorizationRequest
    ) -> q.ProfilePublicationAuthorizationLease:
        """Activate through the real independent archive and persist an action-specific issuance receipt."""
        await self.require_actor(request)
        try:
            reader = await verify_governance_activated_startup(
                self._read_directory,
                self._socket_directory,
                session_factory=self._sessions,
                expected_uid=self._expected_uid,
                expected_gid=self._expected_gid,
            )
            if type(reader) is not CheckpointedShowrunnerGrantReader:
                raise ProfilePublicationUnauthorizedError()
            self._reader = reader
            self._activation = _ACTIVATION_SEAL
            async with self._sessions() as session, session.begin():
                if session.get_bind().dialect.name != "postgresql":
                    raise ProfilePublicationUnauthorizedError()
                scope = GrantScopeV1(request.command.user_id, request.command.project_name, request.command.actor_id)
                grant = await reader.require_current_locked(session, scope=scope)
                await self.require_actor(request)
                issued_at = await self._database_now(session)
                if grant.body.expires_at is None:
                    raise ProfilePublicationUnauthorizedError()
                deadline = min(issued_at + timedelta(seconds=30), datetime.fromisoformat(grant.body.expires_at))
                request_digest, subject_digest = publication_bindings(request)
                lease = q.ProfilePublicationAuthorizationLease(
                    authorization_id=uuid7(),
                    action="PROFILE_PUBLICATION",
                    user_id=request.command.user_id,
                    project_name=request.command.project_name,
                    actor_id=request.command.actor_id,
                    command_id=request.command.command_id,
                    request_digest=request_digest,
                    subject_digest=subject_digest,
                    policy_id=PUBLICATION_POLICY_ID,
                    policy_version=PUBLICATION_POLICY_VERSION,
                    evidence_digest=grant.event_digest,
                    issued_at=issued_at,
                    admit_not_after=deadline,
                )
                await QualityProfileRepository(session).record_authorization(
                    request, lease, grant_sequence=grant.body.sequence
                )
            return lease
        except (
            GovernanceStartupUnavailable,
            ShowrunnerGrantUnavailableError,
            TypeError,
            ValueError,
            exc.SQLAlchemyError,
        ):
            raise ProfilePublicationUnauthorizedError() from None

    async def _database_now(self, session: AsyncSession) -> datetime:
        if session.get_bind().dialect.name != "postgresql" or not session.in_transaction():
            raise ProfilePublicationUnauthorizedError()
        value = await session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ProfilePublicationUnauthorizedError()
        return value

    async def lock_current_grant(
        self,
        session: AsyncSession,
        request: q.ProfilePublicationAuthorizationRequest,
        lease: q.ProfilePublicationAuthorizationLease,
    ) -> None:
        """Lock and resolve this activated issuer's immutable receipt and current signed grant."""
        await self.require_actor(request)
        if self._activation is not _ACTIVATION_SEAL or self._reader is None:
            raise ProfilePublicationUnauthorizedError()
        try:
            lease = q.ProfilePublicationAuthorizationLease.model_validate(lease)
            if (lease.policy_id, lease.policy_version) != (PUBLICATION_POLICY_ID, PUBLICATION_POLICY_VERSION):
                raise ProfilePublicationUnauthorizedError()
            stored = await QualityProfileRepository(session).load_authorization(request, lease.authorization_id)
            if stored is None or stored.lease != lease:
                raise ProfilePublicationUnauthorizedError()
            scope = GrantScopeV1(request.command.user_id, request.command.project_name, request.command.actor_id)
            grant = await self._reader.require_current_locked(session, scope=scope)
            if (grant.body.sequence, grant.event_digest) != (stored.grant_sequence, lease.evidence_digest):
                raise ProfilePublicationUnauthorizedError()
        except (ShowrunnerGrantUnavailableError, TypeError, ValueError, exc.SQLAlchemyError):
            raise ProfilePublicationUnauthorizedError() from None

    async def admit_locked(
        self,
        session: AsyncSession,
        request: q.ProfilePublicationAuthorizationRequest,
        lease: q.ProfilePublicationAuthorizationLease,
    ) -> datetime:
        """Revalidate locked authority, then JWT and actual database time after all waits/I/O."""
        await self.lock_current_grant(session, request, lease)
        await self.require_actor(request)
        try:
            admitted_at = await self._database_now(session)
            build_published_profile(
                request, lease, admitted_at, policy_id=PUBLICATION_POLICY_ID, policy_version=PUBLICATION_POLICY_VERSION
            )
            return admitted_at
        except (TypeError, ValueError, exc.SQLAlchemyError):
            raise ProfilePublicationUnauthorizedError() from None
