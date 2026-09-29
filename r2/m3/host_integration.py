from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from lib.artifact_manifest import (
    ArtifactKey,
    ArtifactManifestEntry,
    ProjectArtifactManifestAdapter,
)
from lib.version_manager import VersionManager
from r2.contracts import (
    AnyShotSpec,
    CandidateSelectionStatus,
    ContentBasis,
    GenerationCandidate,
    GenerationLifecycleStatus,
)
from r2.contracts.enums import ArtifactCurrencyStatus
from r2.production import (
    ApprovedMasterMetadata,
    ArcReelArtifactManifestPort,
    ArcReelVersionRestorePromoter,
    DependencySnapshot,
    ProductionApprovalService,
    R2ArtifactMetadata,
    R2ContractRef,
)

from .render_plan import RenderedCutAsset


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _metadata_schema_version():
    field = R2ArtifactMetadata.model_fields["metadata_schema_version"]
    adapter = TypeAdapter(field.annotation)
    for candidate in (1, "1", "r2-m2-1"):
        try:
            return adapter.validate_python(candidate)
        except Exception:
            pass
    raise RuntimeError("cannot resolve R2ArtifactMetadata.metadata_schema_version")


def compute_content_fingerprint(
    shot: AnyShotSpec,
    direct_dependencies: Sequence[DependencySnapshot],
) -> str:
    payload = {
        "shot": shot.model_dump(mode="json"),
        "direct_dependencies": [
            item.model_dump(mode="json")
            for item in sorted(
                direct_dependencies,
                key=lambda value: value.ref,
            )
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class RegisteredGoldenACandidate:
    artifact_key: str
    candidate: GenerationCandidate
    host_version_ref: str


def validate_m3_target_ref(target_ref: str) -> str:
    if (
        not target_ref
        or target_ref in {".", ".."}
        or any(char in target_ref for char in ("/", "\\", ":", "\x00"))
        or any(ord(char) < 32 for char in target_ref)
    ):
        raise ValueError("target_ref must be one safe filename component")
    return target_ref


def safe_project_subdir(project_dir: Path, name: str) -> Path:
    root = Path(project_dir).resolve()
    path = Path(project_dir) / name
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError(f"{name} must be a directory inside the project")
    return path


class StagedOperationConflictError(ValueError):
    """An approval record is being reused for a different candidate or an older approval."""


class GoldenAHostIntegration:
    def __init__(
        self,
        project_dir: Path,
        *,
        resource_type: str,
        episode: int,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        if resource_type not in VersionManager.RESOURCE_TYPES:
            raise ValueError(f"unsupported VersionManager resource type: {resource_type}")
        versions_dir = safe_project_subdir(self.project_dir, "versions")
        safe_project_subdir(versions_dir, resource_type)
        if (versions_dir / "versions.json").is_symlink():
            raise ValueError("version metadata must stay inside the project")
        self.resource_type = resource_type
        self.episode = episode
        self.versions = VersionManager(self.project_dir)
        self.manifest = ProjectArtifactManifestAdapter(self.project_dir)

    def artifact_key_for(self, target_ref: str) -> str:
        validate_m3_target_ref(target_ref)
        return ArtifactKey.episode_video(
            self.episode,
            target_ref,
        ).encode()

    def current_file_for(self, target_ref: str) -> Path:
        validate_m3_target_ref(target_ref)
        directory = safe_project_subdir(self.project_dir, "r2_m3_current")
        path = directory / f"{target_ref}.mp4"
        if path.is_symlink() or path.resolve().parent != directory.resolve():
            raise ValueError("current file must stay inside the project")
        return path

    def _native_currency(
        self,
        _artifact_key: str,
    ) -> ArtifactCurrencyStatus:
        return ArtifactCurrencyStatus.CURRENT

    def _port(
        self,
        target_ref: str,
        *,
        promoting: bool = False,
    ):
        promoter = None
        if promoting:
            promoter = ArcReelVersionRestorePromoter(
                self.versions,
                resource_type=self.resource_type,
                resource_id=target_ref,
                current_file=self.current_file_for(target_ref),
            )
        return ArcReelArtifactManifestPort(
            self.project_dir,
            native_currency=self._native_currency,
            version_promoter=promoter,
        )

    def _metadata(
        self,
        *,
        target_ref: str,
        content_fingerprint: str,
        content_basis: ContentBasis,
        direct_dependencies: Sequence[DependencySnapshot],
        contract_version: int,
        contract_schema_version: str,
        contract_type: str = "ShotSpec",
    ) -> R2ArtifactMetadata:
        approved = None
        key = self.artifact_key_for(target_ref)
        existing = self._port(target_ref).load_artifact(key)
        if existing is not None and existing.r2_raw is not None:
            approved = R2ArtifactMetadata.model_validate(existing.r2_raw).approved_master

        return R2ArtifactMetadata(
            metadata_schema_version=_metadata_schema_version(),
            contract_ref=R2ContractRef(
                contract_type=contract_type,
                id=target_ref,
                version=contract_version,
                schema_version=contract_schema_version,
            ),
            content_basis=content_basis,
            direct_dependencies=list(direct_dependencies),
            content_fingerprint=content_fingerprint,
            approved_master=approved,
        )

    def _ensure_manifest_entry(
        self,
        *,
        artifact_key: str,
        metadata: R2ArtifactMetadata,
        target_ref: str,
    ) -> None:
        key = ArtifactKey.decode(artifact_key)
        current = self.manifest.get_entry(key)
        if current is not None:
            self._port(target_ref).write_r2_metadata(
                artifact_key,
                metadata,
            )
            return

        current_file = self.current_file_for(target_ref)
        rel = current_file.relative_to(self.project_dir).as_posix()
        digest = "sha256-v1:" + _sha_text(metadata.content_fingerprint)
        entry = ArtifactManifestEntry(
            artifact_path=rel,
            basis_digest=digest,
            r2=metadata.model_dump(mode="json"),
        )
        self.manifest.put_entry(key, entry)

    def stage_candidate(
        self,
        *,
        target_ref: str,
        content_fingerprint: str,
        produced: RenderedCutAsset,
        content_basis: ContentBasis,
        direct_dependencies: Sequence[DependencySnapshot],
        contract_version: int,
        contract_schema_version: str,
        contract_type: str = "ShotSpec",
        operation_id: str | None = None,
        request_digest: str | None = None,
        keep_approved_semantic_state: bool = False,
    ) -> RegisteredGoldenACandidate:
        """Stage ``produced`` as a new host version of ``target_ref``.

        With ``keep_approved_semantic_state``, an artifact that already has an approved master keeps
        its semantic state (fingerprint and dependencies) until the new candidate is promoted, so a
        stage whose promotion never lands cannot make the old master look current against new
        dependencies. The promoting caller then passes the state to ``approve``, which writes it with
        the new approved master in one manifest update.
        """
        if produced.target_ref != target_ref:
            raise ValueError("produced asset target does not match candidate target")
        if (operation_id is None) != (request_digest is None):
            raise ValueError("operation_id and request_digest must be supplied together")

        artifact_key = self.artifact_key_for(target_ref)
        replay_version = None
        if operation_id is not None:
            versions = self.versions.get_versions(self.resource_type, target_ref)
            existing = next((item for item in versions["versions"] if item.get("execution_id") == operation_id), None)
            if existing is not None:
                replay_version = int(existing["version"])
                if existing.get("request_digest") != request_digest:
                    raise StagedOperationConflictError("approval_record is already bound to a different request")
                current = self.snapshot(target_ref).approved_master
                if current is not None and int(current.host_version_ref) > replay_version:
                    raise StagedOperationConflictError("approval_record belongs to a superseded final cut")

        if replay_version is None:
            metadata = self._metadata(
                target_ref=target_ref,
                content_fingerprint=content_fingerprint,
                content_basis=content_basis,
                direct_dependencies=direct_dependencies,
                contract_version=contract_version,
                contract_schema_version=contract_schema_version,
                contract_type=contract_type,
            )
            if not (keep_approved_semantic_state and metadata.approved_master is not None):
                self._ensure_manifest_entry(
                    artifact_key=artifact_key,
                    metadata=metadata,
                    target_ref=target_ref,
                )

            staged_dir = safe_project_subdir(self.project_dir, "r2_m3_staged")
            staged_dir.mkdir(parents=True, exist_ok=True)
            fd, staged_name = tempfile.mkstemp(dir=staged_dir, prefix=f".{target_ref}-", suffix=".mp4")
            os.close(fd)
            staged = Path(staged_name)
            try:
                shutil.copy2(produced.path, staged)
                with staged.open("rb") as handle:
                    staged_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
                if staged_sha256 != produced.sha256.removeprefix("sha256:").lower():
                    raise ValueError("staged candidate does not match produced.sha256")
            except BaseException:
                staged.unlink(missing_ok=True)
                raise

            commit = self.versions.commit_staged_paid_version(
                self.resource_type,
                target_ref,
                "Golden A local candidate",
                staged_file=staged,
                current_file=self.current_file_for(target_ref),
                select_current=False,
                method=produced.method.value,
                execution_fingerprint=produced.execution_fingerprint,
                external_provider_cost=str(produced.external_provider_cost),
                output_sha256=staged_sha256,
                execution_id=operation_id,
                request_digest=request_digest,
            )
            replay_version = commit.version
            if operation_id is not None:
                record = next(
                    item
                    for item in self.versions.get_versions(self.resource_type, target_ref)["versions"]
                    if item["version"] == replay_version
                )
                if record.get("request_digest") != request_digest or record.get("output_sha256") != staged_sha256:
                    raise StagedOperationConflictError("approval_record raced with a different candidate")
        candidate = GenerationCandidate(
            id=f"CAND-{target_ref}-V{replay_version}",
            target_ref=target_ref,
            content_fingerprint=content_fingerprint,
            execution_fingerprint=produced.execution_fingerprint,
            provider_execution_ref=("local:ffmpeg:" + produced.execution_fingerprint),
            output_asset_ref=str(produced.path),
            lifecycle_state=GenerationLifecycleStatus.GENERATED,
            selection_state=CandidateSelectionStatus.UNREVIEWED,
        )
        return RegisteredGoldenACandidate(
            artifact_key=artifact_key,
            candidate=candidate,
            host_version_ref=str(replay_version),
        )

    def staged_version(self, target_ref: str, host_version_ref: str) -> tuple[Path, str]:
        """The staged host version file and its recorded ``sha256:`` output digest."""
        record = self._version_record(target_ref, host_version_ref)
        output_sha256 = record.get("output_sha256")
        if not isinstance(output_sha256, str) or not output_sha256:
            raise ValueError(f"{target_ref} version {host_version_ref} has no recorded output digest")
        path = VersionManager.resolve_snapshot_path(self.project_dir, self.resource_type, record["file"]).resolve()
        return path, "sha256:" + output_sha256.removeprefix("sha256:").lower()

    def _version_record(self, target_ref: str, host_version_ref: str) -> dict:
        version = int(host_version_ref)
        record = next(
            (
                item
                for item in self.versions.get_versions(self.resource_type, target_ref)["versions"]
                if item["version"] == version
            ),
            None,
        )
        if record is None:
            raise KeyError(f"{target_ref} has no host version {host_version_ref}")
        return record

    def semantic_state_for(
        self,
        *,
        target_ref: str,
        content_fingerprint: str,
        content_basis: ContentBasis,
        direct_dependencies: Sequence[DependencySnapshot],
        contract_version: int,
        contract_schema_version: str,
        contract_type: str = "ShotSpec",
    ) -> R2ArtifactMetadata:
        """The metadata a candidate with these arguments carries once it is approved."""
        return self._metadata(
            target_ref=target_ref,
            content_fingerprint=content_fingerprint,
            content_basis=content_basis,
            direct_dependencies=direct_dependencies,
            contract_version=contract_version,
            contract_schema_version=contract_schema_version,
            contract_type=contract_type,
        )

    def check_approvable(
        self, registered: RegisteredGoldenACandidate, semantic_state: R2ArtifactMetadata | None = None
    ) -> None:
        """Raise ``KeyError``/``ValueError`` if ``approve`` would refuse ``registered``.

        ``semantic_state`` is the metadata the caller will write before approving; by default the
        manifest's current metadata is used.
        """
        ProductionApprovalService(self._port(registered.candidate.target_ref)).check(
            artifact_key=registered.artifact_key,
            candidate=registered.candidate,
            host_version_ref=registered.host_version_ref,
            semantic_state=semantic_state,
        )

    def approve(
        self,
        registered: RegisteredGoldenACandidate,
        *,
        approval_record: str,
        selected_by: str,
        selected_at,
        semantic_state: R2ArtifactMetadata | None = None,
    ) -> ApprovedMasterMetadata:
        service = ProductionApprovalService(
            self._port(
                registered.candidate.target_ref,
                promoting=True,
            )
        )
        result = service.promote(
            artifact_key=registered.artifact_key,
            candidate=registered.candidate,
            host_version_ref=registered.host_version_ref,
            approval_record=approval_record,
            selected_by=selected_by,
            selected_at=selected_at,
            semantic_state=semantic_state,
        )
        return result.approved_master

    def snapshot(
        self,
        target_ref: str,
    ) -> R2ArtifactMetadata:
        key = self.artifact_key_for(target_ref)
        snapshot = self._port(target_ref).load_artifact(key)
        if snapshot is None or snapshot.r2_raw is None:
            raise KeyError(key)
        return R2ArtifactMetadata.model_validate(snapshot.r2_raw)
