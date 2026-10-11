"""Verify a stored V2 spatial pair decision and its scoped review custody."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.spatial_pair import (
    SpatialPairCommandModel,
    SpatialPairDecisionModel,
    SpatialPairHeadModel,
    SpatialPairV2CustodyModel,
)
from lib.db.models.spatial_review import SpatialReviewSessionModel
from lib.db.repositories.spatial_pair import (
    SpatialPairIntegrityError,
    VerifiedPairDecision,
    verify_stored_pair_decision,
)
from lib.db.repositories.spatial_review import SpatialReviewIntegrityError, SpatialReviewRepository
from r2.contracts.production_target import TargetVersionRef
from r2.contracts.spatial_pair import PairDecisionCommandV2, PairDecisionResultV2, PairDecisionV2
from r2.spatial_pair.digests import (
    pair_command_digest_v2,
    pair_decision_digest_v2,
    pair_result_digest_v2,
    scoped_pair_id,
)


@dataclass(frozen=True)
class VerifiedPairDecisionV2:
    body: PairDecisionV2
    decision_digest: str


@dataclass(frozen=True)
class LockedPairHeadV2:
    row: SpatialPairHeadModel
    created_here: bool
    current_version: int | None
    current_decision_digest: str | None


@dataclass(frozen=True)
class VerifiedPairCommandReceiptV2:
    user_id: str
    project_name: str
    principal: str
    command_id: str
    result: PairDecisionResultV2
    result_digest: str


class SpatialPairVersionedRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_command_receipt_v2(
        self,
        *,
        user_id: str,
        project_name: str,
        principal: str,
        command_id: str,
        expected_command_digest: str,
    ) -> VerifiedPairCommandReceiptV2 | None:
        """Read a V2 receipt hint; the caller must then recheck current authorities."""
        row = await self.session.get(
            SpatialPairCommandModel,
            (user_id, project_name, principal, command_id),
            populate_existing=True,
        )
        if row is None:
            return None
        try:
            result = PairDecisionResultV2.model_validate(row.result_json)
            digest = pair_result_digest_v2(result.model_dump(mode="json"))
            if (
                result.model_dump(mode="json") != row.result_json
                or result.command_digest != row.command_digest
                or digest != row.result_digest
            ):
                raise ValueError("V2 command receipt differs from its stored columns")
        except (ValidationError, ValueError, TypeError) as exc:
            raise SpatialPairIntegrityError("V2 command receipt integrity verification failed") from exc
        if row.command_digest != expected_command_digest:
            raise SpatialPairIntegrityError("pair command ID has different V2 input")
        return VerifiedPairCommandReceiptV2(
            user_id=user_id,
            project_name=project_name,
            principal=principal,
            command_id=command_id,
            result=result,
            result_digest=digest,
        )

    async def verify_historical_receipt(
        self, *, hint: VerifiedPairCommandReceiptV2, command: PairDecisionCommandV2
    ) -> VerifiedPairDecisionV2:
        """Verify a replay after current source and grant rechecks under the caller's transaction."""
        if (command.user_id, command.project_name, command.principal, command.command_id) != (
            hint.user_id,
            hint.project_name,
            hint.principal,
            hint.command_id,
        ) or pair_command_digest_v2(command.model_dump(mode="json")) != hint.result.command_digest:
            raise SpatialPairIntegrityError("V2 replay command differs from its receipt hint")
        current_receipt = await self.get_command_receipt_v2(
            user_id=command.user_id,
            project_name=command.project_name,
            principal=command.principal,
            command_id=command.command_id,
            expected_command_digest=hint.result.command_digest,
        )
        if current_receipt != hint:
            raise SpatialPairIntegrityError("V2 replay receipt changed after the hint")
        result = hint.result
        row = await self.session.get(
            SpatialPairDecisionModel,
            (command.user_id, command.project_name, result.pair_id, result.pair_version),
            with_for_update=True,
            populate_existing=True,
        )
        custody = await self.session.get(
            SpatialPairV2CustodyModel,
            (command.user_id, command.project_name, result.pair_id, result.pair_version),
            with_for_update=True,
            populate_existing=True,
        )
        if row is None:
            raise SpatialPairIntegrityError("V2 replay decision is missing")
        verified = verify_stored_pair_decision_v2(
            row,
            custody,
            user_id=command.user_id,
            project_name=command.project_name,
            binding_id=command.binding_id,
            expected_binding_version=command.expected_binding_version,
            expected_envelope_digest=command.expected_envelope_digest,
            expected_core_digest=command.expected_core_digest,
            expected_target_ref=command.expected_target_ref,
            expected_scene_ref=command.expected_scene_ref,
        )
        body = verified.body
        expected_result = PairDecisionResultV2(
            result_schema="r2.m8.spatial.pair.result.v2",
            command_digest=body.command_digest,
            pair_id=body.pair_id,
            pair_version=body.pair_version,
            decision_digest=verified.decision_digest,
            decision=body.command.decision,
            binding_id=body.command.binding_id,
            binding_version=body.command.expected_binding_version,
            binding_envelope_digest=body.command.expected_envelope_digest,
            binding_core_digest=body.command.expected_core_digest,
            scene_ref=body.command.expected_scene_ref,
            target_ref=body.command.expected_target_ref,
            review_session_id=body.command.review_session_id,
            review_evidence_digest=body.command.review_evidence_digest,
        )
        if body.command != command or result != expected_result:
            raise SpatialPairIntegrityError("V2 replay result differs from its decision")
        await self._verify_review_consumption(verified)
        return verified

    async def claim_pair_head(self, *, user_id: str, project_name: str, pair_id: str) -> LockedPairHeadV2:
        """Claim the pair row after target/binding locks and before parent master locks."""
        insert = pg_insert if self.session.get_bind().dialect.name == "postgresql" else sqlite_insert
        inserted = (
            await self.session.execute(
                insert(SpatialPairHeadModel)
                .values(
                    user_id=user_id,
                    project_name=project_name,
                    pair_id=pair_id,
                    current_version=None,
                    current_decision_digest=None,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "project_name", "pair_id"])
                .returning(SpatialPairHeadModel.pair_id)
            )
        ).scalar_one_or_none()
        head = await self.session.get(
            SpatialPairHeadModel, (user_id, project_name, pair_id), with_for_update=True, populate_existing=True
        )
        if head is None:
            raise SpatialPairIntegrityError("pair head disappeared after scoped claim")
        if (head.current_version is None) != (head.current_decision_digest is None):
            raise SpatialPairIntegrityError("pair head has incomplete current decision")
        if inserted is None and head.current_version is None:
            raise SpatialPairIntegrityError("pair head has a committed genesis state")
        return LockedPairHeadV2(
            row=head,
            created_here=inserted is not None,
            current_version=head.current_version,
            current_decision_digest=head.current_decision_digest,
        )

    async def append_reviewed_decision(
        self, *, locked: LockedPairHeadV2, decision: PairDecisionV2
    ) -> PairDecisionResultV2:
        """Append after the caller has rechecked current sources and signed grant under its transaction."""
        decision = PairDecisionV2.model_validate(decision.model_dump(mode="json"))
        command = decision.command
        head = await self.session.get(
            SpatialPairHeadModel,
            (command.user_id, command.project_name, decision.pair_id),
            with_for_update=True,
            populate_existing=True,
        )
        if (
            head is None
            or head is not locked.row
            or head.current_version != locked.current_version
            or head.current_decision_digest != locked.current_decision_digest
            or decision.pair_version != (head.current_version or 0) + 1
            or (head.current_version is None and not locked.created_here)
        ):
            raise SpatialPairIntegrityError("V2 pair append disagrees with locked predecessor")
        if head.current_version is not None:
            previous = await self.get_current_verified(
                user_id=command.user_id,
                project_name=command.project_name,
                binding_id=command.binding_id,
                expected_binding_version=command.expected_binding_version,
                expected_envelope_digest=command.expected_envelope_digest,
                expected_core_digest=command.expected_core_digest,
                expected_target_ref=command.expected_target_ref,
                expected_scene_ref=command.expected_scene_ref,
            )
            if previous is None or previous.decision_digest != head.current_decision_digest:
                raise SpatialPairIntegrityError("V2 pair predecessor is invalid")
        evidence = await SpatialReviewRepository(self.session).consume_session(
            user_id=command.user_id,
            project_name=command.project_name,
            principal=command.principal,
            session_id=command.review_session_id,
            expected_evidence_digest=command.review_evidence_digest,
            command_digest=decision.command_digest,
        )
        if evidence != decision.review_evidence:
            raise SpatialPairIntegrityError("V2 pair decision differs from consumed review evidence")
        digest = pair_decision_digest_v2(decision.model_dump(mode="json"))
        target = command.expected_target_ref
        scene = command.expected_scene_ref
        row = SpatialPairDecisionModel(
            user_id=command.user_id,
            project_name=command.project_name,
            pair_id=decision.pair_id,
            pair_version=decision.pair_version,
            decision_body_json=decision.model_dump(mode="json"),
            decision_digest=digest,
            command_digest=decision.command_digest,
            authorization_digest=decision.authorization_digest,
            binding_id=command.binding_id,
            binding_version=command.expected_binding_version,
            binding_envelope_digest=command.expected_envelope_digest,
            binding_core_digest=command.expected_core_digest,
            target_type=target.target_type.value,
            target_id=target.target_id,
            target_registry_version=target.registry_version,
            target_version_digest=target.version_digest,
            scene_type=scene.target_type.value,
            scene_id=scene.target_id,
            scene_registry_version=scene.registry_version,
            scene_version_digest=scene.version_digest,
            master_receipt_id=command.views[0].receipt_id,
            reverse_receipt_id=command.views[1].receipt_id,
            decision=command.decision,
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        custody = SpatialPairV2CustodyModel(
            user_id=command.user_id,
            project_name=command.project_name,
            pair_id=decision.pair_id,
            pair_version=decision.pair_version,
            review_session_id=command.review_session_id,
            review_evidence_digest=command.review_evidence_digest,
            decision_digest=digest,
        )
        self.session.add(custody)
        await self.session.flush()
        verify_stored_pair_decision_v2(
            row,
            custody,
            user_id=command.user_id,
            project_name=command.project_name,
            binding_id=command.binding_id,
            expected_binding_version=command.expected_binding_version,
            expected_envelope_digest=command.expected_envelope_digest,
            expected_core_digest=command.expected_core_digest,
            expected_target_ref=target,
            expected_scene_ref=scene,
        )
        head.current_version = decision.pair_version
        head.current_decision_digest = digest
        await self.session.flush()
        result = PairDecisionResultV2(
            result_schema="r2.m8.spatial.pair.result.v2",
            command_digest=decision.command_digest,
            pair_id=decision.pair_id,
            pair_version=decision.pair_version,
            decision_digest=digest,
            decision=command.decision,
            binding_id=command.binding_id,
            binding_version=command.expected_binding_version,
            binding_envelope_digest=command.expected_envelope_digest,
            binding_core_digest=command.expected_core_digest,
            scene_ref=scene,
            target_ref=target,
            review_session_id=command.review_session_id,
            review_evidence_digest=command.review_evidence_digest,
        )
        self.session.add(
            SpatialPairCommandModel(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                command_id=command.command_id,
                command_digest=decision.command_digest,
                result_json=result.model_dump(mode="json"),
                result_digest=pair_result_digest_v2(result.model_dump(mode="json")),
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return result

    async def get_current_verified(
        self,
        *,
        user_id: str,
        project_name: str,
        binding_id: str,
        expected_binding_version: int,
        expected_envelope_digest: str,
        expected_core_digest: str,
        expected_target_ref: TargetVersionRef,
        expected_scene_ref: TargetVersionRef,
    ) -> VerifiedPairDecision | VerifiedPairDecisionV2 | None:
        """Read local history after the caller locks current target and binding authority."""
        pair_id = scoped_pair_id(user_id=user_id, project_name=project_name, binding_id=binding_id)
        head = await self.session.get(
            SpatialPairHeadModel,
            (user_id, project_name, pair_id),
            with_for_update=True,
            populate_existing=True,
        )
        if head is None:
            return None
        if head.current_version is None or head.current_decision_digest is None:
            raise SpatialPairIntegrityError("pair head integrity: committed genesis or incomplete current pair")
        row = await self.session.get(
            SpatialPairDecisionModel,
            (user_id, project_name, pair_id, head.current_version),
            with_for_update=True,
            populate_existing=True,
        )
        latest = await self.session.scalar(
            select(func.max(SpatialPairDecisionModel.pair_version)).where(
                SpatialPairDecisionModel.user_id == user_id,
                SpatialPairDecisionModel.project_name == project_name,
                SpatialPairDecisionModel.pair_id == pair_id,
            )
        )
        if row is None or latest != head.current_version or row.decision_digest != head.current_decision_digest:
            raise SpatialPairIntegrityError("pair head integrity: current decision is missing or not latest")
        custody = await self.session.get(
            SpatialPairV2CustodyModel,
            (user_id, project_name, pair_id, head.current_version),
            with_for_update=True,
            populate_existing=True,
        )
        verified = verify_stored_pair_decision_versioned(
            row,
            custody,
            user_id=user_id,
            project_name=project_name,
            binding_id=binding_id,
            expected_binding_version=expected_binding_version,
            expected_envelope_digest=expected_envelope_digest,
            expected_core_digest=expected_core_digest,
            expected_target_ref=expected_target_ref,
            expected_scene_ref=expected_scene_ref,
        )
        if isinstance(verified, VerifiedPairDecisionV2):
            await self._verify_review_consumption(verified)
        return verified

    async def _verify_review_consumption(self, verified: VerifiedPairDecisionV2) -> None:
        command = verified.body.command
        try:
            evidence, evidence_digest = await SpatialReviewRepository(self.session).read_complete(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                session_id=command.review_session_id,
            )
        except SpatialReviewIntegrityError as exc:
            raise SpatialPairIntegrityError("pair V2 stored review evidence is invalid") from exc
        session_row = await self.session.get(
            SpatialReviewSessionModel,
            (command.user_id, command.project_name, command.review_session_id),
            with_for_update=True,
            populate_existing=True,
        )
        if (
            session_row is None
            or session_row.consumed_command_digest != verified.body.command_digest
            or evidence != verified.body.review_evidence
            or evidence_digest != command.review_evidence_digest
        ):
            raise SpatialPairIntegrityError("pair V2 decision differs from stored review consumption")


def verify_stored_pair_decision_v2(
    row: SpatialPairDecisionModel,
    custody: SpatialPairV2CustodyModel | None,
    *,
    user_id: str,
    project_name: str,
    binding_id: str,
    expected_binding_version: int,
    expected_envelope_digest: str,
    expected_core_digest: str,
    expected_target_ref: TargetVersionRef,
    expected_scene_ref: TargetVersionRef,
) -> VerifiedPairDecisionV2:
    try:
        if custody is None:
            raise ValueError("V2 decision custody is missing")
        body = PairDecisionV2.model_validate(row.decision_body_json)
        command = body.command
        decision_digest = pair_decision_digest_v2(body.model_dump(mode="json"))
        if (
            body.model_dump(mode="json") != row.decision_body_json
            or (row.user_id, row.project_name, custody.user_id, custody.project_name)
            != (user_id, project_name, user_id, project_name)
            or (command.user_id, command.project_name) != (user_id, project_name)
            or row.pair_id != scoped_pair_id(user_id=user_id, project_name=project_name, binding_id=binding_id)
            or body.pair_id != row.pair_id
            or (custody.pair_id, custody.pair_version) != (row.pair_id, row.pair_version)
            or body.pair_version != row.pair_version
            or (row.binding_id, command.binding_id) != (binding_id, binding_id)
            or (row.binding_version, command.expected_binding_version)
            != (expected_binding_version, expected_binding_version)
            or (row.binding_envelope_digest, command.expected_envelope_digest)
            != (expected_envelope_digest, expected_envelope_digest)
            or (row.binding_core_digest, command.expected_core_digest) != (expected_core_digest, expected_core_digest)
            or command.expected_target_ref != expected_target_ref
            or command.expected_scene_ref != expected_scene_ref
            or (row.target_type, row.target_id, row.target_registry_version, row.target_version_digest)
            != (
                expected_target_ref.target_type.value,
                expected_target_ref.target_id,
                expected_target_ref.registry_version,
                expected_target_ref.version_digest,
            )
            or (row.scene_type, row.scene_id, row.scene_registry_version, row.scene_version_digest)
            != (
                expected_scene_ref.target_type.value,
                expected_scene_ref.target_id,
                expected_scene_ref.registry_version,
                expected_scene_ref.version_digest,
            )
            or (row.master_receipt_id, row.reverse_receipt_id)
            != (command.views[0].receipt_id, command.views[1].receipt_id)
            or row.decision != command.decision
            or row.command_digest != body.command_digest
            or row.authorization_digest != body.authorization_digest
            or (row.decision_digest, custody.decision_digest) != (decision_digest, decision_digest)
            or custody.review_session_id != command.review_session_id
            or custody.review_evidence_digest != command.review_evidence_digest
        ):
            raise ValueError("V2 decision row differs from its scoped body or custody")
        return VerifiedPairDecisionV2(body=body, decision_digest=decision_digest)
    except (ValidationError, ValueError, TypeError) as exc:
        raise SpatialPairIntegrityError("pair V2 decision integrity verification failed") from exc


def verify_stored_pair_decision_versioned(
    row: SpatialPairDecisionModel,
    custody: SpatialPairV2CustodyModel | None,
    *,
    user_id: str,
    project_name: str,
    binding_id: str,
    expected_binding_version: int,
    expected_envelope_digest: str,
    expected_core_digest: str,
    expected_target_ref: TargetVersionRef,
    expected_scene_ref: TargetVersionRef,
) -> VerifiedPairDecision | VerifiedPairDecisionV2:
    body = cast(object, row.decision_body_json)
    if not isinstance(body, dict):
        raise SpatialPairIntegrityError("pair decision body is not an object")
    expected = {
        "user_id": user_id,
        "project_name": project_name,
        "binding_id": binding_id,
        "expected_binding_version": expected_binding_version,
        "expected_envelope_digest": expected_envelope_digest,
        "expected_core_digest": expected_core_digest,
        "expected_target_ref": expected_target_ref,
        "expected_scene_ref": expected_scene_ref,
    }
    if "decision_schema" not in body:
        if custody is not None:
            raise SpatialPairIntegrityError("V1 pair decision has V2 custody")
        return verify_stored_pair_decision(row, **expected)
    if body["decision_schema"] == "r2.m8.spatial.pair.decision.v2":
        return verify_stored_pair_decision_v2(row, custody, **expected)
    raise SpatialPairIntegrityError("pair decision schema is unknown")


__all__ = [
    "LockedPairHeadV2",
    "SpatialPairVersionedRepository",
    "VerifiedPairCommandReceiptV2",
    "VerifiedPairDecisionV2",
    "verify_stored_pair_decision_v2",
    "verify_stored_pair_decision_versioned",
]
