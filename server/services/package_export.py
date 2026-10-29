"""M10-B deterministic package export through one M7 host-local attempt.

Resolve the selection and its evidence without locks, materialize verified private snapshots of every member
outside any transaction, then prepare under the design's global lock order (masters, profile head, run head,
disposition head, packaging head FOR SHARE, grant heads), staging the invocation inside M7's PLANNED commit.
The M7 submit callback builds the archive from the snapshots with no transaction open and publishes it
content-addressed; finalize re-verifies currentness and the published bytes, then commits SUCCEEDED with the
receipt. Export writes no upload, publish or visibility state and never touches Production Authority.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
import time
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.quality_dispositions import DispositionHeadModel
from lib.db.models.quality_runs import QualityRunHeadModel
from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from lib.db.repositories.quality_dispositions import disposition_digest
from lib.db.repositories.quality_packaging import (
    ExportRepository,
    PackageSelectionRepository,
    StoredExportInvocation,
    selection_digest,
)
from lib.db.repositories.quality_probes import attempt_request_digest
from lib.db.repositories.quality_runs import QualityRunRepository
from lib.video_backends.base import AmbiguousSubmitError
from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.advanced_creative.exploration import uuid7
from r2.contracts import packaging as p
from r2.contracts.advanced_creative import PackagingCandidate
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ExecutionAttemptState,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.host_submit import AttemptSubmitter, ProviderSubmitReceipt
from r2.host_hardening.paid_routes import current_release_mode
from r2.host_hardening.route_inventory import (
    HOST_EXPORT_ADAPTER_VERSION,
    PACKAGE_EXPORT_SUBMIT_FAMILIES,
    require_submit_route,
)
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    DispositionStaleError,
    ExportIntegrityFailedError,
    M10Error,
    OperationalEnvelopeExceededError,
    ProfileStaleError,
    RequiredEvidenceMissingError,
    StaleHeadError,
    SubjectStaleError,
    WaiverForbiddenError,
)
from r2.quality.runs import run_digest
from server.auth import get_current_interactive_user
from server.services import package_export_worker
from server.services.execution_attempts import build_execution_attempt_service, capability_resolver
from server.services.governance_grants import CheckpointedShowrunnerGrantReader
from server.services.package_export_worker import (
    MANIFEST_PATH,
    MEMBER_MODE,
    WORKER_CONFIG_SCHEMA,
    WORKER_OUTPUT_SCHEMA,
    ZIP_EPOCH,
    BundleMember,
    ExportEnvelopeError,
    archive_size,
)
from server.services.quality_dispositions import readiness_in
from server.services.quality_package_selection import PackageEvidence, resolve_package_evidence
from server.services.quality_packaging import open_beneath
from server.services.quality_probe_runtime import (
    MAX_RUNTIME_MS,
    READ_DIRS,
    READ_FILES,
    ProbeHost,
    QualityProbeRuntime,
    WorkerOutcome,
    worker_envelope,
)
from server.services.quality_runs import lock_profile_head, lock_subject_masters

_FAMILY = PACKAGE_EXPORT_SUBMIT_FAMILIES[0]
EXPORT_DIRECTORY = "exports"
_MEDIA_SUFFIX = {
    "video/mp4": "mp4",
    "image/png": "png",
    "image/jpeg": "jpg",
    "application/x-subrip": "srt",
    "text/plain": "txt",
    "application/json": "json",
}

CAPTIONS_ROLE_PREFIX = "captions-"
PRIMARY_METADATA = "metadata/metadata.json"
WORK_PREFIX = ".work-"
CREATING_PREFIX = ".creating-"
SNAPSHOT_DIRECTORY = "snapshots"
#: The most entries one export may carry: bounds the worker config well below its 1 MiB read.
MAX_EXPORT_MEMBERS = 1024
#: A kept work directory is swept only after any worker that could still use it has hit its runtime limit.
SWEEP_AFTER_SECONDS = 300
OWNER_LOCK = "owner.lock"
MANIFEST_FILE = "manifest.bytes"
PARTIAL_FILE = "archive.partial"
DOWNLOAD_FILE = "download.zip"
WORKER_BASE_MS = 30000
WORKER_BYTES_PER_SECOND = 50 << 20
WORKER_OUTPUT_CAP = 65536
WORKER_CONFIG_MAX_BYTES = 1 << 19
MIN_LANDLOCK_ABI = 6
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)

type Sessions = async_sessionmaker[AsyncSession]
type GrantReaderFactory = Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]
type SubmitterFactory = Callable[[AsyncSession, str, str, str], AttemptSubmitter]


def builder_identity_digest() -> str:
    """The archive builder is pinned by the exact bytes of its worker and confinement modules."""
    return digest_canonical({"domain": "m10.export-builder.v1", "files": worker_file_digests()})


def export_task_id(user_id: str, project_name: str, command_id: str) -> str:
    scope = digest_canonical({"user_id": user_id, "project_name": project_name, "command_id": command_id})
    return "m10b-export:" + scope.removeprefix("sha256:")


def export_route(builder_digest: str) -> ProviderRouteSnapshot:
    return ProviderRouteSnapshot(
        provider_id=_FAMILY.key.provider_id,
        provider_account_ref="local",
        provider_model_id="zip-stored",
        backend_model_id=builder_digest,
        endpoint_id=_FAMILY.key.endpoint_id,
        submitted_base_url="local://zip",
        adapter_version=HOST_EXPORT_ADAPTER_VERSION,
        capability_profile_ref=_FAMILY.capability_profile_ref,
    )


def execution_identity_digest(request: p.ExportRequest, manifest: p.ExportManifest) -> str:
    """The M7 request identity, recomputed from the stored request and manifest on every read."""
    subject = request.subject
    if (manifest.slot, manifest.selection_id, manifest.selection_digest) != (
        subject.slot,
        subject.selection_id,
        subject.selection_digest,
    ):
        raise RequiredEvidenceMissingError()
    identity = p.ExportExecutionIdentity(
        schema_id="m10.export-execution.v1",
        slot=request.subject.slot,
        selection_id=request.subject.selection_id,
        selection_digest=request.subject.selection_digest,
        manifest_digest=compute_digest("m10.export-manifest.v1", manifest),
        builder_identity_digest=manifest.builder_identity_digest,
        adapter_version=HOST_EXPORT_ADAPTER_VERSION,
    )
    return compute_digest("m10.export-execution.v1", identity)


def worker_file_digests() -> dict[str, str]:
    """The exact worker and confinement module bytes the host expects the worker to report."""
    folder = Path(package_export_worker.__file__).parent
    return {
        name: "sha256:" + hashlib.sha256((folder / name).read_bytes()).hexdigest()
        for name in ("package_export_worker.py", "quality_probe_worker.py")
    }


def _same_builder(reported: object, admitted: str) -> bool:
    """The worker that ran is exactly the builder admitted into the manifest and the M7 route."""
    if type(reported) is not dict:
        return False
    return digest_canonical({"domain": "m10.export-builder.v1", "files": reported}) == admitted


def _abi_at_least(value: object, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def _worker_report(stdout: bytes) -> dict[str, object] | None:
    """The worker's report when it has exactly the expected schema and keys; anything else is no report."""
    try:
        report = json.loads(stdout)
    except ValueError:
        return None
    if (
        type(report) is not dict
        or report.get("schema") != WORKER_OUTPUT_SCHEMA
        or report.get("status") not in {"OK", "INTEGRITY_FAILED", "ENVELOPE_EXCEEDED", "WORKER_FAILED"}
        or not set(report) <= {"schema", "status", "digest", "worker", "envelope", "landlock_abi"}
    ):
        return None
    return report


