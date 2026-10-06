"""Transaction-bound spatial pair decisions over current target and source authority."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.spatial_pair import SpatialPairDecisionModel
from lib.db.repositories.production_binding import ProductionBindingRepository
from lib.db.repositories.spatial_pair import (
    SpatialPairIntegrityError,
    SpatialPairRepository,
    VerifiedPairCommandReceipt,
    verify_stored_pair_decision,
)
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.spatial_pair import PairAuthorizationV1, PairDecisionCommandV1, PairDecisionResultV1, PairDecisionV1
from r2.contracts.spatial_source import FrameDerivationReceiptV1
from r2.production_binding.digests import frame_source_claim_digest
from r2.spatial_pair.digests import (
    pair_authorization_digest,
    pair_command_digest,
    pair_decision_digest,
    scoped_pair_id,
)
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.location_binding import _claim_from_verified_frame
from server.services.master_authority import lock_current_master_rows
from server.services.spatial_frame_reader import SpatialFrameReader, VerifiedSpatialFrame


class PairAuthorizationDeniedError(PermissionError):
    """No trusted Human Showrunner authorization was available for this decision."""


class PairSourceConflictError(ValueError):
    """The command's binding or frame sources are no longer current and exact."""


class _MissingWinnerReceipt(Exception):
    pass


class PairDecisionAuthorizationPort(Protocol):
    async def authorize(
        self,
        *,
        session: AsyncSession,
        command: PairDecisionCommandV1,
        command_digest: str,
        frames: tuple[VerifiedSpatialFrame, VerifiedSpatialFrame],
    ) -> PairAuthorizationV1: ...


class DenyByDefaultPairAuthority:
    async def authorize(
        self,
        *,
        session: AsyncSession,
        command: PairDecisionCommandV1,
        command_digest: str,
        frames: tuple[VerifiedSpatialFrame, VerifiedSpatialFrame],
    ) -> PairAuthorizationV1:
        raise PairAuthorizationDeniedError("spatial pair approval requires a verified project-scoped grant")


class SpatialPairDecisionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        project_dir: Path,
        authority: PairDecisionAuthorizationPort | None = None,
    ) -> None:
        self._sessions = session_factory
        self._frames = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)
        self._authority = authority if authority is not None else DenyByDefaultPairAuthority()

    async def decide(self, command: PairDecisionCommandV1) -> VerifiedPairCommandReceipt:
        digest = pair_command_digest(command.model_dump(mode="json"))
        try:
            return await self._decide_once(command, digest, require_receipt=False)
        except IntegrityError as original:
            try:
                return await self._decide_once(command, digest, require_receipt=True)
            except _MissingWinnerReceipt:
                raise original from None

    async def _decide_once(
        self, command: PairDecisionCommandV1, digest: str, *, require_receipt: bool
    ) -> VerifiedPairCommandReceipt:
        async with self._sessions() as session, session.begin():
            repo = SpatialPairRepository(session)
            previous = await repo.get_command_receipt(
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
                raise PairSourceConflictError("pair target or Scene is stale or unavailable")
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
                raise PairSourceConflictError("pair binding is missing or stale")
            claims = {claim.receipt_id: claim for claim in binding.envelope.ordered_claims}
            if (
                len(claims) != 2
                or {view.receipt_id for view in command.views} != set(claims)
                or any(view.receipt_digest != claims[view.receipt_id].receipt_digest for view in command.views)
            ):
                raise PairSourceConflictError("pair views differ from the binding's two frame receipts")
            pair_id = scoped_pair_id(
                user_id=command.user_id, project_name=command.project_name, binding_id=command.binding_id
            )
            head = await repo.lock_pair_head(
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
                    raise PairSourceConflictError("pair frame differs from the binding's immutable claim")
                verified_frames.append(frame)
            frames = (verified_frames[0], verified_frames[1])
            if previous is not None:
                row = await session.get(
                    SpatialPairDecisionModel,
                    (command.user_id, command.project_name, pair_id, previous.result.pair_version),
                    populate_existing=True,
                )
                if row is None:
                    raise SpatialPairIntegrityError("pair replay decision is missing")
                verified = verify_stored_pair_decision(
                    row,
                    user_id=command.user_id,
                    project_name=command.project_name,
                    binding_id=command.binding_id,
                    expected_binding_version=command.expected_binding_version,
                    expected_envelope_digest=command.expected_envelope_digest,
                    expected_core_digest=command.expected_core_digest,
                    expected_target_ref=target.ref,
                    expected_scene_ref=target.scene.ref,
                )
                if (
                    verified.body.command != command
                    or verified.decision_digest != previous.result.decision_digest
                    or previous.result.pair_id != pair_id
                    or previous.result.command_digest != digest
                    or previous.result.decision != command.decision
                    or previous.result.binding_id != command.binding_id
                    or previous.result.binding_version != binding.body.version
                    or previous.result.binding_envelope_digest != binding.envelope_digest
                    or previous.result.binding_core_digest != binding.core_digest
                    or previous.result.target_ref != target.ref
                    or previous.result.scene_ref != target.scene.ref
                ):
                    raise SpatialPairIntegrityError("pair replay result differs from its decision or current source")
                return previous

            authorization = await self._authority.authorize(
                session=session, command=command, command_digest=digest, frames=frames
            )
            if (
                authorization.user_id != command.user_id
                or authorization.project_name != command.project_name
                or authorization.authenticated_principal != command.principal
                or authorization.authority_role != "HUMAN_SHOWRUNNER"
                or authorization.command_digest != digest
            ):
                raise PairAuthorizationDeniedError("pair authorization does not match the exact command")
            decision = PairDecisionV1(
                command=command,
                command_digest=digest,
                pair_id=pair_id,
                pair_version=(head.current_version or 0) + 1,
                reviewer_id=command.principal,
                authorization=authorization,
                authorization_digest=pair_authorization_digest(authorization.model_dump(mode="json")),
                decided_at=datetime.now(UTC),
            )
            row = await repo.append_decision(
                head=head,
                decision=decision,
                expected_binding_version=binding.body.version,
                expected_envelope_digest=binding.envelope_digest,
                expected_core_digest=binding.core_digest,
                expected_target_ref=target.ref,
                expected_scene_ref=target.scene.ref,
            )
            await repo.advance_head(
                head=head,
                decision=row,
                expected_binding_version=binding.body.version,
                expected_envelope_digest=binding.envelope_digest,
                expected_core_digest=binding.core_digest,
                expected_target_ref=target.ref,
                expected_scene_ref=target.scene.ref,
            )
            result = PairDecisionResultV1(
                command_digest=digest,
                pair_id=pair_id,
                pair_version=decision.pair_version,
                decision_digest=pair_decision_digest(decision.model_dump(mode="json")),
                decision=command.decision,
                binding_id=command.binding_id,
                binding_version=binding.body.version,
                binding_envelope_digest=binding.envelope_digest,
                binding_core_digest=binding.core_digest,
                scene_ref=target.scene.ref,
                target_ref=target.ref,
            )
            return await repo.record_command(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                command_id=command.command_id,
                result=result,
            )

    @staticmethod
    async def _receipt_hints(
        session: AsyncSession, command: PairDecisionCommandV1
    ) -> tuple[FrameDerivationReceiptV1, FrameDerivationReceiptV1]:
        repository = SpatialFrameReceiptRepository(session)
        found: list[FrameDerivationReceiptV1] = []
        for view in command.views:
            try:
                receipt = await repository.get_exact(
                    user_id=command.user_id, project_name=command.project_name, receipt_id=view.receipt_id
                )
            except ValueError as exc:
                raise PairSourceConflictError("pair frame receipt hint failed integrity verification") from exc
            if receipt is None or _receipt_digest(receipt) != view.receipt_digest:
                raise PairSourceConflictError("pair frame receipt hint is missing or changed")
            found.append(receipt)
        if found[0].identity.parent_artifact_key == found[1].identity.parent_artifact_key:
            raise PairSourceConflictError("pair frames must come from distinct parent artifacts")
        return found[0], found[1]


__all__ = [
    "DenyByDefaultPairAuthority",
    "PairAuthorizationDeniedError",
    "PairDecisionAuthorizationPort",
    "PairSourceConflictError",
    "SpatialPairDecisionService",
]
