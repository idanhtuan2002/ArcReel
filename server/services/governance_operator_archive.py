"""Offline reconciliation of a complete operator Governance archive."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from r2.contracts.governance_host_records import MAX_HOST_RECORD_BYTES
from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES
from r2.governance.operator_archive_file_ops import remove_public_temp_if_exact, replace_public_file
from r2.governance.operator_archive_reader import (
    ArchiveReadLimits,
    VerifiedOperatorArchiveV1,
    _locked_archive,
    classify_public_copies,
)
from server.services.governance_grants import GovernanceGrantRecoveryScanner
from server.services.governance_schema_preflight import verify_governance_schema_ready


class OperatorArchiveReconcileUnavailable(RuntimeError):
    """The retained archive, database and public copies cannot be reconciled."""

    def __init__(self) -> None:
        super().__init__("operator Governance archive reconciliation is unavailable")


async def reconcile_complete_archive(
    root: Path,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
    limits: ArchiveReadLimits | None = None,
) -> VerifiedOperatorArchiveV1:
    """Repair an immediately previous public pair from a complete retained chain."""

    try:
        engine = session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise OperatorArchiveReconcileUnavailable
        with _locked_archive(root, uid=expected_uid, limits=limits or ArchiveReadLimits()) as archive:
            state = archive.read_retained(allow_public_temps=True)
            public_state = classify_public_copies(state)
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
            if scanned.checkpoint_digest != state.snapshot.checkpoint.checkpoint_digest:
                raise OperatorArchiveReconcileUnavailable
            if archive.read_retained(allow_public_temps=True) != state:
                raise OperatorArchiveReconcileUnavailable
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
                    temp_name=f".high-water.{state.snapshot.high_water.checkpoint_sequence:020d}.tmp",
                    public_name="high-water.json",
                    raw=state.history[-1][0],
                    maximum=MAX_HOST_RECORD_BYTES,
                    expected_uid=expected_uid,
                )
                archive.note_public_write()
            if public_state != "current":
                replace_public_file(
                    read_fd=archive.read_fd,
                    temp_name=f".checkpoint.{state.snapshot.high_water.checkpoint_sequence:020d}.tmp",
                    public_name="grant-checkpoint.json",
                    raw=state.history[-1][1],
                    maximum=MAX_GRANT_CHECKPOINT_BYTES,
                    expected_uid=expected_uid,
                )
                archive.note_public_write()
            os.fsync(archive.read_fd)
            result = archive.read_complete()
            rescanned = await scanner.verify(load_latest)
            if rescanned.checkpoint_digest != result.snapshot.checkpoint.checkpoint_digest:
                raise OperatorArchiveReconcileUnavailable
            return result
    except Exception:
        raise OperatorArchiveReconcileUnavailable from None


__all__ = ["OperatorArchiveReconcileUnavailable", "reconcile_complete_archive"]
