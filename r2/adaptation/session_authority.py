"""V1's real, single-operator ``AdaptationShowrunnerAuthorityPort`` adapter
(P1 backlog item 6, plan Task 4).

Before this module, ``AdaptationShowrunnerAuthorityPort`` had zero real
(non-test) implementation anywhere -- ``FakeAuthority`` in test code was the
only existing implementor, which meant Gate B's Narrative Lock endpoint
could not be wired into a real server route at all.

V1 is explicitly single-operator and self-hosted, with no multi-tenant or
multi-role promise (``R2_V1_PRODUCTION_RELEASE_STRATEGY.md`` section 4). The
correct-for-V1 real adapter therefore authorizes any principal the host has
already session-authenticated (``server.auth.get_current_user``, checked
before this adapter is ever reached) as ``HUMAN_SHOWRUNNER`` unconditionally
-- it does not implement a separate per-project grant registry, because V1
has no multi-user concept for such a registry to distinguish between, and
inventing one would be new authoritative state ADR-0089 says V1 must not
add. A future multi-operator V2 adapter would need a real grant check here;
this one deliberately does not pretend to have one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from r2.contracts.adaptation import AdaptationDecisionAction, AdaptationDecisionAuthorization


class SessionAuthenticatedShowrunnerAuthority:
    """Implements ``AdaptationShowrunnerAuthorityPort``. Never raises
    ``AdaptationAuthorityDeniedError`` -- any caller reaching this adapter has
    already passed the host's own session-JWT authentication."""

    async def authorize(
        self, *, authenticated_principal: str, action: AdaptationDecisionAction, command_identity_hash: str
    ) -> AdaptationDecisionAuthorization:
        return AdaptationDecisionAuthorization(
            authenticated_principal=authenticated_principal,
            authority_role="HUMAN_SHOWRUNNER",
            action=action,
            command_identity_hash=command_identity_hash,
            approval_receipt=f"session-authorized:{command_identity_hash}",
            authorized_at=datetime.now(UTC),
        )


__all__ = ["SessionAuthenticatedShowrunnerAuthority"]
