"""An offline operator preflight verifies the archive and committed grant ledger together."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_reader import OperatorArchiveReader
from server.services.governance_grants import GovernanceGrantImporter, GovernanceGrantRecoveryScanner
from server.services.governance_operator_archive import (
    OperatorArchiveReconcileUnavailable,
    verify_operator_archive_preflight,
)
from server.services.governance_startup import GovernanceStartupUnavailable, verify_governance_public_startup
from tests.integration.r2.governance.test_grant_importer import _event, _signed
from tests.integration.r2.governance.test_operator_archive_reconcile import _ready_schema
from tests.unit.r2.governance.test_operator_archive_reader import _append_successor, _put, _tree


@pytest.mark.asyncio
async def test_pg_offline_preflight_keeps_one_exact_archive_snapshot_through_ledger_scan(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator preflight requires PostgreSQL")
    await _ready_schema(engine)
    root, _paths = _tree(tmp_path)

    result = await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=os.getuid())

    assert result == OperatorArchiveReader(root, expected_uid=os.getuid()).read()


@pytest.mark.asyncio
async def test_pg_offline_preflight_denies_old_public_pair_against_newer_retained_archive(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator preflight requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=os.getuid())

    assert paths["public_high_water"].read_bytes() == old_high_water
    assert paths["public_checkpoint"].read_bytes() == old_checkpoint


@pytest.mark.asyncio
async def test_pg_offline_preflight_denies_committed_grant_absent_from_checkpoint(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator preflight requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(session_factory, key_id="grant-key-a", public_key=public)
    body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
    body["signer_key_id"] = "grant-key-a"
    await importer.import_event(_signed(body, private), scope=GrantScopeV1("u1", "show-a", "reviewer-a"))
    original = paths["public_checkpoint"].read_bytes()

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=os.getuid())

    assert paths["public_checkpoint"].read_bytes() == original


@pytest.mark.asyncio
async def test_pg_offline_preflight_denies_public_change_after_database_scan(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator preflight requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    original = GovernanceGrantRecoveryScanner.verify

    async def replace_after_scan(
        self: GovernanceGrantRecoveryScanner, load_checkpoint: Callable[[], Awaitable[bytes]]
    ) -> object:
        result = await original(self, load_checkpoint)
        _put(paths["public_checkpoint"], b"{}", 0o644)
        return result

    monkeypatch.setattr(GovernanceGrantRecoveryScanner, "verify", replace_after_scan)

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=os.getuid())

    assert paths["public_checkpoint"].read_bytes() == b"{}"


@pytest.mark.asyncio
async def test_sqlite_offline_preflight_denies_without_archive_mutation(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "sqlite":
        pytest.skip("SQLite denial case")
    root, paths = _tree(tmp_path)
    original = paths["public_checkpoint"].read_bytes()

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=os.getuid())

    assert paths["public_checkpoint"].read_bytes() == original


@pytest.mark.asyncio
async def test_pg_public_startup_verifies_copies_and_ledger_without_archive_access(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("public startup requires PostgreSQL")
    await _ready_schema(engine)
    root, _paths = _tree(tmp_path)

    reader = await verify_governance_public_startup(root / "read", session_factory=session_factory)

    assert reader is not None


@pytest.mark.asyncio
async def test_pg_public_startup_denies_committed_grant_missing_from_checkpoint(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("public startup requires PostgreSQL")
    await _ready_schema(engine)
    root, _paths = _tree(tmp_path)
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(session_factory, key_id="grant-key-a", public_key=public)
    body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
    body["signer_key_id"] = "grant-key-a"
    await importer.import_event(_signed(body, private), scope=GrantScopeV1("u1", "show-a", "reviewer-a"))

    with pytest.raises(GovernanceStartupUnavailable):
        await verify_governance_public_startup(root / "read", session_factory=session_factory)


@pytest.mark.asyncio
async def test_pg_public_startup_denies_public_replace_after_scan(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("public startup requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    original = GovernanceGrantRecoveryScanner.verify

    async def replace_after_scan(
        self: GovernanceGrantRecoveryScanner, load_checkpoint: Callable[[], Awaitable[bytes]]
    ) -> object:
        result = await original(self, load_checkpoint)
        _put(paths["public_checkpoint"], b"{}", 0o644)
        return result

    monkeypatch.setattr(GovernanceGrantRecoveryScanner, "verify", replace_after_scan)

    with pytest.raises(GovernanceStartupUnavailable):
        await verify_governance_public_startup(root / "read", session_factory=session_factory)


@pytest.mark.asyncio
async def test_pg_activated_lifespan_denies_stale_ledger_before_db_mutation_or_readiness(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("activated startup requires PostgreSQL")
    await _ready_schema(engine)
    root, _paths = _tree(tmp_path)
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(session_factory, key_id="grant-key-a", public_key=public)
    body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
    body["signer_key_id"] = "grant-key-a"
    await importer.import_event(_signed(body, private), scope=GrantScopeV1("u1", "show-a", "reviewer-a"))

    import server.app as app_module

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("startup side effect occurred before Governance preflight")

    async def forbidden_async(*_args: object, **_kwargs: object) -> None:
        forbidden()

    monkeypatch.setenv("ARCREEL_GOVERNANCE_READ_DIR", str(root / "read"))
    monkeypatch.setattr(app_module, "async_session_factory", session_factory)
    monkeypatch.setattr(app_module, "migrate_legacy_log_dir", lambda: None)
    monkeypatch.setattr(app_module, "attach_file_handler", lambda: None)
    monkeypatch.setattr(app_module, "ensure_auth_password", lambda: None)
    monkeypatch.setattr(app_module, "init_db", forbidden_async)
    monkeypatch.setattr(app_module, "startup_http_client", forbidden_async)
    app_module.app.state = SimpleNamespace()

    with pytest.raises(GovernanceStartupUnavailable):
        async with app_module.lifespan(app_module.app):
            raise AssertionError("lifespan yielded before Governance denial")
