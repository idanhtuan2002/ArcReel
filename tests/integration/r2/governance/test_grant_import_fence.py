"""Grant imports and full recovery scans serialize before scope enumeration."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantHeadModel
from r2.governance.grant_transition import GrantScopeV1
from server.services.governance_grant_fence import (
    GrantRecoveryFenceUnavailable,
    acquire_grant_import_fence,
    acquire_grant_recovery_scan_fence,
)
from server.services.governance_grants import CurrentShowrunnerGrantReader, GovernanceGrantImporter
from tests.integration.r2.governance.test_grant_importer import _event, _signed


async def _wait_for_blocker(factory: async_sessionmaker[AsyncSession], *, waiter: list[int], holder: list[int]) -> None:
    async with asyncio.timeout(10):
        while True:
            async with factory() as observer:
                blockers = await observer.scalar(select(func.pg_blocking_pids(waiter[0]))) if waiter else []
            if holder and holder[0] in blockers:
                return
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("order", ["scanner_first", "import_first"])
async def test_pg_grant_import_and_recovery_scan_fence_both_orders(
    session_factory: async_sessionmaker[AsyncSession], order: str
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL transaction advisory locks")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    raw = _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private)
    scan_acquired = asyncio.Event()
    release_scan = asyncio.Event()
    scan_pid: list[int] = []
    import_pid: list[int] = []

    async def scan() -> int:
        async with session_factory() as session, session.begin():
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            scan_pid.append(pid)
            await acquire_grant_recovery_scan_fence(session)
            scan_acquired.set()
            await release_scan.wait()
            return await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)) or 0

    if order == "scanner_first":
        engine = session_factory.kw["bind"]

        def capture_import(
            connection: Connection, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool
        ) -> None:
            if "pg_advisory_xact_lock_shared" in statement and not import_pid:
                import_pid.append(connection.connection.driver_connection.get_server_pid())

        event.listen(engine.sync_engine, "before_cursor_execute", capture_import)
        importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
        scan_task = asyncio.create_task(scan())
        import_task = None
        try:
            await asyncio.wait_for(scan_acquired.wait(), timeout=10)
            import_task = asyncio.create_task(importer.import_event(raw, scope=scope))
            await _wait_for_blocker(session_factory, waiter=import_pid, holder=scan_pid)
            async with session_factory() as observer:
                assert await observer.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)) == 0
            assert not import_task.done()
        finally:
            release_scan.set()
            event.remove(engine.sync_engine, "before_cursor_execute", capture_import)
            if import_task is not None:
                await asyncio.wait_for(asyncio.gather(scan_task, import_task, return_exceptions=True), timeout=10)
            else:
                await asyncio.wait_for(asyncio.gather(scan_task, return_exceptions=True), timeout=10)
        assert scan_task.result() == 0
        assert import_task is not None
        assert import_task.result().body.sequence == 1
    else:
        import_locked = asyncio.Event()
        release_import = asyncio.Event()

        async def hold_import(session: AsyncSession) -> None:
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            import_pid.append(pid)
            import_locked.set()
            await release_import.wait()

        importer = GovernanceGrantImporter(
            session_factory, key_id="test-governance-key", public_key=public, on_head_locked=hold_import
        )
        import_task = asyncio.create_task(importer.import_event(raw, scope=scope))
        scan_task = None
        try:
            await asyncio.wait_for(import_locked.wait(), timeout=10)
            scan_task = asyncio.create_task(scan())
            await _wait_for_blocker(session_factory, waiter=scan_pid, holder=import_pid)
            assert not scan_acquired.is_set()
            assert not scan_task.done()
        finally:
            release_import.set()
            release_scan.set()
            if scan_task is not None:
                await asyncio.wait_for(asyncio.gather(import_task, scan_task, return_exceptions=True), timeout=10)
            else:
                await asyncio.wait_for(asyncio.gather(import_task, return_exceptions=True), timeout=10)
        assert import_task.result().body.sequence == 1
        assert scan_task is not None
        assert scan_task.result() == 1


@pytest.mark.asyncio
async def test_pg_distinct_imports_share_fence_and_rollback_releases_it(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL transaction advisory locks")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    issued_at = (datetime.now(UTC).replace(microsecond=0)).strftime("%Y-%m-%dT%H:%M:%SZ")
    reached: set[str] = set()
    both_reached = asyncio.Event()
    release = asyncio.Event()

    async def hold_import(session: AsyncSession) -> None:
        project = await session.scalar(select(ShowrunnerGrantHeadModel.project_name))
        assert isinstance(project, str)
        reached.add(project)
        if len(reached) == 2:
            both_reached.set()
        await release.wait()
        if project == "show-b":
            raise RuntimeError("forced second-scope rollback")

    importer = GovernanceGrantImporter(
        session_factory, key_id="test-governance-key", public_key=public, on_head_locked=hold_import
    )
    first = asyncio.create_task(
        importer.import_event(
            _signed(_event("ISSUE", 1, None, issued_at, project_name="show-a"), private),
            scope=GrantScopeV1("u1", "show-a", "reviewer-a"),
        )
    )
    second = asyncio.create_task(
        importer.import_event(
            _signed(_event("ISSUE", 1, None, issued_at, project_name="show-b"), private),
            scope=GrantScopeV1("u1", "show-b", "reviewer-a"),
        )
    )
    try:
        await asyncio.wait_for(both_reached.wait(), timeout=10)
        assert not first.done()
        assert not second.done()
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), timeout=10)
    assert first.result().body.project_name == "show-a"
    with pytest.raises(RuntimeError, match="forced second-scope rollback"):
        second.result()
    async with session_factory() as session, session.begin():
        await acquire_grant_recovery_scan_fence(session)
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)) == 1


@pytest.mark.asyncio
async def test_recovery_scan_fence_denies_without_postgresql(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("SQLite denial is tested on the SQLite fixture")
        with pytest.raises(GrantRecoveryFenceUnavailable):
            await acquire_grant_recovery_scan_fence(session)


@pytest.mark.asyncio
async def test_import_fence_denies_unsupported_database_dialect() -> None:
    class UnsupportedSession:
        def in_transaction(self) -> bool:
            return True

        def get_bind(self) -> SimpleNamespace:
            return SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

    with pytest.raises(GrantRecoveryFenceUnavailable):
        await acquire_grant_import_fence(cast(AsyncSession, UnsupportedSession()))


@pytest.mark.asyncio
async def test_pg_reader_importer_scanner_lock_chain_finishes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL transaction advisory locks")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=public)
    issue = await importer.import_event(_signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private), scope=scope)
    reader_holds_head = asyncio.Event()
    release_reader = asyncio.Event()
    reader_pid: list[int] = []
    scan_pid: list[int] = []

    async def hold_reader() -> None:
        async with session_factory() as session, session.begin():
            assert (await reader.require_current_locked(session, scope=scope)).event_digest == issue.event_digest
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            reader_pid.append(pid)
            reader_holds_head.set()
            await release_reader.wait()

    async def scan() -> int:
        async with session_factory() as session, session.begin():
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            scan_pid.append(pid)
            await acquire_grant_recovery_scan_fence(session)
            head = await session.get(ShowrunnerGrantHeadModel, (scope.user_id, scope.project_name, scope.principal))
            assert head is not None
            assert head.current_sequence is not None
            return head.current_sequence

    reader_task = asyncio.create_task(hold_reader())
    import_task = None
    scan_task = None
    try:
        await asyncio.wait_for(reader_holds_head.wait(), timeout=10)
        revoke = _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), private)
        import_task = asyncio.create_task(importer.import_event(revoke, scope=scope))
        importer_pid: list[int] = []
        async with asyncio.timeout(10):
            while not importer_pid:
                async with session_factory() as observer:
                    importer_pid = list(
                        (
                            await observer.scalars(
                                text("SELECT pid FROM pg_stat_activity WHERE :reader_pid = ANY(pg_blocking_pids(pid))"),
                                {"reader_pid": reader_pid[0]},
                            )
                        ).all()
                    )
                if not importer_pid:
                    await asyncio.sleep(0.01)
        scan_task = asyncio.create_task(scan())
        await _wait_for_blocker(session_factory, waiter=scan_pid, holder=importer_pid)
        assert not import_task.done()
        assert not scan_task.done()
    finally:
        release_reader.set()
        if import_task is None:
            await asyncio.wait_for(asyncio.gather(reader_task, return_exceptions=True), timeout=10)
        elif scan_task is None:
            await asyncio.wait_for(asyncio.gather(reader_task, import_task, return_exceptions=True), timeout=10)
        else:
            await asyncio.wait_for(
                asyncio.gather(reader_task, import_task, scan_task, return_exceptions=True), timeout=10
            )
    reader_task.result()
    assert import_task is not None
    assert scan_task is not None
    assert import_task.result().body.event_type == "REVOKE"
    assert scan_task.result() == 2
