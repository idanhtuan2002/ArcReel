"""Read a current approved spatial pair with its target, binding and frame sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_binding import ProductionBindingRepository
from lib.db.repositories.spatial_pair import SpatialPairRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.spatial_pair import PairDecisionV1
from r2.production_binding.digests import frame_source_claim_digest, scoped_location_binding_id
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.location_binding import _claim_from_verified_frame
from server.services.master_authority import lock_current_master_rows
from server.services.spatial_frame_reader import SpatialFrameReader


class SpatialPairUnavailableError(ValueError):
    """There is no current approved pair with the requested sources."""


@dataclass(frozen=True)
class VerifiedApprovedSpatialPair:
    body: PairDecisionV1
    decision_digest: str


class CurrentApprovedSpatialPairReader:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession], project_dir: Path) -> None:
        self._sessions = session_factory
        self._frames = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)

    async def read_current(self, *, user_id: str, project_name: str, target_id: str) -> VerifiedApprovedSpatialPair:
        async with self._sessions() as session, session.begin():
            return await self.read_current_locked(
                session, user_id=user_id, project_name=project_name, target_id=target_id
            )

    async def read_current_locked(
        self, session: AsyncSession, *, user_id: str, project_name: str, target_id: str
    ) -> VerifiedApprovedSpatialPair:
        """Keep all pair and source locks in the caller's authority transaction."""
        if not session.in_transaction():
            raise RuntimeError("current pair read requires a caller-owned transaction")
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
            raise SpatialPairUnavailableError("pair target or Scene location is unavailable")
        binding_id = scoped_location_binding_id(user_id=user_id, project_name=project_name, target_id=target_id)
        binding = await ProductionBindingRepository(session).get_current_verified(
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_target_ref=target.ref,
            expected_scene_ref=target.scene.ref,
        )
        if binding is None or binding.body.semantic_ref != target.scene.target.location_ref:
            raise SpatialPairUnavailableError("pair binding is unavailable or stale")
        current = await SpatialPairRepository(session).get_current_verified(
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_binding_version=binding.body.version,
            expected_envelope_digest=binding.envelope_digest,
            expected_core_digest=binding.core_digest,
            expected_target_ref=target.ref,
            expected_scene_ref=target.scene.ref,
        )
        if current is None or current.body.command.decision != "APPROVE":
            raise SpatialPairUnavailableError("pair is not approved")

        claims = {claim.receipt_id: claim for claim in binding.envelope.ordered_claims}
        views = current.body.command.views
        if len(claims) != 2 or {view.receipt_id for view in views} != set(claims):
            raise SpatialPairUnavailableError("approved pair no longer matches the binding's frame receipts")
        receipts = SpatialFrameReceiptRepository(session)
        hints = []
        for view in views:
            claim = claims[view.receipt_id]
            hint = await receipts.get_exact(user_id=user_id, project_name=project_name, receipt_id=view.receipt_id)
            if (
                hint is None
                or _receipt_digest(hint) != view.receipt_digest
                or claim.receipt_digest != view.receipt_digest
                or hint.identity.parent_artifact_key != claim.parent_artifact_key
            ):
                raise SpatialPairUnavailableError("approved pair receipt differs from its current binding")
            hints.append(hint)
        parent_keys = tuple(hint.identity.parent_artifact_key for hint in hints)
        if len(set(parent_keys)) != 2:
            raise SpatialPairUnavailableError("approved pair receipts share one parent")
        await lock_current_master_rows(session, user_id=user_id, project_name=project_name, artifact_keys=parent_keys)
        for view, hint in zip(views, hints, strict=True):
            frame = await self._frames.read_locked(
                session,
                user_id=user_id,
                project_name=project_name,
                receipt_id=view.receipt_id,
                expected_receipt_digest=view.receipt_digest,
                expected_parent_artifact_key=hint.identity.parent_artifact_key,
            )
            claim = claims[view.receipt_id]
            body = _claim_from_verified_frame(frame).model_dump(mode="json")
            if (
                frame.receipt != hint
                or body != claim.model_dump(mode="json", exclude={"claim_digest"})
                or frame_source_claim_digest(body) != claim.claim_digest
            ):
                raise SpatialPairUnavailableError("approved pair frame differs from its immutable claim")
        return VerifiedApprovedSpatialPair(body=current.body, decision_digest=current.decision_digest)


__all__ = ["CurrentApprovedSpatialPairReader", "SpatialPairUnavailableError", "VerifiedApprovedSpatialPair"]
