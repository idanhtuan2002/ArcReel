from __future__ import annotations

import hashlib
import json
import shutil
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
    CandidateSelectionStatus,
    ContentBasis,
    GenerationCandidate,
    GenerationLifecycleStatus,
    ShotSpec,
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

from .local_production import LocalProducedAsset


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
    shot: ShotSpec,
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
        self.resource_type = resource_type
        self.episode = episode
        self.versions = VersionManager(self.project_dir)
        self.manifest = ProjectArtifactManifestAdapter(self.project_dir)

    def artifact_key_for(self, target_ref: str) -> str:
        return ArtifactKey.episode_video(
            self.episode,
            target_ref,
        ).encode()

    def current_file_for(self, target_ref: str) -> Path:
        return self.project_dir / "r2_m3_current" / f"{target_ref}.mp4"

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
    ) -> R2ArtifactMetadata:
        approved = None
        key = self.artifact_key_for(target_ref)
        existing = self._port(target_ref).load_artifact(key)
        if existing is not None and existing.r2_raw is not None:
            approved = R2ArtifactMetadata.model_validate(existing.r2_raw).approved_master

        return R2ArtifactMetadata(
            metadata_schema_version=_metadata_schema_version(),
            contract_ref=R2ContractRef(
                contract_type="ShotSpec",
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
        produced: LocalProducedAsset,
        content_basis: ContentBasis,
        direct_dependencies: Sequence[DependencySnapshot],
        contract_version: int,
        contract_schema_version: str,
    ) -> RegisteredGoldenACandidate:
        if produced.target_ref != target_ref:
            raise ValueError("produced asset target does not match candidate target")

        metadata = self._metadata(
            target_ref=target_ref,
            content_fingerprint=content_fingerprint,
            content_basis=content_basis,
            direct_dependencies=direct_dependencies,
            contract_version=contract_version,
            contract_schema_version=contract_schema_version,
        )
        artifact_key = self.artifact_key_for(target_ref)
        self._ensure_manifest_entry(
            artifact_key=artifact_key,
            metadata=metadata,
            target_ref=target_ref,
        )

        staged_dir = self.project_dir / "r2_m3_staged"
        staged_dir.mkdir(parents=True, exist_ok=True)
        staged = staged_dir / (f"{target_ref}-{produced.execution_fingerprint[:12]}.mp4")
        shutil.copy2(produced.path, staged)

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
        )
        candidate = GenerationCandidate(
            id=f"CAND-{target_ref}-V{commit.version}",
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
            host_version_ref=str(commit.version),
        )

    def approve(
        self,
        registered: RegisteredGoldenACandidate,
        *,
        approval_record: str,
        selected_by: str,
        selected_at,
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