def provider_request(invocation: StoredExportInvocation) -> ProviderRequest:
    return ProviderRequest(
        id=f"{invocation.task_id}:export",
        host_task_ref=invocation.task_id,
        provider=_FAMILY.key.provider_id,
        model="zip-stored",
        endpoint=_FAMILY.key.endpoint_id,
        payload={"schema": "m10.export-execution.v1", "identity_digest": invocation.identity_digest},
        adapter_version=HOST_EXPORT_ADAPTER_VERSION,
    )


def _publish(store: int, work: WorkDirectory, name: str) -> None:
    """Rename the worker's output into the store by descriptor and make the rename durable."""
    try:
        os.replace(PARTIAL_FILE, name, src_dir_fd=work.descriptor, dst_dir_fd=store)
        os.fsync(store)
    except OSError:
        raise ExportIntegrityFailedError() from None


def attempt_submitter(session: AsyncSession, user_id: str, project_name: str, execution_id: str) -> AttemptSubmitter:
    """The M7 submitter whose single attempt uses the execution id reserved by the staged invocation."""
    resolver = capability_resolver()
    return AttemptSubmitter(
        repository=ExecutionAttemptRepository(session, capability_resolver=resolver),
        service=build_execution_attempt_service(session, adapter_registry={}),
        capability_resolver=resolver,
        user_id=user_id,
        project_name=project_name,
        usage_binder=None,
        execution_id_factory=lambda: execution_id,
    )


def _slug(value: str) -> str:
    text = "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "-" for c in value.lower()).strip("-.")
    if not text:
        raise ExportIntegrityFailedError()
    return text


def member_path(role: str, variant_id: str | None, media_type: str) -> str:
    """The fixed layout: video/output.mp4, thumbnails/<variant>.<ext>, captions/<locale>.<ext>, assets/…

    A caption asset declares its locale in its role (`captions-<locale>`), so the profile's asset roles name every
    caption locale it requires.
    """
    suffix = _MEDIA_SUFFIX.get(media_type)
    if suffix is None:
        raise ExportIntegrityFailedError()
    if role == "video" and variant_id is None:
        return "video/output.mp4"
    if role == "thumbnail":
        return f"thumbnails/{_slug(variant_id or 'thumbnail')}.{suffix}"
    if role.startswith(CAPTIONS_ROLE_PREFIX) and variant_id is None:
        return f"captions/{_slug(role.removeprefix(CAPTIONS_ROLE_PREFIX))}.{suffix}"
    return f"assets/{_slug(role)}{'-' + _slug(variant_id) if variant_id else ''}.{suffix}"


def _chosen(candidate: PackagingCandidate, selected: tuple[str, ...]) -> tuple[dict[str, str], dict[str, object]]:
    """Group → chosen variant id, and field → chosen inline value."""
    chosen: dict[str, str] = {}
    values: dict[str, object] = {}
    for group in candidate.variant_groups:
        for variant in group.variants:
            if variant.variant_id in selected:
                chosen[group.group_id] = variant.variant_id
                if variant.value is not None:
                    body = variant.value.model_dump(mode="json")
                    values[group.field] = next(iter(body.values()))
    return chosen, values


def metadata_document(candidate: PackagingCandidate, values: dict[str, object]) -> dict[str, object]:
    """The canonical published metadata: primary values with the chosen alternatives applied."""
    chapters = values.get("chapters", [c.model_dump(mode="json") for c in candidate.chapters])
    return {
        "title": values.get("title", candidate.title),
        "description": values.get("description", candidate.description),
        "tags": values.get("tags", list(candidate.tags)),
        "hashtags": list(candidate.hashtags),
        "chapters": chapters,
        "audience": candidate.audience_classification.model_dump(mode="json"),
        "disclosure": candidate.disclosure.model_dump(mode="json"),
    }


@dataclass(frozen=True)
class PlannedAsset:
    path: str
    source_ref: str
    content_digest: str
    byte_size: int


@dataclass(frozen=True)
class ExportPlan:
    """Everything an export materializes, computed from immutable evidence before any byte is copied."""

    assets: tuple[PlannedAsset, ...]
    documents: tuple[tuple[str, bytes], ...]
    manifest: p.ExportManifest
    manifest_bytes: bytes
    archive_bytes: int


