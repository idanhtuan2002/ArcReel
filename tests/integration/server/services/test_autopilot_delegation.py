"""An autopilot delegation is the Showrunner's recorded decision; runs it starts are bound to it (ADR-0124)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from server import auth
from tests.integration.lib.db.repositories.test_production_runs import policy
from tests.integration.server.services.test_automation_grants import custodian, interactive_env  # noqa: F401
from tests.integration.server.services.test_quality_profile_custodian import prepare_qualified_custody


@pytest.fixture
async def autopilot_host(concurrent_session_factory, tmp_path, request):
    request.getfixturevalue("interactive_env")
    from server.services.governance_attestation import serve_governance_attestor

    sessions = concurrent_session_factory
    root, runtime, _importer, _key, event = await prepare_qualified_custody(sessions, tmp_path)
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        issuer = custodian(sessions, root, runtime)
        await issuer.activate()
        yield issuer, sessions, event


def _migration():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "alembic/versions/b7a310300004_autopilot_delegations.py"
    spec = importlib.util.spec_from_file_location("autopilot_delegation_migration_fixture", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _set(issuer, sessions, *, command_id: str, enabled: bool, token: str | None = None, **changes):
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import AutomationMode
    from r2.contracts.autopilot import StoryAutopilot

    async with sessions() as session, session.begin():
        return await issuer.set_autopilot_locked(
            session,
            interactive_token=auth.create_token("actor") if token is None else token,
            user_id="default",
            project_name="project",
            command_id=command_id,
            enabled=enabled,
            kind="story",
            mode=AutomationMode.AUTO,
            policy_digest=changes.pop("policy_digest", policy_digest(policy())),
            story=StoryAutopilot(idea="Chuyến đò cuối.", book_chapters=12),
            **changes,
        )


async def _run(sessions, command_id: str):
    from lib.db.repositories.production_runs import ProductionRunRepository
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import RunCommand

    async with sessions() as session, session.begin():
        return await ProductionRunRepository(session).create(
            command=RunCommand(
                user_id="default",
                project_name="project",
                command_id=command_id,
                action="START",
                expected_version=0,
                expected_input_digest="sha256:" + "c" * 64,
                policy_digest=policy_digest(policy()),
                idea="Chuyến đò cuối.",
                end_stage="HANDOFF",
            ),
            policy=policy(),
        )


async def _cancel(sessions, run) -> None:
    import sqlalchemy as sa

    from lib.db.models.production_run import ProductionRunModel

    async with sessions() as session, session.begin():
        await session.execute(
            sa.update(ProductionRunModel).where(ProductionRunModel.run_id == run.run_id).values(status="CANCELLED")
        )


def _request(run, delegation, command_id: str, expires_at: datetime):
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import AutomationOperation, GrantRequest

    return GrantRequest(
        user_id=run.user_id,
        project_name=run.project_name,
        run_id=run.run_id,
        issuer_id=delegation.issuer_id,
        command_id=command_id,
        expected_run_version=run.version,
        input_digest=run.input_digest,
        policy_digest=policy_digest(run.policy),
        operations=frozenset(AutomationOperation),
        expires_at=expires_at,
    )


async def test_enable_replay_disable_are_appended_versions(autopilot_host):
    from lib.db.repositories.autopilot import AutopilotRepository

    issuer, sessions, event = autopilot_host
    enabled = await _set(issuer, sessions, command_id="enable-1", enabled=True)
    assert (enabled.version, enabled.state, enabled.issuer_id) == (1, "ENABLED", "actor")
    assert (enabled.parent_sequence, enabled.parent_event_digest) == (event.body.sequence, event.event_digest)
    assert await _set(issuer, sessions, command_id="enable-1", enabled=True) == enabled
    with pytest.raises(PermissionError, match="REPLAY_CONFLICT"):
        await _set(issuer, sessions, command_id="enable-1", enabled=False)
    disabled = await _set(issuer, sessions, command_id="disable-1", enabled=False)
    assert (disabled.version, disabled.state, disabled.story) == (2, "DISABLED", enabled.story)
    assert await _set(issuer, sessions, command_id="disable-2", enabled=False) == disabled
    async with sessions() as session:
        assert await AutopilotRepository(session).current("default", "project") == disabled
    for token in ("not-a-jwt", auth.create_token("other")):
        # An invalid session, or a session of a principal without a Showrunner grant, records nothing.
        with pytest.raises(PermissionError, match=r"INTERACTIVE_SHOWRUNNER_REQUIRED|grant head is missing"):
            await _set(issuer, sessions, command_id="enable-2", enabled=True, token=token)


async def test_versions_are_immutable(autopilot_host):
    import sqlalchemy as sa

    issuer, sessions, _event = autopilot_host
    await _set(issuer, sessions, command_id="enable-1", enabled=True)
    async with sessions() as session, session.begin():
        connection = await session.connection()
        await connection.run_sync(_migration().install_immutability)
    with pytest.raises(sa.exc.DBAPIError, match="IMMUTABLE"):
        async with sessions() as session, session.begin():
            await session.execute(sa.text("UPDATE auto_autopilot_delegations SET state = 'DISABLED'"))
    with pytest.raises(sa.exc.DBAPIError, match="IMMUTABLE"):
        async with sessions() as session, session.begin():
            await session.execute(sa.text("DELETE FROM auto_autopilot_delegations"))


async def test_delegated_grant_is_bound_to_the_current_enabled_delegation(autopilot_host):
    from r2.contracts.autopilot import autopilot_command_id

    issuer, sessions, event = autopilot_host
    delegation = await _set(issuer, sessions, command_id="enable-1", enabled=True)
    parent_expiry = datetime.fromisoformat(event.body.expires_at)

    stranger = await _run(sessions, "manual-start")
    with pytest.raises(PermissionError, match="SCOPE_MISMATCH"):
        async with sessions() as session, session.begin():
            await issuer.issue_delegated_locked(
                session, delegation=delegation, request=_request(stranger, delegation, "manual-start", parent_expiry)
            )
    await _cancel(sessions, stranger)

    command_id = autopilot_command_id(delegation, 1)
    run = await _run(sessions, command_id)
    async with sessions() as session, session.begin():
        assert await issuer.require_delegation_locked(session, delegation=delegation) == parent_expiry
        grant = await issuer.issue_delegated_locked(
            session, delegation=delegation, request=_request(run, delegation, command_id, parent_expiry)
        )
    # The child grant lives as long as its parent grant, not a session's day.
    assert (grant.expires_at, grant.parent_event_digest, grant.issuer_id) == (
        parent_expiry,
        event.event_digest,
        "actor",
    )
    async with sessions() as session, session.begin():
        replay = await issuer.issue_delegated_locked(
            session, delegation=delegation, request=_request(run, delegation, command_id, parent_expiry)
        )
    assert replay == grant

    await _set(issuer, sessions, command_id="disable-1", enabled=False)
    with pytest.raises(PermissionError, match="DELEGATION_NOT_CURRENT"):
        async with sessions() as session, session.begin():
            await issuer.require_delegation_locked(session, delegation=delegation)

    await _cancel(sessions, run)
    moved = await _set(issuer, sessions, command_id="enable-2", enabled=True, policy_digest="sha256:" + "e" * 64)
    later = await _run(sessions, autopilot_command_id(moved, 1))
    with pytest.raises(PermissionError, match="SCOPE_MISMATCH"):
        async with sessions() as session, session.begin():
            await issuer.issue_delegated_locked(
                session,
                delegation=moved,
                request=_request(later, moved, autopilot_command_id(moved, 1), datetime.now(UTC).replace(year=2099)),
            )
