"""Host steps of the ADR-0103 activation ceremony: enroll, import a signed event, export and publish.

Every step runs offline: the application and its workers are stopped. None of them holds a signing key;
signed bytes arrive from the offline signer. Each step ends in the same verification the startup
attestor runs, so a step that leaves an archive the application would deny fails here first.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantHeadModel
from r2.contracts.governance_host_records import MAX_HOST_RECORD_BYTES, parse_checkpoint_high_water
from r2.contracts.governance_verifier_registry import ParsedVerifierRegistryV1, parse_verifier_registry
from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES, parse_grant_checkpoint
from r2.contracts.showrunner_grant import parse_grant_event
from r2.governance.ceremony import (
    CeremonyInvalid,
    checkpoint_body,
    digest_name,
    high_water_record,
    sequence_name,
)
from r2.governance.checkpoint_signature import verify_grant_checkpoint
from r2.governance.grant_signature import VerifiedGrantEventV1, verify_grant_event
from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_file_ops import publish_retained_file
from r2.governance.operator_archive_reader import (
    ArchiveReadLimits,
    OperatorArchiveReader,
    VerifiedOperatorArchiveV1,
    _locked_archive,
)
from server.services.governance_grants import GovernanceGrantHeadExporter, GovernanceGrantImporter
from server.services.governance_operator_archive import publish_candidate_archive, verify_operator_archive_preflight

_PUBLIC_REGISTRY = "governance-verifiers-v1.json"
_PUBLIC_APPROVED = "approved-deployment.json"
_RETAINED_DIRECTORIES = ("approved", "registries", "high-water", "checkpoints", ".staging")


def _registry_from_public(root: Path) -> ParsedVerifierRegistryV1:
    return parse_verifier_registry(_read_public(root / "read" / _PUBLIC_REGISTRY))


def _read_public(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise CeremonyInvalid("public record is not a regular file")
        raw = handle.read(MAX_GRANT_CHECKPOINT_BYTES + 1)
    if len(raw) > MAX_GRANT_CHECKPOINT_BYTES:
        raise CeremonyInvalid("public record is too large")
    return raw


def _create_public(read_fd: int, name: str, raw: bytes) -> None:
    """Create one public copy that only genesis writes; it is never replaced in place."""
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644, dir_fd=read_fd)
    try:
        os.fchmod(fd, 0o644)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _create_tree(root: Path) -> None:
    """The custody tree with the contract's modes; refuses one that already exists."""
    if not root.is_absolute() or root.exists():
        raise CeremonyInvalid("the custody root must be a new absolute path")
    root.mkdir(mode=0o700)
    os.chmod(root, 0o700)
    (root / "read").mkdir(mode=0o755)
    os.chmod(root / "read", 0o755)
    archive = root / "archive"
    archive.mkdir(mode=0o700)
    os.chmod(archive, 0o700)
    for name in _RETAINED_DIRECTORIES:
        (archive / name).mkdir(mode=0o700)
        os.chmod(archive / name, 0o700)
    lock = os.open(archive / ".publisher.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(lock, 0o600)
    os.close(lock)
    for directory in (archive, root / "read", root):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


async def _ledger_is_empty(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel))
    return not count


