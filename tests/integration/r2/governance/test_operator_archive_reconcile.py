"""A complete retained archive repairs stale public copies only after a database scan."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_reader import OperatorArchiveReader
from server.services import governance_operator_archive as archive_service
from server.services.governance_grants import GovernanceGrantImporter
from server.services.governance_operator_archive import OperatorArchiveReconcileUnavailable, reconcile_complete_archive
from tests.integration.r2.governance.test_governance_schema_preflight import _head
from tests.integration.r2.governance.test_grant_importer import _event, _signed
from tests.unit.r2.governance.test_operator_archive_reader import _append_successor, _put, _tree


async def _ready_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"), {"revision": _head()}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("public_state", ["previous", "new_high_water"])
async def test_pg_reconciles_complete_retained_archive_after_full_scan(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, public_state: str
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator reconciliation requires PostgreSQL schema preflight")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    if public_state == "previous":
        _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)

    result = await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())

    assert result.snapshot.high_water.checkpoint_sequence == 2
    assert paths["public_high_water"].read_bytes() == result.high_water_raw
    assert paths["public_checkpoint"].read_bytes() == result.checkpoint_raw
    assert OperatorArchiveReader(root, expected_uid=os.getuid()).read().checkpoint_raw == result.checkpoint_raw
    again = await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())
    assert again.checkpoint_raw == result.checkpoint_raw


@pytest.mark.asyncio
async def test_pg_divergent_committed_ledger_denies_before_public_replacement(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator reconciliation requires PostgreSQL schema preflight")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(session_factory, key_id="grant-key-a", public_key=public)
    body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
    body["signer_key_id"] = "grant-key-a"
    await importer.import_event(_signed(body, private), scope=GrantScopeV1("u1", "show-a", "reviewer-a"))

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())
    assert paths["public_high_water"].read_bytes() == old_high_water
    assert paths["public_checkpoint"].read_bytes() == old_checkpoint


@pytest.mark.asyncio
async def test_pg_retry_after_high_water_public_write_completes_pair(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator reconciliation requires PostgreSQL schema preflight")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    latest_high_water = (root / "archive" / "high-water" / "00000000000000000002.json").read_bytes()
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    original = archive_service.replace_public_file

    def stop_after_high_water(**kwargs: object) -> None:
        original(**kwargs)
        if kwargs["public_name"] == "high-water.json":
            raise RuntimeError("simulated operator interruption")

    monkeypatch.setattr(archive_service, "replace_public_file", stop_after_high_water)
    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())
    assert paths["public_high_water"].read_bytes() == latest_high_water
    assert paths["public_checkpoint"].read_bytes() == old_checkpoint
    monkeypatch.setattr(archive_service, "replace_public_file", original)

    result = await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())
    assert result.snapshot.high_water.checkpoint_sequence == 2
    assert paths["public_checkpoint"].read_bytes() == result.checkpoint_raw


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["high-water", "checkpoint"])
@pytest.mark.parametrize("matching", [True, False])
async def test_pg_public_temporary_recovery_requires_exact_retained_bytes(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, kind: str, matching: bool
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("operator reconciliation requires PostgreSQL schema preflight")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    latest_checkpoint = paths["public_checkpoint"].read_bytes()
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    retained = (
        (root / "archive" / "high-water" / "00000000000000000002.json").read_bytes()
        if kind == "high-water"
        else latest_checkpoint
    )
    temporary = root / "read" / f".{kind}.00000000000000000002.tmp"
    temporary_raw = retained if matching else b"{}"
    _put(temporary, temporary_raw, 0o644)

    if matching:
        result = await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())
        assert not temporary.exists()
        assert paths["public_high_water"].read_bytes() == result.high_water_raw
        assert paths["public_checkpoint"].read_bytes() == result.checkpoint_raw
    else:
        with pytest.raises(OperatorArchiveReconcileUnavailable):
            await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())
        assert temporary.read_bytes() == temporary_raw
        assert paths["public_high_water"].read_bytes() == old_high_water
        assert paths["public_checkpoint"].read_bytes() == old_checkpoint


@pytest.mark.asyncio
async def test_sqlite_denies_reconciliation_without_public_mutation(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "sqlite":
        pytest.skip("SQLite denial case")
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=os.getuid())
    assert paths["public_high_water"].read_bytes() == old_high_water
    assert paths["public_checkpoint"].read_bytes() == old_checkpoint
