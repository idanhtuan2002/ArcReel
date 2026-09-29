"""M8 exploration evidence repository (spec §5–§6, plan Task A2).

Every read and write is scoped by ``(user_id, project_name)``; a foreign identity is reported
exactly like an unknown one. Writes flush and never commit: the caller's unit of work commits
or rolls back once.

Append follows the normative lock order:

1. a scoped command receipt lookup;
2. a lock on the command key;
3. a lock on the candidate head;
4. predecessor and head-version compare-and-set validation;
5. the immutable revision and the head update;
6. the command receipt.

An exact replay of a completed command returns its original head before any currentness check
and changes no row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.advanced_creative import (
    M8CandidateHeadModel,
    M8CandidateRevisionModel,
    M8CommandReceiptModel,
    M8PromotionAuthorizationModel,
    M8PromotionPreviewModel,
    M8PromotionReceiptModel,
)
from r2.advanced_creative.digests import digest_canonical, digest_command, digest_payload
from r2.advanced_creative.errors import CandidateConflictError, CommandConflictError, ExplorationNotFoundError
from r2.contracts.advanced_creative import (
    CandidateHead,
    CanonicalJsonObject,
    ExplorationRevision,
    PromotionAuthorization,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
    PromotionTargetKind,
)

APPEND_REVISION = "APPEND_REVISION"
PREVIEW = "PREVIEW"
PROMOTE = "PROMOTE"
MAX_HISTORY_PAGE = 100


@dataclass(frozen=True)
class CommandReceipt:
    """One completed M8 command in its ``(user, project, actor_scope, operation)`` scope."""

    actor_scope: str
    operation: str
    command_id: str
    command_digest: str
    result_kind: str
    result_ref: str
    result_digest: str
    created_at: datetime


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _receipt_from_row(row: M8CommandReceiptModel) -> CommandReceipt:
    return CommandReceipt(
        actor_scope=row.actor_scope,
        operation=row.operation,
        command_id=row.command_id,
        command_digest=row.command_digest,
        result_kind=row.result_kind,
        result_ref=row.result_ref,
        result_digest=row.result_digest,
        created_at=_as_utc(row.created_at),
    )


def _revision_from_row(row: M8CandidateRevisionModel) -> ExplorationRevision:
    return ExplorationRevision.model_validate(
        {
            "candidate_id": row.candidate_id,
            "revision": row.revision,
            "kind": row.kind,
            "parent_revision": row.parent_revision,
            "payload": row.payload_json,
            "payload_digest": row.payload_digest,
            "lineage": row.lineage_json,
            "created_by": row.created_by,
            "created_at": _as_utc(row.created_at),
        }
    )


def _preview_from_row(row: M8PromotionPreviewModel) -> PromotionPreview:
    return PromotionPreview(
        preview_id=row.preview_id,
        preview_command_id=row.preview_command_id,
        project_name=row.project_name,
        candidate_id=row.candidate_id,
        candidate_revision=row.candidate_revision,
        candidate_payload_digest=row.candidate_payload_digest,
        target=PromotionTarget(
            kind=PromotionTargetKind(row.target_kind),
            target_ref=row.target_ref,
            expected_target_version=row.expected_target_version,
        ),
        expected_master_id=row.expected_master_id,
        expected_master_digest=row.expected_master_digest,
        impact=CanonicalJsonObject.model_validate(row.impact_json),
        impact_digest=row.impact_digest,
        authorization_scope=row.authorization_scope,
        issued_at=_as_utc(row.issued_at),
        expires_at=_as_utc(row.expires_at),
    )


def append_command_digest(
    *, user_id: str, project_name: str, candidate: ExplorationRevision, expected_head_version: int | None
) -> str:
    return digest_command(
        APPEND_REVISION,
        user_id,
        project_name,
        candidate.created_by,
        {"candidate": candidate, "expected_head_version": expected_head_version},
    )


def _head_after(candidate: ExplorationRevision, expected_head_version: int | None) -> CandidateHead:
    return CandidateHead(
        candidate_id=candidate.candidate_id,
        current_revision=candidate.revision,
        head_version=(expected_head_version or 0) + 1,
    )


class ExplorationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- command receipts ------------------------------------------------------------

    async def lock_command_key(
        self, *, user_id: str, project_name: str, actor_scope: str, operation: str, command_id: str
    ) -> None:
        """Serialize one command key for the rest of the transaction (PostgreSQL); a no-op otherwise."""
        if self.session.get_bind().dialect.name != "postgresql":
            return
        key = f"m8-command:{user_id}:{project_name}:{actor_scope}:{operation}:{command_id}"
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    async def get_command_receipt(
        self, *, user_id: str, project_name: str, actor_scope: str, operation: str, command_id: str
    ) -> CommandReceipt | None:
        row = await self.session.get(M8CommandReceiptModel, (user_id, project_name, actor_scope, operation, command_id))
        return None if row is None else _receipt_from_row(row)

    async def stage_command_receipt(self, *, user_id: str, project_name: str, receipt: CommandReceipt) -> None:
        self.session.add(
            M8CommandReceiptModel(
                user_id=user_id,
                project_name=project_name,
                actor_scope=receipt.actor_scope,
                operation=receipt.operation,
                command_id=receipt.command_id,
                command_digest=receipt.command_digest,
                result_kind=receipt.result_kind,
                result_ref=receipt.result_ref,
                result_digest=receipt.result_digest,
                created_at=receipt.created_at,
            )
        )
        await self.session.flush()

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
    ) -> None:
        await self.stage_command_receipt(
            user_id=user_id,
            project_name=project_name,
            receipt=CommandReceipt(
                actor_scope=actor_scope,
                operation=operation,
                command_id=command_id,
                command_digest=command_digest,
                result_kind=result_kind,
                result_ref=result_ref,
                result_digest=result_digest,
                created_at=created_at,
            ),
        )

    # --- candidate heads and revisions -------------------------------------------------

    async def get_head(
        self, *, user_id: str, project_name: str, candidate_id: str, for_update: bool = False
    ) -> CandidateHead | None:
        statement = select(M8CandidateHeadModel).where(
            M8CandidateHeadModel.user_id == user_id,
            M8CandidateHeadModel.project_name == project_name,
            M8CandidateHeadModel.candidate_id == candidate_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        return CandidateHead(
            candidate_id=row.candidate_id, current_revision=row.current_revision, head_version=row.head_version
        )

    async def append_revision(
        self,
        *,
        user_id: str,
        project_name: str,
        candidate: ExplorationRevision,
        expected_head_version: int | None,
        command_id: str,
    ) -> CandidateHead:
        scope = {
            "user_id": user_id,
            "project_name": project_name,
            "actor_scope": candidate.created_by,
            "operation": APPEND_REVISION,
            "command_id": command_id,
        }
        command_digest = append_command_digest(
            user_id=user_id, project_name=project_name, candidate=candidate, expected_head_version=expected_head_version
        )
        replay = await self._replayed_head(scope, command_digest, candidate, expected_head_version)
        if replay is not None:
            return replay
        await self.lock_command_key(**scope)
        replay = await self._replayed_head(scope, command_digest, candidate, expected_head_version)
        if replay is not None:
            return replay

        if candidate.payload_digest != digest_payload(candidate.payload, candidate.lineage):
            raise CandidateConflictError("payload_digest is not the digest of the revision's payload and lineage")
        now = candidate.created_at
        if candidate.revision == 1:
            if candidate.parent_revision is not None or expected_head_version is not None:
                raise CandidateConflictError("a genesis revision has no parent and no expected head version")
            await self._insert_genesis_head(user_id=user_id, project_name=project_name, candidate=candidate)
        else:
            head = await self.get_head(
                user_id=user_id, project_name=project_name, candidate_id=candidate.candidate_id, for_update=True
            )
            if head is None:
                raise ExplorationNotFoundError("no such candidate in this scope")
            if (
                candidate.parent_revision != head.current_revision
                or candidate.revision != head.current_revision + 1
                or expected_head_version != head.head_version
            ):
                raise CandidateConflictError("the candidate head moved; reload it and append again")
            advanced = await self.session.execute(
                update(M8CandidateHeadModel)
                .where(
                    M8CandidateHeadModel.candidate_id == candidate.candidate_id,
                    M8CandidateHeadModel.head_version == head.head_version,
                )
                .values(current_revision=candidate.revision, head_version=head.head_version + 1, updated_at=now)
            )
            if getattr(advanced, "rowcount", 0) != 1:
                raise CandidateConflictError("the candidate head moved; reload it and append again")

        self.session.add(
            M8CandidateRevisionModel(
                user_id=user_id,
                project_name=project_name,
                candidate_id=candidate.candidate_id,
                revision=candidate.revision,
                parent_revision=candidate.parent_revision,
                kind=candidate.kind.value,
                payload_json=candidate.payload.model_dump(mode="json"),
                payload_digest=candidate.payload_digest,
                lineage_json=candidate.lineage.model_dump(mode="json"),
                created_by=candidate.created_by,
                created_at=now,
            )
        )
        await self.session.flush()
        head = _head_after(candidate, expected_head_version)
        await self.stage_command_receipt(
            user_id=user_id,
            project_name=project_name,
            receipt=CommandReceipt(
                actor_scope=candidate.created_by,
                operation=APPEND_REVISION,
                command_id=command_id,
                command_digest=command_digest,
                result_kind="CANDIDATE_HEAD",
                result_ref=candidate.candidate_id,
                result_digest=digest_canonical(head),
                created_at=now,
            ),
        )
        return head

    async def _replayed_head(
        self,
        scope: dict[str, str],
        command_digest: str,
        candidate: ExplorationRevision,
        expected_head_version: int | None,
    ) -> CandidateHead | None:
        receipt = await self.get_command_receipt(**scope)
        if receipt is None:
            return None
        head = _head_after(candidate, expected_head_version)
        if receipt.command_digest != command_digest or receipt.result_digest != digest_canonical(head):
            raise CommandConflictError("this command id was already used for a different request")
        return head

    async def _insert_genesis_head(self, *, user_id: str, project_name: str, candidate: ExplorationRevision) -> None:
        try:
            async with self.session.begin_nested():
                self.session.add(
                    M8CandidateHeadModel(
                        user_id=user_id,
                        project_name=project_name,
                        candidate_id=candidate.candidate_id,
                        current_revision=1,
                        head_version=1,
                        created_at=candidate.created_at,
                        updated_at=candidate.created_at,
                    )
                )
                await self.session.flush()
        except IntegrityError as exc:
            raise CandidateConflictError("this candidate already exists") from exc

    async def get_exact(
        self, *, user_id: str, project_name: str, candidate_id: str, revision: int
    ) -> ExplorationRevision | None:
        row = (
            await self.session.execute(
                select(M8CandidateRevisionModel).where(
                    M8CandidateRevisionModel.user_id == user_id,
                    M8CandidateRevisionModel.project_name == project_name,
                    M8CandidateRevisionModel.candidate_id == candidate_id,
                    M8CandidateRevisionModel.revision == revision,
                )
            )
        ).scalar_one_or_none()
        return None if row is None else _revision_from_row(row)

    async def history(
        self, *, user_id: str, project_name: str, candidate_id: str, after_revision: int | None, limit: int
    ) -> tuple[ExplorationRevision, ...]:
        if not 1 <= limit <= MAX_HISTORY_PAGE:
            raise ValueError(f"limit must be in [1, {MAX_HISTORY_PAGE}]")
        statement = (
            select(M8CandidateRevisionModel)
            .where(
                M8CandidateRevisionModel.user_id == user_id,
                M8CandidateRevisionModel.project_name == project_name,
                M8CandidateRevisionModel.candidate_id == candidate_id,
            )
            .order_by(M8CandidateRevisionModel.revision)
            .limit(limit)
        )
        if after_revision is not None:
            statement = statement.where(M8CandidateRevisionModel.revision > after_revision)
        rows = (await self.session.execute(statement)).scalars().all()
        return tuple(_revision_from_row(row) for row in rows)

    # --- previews, authorizations and promotion receipts ----------------------------------

    async def stage_preview(self, *, user_id: str, preview: PromotionPreview) -> str:
        """Stage ``preview``; return its digest (the canonical digest of the complete model)."""
        preview_digest = digest_canonical(preview)
        self.session.add(
            M8PromotionPreviewModel(
                user_id=user_id,
                preview_id=preview.preview_id,
                project_name=preview.project_name,
                preview_command_id=preview.preview_command_id,
                candidate_id=preview.candidate_id,
                candidate_revision=preview.candidate_revision,
                candidate_payload_digest=preview.candidate_payload_digest,
                target_kind=preview.target.kind.value,
                target_ref=preview.target.target_ref,
                expected_target_version=preview.target.expected_target_version,
                expected_master_id=preview.expected_master_id,
                expected_master_digest=preview.expected_master_digest,
                impact_json=preview.impact.model_dump(mode="json"),
                impact_digest=preview.impact_digest,
                preview_digest=preview_digest,
                authorization_scope=preview.authorization_scope,
                issued_at=preview.issued_at,
                expires_at=preview.expires_at,
                ttl_seconds=int((preview.expires_at - preview.issued_at).total_seconds()),
            )
        )
        await self.session.flush()
        return preview_digest

    async def get_preview(
        self, *, user_id: str, project_name: str, preview_id: str, for_update: bool = False
    ) -> tuple[PromotionPreview, str] | None:
        """The scoped preview and its digest; ``for_update`` locks its row."""
        statement = select(M8PromotionPreviewModel).where(
            M8PromotionPreviewModel.user_id == user_id,
            M8PromotionPreviewModel.project_name == project_name,
            M8PromotionPreviewModel.preview_id == preview_id,
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await self.session.execute(statement)).scalar_one_or_none()
        return None if row is None else (_preview_from_row(row), row.preview_digest)

    async def stage_authorization(self, *, user_id: str, authorization: PromotionAuthorization) -> str:
        authorization_digest = digest_canonical(authorization)
        self.session.add(
            M8PromotionAuthorizationModel(
                user_id=user_id,
                project_name=authorization.project_name,
                command_id=authorization.command_id,
                preview_id=authorization.preview_id,
                preview_digest=authorization.preview_digest,
                actor_id=authorization.actor_id,
                actor_scope=authorization.actor_scope,
                decision=authorization.decision,
                authorized_at=authorization.authorized_at,
                authorization_digest=authorization_digest,
            )
        )
        await self.session.flush()
        return authorization_digest

    async def stage_promotion_receipt(
        self, *, user_id: str, receipt: PromotionReceipt, preview_id: str, authorization_digest: str
    ) -> None:
        self.session.add(
            M8PromotionReceiptModel(
                user_id=user_id,
                receipt_id=receipt.receipt_id,
                project_name=receipt.project_name,
                command_id=receipt.command_id,
                preview_id=preview_id,
                preview_digest=receipt.preview_digest,
                authorization_digest=authorization_digest,
                candidate_id=receipt.candidate_id,
                candidate_revision=receipt.candidate_revision,
                target_kind=receipt.target.kind.value,
                target_ref=receipt.target.target_ref,
                expected_target_version=receipt.target.expected_target_version,
                result_artifact_ref=receipt.result_artifact_ref,
                result_master_id=receipt.result_master_id,
                result_digest=receipt.result_digest,
                promoted_at=receipt.promoted_at,
            )
        )
        await self.session.flush()

    async def get_promotion_receipt(
        self, *, user_id: str, project_name: str, command_id: str
    ) -> PromotionReceipt | None:
        row = (
            await self.session.execute(
                select(M8PromotionReceiptModel).where(
                    M8PromotionReceiptModel.user_id == user_id,
                    M8PromotionReceiptModel.project_name == project_name,
                    M8PromotionReceiptModel.command_id == command_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return PromotionReceipt(
            receipt_id=row.receipt_id,
            command_id=row.command_id,
            project_name=row.project_name,
            preview_digest=row.preview_digest,
            candidate_id=row.candidate_id,
            candidate_revision=row.candidate_revision,
            target=PromotionTarget(
                kind=PromotionTargetKind(row.target_kind),
                target_ref=row.target_ref,
                expected_target_version=row.expected_target_version,
            ),
            result_artifact_ref=row.result_artifact_ref,
            result_master_id=row.result_master_id,
            result_digest=row.result_digest,
            promoted_at=_as_utc(row.promoted_at),
        )


__all__ = [
    "APPEND_REVISION",
    "MAX_HISTORY_PAGE",
    "PREVIEW",
    "PROMOTE",
    "CommandReceipt",
    "ExplorationRepository",
    "append_command_digest",
]
