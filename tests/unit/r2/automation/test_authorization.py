"""Automatic authority is exact, bounded and distinct from Human grants."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError


def request_data():
    return {
        "user_id": "default",
        "project_name": "project",
        "run_id": "run-1",
        "issuer_id": "actor",
        "command_id": "start-1",
        "expected_run_version": 1,
        "input_digest": "sha256:" + "c" * 64,
        "policy_digest": "sha256:" + "a" * 64,
        "operations": ["STORY_COMMIT", "QUALITY", "EXPORT"],
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }


def test_delegation_has_no_human_or_publication_operation():
    from r2.contracts.automation import AutomationOperation, GrantRequest

    request = GrantRequest(**request_data())
    assert request.operations == frozenset(
        {AutomationOperation.STORY_COMMIT, AutomationOperation.QUALITY, AutomationOperation.EXPORT}
    )
    assert "GATE_D" not in {operation.value for operation in AutomationOperation}
    assert "PROFILE_PUBLICATION" not in {operation.value for operation in AutomationOperation}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operations", ["GATE_D"]),
        ("operations", ["WAIVE"]),
        ("operations", []),
        ("run_id", "*"),
        ("issuer_id", "*"),
        ("expected_run_version", 0),
        ("principal", "HUMAN_SHOWRUNNER"),
        ("proof", "trusted"),
    ],
)
def test_untrusted_delegation_cannot_expand_authority(field, value):
    from r2.contracts.automation import GrantRequest

    with pytest.raises(ValidationError):
        GrantRequest(**{**request_data(), field: value})


def test_authorization_subject_binds_exact_intent_and_content():
    from r2.automation.authorization import authorization_subject_digest
    from r2.contracts.automation import AuthorizationSubject

    data = {
        key: value
        for key, value in request_data().items()
        if key in {"user_id", "project_name", "run_id", "input_digest", "policy_digest"}
    }
    subject = AuthorizationSubject(
        **data,
        grant_id="grant-1",
        grant_version=1,
        expected_run_version=2,
        generation=1,
        operation="EXPORT",
        command_id="export-1",
        subject_digest="sha256:" + "b" * 64,
    )
    original = authorization_subject_digest(subject)
    for field, value in {
        "command_id": "export-2",
        "generation": 2,
        "grant_version": 2,
        "expected_run_version": 3,
        "subject_digest": "sha256:" + "d" * 64,
    }.items():
        assert authorization_subject_digest(subject.model_copy(update={field: value})) != original
