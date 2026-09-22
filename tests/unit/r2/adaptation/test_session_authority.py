from __future__ import annotations

from r2.adaptation.session_authority import SessionAuthenticatedShowrunnerAuthority
from r2.contracts.adaptation import AdaptationDecisionAction


async def test_authorizes_any_session_authenticated_principal() -> None:
    # V1 is single-operator/self-hosted with no multi-tenant grant registry
    # (R2_V1_PRODUCTION_RELEASE_STRATEGY.md section 4) -- this adapter trusts
    # the host's own session-JWT authentication entirely and never denies.
    authority = SessionAuthenticatedShowrunnerAuthority()
    result = await authority.authorize(
        authenticated_principal="operator-1",
        action=AdaptationDecisionAction.ADMIT,
        command_identity_hash="sha256:" + "a" * 64,
    )
    assert result.authenticated_principal == "operator-1"
    assert result.authority_role == "HUMAN_SHOWRUNNER"
    assert result.action == AdaptationDecisionAction.ADMIT
    assert result.command_identity_hash == "sha256:" + "a" * 64
    assert result.approval_receipt == "session-authorized:sha256:" + "a" * 64


async def test_authorizes_a_different_principal_identically() -> None:
    authority = SessionAuthenticatedShowrunnerAuthority()
    result = await authority.authorize(
        authenticated_principal="a-completely-different-operator",
        action=AdaptationDecisionAction.REJECT,
        command_identity_hash="sha256:" + "b" * 64,
    )
    assert result.authenticated_principal == "a-completely-different-operator"
    assert result.authority_role == "HUMAN_SHOWRUNNER"
