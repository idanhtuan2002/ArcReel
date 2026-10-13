"""Derive a Gate C shot approval from a finished R2 shot task (ADR-0104).

The caller names only the task. Everything Gate C stages comes from server authority:
- the task's verified evidence;
- the output digest sealed on its M7 attempt;
- the current target and binding snapshot;
- the ledger call bound to the execution.

The output is a candidate of ``episode_video(1, target_id)``; the shared Gate C core then promotes it
under the slot lock exactly like any other shot approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.artifact_manifest import ArtifactKey, ProjectArtifactManifestAdapter
from lib.async_thread import run_noninterruptible_sync
from lib.db.models.api_call import ApiCall
from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from lib.db.repositories.production_binding import ProductionBindingIntegrityError
from lib.db.repositories.task_repo import TaskRepository
from lib.generation_queue import R2_SHOT_GENERATION_TASK_TYPE
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ProductionBindingTarget, ProductionMethod
from r2.contracts.production import ShotSpecV2
from r2.contracts.shot_generation import R2ShotGenerationTaskV1
from r2.m3.host_integration import compute_content_fingerprint
from r2.m3.render_plan import RenderedCutAsset
from r2.production.artifact_metadata import DependencySnapshot, R2ArtifactMetadata
from r2.production_intelligence.shot_identity import verify_task_evidence
from r2.production_intelligence.shot_profiles import PROFILES
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.execution_attempts import capability_resolver
from server.services.location_binding import BindingSourceConflictError
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.r2_shot_output import file_digest, output_path_for, sealed_output_digest

R2_SHOT_EPISODE = 1
SHOT_CONTRACT_TYPE = "ShotSpec"


class R2ShotApprovalRefused(ValueError):
    """The named task cannot become this target's shot candidate; ``code`` says why."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class R2ShotCut:
    """Every semantic and produced field Gate C needs, derived by the server."""

    target_ref: str
    content_fingerprint: str
    content_basis: ContentBasis
    direct_dependencies: list[DependencySnapshot]
    contract_version: int
    contract_schema_version: str
    produced: RenderedCutAsset


def binding_dependency(evidence: R2ShotGenerationTaskV1) -> DependencySnapshot:
    return DependencySnapshot(
        ref=f"r2-binding-snapshot:{evidence.target_id}",
        version=str(evidence.target_registry_version),
        fingerprint=evidence.binding_snapshot_digest,
    )


async def _task_evidence(
    session: AsyncSession, *, user_id: str, project_name: str, target_id: str, task_id: str
) -> R2ShotGenerationTaskV1:
    task = await TaskRepository(session).get(task_id)
    # A foreign or unknown task is indistinguishable from a missing one.
    if task is None or (task["user_id"], task["project_name"]) != (user_id, project_name):
        raise R2ShotApprovalRefused("r2_shot_task_not_found", 404)
    if task["task_type"] != R2_SHOT_GENERATION_TASK_TYPE or task["status"] != "succeeded":
        raise R2ShotApprovalRefused("r2_shot_task_not_succeeded")
    try:
        evidence = R2ShotGenerationTaskV1.model_validate(task["payload"])
        profile = PROFILES[evidence.execution_profile_ref]
        verify_task_evidence(evidence, profile)
    except (KeyError, ValueError) as exc:
        raise R2ShotApprovalRefused("r2_shot_task_evidence_invalid") from exc
    if (evidence.user_id, evidence.project_name, evidence.task_id) != (user_id, project_name, task_id):
        raise R2ShotApprovalRefused("r2_shot_task_evidence_invalid")
    if evidence.target_id != target_id:
        raise R2ShotApprovalRefused("r2_shot_task_target_mismatch")
    return evidence


async def _sealed_execution(session: AsyncSession, evidence: R2ShotGenerationTaskV1) -> tuple[str, str, Decimal, float]:
    """The execution ID, sealed output digest, ledger cost and wall time of the task's attempt."""
    attempt = await ExecutionAttemptRepository(session, capability_resolver=capability_resolver()).get_for_task_attempt(
        user_id=evidence.user_id, project_name=evidence.project_name, task_id=evidence.task_id, attempt_no=1
    )
    if attempt is None or attempt.request_digest != evidence.host_request_digest:
        raise R2ShotApprovalRefused("r2_shot_output_unsealed")
    digest = await sealed_output_digest(session, attempt)
    if digest is None:
        raise R2ShotApprovalRefused("r2_shot_output_unsealed")
    call = await session.scalar(
        select(ApiCall).where(
            ApiCall.user_id == evidence.user_id,
            ApiCall.project_name == evidence.project_name,
            ApiCall.execution_id == attempt.execution_id,
        )
    )
    cost = Decimal(str(call.cost_amount)) if call is not None else Decimal("0")
    wall = (call.duration_ms or 0) / 1000 if call is not None else 0.0
    return attempt.execution_id, digest, cost, wall


