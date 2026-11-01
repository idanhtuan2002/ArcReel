from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from lib.db.repositories.gates import GreenlightRepository
from r2.automation.authorization import automation_principal
from r2.contracts.automation import AutomationOperation
from r2.contracts.gates import GateAuthorization, GreenlightDecision, ScriptLockDecision
from tests.integration.server.services.test_automation_grants import delegated_host as delegated_host
from tests.integration.server.services.test_automation_grants import interactive_env as interactive_env
from tests.integration.server.services.test_automation_grants import subject_for

SOURCE = "sha256:" + "a" * 64


def _subject(run, grant, source=SOURCE, **changes):
    from server.production_run.greenlight_authority import greenlight_subject_digest

    return subject_for(run, grant).model_copy(
        update={"subject_digest": greenlight_subject_digest(source_digest=source), **changes}
    )


async def _history(sessions, run) -> list[GreenlightDecision]:
    async with sessions() as session:
        return await GreenlightRepository(session).list_for_project(user_id=run.user_id, project_name=run.project_name)


def test_legacy_human_gate_authorization_wire_is_unchanged():
    wire = {
        "decision_id": "d1",
        "user_id": "u",
        "project_name": "p",
        "source_digest": SOURCE,
        "action": "GREENLIGHT",
        "authorization": {
            "authenticated_principal": "alice",
            "authority_role": "HUMAN_OPERATOR",
            "authorized_at": "2026-11-01T00:00:00Z",
        },
        "sequence": 1,
        "created_at": "2026-11-01T00:00:00Z",
    }
    restored = GreenlightDecision.model_validate(wire)
    assert isinstance(restored.authorization, GateAuthorization)
    assert restored.model_dump(mode="json") == wire


def test_automation_authorization_is_refused_outside_gate_a():
    from r2.contracts.gates import GateAutomationAuthorizationV1

    automatic = GateAutomationAuthorizationV1(
        authenticated_principal="automation:x",
        automation_reference="automation:v1:r:auto-" + "0" * 64 + ":g:1",
        authorized_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError):
        ScriptLockDecision.model_validate(
            {
                "decision_id": "d1",
                "user_id": "u",
                "project_name": "p",
                "source_digest": SOURCE,
                "script_digest": SOURCE,
                "action": "LOCK",
                "authorization": automatic.model_dump(mode="json"),
                "sequence": 1,
                "created_at": "2026-11-01T00:00:00Z",
            }
        )


async def test_automatic_greenlight_records_the_run_principal_and_replays(delegated_host):
    from r2.contracts.gates import GateAutomationAuthorizationV1
    from server.production_run.greenlight_authority import greenlight_automatically

    issuer, sessions, _request, grant, run, *_ = delegated_host
    subject = _subject(run, grant)

    first = await greenlight_automatically(
        sessions=sessions, authority=issuer.authority(), subject=subject, source_digest=SOURCE
    )
    replay = await greenlight_automatically(
        sessions=sessions, authority=issuer.authority(), subject=subject, source_digest=SOURCE
    )

    assert replay == first
    [stored] = await _history(sessions, run)
    assert stored == first
    assert stored.action == "GREENLIGHT"
    assert stored.source_digest == SOURCE
    assert isinstance(stored.authorization, GateAutomationAuthorizationV1)
    assert stored.authorization.authenticated_principal == automation_principal(run.run_id) == grant.principal
    assert stored.authorization.automation_reference.startswith(f"automation:v1:{run.run_id}:")


@pytest.mark.parametrize(
    "change",
    [
        {"operation": AutomationOperation.STORY},
        {"subject_digest": "sha256:" + "e" * 64},
    ],
)
async def test_a_subject_for_another_operation_or_source_writes_nothing(delegated_host, change):
    from server.production_run.greenlight_authority import greenlight_automatically

    issuer, sessions, _request, grant, run, *_ = delegated_host

    with pytest.raises(PermissionError):
        await greenlight_automatically(
            sessions=sessions,
            authority=issuer.authority(),
            subject=_subject(run, grant, **change),
            source_digest=SOURCE,
        )
    assert await _history(sessions, run) == []


async def test_a_revoked_grant_writes_no_greenlight(delegated_host):
    from server.auth import create_token
    from server.production_run.greenlight_authority import greenlight_automatically

    issuer, sessions, _request, grant, run, *_ = delegated_host
    await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)

    with pytest.raises(PermissionError):
        await greenlight_automatically(
            sessions=sessions, authority=issuer.authority(), subject=_subject(run, grant), source_digest=SOURCE
        )
    assert await _history(sessions, run) == []


async def test_revocation_inside_the_owner_transaction_rolls_back_the_greenlight(delegated_host, monkeypatch):
    from server.auth import create_token
    from server.production_run import greenlight_authority

    issuer, sessions, _request, grant, run, *_ = delegated_host
    original_append = GreenlightRepository.append

    async def append_then_revoke(self, decision):
        await original_append(self, decision)
        await issuer.revoke(interactive_token=create_token("actor"), run_id=run.run_id, expected_version=grant.version)

    monkeypatch.setattr(greenlight_authority.GreenlightRepository, "append", append_then_revoke)
    with pytest.raises(PermissionError):
        await greenlight_authority.greenlight_automatically(
            sessions=sessions, authority=issuer.authority(), subject=_subject(run, grant), source_digest=SOURCE
        )
    assert await _history(sessions, run) == []


async def test_a_lookalike_authority_is_refused(delegated_host):
    from server.production_run.greenlight_authority import greenlight_automatically

    _issuer, sessions, _request, grant, run, *_ = delegated_host

    class Lookalike:
        async def require_locked(self, session, *, subject):
            raise AssertionError("must not be consulted")

    with pytest.raises(PermissionError):
        await greenlight_automatically(
            sessions=sessions, authority=Lookalike(), subject=_subject(run, grant), source_digest=SOURCE
        )
