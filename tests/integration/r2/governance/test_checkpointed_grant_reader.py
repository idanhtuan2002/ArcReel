"""A current grant must match a fresh signed checkpoint under its row lock."""

from __future__ import annotations

import asyncio
from datetime import UTC

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantEventModel
from r2.governance.grant_transition import GrantScopeV1
from server.services.governance_grants import (
    CheckpointedShowrunnerGrantReader,
    GovernanceGrantImporter,
    ShowrunnerGrantUnavailableError,
)
from tests.integration.r2.governance.test_grant_import_fence import _wait_for_blocker
from tests.integration.r2.governance.test_grant_importer import _event, _signed
from tests.integration.r2.governance.test_grant_recovery_snapshot import _checkpoint, _head


def _reader(raw: bytes, private: Ed25519PrivateKey, *, fail_load: bool = False) -> CheckpointedShowrunnerGrantReader:
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    async def load() -> bytes:
        if fail_load:
            raise OSError("synthetic secret path")
        return raw

    return CheckpointedShowrunnerGrantReader(
        grant_key_id="test-governance-key",
        grant_public_key=public,
        deployment_id="deploy-a",
        checkpoint_key_id="checkpoint-test-key",
        checkpoint_public_key=public,
        load_checkpoint=load,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["match", "missing_scope", "wrong_signature", "head_mismatch", "old_after_reissue", "loader_failure"]
)
async def test_checkpointed_current_reader_requires_exact_signed_head(
    session_factory: async_sessionmaker[AsyncSession], state: str
) -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    issue = await importer.import_event(_signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private), scope=scope)
    heads = [_head("show-a", 1, issue.event_digest)]
    if state == "old_after_reissue":
        revoke = await importer.import_event(
            _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), private), scope=scope
        )
        await importer.import_event(
            _signed(_event("ISSUE", 3, revoke.event_digest, "2026-03-01T00:00:00Z"), private), scope=scope
        )
    if state == "missing_scope":
        heads = []
    elif state == "head_mismatch":
        heads = [_head("show-a", 1, "sha256:" + "0" * 64)]
    raw = _checkpoint(heads, signer=Ed25519PrivateKey.generate() if state == "wrong_signature" else None)
    reader = _reader(raw, private, fail_load=state == "loader_failure")
    async with session_factory() as session, session.begin():
        if state == "match":
            assert (await reader.require_current_locked(session, scope=scope)).event_digest == issue.event_digest
            row = await session.get(ShowrunnerGrantEventModel, ("u1", "show-a", "reviewer-a", 1))
            assert row is not None
            assert (
                await reader.require_historical_issue_locked(
                    session,
                    scope=scope,
                    event_digest=issue.event_digest,
                    authenticated_at=row.imported_at.replace(tzinfo=UTC),
                )
            ).event_digest == issue.event_digest
        else:
            with pytest.raises(ShowrunnerGrantUnavailableError) as exc:
                await reader.require_current_locked(session, scope=scope)
            assert "synthetic" not in str(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["reader_first", "importer_first"])
async def test_pg_checkpointed_reader_serializes_with_import_and_rechecks_head(
    session_factory: async_sessionmaker[AsyncSession], order: str
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL row-lock blocker evidence")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    base_importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    issue = await base_importer.import_event(
        _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private), scope=scope
    )
    revoke = await base_importer.import_event(
        _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), private), scope=scope
    )
    reader_first_digest: list[str] = []
    if order == "reader_first":
        reissue = await base_importer.import_event(
            _signed(_event("ISSUE", 3, revoke.event_digest, "2026-03-01T00:00:00Z"), private), scope=scope
        )
        reader_first_digest.append(reissue.event_digest)
        current = _checkpoint([_head("show-a", 3, reissue.event_digest)])
        next_raw = _signed(_event("REVOKE", 4, reissue.event_digest, "2026-04-01T00:00:00Z"), private)
    else:
        current = _checkpoint([_head("show-a", 2, revoke.event_digest)])
        next_raw = _signed(_event("ISSUE", 3, revoke.event_digest, "2026-03-01T00:00:00Z"), private)

    reader = _reader(current, private)
    reader_holds = asyncio.Event()
    release_reader = asyncio.Event()
    importer_holds = asyncio.Event()
    release_importer = asyncio.Event()
    reader_pid: list[int] = []
    importer_pid: list[int] = []

    async def hold_import(session: AsyncSession) -> None:
        pid = await session.scalar(select(func.pg_backend_pid()))
        assert isinstance(pid, int)
        if not importer_pid:
            importer_pid.append(pid)
        importer_holds.set()
        await release_importer.wait()

    importer = GovernanceGrantImporter(
        session_factory, key_id="test-governance-key", public_key=public, on_head_locked=hold_import
    )

    async def read() -> str:
        async with session_factory() as session, session.begin():
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            reader_pid.append(pid)
            try:
                event = await reader.require_current_locked(session, scope=scope)
            except ShowrunnerGrantUnavailableError:
                reader_holds.set()
                await release_reader.wait()
                return "denied"
            reader_holds.set()
            await release_reader.wait()
            return event.event_digest

    if order == "reader_first":
        read_task = asyncio.create_task(read())
        await asyncio.wait_for(reader_holds.wait(), timeout=10)
        engine = session_factory.kw["bind"]

        def capture_import(
            connection: Connection, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool
        ) -> None:
            if "pg_advisory_xact_lock_shared" in statement and not importer_pid:
                importer_pid.append(connection.connection.driver_connection.get_server_pid())

        event.listen(engine.sync_engine, "before_cursor_execute", capture_import)
        import_task = asyncio.create_task(importer.import_event(next_raw, scope=scope))
        try:
            await _wait_for_blocker(session_factory, waiter=importer_pid, holder=reader_pid)
            assert not import_task.done()
        finally:
            release_reader.set()
            release_importer.set()
            await asyncio.wait_for(asyncio.gather(read_task, import_task, return_exceptions=True), timeout=10)
            event.remove(engine.sync_engine, "before_cursor_execute", capture_import)
        assert read_task.result() == reader_first_digest[0]
        assert import_task.result().body.event_type == "REVOKE"
    else:
        import_task = asyncio.create_task(importer.import_event(next_raw, scope=scope))
        await asyncio.wait_for(importer_holds.wait(), timeout=10)
        read_task = asyncio.create_task(read())
        try:
            await _wait_for_blocker(session_factory, waiter=reader_pid, holder=importer_pid)
            assert not reader_holds.is_set()
        finally:
            release_importer.set()
            release_reader.set()
            await asyncio.wait_for(asyncio.gather(import_task, read_task, return_exceptions=True), timeout=10)
        assert import_task.result().body.event_type == "ISSUE"
        assert read_task.result() == "denied"
