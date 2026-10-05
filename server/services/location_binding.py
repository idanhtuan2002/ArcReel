"""Create the first LOCATION binding from current Take targets and verified source frames."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.production_binding import (
    ProductionBindingAlreadyCurrentError,
    ProductionBindingIntegrityError,
    ProductionBindingRepository,
    VerifiedBindingCommandReceipt,
)
from lib.db.repositories.spatial_source import SpatialFrameReceiptRepository, _receipt_digest
from r2.contracts.enums import ProductionBindingRole, ProductionBindingTarget
from r2.contracts.preparation import ProductionBinding
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_binding_authority import (
    BindingCreateCommandV1,
    BindingCreateResultV1,
    BindingEnvelopeV1,
    FrameSourceClaimV1,
    FrameSourceClaimWithDigestV1,
)
from r2.contracts.spatial_source import FrameDerivationReceiptV1
from r2.production_binding.digests import (
    binding_body_digest,
    binding_create_command_digest,
    binding_envelope_digest,
    frame_source_claim_digest,
    scoped_location_binding_id,
    source_group_ref,
)
from r2.target_registry.resolver import TransactionBoundTargetAuthorityResolver
from server.services.master_authority import lock_current_master_rows
from server.services.spatial_frame_reader import SpatialFrameReader, VerifiedSpatialFrame


class BindingSourceConflictError(ValueError):
    """A pinned source receipt or parent changed before the binding commit."""


class _MissingWinnerReceipt(Exception):
    pass


def _claim_from_verified_frame(frame: VerifiedSpatialFrame) -> FrameSourceClaimV1:
    receipt = frame.receipt
    identity = receipt.identity
    return FrameSourceClaimV1(
        receipt_id=receipt.frame_candidate_id,
        receipt_digest=frame.receipt_digest,
        frame_candidate_id=receipt.frame_candidate_id,
        frame_content_digest=identity.frame_content_digest,
        frame_probe_digest=receipt.frame_probe_digest,
        frame_byte_size=receipt.frame_byte_size,
        parent_artifact_key=identity.parent_artifact_key,
        parent_master_version=identity.parent_master_version,
        parent_candidate_id=identity.parent_candidate_id,
        parent_content_digest=identity.parent_content_digest,
        decoded_frame_index=identity.decoded_frame_index,
        recipe_version=identity.recipe_version,
        decoder_identity=identity.decoder_identity,
    )


class LocationBindingCreationService:
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession], project_dir: Path) -> None:
        self._sessions = session_factory
        self._frames = SpatialFrameReader(session_factory=session_factory, project_dir=project_dir)

    async def create(self, command: BindingCreateCommandV1) -> VerifiedBindingCommandReceipt:
        digest = binding_create_command_digest(command.model_dump(mode="json"))
        try:
            return await self._create_once(command, digest, require_receipt=False)
        except (IntegrityError, ProductionBindingAlreadyCurrentError) as original:
            try:
                return await self._create_once(command, digest, require_receipt=True)
            except _MissingWinnerReceipt:
                raise original from None

    async def _create_once(
        self, command: BindingCreateCommandV1, digest: str, *, require_receipt: bool
    ) -> VerifiedBindingCommandReceipt:
        async with self._sessions() as session, session.begin():
            repo = ProductionBindingRepository(session)
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
            verified_target = await TransactionBoundTargetAuthorityResolver(session).resolve_current(
                user_id=command.user_id,
                project_name=command.project_name,
                target_type=ProductionBindingTarget.SHOT,
                target_id=command.expected_target_ref.target_id,
            )
            if (
                verified_target is None
                or verified_target.ref != command.expected_target_ref
                or not isinstance(verified_target.target, ShotSpecV2)
                or verified_target.scene is None
                or not isinstance(verified_target.scene.target, SceneSpec)
                or not verified_target.scene.target.location_ref
            ):
                raise ProductionBindingIntegrityError("binding target or Scene location is stale or unavailable")
            scene_ref = verified_target.scene.ref
            location_ref = verified_target.scene.target.location_ref
            binding_id = scoped_location_binding_id(
                user_id=command.user_id,
                project_name=command.project_name,
                target_id=command.expected_target_ref.target_id,
            )
            if previous is not None:
                current = await repo.get_current_verified(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    binding_id=binding_id,
                    expected_target_ref=verified_target.ref,
                    expected_scene_ref=scene_ref,
                )
                if (
                    current is None
                    or previous.result.binding_id != binding_id
                    or previous.result.binding_version != current.body.version
                    or previous.result.envelope_digest != current.envelope_digest
                    or previous.result.target_ref != verified_target.ref
                    or current.body.semantic_ref != location_ref
                ):
                    raise ProductionBindingIntegrityError("binding replay receipt is not current")
                frames = await self._read_locked_frames(session, command, hints)
                claims = self._claims(frames)
                if tuple(current.envelope.ordered_claims) != claims:
                    raise BindingSourceConflictError("binding replay sources differ from current receipts")
                return previous

            head = await repo.lock_binding_head(
                user_id=command.user_id, project_name=command.project_name, binding_id=binding_id
            )
            frames = await self._read_locked_frames(session, command, hints)
            claims = self._claims(frames)
            frame_ids = [claim.frame_candidate_id for claim in claims]
            body = ProductionBinding(
                id=binding_id,
                schema_version="1",
                version=1,
                target_type=ProductionBindingTarget.SHOT,
                target_id=verified_target.ref.target_id,
                semantic_ref=location_ref,
                production_ref=source_group_ref(
                    user_id=command.user_id, project_name=command.project_name, frame_candidate_ids=frame_ids
                ),
                role=ProductionBindingRole.LOCATION,
                asset_refs=frame_ids,
                variant_ref=None,
                state_ref=None,
            )
            envelope = BindingEnvelopeV1(
                user_id=command.user_id,
                project_name=command.project_name,
                binding_id=binding_id,
                binding_version=1,
                binding_body_digest=binding_body_digest(body),
                scene_ref=scene_ref,
                target_ref=verified_target.ref,
                ordered_claims=claims,
                spatial_set_id=None,
                spatial_set_digest=None,
            )
            version = await repo.append_first_version(head=head, body=body, envelope=envelope)
            await repo.advance_first_head(
                head=head,
                version=version,
                expected_target_ref=verified_target.ref,
                expected_scene_ref=scene_ref,
            )
            return await repo.record_command(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                command_id=command.command_id,
                result=BindingCreateResultV1(
                    command_digest=digest,
                    binding_id=binding_id,
                    binding_version=1,
                    envelope_digest=binding_envelope_digest(envelope.model_dump(mode="json")),
                    target_ref=verified_target.ref,
                ),
            )

    @staticmethod
    async def _receipt_hints(
        session: AsyncSession, command: BindingCreateCommandV1
    ) -> tuple[FrameDerivationReceiptV1, FrameDerivationReceiptV1]:
        repository = SpatialFrameReceiptRepository(session)
        found: list[FrameDerivationReceiptV1] = []
        for expected in command.ordered_frame_receipts:
            try:
                receipt = await repository.get_exact(
                    user_id=command.user_id, project_name=command.project_name, receipt_id=expected.receipt_id
                )
            except ValueError as exc:
                raise BindingSourceConflictError("binding frame receipt hint failed integrity verification") from exc
            if receipt is None or _receipt_digest(receipt) != expected.receipt_digest:
                raise BindingSourceConflictError("binding frame receipt hint is missing or changed")
            found.append(receipt)
        if found[0].identity.parent_artifact_key == found[1].identity.parent_artifact_key:
            raise BindingSourceConflictError("binding frames must come from distinct parent artifacts")
        return found[0], found[1]

    async def _read_locked_frames(
        self,
        session: AsyncSession,
        command: BindingCreateCommandV1,
        hints: tuple[FrameDerivationReceiptV1, FrameDerivationReceiptV1],
    ) -> tuple[VerifiedSpatialFrame, VerifiedSpatialFrame]:
        await lock_current_master_rows(
            session,
            user_id=command.user_id,
            project_name=command.project_name,
            artifact_keys=tuple(hint.identity.parent_artifact_key for hint in hints),
        )
        found: list[VerifiedSpatialFrame] = []
        for expected, hint in zip(command.ordered_frame_receipts, hints, strict=True):
            verified = await self._frames.read_locked(
                session,
                user_id=command.user_id,
                project_name=command.project_name,
                receipt_id=expected.receipt_id,
                expected_receipt_digest=expected.receipt_digest,
                expected_parent_artifact_key=hint.identity.parent_artifact_key,
            )
            if verified.receipt != hint:
                raise BindingSourceConflictError("binding frame receipt changed after the unlocked hint")
            found.append(verified)
        return found[0], found[1]

    @staticmethod
    def _claims(
        frames: tuple[VerifiedSpatialFrame, VerifiedSpatialFrame],
    ) -> tuple[FrameSourceClaimWithDigestV1, FrameSourceClaimWithDigestV1]:
        claims: list[FrameSourceClaimWithDigestV1] = []
        for frame in frames:
            body = _claim_from_verified_frame(frame).model_dump(mode="json")
            claims.append(
                FrameSourceClaimWithDigestV1.model_validate(body | {"claim_digest": frame_source_claim_digest(body)})
            )
        return claims[0], claims[1]


__all__ = ["BindingSourceConflictError", "LocationBindingCreationService"]