async def _current_shot(
    session_factory: async_sessionmaker[AsyncSession], project_dir: Path, evidence: R2ShotGenerationTaskV1
) -> ShotSpecV2:
    """The current Shot body, refused unless the target and binding snapshot are still the task's."""
    try:
        await CurrentLocationBindingSnapshotReader(
            session_factory=session_factory, project_dir=project_dir
        ).read_current(
            user_id=evidence.user_id,
            project_name=evidence.project_name,
            target_id=evidence.target_id,
            expected_snapshot_digest=evidence.binding_snapshot_digest,
        )
    except (ProductionBindingIntegrityError, BindingSourceConflictError) as exc:
        raise R2ShotApprovalRefused("r2_shot_binding_stale") from exc
    async with session_factory() as session:
        target = await TransactionBoundTargetAuthorityResolver(session).resolve_current(
            user_id=evidence.user_id,
            project_name=evidence.project_name,
            target_type=ProductionBindingTarget.SHOT,
            target_id=evidence.target_id,
        )
    if (
        target is None
        or not isinstance(target.target, ShotSpecV2)
        or (target.ref.registry_version, target.ref.version_digest)
        != (evidence.target_registry_version, evidence.target_digest)
    ):
        raise R2ShotApprovalRefused("r2_shot_binding_stale")
    return target.target


def _require_slot_owner(project_dir: Path, target_id: str) -> None:
    """The slot must be empty or already hold this target's ShotSpec metadata."""
    entry = ProjectArtifactManifestAdapter(project_dir).get_entry(ArtifactKey.episode_video(R2_SHOT_EPISODE, target_id))
    if entry is None:
        return
    if entry.r2 is None:
        raise R2ShotApprovalRefused("r2_shot_slot_owned")
    contract = R2ArtifactMetadata.model_validate(entry.r2).contract_ref
    if (contract.contract_type, contract.id) != (SHOT_CONTRACT_TYPE, target_id):
        raise R2ShotApprovalRefused("r2_shot_slot_owned")


async def prepare_r2_shot_cut(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    project_dir: Path,
    user_id: str,
    project_name: str,
    target_id: str,
    task_id: str,
) -> R2ShotCut:
    async with session_factory() as session:
        evidence = await _task_evidence(
            session, user_id=user_id, project_name=project_name, target_id=target_id, task_id=task_id
        )
        execution_id, sealed, cost, wall = await _sealed_execution(session, evidence)
    output = output_path_for(project_dir, task_id)
    if not output.is_file() or output.is_symlink():
        raise R2ShotApprovalRefused("r2_shot_output_missing")
    if await run_noninterruptible_sync(lambda: file_digest(output)) != sealed:
        raise R2ShotApprovalRefused("r2_shot_output_changed")
    shot = await _current_shot(session_factory, project_dir, evidence)
    await run_noninterruptible_sync(lambda: _require_slot_owner(project_dir, target_id))

    dependencies = [binding_dependency(evidence)]
    profile = PROFILES[evidence.execution_profile_ref]
    return R2ShotCut(
        target_ref=target_id,
        content_fingerprint=compute_content_fingerprint(shot, dependencies),
        content_basis=shot.content_basis,
        direct_dependencies=dependencies,
        contract_version=evidence.target_registry_version,
        contract_schema_version=shot.schema_version,
        produced=RenderedCutAsset(
            target_ref=target_id,
            method=ProductionMethod.GENERATED_VIDEO,
            path=output,
            sha256=sealed,
            duration_seconds=float(profile.duration_seconds),
            execution_fingerprint=evidence.host_request_digest,
            tool="provider",
            tool_version=evidence.execution_profile_ref,
            wall_time_seconds=wall,
            external_provider_cost=cost,
            source_master_refs=(),
            provider_execution_ref=f"m7:{execution_id}",
        ),
    )


__all__ = ["R2_SHOT_EPISODE", "R2ShotApprovalRefused", "R2ShotCut", "binding_dependency", "prepare_r2_shot_cut"]
