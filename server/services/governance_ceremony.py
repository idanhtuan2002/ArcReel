"""Host steps of the ADR-0103 activation ceremony: enroll, import a signed event, export and publish.

Every step runs offline: the application and its workers are stopped. None of them holds a signing key;
signed bytes arrive from the offline signer. Each step ends in the same verification the startup
attestor runs, so a step that leaves an archive the application would deny fails here first.
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantHeadModel
from r2.contracts.governance_host_records import (
    MAX_HOST_RECORD_BYTES,
    parse_approved_deployment,
    parse_checkpoint_high_water,
)
from r2.contracts.governance_verifier_registry import parse_verifier_registry
from r2.contracts.grant_checkpoint import MAX_GRANT_CHECKPOINT_BYTES, parse_grant_checkpoint
from r2.governance.ceremony import (
    CeremonyInvalid,
    checkpoint_body,
    digest,
    digest_name,
    high_water_record,
    sequence_name,
)
from r2.governance.checkpoint_signature import verify_grant_checkpoint
from r2.governance.grant_signature import VerifiedGrantEventV1, verify_grant_event
from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_file_ops import publish_retained_file
from r2.governance.operator_archive_reader import (
    _DIRECTORY_FLAGS,
    ArchiveReadLimits,
    OperatorArchiveInvalid,
    OperatorArchiveReader,
    VerifiedOperatorArchiveV1,
    _locked_archive,
    _open_regular,
)
from server.services.governance_grant_fence import acquire_grant_recovery_scan_fence
from server.services.governance_grants import GovernanceGrantHeadExporter, GovernanceGrantImporter
from server.services.governance_operator_archive import (
    publish_candidate_archive,
    reconcile_complete_archive,
    verify_operator_archive_preflight,
)
from server.services.governance_schema_preflight import verify_governance_schema_ready

_PUBLIC_REGISTRY = "governance-verifiers-v1.json"
_PUBLIC_APPROVED = "approved-deployment.json"
_RETAINED_DIRECTORIES = ("approved", "registries", "high-water", "checkpoints", ".staging")


def _fsync_directory(fd: int) -> None:
    os.fsync(fd)


def _write_new(parent_fd: int, name: str, raw: bytes, mode: int) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=parent_fd)
    try:
        os.fchmod(fd, mode)
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)


def _create_tree(root: Path, stack: ExitStack) -> None:
    """The custody tree with the contract's modes, created through no-follow directory descriptors.

    Refuses an existing root. A crash leaves a partial tree, which `enroll` refuses; the runbook moves it
    aside and enrolls again (the ledger is still empty, so nothing else depends on it).
    """
    if not root.is_absolute() or root == Path("/") or any(part in {".", ".."} for part in root.parts):
        raise CeremonyInvalid("the custody root must be an absolute path")
    parent = os.open("/", _DIRECTORY_FLAGS)
    stack.callback(os.close, parent)
    for part in root.parts[1:-1]:
        parent = os.open(part, _DIRECTORY_FLAGS, dir_fd=parent)
        stack.callback(os.close, parent)
    try:
        os.mkdir(root.name, 0o700, dir_fd=parent)
    except FileExistsError as exc:
        raise CeremonyInvalid("the custody root must be a new path") from exc
    root_fd = os.open(root.name, _DIRECTORY_FLAGS, dir_fd=parent)
    stack.callback(os.close, root_fd)
    os.fchmod(root_fd, 0o700)
    for name, mode in (("read", 0o755), ("archive", 0o700)):
        os.mkdir(name, mode, dir_fd=root_fd)
        child = os.open(name, _DIRECTORY_FLAGS, dir_fd=root_fd)
        stack.callback(os.close, child)
        os.fchmod(child, mode)
        if name == "archive":
            for retained in _RETAINED_DIRECTORIES:
                os.mkdir(retained, 0o700, dir_fd=child)
                retained_fd = os.open(retained, _DIRECTORY_FLAGS, dir_fd=child)
                os.fchmod(retained_fd, 0o700)
                os.close(retained_fd)
            lock = os.open(".publisher.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=child)
            os.fchmod(lock, 0o600)
            os.close(lock)
        _fsync_directory(child)
    _fsync_directory(root_fd)
    _fsync_directory(parent)


def _require_bound(registry_raw: bytes, approved_raw: bytes, checkpoint_raw: bytes) -> None:
    """The approval names these exact registry bytes and keys, and the checkpoint is its empty genesis."""
    registry = parse_verifier_registry(registry_raw)
    approved = parse_approved_deployment(approved_raw).body
    if (
        approved.deployment_id != registry.deployment_id
        or approved.approval_sequence != 1
        or approved.registry_file_digest != digest(registry_raw)
        or approved.registry_sequence != registry.registry_sequence
        or approved.grant_event_key_id != registry.grant_event.key_id
        or approved.checkpoint_key_id != registry.grant_checkpoint.key_id
    ):
        raise CeremonyInvalid("the approval does not bind this registry")
    verify_grant_checkpoint(
        checkpoint_raw,
        deployment_id=registry.deployment_id,
        key_id=registry.grant_checkpoint.key_id,
        public_key=registry.grant_checkpoint.public_key,
    )
    body = parse_grant_checkpoint(checkpoint_raw).body
    if body.checkpoint_sequence != 1 or body.heads:
        raise CeremonyInvalid("genesis needs the empty sequence-1 checkpoint")


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
    """Create the archive at sequence 1 over an empty grant ledger, then run the operator preflight.

    Every record binding and the database schema are verified before anything is written. The exclusive
    grant fence is held from the empty-ledger check until the genesis files are durable, so no import can
    commit in between.
    """
    _require_bound(registry_raw, approved_raw, checkpoint_raw)
    engine: AsyncEngine = session_factory.kw["bind"]
    await verify_governance_schema_ready(engine)
    high_water_raw = high_water_record(
        approved_raw=approved_raw,
        checkpoint_raw=checkpoint_raw,
        previous=None,
        previous_raw=None,
        operator_id=operator_id,
    )
    async with session_factory() as session, session.begin():
        await acquire_grant_recovery_scan_fence(session)
        if await session.scalar(select(func.count()).select_from(ShowrunnerGrantHeadModel)):
            raise CeremonyInvalid("genesis needs an empty grant ledger")
        with ExitStack() as stack:
            _create_tree(root, stack)
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
                _write_new(archive.read_fd, name, raw, 0o644)
            _fsync_directory(archive.read_fd)
    return await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=expected_uid)


async def import_grant_event(
    root: Path,
    event_raw: bytes,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
) -> VerifiedGrantEventV1:
    """Import one signed ISSUE/REVOKE under the grant key of the verified archive; a checkpoint must follow."""
    registry = parse_verifier_registry(OperatorArchiveReader(root, expected_uid=expected_uid).read().registry_raw)
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


def _retained_predecessors(root: Path, sequence: int, expected_uid: int) -> tuple[bytes, bytes]:
    """The approval and the high-water record ``sequence - 1``, read under the publisher lock.

    They exist in every state of an interrupted publication of ``sequence``. The publisher revalidates the
    whole chain with the successor, so a wrong read is refused rather than trusted.
    """
    with _locked_archive(root, uid=expected_uid, limits=ArchiveReadLimits()) as archive:
        found: list[bytes] = []
        for parent, name in (
            (archive.approved_fd, sequence_name(1)),
            (archive.high_water_fd, sequence_name(sequence - 1)),
        ):
            fd, info = _open_regular(
                parent, name, uid=expected_uid, mode=0o600, device=archive.device, maximum=MAX_HOST_RECORD_BYTES
            )
            try:
                raw = os.read(fd, MAX_HOST_RECORD_BYTES + 1)
            finally:
                os.close(fd)
            if len(raw) != info.st_size:
                raise OperatorArchiveInvalid
            found.append(raw)
        return found[0], found[1]


async def publish_signed_checkpoint(
    root: Path,
    checkpoint_raw: bytes,
    *,
    operator_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    expected_uid: int = 0,
) -> VerifiedOperatorArchiveV1:
    """Retain and publish one signed successor; a retry of the same file resumes or confirms it.

    The high-water record takes the checkpoint's issue time as ``recorded_at``, so every retry rebuilds
    identical bytes and the locked publisher can recognize a staged, linked or complete earlier attempt.
    """
    body = parse_grant_checkpoint(checkpoint_raw).body
    if body.checkpoint_sequence < 2:
        raise CeremonyInvalid("genesis is enrolled, not published")
    approved_raw, previous_raw = _retained_predecessors(root, body.checkpoint_sequence, expected_uid)
    high_water_raw = high_water_record(
        approved_raw=approved_raw,
        checkpoint_raw=checkpoint_raw,
        previous=parse_checkpoint_high_water(previous_raw),
        previous_raw=previous_raw,
        operator_id=operator_id,
        recorded_at=body.issued_at,
    )
    return await publish_candidate_archive(
        root, high_water_raw, checkpoint_raw, session_factory=session_factory, expected_uid=expected_uid
    )


async def reconcile(
    root: Path, *, session_factory: async_sessionmaker[AsyncSession], expected_uid: int = 0
) -> VerifiedOperatorArchiveV1:
    """Republish the public pair from the complete retained chain after an interrupted publication."""
    return await reconcile_complete_archive(root, session_factory=session_factory, expected_uid=expected_uid)


__all__ = [
    "enroll_genesis",
    "import_grant_event",
    "next_checkpoint_body",
    "publish_signed_checkpoint",
    "reconcile",
]
