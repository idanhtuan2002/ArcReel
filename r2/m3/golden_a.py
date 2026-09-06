from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from lib.artifact_manifest import (
    ArtifactKey,
    ArtifactManifestEntry,
    ProjectArtifactManifestAdapter,
)
from r2.contracts.enums import ArtifactCurrencyStatus, ProductionMethod
from r2.production import (
    ArcReelArtifactManifestPort,
    DependencyResolverRegistry,
    DependencySnapshot,
    R2ArtifactBridge,
    R2ArtifactMetadata,
    R2ContractRef,
)
from .composition import GoldenAComposer
from .director import FixtureOpenMontageBackend, GoldenAOpenMontageAdapter
from .factual_fixture import GoldenAFactualBundle, load_golden_a_factual_bundle
from .host_integration import GoldenAHostIntegration, compute_content_fingerprint
from .local_production import GoldenALocalProducer
from .preparation import GoldenAProductionPreparation


FIXED_APPROVAL_TIME = datetime(
    2026, 9, 6, 22, 30, tzinfo=timezone.utc
)


def _stable_hash(payload) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


class MappingResolver:
    def __init__(self, values: Mapping[str, DependencySnapshot]) -> None:
        self.values = dict(values)

    def supports(self, ref: str) -> bool:
        return ref in self.values

    def resolve(self, ref: str) -> DependencySnapshot:
        return self.values[ref]


@dataclass(frozen=True)
class GoldenARunResult:
    final_path: Path
    final_sha256: str
    final_duration_seconds: float
    methods: tuple[ProductionMethod, ...]
    external_provider_cost: Decimal
    lineage: dict
    invalidation: dict[str, str]
    restart_verified: bool
    evidence_path: Path