def plan_export(selection: p.PackageSelection, evidence: PackageEvidence, builder_digest: str) -> ExportPlan:
    """Layout, documents, manifest and exact archive size; paths may never collide or overwrite each other."""
    preview = selection.preview
    candidate = evidence.candidate
    chosen, values = _chosen(candidate, preview.selected_variant_ids)
    chosen_ids = set(chosen.values())
    used: set[str] = set()

    def claim(path: str) -> str:
        if path.casefold() in used:
            raise ExportIntegrityFailedError()
        used.add(path.casefold())
        return path

    assets: list[PlannedAsset] = []
    raw: list[tuple[str, str, int, str]] = []
    for asset in candidate.assets:
        if asset.variant_id is not None and asset.variant_id not in chosen_ids:
            continue
        path = claim(member_path(asset.role, asset.variant_id, asset.media_type))
        assets.append(PlannedAsset(path, asset.source_ref, asset.content_digest, asset.byte_size))
        raw.append((path, asset.media_type, asset.byte_size, asset.content_digest))
    documents: list[tuple[str, bytes]] = [
        (claim(PRIMARY_METADATA), canonical_json_bytes(metadata_document(candidate, values)))
    ]
    documents.extend(
        (claim(f"metadata/{_slug(localized.locale)}.json"), canonical_json_bytes(localized.model_dump(mode="json")))
        for localized in candidate.localization_variants
    )
    raw.extend(
        (path, "application/json", len(data), "sha256:" + hashlib.sha256(data).hexdigest()) for path, data in documents
    )
    # The operational envelope is admitted before any contract model can refuse the same sizes as integrity.
    if len(raw) > MAX_EXPORT_MEMBERS:
        raise OperationalEnvelopeExceededError()
    try:
        archive_size([(path, size) for path, _, size, _ in raw], 0)
    except ExportEnvelopeError:
        raise OperationalEnvelopeExceededError() from None
    entries = [
        p.ExportManifestEntry(path=path, media_type=media, byte_size=size, content_digest=digest)
        for path, media, size, digest in raw
    ]
    try:
        manifest = p.ExportManifest(
            schema_id="m10.export-manifest.v1",
            slot=preview.slot,
            selection_id=selection.selection_id,
            selection_digest=selection_digest(selection),
            disposition_id=preview.disposition_id,
            disposition_digest=preview.disposition_digest,
            candidate_payload_digest=preview.candidate_payload_digest,
            builder_identity_digest=builder_digest,
            chosen_variants=tuple(
                p.VariantChoice(group_id=group, variant_id=variant) for group, variant in chosen.items()
            ),
            entries=tuple(entries),
        )
    except ValueError:
        raise ExportIntegrityFailedError() from None
    manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
    try:
        size = archive_size([(e.path, e.byte_size) for e in manifest.entries], len(manifest_bytes))
    except ExportEnvelopeError:
        raise OperationalEnvelopeExceededError() from None
    return ExportPlan(tuple(assets), tuple(documents), manifest, manifest_bytes, size)


def archive_ref(digest: str) -> str:
    return f"{EXPORT_DIRECTORY}/{digest.removeprefix('sha256:')}.zip"


def _open_directory(parent: int, name: str, *, create: bool) -> int:
    """A directory below ``parent`` opened without following links (created owner-only when asked)."""
    if create:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, 0o700, dir_fd=parent)
    descriptor = os.open(name, os.O_RDONLY | _DIRECTORY | _NOFOLLOW, dir_fd=parent)
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ExportIntegrityFailedError()
    return descriptor


def open_export_store(project_root: Path) -> int:
    """The project's export directory, pinned by descriptor; a link anywhere on the way is refused."""
    if os.name != "posix":
        raise ExportIntegrityFailedError()
    try:
        root = os.open(project_root, os.O_RDONLY | _DIRECTORY | _NOFOLLOW)
    except OSError:
        raise ExportIntegrityFailedError() from None
    try:
        return _open_directory(root, EXPORT_DIRECTORY, create=True)
    except OSError:
        raise ExportIntegrityFailedError() from None
    finally:
        os.close(root)


class WorkDirectory:
    """A private per-export scratch directory under the pinned store, published already owned.

    It is created under a `.creating-` name, its exclusive owner flock is taken, and only then is it renamed to
    `.work-<uuid>`, so a sweep can never see an unowned live directory. Snapshots live in `snapshots/`; the
    manifest bytes and the precreated output inode live beside it.
    """

    def __init__(self, store: int, project_root: Path) -> None:
        token = uuid.uuid4().hex
        self.name = f"{WORK_PREFIX}{token}"
        self._store = store
        self._removable = True
        creating = f"{CREATING_PREFIX}{token}"
        acquired: list[int] = []
        try:
            directory = _open_directory(store, creating, create=True)
            acquired.append(directory)
            lock = os.open(OWNER_LOCK, os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600, dir_fd=directory)
            acquired.append(lock)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            snapshots = _open_directory(directory, SNAPSHOT_DIRECTORY, create=True)
            acquired.append(snapshots)
            os.rename(creating, self.name, src_dir_fd=store, dst_dir_fd=store)
        except BaseException:
            for descriptor in reversed(acquired):
                with contextlib.suppress(OSError):
                    os.close(descriptor)
            with contextlib.suppress(OSError):
                shutil.rmtree(creating, dir_fd=store)
            raise
        self.descriptor, self._lock, self.snapshots = acquired
        self.path = project_root / EXPORT_DIRECTORY / self.name

    def create(self, name: str, *, in_snapshots: bool = False) -> int:
        parent = self.snapshots if in_snapshots else self.descriptor
        return os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600, dir_fd=parent)

    def mark_launch(self) -> None:
        """Restart the sweep grace at every launch and abandonment, while ownership is still held."""
        with contextlib.suppress(OSError):
            os.utime(self._lock)

    def keep(self) -> None:
        """A worker that may still run keeps its scratch; the sweep removes it after the maximum runtime."""
        self._removable = False

    def close(self) -> None:
        """Remove everything this export created (unless kept) and release ownership."""
        if self._removable:
            with contextlib.suppress(OSError):
                shutil.rmtree(self.name, dir_fd=self._store)
        for descriptor in (self.snapshots, self._lock, self.descriptor):
            with contextlib.suppress(OSError):
                os.close(descriptor)


@dataclass(frozen=True)
class PinnedMember:
    member: BundleMember
    identity: tuple[int, int]


def _write_pinned(work: WorkDirectory, name: str, data: bytes, *, in_snapshots: bool) -> tuple[int, int]:
    with os.fdopen(work.create(name, in_snapshots=in_snapshots), "wb") as sink:
        sink.write(data)
        sink.flush()
        os.fsync(sink.fileno())
        info = os.fstat(sink.fileno())
    return (info.st_dev, info.st_ino)


