"""Preview-bound M8 promotion into the host master authority (spec §5–§6, ADR-0097).

This is the only M8 module that invokes the authority adapter (``SlotAuthority.promote``). A new
promotion takes the ADR-0097 locks in order: command key, candidate head, preview, then the
slot's authority row. Under them it revalidates every bound field. It then stages the
authorization, the M7 promotion (head version, pointer, M7 receipt, project event) and the M8
receipts, and commits once. An exact replay returns the stored receipt before any currentness
check.

Under the locks the promotion also recomputes the revision's payload digest from its stored payload
and lineage, and requires the rendered object to be registered for the target slot (ADR-0097 review
round 1).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from r2.advanced_creative.digests import digest_canonical, digest_command, digest_payload
from r2.advanced_creative.errors import (
    CandidateConflictError,
    CommandConflictError,
    ExplorationNotFoundError,
    PromotionBindingStaleError,
    PromotionTargetUnavailableError,
)
from r2.advanced_creative.exploration import (
    ExplorationStore,
    FormatEvidence,
    RefuseFormatEvidence,
    SlotAuthority,
    genesis_allowed,
    promotable_format,
    uuid7,
)
from r2.contracts.advanced_creative import PromotionAuthorization, PromotionReceipt, PromotionTargetKind

PROMOTE_OPERATION = "PROMOTE"


class ExplorationPromotion:
    def __init__(
        self,
        *,
        store: ExplorationStore,
        slots: SlotAuthority,
        commit: Callable[[], Awaitable[None]],
        clock: Callable[[], datetime],
        new_id: Callable[[], str] = uuid7,
        format_evidence: FormatEvidence | None = None,
    ) -> None:
        self._store = store
        self._slots = slots
        self._commit = commit
        self._clock = clock
        self._new_id = new_id
        self._format_evidence = format_evidence or RefuseFormatEvidence()

    async def promote(
        self,
        *,
        user_id: str,
        project_name: str,
        authorization: PromotionAuthorization,
        expected_candidate_head_version: int,
    ) -> PromotionReceipt:
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
        replay = await self._replayed(scope, command_digest)
        if replay is not None:
            return replay
        # Lock order (ADR-0097): command key, candidate head, preview, slot row.
        await self._store.lock_command_key(**scope)
        replay = await self._replayed(scope, command_digest)
        if replay is not None:
            return replay
        found = await self._store.get_preview(
            user_id=user_id, project_name=project_name, preview_id=authorization.preview_id
        )
        if found is None:
            raise ExplorationNotFoundError("no such preview in this scope")
        preview, _ = found
        head = await self._store.get_head(
            user_id=user_id, project_name=project_name, candidate_id=preview.candidate_id, for_update=True
        )
        locked = await self._store.get_preview(
            user_id=user_id, project_name=project_name, preview_id=authorization.preview_id, for_update=True
        )
        if head is None or locked is None:
            raise ExplorationNotFoundError("no such preview in this scope")
        preview, preview_digest = locked
        if head.head_version != expected_candidate_head_version:
            raise CandidateConflictError("the candidate head moved; reload it and authorize again")
        now = self._clock()
        if (
            authorization.preview_digest != preview_digest
            or authorization.actor_scope != preview.authorization_scope
            or now >= preview.expires_at
        ):
            raise PromotionBindingStaleError("the authorization does not bind this current, unexpired preview")
        if preview.target.kind is not PromotionTargetKind.ARTIFACT_SLOT or self._slots.is_manifest_key(
            preview.target.target_ref
        ):
            raise PromotionTargetUnavailableError("only M8 artifact slots can be promoted into (ADR-0095, ADR-0097)")
        revision = await self._store.get_exact(
            user_id=user_id,
            project_name=project_name,
            candidate_id=preview.candidate_id,
            revision=preview.candidate_revision,
        )
        if (
            revision is None
            or revision.payload_digest != preview.candidate_payload_digest
            or digest_payload(revision.payload, revision.lineage) != revision.payload_digest
        ):
            raise PromotionBindingStaleError("the previewed revision no longer matches")
        payload = promotable_format(revision)
        target_ref = preview.target.target_ref
        await self._format_evidence.verify(
            user_id=user_id, project_name=project_name, target_ref=target_ref, payload=payload
        )
        await self._slots.lock_slot(user_id=user_id, project_name=project_name, target_ref=target_ref)
        master = await self._slots.current_head(user_id=user_id, project_name=project_name, target_ref=target_ref)
        if master is None:
            # A format slot's first promotion: the preview bound "no master" at version 0.
            if not (
                genesis_allowed(preview.target)
                and preview.expected_master_id is None
                and preview.expected_master_digest is None
            ):
                raise PromotionBindingStaleError("the slot's master moved since the preview")
        elif (
            master.master_version != preview.target.expected_target_version
            or master.candidate_id != preview.expected_master_id
            or master.content_digest != preview.expected_master_digest
        ):
            raise PromotionBindingStaleError("the slot's master moved since the preview")
        candidate_object = await self._slots.candidate_object(
            user_id=user_id, project_name=project_name, candidate_id=payload.rendered_artifact_ref
        )
        if (
            candidate_object is None
            or candidate_object.artifact_key != target_ref
            or candidate_object.content_digest != payload.rendered_artifact_digest
        ):
            raise PromotionBindingStaleError("the rendered artifact is not a candidate object registered for this slot")

        authorization_digest = await self._store.stage_authorization(user_id=user_id, authorization=authorization)
        promoted = await self._slots.promote(
            user_id=user_id,
            project_name=project_name,
            target_ref=target_ref,
            candidate_id=payload.rendered_artifact_ref,
            expected_master_version=0 if master is None else master.master_version,
            approval_record=f"m8:{authorization.command_id}",
            command_id=f"m8-promote:{authorization.command_id}",
        )
        receipt = PromotionReceipt(
            receipt_id=self._new_id(),
            command_id=authorization.command_id,
            project_name=project_name,
            preview_digest=preview_digest,
            candidate_id=preview.candidate_id,
            candidate_revision=preview.candidate_revision,
            target=preview.target,
            result_artifact_ref=target_ref,
            result_master_id=promoted.candidate_id,
            result_digest=promoted.content_digest,
            promoted_at=now,
        )
        await self._store.stage_promotion_receipt(
            user_id=user_id,
            receipt=receipt,
            preview_id=preview.preview_id,
            authorization_digest=authorization_digest,
        )
        await self._store.record_command(
            **scope,
            command_digest=command_digest,
            result_kind="PROMOTION_RECEIPT",
            result_ref=receipt.receipt_id,
            result_digest=digest_canonical(receipt),
            created_at=now,
        )
        await self._commit()
        return receipt

    async def _replayed(self, scope: dict[str, str], command_digest: str) -> PromotionReceipt | None:
        recorded = await self._store.get_command_receipt(**scope)
        if recorded is None:
            return None
        if recorded.command_digest != command_digest:
            raise CommandConflictError("this command id was already used for a different request")
        receipt = await self._store.get_promotion_receipt(
            user_id=scope["user_id"], project_name=scope["project_name"], command_id=scope["command_id"]
        )
        if receipt is None or digest_canonical(receipt) != recorded.result_digest:
            raise CommandConflictError("the recorded promotion no longer matches its command")
        return receipt


__all__ = ["PROMOTE_OPERATION", "ExplorationPromotion"]
