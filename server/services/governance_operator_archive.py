"""Offline reconciliation of a complete operator Governance archive."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from r2.contracts.governance_host_records import MAX_HOST_RECORD_BYTES
from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES
from r2.governance.archived_custody_chain import ArchivedCustodyInvalid, validate_retained_custody_chain
from r2.governance.operator_archive_file_ops import (
    publish_retained_file,
    remove_linked_staging_if_exact,
    remove_public_temp_if_exact,
    remove_staged_file_if_exact,
    replace_public_file,
)
from r2.governance.operator_archive_reader import (
    ArchiveReadLimits,
    OperatorArchiveInvalid,
    VerifiedOperatorArchiveV1,
    _locked_archive,
    _LockedArchive,
    _RetainedArchiveState,
    classify_public_copies,
)
from r2.governance.public_custody_snapshot import VerifiedPublicCustodySnapshotV1
from server.services.governance_grants import GovernanceGrantRecoveryScanner
from server.services.governance_schema_preflight import verify_governance_schema_ready


class OperatorArchiveReconcileUnavailable(RuntimeError):
    """The retained archive, database and public copies cannot be reconciled."""

    def __init__(self) -> None:
        super().__init__("operator Governance archive reconciliation is unavailable")


_CandidateLocation = Literal[
    "prior",
    "staged_checkpoint",
    "linked_checkpoint",
    "orphan_checkpoint",
    "staged_high_water",
    "linked_high_water",
    "complete",
]


def _classify_candidate_archive(
    archive: _LockedArchive, high_water_raw: bytes, checkpoint_raw: bytes
) -> tuple[_CandidateLocation, _RetainedArchiveState]:
    """Classify one exact signed successor against the locked filesystem state."""

    readers: tuple[tuple[_CandidateLocation, Callable[[], _RetainedArchiveState]], ...] = (
        ("prior", lambda: archive.read_retained(allow_public_temps=True)),
        ("staged_checkpoint", lambda: archive.read_staged_checkpoint(checkpoint_raw)),
        ("linked_checkpoint", lambda: archive.read_linked_checkpoint(checkpoint_raw)),
        ("orphan_checkpoint", lambda: archive.read_orphan_checkpoint(checkpoint_raw)),
        ("staged_high_water", lambda: archive.read_staged_high_water(high_water_raw, checkpoint_raw)),
        ("linked_high_water", lambda: archive.read_linked_high_water(high_water_raw, checkpoint_raw)),
    )
    for location, read in readers:
        try:
            state = read()
        except OperatorArchiveInvalid:
            continue
        if location == "prior" and state.history[-1] == (high_water_raw, checkpoint_raw):
            return "complete", state
        if state.public_temps:
            raise OperatorArchiveInvalid
        if location == "linked_high_water":
            if state.history[-1] != (high_water_raw, checkpoint_raw):
                raise OperatorArchiveInvalid
            return location, state
        if classify_public_copies(state) != "current":
            raise OperatorArchiveInvalid
        try:
            snapshot = validate_retained_custody_chain(
                state.approved_raw, state.registry_raw, (*state.history, (high_water_raw, checkpoint_raw))
            )
        except ArchivedCustodyInvalid:
            raise OperatorArchiveInvalid from None
        if snapshot.high_water.checkpoint_sequence != state.snapshot.high_water.checkpoint_sequence + 1:
            raise OperatorArchiveInvalid
        return location, state
    raise OperatorArchiveInvalid


async def verify_candidate_preflight(
    archive: _LockedArchive,
    state: _RetainedArchiveState,
    high_water_raw: bytes,
    checkpoint_raw: bytes,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    reread: Callable[[], _RetainedArchiveState],
) -> VerifiedPublicCustodySnapshotV1:
    """Verify a successor and committed ledger while the caller keeps the archive lock."""

    try:
        engine = session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine) or classify_public_copies(state) != "current":
            raise OperatorArchiveReconcileUnavailable
        snapshot = validate_retained_custody_chain(
            state.approved_raw, state.registry_raw, (*state.history, (high_water_raw, checkpoint_raw))
        )
        if snapshot.high_water.checkpoint_sequence != state.snapshot.high_water.checkpoint_sequence + 1:
            raise OperatorArchiveReconcileUnavailable
        await verify_governance_schema_ready(engine)
        registry = snapshot.registry
        scanner = GovernanceGrantRecoveryScanner(
            session_factory,
            grant_key_id=registry.grant_event.key_id,
            grant_public_key=registry.grant_event.public_key,
            deployment_id=registry.deployment_id,
            checkpoint_key_id=registry.grant_checkpoint.key_id,
            checkpoint_public_key=registry.grant_checkpoint.public_key,
        )

        async def load_candidate() -> bytes:
            return checkpoint_raw

        scanned = await scanner.verify(load_candidate)
        if scanned.checkpoint_digest != snapshot.checkpoint.checkpoint_digest or reread() != state:
            raise OperatorArchiveReconcileUnavailable
        archive._assert_stable()
        return snapshot
    except Exception:
        raise OperatorArchiveReconcileUnavailable from None


async def _verify_committed_state(
    archive: _LockedArchive,
    state: _RetainedArchiveState,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    reread: Callable[[], _RetainedArchiveState],
) -> GovernanceGrantRecoveryScanner:
    engine = session_factory.kw.get("bind")
    if not isinstance(engine, AsyncEngine):
        raise OperatorArchiveReconcileUnavailable
    await verify_governance_schema_ready(engine)
    registry = state.snapshot.registry
    scanner = GovernanceGrantRecoveryScanner(
        session_factory,
        grant_key_id=registry.grant_event.key_id,
        grant_public_key=registry.grant_event.public_key,
        deployment_id=registry.deployment_id,
        checkpoint_key_id=registry.grant_checkpoint.key_id,
        checkpoint_public_key=registry.grant_checkpoint.public_key,
    )

    async def load_latest() -> bytes:
        return state.history[-1][1]

    scanned = await scanner.verify(load_latest)
    if scanned.checkpoint_digest != state.snapshot.checkpoint.checkpoint_digest or reread() != state:
        raise OperatorArchiveReconcileUnavailable
    archive._assert_stable()
    return scanner


async def _reconcile_locked(
    archive: _LockedArchive,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int,
    after_phase: Callable[[str], None] | None = None,
) -> VerifiedOperatorArchiveV1:
    state = archive.read_retained(allow_public_temps=True)
    public_state = classify_public_copies(state)
    scanner = await _verify_committed_state(
        archive,
        state,
        session_factory=session_factory,
        reread=lambda: archive.read_retained(allow_public_temps=True),
    )

    async def load_latest() -> bytes:
        return state.history[-1][1]

    sequence = state.snapshot.high_water.checkpoint_sequence
    temp_expected = {
        f".high-water.{sequence:020d}.tmp": (state.history[-1][0], MAX_HOST_RECORD_BYTES),
        f".checkpoint.{sequence:020d}.tmp": (state.history[-1][1], MAX_GRANT_CHECKPOINT_BYTES),
    }
    for name in state.public_temps:
        expected, maximum = temp_expected[name]
        remove_public_temp_if_exact(
            read_fd=archive.read_fd,
            temp_name=name,
            expected=expected,
            maximum=maximum,
            expected_uid=expected_uid,
        )
        archive.note_public_write()
    if public_state == "previous":
        replace_public_file(
            read_fd=archive.read_fd,
            temp_name=f".high-water.{sequence:020d}.tmp",
            public_name="high-water.json",
            raw=state.history[-1][0],
            maximum=MAX_HOST_RECORD_BYTES,
            expected_uid=expected_uid,
            after_phase=(lambda phase: after_phase(f"public_high_water:{phase}")) if after_phase else None,
        )
        archive.note_public_write()
    if public_state != "current":
        replace_public_file(
            read_fd=archive.read_fd,
            temp_name=f".checkpoint.{sequence:020d}.tmp",
            public_name="grant-checkpoint.json",
            raw=state.history[-1][1],
            maximum=MAX_GRANT_CHECKPOINT_BYTES,
            expected_uid=expected_uid,
            after_phase=(lambda phase: after_phase(f"public_checkpoint:{phase}")) if after_phase else None,
        )
        archive.note_public_write()
    os.fsync(archive.read_fd)
    result = archive.read_complete()
    rescanned = await scanner.verify(load_latest)
    if rescanned.checkpoint_digest != result.snapshot.checkpoint.checkpoint_digest or archive.read_complete() != result:
        raise OperatorArchiveReconcileUnavailable
    return result


async def reconcile_complete_archive(
    root: Path,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
    limits: ArchiveReadLimits | None = None,
) -> VerifiedOperatorArchiveV1:
    """Repair an immediately previous public pair from a complete retained chain."""

    try:
        with _locked_archive(root, uid=expected_uid, limits=limits or ArchiveReadLimits()) as archive:
            return await _reconcile_locked(archive, session_factory=session_factory, expected_uid=expected_uid)
    except Exception:
        raise OperatorArchiveReconcileUnavailable from None


async def publish_candidate_archive(
    root: Path,
    high_water_raw: bytes,
    checkpoint_raw: bytes,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
    limits: ArchiveReadLimits | None = None,
    after_phase: Callable[[str], None] | None = None,
) -> VerifiedOperatorArchiveV1:
    """Publish one committed signed successor while holding the offline archive lock."""

    try:
        with _locked_archive(root, uid=expected_uid, limits=limits or ArchiveReadLimits()) as archive:
            for _ in range(8):
                location, state = _classify_candidate_archive(archive, high_water_raw, checkpoint_raw)
                if location == "complete":
                    result = await _reconcile_locked(
                        archive, session_factory=session_factory, expected_uid=expected_uid, after_phase=after_phase
                    )
                    if (result.high_water_raw, result.checkpoint_raw) != (high_water_raw, checkpoint_raw):
                        raise OperatorArchiveReconcileUnavailable
                    return result
                sequence = state.snapshot.high_water.checkpoint_sequence + (location != "linked_high_water")
                checkpoint_stage = f".checkpoint.{sequence:020d}.tmp"
                checkpoint_name = f"sha256-{hashlib.sha256(checkpoint_raw).hexdigest()}.json"
                high_water_stage = f".high-water.{sequence:020d}.tmp"
                high_water_name = f"{sequence:020d}.json"
                if location == "linked_high_water":
                    await _verify_committed_state(
                        archive,
                        state,
                        session_factory=session_factory,
                        reread=lambda: archive.read_linked_high_water(high_water_raw, checkpoint_raw),
                    )
                    remove_linked_staging_if_exact(
                        staging_fd=archive.staging_fd,
                        final_fd=archive.high_water_fd,
                        staging_name=high_water_stage,
                        final_name=high_water_name,
                        raw=high_water_raw,
                        maximum=MAX_HOST_RECORD_BYTES,
                        expected_uid=expected_uid,
                    )
                    archive.note_retained_write(archive.high_water_fd)
                    continue
                await verify_candidate_preflight(
                    archive,
                    state,
                    high_water_raw,
                    checkpoint_raw,
                    session_factory=session_factory,
                    reread=lambda: _classify_candidate_archive(archive, high_water_raw, checkpoint_raw)[1],
                )
                if location == "prior":
                    publish_retained_file(
                        staging_fd=archive.staging_fd,
                        final_fd=archive.checkpoint_fd,
                        staging_name=checkpoint_stage,
                        final_name=checkpoint_name,
                        raw=checkpoint_raw,
                        maximum=MAX_GRANT_CHECKPOINT_BYTES,
                        expected_uid=expected_uid,
                        after_phase=(lambda phase: after_phase(f"checkpoint:{phase}")) if after_phase else None,
                    )
                    archive.note_retained_write(archive.checkpoint_fd)
                elif location in {"staged_checkpoint", "linked_checkpoint"}:
                    cleanup = (
                        remove_staged_file_if_exact
                        if location == "staged_checkpoint"
                        else remove_linked_staging_if_exact
                    )
                    cleanup(
                        staging_fd=archive.staging_fd,
                        final_fd=archive.checkpoint_fd,
                        staging_name=checkpoint_stage,
                        final_name=checkpoint_name,
                        raw=checkpoint_raw,
                        maximum=MAX_GRANT_CHECKPOINT_BYTES,
                        expected_uid=expected_uid,
                    )
                    archive.note_retained_write(archive.checkpoint_fd)
                elif location == "orphan_checkpoint":
                    publish_retained_file(
                        staging_fd=archive.staging_fd,
                        final_fd=archive.high_water_fd,
                        staging_name=high_water_stage,
                        final_name=high_water_name,
                        raw=high_water_raw,
                        maximum=MAX_HOST_RECORD_BYTES,
                        expected_uid=expected_uid,
                        after_phase=(lambda phase: after_phase(f"high_water:{phase}")) if after_phase else None,
                    )
                    archive.note_retained_write(archive.high_water_fd)
                elif location == "staged_high_water":
                    remove_staged_file_if_exact(
                        staging_fd=archive.staging_fd,
                        final_fd=archive.high_water_fd,
                        staging_name=high_water_stage,
                        final_name=high_water_name,
                        raw=high_water_raw,
                        maximum=MAX_HOST_RECORD_BYTES,
                        expected_uid=expected_uid,
                    )
                    archive.note_retained_write(archive.high_water_fd)
                else:
                    raise OperatorArchiveReconcileUnavailable
            raise OperatorArchiveReconcileUnavailable
    except Exception:
        raise OperatorArchiveReconcileUnavailable from None


__all__ = [
    "OperatorArchiveReconcileUnavailable",
    "publish_candidate_archive",
    "reconcile_complete_archive",
    "verify_candidate_preflight",
]