async def enroll_genesis(
    root: Path,
    *,
    registry_raw: bytes,
    approved_raw: bytes,
    checkpoint_raw: bytes,
    operator_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
) -> VerifiedOperatorArchiveV1:
    """Create the archive at sequence 1 over an empty grant ledger, then run the operator preflight."""
    registry = parse_verifier_registry(registry_raw)
    verify_grant_checkpoint(
        checkpoint_raw,
        deployment_id=registry.deployment_id,
        key_id=registry.grant_checkpoint.key_id,
        public_key=registry.grant_checkpoint.public_key,
    )
    checkpoint = parse_grant_checkpoint(checkpoint_raw)
    if checkpoint.body.checkpoint_sequence != 1 or checkpoint.body.heads:
        raise CeremonyInvalid("genesis needs the empty sequence-1 checkpoint")
    if not await _ledger_is_empty(session_factory):
        raise CeremonyInvalid("genesis needs an empty grant ledger")
    high_water_raw = high_water_record(
        approved_raw=approved_raw,
        checkpoint_raw=checkpoint_raw,
        previous=None,
        previous_raw=None,
        operator_id=operator_id,
    )
    _create_tree(root)
    with _locked_archive(root, uid=expected_uid, limits=ArchiveReadLimits()) as archive:
        for final_fd, name, raw, maximum in (
            (archive.registry_fd, digest_name(registry_raw), registry_raw, MAX_HOST_RECORD_BYTES),
            (archive.checkpoint_fd, digest_name(checkpoint_raw), checkpoint_raw, MAX_GRANT_CHECKPOINT_BYTES),
            (archive.approved_fd, sequence_name(1), approved_raw, MAX_HOST_RECORD_BYTES),
            (archive.high_water_fd, sequence_name(1), high_water_raw, MAX_HOST_RECORD_BYTES),
        ):
            publish_retained_file(
                staging_fd=archive.staging_fd,
                final_fd=final_fd,
                staging_name=f".genesis.{name}.tmp",
                final_name=name,
                raw=raw,
                maximum=maximum,
                expected_uid=expected_uid,
            )
        # Genesis has no earlier public copy to replace, so all four are created once.
        for name, raw in (
            (_PUBLIC_REGISTRY, registry_raw),
            (_PUBLIC_APPROVED, approved_raw),
            ("high-water.json", high_water_raw),
            ("grant-checkpoint.json", checkpoint_raw),
        ):
            _create_public(archive.read_fd, name, raw)
        os.fsync(archive.read_fd)
    return await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=expected_uid)


async def import_grant_event(
    root: Path, event_raw: bytes, *, session_factory: async_sessionmaker[AsyncSession]
) -> VerifiedGrantEventV1:
    """Import one signed ISSUE/REVOKE under the registry's grant key; the next checkpoint must follow."""
    registry = _registry_from_public(root)
    key = registry.grant_event
    event = verify_grant_event(event_raw, key_id=key.key_id, public_key=key.public_key)
    body = event.body
    return await GovernanceGrantImporter(session_factory, key_id=key.key_id, public_key=key.public_key).import_event(
        event_raw, scope=GrantScopeV1(body.user_id, body.project_name, body.principal)
    )


async def next_checkpoint_body(
    root: Path, *, session_factory: async_sessionmaker[AsyncSession], expected_uid: int = 0
) -> bytes:
    """The unsigned successor of the retained latest checkpoint, carrying every committed grant head."""
    archive = OperatorArchiveReader(root, expected_uid=expected_uid).read()
    registry = parse_verifier_registry(archive.registry_raw)
    latest = parse_grant_checkpoint(archive.checkpoint_raw)
    heads = await GovernanceGrantHeadExporter(
        session_factory, grant_key_id=registry.grant_event.key_id, grant_public_key=registry.grant_event.public_key
    ).heads()
    return checkpoint_body(
        deployment_id=registry.deployment_id,
        signer_key_id=registry.grant_checkpoint.key_id,
        sequence=latest.body.checkpoint_sequence + 1,
        previous=latest,
        heads=heads,
    )


async def publish_signed_checkpoint(
    root: Path,
    checkpoint_raw: bytes,
    *,
    operator_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
) -> VerifiedOperatorArchiveV1:
    """Retain and publish one signed successor through the locked candidate publisher."""
    archive = OperatorArchiveReader(root, expected_uid=expected_uid).read()
    high_water_raw = high_water_record(
        approved_raw=archive.approved_raw,
        checkpoint_raw=checkpoint_raw,
        previous=parse_checkpoint_high_water(archive.high_water_raw),
        previous_raw=archive.high_water_raw,
        operator_id=operator_id,
    )
    return await publish_candidate_archive(
        root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=expected_uid
    )


def parse_event_scope(event_raw: bytes) -> GrantScopeV1:
    body = parse_grant_event(event_raw).body
    return GrantScopeV1(body.user_id, body.project_name, body.principal)


__all__ = [
    "enroll_genesis",
    "import_grant_event",
    "next_checkpoint_body",
    "parse_event_scope",
    "publish_signed_checkpoint",
]
