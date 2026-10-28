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
import hashlib
import os
import shutil
import uuid
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
from lib.db.repositories.quality_runs import QualityRunRepository
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
    RequiredEvidenceMissingError,
    StaleHeadError,
)
from r2.quality.runs import run_digest
from server.auth import get_current_interactive_user
from server.services import package_export_worker
from server.services.execution_attempts import build_execution_attempt_service, capability_resolver
from server.services.governance_grants import CheckpointedShowrunnerGrantReader
from server.services.package_export_worker import BundleMember, ExportBuildError, build_archive
from server.services.quality_dispositions import readiness_in
from server.services.quality_package_selection import PackageEvidence, resolve_package_evidence
from server.services.quality_packaging import open_beneath
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

type Sessions = async_sessionmaker[AsyncSession]
type GrantReaderFactory = Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]
type SubmitterFactory = Callable[[AsyncSession, str, str, str], AttemptSubmitter]


def builder_identity_digest() -> str:
    """The archive builder is pinned by the exact bytes of its stdlib-only module."""
    return "sha256:" + hashlib.sha256(Path(package_export_worker.__file__).read_bytes()).hexdigest()


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


def member_path(role: str, variant_id: str | None, media_type: str, locale: str | None = None) -> str:
    """The fixed bundle layout: video/output.mp4, thumbnails/<variant>.<ext>, captions/<locale>.srt, assets/…"""
    suffix = _MEDIA_SUFFIX.get(media_type)
    if suffix is None:
        raise ExportIntegrityFailedError()
    if role == "video" and variant_id is None:
        return "video/output.mp4"
    if role == "thumbnail":
        return f"thumbnails/{_slug(variant_id or 'thumbnail')}.{suffix}"
    if locale is not None:
        return f"captions/{_slug(locale)}.{suffix}"
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
class Materialized:
    members: tuple[BundleMember, ...]
    manifest: p.ExportManifest
    manifest_bytes: bytes


def _snapshot(root: Path, source_ref: str, directory: Path, digest: str, size: int) -> Path:
    """A private copy of one asset read beneath the project root without links, verified while copied."""
    parts = PurePosixPath(source_ref).parts
    if str(PurePosixPath(source_ref)) != source_ref or PurePosixPath(source_ref).is_absolute() or ".." in parts:
        raise ExportIntegrityFailedError()
    descriptor = open_beneath(root, parts)
    if descriptor is None:
        raise ExportIntegrityFailedError()
    target = directory / uuid.uuid4().hex
    hasher = hashlib.sha256()
    copied = 0
    with os.fdopen(descriptor, "rb", buffering=0) as source, target.open("xb") as sink:
        while chunk := source.read(min(1 << 20, size + 1 - copied)):
            copied += len(chunk)
            if copied > size:
                raise ExportIntegrityFailedError()
            hasher.update(chunk)
            sink.write(chunk)
        sink.flush()
        os.fsync(sink.fileno())
    if (copied, "sha256:" + hasher.hexdigest()) != (size, digest):
        raise ExportIntegrityFailedError()
    return target


def materialize(
    root: Path, directory: Path, selection: p.PackageSelection, evidence: PackageEvidence, builder_digest: str
) -> Materialized:
    """Snapshot every exported asset and the metadata documents; build the exact manifest they satisfy."""
    preview = selection.preview
    candidate = evidence.candidate
    chosen, values = _chosen(candidate, preview.selected_variant_ids)
    chosen_ids = set(chosen.values())
    members: list[BundleMember] = []
    for asset in candidate.assets:
        if asset.variant_id is not None and asset.variant_id not in chosen_ids:
            continue
        source = _snapshot(root, asset.source_ref, directory, asset.content_digest, asset.byte_size)
        path = member_path(asset.role, asset.variant_id, asset.media_type)
        members.append(BundleMember(path, source, asset.content_digest, asset.byte_size))
    documents = {"metadata/metadata.json": metadata_document(candidate, values)}
    for localized in candidate.localization_variants:
        documents[f"metadata/{_slug(localized.locale)}.json"] = localized.model_dump(mode="json")
    for path, document in documents.items():
        data = canonical_json_bytes(document)
        target = directory / uuid.uuid4().hex
        target.write_bytes(data)
        members.append(BundleMember(path, target, "sha256:" + hashlib.sha256(data).hexdigest(), len(data)))
    media = {m.path: m for m in members}
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
            entries=tuple(
                p.ExportManifestEntry(
                    path=m.path,
                    media_type=_media_of(m.path, candidate),
                    byte_size=m.byte_size,
                    content_digest=m.content_digest,
                )
                for m in media.values()
            ),
        )
    except ValueError:
        raise ExportIntegrityFailedError() from None
    return Materialized(tuple(members), manifest, canonical_json_bytes(manifest.model_dump(mode="json")))


