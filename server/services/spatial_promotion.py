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
from lib.db.repositories.spatial_promotion import SpatialPromotionRepository
from r2.advanced_creative.digests import digest_canonical, digest_command
from r2.advanced_creative.errors import (
    CandidateConflictError,
    CommandConflictError,
    ExplorationNotFoundError,
    PromotionBindingStaleError,
)
from r2.advanced_creative.exploration import PREVIEW_OPERATION, PREVIEW_TTL, uuid7
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    PromotionPreview,
    PromotionTarget,
    PromotionTargetKind,
)
from r2.contracts.production_binding_authority import FrameSourceClaimWithDigestV1
from r2.contracts.spatial_constraint import SpatialSourceBindingV1
from r2.contracts.spatial_promotion import SpatialPreviewBindingV2, SpatialPromotionPreviewV2
from r2.production_binding.digests import scoped_location_binding_id
from r2.production_binding.spatial_set import (
    SpatialConstraintError,
    derive_spatial_constraint_set,
    spatial_constraint_set_digest,
    spatial_constraint_set_id,
)
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.spatial_pair_current_v2 import CurrentApprovedSpatialPairReaderV2

SPATIAL_PREVIEW_RESULT = "SPATIAL_PREVIEW_V2"


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
    ) -> None:
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
            approval = await self._pairs.read_current_locked(
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


__all__ = ["SPATIAL_PREVIEW_RESULT", "SpatialPreviewCommand", "SpatialPromotionService"]
