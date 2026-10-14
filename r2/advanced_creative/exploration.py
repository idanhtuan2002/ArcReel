"""M8 exploration: append revisions and issue promotion previews (spec §4–§6, ADR-0097).

Domain logic over injected ports; persistence and the host authority are composed by the server.
Every operation runs in one unit of work under the ADR-0097 lock order and commits once.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol

from r2.advanced_creative.digests import digest_canonical, digest_command
from r2.advanced_creative.errors import (
    CandidateConflictError,
    CommandConflictError,
    ExplorationNotFoundError,
    PromotionBindingStaleError,
    PromotionTargetUnavailableError,
)
from r2.contracts.advanced_creative import (
    CandidateHead,
    CanonicalJsonObject,
    ExplorationKind,
    ExplorationRevision,
    FormatCandidate,
    PromotionAuthorization,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
    PromotionTargetKind,
)
from r2.contracts.host_hardening import MasterHeadSnapshot, VerifiedCandidateObject

PREVIEW_TTL = timedelta(seconds=900)
PREVIEW_OPERATION = "PREVIEW"


def uuid7() -> str:
    """A UUIDv7 string: 48-bit Unix milliseconds, version and variant bits, then randomness."""
    millis = time.time_ns() // 1_000_000
    random_bits = int.from_bytes(os.urandom(10), "big")
    value = (millis & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= (random_bits >> 68) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)
    return str(uuid.UUID(int=value))


class CommandReceiptView(Protocol):
    @property
    def command_digest(self) -> str: ...

    @property
    def result_ref(self) -> str: ...

    @property
    def result_digest(self) -> str: ...


class ExplorationStore(Protocol):
    """The M8 evidence store of one unit of work (``ExplorationRepository``)."""

    async def append_revision(
        self,
        *,
        user_id: str,
        project_name: str,
        candidate: ExplorationRevision,
        expected_head_version: int | None,
        command_id: str,
    ) -> CandidateHead: ...

    async def get_exact(
        self, *, user_id: str, project_name: str, candidate_id: str, revision: int
    ) -> ExplorationRevision | None: ...

    async def history(
        self, *, user_id: str, project_name: str, candidate_id: str, after_revision: int | None, limit: int
    ) -> tuple[ExplorationRevision, ...]: ...

    async def get_head(
        self, *, user_id: str, project_name: str, candidate_id: str, for_update: bool = False
    ) -> CandidateHead | None: ...

    async def lock_command_key(
        self, *, user_id: str, project_name: str, actor_scope: str, operation: str, command_id: str
    ) -> None: ...

    async def get_command_receipt(
        self, *, user_id: str, project_name: str, actor_scope: str, operation: str, command_id: str
    ) -> CommandReceiptView | None: ...

    async def record_command(
        self,
        *,
        user_id: str,
        project_name: str,
        actor_scope: str,
        operation: str,
        command_id: str,
        command_digest: str,
        result_kind: str,
        result_ref: str,
        result_digest: str,
        created_at: datetime,
    ) -> None: ...

    async def stage_preview(self, *, user_id: str, preview: PromotionPreview) -> str: ...

    async def get_preview(
        self, *, user_id: str, project_name: str, preview_id: str, for_update: bool = False
    ) -> tuple[PromotionPreview, str] | None: ...

    async def stage_authorization(self, *, user_id: str, authorization: PromotionAuthorization) -> str: ...

    async def stage_promotion_receipt(
        self, *, user_id: str, receipt: PromotionReceipt, preview_id: str, authorization_digest: str
    ) -> None: ...

    async def get_promotion_receipt(
        self, *, user_id: str, project_name: str, command_id: str
    ) -> PromotionReceipt | None: ...


class SlotAuthority(Protocol):
    """The host master authority for M8 artifact slots, on the same unit of work."""

    def is_manifest_key(self, target_ref: str) -> bool: ...

    async def current_head(self, *, user_id: str, project_name: str, target_ref: str) -> MasterHeadSnapshot | None: ...

    async def lock_slot(self, *, user_id: str, project_name: str, target_ref: str) -> None: ...

    async def candidate_object(
        self, *, user_id: str, project_name: str, candidate_id: str
    ) -> VerifiedCandidateObject | None: ...

    async def promote(
        self,
        *,
        user_id: str,
        project_name: str,
        target_ref: str,
        candidate_id: str,
        expected_master_version: int,
        approval_record: str,
        command_id: str,
    ) -> MasterHeadSnapshot: ...


def is_format_slot(target_ref: str) -> bool:
    """An M8 format projection slot (``m8-format:<source key digest>:<profile ref>``)."""
    return target_ref.startswith("m8-format:")


class FormatEvidence(Protocol):
    """Re-verifies a FORMAT candidate's evidence for a slot; raises ``PromotionBindingStaleError`` if stale."""

    async def verify(self, *, user_id: str, project_name: str, target_ref: str, payload: FormatCandidate) -> None: ...


