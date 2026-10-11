"""Create scoped frame review sessions from current, verified sources."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_binding import ProductionBindingRepository
from lib.db.repositories.spatial_review import SpatialReviewRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.review_evidence import ReviewFrameV1, ReviewSnapshotV1
from r2.governance.grant_transition import GrantScopeV1
from r2.production_binding.digests import frame_source_claim_digest, scoped_location_binding_id
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.location_binding import _claim_from_verified_frame
from server.services.master_authority import lock_current_master_rows
from server.services.spatial_frame_reader import SpatialFrameReader


class SpatialReviewSourceConflictError(ValueError):
    """A current target, binding or exact frame source cannot be established."""


class SpatialReviewSessionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        project_dir: Path,
        grants: CurrentShowrunnerGrantReader,
    ) -> None:
        self._sessions = session_factory
        self._frames = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)
        self._grants = grants

    async def create(self, *, user_id: str, project_name: str, principal: str, target_id: str) -> ReviewSnapshotV1:
        """The caller must supply a principal from an interactive JWT dependency."""

        async with self._sessions() as session, session.begin():
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
                raise SpatialReviewSourceConflictError("review target or Scene is unavailable")
            binding_id = scoped_location_binding_id(user_id=user_id, project_name=project_name, target_id=target_id)
            binding = await ProductionBindingRepository(session).get_current_verified(
                user_id=user_id,
                project_name=project_name,
                binding_id=binding_id,
                expected_target_ref=target.ref,
                expected_scene_ref=target.scene.ref,
            )
            if binding is None or binding.body.semantic_ref != target.scene.target.location_ref:
                raise SpatialReviewSourceConflictError("review binding is unavailable or stale")
            claims = binding.envelope.ordered_claims
            receipt_repository = SpatialFrameReceiptRepository(session)
            hints = []
            for claim in claims:
                try:
                    hint = await receipt_repository.get_exact(
                        user_id=user_id, project_name=project_name, receipt_id=claim.receipt_id
                    )
                except ValueError as exc:
                    raise SpatialReviewSourceConflictError("review frame receipt integrity failed") from exc
                if (
                    hint is None
                    or _receipt_digest(hint) != claim.receipt_digest
                    or hint.identity.parent_artifact_key != claim.parent_artifact_key
                ):
                    raise SpatialReviewSourceConflictError("review receipt differs from current binding")
                hints.append(hint)
            parent_keys = tuple(hint.identity.parent_artifact_key for hint in hints)
            if len(set(parent_keys)) != 2:
                raise SpatialReviewSourceConflictError("review receipts share one parent")
            await lock_current_master_rows(
                session, user_id=user_id, project_name=project_name, artifact_keys=parent_keys
            )
            frames = []
            for role, claim, hint in zip(("MASTER", "REVERSE"), claims, hints, strict=True):
                verified = await self._frames.read_locked(
                    session,
                    user_id=user_id,
                    project_name=project_name,
                    receipt_id=claim.receipt_id,
                    expected_receipt_digest=claim.receipt_digest,
                    expected_parent_artifact_key=hint.identity.parent_artifact_key,
                )
                claim_body = _claim_from_verified_frame(verified).model_dump(mode="json")
                if (
                    verified.receipt != hint
                    or claim_body != claim.model_dump(mode="json", exclude={"claim_digest"})
                    or frame_source_claim_digest(claim_body) != claim.claim_digest
                ):
                    raise SpatialReviewSourceConflictError("review frame differs from current binding claim")
                frames.append(
                    ReviewFrameV1(
                        role=role,
                        receipt_id=claim.receipt_id,
                        receipt_digest=claim.receipt_digest,
                        png_digest="sha256:" + sha256(verified.png_bytes).hexdigest(),
                    )
                )
            await self._grants.require_current_locked(
                session, scope=GrantScopeV1(user_id=user_id, project_name=project_name, principal=principal)
            )
            repository = SpatialReviewRepository(session)
            now = await repository._now()
            snapshot = ReviewSnapshotV1(
                session_id=uuid4().hex,
                user_id=user_id,
                project_name=project_name,
                principal=principal,
                scene_ref=target.scene.ref,
                target_ref=target.ref,
                binding_id=binding_id,
                binding_version=binding.body.version,
                envelope_digest=binding.envelope_digest,
                core_digest=binding.core_digest,
                frames=(frames[0], frames[1]),
                created_at=now,
                expires_at=now + timedelta(minutes=10),
            )
            await repository.create_session(snapshot)
            return snapshot


__all__ = ["SpatialReviewSessionService", "SpatialReviewSourceConflictError"]
