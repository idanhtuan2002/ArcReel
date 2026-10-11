"""Transaction-bound V2 spatial pair decisions over exact frame review custody."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_binding import ProductionBindingRepository
from lib.db.repositories.spatial_pair_v2 import SpatialPairVersionedRepository
from lib.db.repositories.spatial_review import SpatialReviewRepository
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.review_evidence import ReviewFrameV1
from r2.contracts.spatial_pair import (
    PairAuthorizationV1,
    PairDecisionCommandV2,
    PairDecisionResultV2,
    PairDecisionV2,
)
from r2.contracts.spatial_source import FrameDerivationReceiptV1
from r2.governance.grant_transition import GrantScopeV1
from r2.production_binding.digests import frame_source_claim_digest
from r2.spatial_pair.digests import pair_authorization_digest, pair_command_digest_v2, scoped_pair_id
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.auth import CurrentUserInfo
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.location_binding import _claim_from_verified_frame
from server.services.master_authority import lock_current_master_rows
from server.services.spatial_frame_reader import SpatialFrameReader, VerifiedSpatialFrame
from server.services.spatial_pair_decision import PairAuthorizationDeniedError, PairSourceConflictError


class _MissingWinnerReceipt(Exception):
    pass


class SpatialPairDecisionServiceV2:
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

    async def decide(
        self, command: PairDecisionCommandV2, *, authenticated_user: CurrentUserInfo
    ) -> PairDecisionResultV2:
        """The caller must obtain authenticated_user from the interactive JWT dependency."""
        if (
            authenticated_user.id != command.user_id
            or authenticated_user.sub != command.principal
            or authenticated_user.role != "user"
        ):
            raise PairAuthorizationDeniedError("interactive principal differs from V2 pair command")
        digest = pair_command_digest_v2(command.model_dump(mode="json"))
        try:
            return await self._decide_once(command, digest, require_receipt=False)
        except IntegrityError as original:
            try:
                return await self._decide_once(command, digest, require_receipt=True)
            except _MissingWinnerReceipt:
                raise original from None

    async def _decide_once(
        self, command: PairDecisionCommandV2, digest: str, *, require_receipt: bool
    ) -> PairDecisionResultV2:
        async with self._sessions() as session, session.begin():
            repo = SpatialPairVersionedRepository(session)
            previous = await repo.get_command_receipt_v2(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                command_id=command.command_id,
                expected_command_digest=digest,
            )
            if require_receipt and previous is None:
                raise _MissingWinnerReceipt
            hints = await self._receipt_hints(session, command)
            target = await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id=command.user_id,
                project_name=command.project_name,
                target_type=ProductionBindingTarget.SHOT,
                target_id=command.expected_target_ref.target_id,
            )
            if (
                target is None
                or target.ref != command.expected_target_ref
                or target.scene is None
                or target.scene.ref != command.expected_scene_ref
                or not isinstance(target.target, ShotSpecV2)
                or not isinstance(target.scene.target, SceneSpec)
                or not target.scene.target.location_ref
            ):
                raise PairSourceConflictError("V2 pair target or Scene is stale or unavailable")
            binding = await ProductionBindingRepository(session).get_current_verified(
                user_id=command.user_id,
                project_name=command.project_name,
                binding_id=command.binding_id,
                expected_target_ref=target.ref,
                expected_scene_ref=target.scene.ref,
            )
            if (
                binding is None
                or binding.body.version != command.expected_binding_version
                or binding.envelope_digest != command.expected_envelope_digest
                or binding.core_digest != command.expected_core_digest
                or binding.body.semantic_ref != target.scene.target.location_ref
            ):
                raise PairSourceConflictError("V2 pair binding is missing or stale")
            claims = {claim.receipt_id: claim for claim in binding.envelope.ordered_claims}
            if (
                len(claims) != 2
                or {view.receipt_id for view in command.views} != set(claims)
                or any(view.receipt_digest != claims[view.receipt_id].receipt_digest for view in command.views)
            ):
                raise PairSourceConflictError("V2 pair views differ from current binding claims")
            pair_id = scoped_pair_id(
                user_id=command.user_id, project_name=command.project_name, binding_id=command.binding_id
            )
            locked = await repo.claim_pair_head(
                user_id=command.user_id, project_name=command.project_name, pair_id=pair_id
            )
            await lock_current_master_rows(
                session,
                user_id=command.user_id,
                project_name=command.project_name,
                artifact_keys=tuple(hint.identity.parent_artifact_key for hint in hints),
            )
            verified_frames: list[VerifiedSpatialFrame] = []
            for view, hint in zip(command.views, hints, strict=True):
                frame = await self._frames.read_locked(
                    session,
                    user_id=command.user_id,
                    project_name=command.project_name,
                    receipt_id=view.receipt_id,
                    expected_receipt_digest=view.receipt_digest,
                    expected_parent_artifact_key=hint.identity.parent_artifact_key,
                )
                claim = claims[view.receipt_id]
                claim_body = _claim_from_verified_frame(frame).model_dump(mode="json")
                if (
                    frame.receipt != hint
                    or claim_body != claim.model_dump(mode="json", exclude={"claim_digest"})
                    or frame_source_claim_digest(claim_body) != claim.claim_digest
                ):
                    raise PairSourceConflictError("V2 pair frame differs from current binding claim")
                verified_frames.append(frame)
            grant = await self._grants.require_current_locked(
                session,
                scope=GrantScopeV1(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    principal=command.principal,
                ),
            )
            if locked.current_version is not None:
                current = await repo.get_current_verified(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    binding_id=command.binding_id,
                    expected_binding_version=command.expected_binding_version,
                    expected_envelope_digest=command.expected_envelope_digest,
                    expected_core_digest=command.expected_core_digest,
                    expected_target_ref=target.ref,
                    expected_scene_ref=target.scene.ref,
                )
                if current is None or current.decision_digest != locked.current_decision_digest:
                    raise PairSourceConflictError("V2 pair current head differs from locked predecessor")
            if previous is None:
                previous = await repo.get_command_receipt_v2(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    principal=command.principal,
                    command_id=command.command_id,
                    expected_command_digest=digest,
                )
            if previous is not None:
                verified = await repo.verify_historical_receipt(hint=previous, command=command)
                self._require_same_pngs(verified.body.review_evidence.snapshot.frames, verified_frames)
                return previous.result
            review_repo = SpatialReviewRepository(session)
            evidence, evidence_digest = await review_repo.read_complete(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                session_id=command.review_session_id,
            )
            snapshot = evidence.snapshot
            if (
                evidence_digest != command.review_evidence_digest
                or snapshot.scene_ref != target.scene.ref
                or snapshot.target_ref != target.ref
                or snapshot.binding_id != command.binding_id
                or snapshot.binding_version != binding.body.version
                or snapshot.envelope_digest != binding.envelope_digest
                or snapshot.core_digest != binding.core_digest
                or [frame.receipt_id for frame in snapshot.frames] != [view.receipt_id for view in command.views]
                or [frame.receipt_digest for frame in snapshot.frames]
                != [view.receipt_digest for view in command.views]
            ):
                raise PairSourceConflictError("V2 review snapshot differs from current sources")
            self._require_same_pngs(snapshot.frames, verified_frames)
            now = await review_repo._now()
            authorization = PairAuthorizationV1(
                user_id=command.user_id,
                project_name=command.project_name,
                authenticated_principal=command.principal,
                authority_role="HUMAN_SHOWRUNNER",
                command_digest=digest,
                authorization_ref=grant.event_digest,
                authenticated_at=now,
            )
            decision = PairDecisionV2(
                decision_schema="r2.m8.spatial.pair.decision.v2",
                command=command,
                command_digest=digest,
                pair_id=pair_id,
                pair_version=(locked.current_version or 0) + 1,
                reviewer_id=command.principal,
                authorization=authorization,
                authorization_digest=pair_authorization_digest(authorization.model_dump(mode="json")),
                review_evidence=evidence,
                decided_at=now,
            )
            return await repo.append_reviewed_decision(locked=locked, decision=decision)

    @staticmethod
    def _require_same_pngs(
        frames: tuple[ReviewFrameV1, ReviewFrameV1], verified_frames: list[VerifiedSpatialFrame]
    ) -> None:
        if [frame.png_digest for frame in frames] != [
            "sha256:" + sha256(frame.png_bytes).hexdigest() for frame in verified_frames
        ]:
            raise PairSourceConflictError("V2 reviewed PNG bytes differ from current bytes")

    @staticmethod
    async def _receipt_hints(
        session: AsyncSession, command: PairDecisionCommandV2
    ) -> tuple[FrameDerivationReceiptV1, FrameDerivationReceiptV1]:
        repository = SpatialFrameReceiptRepository(session)
        found: list[FrameDerivationReceiptV1] = []
        for view in command.views:
            try:
                receipt = await repository.get_exact(
                    user_id=command.user_id, project_name=command.project_name, receipt_id=view.receipt_id
                )
            except ValueError as exc:
                raise PairSourceConflictError("V2 frame receipt hint failed integrity verification") from exc
            if receipt is None or _receipt_digest(receipt) != view.receipt_digest:
                raise PairSourceConflictError("V2 frame receipt hint is missing or changed")
            found.append(receipt)
        if found[0].identity.parent_artifact_key == found[1].identity.parent_artifact_key:
            raise PairSourceConflictError("V2 pair frames share one parent artifact")
        return found[0], found[1]


__all__ = ["SpatialPairDecisionServiceV2"]
