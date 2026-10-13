"""Read-only public custody and committed-grant preflight for activated startup."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from r2.governance.public_custody_snapshot import validate_public_custody_snapshot
from server.services.governance_attestation import require_governance_archive_freshness
from server.services.governance_checkpoint_file import GovernanceCheckpointFile
from server.services.governance_grants import CheckpointedShowrunnerGrantReader, GovernanceGrantRecoveryScanner
from server.services.governance_schema_preflight import verify_governance_schema_ready


class GovernanceStartupUnavailable(RuntimeError):
    """Public custody and the committed grant ledger cannot be reconciled."""

    def __init__(self) -> None:
        super().__init__("Governance startup is unavailable")


async def verify_governance_public_startup(
    read_directory: Path,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> CheckpointedShowrunnerGrantReader:
    """Require stable public copies, exact schema, and a complete ledger scan."""

    return await _verify_startup(
        read_directory,
        session_factory=session_factory,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        socket_directory=None,
    )


async def verify_governance_activated_startup(
    read_directory: Path,
    socket_directory: Path | None,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> CheckpointedShowrunnerGrantReader:
    """Require a new independent host archive proof before returning runtime authority."""
    if socket_directory is None:
        raise GovernanceStartupUnavailable
    return await _verify_startup(
        read_directory,
        session_factory=session_factory,
        expected_uid=expected_uid,
        expected_gid=expected_gid,
        socket_directory=socket_directory,
    )


async def _verify_startup(
    read_directory: Path,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int,
    expected_gid: int,
    socket_directory: Path | None,
) -> CheckpointedShowrunnerGrantReader:

    try:
        engine = session_factory.kw.get("bind")
        if not isinstance(engine, AsyncEngine):
            raise GovernanceStartupUnavailable
        loader = GovernanceCheckpointFile(read_directory, expected_uid=expected_uid, expected_gid=expected_gid)
        copies = await loader.load_public_copies()
        snapshot = validate_public_custody_snapshot(*copies)
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
        scanned = await scanner.verify(loader.load)
        if scanned.checkpoint_digest != snapshot.checkpoint.checkpoint_digest:
            raise GovernanceStartupUnavailable
        if socket_directory is not None:
            await require_governance_archive_freshness(
                socket_directory, copies, expected_uid=expected_uid, expected_gid=expected_gid
            )
        if await loader.load_public_copies() != copies:
            raise GovernanceStartupUnavailable
        return CheckpointedShowrunnerGrantReader(
            grant_key_id=registry.grant_event.key_id,
            grant_public_key=registry.grant_event.public_key,
            deployment_id=registry.deployment_id,
            checkpoint_key_id=registry.grant_checkpoint.key_id,
            checkpoint_public_key=registry.grant_checkpoint.public_key,
            load_checkpoint=loader.load,
        )
    except Exception:
        raise GovernanceStartupUnavailable from None


__all__ = ["GovernanceStartupUnavailable", "verify_governance_activated_startup", "verify_governance_public_startup"]