class GoldenARunner:
    def _claim_snapshots(
        self,
        bundle: GoldenAFactualBundle,
    ) -> dict[str, DependencySnapshot]:
        return {
            claim.id: DependencySnapshot(
                ref=f"claim:{claim.id}",
                version=str(claim.version),
                fingerprint=_stable_hash(claim),
            )
            for claim in bundle.claim_ledger.claims
        }

    def _shot_claim_ids(self, bundle: GoldenAFactualBundle, direction):
        section_claims = {
            section.id: list(section.claim_refs)
            for section in bundle.script.sections
        }
        scene_sections = {
            scene.id: list(scene.source_unit_refs)
            for scene in direction.scenes
        }
        return {
            shot.id: [
                claim_id
                for section_id in scene_sections[shot.scene_id]
                for claim_id in section_claims[section_id]
            ]
            for shot in direction.shots
        }

    def _register_final(
        self,
        *,
        project_dir: Path,
        episode: int,
        final_path: Path,
        content_basis,
        shot_metadata: Mapping[str, R2ArtifactMetadata],
    ) -> tuple[str, str]:
        dependencies = [
            DependencySnapshot(
                ref=f"artifact:{shot_id}",
                version=str(metadata.contract_ref.version),
                fingerprint=metadata.content_fingerprint,
            )
            for shot_id, metadata in sorted(shot_metadata.items())
        ]
        content_fingerprint = _stable_hash(
            {
                "target_ref": "FINAL-GOLDEN-A",
                "method": ProductionMethod.COMPOSITE.value,
                "dependencies": [
                    dep.model_dump(mode="json")
                    for dep in dependencies
                ],
            }
        )
        metadata = R2ArtifactMetadata(
            metadata_schema_version="1",
            contract_ref=R2ContractRef(
                contract_type="GoldenAComposite",
                id="FINAL-GOLDEN-A",
                version=1,
                schema_version="1",
            ),
            content_basis=content_basis,
            direct_dependencies=dependencies,
            content_fingerprint=content_fingerprint,
            approved_master=None,
        )

        key = ArtifactKey.episode_video(episode, "FINAL-GOLDEN-A")
        rel = final_path.relative_to(project_dir).as_posix()
        entry = ArtifactManifestEntry(
            artifact_path=rel,
            basis_digest="sha256-v1:" + content_fingerprint,
            r2=metadata.model_dump(mode="json"),
        )
        adapter = ProjectArtifactManifestAdapter(project_dir)
        if not adapter.put_entry(key, entry):
            existing = adapter.get_entry(key)
            if existing != entry:
                raise RuntimeError(
                    "final manifest entry already exists with different data"
                )
        return key.encode(), content_fingerprint

    def _lineage(
        self,
        *,
        bundle: GoldenAFactualBundle,
        direction,
        host: GoldenAHostIntegration,
        final_asset,
    ) -> dict:
        sections = {item.id: item for item in bundle.script.sections}
        claims = {item.id: item for item in bundle.claim_ledger.claims}
        evidence = {item.id: item for item in bundle.evidence}
        scene_by_id = {scene.id: scene for scene in direction.scenes}
        shots = []

        for shot in direction.shots:
            scene = scene_by_id[shot.scene_id]
            section_ids = list(scene.source_unit_refs)
            claim_ids = sorted(
                {
                    claim_id
                    for section_id in section_ids
                    for claim_id in sections[section_id].claim_refs
                }
            )
            evidence_ids = sorted(
                {
                    evidence_id
                    for claim_id in claim_ids
                    for evidence_id in claims[claim_id].evidence_refs
                }
            )
            source_ids = sorted(
                {
                    evidence[evidence_id].source_ref
                    for evidence_id in evidence_ids
                }
            )
            master = host.snapshot(shot.id).approved_master
            if master is None:
                raise RuntimeError(f"{shot.id} has no approved master")

            shots.append(
                {
                    "final_ref": "FINAL-GOLDEN-A",
                    "approved_master": master.model_dump(mode="json"),
                    "shot_spec": shot.id,
                    "scene_spec": scene.id,
                    "script_sections": section_ids,
                    "claims": claim_ids,
                    "evidence": evidence_ids,
                    "sources": source_ids,
                }
            )

        return {
            "final": {
                "target_ref": "FINAL-GOLDEN-A",
                "sha256": final_asset.sha256,
                "source_master_refs": list(final_asset.source_master_refs),
            },
            "shots": shots,
        }

    def _invalidation(
        self,
        *,
        project_dir: Path,
        direction,
        host: GoldenAHostIntegration,
        claim_snapshots: Mapping[str, DependencySnapshot],
        shot_claim_ids: Mapping[str, Sequence[str]],
        final_key: str,
    ) -> dict[str, str]:
        current_claims = dict(claim_snapshots)
        old_claim2 = current_claims["CLAIM-002"]
        current_claims["CLAIM-002"] = DependencySnapshot(
            ref=old_claim2.ref,
            version="2",
            fingerprint=hashlib.sha256(
                b"CLAIM-002-semantic-change-v2"
            ).hexdigest(),
        )

        port = ArcReelArtifactManifestPort(
            project_dir,
            native_currency=lambda _key: ArtifactCurrencyStatus.CURRENT,
        )
        claim_bridge = R2ArtifactBridge(
            port,
            DependencyResolverRegistry(
                [
                    MappingResolver(
                        {
                            snapshot.ref: snapshot
                            for snapshot in current_claims.values()
                        }
                    )
                ]
            ),
        )

        results: dict[str, str] = {}
        shot_current_snapshots: dict[str, DependencySnapshot] = {}
        shot_by_id = {shot.id: shot for shot in direction.shots}

        for shot_id in ("SH01", "SH02", "SH03", "SH04"):
            status = claim_bridge.evaluate_currency(
                host.artifact_key_for(shot_id)
            ).status
            if status is None:
                raise RuntimeError(f"missing R2 currency for {shot_id}")
            results[shot_id] = status.value

            current_dependencies = [
                current_claims[claim_id]
                for claim_id in shot_claim_ids[shot_id]
            ]
            current_content_fp = compute_content_fingerprint(
                shot_by_id[shot_id],
                current_dependencies,
            )
            shot_current_snapshots[f"artifact:{shot_id}"] = DependencySnapshot(
                ref=f"artifact:{shot_id}",
                version=str(shot_by_id[shot_id].version),
                fingerprint=current_content_fp,
            )

        final_bridge = R2ArtifactBridge(
            port,
            DependencyResolverRegistry(
                [MappingResolver(shot_current_snapshots)]
            ),
        )
        final_status = final_bridge.evaluate_currency(final_key).status
        if final_status is None:
            raise RuntimeError("missing R2 currency for final composite")
        results["FINAL-GOLDEN-A"] = final_status.value
        return results

    def run(self, output_dir: Path) -> GoldenARunResult:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        project_dir = output_dir / "host_project"
        production_dir = output_dir / "production"

        bundle = load_golden_a_factual_bundle()
        direction = GoldenAOpenMontageAdapter(
            FixtureOpenMontageBackend()
        ).direct(bundle.script)
        prepared = GoldenAProductionPreparation().prepare(
            direction.shots,
            reused_asset_ref="r2/m3/fixtures/assets/reused_terminal_frame.svg",
        )

        host = GoldenAHostIntegration(
            project_dir,
            resource_type="videos",
            episode=1,
        )
        producer = GoldenALocalProducer()
        claim_snapshots = self._claim_snapshots(bundle)
        shot_claim_ids = self._shot_claim_ids(bundle, direction)

        provenance: list[dict] = []
        methods: set[ProductionMethod] = set()

        for item in prepared:
            dependencies = [
                claim_snapshots[claim_id]
                for claim_id in shot_claim_ids[item.shot.id]
            ]
            content_fp = compute_content_fingerprint(
                item.shot,
                dependencies,
            )
            produced = producer.produce(
                item,
                work_dir=production_dir / item.shot.id,
                execution_variant="golden-a-e2e",
            )
            registered = host.stage_candidate(
                target_ref=item.shot.id,
                content_fingerprint=content_fp,
                produced=produced,
                content_basis=item.shot.content_basis,
                direct_dependencies=dependencies,
                contract_version=item.shot.version,
                contract_schema_version=item.shot.schema_version,
            )
            host.approve(
                registered,
                approval_record=f"APR-{item.shot.id}",
                selected_by="human-showrunner",
                selected_at=FIXED_APPROVAL_TIME,
            )
            methods.add(produced.method)
            provenance.append(
                {
                    "target_ref": item.shot.id,
                    "method": produced.method.value,
                    "tool": produced.tool,
                    "tool_version": produced.tool_version,
                    "content_fingerprint": content_fp,
                    "execution_fingerprint": produced.execution_fingerprint,
                    "output_sha256": produced.sha256,
                    "wall_time_seconds": produced.wall_time_seconds,
                    "external_provider_cost": str(
                        produced.external_provider_cost
                    ),
                    "direct_dependencies": [
                        dep.model_dump(mode="json")
                        for dep in dependencies
                    ],
                }
            )

        final_path = project_dir / "final" / "final.mp4"
        final_asset = GoldenAComposer().compose(
            host,
            ["SH01", "SH02", "SH03", "SH04"],
            output_path=final_path,
        )
        methods.add(final_asset.method)

        shot_metadata = {
            shot.id: host.snapshot(shot.id)
            for shot in direction.shots
        }
        final_key, final_content_fp = self._register_final(
            project_dir=project_dir,
            episode=1,
            final_path=final_path,
            content_basis=bundle.script.content_basis,
            shot_metadata=shot_metadata,
        )
        provenance.append(
            {
                "target_ref": final_asset.target_ref,
                "method": final_asset.method.value,
                "tool": final_asset.tool,
                "tool_version": final_asset.tool_version,
                "content_fingerprint": final_content_fp,
                "execution_fingerprint": final_asset.execution_fingerprint,
                "output_sha256": final_asset.sha256,
                "wall_time_seconds": final_asset.wall_time_seconds,
                "external_provider_cost": str(
                    final_asset.external_provider_cost
                ),
                "direct_dependencies": [
                    {
                        "ref": f"artifact:{shot_id}",
                        "version": str(metadata.contract_ref.version),
                        "fingerprint": metadata.content_fingerprint,
                    }
                    for shot_id, metadata in sorted(shot_metadata.items())
                ],
            }
        )

        lineage = self._lineage(
            bundle=bundle,
            direction=direction,
            host=host,
            final_asset=final_asset,
        )
        invalidation = self._invalidation(
            project_dir=project_dir,
            direction=direction,
            host=host,
            claim_snapshots=claim_snapshots,
            shot_claim_ids=shot_claim_ids,
            final_key=final_key,
        )

        restarted = GoldenAHostIntegration(
            project_dir,
            resource_type="videos",
            episode=1,
        )
        restart_verified = all(
            restarted.snapshot(shot.id).approved_master is not None
            and restarted.current_file_for(shot.id).is_file()
            for shot in direction.shots
        )
        final_entry = ProjectArtifactManifestAdapter(
            project_dir
        ).get_entry(
            ArtifactKey.episode_video(1, "FINAL-GOLDEN-A")
        )
        restart_verified = (
            restart_verified
            and final_entry is not None
            and final_path.is_file()
        )

        total_cost = sum(
            (
                Decimal(record["external_provider_cost"])
                for record in provenance
            ),
            Decimal("0"),
        )
        evidence = {
            "final": {
                "path": str(final_path),
                "sha256": final_asset.sha256,
                "duration_seconds": final_asset.duration_seconds,
                "content_fingerprint": final_content_fp,
                "execution_fingerprint": final_asset.execution_fingerprint,
            },
            "methods": sorted(method.value for method in methods),
            "external_provider_cost": str(total_cost),
            "provenance": provenance,
            "lineage": lineage,
            "invalidation": invalidation,
            "restart_verified": restart_verified,
        }
        evidence_path = output_dir / "golden_a_evidence.json"
        evidence_path.write_text(
            json.dumps(
                evidence,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        return GoldenARunResult(
            final_path=final_path,
            final_sha256=final_asset.sha256,
            final_duration_seconds=final_asset.duration_seconds,
            methods=tuple(sorted(methods, key=lambda value: value.value)),
            external_provider_cost=total_cost,
            lineage=lineage,
            invalidation=invalidation,
            restart_verified=restart_verified,
            evidence_path=evidence_path,
        )
