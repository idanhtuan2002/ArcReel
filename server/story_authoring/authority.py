"""Human Showrunner authority for story decisions, read from the activated Governance grant ledger.

:class:`GrantNarrativeShowrunnerAuthority` is the production ``NarrativeShowrunnerAuthorityPort``: every answer
requires a current, signed ``HUMAN_SHOWRUNNER`` grant for the exact ``(user_id, project_name, principal)``,
read under a transaction through the existing ``CurrentShowrunnerGrantReader`` (the checkpointed reader in an
activated deployment). It reads and verifies grants only; it issues, amends, revokes and infers none. Without
a grant reader, or without a current grant, every method denies.

:meth:`GrantNarrativeShowrunnerAuthority.require_showrunner` answers the same question for the approvals the
Narrative port does not mint itself: the touchpoint-2 ``CanonCommitApproval`` and ``NarrativePlanApproval``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.narrative_lifecycle import (
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeDecisionRetryAuthentication,
    NarrativeWorkScope,
)
from r2.governance.grant_transition import GrantScopeV1
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from server.services.governance_grants import CurrentShowrunnerGrantReader, ShowrunnerGrantUnavailableError

AUTHORITY_ROLE = "HUMAN_SHOWRUNNER"


def _fingerprint(prefix: str, value: object) -> str:
    return prefix + hashlib.sha256(canonical_json_bytes(ensure_json_value(value))).hexdigest()


@dataclass(frozen=True)
class ShowrunnerProof:
    """A principal's current grant at one instant: who acts, and which signed event proved it."""

    actor_id: str
    grant_event_digest: str
    authenticated_at: datetime

    @property
    def authenticated_via(self) -> str:
        return f"governance-grant:{self.grant_event_digest}"


class GrantNarrativeShowrunnerAuthority:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        grants: CurrentShowrunnerGrantReader | None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._grants = grants
        self._clock = clock

    async def require_showrunner(self, principal: str, *, user_id: str, project_name: str) -> ShowrunnerProof:
        if self._grants is None:
            raise NarrativeDecisionAuthorizationError("Governance grants are not activated on this deployment")
        try:
            async with self._session_factory() as session, session.begin():
                event = await self._grants.require_current_locked(
                    session, scope=GrantScopeV1(user_id=user_id, project_name=project_name, principal=principal)
                )
        except ShowrunnerGrantUnavailableError as exc:
            raise NarrativeDecisionAuthorizationError(
                f"{principal!r} holds no current Showrunner grant: {exc}"
            ) from exc
        return ShowrunnerProof(
            actor_id=principal, grant_event_digest=event.event_digest, authenticated_at=self._clock()
        )

    async def authorize_initial_decision(
        self, authenticated_principal: str, canonical_command: NarrativeDecisionCommand
    ) -> NarrativeDecisionAuthorization:
        scope = canonical_command.work_scope
        if canonical_command.actor_id != authenticated_principal:
            raise NarrativeDecisionAuthorizationError(
                "the command names another actor than the authenticated principal"
            )
        proof = await self.require_showrunner(
            authenticated_principal, user_id=scope.user_id, project_name=scope.project_name
        )
        return NarrativeDecisionAuthorization(
            authorization_ref=_fingerprint("nda:", [proof.grant_event_digest, canonical_command.decision_id]),
            user_id=scope.user_id,
            project_name=scope.project_name,
            actor_id=proof.actor_id,
            authority_role=AUTHORITY_ROLE,
            decision_family=canonical_command.decision_family,
            action=canonical_command.action,
            decision_id=canonical_command.decision_id,
            stable_subject_fingerprint=_fingerprint("nss:", scope.model_dump(mode="json")),
            decision_command_fingerprint=_fingerprint("ndc:", canonical_command.model_dump(mode="json")),
            authenticated_at=proof.authenticated_at,
            authenticated_via=proof.authenticated_via,
        )

    async def authenticate_exact_retry(
        self, authenticated_principal: str, decision_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication:
        return await self._authenticate(authenticated_principal, decision_id, exact_scope, kind="retry")

    async def authenticate_scoped_showrunner(
        self, authenticated_principal: str, subject_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication:
        return await self._authenticate(authenticated_principal, subject_id, exact_scope, kind="scoped")

    async def _authenticate(
        self, principal: str, subject_id: str, scope: NarrativeWorkScope, *, kind: str
    ) -> NarrativeDecisionRetryAuthentication:
        proof = await self.require_showrunner(principal, user_id=scope.user_id, project_name=scope.project_name)
        return NarrativeDecisionRetryAuthentication(
            retry_authentication_ref=_fingerprint(f"nra-{kind}:", [proof.grant_event_digest, subject_id]),
            user_id=scope.user_id,
            project_name=scope.project_name,
            actor_id=proof.actor_id,
            authority_role=AUTHORITY_ROLE,
            decision_id=subject_id,
            authenticated_at=proof.authenticated_at,
            authenticated_via=proof.authenticated_via,
        )
