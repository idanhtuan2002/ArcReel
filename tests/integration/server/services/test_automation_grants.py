"""Run delegation uses real interactive, signed and checkpointed authority."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from server import auth
from tests.integration.lib.db.repositories.test_production_runs import intent_for, policy
from tests.integration.server.services.test_quality_profile_custodian import SECRET, prepare_qualified_custody


@pytest.fixture
def interactive_env(monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", SECRET)


def custodian(sessions, root, runtime):
    from server.services.automation_grants import AutomationGrantCustodian

    return AutomationGrantCustodian(
        sessions,
        read_directory=root / "read",
        socket_directory=runtime,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )


@pytest.mark.parametrize("kind", ["missing", "apikey", "invalid", "embedded", "disabled", "wrong_actor"])
async def test_unqualified_actor_cannot_issue_delegation(interactive_env, tmp_path, monkeypatch, kind):
    from r2.contracts.automation import GrantRequest
    from tests.unit.r2.automation.test_authorization import request_data

    class ForbiddenSessions:
        def __call__(self):
            raise AssertionError("unqualified actor crossed database boundary")

    token = auth.create_token("other" if kind == "wrong_actor" else "actor")
    if kind == "missing":
        token = None
    elif kind == "apikey":
        token = "arc-unqualified"
    elif kind == "invalid":
        token = "not-a-jwt"
    elif kind == "embedded":
        token = auth.create_download_token("actor", "project")
    elif kind == "disabled":
        monkeypatch.setenv("AUTH_ENABLED", "false")
    issuer = custodian(ForbiddenSessions(), tmp_path, tmp_path)
    with pytest.raises(PermissionError):
        await issuer.issue(interactive_token=token, request=GrantRequest(**request_data()))


@pytest.fixture
async def delegated_host(concurrent_session_factory, tmp_path, interactive_env, request):
    from lib.db.repositories.production_runs import ProductionRunRepository
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import AutomationOperation, GrantRequest, RunCommand
    from server.services.governance_attestation import serve_governance_attestor

    expiry_seconds = getattr(request, "param", 1800)
    sessions = concurrent_session_factory
    root, runtime, importer, key, event = await prepare_qualified_custody(sessions, tmp_path)
    async with serve_governance_attestor(
        root, runtime, session_factory=sessions, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        async with sessions() as session, session.begin():
            run = await ProductionRunRepository(session).create(
                command=RunCommand(
                    user_id="default",
                    project_name="project",
                    command_id="start-1",
                    action="START",
                    expected_version=0,
                    expected_input_digest="sha256:" + "c" * 64,
                    policy_digest=policy_digest(policy()),
                    idea="Chuyến đò cuối.",
                ),
                policy=policy(),
            )
        request = GrantRequest(
            user_id=run.user_id,
            project_name=run.project_name,
            run_id=run.run_id,
            issuer_id="actor",
            command_id="start-1",
            expected_run_version=run.version,
            input_digest=run.input_digest,
            policy_digest=policy_digest(run.policy),
            operations=frozenset(AutomationOperation),
            expires_at=datetime.now(UTC) + timedelta(seconds=expiry_seconds),
        )
        issuer = custodian(sessions, root, runtime)
        grant = await issuer.issue(interactive_token=auth.create_token("actor"), request=request)
        async with sessions() as session, session.begin():
            running = await ProductionRunRepository(session).claim_due(owner_id="worker", lease_seconds=30)
            await ProductionRunRepository(session).stage_intent(run=running, intent=intent_for(running))
        yield issuer, sessions, request, grant, running, importer, key, event, root, runtime


def subject_for(run, grant, **changes):
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import AuthorizationSubject

    return AuthorizationSubject.model_validate(
        dict(
            user_id=run.user_id,
            project_name=run.project_name,
            run_id=run.run_id,
            grant_id=grant.grant_id,
            grant_version=grant.version,
            expected_run_version=run.version,
            generation=run.generation,
            input_digest=run.input_digest,
            policy_digest=policy_digest(run.policy),
            operation=run.stage,
            command_id=intent_for(run).identity.command_id,
            subject_digest="sha256:" + "d" * 64,
            **changes,
        )
    )


async def test_issue_replay_and_exact_automatic_decision(delegated_host):
    issuer, sessions, request, grant, run, *_ = delegated_host
    replay = await issuer.issue(interactive_token=auth.create_token("actor"), request=request)
    assert replay == grant
    assert grant.principal.startswith("automation:")
    assert grant.principal != request.issuer_id
    authority = issuer.authority()
    subject = subject_for(run, grant)
    async with sessions() as session, session.begin():
        authorization = await authority.require_locked(session, subject=subject)
    async with sessions() as session, session.begin():
        assert await authority.require_locked(session, subject=subject) == authorization
    assert authorization.actor_kind == "RUN_AUTOMATION"
    assert authorization.parent_event_digest == grant.parent_event_digest


@pytest.mark.parametrize("change", ["run", "project", "policy", "input", "version", "generation", "grant"])
async def test_current_authority_rejects_scope_or_policy_substitution(delegated_host, change):
    issuer, sessions, _, grant, run, *_ = delegated_host
    subject = subject_for(run, grant)
    updates = {
        "run": {"run_id": "other"},
        "project": {"project_name": "other"},
        "policy": {"policy_digest": "sha256:" + "e" * 64},
        "input": {"input_digest": "sha256:" + "e" * 64},
        "version": {"expected_run_version": run.version + 1},
        "generation": {"generation": run.generation + 1},
        "grant": {"grant_version": grant.version + 1},
    }
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(session, subject=subject.model_copy(update=updates[change]))


async def test_decision_replay_cannot_authorize_different_content(delegated_host):
    issuer, sessions, _, grant, run, *_ = delegated_host
    subject = subject_for(run, grant)
    async with sessions() as session, session.begin():
        await issuer.authority().require_locked(session, subject=subject)
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(
                session, subject=subject.model_copy(update={"subject_digest": "sha256:" + "e" * 64})
            )


async def test_revoke_serializes_against_owner_and_blocks_replayed_authorization(delegated_host):
    issuer, sessions, _, grant, run, *_ = delegated_host
    subject = subject_for(run, grant)
    async with sessions() as owner, owner.begin():
        await issuer.authority().require_locked(owner, subject=subject)
        revoking = asyncio.create_task(
            issuer.revoke(
                interactive_token=auth.create_token("actor"), run_id=run.run_id, expected_version=grant.version
            )
        )
        await owner.execute(sa.text("SELECT pg_sleep(0.1)"))
        assert not revoking.done()
    revoked = await revoking
    assert revoked.state == "REVOKED"
    assert revoked.version == grant.version + 1
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(session, subject=subject)


async def test_parent_revocation_blocks_child_without_reissuing_human_event(delegated_host):
    from r2.governance.grant_transition import GrantScopeV1
    from tests.integration.r2.governance.test_grant_importer import _event, _signed

    issuer, sessions, _, grant, run, importer, key, event, *_ = delegated_host
    body = _event("REVOKE", 2, event.event_digest, "2026-10-30T00:00:00Z", project_name="project")
    body.update(user_id="default", principal="actor", signer_key_id="grant-key-a")
    await importer.import_event(_signed(body, key), scope=GrantScopeV1("default", "project", "actor"))
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(session, subject=subject_for(run, grant))


async def test_later_operation_cannot_skip_current_run_stage(delegated_host):
    issuer, sessions, _, grant, run, *_ = delegated_host
    subject = subject_for(run, grant).model_copy(update={"operation": "EXPORT"})
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(session, subject=subject)


async def test_expired_worker_lease_cannot_issue_owner_decision(delegated_host):
    from lib.db.models.production_run import ProductionRunModel

    issuer, sessions, _, grant, run, *_ = delegated_host
    async with sessions() as session, session.begin():
        await session.execute(
            sa.update(ProductionRunModel)
            .where(ProductionRunModel.run_id == run.run_id)
            .values(lease_until=sa.func.clock_timestamp())
        )
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(session, subject=subject_for(run, grant))


def delegation_migration():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "alembic/versions/b7a310300002_automation_delegation.py"
    spec = importlib.util.spec_from_file_location("automation_delegation_migration_fixture", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("target", ["event_update", "event_delete", "decision_update", "decision_delete"])
async def test_delegation_and_owner_decision_are_immutable(delegated_host, target):
    from lib.db.models.automation_grant import AutomationDecisionModel, AutomationGrantEventModel

    issuer, sessions, _, grant, run, *_ = delegated_host
    async with sessions() as session, session.begin():
        await issuer.authority().require_locked(session, subject=subject_for(run, grant))
        connection = await session.connection()
        await connection.run_sync(delegation_migration().install_immutability)
    model = AutomationGrantEventModel if target.startswith("event") else AutomationDecisionModel
    statement = (
        sa.delete(model)
        if target.endswith("delete")
        else (
            sa.update(model).values(grant_json="{}")
            if model is AutomationGrantEventModel
            else sa.update(model).values(authorization_json="{}")
        )
    )
    with pytest.raises(sa.exc.IntegrityError, match="AUTOMATION_DELEGATION_IMMUTABLE"):
        async with sessions() as session, session.begin():
            await session.execute(statement)


async def test_grant_head_cannot_rollback_after_revoke(delegated_host):
    from lib.db.models.automation_grant import AutomationGrantHeadModel

    issuer, sessions, _, grant, run, *_ = delegated_host
    async with sessions() as session, session.begin():
        connection = await session.connection()
        await connection.run_sync(delegation_migration().install_immutability)
    await issuer.revoke(interactive_token=auth.create_token("actor"), run_id=run.run_id, expected_version=grant.version)
    with pytest.raises(sa.exc.IntegrityError, match="AUTOMATION_DELEGATION_IMMUTABLE"):
        async with sessions() as session, session.begin():
            await session.execute(sa.update(AutomationGrantHeadModel).values(version=1))


@pytest.mark.parametrize("change", ["operation", "expiry", "command", "policy", "input", "version"])
async def test_issue_replay_cannot_escalate_original_start_request(delegated_host, change):
    issuer, _, request, _, _, *_ = delegated_host
    changes = {
        "operation": {"operations": frozenset({"BRIEF"})},
        "expiry": {"expires_at": request.expires_at + timedelta(seconds=1)},
        "command": {"command_id": "different-start"},
        "policy": {"policy_digest": "sha256:" + "f" * 64},
        "input": {"input_digest": "sha256:" + "f" * 64},
        "version": {"expected_run_version": request.expected_run_version + 1},
    }
    with pytest.raises(PermissionError):
        await issuer.issue(
            interactive_token=auth.create_token("actor"), request=request.model_copy(update=changes[change])
        )


async def test_interactive_admin_without_scoped_signed_grant_cannot_delegate(delegated_host):
    issuer, _, request, _, _, *_ = delegated_host
    with pytest.raises(PermissionError):
        await issuer.issue(
            interactive_token=auth.create_token("other-admin"),
            request=request.model_copy(update={"issuer_id": "other-admin"}),
        )


async def test_unactivated_custodian_cannot_produce_worker_authority(interactive_env, tmp_path):
    issuer = custodian(None, tmp_path, tmp_path)
    with pytest.raises(PermissionError):
        issuer.authority()


async def test_delegation_migration_roundtrip_preserves_human_events_and_runs(delegated_host):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    _, sessions, _, _, run, *_ = delegated_host
    module = delegation_migration()
    async with sessions.kw["bind"].begin() as connection:

        def roundtrip(sync):
            human = sync.exec_driver_sql("SELECT raw_event FROM r2_showrunner_grant_events").scalars().all()
            state = sync.exec_driver_sql("SELECT snapshot_json FROM auto_production_runs").scalars().all()
            for name in ("auto_authorization_decisions", "auto_grant_heads", "auto_grant_events"):
                sync.exec_driver_sql(f'DROP TABLE "{name}"')
            with Operations.context(MigrationContext.configure(sync)):
                module.upgrade()
                module.downgrade()
                module.upgrade()
            assert sync.exec_driver_sql("SELECT raw_event FROM r2_showrunner_grant_events").scalars().all() == human
            assert sync.exec_driver_sql("SELECT snapshot_json FROM auto_production_runs").scalars().all() == state
            assert run.run_id in state[0]

        await connection.run_sync(roundtrip)


async def test_changed_checkpoint_invalidates_existing_worker_authority(delegated_host):
    issuer, sessions, _, grant, run, _, _, _, root, _ = delegated_host
    authority = issuer.authority()
    async with sessions() as session, session.begin():
        await authority.require_locked(session, subject=subject_for(run, grant))
    (root / "read/grant-checkpoint.json").write_bytes(b"{}")
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await authority.require_locked(session, subject=subject_for(run, grant))


def test_sqlite_delegation_migration_enforces_immutable_history():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine("sqlite://")
    module = delegation_migration()
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql(
                "CREATE TABLE auto_production_runs (user_id TEXT, project_name TEXT, "
                "run_id TEXT, UNIQUE(user_id,project_name,run_id))"
            )
            connection.exec_driver_sql("INSERT INTO auto_production_runs VALUES ('u','p','r')")
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
                connection.exec_driver_sql("INSERT INTO auto_grant_events VALUES ('u','p','r',1,'g','{}')")
                connection.exec_driver_sql("INSERT INTO auto_grant_heads VALUES ('u','p','r','g',1)")
                with pytest.raises(sa.exc.IntegrityError, match="AUTOMATION_DELEGATION_IMMUTABLE"):
                    connection.exec_driver_sql("UPDATE auto_grant_events SET grant_json='[]'")
                with pytest.raises(sa.exc.IntegrityError, match="AUTOMATION_DELEGATION_IMMUTABLE"):
                    connection.exec_driver_sql("UPDATE auto_grant_heads SET version=1")
                module.downgrade()
                assert connection.exec_driver_sql("SELECT count(*) FROM auto_production_runs").scalar_one() == 1
                module.upgrade()
    finally:
        engine.dispose()


async def test_authorization_requires_durable_staged_command_identity(delegated_host):
    issuer, sessions, _, grant, run, *_ = delegated_host
    subject = subject_for(run, grant).model_copy(update={"command_id": "unstaged-command"})
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(session, subject=subject)


@pytest.mark.parametrize("delegated_host", [3], indirect=True)
async def test_expired_child_cannot_reuse_previously_admitted_decision(delegated_host):
    issuer, sessions, _, grant, run, *_ = delegated_host
    subject = subject_for(run, grant)
    async with sessions() as session, session.begin():
        await issuer.authority().require_locked(session, subject=subject)
        await session.execute(sa.text("SELECT pg_sleep(3.1)"))
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await issuer.authority().require_locked(session, subject=subject)


async def test_new_worker_reuses_original_decision_after_fresh_authority_check(delegated_host):
    from lib.db.models.automation_grant import AutomationDecisionModel
    from lib.db.models.production_run import ProductionRunModel
    from lib.db.repositories.production_runs import ProductionRunRepository

    issuer, sessions, _, grant, run, *_ = delegated_host
    authority = issuer.authority()
    original_subject = subject_for(run, grant)
    async with sessions() as session, session.begin():
        original = await authority.require_locked(session, subject=original_subject)
    async with sessions() as session, session.begin():
        await session.execute(
            sa.update(ProductionRunModel)
            .where(ProductionRunModel.run_id == run.run_id)
            .values(lease_until=sa.func.clock_timestamp())
        )
    async with sessions() as session, session.begin():
        current = await ProductionRunRepository(session).claim_due(owner_id="replacement", lease_seconds=30)
    assert current.version > run.version
    assert current.fencing_epoch > run.fencing_epoch
    with pytest.raises(PermissionError):
        async with sessions() as session, session.begin():
            await authority.require_locked(session, subject=original_subject)
    async with sessions() as session, session.begin():
        replay = await authority.require_locked(session, subject=subject_for(current, grant))
        assert replay == original
        assert await session.scalar(sa.select(sa.func.count()).select_from(AutomationDecisionModel)) == 1


async def test_a_renewed_grant_replays_the_commands_admission_and_nothing_else(delegated_host):
    from lib.db.repositories.production_runs import ProductionRunRepository
    from r2.contracts.automation import GrantRequest

    issuer, sessions, request, grant, run, *_ = delegated_host
    authority = issuer.authority()
    async with sessions() as session, session.begin():
        first = await authority.require_locked(session, subject=subject_for(run, grant))
    async with sessions() as session, session.begin():
        current = await ProductionRunRepository(session).get(
            user_id=run.user_id, project_name=run.project_name, run_id=run.run_id
        )
        renewed = await issuer.renew_locked(
            session,
            interactive_token=auth.create_token("actor"),
            request=GrantRequest.model_validate(
                {
                    **request.model_dump(),
                    "command_id": "resume-1",
                    "expected_run_version": current.version,
                    "expires_at": datetime.now(UTC) + timedelta(seconds=1200),
                }
            ),
        )
    assert renewed.version == grant.version + 1

    async with sessions() as session, session.begin():
        replay = await authority.require_locked(session, subject=subject_for(run, renewed))
    assert replay == first
    with pytest.raises(PermissionError, match="AUTOMATION_AUTHORITY_NOT_CURRENT"):
        async with sessions() as session, session.begin():
            await authority.require_locked(session, subject=subject_for(run, grant))
    with pytest.raises(PermissionError, match="AUTOMATION_COMMAND_REPLAY_CONFLICT"):
        async with sessions() as session, session.begin():
            await authority.require_locked(
                session,
                subject=subject_for(run, renewed).model_copy(update={"subject_digest": "sha256:" + "e" * 64}),
            )