def snapshot_assets(root: Path, work: WorkDirectory, plan: ExportPlan) -> tuple[PinnedMember, ...]:
    """Private verified copies of every planned asset plus the documents, each with its inode identity."""
    members: list[PinnedMember] = []
    for index, asset in enumerate(plan.assets):
        relative = PurePosixPath(asset.source_ref)
        if str(relative) != asset.source_ref or relative.is_absolute() or ".." in relative.parts:
            raise ExportIntegrityFailedError()
        source = open_beneath(root, relative.parts)
        if source is None:
            raise ExportIntegrityFailedError()
        name = f"asset-{index}"
        hasher = hashlib.sha256()
        copied = 0
        with (
            os.fdopen(source, "rb", buffering=0) as reader,
            os.fdopen(work.create(name, in_snapshots=True), "wb") as sink,
        ):
            while chunk := reader.read(min(1 << 20, asset.byte_size + 1 - copied)):
                copied += len(chunk)
                if copied > asset.byte_size:
                    raise ExportIntegrityFailedError()
                hasher.update(chunk)
                sink.write(chunk)
            sink.flush()
            os.fsync(sink.fileno())
            info = os.fstat(sink.fileno())
        if (copied, "sha256:" + hasher.hexdigest()) != (asset.byte_size, asset.content_digest):
            raise ExportIntegrityFailedError()
        source_path = work.path / SNAPSHOT_DIRECTORY / name
        members.append(
            PinnedMember(
                BundleMember(asset.path, source_path, asset.content_digest, asset.byte_size),
                (info.st_dev, info.st_ino),
            )
        )
    for index, (path, data) in enumerate(plan.documents):
        name = f"document-{index}"
        identity = _write_pinned(work, name, data, in_snapshots=True)
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        members.append(
            PinnedMember(BundleMember(path, work.path / SNAPSHOT_DIRECTORY / name, digest, len(data)), identity)
        )
    return tuple(members)


@dataclass(frozen=True)
class VerifiedArchive:
    digest: str
    byte_size: int
    generation: tuple[int, int, int, int, int]


def _generation(info: os.stat_result) -> tuple[int, int, int, int, int]:
    """Identity plus size, mtime and ctime; any write to the inode moves ctime, which no caller can restore."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def verify_archive(store: int, name: str, manifest: p.ExportManifest, manifest_bytes: bytes) -> VerifiedArchive:
    """The published object is exactly this manifest's archive: names, fixed fields, manifest bytes and digests."""
    try:
        descriptor = os.open(name, os.O_RDONLY | _NOFOLLOW | _NONBLOCK, dir_fd=store)
    except OSError:
        raise ExportIntegrityFailedError() from None
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ExportIntegrityFailedError()
        hasher = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
        handle.seek(0)
        expected = sorted([*(e.path for e in manifest.entries), MANIFEST_PATH], key=str.encode)
        try:
            with zipfile.ZipFile(handle) as archive:
                infos = archive.infolist()
                if [i.filename for i in infos] != expected or archive.comment != b"":
                    raise ExportIntegrityFailedError()
                sizes = {e.path: e.byte_size for e in manifest.entries} | {MANIFEST_PATH: len(manifest_bytes)}
                digests = {e.path: e.content_digest for e in manifest.entries}
                for info in infos:
                    if (
                        info.compress_type != zipfile.ZIP_STORED
                        or info.date_time != ZIP_EPOCH
                        or (info.create_system, info.create_version, info.extract_version) != (3, 20, 20)
                        or info.flag_bits != 0
                        or info.external_attr >> 16 != MEMBER_MODE
                        or info.extra != b""
                        or info.comment != b""
                        or info.file_size != sizes[info.filename]
                    ):
                        raise ExportIntegrityFailedError()
                    member = hashlib.sha256()
                    with archive.open(info) as stream:
                        for chunk in iter(lambda: stream.read(1 << 20), b""):
                            member.update(chunk)
                    expected_digest = digests.get(info.filename, "sha256:" + hashlib.sha256(manifest_bytes).hexdigest())
                    if "sha256:" + member.hexdigest() != expected_digest:
                        raise ExportIntegrityFailedError()
                if archive.read(MANIFEST_PATH) != manifest_bytes:
                    raise ExportIntegrityFailedError()
        except (zipfile.BadZipFile, KeyError, OSError):
            raise ExportIntegrityFailedError() from None
        after = os.fstat(handle.fileno())
    if _generation(before) != _generation(after):
        raise ExportIntegrityFailedError()
    return VerifiedArchive("sha256:" + hasher.hexdigest(), before.st_size, _generation(before))


def published_generation(store: int, name: str) -> tuple[int, int, int, int, int] | None:
    try:
        return _generation(os.stat(name, dir_fd=store, follow_symlinks=False))
    except OSError:
        return None


_WIDEST_IDENTITY: tuple[int, int] = (2**64 - 1, 2**64 - 1)


def worker_config(
    work: WorkDirectory,
    members: list[tuple[BundleMember, tuple[int, int]]],
    manifest_identity: tuple[int, int],
    output_identity: tuple[int, int],
) -> dict[str, object]:
    """The exact worker configuration: snapshot directory grant, pinned member/manifest/output inodes."""
    snapshot_dir = work.path / SNAPSHOT_DIRECTORY
    return {
        "schema": WORKER_CONFIG_SCHEMA,
        "envelope": worker_envelope(),
        "read_files": list(READ_FILES),
        "exec_files": [],
        "read_dirs": [*READ_DIRS, str(snapshot_dir)],
        "scratch": [str(work.path / PARTIAL_FILE)],
        "members": [
            {
                "path": member.path,
                "source": str(member.source),
                "digest": member.content_digest,
                "size": member.byte_size,
                "identity": list(identity),
            }
            for member, identity in members
        ],
        "manifest": str(snapshot_dir / MANIFEST_FILE),
        "manifest_identity": list(manifest_identity),
        "output": str(work.path / PARTIAL_FILE),
        "output_identity": list(output_identity),
    }


def admit_worker_config(work: WorkDirectory, plan: ExportPlan) -> None:
    """Refuse before copying or PLANNED when the largest possible worker config would exceed its bound."""
    snapshot_dir = work.path / SNAPSHOT_DIRECTORY
    planned: list[tuple[BundleMember, tuple[int, int]]] = [
        (BundleMember(a.path, snapshot_dir / f"asset-{i}", a.content_digest, a.byte_size), _WIDEST_IDENTITY)
        for i, a in enumerate(plan.assets)
    ]
    planned += [
        (BundleMember(path, snapshot_dir / f"document-{i}", "sha256:" + "0" * 64, len(data)), _WIDEST_IDENTITY)
        for i, (path, data) in enumerate(plan.documents)
    ]
    config = worker_config(work, planned, _WIDEST_IDENTITY, _WIDEST_IDENTITY)
    if len(json.dumps(config, sort_keys=True).encode("utf-8")) > WORKER_CONFIG_MAX_BYTES:
        raise OperationalEnvelopeExceededError()


