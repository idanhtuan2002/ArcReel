"""Offline candidate publication checks exact retained bytes against committed PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.content_digest import canonical_json_bytes
from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_reader import OperatorArchiveReader
from server.services.governance_grants import GovernanceGrantImporter, GovernanceGrantRecoveryScanner
from server.services.governance_operator_archive import OperatorArchiveReconcileUnavailable, publish_candidate_archive
from tests.integration.r2.governance.test_grant_importer import _event, _signed
from tests.integration.r2.governance.test_operator_archive_reconcile import _ready_schema
from tests.unit.r2.governance.test_operator_archive_reader import _append_successor, _digest, _put, _tree


def _candidate_tree(tmp_path: Path) -> tuple[Path, bytes, bytes]:
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    high_water_raw = paths["public_high_water"].read_bytes()
    checkpoint_raw = paths["public_checkpoint"].read_bytes()
    (root / "archive" / "high-water" / "00000000000000000002.json").unlink()
    (root / "archive" / "checkpoints" / f"sha256-{_digest(checkpoint_raw)[7:]}.json").unlink()
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    return root, high_water_raw, checkpoint_raw


def _publish_in_other_process(
    root: str,
    high_water_raw: bytes,
    checkpoint_raw: bytes,
    database_url: str,
    schema: str,
    ready: multiprocessing.synchronize.Event,
    release: multiprocessing.synchronize.Event,
    outcomes: multiprocessing.queues.Queue,
) -> None:
    async def run() -> None:
        engine = create_async_engine(database_url, connect_args={"server_settings": {"search_path": schema}})
        factory = async_sessionmaker(engine, expire_on_commit=False)

        def pause(phase: str) -> None:
            if phase == "checkpoint:file_fsync":
                ready.set()
                if not release.wait(15):
                    raise RuntimeError("publisher process timed out")

        try:
            result = await publish_candidate_archive(
                Path(root),
                high_water_raw,
                checkpoint_raw,
                session_factory=factory,
                expected_uid=os.getuid(),
                after_phase=pause,
            )
            outcomes.put(("ok", result.checkpoint_raw == checkpoint_raw))
        except Exception as exc:
            outcomes.put(("error", type(exc).__name__))
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.asyncio
async def test_pg_publishes_exact_candidate_under_one_archive_lock(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)

    result = await publish_candidate_archive(
        root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
    )

    assert result.snapshot.high_water.checkpoint_sequence == 2
    assert result.high_water_raw == high_water_raw
    assert result.checkpoint_raw == checkpoint_raw
    assert OperatorArchiveReader(root, expected_uid=os.getuid()).read() == result
    assert not list((root / "archive" / ".staging").iterdir())
    again = await publish_candidate_archive(
        root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
    )
    assert again == result


@pytest.mark.asyncio
async def test_pg_candidate_publisher_denies_divergent_ledger_before_archive_mutation(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    importer = GovernanceGrantImporter(session_factory, key_id="grant-key-a", public_key=public)
    body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
    body["signer_key_id"] = "grant-key-a"
    await importer.import_event(_signed(body, private), scope=GrantScopeV1("u1", "show-a", "reviewer-a"))

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await publish_candidate_archive(
            root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
        )
    assert not (root / "archive" / "high-water" / "00000000000000000002.json").exists()
    assert not list((root / "archive" / ".staging").iterdir())


@pytest.mark.asyncio
async def test_pg_candidate_publisher_rereads_public_files_after_final_database_await(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)
    original = GovernanceGrantRecoveryScanner.verify
    scans = 0

    async def change_public_after_scan(
        self: GovernanceGrantRecoveryScanner, load_checkpoint: Callable[[], Awaitable[bytes]]
    ):
        nonlocal scans
        result = await original(self, load_checkpoint)
        scans += 1
        if scans == 4:
            _put(root / "read" / "grant-checkpoint.json", b"{}", 0o644)
        return result

    monkeypatch.setattr(GovernanceGrantRecoveryScanner, "verify", change_public_after_scan)
    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await publish_candidate_archive(
            root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
        )
    assert scans == 4


@pytest.mark.asyncio
async def test_pg_candidate_publisher_quarantines_different_complete_candidate(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)
    alternate = json.loads(high_water_raw)
    alternate["recorded_at"] = "2026-10-12T00:00:04Z"
    alternate_raw = canonical_json_bytes(alternate, allow_nan=False)
    _put(root / "archive" / "high-water" / "00000000000000000002.json", alternate_raw, 0o600)
    _put(root / "archive" / "checkpoints" / f"sha256-{_digest(checkpoint_raw)[7:]}.json", checkpoint_raw, 0o600)

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await publish_candidate_archive(
            root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
        )
    assert (root / "archive" / "high-water" / "00000000000000000002.json").read_bytes() == alternate_raw
    assert not list((root / "archive" / ".staging").iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["staging", "orphan"])
async def test_pg_candidate_publisher_quarantines_unknown_archive_entry(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, foreign: str
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)
    path = (
        root / "archive" / ".staging" / "unknown.tmp"
        if foreign == "staging"
        else root / "archive" / "checkpoints" / f"sha256-{_digest(b'foreign')[7:]}.json"
    )
    _put(path, b"foreign", 0o600)
    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await publish_candidate_archive(
            root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
        )
    assert path.read_bytes() == b"foreign"
    assert not (root / "archive" / "high-water" / "00000000000000000002.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["checkpoint", "high_water"])
@pytest.mark.parametrize(
    "phase",
    ["file_written", "file_fsync", "staging_fsync", "link_created", "link_fsync", "stage_unlinked", "unlink_fsync"],
)
async def test_pg_candidate_publisher_resumes_each_retained_write_interruption(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, kind: str, phase: str
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)

    def interrupt(current: str) -> None:
        if current == f"{kind}:{phase}":
            raise RuntimeError("simulated interruption")

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await publish_candidate_archive(
            root,
            high_water_raw,
            checkpoint_raw,
            session_factory=session_factory,
            expected_uid=os.getuid(),
            after_phase=interrupt,
        )
    result = await publish_candidate_archive(
        root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
    )
    assert result.high_water_raw == high_water_raw
    assert result.checkpoint_raw == checkpoint_raw
    assert OperatorArchiveReader(root, expected_uid=os.getuid()).read() == result


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["public_high_water", "public_checkpoint"])
@pytest.mark.parametrize("phase", ["file_written", "file_fsync", "renamed", "directory_fsync"])
async def test_pg_candidate_publisher_resumes_each_public_write_interruption(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, kind: str, phase: str
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)

    def interrupt(current: str) -> None:
        if current == f"{kind}:{phase}":
            raise RuntimeError("simulated interruption")

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await publish_candidate_archive(
            root,
            high_water_raw,
            checkpoint_raw,
            session_factory=session_factory,
            expected_uid=os.getuid(),
            after_phase=interrupt,
        )
    result = await publish_candidate_archive(
        root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
    )
    assert OperatorArchiveReader(root, expected_uid=os.getuid()).read() == result
    assert not list((root / "read").glob(".*.tmp"))


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["publication_unlinked", "linked_cleanup_unlinked"])
async def test_pg_complete_retry_fsyncs_staging_after_interrupted_unlink(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)
    staged = root / "archive" / ".staging" / ".high-water.00000000000000000002.tmp"

    def interrupt(phase: str) -> None:
        expected = "high_water:stage_unlinked" if interruption == "publication_unlinked" else "high_water:link_created"
        if phase == expected:
            raise RuntimeError("simulated interruption")

    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await publish_candidate_archive(
            root,
            high_water_raw,
            checkpoint_raw,
            session_factory=session_factory,
            expected_uid=os.getuid(),
            after_phase=interrupt,
        )
    staging_info = staged.parent.stat()
    original_fsync = os.fsync
    if interruption == "linked_cleanup_unlinked":

        def fail_after_unlink(fd: int) -> None:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == (staging_info.st_dev, staging_info.st_ino) and not staged.exists():
                raise OSError("simulated pre-fsync crash")
            original_fsync(fd)

        with monkeypatch.context() as patcher:
            patcher.setattr(os, "fsync", fail_after_unlink)
            with pytest.raises(OperatorArchiveReconcileUnavailable):
                await publish_candidate_archive(
                    root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
                )
    assert not staged.exists()
    observed_staging_fsync = False

    def observe_fsync(fd: int) -> None:
        nonlocal observed_staging_fsync
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) == (staging_info.st_dev, staging_info.st_ino):
            observed_staging_fsync = True
        original_fsync(fd)

    with monkeypatch.context() as patcher:
        patcher.setattr(os, "fsync", observe_fsync)
        result = await publish_candidate_archive(
            root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
        )
    assert result.checkpoint_raw == checkpoint_raw
    assert observed_staging_fsync


@pytest.mark.asyncio
async def test_pg_two_publisher_processes_serialize_on_archive_lock(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate publisher requires PostgreSQL")
    await _ready_schema(engine)
    async with engine.connect() as connection:
        schema = (await connection.execute(text("SHOW search_path"))).scalar_one()
    root, high_water_raw, checkpoint_raw = _candidate_tree(tmp_path)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    outcomes = context.Queue()
    process = context.Process(
        target=_publish_in_other_process,
        args=(
            str(root),
            high_water_raw,
            checkpoint_raw,
            engine.url.render_as_string(hide_password=False),
            schema,
            ready,
            release,
            outcomes,
        ),
    )
    process.start()
    try:
        if not ready.wait(15):
            pytest.fail(f"first publisher did not reach the held-lock phase: {outcomes.get(timeout=2)}")
        with pytest.raises(OperatorArchiveReconcileUnavailable):
            await publish_candidate_archive(
                root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
            )
    finally:
        release.set()
        process.join(timeout=20)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0
    assert outcomes.get(timeout=2) == ("ok", True)
    result = await publish_candidate_archive(
        root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=os.getuid()
    )
    assert OperatorArchiveReader(root, expected_uid=os.getuid()).read() == result
