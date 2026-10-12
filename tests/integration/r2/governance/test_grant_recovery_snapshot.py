"""A recovery snapshot matches every signed grant head under the global import fence."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from lib.db.models.governance_grant import ShowrunnerGrantEventModel, ShowrunnerGrantHeadModel
from r2.governance.grant_signature import verify_grant_event
from r2.governance.grant_transition import GrantScopeV1
from server.services.governance_grant_fence import GrantRecoveryFenceUnavailable
from server.services.governance_grants import (
    GovernanceGrantImporter,
    GovernanceGrantRecoveryScanner,
    GrantRecoveryUnavailable,
)
from tests.integration.r2.governance.test_grant_importer import _event, _signed


def _checkpoint(heads: list[dict[str, object]], *, signer: Ed25519PrivateKey | None = None) -> bytes:
    body = {
        "schema": "governance.grant_head_checkpoint.v1",
        "deployment_id": "deploy-a",
        "checkpoint_sequence": 1,
        "previous_checkpoint_digest": None,
        "issued_at": "2026-10-12T00:00:00Z",
        "signer_key_id": "checkpoint-test-key",
        "heads": heads,
    }
    private = signer or Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    signature = base64.urlsafe_b64encode(private.sign(canonical_json_bytes(body, allow_nan=False))).decode().rstrip("=")
    return canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)


def _head(project: str, sequence: int, digest: str) -> dict[str, object]:
    return {
        "user_id": "u1",
        "project_name": project,
        "principal": "reviewer-a",
        "head_sequence": sequence,
        "head_event_digest": digest,
    }


def _services(
    factory: async_sessionmaker[AsyncSession],
    *,
    on_head_locked: Callable[[AsyncSession], Awaitable[None]] | None = None,
) -> tuple[GovernanceGrantImporter, GovernanceGrantRecoveryScanner, Ed25519PrivateKey]:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(
        factory, key_id="test-governance-key", public_key=public, on_head_locked=on_head_locked
    )
    scanner = GovernanceGrantRecoveryScanner(
        factory,
        grant_key_id="test-governance-key",
        grant_public_key=public,
        deployment_id="deploy-a",
        checkpoint_key_id="checkpoint-test-key",
        checkpoint_public_key=public,
    )
    return importer, scanner, private


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        "empty",
        "issue_match",
        "two_scope_match",
        "revoke_match",
        "old_checkpoint",
        "restored_before_revoke",
        "missing_scope",
        "extra_scope",
        "empty_head",
        "corrupt_event",
        "corrupt_digest",
        "corrupt_second_scope",
        "wrong_signature",
        "malformed_checkpoint",
        "loader_failure",
    ],
)
async def test_pg_recovery_snapshot_compares_all_signed_heads(
    session_factory: async_sessionmaker[AsyncSession], state: str
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("full recovery scan requires PostgreSQL")
    importer, scanner, private = _services(session_factory)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    heads = []
    if state != "empty":
        issue = await importer.import_event(
            _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private), scope=scope
        )
        heads = [_head("show-a", 1, issue.event_digest)]
        if state in {"revoke_match", "old_checkpoint", "restored_before_revoke"}:
            revoke = await importer.import_event(
                _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), private), scope=scope
            )
            if state != "old_checkpoint":
                heads = [_head("show-a", 2, revoke.event_digest)]
            if state == "restored_before_revoke":
                async with session_factory() as session, session.begin():
                    await session.execute(
                        update(ShowrunnerGrantHeadModel)
                        .where(
                            ShowrunnerGrantHeadModel.user_id == "u1",
                            ShowrunnerGrantHeadModel.project_name == "show-a",
                            ShowrunnerGrantHeadModel.principal == "reviewer-a",
                        )
                        .values(current_sequence=1, current_event_digest=issue.event_digest)
                    )
                    await session.execute(
                        delete(ShowrunnerGrantEventModel).where(
                            ShowrunnerGrantEventModel.user_id == "u1",
                            ShowrunnerGrantEventModel.project_name == "show-a",
                            ShowrunnerGrantEventModel.principal == "reviewer-a",
                            ShowrunnerGrantEventModel.sequence == 2,
                        )
                    )
        if state == "missing_scope":
            heads = []
        if state in {"two_scope_match", "corrupt_second_scope"}:
            second_scope = GrantScopeV1("u1", "show-b", "reviewer-a")
            second = await importer.import_event(
                _signed(
                    _event("ISSUE", 1, None, "2026-01-01T00:00:00Z", project_name="show-b"),
                    private,
                ),
                scope=second_scope,
            )
            heads.append(_head("show-b", 1, second.event_digest))
            if state == "corrupt_second_scope":
                async with session_factory() as session, session.begin():
                    row = await session.get(ShowrunnerGrantEventModel, ("u1", "show-b", "reviewer-a", 1))
                    assert row is not None
                    row.raw_event += b"tampered"
        if state == "extra_scope":
            heads.append(_head("show-b", 1, "sha256:" + "b" * 64))
        if state == "empty_head":
            async with session_factory() as session, session.begin():
                await session.execute(
                    update(ShowrunnerGrantHeadModel).values(current_sequence=None, current_event_digest=None)
                )
        if state == "corrupt_event":
            async with session_factory() as session, session.begin():
                row = await session.get(ShowrunnerGrantEventModel, ("u1", "show-a", "reviewer-a", 1))
                assert row is not None
                row.raw_event += b"tampered"
        if state == "corrupt_digest":
            async with session_factory() as session, session.begin():
                row = await session.get(ShowrunnerGrantEventModel, ("u1", "show-a", "reviewer-a", 1))
                assert row is not None
                row.event_digest = "sha256:" + "0" * 64

    raw = _checkpoint(heads, signer=Ed25519PrivateKey.generate() if state == "wrong_signature" else None)
    called = 0

    async def load() -> bytes:
        nonlocal called
        called += 1
        if state == "loader_failure":
            raise OSError("synthetic checkpoint unavailable")
        if state == "malformed_checkpoint":
            return b"not a checkpoint"
        return raw

    if state in {"empty", "issue_match", "two_scope_match", "revoke_match"}:
        verified = await scanner.verify(load)
        assert [head.model_dump(mode="json") for head in verified.body.heads] == heads
        assert len(verified.body.heads) == len(heads)
    else:
        with pytest.raises(GrantRecoveryUnavailable) as exc:
            await scanner.verify(load)
        assert "synthetic" not in str(exc.value)
        assert "u1" not in str(exc.value)
    assert called == 1


@pytest.mark.asyncio
async def test_sqlite_recovery_scan_denies_before_loading(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name == "postgresql":
            pytest.skip("SQLite denial is tested on the SQLite fixture")
    _, scanner, _ = _services(session_factory)
    called = False

    async def load() -> bytes:
        nonlocal called
        called = True
        return _checkpoint([])

    with pytest.raises(GrantRecoveryFenceUnavailable):
        await scanner.verify(load)
    assert not called


@pytest.mark.asyncio
async def test_pg_recovery_loader_runs_after_waiting_import_commits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL transaction advisory locks")
    import_locked = asyncio.Event()
    release_import = asyncio.Event()
    import_pid: list[int] = []

    async def hold_import(session: AsyncSession) -> None:
        pid = await session.scalar(select(func.pg_backend_pid()))
        assert isinstance(pid, int)
        import_pid.append(pid)
        import_locked.set()
        await release_import.wait()

    importer, scanner, private = _services(session_factory, on_head_locked=hold_import)
    scope = GrantScopeV1("u1", "show-a", "reviewer-a")
    raw_event = _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), private)
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    expected_digest = verify_grant_event(raw_event, key_id="test-governance-key", public_key=public).event_digest
    import_task = asyncio.create_task(importer.import_event(raw_event, scope=scope))
    loader_called = asyncio.Event()
    scanner_task = None

    async def load() -> bytes:
        loader_called.set()
        return _checkpoint([_head("show-a", 1, expected_digest)])

    try:
        await asyncio.wait_for(import_locked.wait(), timeout=10)
        scanner_task = asyncio.create_task(scanner.verify(load))
        async with asyncio.timeout(10):
            while True:
                async with session_factory() as observer:
                    blocked = list(
                        (
                            await observer.scalars(
                                text("SELECT pid FROM pg_stat_activity WHERE :import_pid = ANY(pg_blocking_pids(pid))"),
                                {"import_pid": import_pid[0]},
                            )
                        ).all()
                    )
                    waiting = await observer.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel))
                if blocked:
                    break
                assert waiting == 0
                await asyncio.sleep(0.01)
        assert not loader_called.is_set()
    finally:
        release_import.set()
        if scanner_task is None:
            await asyncio.wait_for(asyncio.gather(import_task, return_exceptions=True), timeout=10)
        else:
            await asyncio.wait_for(asyncio.gather(import_task, scanner_task, return_exceptions=True), timeout=10)
    assert scanner_task is not None
    assert import_task.result().event_digest == expected_digest
    assert scanner_task.result().body.heads[0].head_event_digest == import_task.result().event_digest
    assert loader_called.is_set()
