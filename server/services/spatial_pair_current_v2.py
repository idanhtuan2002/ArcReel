"""Read an internal current V2 approval with signed grant and exact frame custody."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_binding import ProductionBindingRepository
from lib.db.repositories.spatial_pair_v2 import SpatialPairVersionedRepository, VerifiedPairDecisionV2
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.governance.grant_transition import GrantScopeV1
from r2.production_binding.digests import frame_source_claim_digest, scoped_location_binding_id
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.location_binding import _claim_from_verified_frame
from server.services.master_authority import lock_current_master_rows
from server.services.spatial_frame_reader import SpatialFrameReader


class SpatialPairV2UnavailableError(ValueError):
    """No current V2 approval has the requested grant and sources."""


class CurrentApprovedSpatialPairReaderV2:
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

    async def read_current(self, *, user_id: str, project_name: str, target_id: str) -> VerifiedPairDecisionV2:
        async with self._sessions() as session, session.begin():
            return await self.read_current_locked(
                session, user_id=user_id, project_name=project_name, target_id=target_id
            )

    async def read_current_locked(
        self, session: AsyncSession, *, user_id: str, project_name: str, target_id: str
    ) -> VerifiedPairDecisionV2:
        """Keep the target, pair, parent and grant locks through the caller's transaction."""
        if not session.in_transaction():
            raise RuntimeError("current V2 pair read requires a caller-owned transaction")
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
            raise SpatialPairV2UnavailableError("V2 pair target or Scene location is unavailable")
        binding_id = scoped_location_binding_id(user_id=user_id, project_name=project_name, target_id=target_id)
        binding = await ProductionBindingRepository(session).get_current_verified(
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_target_ref=target.ref,
            expected_scene_ref=target.scene.ref,
        )
        if binding is None or binding.body.semantic_ref != target.scene.target.location_ref:
            raise SpatialPairV2UnavailableError("V2 pair binding is unavailable or stale")
        pair_repo = SpatialPairVersionedRepository(session)
        current = await pair_repo.get_current_body_verified(
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_binding_version=binding.body.version,
            expected_envelope_digest=binding.envelope_digest,
            expected_core_digest=binding.core_digest,
            expected_target_ref=target.ref,
            expected_scene_ref=target.scene.ref,
        )
        if not isinstance(current, VerifiedPairDecisionV2) or current.body.command.decision != "APPROVE":
            raise SpatialPairV2UnavailableError("current pair is not a V2 approval")
        claims = {claim.receipt_id: claim for claim in binding.envelope.ordered_claims}
        views = current.body.command.views
        if len(claims) != 2 or {view.receipt_id for view in views} != set(claims):
            raise SpatialPairV2UnavailableError("V2 approval no longer matches its frame receipts")
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
                raise SpatialPairV2UnavailableError("V2 approval receipt differs from its binding")
            hints.append(hint)
        parent_keys = tuple(hint.identity.parent_artifact_key for hint in hints)
        if len(set(parent_keys)) != 2:
            raise SpatialPairV2UnavailableError("V2 approval receipts share one parent")
        await lock_current_master_rows(session, user_id=user_id, project_name=project_name, artifact_keys=parent_keys)
        review_frames = current.body.review_evidence.snapshot.frames
        for view, hint, review_frame in zip(views, hints, review_frames, strict=True):
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
                or review_frame.png_digest != "sha256:" + sha256(frame.png_bytes).hexdigest()
            ):
                raise SpatialPairV2UnavailableError("V2 approval frame differs from its immutable claim")
        grant_scope = GrantScopeV1(user_id=user_id, project_name=project_name, principal=current.body.command.principal)
        await self._grants.require_current_locked(session, scope=grant_scope)
        await self._grants.require_historical_issue_locked(
            session,
            scope=grant_scope,
            event_digest=current.body.authorization.authorization_ref,
            authenticated_at=current.body.authorization.authenticated_at,
        )
        await pair_repo.verify_review_consumption(current)
        return current


__all__ = ["CurrentApprovedSpatialPairReaderV2", "SpatialPairV2UnavailableError"]
