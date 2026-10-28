"""Receipt-first publication through activated Human custody and one owning transaction."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.repositories.quality import QualityProfileRepository
from r2.quality.errors import M10Error, ProfilePublicationUnauthorizedError, RequiredEvidenceMissingError
from r2.quality.profiles import build_published_profile, validate_publication_envelope
from server.services.quality_profile_custodian import (
    PUBLICATION_POLICY_ID,
    PUBLICATION_POLICY_VERSION,
    InteractiveProfilePublicationCustodian,
)


class ProfilePublicationService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        custodian: InteractiveProfilePublicationCustodian,
    ) -> None:
        if type(custodian) is not InteractiveProfilePublicationCustodian:
            raise ProfilePublicationUnauthorizedError()
        self._sessions = sessions
        self._custodian = custodian

    async def publish(self, request: q.ProfilePublicationAuthorizationRequest) -> q.QualityProfileRevision:
        """Return exact historical receipts or commit all publication outputs after fresh admission."""
        validate_publication_envelope(request)
        request = q.ProfilePublicationAuthorizationRequest.model_validate(request)
        try:
            await self._custodian.require_actor(request)
            async with self._sessions() as session:
                prior = await QualityProfileRepository(session).replay(request)
            if prior is not None:
                await self._custodian.require_actor(request)
                return prior
            lease = await self._custodian.authorize_publication(request)
            async with self._sessions() as session, session.begin():
                repository = QualityProfileRepository(session)
                await repository.lock_command(request.command)
                prior = await repository.replay(request)
                if prior is not None:
                    await self._custodian.require_actor(request)
                    return prior
                # Profile head before grant head, the same order as run closure and disposition.
                await repository.lock_profile(request)
                admitted_at = await self._custodian.admit_locked(session, request, lease)
                revision = build_published_profile(
                    request,
                    lease,
                    admitted_at,
                    policy_id=PUBLICATION_POLICY_ID,
                    policy_version=PUBLICATION_POLICY_VERSION,
                )
                await repository.stage_publication(request, lease, revision, admitted_at)
            return revision
        except M10Error:
            raise
        except Exception:
            raise RequiredEvidenceMissingError() from None
