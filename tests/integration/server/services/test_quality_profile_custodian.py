"""Publication request binding uses the real interactive JWT verifier before external authority I/O."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from r2.quality.errors import OperationalEnvelopeExceededError, ProfilePublicationUnauthorizedError
from server import auth
from server.services.quality_profile_custodian import InteractiveProfilePublicationCustodian
from tests.unit.r2.quality.test_quality_profiles import publication_request, sized_request

MIGRATION_PATH = Path(__file__).resolve().parents[4] / "alembic/versions/65f53650f3a8_quality_profile_publication.py"

SECRET = "m10-test-secret-that-is-at-least-32-bytes"


class ForbiddenSessions:
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("preflight crossed the external database boundary")


@pytest.fixture
def interactive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_SECRET", SECRET)


async def bind(request, token: str | None, path: Path):
    return await InteractiveProfilePublicationCustodian.for_request(
        request,
        cast(async_sessionmaker[AsyncSession], ForbiddenSessions()),
        interactive_token=token,
        read_directory=path / "missing-read-directory",
        socket_directory=path / "missing-attestor-directory",
        expected_uid=0,
        expected_gid=0,
    )


async def test_valid_interactive_factory_binds_without_database_or_archive_io(interactive_env, tmp_path: Path) -> None:
    request = publication_request(user_id="default")
    token = auth.create_token("actor")
    wrapper = await bind(request, token, tmp_path)
    assert await wrapper.require_actor(request) is None
    assert token not in repr(wrapper)
    assert SECRET not in repr(wrapper)
    with pytest.raises(ProfilePublicationUnauthorizedError):
        await wrapper.require_actor(publication_request(user_id="default", cohort_id="other"))


@pytest.mark.parametrize(
    "kind", ["missing", "api_key", "invalid", "download", "expired", "disabled", "other_principal", "other_tenant"]
)
async def test_factory_refuses_noninteractive_or_mismatched_identity_before_io(
    interactive_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    request = publication_request(user_id="other" if kind == "other_tenant" else "default")
    token = auth.create_token("other" if kind == "other_principal" else "actor")
    if kind == "missing":
        token = None
    elif kind == "api_key":
        token = "arc-test-key"
    elif kind == "invalid":
        token = "invalid-jwt"
    elif kind == "download":
        token = auth.create_download_token("actor", "project")
    elif kind == "expired":
        import jwt

        token = jwt.encode({"sub": "actor", "iat": 0, "exp": 1}, SECRET, algorithm="HS256")
    elif kind == "disabled":
        monkeypatch.setenv("AUTH_ENABLED", "false")
    with pytest.raises(ProfilePublicationUnauthorizedError):
        await bind(request, token, tmp_path)


async def test_oversized_factory_input_refuses_before_auth_database_or_archive(interactive_env, tmp_path: Path) -> None:
    with pytest.raises(OperationalEnvelopeExceededError):
        await bind(sized_request(1_048_577), None, tmp_path)


async def prepare_qualified_custody(sessions, tmp_path: Path):
    """Construct real signed/checkpointed host fixtures; version-table input is fixture state."""
    import hashlib
    import importlib.util
    import json

    import sqlalchemy as sa
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from lib.content_digest import canonical_json_bytes
    from r2.governance.grant_transition import GrantScopeV1
    from server.services.governance_grants import GovernanceGrantImporter
    from tests.integration.r2.governance.test_grant_importer import _event, _signed
    from tests.integration.r2.governance.test_operator_archive_reconcile import _ready_schema
    from tests.unit.r2.governance.test_operator_archive_reader import _put, _tree

    engine = sessions.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("activated Human publication requires PostgreSQL")
    await _ready_schema(engine)
    event_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    public = event_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(sessions, key_id="grant-key-a", public_key=public)
    body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z", project_name="project")
    body.update(user_id="default", principal="actor", signer_key_id="grant-key-a")
    event = await importer.import_event(_signed(body, event_key), scope=GrantScopeV1("default", "project", "actor"))

    def files():
        root, paths = _tree(tmp_path)
        runtime = tmp_path / "run"
        runtime.mkdir(mode=0o700)
        checkpoint_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        old_path = paths["checkpoint"]
        checkpoint_body = json.loads(old_path.read_bytes())["body"]
        checkpoint_body["heads"] = [
            {
                "user_id": "default",
                "project_name": "project",
                "principal": "actor",
                "head_sequence": 1,
                "head_event_digest": event.event_digest,
            }
        ]
        checkpoint = _signed(checkpoint_body, checkpoint_key)

        def digest(raw: bytes) -> str:
            return "sha256:" + hashlib.sha256(raw).hexdigest()

        destination = root / "archive/checkpoints" / ("sha256-" + digest(checkpoint)[7:] + ".json")
        _put(destination, checkpoint, 0o600)
        old_path.unlink()
        _put(paths["public_checkpoint"], checkpoint, 0o644)
        high = json.loads(paths["high_water"].read_bytes())
        high.update(
            checkpoint_body_digest=digest(canonical_json_bytes(checkpoint_body, allow_nan=False)),
            checkpoint_file_digest=digest(checkpoint),
        )
        raw = canonical_json_bytes(high, allow_nan=False)
        _put(paths["high_water"], raw, 0o600)
        _put(paths["public_high_water"], raw, 0o644)
        return root, runtime

    root, runtime = files()
    migration_path = MIGRATION_PATH
    spec = importlib.util.spec_from_file_location("m10_custodian_migration_fixture", migration_path)
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    async with engine.begin() as connection:
        await connection.run_sync(migration.install_immutability)
        assert await connection.scalar(sa.text("SELECT count(*) FROM r2_showrunner_grant_events")) == 1
    return root, runtime, importer, event_key, event


@pytest.fixture
async def qualified_host(session_factory, tmp_path: Path, interactive_env):
    import os

    from server.services.governance_attestation import serve_governance_attestor

    root, runtime, importer, key, event = await prepare_qualified_custody(session_factory, tmp_path)
    async with serve_governance_attestor(
        root, runtime, session_factory=session_factory, expected_uid=os.getuid(), expected_gid=os.getgid()
    ):
        wrapper = await InteractiveProfilePublicationCustodian.for_request(
            publication_request(user_id="default"),
            session_factory,
            interactive_token=auth.create_token("actor"),
            read_directory=root / "read",
            socket_directory=runtime,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
        )
        yield wrapper, session_factory, root, runtime, importer, key, event


async def test_real_activated_issuer_persists_action_receipt_and_admits_under_current_grant(qualified_host) -> None:
    import sqlalchemy as sa

    from lib.db.models.quality import ProfilePublicationAuthorizationModel
    from lib.db.repositories.quality import QualityProfileRepository

    wrapper, sessions, *_ = qualified_host
    request = publication_request(user_id="default")
    lease = await wrapper.authorize_publication(request)
    assert lease.action == "PROFILE_PUBLICATION"
    assert lease.actor_id == "actor"
    assert 0 < (lease.admit_not_after - lease.issued_at).total_seconds() <= 30
    async with sessions() as session, session.begin():
        stored = await QualityProfileRepository(session).load_authorization(request, lease.authorization_id)
        assert stored is not None
        assert stored.lease == lease
        assert stored.grant_sequence == 1
        await wrapper.lock_current_grant(session, request, lease)
        admitted = await wrapper.admit_locked(session, request, lease)
        assert lease.issued_at <= admitted < lease.admit_not_after
        assert (
            await session.execute(sa.select(sa.func.count()).select_from(ProfilePublicationAuthorizationModel))
        ).scalar_one() == 1


async def test_missing_independent_archive_refuses_new_issuance(interactive_env, tmp_path: Path) -> None:
    request = publication_request(user_id="default")
    wrapper = await bind(request, auth.create_token("actor"), tmp_path)
    with pytest.raises(ProfilePublicationUnauthorizedError):
        await wrapper.authorize_publication(request)


async def test_data_lease_and_unactivated_wrapper_cannot_admit(qualified_host) -> None:
    import os

    wrapper, sessions, root, runtime, *_ = qualified_host
    request = publication_request(user_id="default")
    lease = await wrapper.authorize_publication(request)
    unactivated = await InteractiveProfilePublicationCustodian.for_request(
        request,
        sessions,
        interactive_token=auth.create_token("actor"),
        read_directory=root / "read",
        socket_directory=runtime,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    async with sessions() as session, session.begin():
        with pytest.raises(ProfilePublicationUnauthorizedError):
            await unactivated.admit_locked(session, request, lease)


async def test_revoked_current_grant_refuses_existing_action_lease(qualified_host) -> None:
    from r2.governance.grant_transition import GrantScopeV1
    from tests.integration.r2.governance.test_grant_importer import _event, _signed

    wrapper, sessions, _, _, importer, key, event = qualified_host
    request = publication_request(user_id="default")
    lease = await wrapper.authorize_publication(request)
    body = _event("REVOKE", 2, event.event_digest, "2026-10-27T00:00:00Z", project_name="project")
    body.update(user_id="default", principal="actor", signer_key_id="grant-key-a")
    await importer.import_event(_signed(body, key), scope=GrantScopeV1("default", "project", "actor"))
    async with sessions() as session, session.begin():
        with pytest.raises(ProfilePublicationUnauthorizedError):
            await wrapper.admit_locked(session, request, lease)


async def test_issuer_and_publisher_reject_oversize_before_any_external_io(interactive_env, tmp_path: Path) -> None:
    from server.services.quality_profiles import ProfilePublicationService

    request = publication_request(user_id="default")
    wrapper = await bind(request, auth.create_token("actor"), tmp_path)
    service = ProfilePublicationService(cast(async_sessionmaker[AsyncSession], ForbiddenSessions()), custodian=wrapper)
    oversized = sized_request(1_048_577)
    with pytest.raises(OperationalEnvelopeExceededError):
        await wrapper.authorize_publication(oversized)
    with pytest.raises(OperationalEnvelopeExceededError):
        await service.publish(oversized)


async def test_factual_policy_refuses_factory_issuer_and_publisher_before_io(interactive_env, tmp_path: Path) -> None:
    from r2.quality.errors import PrerequisiteNotAcceptedError
    from server.services.quality_profiles import ProfilePublicationService
    from tests.unit.r2.contracts.test_quality import policy_data

    policy = policy_data()
    policy["assessment_requirements"][0]["slots"][0]["kind"] = "FACTUAL"
    factual = publication_request(user_id="default", policy=policy)
    wrapper = await bind(publication_request(user_id="default"), auth.create_token("actor"), tmp_path)
    service = ProfilePublicationService(cast(async_sessionmaker[AsyncSession], ForbiddenSessions()), custodian=wrapper)
    with pytest.raises(PrerequisiteNotAcceptedError):
        await bind(factual, None, tmp_path)
    with pytest.raises(PrerequisiteNotAcceptedError):
        await wrapper.authorize_publication(factual)
    with pytest.raises(PrerequisiteNotAcceptedError):
        await service.publish(factual)


async def test_final_admission_rechecks_jwt_after_authority_io(qualified_host, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlalchemy as sa

    wrapper, sessions, *_rest = qualified_host
    request = publication_request(user_id="default")
    lease = await wrapper.authorize_publication(request)
    engine = sessions.kw["bind"].sync_engine
    changed = False

    def rotate_after_grant_io(connection, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if "FROM r2_showrunner_grant_events" in statement:
            monkeypatch.setenv("AUTH_TOKEN_SECRET", "rotated-test-secret-with-at-least-32-bytes")
            changed = True

    sa.event.listen(engine, "after_cursor_execute", rotate_after_grant_io)
    try:
        async with sessions() as session, session.begin():
            with pytest.raises(ProfilePublicationUnauthorizedError):
                await wrapper.admit_locked(session, request, lease)
        assert changed
    finally:
        sa.event.remove(engine, "after_cursor_execute", rotate_after_grant_io)


@pytest.mark.parametrize("field", ["authorization_id", "policy_id", "subject_digest"])
async def test_final_admission_refuses_a_forged_action_lease(qualified_host, field: str) -> None:
    wrapper, sessions, *_rest = qualified_host
    request = publication_request(user_id="default")
    lease = await wrapper.authorize_publication(request)
    changed = "sha256:" + "b" * 64 if field == "subject_digest" else "unissued-or-wrong-policy"
    forged = lease.model_copy(update={field: changed})
    async with sessions() as session, session.begin():
        with pytest.raises(ProfilePublicationUnauthorizedError):
            await wrapper.admit_locked(session, request, forged)


async def test_request_wrapper_binds_the_physical_command_id(interactive_env, tmp_path: Path) -> None:
    request = publication_request(user_id="default")
    wrapper = await bind(request, auth.create_token("actor"), tmp_path)
    changed = request.model_copy(update={"command": request.command.model_copy(update={"command_id": "other-command"})})
    with pytest.raises(ProfilePublicationUnauthorizedError):
        await wrapper.require_actor(changed)