@dataclass
class Download:
    """An open, verified private archive snapshot; ``close`` removes it and releases its scratch."""

    descriptor: int
    work: WorkDirectory
    store: int

    closed: bool = False

    def close(self) -> None:
        """Idempotent: the first call releases everything, later calls do nothing."""
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(OSError):
            os.close(self.descriptor)
        self.work.close()
        with contextlib.suppress(OSError):
            os.close(self.store)


def _snapshot_archive(
    store: int, work: WorkDirectory, name: str, digest: str, size: int
) -> tuple[int, tuple[int, int, int, int, int]]:
    """Copy the published archive into private scratch while hashing; return the copy's descriptor and source generation."""
    try:
        source = os.open(name, os.O_RDONLY | _NOFOLLOW | _NONBLOCK, dir_fd=store)
    except OSError:
        raise ExportIntegrityFailedError() from None
    with os.fdopen(source, "rb", buffering=0) as reader:
        target = work.create(DOWNLOAD_FILE)
        try:
            before = os.fstat(reader.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != size:
                raise ExportIntegrityFailedError()
            hasher = hashlib.sha256()
            copied = 0
            while chunk := reader.read(min(1 << 20, size + 1 - copied)):
                copied += len(chunk)
                if copied > size:
                    raise ExportIntegrityFailedError()
                hasher.update(chunk)
                view = memoryview(chunk)
                while view:
                    view = view[os.write(target, view) :]
            if _generation(os.fstat(reader.fileno())) != _generation(before):
                raise ExportIntegrityFailedError()
            if (copied, "sha256:" + hasher.hexdigest()) != (size, digest):
                raise ExportIntegrityFailedError()
            os.lseek(target, 0, os.SEEK_SET)
        except BaseException:
            os.close(target)
            raise
    return target, _generation(before)


@dataclass(frozen=True)
class SlotStatus:
    """What a PACKAGING_SLOT holds now and has held.

    `exportable` and `refusal_code` describe the current selection only; `readiness_*` and `disposition_decision`
    are the quality readiness of that selection's subject. `receipts` is the slot's whole export history as
    (selection_id, receipt) pairs, oldest first; only receipts of the current selection can be downloaded.
    """

    head_version: int
    selection: p.PackageSelection | None
    exportable: bool
    refusal_code: str | None
    readiness_state: str | None
    readiness_reasons: tuple[str, ...]
    disposition_decision: str | None
    receipts: tuple[tuple[str, p.ExportBundleReceipt], ...]


SLOT_READ_ATTEMPTS = 3


class PackageExportService:
    """Export the current selection of one PACKAGING_SLOT as a deterministic local archive."""

    def __init__(
        self,
        *,
        sessions: Sessions,
        grant_reader: GrantReaderFactory,
        project_root: Path,
        interactive_token: str | None,
        submitter_for: SubmitterFactory = attempt_submitter,
        clock: Callable[[], datetime] | None = None,
        runtime: QualityProbeRuntime | None = None,
    ) -> None:
        self._sessions = sessions
        self._grant_reader = grant_reader
        self._project_root = project_root
        self._token = interactive_token
        self._submitter_for = submitter_for
        self._clock = clock or (lambda: datetime.now(UTC))
        self._runtime = runtime or QualityProbeRuntime(ProbeHost(tools={}, worker=Path(package_export_worker.__file__)))

    async def _require_actor(self, request: p.ExportRequest) -> None:
        try:
            user = await get_current_interactive_user(self._token)
        except HTTPException:
            raise RequiredEvidenceMissingError() from None
        if (user.id, user.sub) != (request.command.user_id, request.command.actor_id):
            raise RequiredEvidenceMissingError()

    async def export(self, request: p.ExportRequest) -> p.ExportBundleReceipt:
        if request.command.request_digest != compute_digest("m10.export-request.v1", request):
            raise RequiredEvidenceMissingError()
        await self._require_actor(request)
        subject = request.subject
        async with self._sessions() as session, session.begin():
            await PackageSelectionRepository(session).lock_command(request.command)
            existing = await ExportRepository(session).invocation(request)
            receipt = (
                None
                if existing is None
                else await ExportRepository(session).receipt(
                    user_id=subject.user_id, project_name=subject.project_name, execution_id=existing.execution_id
                )
            )
        if receipt is not None:
            return receipt
        if existing is not None:
            return await self._resume(existing)
        require_submit_route(
            _FAMILY.key.provider_id,
            _FAMILY.key.endpoint_id,
            HOST_EXPORT_ADAPTER_VERSION,
            release_mode=current_release_mode(),
            now=self._clock(),
        )
        reader = await self._grant_reader()
        async with self._sessions() as session:
            selection, evidence = await self._resolve(session, request.subject)
        builder_digest = builder_identity_digest()
        plan = plan_export(selection, evidence, builder_digest)
        store = await asyncio.to_thread(open_export_store, self._project_root)
        try:
            work = await asyncio.to_thread(WorkDirectory, store, self._project_root)
            try:
                admit_worker_config(work, plan)
                members = await asyncio.to_thread(snapshot_assets, self._project_root, work, plan)
                return await self._submit(request, reader, selection, plan, members, builder_digest, store, work)
            finally:
                await asyncio.to_thread(work.close)
        finally:
            os.close(store)

    async def slot_status(self, slot: p.PackagingSlotKey, actor_id: str) -> SlotStatus:
        """The slot's current selection checked by the same currentness and readiness rules export applies.

        A selection replaced between the unlocked head read and the locked check is projected again from the
        replacement, in a new transaction, up to `SLOT_READ_ATTEMPTS` times.
        """
        reader = await self._grant_reader()
        for _ in range(SLOT_READ_ATTEMPTS):
            async with self._sessions() as session, session.begin():
                status = await self._project_slot(session, reader, slot, actor_id)
            if status is not None:
                return status
        raise StaleHeadError()

    async def _project_slot(
        self, session: AsyncSession, reader: CheckpointedShowrunnerGrantReader, slot: p.PackagingSlotKey, actor_id: str
    ) -> SlotStatus | None:
        """One consistent projection, or None when the head moved after it was read and the check refused."""
        selections = PackageSelectionRepository(session)
        exports = ExportRepository(session)
        selection_id, version = await selections.current_head(slot)
        history: list[tuple[str, p.ExportBundleReceipt]] = []
        for held in await selections.slot_selection_ids(slot):
            found = await exports.selection_receipts(
                user_id=slot.user_id, project_name=slot.project_name, selection_id=held
            )
            history.extend((held, receipt) for receipt in found)
        receipts = tuple(history)
        if selection_id is None:
            return SlotStatus(version, None, False, StaleHeadError().code, None, (), None, receipts)
        selection = await selections.selection(
            user_id=slot.user_id, project_name=slot.project_name, selection_id=selection_id
        )
        if selection is None:
            raise RequiredEvidenceMissingError()
        subject = p.ExportSubject(
            user_id=slot.user_id,
            project_name=slot.project_name,
            actor_id=actor_id,
            slot=slot,
            selection_id=selection_id,
            selection_digest=selection_digest(selection),
        )
        refusal: M10Error | None = None
        try:
            await self._require_current(session, reader, subject, selection)
        except (
            DispositionStaleError,
            ProfileStaleError,
            StaleHeadError,
            SubjectStaleError,
            WaiverForbiddenError,
        ) as error:
            refusal = error
        if refusal is not None and await selections.current_head(slot) != (selection_id, version):
            # An earlier refusal can mask a replacement of the selection itself; project the replacement instead.
            return None
        run = await QualityRunRepository(session).run(
            user_id=slot.user_id, project_name=slot.project_name, run_id=selection.preview.quality_run_id
        )
        readiness, disposition = None, None
        if run is not None:
            readiness, disposition, _ = await readiness_in(
                session,
                reader,
                project_root=self._project_root,
                user_id=slot.user_id,
                project_name=slot.project_name,
                subject_digest=run.subject_digest,
                profile_id=run.profile_id,
            )
        return SlotStatus(
            version,
            selection,
            refusal is None,
            None if refusal is None else refusal.code,
            None if readiness is None else readiness.state,
            () if readiness is None else readiness.reasons,
            None if disposition is None else disposition.decision,
            receipts,
        )

    async def open_download(self, user_id: str, project_name: str, archive_digest: str) -> Download:
        """A verified private snapshot of a receipted archive whose selection is still current and READY.

        The bytes are copied (no-follow, by descriptor) and checked against the receipt's digest and size first;
        then currentness is revalidated under the global lock order and the published file's generation must be
        unchanged. The caller streams the returned descriptor and closes the download when done.
        """
        async with self._sessions() as session:
            receipted = await ExportRepository(session).receipted_invocations(
                project_name=project_name, archive_digest=archive_digest
            )
        receipted = [(i, r) for i, r in receipted if i.request.command.user_id == user_id]
        if not receipted:
            raise RequiredEvidenceMissingError()
        reader = await self._grant_reader()
        store = await asyncio.to_thread(open_export_store, self._project_root)
        try:
            work = await asyncio.to_thread(WorkDirectory, store, self._project_root)
        except BaseException:
            os.close(store)
            raise
        try:
            name = PurePosixPath(archive_ref(archive_digest)).name
            descriptor, generation = await asyncio.to_thread(
                _snapshot_archive, store, work, name, archive_digest, receipted[0][1].archive_byte_size
            )
            try:
                last: Exception | None = None
                for invocation, _receipt in receipted:
                    try:
                        async with self._sessions() as session, session.begin():
                            selection = await PackageSelectionRepository(session).selection(
                                user_id=user_id,
                                project_name=project_name,
                                selection_id=invocation.request.subject.selection_id,
                            )
                            if selection is None:
                                raise RequiredEvidenceMissingError()
                            await self._require_current(session, reader, invocation.request.subject, selection)
                            if published_generation(store, name) != generation:
                                raise ExportIntegrityFailedError()
                        return Download(descriptor, work, store)
                    except M10Error as error:
                        last = error
                raise last if last is not None else RequiredEvidenceMissingError()
            except BaseException:
                os.close(descriptor)
                raise
        except BaseException:
            work.close()
            os.close(store)
            raise

    async def _resolve(
        self, session: AsyncSession, subject: p.ExportSubject
    ) -> tuple[p.PackageSelection, PackageEvidence]:
        selection = await PackageSelectionRepository(session).selection(
            user_id=subject.user_id, project_name=subject.project_name, selection_id=subject.selection_id
        )
        if (
            selection is None
            or selection_digest(selection) != subject.selection_digest
            or selection.preview.slot != subject.slot
        ):
            raise StaleHeadError()
        preview = selection.preview
        evidence = await resolve_package_evidence(
            session,
            user_id=subject.user_id,
            project_name=subject.project_name,
            slot=preview.slot,
            candidate_id=preview.candidate_id,
            candidate_revision=preview.candidate_revision,
            candidate_payload_digest=preview.candidate_payload_digest,
            observation_id=preview.packaging_observation_id,
            selected_variant_ids=preview.selected_variant_ids,
            waivers=preview.waivers,
        )
        return selection, evidence

    async def _require_current(
        self,
        session: AsyncSession,
        reader: CheckpointedShowrunnerGrantReader,
        subject: p.ExportSubject,
        selection: p.PackageSelection,
    ) -> None:
        """Global order with FOR SHARE heads; the selection must still fill the slot and be READY."""
        user_id, project_name = subject.user_id, subject.project_name
        preview = selection.preview
        run = await QualityRunRepository(session).run(
            user_id=user_id, project_name=project_name, run_id=preview.quality_run_id
        )
        if run is None or run_digest(run) != preview.quality_run_digest:
            raise DispositionStaleError()
        await lock_subject_masters(session, run.subject)
        await lock_profile_head(session, user_id=user_id, project_name=project_name, profile_id=run.profile_id)
        keys = {
            "user_id": user_id,
            "project_name": project_name,
            "subject_digest": run.subject_digest,
            "profile_id": run.profile_id,
        }
        head_run = (
            await session.execute(
                select(QualityRunHeadModel.current_run_id).filter_by(**keys).with_for_update(read=True)
            )
        ).scalar_one_or_none()
        head_disposition = (
            await session.execute(
                select(DispositionHeadModel.current_disposition_id).filter_by(**keys).with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if head_run != preview.quality_run_id or head_disposition != preview.disposition_id:
            raise DispositionStaleError()
        current, _ = await PackageSelectionRepository(session).lock_head(preview.slot, for_update=False)
        if current != selection.selection_id:
            raise StaleHeadError()
        await self._resolve(session, subject)
        readiness, disposition, ready_run = await readiness_in(
            session,
            reader,
            project_root=self._project_root,
            user_id=user_id,
            project_name=project_name,
            subject_digest=run.subject_digest,
            profile_id=run.profile_id,
        )
        if (
            readiness.state != "READY"
            or disposition is None
            or ready_run is None
            or (disposition.disposition_id, disposition_digest(disposition), ready_run.run_id)
            != (preview.disposition_id, preview.disposition_digest, preview.quality_run_id)
        ):
            raise DispositionStaleError()

    async def _submit(
        self,
        request: p.ExportRequest,
        reader: CheckpointedShowrunnerGrantReader,
        selection: p.PackageSelection,
        plan: ExportPlan,
        members: tuple[PinnedMember, ...],
        builder_digest: str,
        store: int,
        work: WorkDirectory,
    ) -> p.ExportBundleReceipt:
        command = request.command
        manifest_digest = compute_digest("m10.export-manifest.v1", plan.manifest)
        invocation = StoredExportInvocation(
            request=request,
            execution_id=uuid7(),
            task_id=export_task_id(command.user_id, command.project_name, command.command_id),
            manifest=plan.manifest,
            manifest_digest=manifest_digest,
            identity_digest=execution_identity_digest(request, plan.manifest),
        )
        known: list[M10Error] = []
        async with self._sessions() as session:
            try:
                await session.begin()
                await PackageSelectionRepository(session).lock_command(command)
                if await ExportRepository(session).invocation(request) is not None:
                    raise RequiredEvidenceMissingError()
                await self._require_current(session, reader, request.subject, selection)
                await ExportRepository(session).stage_invocation(invocation, self._clock())
            except BaseException:
                await session.rollback()
                raise
            submitter = self._submitter_for(session, command.user_id, command.project_name, invocation.execution_id)

            async def submit(attempt: AttemptSnapshot) -> ProviderSubmitReceipt[str]:
                try:
                    digest = await self._build_and_publish(attempt.execution_id, plan, members, store, work)
                except (ExportIntegrityFailedError, OperationalEnvelopeExceededError) as error:
                    known.append(error)
                    raise
                return ProviderSubmitReceipt(
                    observation=ProviderObservation(
                        observation_id=f"{attempt.execution_id}:accepted",
                        kind=ProviderObservationKind.ACCEPTED,
                        observed_at=self._clock(),
                        provider_job_id=f"{attempt.execution_id}:{digest}",
                        evidence_digest=digest,
                    ),
                    value=digest,
                )

            outcome = await submitter.submit(
                task_id=invocation.task_id,
                api_call_id=None,
                route=export_route(builder_digest),
                request=provider_request(invocation),
                submit=submit,
            )
        if outcome.execution_id != invocation.execution_id:
            raise RequiredEvidenceMissingError()
        if outcome.snapshot.state is ExecutionAttemptState.ACCEPTED:
            return await self._finalize(invocation, reader)
        if outcome.snapshot.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE:
            # In-process the typed refusal is kept; a later replay of the failed command reports integrity.
            raise known[-1] if known else ExportIntegrityFailedError()
        raise RequiredEvidenceMissingError()

    async def _build_and_publish(
        self, execution_id: str, plan: ExportPlan, members: tuple[PinnedMember, ...], store: int, work: WorkDirectory
    ) -> str:
        """Build in the confined worker into one precreated output inode, then publish it content-addressed.

        A refusal is known only when the worker reported it, exited 1 and its unit is verified gone; every other
        result after a possible start is ambiguous, keeps its scratch for the sweep and is never rebuilt.
        """
        ambiguous = AmbiguousSubmitError(
            provider=_FAMILY.key.provider_id, message="[create_ambiguous] export outcome unknown"
        )
        budget_ms = WORKER_BASE_MS + plan.archive_bytes * 1000 // WORKER_BYTES_PER_SECOND
        if budget_ms > MAX_RUNTIME_MS:
            raise OperationalEnvelopeExceededError()
        manifest_identity = _write_pinned(work, MANIFEST_FILE, plan.manifest_bytes, in_snapshots=True)
        output = work.create(PARTIAL_FILE)
        info = os.fstat(output)
        os.close(output)
        config = worker_config(
            work,
            [(m.member, m.identity) for m in members],
            manifest_identity,
            (info.st_dev, info.st_ino),
        )
        payload = json.dumps(config, sort_keys=True).encode("utf-8")
        if len(payload) > WORKER_CONFIG_MAX_BYTES:
            raise OperationalEnvelopeExceededError()
        work.mark_launch()
        try:
            outcome = await self._runtime.launch(
                payload,
                budget_ms=budget_ms,
                output_cap=WORKER_OUTPUT_CAP,
                scratch=(work.path / PARTIAL_FILE,),
                fsize=plan.archive_bytes + (1 << 20),
                unit_prefix="m10-export",
            )
        except asyncio.CancelledError:
            # The A4 supervisor kills the unit on cancellation but cannot prove it; keep scratch for the sweep.
            work.keep()
            raise
        except Exception:
            work.keep()
            raise ambiguous from None
        finally:
            work.mark_launch()
        if not outcome.group_cleanup_verified:
            work.keep()
            raise ambiguous
        try:
            return await self._accept(outcome, plan, store, work, ambiguous)
        except (M10Error, AmbiguousSubmitError):
            raise
        except Exception:
            raise ambiguous from None

    async def _accept(
        self, outcome: WorkerOutcome, plan: ExportPlan, store: int, work: WorkDirectory, ambiguous: AmbiguousSubmitError
    ) -> str:
        """Classify a verified-clean worker end; only a fully bound OK report is published."""
        report = _worker_report(outcome.stdout)
        status = None if report is None else report["status"]
        if report is not None and outcome.exit_code == 1 and outcome.manager_result == "EXIT_CODE":
            if status == "INTEGRITY_FAILED":
                raise ExportIntegrityFailedError()
            if status == "ENVELOPE_EXCEEDED":
                raise OperationalEnvelopeExceededError()
        digest = None if report is None else report["digest"]
        if (
            report is None
            or status != "OK"
            or not isinstance(digest, str)
            or (outcome.exit_code, outcome.manager_result) != (0, "SUCCESS")
            or report.get("envelope") != worker_envelope()
            or not _abi_at_least(report.get("landlock_abi"), MIN_LANDLOCK_ABI)
            or not _same_builder(report.get("worker"), plan.manifest.builder_identity_digest)
        ):
            raise ambiguous
        published = PurePosixPath(archive_ref(digest)).name
        await asyncio.to_thread(_publish, store, work, published)
        verified = await asyncio.to_thread(verify_archive, store, published, plan.manifest, plan.manifest_bytes)
        if verified.digest != digest or verified.byte_size != plan.archive_bytes:
            raise ambiguous
        return digest

    async def _resume(self, invocation: StoredExportInvocation) -> p.ExportBundleReceipt:
        """An earlier call prepared this command: finalize an accepted attempt; never rebuild under it."""
        command = invocation.request.command
        async with self._sessions() as session:
            attempt = await ExecutionAttemptRepository(session, capability_resolver=capability_resolver()).get_exact(
                user_id=command.user_id, project_name=command.project_name, execution_id=invocation.execution_id
            )
        if attempt is None or attempt.state is not ExecutionAttemptState.ACCEPTED:
            raise (
                ExportIntegrityFailedError()
                if (attempt is not None and attempt.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE)
                else RequiredEvidenceMissingError()
            )
        return await self._finalize(invocation, await self._grant_reader())

    async def _finalize(
        self, invocation: StoredExportInvocation, reader: CheckpointedShowrunnerGrantReader
    ) -> p.ExportBundleReceipt:
        request = invocation.request
        command = request.command
        subject = request.subject
        async with self._sessions() as session:
            attempt = await ExecutionAttemptRepository(session, capability_resolver=capability_resolver()).get_exact(
                user_id=subject.user_id, project_name=subject.project_name, execution_id=invocation.execution_id
            )
        prefix = f"{invocation.execution_id}:"
        job = "" if attempt is None or attempt.provider_job_id is None else attempt.provider_job_id
        digest = job.removeprefix(prefix)
        if (
            attempt is None
            or attempt.state is not ExecutionAttemptState.ACCEPTED
            or not job.startswith(prefix)
            or attempt.task_id != invocation.task_id
            or invocation.task_id != export_task_id(command.user_id, command.project_name, command.command_id)
            or invocation.identity_digest != execution_identity_digest(request, invocation.manifest)
            or attempt.request_digest != attempt_request_digest(provider_request(invocation))
            or attempt.route != export_route(invocation.manifest.builder_identity_digest)
        ):
            raise RequiredEvidenceMissingError()
        manifest_bytes = canonical_json_bytes(invocation.manifest.model_dump(mode="json"))
        name = PurePosixPath(archive_ref(digest)).name
        store = await asyncio.to_thread(open_export_store, self._project_root)
        try:
            # Bulk verification outside any lock; under the lock only the pinned generation is rechecked.
            verified = await asyncio.to_thread(verify_archive, store, name, invocation.manifest, manifest_bytes)
            if verified.digest != digest:
                raise ExportIntegrityFailedError()
            async with self._sessions() as session, session.begin():
                repository = ExportRepository(session)
                await PackageSelectionRepository(session).lock_command(command)
                replayed = await repository.receipt(
                    user_id=subject.user_id, project_name=subject.project_name, execution_id=invocation.execution_id
                )
                if replayed is not None:
                    return replayed
                attempts = ExecutionAttemptRepository(session, capability_resolver=capability_resolver())
                current = await attempts.get_exact(
                    user_id=subject.user_id, project_name=subject.project_name, execution_id=invocation.execution_id
                )
                if (
                    current is None
                    or current.state is not ExecutionAttemptState.ACCEPTED
                    or current.provider_job_id != job
                ):
                    raise RequiredEvidenceMissingError()
                selection = await PackageSelectionRepository(session).selection(
                    user_id=subject.user_id, project_name=subject.project_name, selection_id=subject.selection_id
                )
                if selection is None:
                    raise RequiredEvidenceMissingError()
                await self._require_current(session, reader, request.subject, selection)
                if published_generation(store, name) != verified.generation:
                    raise ExportIntegrityFailedError()
                succeeded = await attempts.apply_provider_observation(
                    user_id=subject.user_id,
                    project_name=subject.project_name,
                    execution_id=invocation.execution_id,
                    expected_version=current.state_version,
                    observation=ProviderObservation(
                        observation_id=f"{invocation.execution_id}:succeeded",
                        kind=ProviderObservationKind.SUCCEEDED,
                        observed_at=self._clock(),
                        provider_job_id=job,
                        evidence_digest=digest,
                    ),
                )
                if succeeded.state is not ExecutionAttemptState.SUCCEEDED:
                    raise RequiredEvidenceMissingError()
                receipt = p.ExportBundleReceipt(
                    receipt_id=uuid7(),
                    execution_id=invocation.execution_id,
                    command_id=command.command_id,
                    request_digest=command.request_digest,
                    manifest=invocation.manifest,
                    manifest_digest=invocation.manifest_digest,
                    archive_ref=archive_ref(digest),
                    archive_digest=digest,
                    archive_byte_size=verified.byte_size,
                    status="EXPORTED",
                    exported_at=self._clock(),
                )
                await repository.stage_receipt(
                    user_id=subject.user_id, project_name=subject.project_name, receipt=receipt
                )
            return receipt
        finally:
            os.close(store)


def sweep_work(project_root: Path) -> int:
    """Remove scratch directories of exports that no longer run (their owner lock is free)."""
    try:
        store = open_export_store(project_root)
    except ExportIntegrityFailedError:
        return 0
    removed = 0
    try:
        for name in os.listdir(store):
            if not name.startswith(WORK_PREFIX):
                continue
            try:
                directory = _open_directory(store, name, create=False)
            except OSError:
                continue
            try:
                # Directories are published already owned, so a missing lock means a damaged directory: keep it.
                lock = os.open(OWNER_LOCK, os.O_RDWR | _NOFOLLOW, dir_fd=directory)
            except OSError:
                os.close(directory)
                continue
            if time.time() - os.fstat(lock).st_mtime < SWEEP_AFTER_SECONDS:
                # A kept directory may belong to a worker that is still within its runtime limit.
                os.close(lock)
                os.close(directory)
                continue
            try:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                shutil.rmtree(name, dir_fd=store)
                removed += 1
            finally:
                os.close(lock)
                os.close(directory)
    finally:
        os.close(store)
    return removed


__all__ = [
    "EXPORT_DIRECTORY",
    "Download",
    "PackageExportService",
    "archive_ref",
    "builder_identity_digest",
    "export_route",
    "export_task_id",
    "member_path",
    "metadata_document",
    "plan_export",
    "snapshot_assets",
    "sweep_work",
    "verify_archive",
    "worker_config",
]
