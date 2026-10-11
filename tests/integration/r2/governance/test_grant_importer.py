"""A signed Governance event controls one scoped grant head."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from lib.db.models.governance_grant import ShowrunnerGrantEventModel, ShowrunnerGrantHeadModel
from lib.db.models.user import User
from r2.governance.grant_transition import GrantScopeV1
from server.services.governance_grants import (
    CurrentShowrunnerGrantReader,
    GovernanceGrantImporter,
    ShowrunnerGrantUnavailableError,
)


def _signed(body: dict[str, object], private: Ed25519PrivateKey) -> bytes:
    signature = base64.urlsafe_b64encode(private.sign(canonical_json_bytes(body, allow_nan=False))).decode().rstrip("=")
    return canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)


def _event(
    action: str,
    sequence: int,
    predecessor: str | None,
    issued_at: str,
    *,
    project_name: str = "show-a",
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "governance.showrunner_grant_event.v1",
        "event_type": action,
        "user_id": "u1",
        "project_name": project_name,
        "principal": "reviewer-a",
        "role": "HUMAN_SHOWRUNNER",
        "sequence": sequence,
        "previous_event_digest": predecessor,
        "issued_at": issued_at,
        "signer_key_id": "test-governance-key",
    }
    if action == "ISSUE":
        body["not_before"] = issued_at
        body["expires_at"] = (datetime.now(UTC) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return body


@pytest.mark.asyncio
async def test_import_issue_revoke_and_reissue_is_scoped_and_replay_safe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    async with session_factory() as session, session.begin():
        if await session.get(User, "u1") is None:
            session.add(User(id="u1", username="u1"))
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=public)

    issue_raw = _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private)
    issue = await importer.import_event(issue_raw, scope=scope)
    assert await importer.import_event(issue_raw, scope=scope) == issue
    async with session_factory() as session, session.begin():
        assert (await reader.require_current_locked(session, scope=scope)).event_digest == issue.event_digest
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantEventModel)) == 1

    revoke_raw = _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), private)
    revoke = await importer.import_event(revoke_raw, scope=scope)
    async with session_factory() as session, session.begin():
        with pytest.raises(ShowrunnerGrantUnavailableError):
            await reader.require_current_locked(session, scope=scope)
    reissue_raw = _signed(_event("ISSUE", 3, revoke.event_digest, "2026-03-01T00:00:00Z"), private)
    reissue = await importer.import_event(reissue_raw, scope=scope)
    async with session_factory() as session, session.begin():
        assert (await reader.require_current_locked(session, scope=scope)).event_digest == reissue.event_digest
        old_authorization_time = datetime(2026, 1, 2, tzinfo=UTC)
        assert (
            await reader.require_historical_issue_locked(
                session,
                scope=scope,
                event_digest=issue.event_digest,
                authenticated_at=old_authorization_time,
            )
        ).event_digest == issue.event_digest
        for event_digest, authenticated_at in (
            ("sha256:" + "0" * 64, old_authorization_time),
            (revoke.event_digest, datetime(2026, 2, 2, tzinfo=UTC)),
            (issue.event_digest, datetime(2026, 2, 2, tzinfo=UTC)),
        ):
            with pytest.raises(ShowrunnerGrantUnavailableError):
                await reader.require_historical_issue_locked(
                    session,
                    scope=scope,
                    event_digest=event_digest,
                    authenticated_at=authenticated_at,
                )
        head = await session.get(ShowrunnerGrantHeadModel, ("u1", "show-a", "reviewer-a"))
        assert head is not None
        assert head.current_sequence == 3
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantEventModel)) == 3


@pytest.mark.asyncio
async def test_import_rejects_other_scope_without_creating_head(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    raw = _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z", project_name="other-show"), private)
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await importer.import_event(raw, scope=GrantScopeV1("u1", "show-a", "reviewer-a"))
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)) == 0


@pytest.mark.asyncio
async def test_invalid_first_event_rolls_back_head_claim(session_factory: async_sessionmaker[AsyncSession]) -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    async with session_factory() as session, session.begin():
        if await session.get(User, "u1") is None:
            session.add(User(id="u1", username="u1"))
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    raw = _signed(_event("REVOKE", 1, None, "2026-01-01T00:00:00Z"), private)
    with pytest.raises(ShowrunnerGrantUnavailableError):
        await importer.import_event(raw, scope=scope)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantEventModel)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["signed_bytes", "head_digest"])
async def test_reader_recomputes_stored_grant_integrity(
    session_factory: async_sessionmaker[AsyncSession], tamper: str
) -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    async with session_factory() as session, session.begin():
        if await session.get(User, "u1") is None:
            session.add(User(id="u1", username="u1"))
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=public)
    await importer.import_event(_signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private), scope=scope)
    async with session_factory() as session, session.begin():
        if tamper == "signed_bytes":
            row = await session.get(ShowrunnerGrantEventModel, ("u1", "show-a", "reviewer-a", 1))
            assert row is not None
            row.raw_event = row.raw_event + b" "
        else:
            head = await session.get(ShowrunnerGrantHeadModel, ("u1", "show-a", "reviewer-a"))
            assert head is not None
            head.current_event_digest = "sha256:" + "0" * 64
    async with session_factory() as session, session.begin():
        with pytest.raises(ShowrunnerGrantUnavailableError):
            await reader.require_current_locked(session, scope=scope)


@pytest.mark.asyncio
async def test_reader_rejects_missing_older_signed_event(session_factory: async_sessionmaker[AsyncSession]) -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    async with session_factory() as session, session.begin():
        if await session.get(User, "u1") is None:
            session.add(User(id="u1", username="u1"))
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=public)
    issue = await importer.import_event(_signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private), scope=scope)
    revoke = await importer.import_event(
        _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), private), scope=scope
    )
    await importer.import_event(
        _signed(_event("ISSUE", 3, revoke.event_digest, "2026-03-01T00:00:00Z"), private), scope=scope
    )
    async with session_factory() as session, session.begin():
        first = await session.get(ShowrunnerGrantEventModel, ("u1", "show-a", "reviewer-a", 1))
        assert first is not None
        await session.delete(first)
    async with session_factory() as session, session.begin():
        with pytest.raises(ShowrunnerGrantUnavailableError):
            await reader.require_current_locked(session, scope=scope)


@pytest.mark.asyncio
async def test_pg_head_fk_cannot_point_to_another_projects_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL foreign keys")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    async with session_factory() as session, session.begin():
        if await session.get(User, "u1") is None:
            session.add(User(id="u1", username="u1"))
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    issue = await importer.import_event(
        _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z", project_name="show-b"), private),
        scope=GrantScopeV1("u1", "show-b", "reviewer-a"),
    )
    async with session_factory() as session:
        head = ShowrunnerGrantHeadModel(user_id="u1", project_name="show-a", principal="reviewer-a")
        session.add(head)
        await session.flush()
        head.current_sequence = 1
        head.current_event_digest = issue.event_digest
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_pg_session_timezone_cannot_activate_future_grant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL session timezone")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
    body["not_before"] = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    async with session_factory() as session, session.begin():
        if await session.get(User, "u1") is None:
            session.add(User(id="u1", username="u1"))
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=public)
    await importer.import_event(_signed(body, private), scope=scope)
    async with session_factory() as session, session.begin():
        await session.execute(text("SET LOCAL TIME ZONE 'Asia/Bangkok'"))
        assert await session.scalar(text("SHOW TIME ZONE")) == "Asia/Bangkok"
        with pytest.raises(ShowrunnerGrantUnavailableError):
            await reader.require_current_locked(session, scope=scope)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_rolls_back", [False, True])
async def test_pg_first_writer_serializes_same_grant_event(
    session_factory: async_sessionmaker[AsyncSession], first_rolls_back: bool
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL row locks")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    raw = _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private)
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    first_pids: list[int] = []

    async def pause_after_lock(session: AsyncSession) -> None:
        if not first_locked.is_set():
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert pid is not None
            first_pids.append(pid)
            first_locked.set()
            await release_first.wait()
            if first_rolls_back:
                raise RuntimeError("test rollback after claiming grant head")

    importer = GovernanceGrantImporter(
        session_factory, key_id="test-governance-key", public_key=public, on_head_locked=pause_after_lock
    )
    first = asyncio.create_task(importer.import_event(raw, scope=scope))
    second: asyncio.Task | None = None
    try:
        await asyncio.wait_for(first_locked.wait(), timeout=10)
        assert len(first_pids) == 1
        second = asyncio.create_task(importer.import_event(raw, scope=scope))
        blocked: list[int] = []
        for _ in range(100):
            async with session_factory() as observer:
                blocked = list(
                    (
                        await observer.scalars(
                            text(
                                "SELECT pid FROM pg_stat_activity WHERE pid <> :first_pid "
                                "AND :first_pid = ANY(pg_blocking_pids(pid))"
                            ),
                            {"first_pid": first_pids[0]},
                        )
                    ).all()
                )
            if blocked:
                break
            await asyncio.sleep(0.05)
        assert len(blocked) == 1
        assert not second.done()
    finally:
        release_first.set()
    first_result = None
    if first_rolls_back:
        with pytest.raises(RuntimeError, match="test rollback"):
            await asyncio.wait_for(first, timeout=10)
    else:
        first_result = await asyncio.wait_for(first, timeout=10)
    assert second is not None
    second_result = await asyncio.wait_for(second, timeout=10)
    if not first_rolls_back:
        assert first_result is not None
        assert second_result == first_result
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)) == 1
        assert await session.scalar(select(func.count()).select_from(ShowrunnerGrantEventModel)) == 1
        head = await session.get(ShowrunnerGrantHeadModel, ("u1", "show-a", "reviewer-a"))
        assert head is not None
        assert head.current_sequence == 1


@pytest.mark.asyncio
async def test_pg_revoke_waits_for_current_grant_reader(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL row locks")
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    importer = GovernanceGrantImporter(session_factory, key_id="test-governance-key", public_key=public)
    reader = CurrentShowrunnerGrantReader(key_id="test-governance-key", public_key=public)
    issue = await importer.import_event(_signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private), scope=scope)
    locked = asyncio.Event()
    release_reader = asyncio.Event()
    reader_pids: list[int] = []

    async def held_read() -> None:
        async with session_factory() as session, session.begin():
            assert (await reader.require_current_locked(session, scope=scope)).event_digest == issue.event_digest
            pid = await session.scalar(select(func.pg_backend_pid()))
            assert pid is not None
            reader_pids.append(pid)
            locked.set()
            await release_reader.wait()

    read_task = asyncio.create_task(held_read())
    revoke_task: asyncio.Task | None = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=10)
        assert len(reader_pids) == 1
        revoke_raw = _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), private)
        revoke_task = asyncio.create_task(importer.import_event(revoke_raw, scope=scope))
        blocked: list[int] = []
        for _ in range(100):
            async with session_factory() as observer:
                blocked = list(
                    (
                        await observer.scalars(
                            text(
                                "SELECT pid FROM pg_stat_activity WHERE pid <> :reader_pid "
                                "AND :reader_pid = ANY(pg_blocking_pids(pid))"
                            ),
                            {"reader_pid": reader_pids[0]},
                        )
                    ).all()
                )
            if blocked:
                break
            await asyncio.sleep(0.05)
        assert len(blocked) == 1
        assert not revoke_task.done()
    finally:
        release_reader.set()
    await asyncio.wait_for(read_task, timeout=10)
    assert revoke_task is not None
    await asyncio.wait_for(revoke_task, timeout=10)
    async with session_factory() as session, session.begin():
        with pytest.raises(ShowrunnerGrantUnavailableError):
            await reader.require_current_locked(session, scope=scope)
