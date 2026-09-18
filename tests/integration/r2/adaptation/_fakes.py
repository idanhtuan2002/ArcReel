"""Shared test doubles for the M6 adaptation authority suites — not a conftest module:
conftest.py only holds fixtures and collection hooks, and imports this module to build
them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from r2.adaptation.errors import AdaptationAuthorityDeniedError
from r2.contracts.adaptation import AdaptationDecisionAuthorization

PRINCIPAL = "human:anhtuan"


class FakeAuthority:
    def __init__(
        self,
        *,
        deny: bool = False,
        principal: str = PRINCIPAL,
        command_identity_hash: str | None = None,
    ) -> None:
        self.deny = deny
        self.principal = principal
        self.command_identity_hash = command_identity_hash
        self.calls: list[tuple[str, str]] = []

    async def authorize(
        self, *, authenticated_principal, action, command_identity_hash
    ) -> AdaptationDecisionAuthorization:
        self.calls.append((authenticated_principal, command_identity_hash))
        if self.deny or authenticated_principal != self.principal:
            raise AdaptationAuthorityDeniedError("Human Showrunner grant is absent for this principal")
        return AdaptationDecisionAuthorization(
            authenticated_principal=authenticated_principal,
            authority_role="HUMAN_SHOWRUNNER",
            action=action,
            command_identity_hash=self.command_identity_hash or command_identity_hash,
            approval_receipt=f"receipt:{command_identity_hash}",
            authorized_at=datetime.now(UTC),
        )
