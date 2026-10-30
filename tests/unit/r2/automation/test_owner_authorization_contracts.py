"""Historical Human wire stays exact; automatic authority has its own tagged reference."""

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError


def human_wire():
    return {
        "authorization_ref": "nda:original",
        "user_id": "default",
        "project_name": "project",
        "actor_id": "actor",
        "authority_role": "HUMAN_SHOWRUNNER",
        "decision_family": "REVISION_ACCEPTANCE",
        "action": "ACCEPT",
        "decision_id": "decision-1",
        "stable_subject_fingerprint": "nss:original",
        "decision_command_fingerprint": "ndc:original",
        "authenticated_at": "2026-10-30T00:00:00Z",
        "authenticated_via": "governance-grant:original",
    }


def auto_wire():
    from r2.automation.authorization import automation_principal

    return {
        **human_wire(),
        "schema_id": "r2.narrative-automation-authorization.v1",
        "authorization_ref": "anda:v1:" + "a" * 64,
        "authority_role": "RUN_AUTOMATION",
        "actor_id": automation_principal("run-1"),
        "authenticated_via": "automation:v1:run-1:auto-" + "b" * 64 + ":grant-1:1",
    }


def test_legacy_human_authorization_roundtrip():
    from r2.contracts.narrative_lifecycle import NarrativeDecisionAuthorization, NarrativeDecisionAuthorizationEvidence

    original = NarrativeDecisionAuthorization(**human_wire())
    assert original.model_dump(mode="json") == human_wire()
    restored = TypeAdapter(NarrativeDecisionAuthorizationEvidence).validate_python(human_wire())
    assert type(restored) is NarrativeDecisionAuthorization
    assert restored.model_dump(mode="json") == human_wire()


def test_tagged_automatic_authorization_roundtrip_is_separate_from_human():
    from r2.contracts.narrative_lifecycle import (
        NarrativeAutomationDecisionAuthorizationV1,
        NarrativeDecisionAuthorization,
        NarrativeDecisionAuthorizationEvidence,
    )

    wire = auto_wire()
    restored = TypeAdapter(NarrativeDecisionAuthorizationEvidence).validate_python(wire)
    assert type(restored) is NarrativeAutomationDecisionAuthorizationV1
    assert restored.model_dump(mode="json") == wire
    assert restored.authenticated_at == datetime(2026, 10, 30, tzinfo=UTC)
    with pytest.raises(ValidationError):
        NarrativeDecisionAuthorization(**wire)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actor_id", "actor"),
        ("authority_role", "HUMAN_SHOWRUNNER"),
        ("authenticated_via", "governance-grant:pretend"),
        ("authenticated_via", "automation:v1:*:auto-a:grant:1"),
        ("authorization_ref", "nda:human"),
        ("schema_id", "r2.narrative-automation-authorization.v2"),
    ],
)
def test_automatic_projection_rejects_missing_or_human_shaped_binding(field, value):
    from r2.contracts.narrative_lifecycle import NarrativeAutomationDecisionAuthorizationV1

    with pytest.raises(ValidationError):
        NarrativeAutomationDecisionAuthorizationV1(**{**auto_wire(), field: value})


def test_automatic_retry_is_fresh_metadata_and_does_not_change_legacy_wire():
    from r2.contracts.narrative_lifecycle import (
        NarrativeAutomationRetryAuthenticationV1,
        NarrativeDecisionRetryAuthentication,
        NarrativeDecisionRetryAuthenticationEvidence,
    )

    base = {
        key: value
        for key, value in auto_wire().items()
        if key
        in {
            "user_id",
            "project_name",
            "actor_id",
            "authority_role",
            "decision_id",
            "authenticated_at",
            "authenticated_via",
        }
    }
    wire = {**base, "schema_id": "r2.narrative-automation-retry.v1", "retry_authentication_ref": "anra:v1:" + "c" * 64}
    restored = TypeAdapter(NarrativeDecisionRetryAuthenticationEvidence).validate_python(wire)
    assert type(restored) is NarrativeAutomationRetryAuthenticationV1
    assert restored.model_dump(mode="json") == wire
    with pytest.raises(ValidationError):
        NarrativeDecisionRetryAuthentication(**wire)