class RefuseFormatEvidence:
    """The fail-closed default: without wired evidence no FORMAT candidate is previewed or promoted."""

    async def verify(self, *, user_id: str, project_name: str, target_ref: str, payload: FormatCandidate) -> None:
        raise PromotionBindingStaleError("format evidence is not available")


def genesis_allowed(target: PromotionTarget) -> bool:
    """Only a format slot's first promotion may run against no master, at expected version 0."""
    return is_format_slot(target.target_ref) and target.expected_target_version == 0


def promotable_format(revision: ExplorationRevision) -> FormatCandidate:
    """The FormatCandidate payload an ARTIFACT_SLOT promotion needs, or the unavailable-target error."""
    if revision.kind is not ExplorationKind.FORMAT or not isinstance(revision.payload, FormatCandidate):
        raise PromotionTargetUnavailableError(f"{revision.kind.value} candidates have no promotable artifact yet")
    return revision.payload


class ExplorationService:
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

    async def append_revision(
        self,
        *,
        user_id: str,
        project_name: str,
        candidate: ExplorationRevision,
        expected_head_version: int | None,
        command_id: str,
    ) -> CandidateHead:
        if candidate.lineage.project_name != project_name or candidate.created_by != user_id:
            raise ExplorationNotFoundError("the revision is not in this scope")
        if candidate.kind is ExplorationKind.SPATIAL:
            raise CandidateConflictError("spatial revisions require server-owned spatial execution")
        head = await self._store.append_revision(
            user_id=user_id,
            project_name=project_name,
            candidate=candidate,
            expected_head_version=expected_head_version,
            command_id=command_id,
        )
        await self._commit()
        return head

    async def head(self, *, user_id: str, project_name: str, candidate_id: str) -> CandidateHead:
        found = await self._store.get_head(user_id=user_id, project_name=project_name, candidate_id=candidate_id)
        if found is None:
            raise ExplorationNotFoundError("no such candidate in this scope")
        return found

    async def get_exact(
        self, *, user_id: str, project_name: str, candidate_id: str, revision: int
    ) -> ExplorationRevision:
        found = await self._store.get_exact(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id, revision=revision
        )
        if found is None:
            raise ExplorationNotFoundError("no such revision in this scope")
        return found

    async def history(
        self, *, user_id: str, project_name: str, candidate_id: str, after_revision: int | None, limit: int
    ) -> tuple[ExplorationRevision, ...]:
        return await self._store.history(
            user_id=user_id,
            project_name=project_name,
            candidate_id=candidate_id,
            after_revision=after_revision,
            limit=limit,
        )

    async def create_preview(
        self,
        *,
        user_id: str,
        project_name: str,
        candidate_id: str,
        revision: int,
        target: PromotionTarget,
        command_id: str,
    ) -> PromotionPreview:
        scope = {
            "user_id": user_id,
            "project_name": project_name,
            "actor_scope": user_id,
            "operation": PREVIEW_OPERATION,
            "command_id": command_id,
        }
        command_digest = digest_command(
            PREVIEW_OPERATION,
            user_id,
            project_name,
            user_id,
            {"candidate_id": candidate_id, "revision": revision, "target": target},
        )
        replay = await self._replayed_preview(scope, command_digest)
        if replay is not None:
            return replay
        # Lock order (ADR-0097): command key, then candidate head.
        await self._store.lock_command_key(**scope)
        replay = await self._replayed_preview(scope, command_digest)
        if replay is not None:
            return replay
        head = await self._store.get_head(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id, for_update=True
        )
        stored = await self._store.get_exact(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id, revision=revision
        )
        if head is None or stored is None:
            raise ExplorationNotFoundError("no such revision in this scope")
        if target.kind is PromotionTargetKind.PRODUCTION_BINDING:
            raise PromotionTargetUnavailableError("the ProductionBinding target has no authority yet (ADR-0095)")
        if self._slots.is_manifest_key(target.target_ref):
            raise PromotionTargetUnavailableError("manifest artifacts are promoted by the host flows (ADR-0097)")
        payload = promotable_format(stored)
        await self._format_evidence.verify(
            user_id=user_id, project_name=project_name, target_ref=target.target_ref, payload=payload
        )
        master = await self._slots.current_head(
            user_id=user_id, project_name=project_name, target_ref=target.target_ref
        )
        if master is None and not genesis_allowed(target):
            raise PromotionTargetUnavailableError("the slot has no master to replace")
        if (0 if master is None else master.master_version) != target.expected_target_version:
            raise PromotionBindingStaleError("the slot's master version moved")
        issued_at = self._clock()
        impact = CanonicalJsonObject.model_validate(
            {
                "from": None
                if master is None
                else {
                    "master_id": master.candidate_id,
                    "master_digest": master.content_digest,
                    "master_version": master.master_version,
                },
                "to": {
                    "candidate_object_id": payload.rendered_artifact_ref,
                    "content_digest": payload.rendered_artifact_digest,
                },
            }
        )
        preview = PromotionPreview(
            preview_id=self._new_id(),
            preview_command_id=command_id,
            project_name=project_name,
            candidate_id=candidate_id,
            candidate_revision=revision,
            candidate_payload_digest=stored.payload_digest,
            target=target,
            expected_master_id=None if master is None else master.candidate_id,
            expected_master_digest=None if master is None else master.content_digest,
            impact=impact,
            impact_digest=digest_canonical(impact),
            authorization_scope=user_id,
            issued_at=issued_at,
            expires_at=issued_at + PREVIEW_TTL,
        )
        preview_digest = await self._store.stage_preview(user_id=user_id, preview=preview)
        await self._store.record_command(
            **scope,
            command_digest=command_digest,
            result_kind="PREVIEW",
            result_ref=preview.preview_id,
            result_digest=preview_digest,
            created_at=issued_at,
        )
        await self._commit()
        return preview

    async def _replayed_preview(self, scope: dict[str, str], command_digest: str) -> PromotionPreview | None:
        receipt = await self._store.get_command_receipt(**scope)
        if receipt is None:
            return None
        if receipt.command_digest != command_digest:
            raise CommandConflictError("this command id was already used for a different request")
        stored = await self._store.get_preview(
            user_id=scope["user_id"], project_name=scope["project_name"], preview_id=receipt.result_ref
        )
        if stored is None or stored[1] != receipt.result_digest:
            raise CommandConflictError("the recorded preview no longer matches its command")
        return stored[0]


__all__ = [
    "PREVIEW_OPERATION",
    "PREVIEW_TTL",
    "CommandReceiptView",
    "ExplorationService",
    "ExplorationStore",
    "FormatEvidence",
    "RefuseFormatEvidence",
    "SlotAuthority",
    "genesis_allowed",
    "is_format_slot",
    "promotable_format",
    "uuid7",
]