def _media_of(path: str, candidate: PackagingCandidate) -> str:
    if path.startswith("metadata/"):
        return "application/json"
    for asset in candidate.assets:
        if member_path(asset.role, asset.variant_id, asset.media_type) == path:
            return asset.media_type
    raise ExportIntegrityFailedError()


def archive_ref(digest: str) -> str:
    return f"{EXPORT_DIRECTORY}/{digest.removeprefix('sha256:')}.zip"


def _file_digest(path: Path) -> tuple[str, int]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
            size += len(chunk)
    return "sha256:" + hasher.hexdigest(), size


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
    ) -> None:
        self._sessions = sessions
        self._grant_reader = grant_reader
        self._project_root = project_root
        self._token = interactive_token
        self._submitter_for = submitter_for
        self._clock = clock or (lambda: datetime.now(UTC))

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
            selection, evidence = await self._resolve(session, request)
        builder_digest = builder_identity_digest()
        store = self._project_root / EXPORT_DIRECTORY
        await asyncio.to_thread(store.mkdir, parents=True, exist_ok=True)
        snapshots = store / f".snapshot-{uuid.uuid4().hex}"
        await asyncio.to_thread(snapshots.mkdir, mode=0o700)
        try:
            built = await asyncio.to_thread(
                materialize, self._project_root, snapshots, selection, evidence, builder_digest
            )
            return await self._submit(request, reader, selection, built, builder_digest, store)
        finally:
            await asyncio.to_thread(shutil.rmtree, snapshots, True)

    async def _resolve(
        self, session: AsyncSession, request: p.ExportRequest
    ) -> tuple[p.PackageSelection, PackageEvidence]:
        subject = request.subject
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
        request: p.ExportRequest,
        selection: p.PackageSelection,
    ) -> None:
        """Global order with FOR SHARE heads; the selection must still fill the slot and be READY."""
        subject = request.subject
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
        await self._resolve(session, request)
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
        built: Materialized,
        builder_digest: str,
        store: Path,
    ) -> p.ExportBundleReceipt:
        command = request.command
        manifest_digest = compute_digest("m10.export-manifest.v1", built.manifest)
        identity = p.ExportExecutionIdentity(
            schema_id="m10.export-execution.v1",
            slot=request.subject.slot,
            selection_id=selection.selection_id,
            selection_digest=selection_digest(selection),
            manifest_digest=manifest_digest,
            builder_identity_digest=builder_digest,
            adapter_version=HOST_EXPORT_ADAPTER_VERSION,
        )
        invocation = StoredExportInvocation(
            request=request,
            execution_id=uuid7(),
            task_id=export_task_id(command.user_id, command.project_name, command.command_id),
            manifest=built.manifest,
            manifest_digest=manifest_digest,
            identity_digest=compute_digest("m10.export-execution.v1", identity),
        )
        provider_request = ProviderRequest(
            id=f"{invocation.task_id}:export",
            host_task_ref=invocation.task_id,
            provider=_FAMILY.key.provider_id,
            model="zip-stored",
            endpoint=_FAMILY.key.endpoint_id,
            payload={"schema": "m10.export-execution.v1", "identity_digest": invocation.identity_digest},
            adapter_version=HOST_EXPORT_ADAPTER_VERSION,
        )
        async with self._sessions() as session:
            try:
                await session.begin()
                await PackageSelectionRepository(session).lock_command(command)
                if await ExportRepository(session).invocation(request) is not None:
                    raise RequiredEvidenceMissingError()
                await self._require_current(session, reader, request, selection)
                await ExportRepository(session).stage_invocation(invocation, self._clock())
            except BaseException:
                await session.rollback()
                raise
            submitter = self._submitter_for(session, command.user_id, command.project_name, invocation.execution_id)

            async def submit(attempt: AttemptSnapshot) -> ProviderSubmitReceipt[str]:
                digest = await asyncio.to_thread(self._build_and_publish, attempt.execution_id, built, store)
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
                request=provider_request,
                submit=submit,
            )
        if outcome.execution_id != invocation.execution_id:
            raise RequiredEvidenceMissingError()
        if outcome.snapshot.state is ExecutionAttemptState.ACCEPTED:
            return await self._finalize(invocation, reader)
        if outcome.snapshot.state is ExecutionAttemptState.FAILED_BEFORE_ACCEPTANCE:
            raise ExportIntegrityFailedError()
        raise RequiredEvidenceMissingError()

    @staticmethod
    def _build_and_publish(execution_id: str, built: Materialized, store: Path) -> str:
        """Build into a private partial file, then publish it content-addressed after full re-verification."""
        partial = store / f".partial-{execution_id}.zip"
        partial.unlink(missing_ok=True)
        try:
            digest = build_archive(partial, built.members, built.manifest_bytes)
        except ExportBuildError:
            partial.unlink(missing_ok=True)
            raise ExportIntegrityFailedError() from None
        published = store.parent / archive_ref(digest)
        if published.exists():
            partial.unlink()
        else:
            os.replace(partial, published)
        directory = os.open(store, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if _file_digest(published)[0] != digest:
            raise ExportIntegrityFailedError()
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
        async with self._sessions() as session, session.begin():
            repository = ExportRepository(session)
            await PackageSelectionRepository(session).lock_command(command)
            replayed = await repository.receipt(
                user_id=subject.user_id, project_name=subject.project_name, execution_id=invocation.execution_id
            )
            if replayed is not None:
                return replayed
            attempts = ExecutionAttemptRepository(session, capability_resolver=capability_resolver())
            attempt = await attempts.get_exact(
                user_id=subject.user_id, project_name=subject.project_name, execution_id=invocation.execution_id
            )
            prefix = f"{invocation.execution_id}:"
            job = "" if attempt is None or attempt.provider_job_id is None else attempt.provider_job_id
            digest = job.removeprefix(prefix)
            if attempt is None or attempt.state is not ExecutionAttemptState.ACCEPTED or not job.startswith(prefix):
                raise RequiredEvidenceMissingError()
            selection = await PackageSelectionRepository(session).selection(
                user_id=subject.user_id, project_name=subject.project_name, selection_id=subject.selection_id
            )
            if selection is None:
                raise RequiredEvidenceMissingError()
            await self._require_current(session, reader, request, selection)
            published = self._project_root / archive_ref(digest)
            try:
                on_disk, size = await asyncio.to_thread(_file_digest, published)
            except FileNotFoundError:
                raise ExportIntegrityFailedError() from None
            if on_disk != digest:
                raise ExportIntegrityFailedError()
            succeeded = await attempts.apply_provider_observation(
                user_id=subject.user_id,
                project_name=subject.project_name,
                execution_id=invocation.execution_id,
                expected_version=attempt.state_version,
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
                archive_byte_size=size,
                status="EXPORTED",
                exported_at=self._clock(),
            )
            await repository.stage_receipt(user_id=subject.user_id, project_name=subject.project_name, receipt=receipt)
        return receipt


def sweep_partials(project_root: Path) -> int:
    """Remove orphaned partial archives and snapshot directories left by an interrupted export."""
    store = project_root / EXPORT_DIRECTORY
    removed = 0
    if not store.is_dir():
        return removed
    for entry in store.iterdir():
        if entry.name.startswith(".partial-") and entry.is_file() and not entry.is_symlink():
            entry.unlink(missing_ok=True)
            removed += 1
        elif entry.name.startswith(".snapshot-") and entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


__all__ = [
    "EXPORT_DIRECTORY",
    "PackageExportService",
    "archive_ref",
    "builder_identity_digest",
    "export_route",
    "export_task_id",
    "materialize",
    "member_path",
    "metadata_document",
    "sweep_partials",
]
