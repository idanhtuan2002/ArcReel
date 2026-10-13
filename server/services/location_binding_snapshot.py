"""Read the exact current LOCATION binding snapshot from target and frame authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_binding import ProductionBindingIntegrityError, ProductionBindingRepository
from lib.db.repositories.spatial_constraint import SpatialConstraintSetIntegrityError, SpatialConstraintSetRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_binding_authority import (
    BindingSnapshotV1,
    FrameSourceClaimWithDigestV1,
    SnapshotBindingRefV1,
)
from r2.contracts.spatial_constraint import SpatialConstraintSetV1, SpatialSourceBindingV1
from r2.production_binding.digests import binding_snapshot_digest, frame_source_claim_digest, scoped_location_binding_id
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.location_binding import BindingSourceConflictError, _claim_from_verified_frame
from server.services.master_authority import lock_current_master_rows
from server.services.spatial_frame_reader import SpatialFrameReader


@dataclass(frozen=True)
class VerifiedLocationBindingSnapshot:
    body: BindingSnapshotV1
    digest: str
    spatial_set: SpatialConstraintSetV1 | None = None


def _source_identity(source: SpatialSourceBindingV1) -> tuple[object, ...]:
    return (
        source.frame_derivation_receipt_id,
        source.frame_derivation_receipt_digest,
        source.frame_content_digest,
        source.parent_artifact_key,
        source.parent_master_version,
        source.parent_candidate_id,
        source.parent_content_digest,
    )


def _claim_identity(claim: FrameSourceClaimWithDigestV1) -> tuple[object, ...]:
    return (
        claim.receipt_id,
        claim.receipt_digest,
        claim.frame_content_digest,
        claim.parent_artifact_key,
        claim.parent_master_version,
        claim.parent_candidate_id,
        claim.parent_content_digest,
    )


class CurrentLocationBindingSnapshotReader:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession], project_dir: Path) -> None:
        self._sessions = session_factory
        self._frames = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)

    async def read_current(
        self,
        *,
        user_id: str,
        project_name: str,
        target_id: str,
        expected_snapshot_digest: str | None = None,
    ) -> VerifiedLocationBindingSnapshot:
        async with self._sessions() as session, session.begin():
            return await self.read_in_session(
                session,
                user_id=user_id,
                project_name=project_name,
                target_id=target_id,
                expected_snapshot_digest=expected_snapshot_digest,
            )

    async def read_in_session(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        project_name: str,
        target_id: str,
        expected_snapshot_digest: str | None = None,
    ) -> VerifiedLocationBindingSnapshot:
        """Lock and verify the snapshot inside the caller's transaction; the caller commits."""
        target = await TransactionBoundTargetAuthorityResolver(session).resolve_current(
            user_id=user_id,
            project_name=project_name,
            target_type=ProductionBindingTarget.SHOT,
            target_id=target_id,
        )
        if (
            target is None
            or not isinstance(target.target, ShotSpecV2)
            or target.scene is None
            or not isinstance(target.scene.target, SceneSpec)
            or not target.scene.target.location_ref
        ):
            raise ProductionBindingIntegrityError("binding snapshot target or Scene location is unavailable")
        binding_id = scoped_location_binding_id(user_id=user_id, project_name=project_name, target_id=target_id)
        current = await ProductionBindingRepository(session).get_current_verified(
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_target_ref=target.ref,
            expected_scene_ref=target.scene.ref,
        )
        if current is None or current.body.semantic_ref != target.scene.target.location_ref:
            raise ProductionBindingIntegrityError("binding snapshot has no current Scene-bound LOCATION binding")

        claims = current.envelope.ordered_claims
        receipt_repository = SpatialFrameReceiptRepository(session)
        parent_keys: list[str] = []
        for claim in claims:
            try:
                hint = await receipt_repository.get_exact(
                    user_id=user_id, project_name=project_name, receipt_id=claim.receipt_id
                )
            except ValueError as exc:
                raise BindingSourceConflictError("binding snapshot receipt hint failed integrity verification") from exc
            if (
                hint is None
                or _receipt_digest(hint) != claim.receipt_digest
                or hint.identity.parent_artifact_key != claim.parent_artifact_key
            ):
                raise BindingSourceConflictError("binding snapshot receipt hint differs from immutable claim")
            parent_keys.append(hint.identity.parent_artifact_key)
        if len(set(parent_keys)) != 2:
            raise BindingSourceConflictError("binding snapshot receipts share one parent")
        await lock_current_master_rows(
            session, user_id=user_id, project_name=project_name, artifact_keys=tuple(parent_keys)
        )
        for claim in claims:
            frame = await self._frames.read_locked(
                session,
                user_id=user_id,
                project_name=project_name,
                receipt_id=claim.receipt_id,
                expected_receipt_digest=claim.receipt_digest,
                expected_parent_artifact_key=claim.parent_artifact_key,
            )
            body = _claim_from_verified_frame(frame).model_dump(mode="json")
            if (
                body != claim.model_dump(mode="json", exclude={"claim_digest"})
                or frame_source_claim_digest(body) != claim.claim_digest
            ):
                raise BindingSourceConflictError("binding snapshot frame differs from immutable claim")

        spatial_set = None
        envelope = current.envelope
        if envelope.spatial_set_id is not None and envelope.spatial_set_digest is not None:
            try:
                spatial_set = await SpatialConstraintSetRepository(session).get_verified(
                    user_id=user_id,
                    project_name=project_name,
                    set_id=envelope.spatial_set_id,
                    expected_digest=envelope.spatial_set_digest,
                    expected_binding_id=binding_id,
                )
            except SpatialConstraintSetIntegrityError as exc:
                raise ProductionBindingIntegrityError("binding snapshot spatial set failed verification") from exc
            if sorted(map(_source_identity, spatial_set.ordered_sources)) != sorted(map(_claim_identity, claims)):
                raise BindingSourceConflictError("binding snapshot spatial set sources differ from its frame claims")

        snapshot = BindingSnapshotV1(
            user_id=user_id,
            project_name=project_name,
            ordered_bindings=(
                SnapshotBindingRefV1(
                    binding_id=binding_id,
                    version=current.body.version,
                    envelope_digest=current.envelope_digest,
                ),
            ),
            target_versions=(target.scene.ref, target.ref),
        )
        digest = binding_snapshot_digest(snapshot.model_dump(mode="json"))
        if expected_snapshot_digest is not None and digest != expected_snapshot_digest:
            raise ProductionBindingIntegrityError("binding snapshot digest is stale")
        return VerifiedLocationBindingSnapshot(body=snapshot, digest=digest, spatial_set=spatial_set)


__all__ = ["CurrentLocationBindingSnapshotReader", "VerifiedLocationBindingSnapshot"]
