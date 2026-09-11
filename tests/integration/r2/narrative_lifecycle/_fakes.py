"""Shared test doubles for the M5C-2 acceptance/conflict/evidence/integrity suites —
not a conftest module: conftest.py only holds fixtures and collection hooks, and imports
this module to build them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from r2.contracts.narrative_lifecycle import (
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeDecisionRetryAuthentication,
    NarrativeWorkScope,
)
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from tests.factories import make_narrative_decision_authorization

SHOWRUNNER = "showrunner-1"
_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


class FakeShowrunnerAuthorityPort:
    """Denies every principal but ``SHOWRUNNER``. ``next_authorization`` lets a test
    inject a response bound to a different family/action/scope, so the service (not the
    caller) must be the one to reject the mismatch."""

    def __init__(self) -> None:
        self.next_authorization: NarrativeDecisionAuthorization | None = None

    async def authorize_initial_decision(
        self, authenticated_principal: str, canonical_command: NarrativeDecisionCommand
    ) -> NarrativeDecisionAuthorization:
        if authenticated_principal != SHOWRUNNER:
            raise NarrativeDecisionAuthorizationError(f"{authenticated_principal!r} lacks Human Showrunner capability")
        if self.next_authorization is not None:
            override, self.next_authorization = self.next_authorization, None
            return override
        scope = canonical_command.work_scope
        return make_narrative_decision_authorization(
            decision_id=canonical_command.decision_id,
            user_id=scope.user_id,
            project_name=scope.project_name,
            decision_family=canonical_command.decision_family,
            action=canonical_command.action,
        )

    async def authenticate_exact_retry(
        self, authenticated_principal: str, decision_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication:
        if authenticated_principal != SHOWRUNNER:
            raise NarrativeDecisionAuthorizationError(f"{authenticated_principal!r} lacks Human Showrunner capability")
        return NarrativeDecisionRetryAuthentication(
            retry_authentication_ref="retry-1",
            user_id=exact_scope.user_id,
            project_name=exact_scope.project_name,
            actor_id=SHOWRUNNER,
            authority_role="HUMAN_SHOWRUNNER",
            decision_id=decision_id,
            authenticated_at=_NOW,
            authenticated_via="test",
        )
