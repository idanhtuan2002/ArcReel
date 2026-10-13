"""Typed spatial promotion: preview a constraint set for one current LOCATION binding version.

The preview runs in one transaction under the spec's lock order: the M8 command key and candidate
head, then (inside the V2 pair reader) the target, binding, pair, source masters and frames. It
derives the constraint set from the exact revision, the selected VISIBLE assertions and the
approved pair's MASTER/REVERSE views; the client supplies only identities and a selection.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.base import utc_now
from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.production_binding import ProductionBindingRepository
from lib.db.repositories.spatial_constraint import SpatialConstraintSetRepository
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError
from lib.db.repositories.spatial_pair_v2 import VerifiedPairDecisionV2
from lib.db.repositories.spatial_promotion import SpatialPromotionRepository
from r2.advanced_creative.digests import digest_canonical, digest_command
from r2.advanced_creative.errors import (
    CandidateConflictError,
    CommandConflictError,
    ExplorationNotFoundError,
    PromotionBindingStaleError,
    PromotionTargetUnavailableError,
)
from r2.advanced_creative.exploration import PREVIEW_OPERATION, PREVIEW_TTL, uuid7
from r2.advanced_creative.promotion import PROMOTE_OPERATION
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    PromotionAuthorization,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
    PromotionTargetKind,
)
from r2.contracts.production_binding_authority import FrameSourceClaimWithDigestV1
from r2.contracts.spatial_constraint import SpatialSourceBindingV1
from r2.contracts.spatial_promotion import (
    SpatialPreviewBindingV2,
    SpatialPromotionPreviewV2,
    SpatialPromotionReceiptV2,
    SpatialPromotionResultV2,
    binding_version_ref,
)
from r2.production_binding.digests import binding_envelope_digest, scoped_location_binding_id
from r2.production_binding.spatial_promotion import spatial_receipt_v2_digest
from r2.production_binding.spatial_set import (
    SpatialConstraintError,
    derive_spatial_constraint_set,
    spatial_constraint_set_digest,
    spatial_constraint_set_id,
)
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.spatial_pair_current_v2 import CurrentApprovedSpatialPairReaderV2, SpatialPairV2UnavailableError

SPATIAL_PREVIEW_RESULT = "SPATIAL_PREVIEW_V2"
SPATIAL_PROMOTION_RESULT = "SPATIAL_PROMOTION_V2"


@dataclass(frozen=True)
class SpatialPreviewCommand:
    user_id: str
    project_name: str
    candidate_id: str
    candidate_revision: int
    target_id: str
    expected_binding_version: int
    selected_assertion_ids: tuple[str, ...]
    command_id: str


def _source(view: str, claim: FrameSourceClaimWithDigestV1) -> SpatialSourceBindingV1:
    return SpatialSourceBindingV1(
        view=view,  # type: ignore[arg-type]
        parent_artifact_key=claim.parent_artifact_key,
        parent_master_version=claim.parent_master_version,
        parent_candidate_id=claim.parent_candidate_id,
        parent_content_digest=claim.parent_content_digest,
        frame_derivation_receipt_id=claim.receipt_id,
        frame_derivation_receipt_digest=claim.receipt_digest,
        frame_candidate_id=claim.frame_candidate_id,
        frame_content_digest=claim.frame_content_digest,
    )


class SpatialPromotionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        project_dir: Path,
        grants: CurrentShowrunnerGrantReader,
        clock: Callable[[], datetime] = utc_now,
        new_id: Callable[[], str] = uuid7,
        sidecars_for: Callable[[AsyncSession], SpatialPromotionRepository] = SpatialPromotionRepository,
    ) -> None:
        self._sidecars_for = sidecars_for
        self._sessions = session_factory
        self._pairs = CurrentApprovedSpatialPairReaderV2(
            session_factory=session_factory, project_dir=project_dir, grants=grants
        )
        self._clock = clock
        self._new_id = new_id

    async def create_preview(self, command: SpatialPreviewCommand) -> SpatialPromotionPreviewV2:
        scope = {
            "user_id": command.user_id,
            "project_name": command.project_name,
            "actor_scope": command.user_id,
            "operation": PREVIEW_OPERATION,
            "command_id": command.command_id,
        }
        command_digest = digest_command(
            PREVIEW_OPERATION,
            command.user_id,
            command.project_name,
            command.user_id,
            {
                "spatial_preview": {
                    "candidate_id": command.candidate_id,
                    "candidate_revision": command.candidate_revision,
                    "target_id": command.target_id,
                    "expected_binding_version": command.expected_binding_version,
                    "selected_assertion_ids": list(command.selected_assertion_ids),
                }
            },
        )
        async with self._sessions() as session, session.begin():
            store = ExplorationRepository(session)
            replay = await self._replayed(session, store, scope, command_digest)
            if replay is not None:
                return replay
            await store.lock_command_key(**scope)
            replay = await self._replayed(session, store, scope, command_digest)
            if replay is not None:
                return replay
            head = await store.get_head(
                user_id=command.user_id,
                project_name=command.project_name,
                candidate_id=command.candidate_id,
                for_update=True,
            )
            revision = await store.get_exact(
                user_id=command.user_id,
                project_name=command.project_name,
                candidate_id=command.candidate_id,
                revision=command.candidate_revision,
            )
            if head is None or revision is None:
                raise ExplorationNotFoundError("no such revision in this scope")
            approval = await self._current_approval(
                session, user_id=command.user_id, project_name=command.project_name, target_id=command.target_id
            )
            binding_id = scoped_location_binding_id(
                user_id=command.user_id, project_name=command.project_name, target_id=command.target_id
            )
            pair_command = approval.body.command
            current = await ProductionBindingRepository(session).get_current_verified(
                user_id=command.user_id,
                project_name=command.project_name,
                binding_id=binding_id,
                expected_target_ref=pair_command.expected_target_ref,
                expected_scene_ref=pair_command.expected_scene_ref,
            )
            if current is None or current.body.version != command.expected_binding_version:
                raise PromotionBindingStaleError("the binding version moved since it was read")
            claims = {claim.receipt_id: claim for claim in current.envelope.ordered_claims}
            views = {view.role: view.receipt_id for view in pair_command.views}
            try:
                proposal = derive_spatial_constraint_set(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    binding_id=binding_id,
                    revision=revision,
                    selected_assertion_ids=command.selected_assertion_ids,
                    pair_id=approval.body.pair_id,
                    pair_version=approval.body.pair_version,
                    pair_decision_digest=approval.decision_digest,
                    ordered_sources=(
                        _source("MASTER", claims[views["MASTER"]]),
                        _source("REVERSE", claims[views["REVERSE"]]),
                    ),
                )
            except SpatialConstraintError as exc:
                raise CandidateConflictError(f"the selection cannot become production constraints: {exc}") from exc
            proposal_digest = spatial_constraint_set_digest(proposal.model_dump(mode="json"))
            issued_at = self._clock()
            impact = CanonicalJsonObject.model_validate(
                {
                    "binding_version": {"from": current.body.version, "to": current.body.version + 1},
                    "constraint_set_id": spatial_constraint_set_id(proposal_digest),
                }
            )
            base = PromotionPreview(
                preview_id=self._new_id(),
                preview_command_id=command.command_id,
                project_name=command.project_name,
                candidate_id=command.candidate_id,
                candidate_revision=command.candidate_revision,
                candidate_payload_digest=revision.payload_digest,
                target=PromotionTarget(
                    kind=PromotionTargetKind.PRODUCTION_BINDING,
                    target_ref=binding_id,
                    expected_target_version=current.body.version,
                ),
                expected_master_id=None,
                expected_master_digest=None,
                impact=impact,
                impact_digest=digest_canonical(impact),
                authorization_scope=command.user_id,
                issued_at=issued_at,
                expires_at=issued_at + PREVIEW_TTL,
            )
            await store.stage_preview(user_id=command.user_id, preview=base)
            preview = await SpatialPromotionRepository(session).stage_preview_binding(
                user_id=command.user_id,
                base_preview=base,
                binding=SpatialPreviewBindingV2(
                    schema_version="2",
                    binding_id=binding_id,
                    expected_binding_version=current.body.version,
                    binding_envelope_digest=current.envelope_digest,
                    target_ref=pair_command.expected_target_ref,
                    selected_assertion_ids=command.selected_assertion_ids,
                    proposal=proposal,
                    proposal_digest=proposal_digest,
                    pair_id=approval.body.pair_id,
                    pair_version=approval.body.pair_version,
                    pair_decision_digest=approval.decision_digest,
                ),
            )
            _, v2_digest = await SpatialPromotionRepository(session).get_preview_verified(
                user_id=command.user_id, base_preview=base
            )
            await store.record_command(
                **scope,
                command_digest=command_digest,
                result_kind=SPATIAL_PREVIEW_RESULT,
                result_ref=base.preview_id,
                result_digest=v2_digest,
                created_at=issued_at,
            )
            return preview

    async def promote(
        self,
        *,
        user_id: str,
        project_name: str,
        authorization: PromotionAuthorization,
        expected_candidate_head_version: int,
    ) -> SpatialPromotionReceiptV2:
        """Promote one previewed constraint set into binding version N+1 in one transaction.

        Lock order: M8 command key, candidate head, preview, then (inside the V2 pair reader) the
        target, binding, pair, masters and frames, then the binding head. Every bound identity is
        rechecked and the set is derived again; the set, the binding version, the authorization,
        the receipt with its result sidecar and the command receipt commit together.
        """
        if authorization.project_name != project_name or authorization.actor_id != user_id:
            raise ExplorationNotFoundError("the authorization is not in this scope")
        scope = {
            "user_id": user_id,
            "project_name": project_name,
            "actor_scope": authorization.actor_scope,
            "operation": PROMOTE_OPERATION,
            "command_id": authorization.command_id,
        }
        command_digest = digest_command(
            PROMOTE_OPERATION,
            user_id,
            project_name,
            authorization.actor_scope,
            {"authorization": authorization, "expected_candidate_head_version": expected_candidate_head_version},
        )
        async with self._sessions() as session, session.begin():
            store = ExplorationRepository(session)
            sidecars = self._sidecars_for(session)
            replay = await self._replayed_promotion(store, sidecars, scope, command_digest)
            if replay is not None:
                return replay
            await store.lock_command_key(**scope)
            replay = await self._replayed_promotion(store, sidecars, scope, command_digest)
            if replay is not None:
                return replay
            found = await store.get_preview(
                user_id=user_id, project_name=project_name, preview_id=authorization.preview_id
            )
            if found is None:
                raise ExplorationNotFoundError("no such preview in this scope")
            head = await store.get_head(
                user_id=user_id, project_name=project_name, candidate_id=found[0].candidate_id, for_update=True
            )
            locked = await store.get_preview(
                user_id=user_id, project_name=project_name, preview_id=authorization.preview_id, for_update=True
            )
            if head is None or locked is None:
                raise ExplorationNotFoundError("no such preview in this scope")
            if locked[0].target.kind is not PromotionTargetKind.PRODUCTION_BINDING:
                raise PromotionTargetUnavailableError("this endpoint promotes only spatial binding previews")
            preview, preview_digest = await sidecars.get_preview_verified(user_id=user_id, base_preview=locked[0])
            base = preview.base_preview
            if head.head_version != expected_candidate_head_version:
                raise CandidateConflictError("the candidate head moved; reload it and authorize again")
            now = self._clock()
            if (
                authorization.preview_digest != preview_digest
                or authorization.actor_scope != base.authorization_scope
                or now >= base.expires_at
            ):
                raise PromotionBindingStaleError("the authorization does not bind this current, unexpired preview")
            revision = await store.get_exact(
                user_id=user_id,
                project_name=project_name,
                candidate_id=base.candidate_id,
                revision=base.candidate_revision,
            )
            if revision is None or revision.payload_digest != base.candidate_payload_digest:
                raise PromotionBindingStaleError("the previewed revision no longer matches")
            bound = preview.binding
            approval = await self._current_approval(
                session, user_id=user_id, project_name=project_name, target_id=bound.target_ref.target_id
            )
            if (approval.body.pair_id, approval.body.pair_version, approval.decision_digest) != (
                bound.pair_id,
                bound.pair_version,
                bound.pair_decision_digest,
            ):
                raise PromotionBindingStaleError("the pair approval changed since the preview")
            pair_command = approval.body.command
            bindings = ProductionBindingRepository(session)
            current = await bindings.get_current_verified(
                user_id=user_id,
                project_name=project_name,
                binding_id=bound.binding_id,
                expected_target_ref=pair_command.expected_target_ref,
                expected_scene_ref=pair_command.expected_scene_ref,
            )
            if (
                current is None
                or current.body.version != bound.expected_binding_version
                or current.envelope_digest != bound.binding_envelope_digest
            ):
                raise PromotionBindingStaleError("the binding version moved since the preview")
            claims = {claim.receipt_id: claim for claim in current.envelope.ordered_claims}
            views = {view.role: view.receipt_id for view in pair_command.views}
            try:
                derived = derive_spatial_constraint_set(
                    user_id=user_id,
                    project_name=project_name,
                    binding_id=bound.binding_id,
                    revision=revision,
                    selected_assertion_ids=bound.selected_assertion_ids,
                    pair_id=approval.body.pair_id,
                    pair_version=approval.body.pair_version,
                    pair_decision_digest=approval.decision_digest,
                    ordered_sources=(
                        _source("MASTER", claims[views["MASTER"]]),
                        _source("REVERSE", claims[views["REVERSE"]]),
                    ),
                )
            except SpatialConstraintError as exc:
                raise PromotionBindingStaleError("the previewed constraints can no longer be derived") from exc
            if derived != bound.proposal:
                raise PromotionBindingStaleError("the derived constraint set differs from the preview")

            set_id = await SpatialConstraintSetRepository(session).stage(derived, now=now)
            successor = await bindings.append_spatial_successor(
                current=current,
                spatial_set_id=set_id,
                spatial_set_digest=bound.proposal_digest,
                expected_target_ref=pair_command.expected_target_ref,
                expected_scene_ref=pair_command.expected_scene_ref,
            )
            authorization_digest = await store.stage_authorization(user_id=user_id, authorization=authorization)
            receipt = PromotionReceipt(
                receipt_id=self._new_id(),
                command_id=authorization.command_id,
                project_name=project_name,
                preview_digest=preview_digest,
                candidate_id=base.candidate_id,
                candidate_revision=base.candidate_revision,
                target=base.target,
                result_artifact_ref=binding_version_ref(bound.binding_id, successor.body.version),
                result_master_id=None,
                result_digest=binding_envelope_digest(successor.envelope.model_dump(mode="json")),
                promoted_at=now,
            )
            await store.stage_promotion_receipt(
                user_id=user_id, receipt=receipt, preview_id=base.preview_id, authorization_digest=authorization_digest
            )
            promoted = await sidecars.stage_result(
                user_id=user_id,
                base_receipt=receipt,
                result=SpatialPromotionResultV2(
                    schema_version="2",
                    binding_id=bound.binding_id,
                    binding_version=successor.body.version,
                    binding_envelope_digest=receipt.result_digest,
                    constraint_set_id=set_id,
                    constraint_set_digest=bound.proposal_digest,
                ),
            )
            await store.record_command(
                **scope,
                command_digest=command_digest,
                result_kind=SPATIAL_PROMOTION_RESULT,
                result_ref=receipt.receipt_id,
                result_digest=spatial_receipt_v2_digest(promoted.model_dump(mode="json")),
                created_at=now,
            )
            return promoted

    async def _current_approval(
        self, session: AsyncSession, *, user_id: str, project_name: str, target_id: str
    ) -> VerifiedPairDecisionV2:
        """The current V2 APPROVE of the current binding version, read under its locks.

        An approval binds one binding version, so after a promotion the next one needs a fresh
        approval; any approval that does not verify against the current version is stale here.
        """
        try:
            return await self._pairs.read_current_locked(
                session, user_id=user_id, project_name=project_name, target_id=target_id
            )
        except (SpatialPairV2UnavailableError, SpatialPairIntegrityError) as exc:
            raise PromotionBindingStaleError("no current pair approval binds this binding version") from exc

    @staticmethod
    async def _replayed_promotion(
        store: ExplorationRepository,
        sidecars: SpatialPromotionRepository,
        scope: dict[str, str],
        command_digest: str,
    ) -> SpatialPromotionReceiptV2 | None:
        recorded = await store.get_command_receipt(**scope)
        if recorded is None:
            return None
        if recorded.command_digest != command_digest or recorded.result_kind != SPATIAL_PROMOTION_RESULT:
            raise CommandConflictError("this command id was already used for a different request")
        base = await store.get_promotion_receipt(
            user_id=scope["user_id"], project_name=scope["project_name"], command_id=scope["command_id"]
        )
        if base is None:
            raise CommandConflictError("the recorded spatial promotion is missing")
        receipt = await sidecars.get_receipt_verified(user_id=scope["user_id"], base_receipt=base)
        if spatial_receipt_v2_digest(receipt.model_dump(mode="json")) != recorded.result_digest:
            raise CommandConflictError("the recorded spatial promotion no longer matches its command")
        return receipt

    @staticmethod
    async def _replayed(
        session: AsyncSession, store: ExplorationRepository, scope: dict[str, str], command_digest: str
    ) -> SpatialPromotionPreviewV2 | None:
        receipt = await store.get_command_receipt(**scope)
        if receipt is None:
            return None
        if receipt.command_digest != command_digest or receipt.result_kind != SPATIAL_PREVIEW_RESULT:
            raise CommandConflictError("this command id was already used for a different request")
        found = await store.get_preview(
            user_id=scope["user_id"], project_name=scope["project_name"], preview_id=receipt.result_ref
        )
        if found is None:
            raise CommandConflictError("the recorded spatial preview is missing")
        preview, v2_digest = await SpatialPromotionRepository(session).get_preview_verified(
            user_id=scope["user_id"], base_preview=found[0]
        )
        if v2_digest != receipt.result_digest:
            raise CommandConflictError("the recorded spatial preview no longer matches its command")
        return preview


__all__ = ["SPATIAL_PREVIEW_RESULT", "SPATIAL_PROMOTION_RESULT", "SpatialPreviewCommand", "SpatialPromotionService"]
