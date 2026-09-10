"""Scoped, transaction-bound adapter for the append-only Narrative-lifecycle evidence.

``NarrativeLifecycleRepository`` exposes exact scoped reads and append-only writes. It
never commits, rolls back, or constructs a session; the unit of work owns that. Every
read predicate carries ``(user_id, project_name)`` so an unknown id and a cross-scope id
return the same ``None``. The cross-row rule "a SUCCEEDED result owns >=1 ordered
change-set row, a non-success result owns none" is enforced here, inside the transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.narrative_lifecycle import (
    NarrativeChangeSetModel,
    NarrativeDraftCandidateModel,
    NarrativeExtractionAttemptModel,
    NarrativeExtractionResultChangeSetModel,
    NarrativeExtractionResultModel,
    NarrativeRevisionModel,
)
from r2.contracts.narrative_lifecycle import (
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeSet,
    NarrativeRevision,
)
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeEvidenceIdentityConflictError,
    NarrativeEvidenceIntegrityError,
)


def _mentions(exc: IntegrityError, needle: str) -> bool:
    return needle in str(getattr(exc, "orig", None) or exc).lower()


def _identity_conflict(exc: IntegrityError, subject: str) -> Exception:
    if _mentions(exc, "generation"):
        return NarrativeAttemptGenerationConflict(f"{subject} conflicts with an existing attempt generation")
    return NarrativeEvidenceIdentityConflictError(f"{subject} was already recorded with a different tuple")


def _stored_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _candidate_from_row(row: NarrativeDraftCandidateModel) -> DraftCandidate:
    try:
        return DraftCandidate.model_validate(
            {
                "candidate_id": row.candidate_id,
                "work_scope": {
                    "user_id": row.user_id,
                    "project_name": row.project_name,
                    "plan_id": row.plan_id,
                    "scene_contract_id": row.scene_contract_id,
                    "canon_branch_id": row.canon_branch_id,
                },
                "base_canon_version_id": row.base_canon_version_id,
                "plan_version": row.plan_version,
                "scene_contract_version": row.scene_contract_version,
                "context_pack_id": row.context_pack_id,
                "normalized_content": row.normalized_content,
                "content_hash": row.content_hash,
                "writer_kind": row.writer_kind,
                "writer_version": row.writer_version,
                "provenance": row.provenance_json,
                "created_at": _stored_aware(row.created_at),
                "created_by": row.created_by,
                "semantic_fingerprint": row.semantic_fingerprint,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(f"corrupt draft candidate row {row.candidate_id!r}: {exc}") from exc


def _revision_from_row(row: NarrativeRevisionModel) -> NarrativeRevision:
    try:
        return NarrativeRevision.model_validate(
            {
                "revision_id": row.revision_id,
                "work_scope": {
                    "user_id": row.user_id,
                    "project_name": row.project_name,
                    "plan_id": row.plan_id,
                    "scene_contract_id": row.scene_contract_id,
                    "canon_branch_id": row.canon_branch_id,
                },
                "base_candidate_id": row.base_candidate_id,
                "predecessor_revision_id": row.predecessor_revision_id,
                "base_canon_version_id": row.base_canon_version_id,
                "plan_version": row.plan_version,
                "scene_contract_version": row.scene_contract_version,
                "context_pack_id": row.context_pack_id,
                "normalized_content": row.normalized_content,
                "content_hash": row.content_hash,
                "review_refs": row.review_refs_json,
                "provenance": row.provenance_json,
                "created_at": _stored_aware(row.created_at),
                "created_by": row.created_by,
                "semantic_fingerprint": row.semantic_fingerprint,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(f"corrupt narrative revision row {row.revision_id!r}: {exc}") from exc


def _attempt_from_row(row: NarrativeExtractionAttemptModel) -> ExtractionAttempt:
    try:
        return ExtractionAttempt.model_validate(
            {
                "attempt_id": row.attempt_id,
                "generation": row.generation,
                "work_scope": {
                    "user_id": row.user_id,
                    "project_name": row.project_name,
                    "plan_id": row.plan_id,
                    "scene_contract_id": row.scene_contract_id,
                    "canon_branch_id": row.canon_branch_id,
                },
                "revision_id": row.revision_id,
                "revision_acceptance_decision_id": row.revision_acceptance_decision_id,
                "observed_revision_effective_generation": row.observed_revision_effective_generation,
                "base_canon_version_id": row.base_canon_version_id,
                "plan_version": row.plan_version,
                "scene_contract_version": row.scene_contract_version,
                "context_pack_id": row.context_pack_id,
                "extractor_kind": row.extractor_kind,
                "extractor_version": row.extractor_version,
                "policy_ref": row.policy_ref,
                "policy_version": row.policy_version,
                "admitted_at": _stored_aware(row.admitted_at),
                "admitted_by": row.admitted_by,
                "input_fingerprint": row.input_fingerprint,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(f"corrupt extraction attempt row {row.attempt_id!r}: {exc}") from exc


def _result_from_row(row: NarrativeExtractionResultModel, change_set_ids: tuple[str, ...]) -> ExtractionResult:
    try:
        return ExtractionResult.model_validate(
            {
                "result_id": row.result_id,
                "attempt_id": row.attempt_id,
                "generation": row.generation,
                "outcome": row.outcome,
                "change_set_ids": change_set_ids,
                "diagnostics": row.diagnostics_json,
                "provider_receipt": row.provider_receipt_json,
                "completed_at": _stored_aware(row.completed_at),
                "output_fingerprint": row.output_fingerprint,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(f"corrupt extraction result row {row.result_id!r}: {exc}") from exc


def _change_set_from_row(row: NarrativeChangeSetModel) -> NarrativeChangeSet:
    try:
        return NarrativeChangeSet.model_validate(
            {
                "change_set_id": row.change_set_id,
                "change_set_lineage_id": row.change_set_lineage_id,
                "source_revision_id": row.source_revision_id,
                "extraction_attempt_id": row.extraction_attempt_id,
                "extraction_generation": row.extraction_generation,
                "base_canon_version_id": row.base_canon_version_id,
                "source_spans": row.source_spans_json,
                "semantic_effect_keys": row.semantic_effect_keys_json,
                "changes": row.changes_json,
                "confidence": row.confidence,
                "extractor_version": row.extractor_version,
                "policy_ref": row.policy_ref,
                "policy_version": row.policy_version,
                "created_at": _stored_aware(row.created_at),
                "output_fingerprint": row.output_fingerprint,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(f"corrupt narrative change set row {row.change_set_id!r}: {exc}") from exc


def _candidate_row(candidate: DraftCandidate) -> NarrativeDraftCandidateModel:
    scope = candidate.work_scope
    return NarrativeDraftCandidateModel(
        candidate_id=candidate.candidate_id,
        user_id=scope.user_id,
        project_name=scope.project_name,
        plan_id=scope.plan_id,
        scene_contract_id=scope.scene_contract_id,
        canon_branch_id=scope.canon_branch_id,
        base_canon_version_id=candidate.base_canon_version_id,
        plan_version=candidate.plan_version,
        scene_contract_version=candidate.scene_contract_version,
        context_pack_id=candidate.context_pack_id,
        normalized_content=candidate.normalized_content,
        content_hash=candidate.content_hash,
        writer_kind=candidate.writer_kind,
        writer_version=candidate.writer_version,
        provenance_json=candidate.provenance.model_dump(mode="json"),
        created_at=candidate.created_at,
        created_by=candidate.created_by,
        semantic_fingerprint=candidate.semantic_fingerprint,
    )


def _revision_row(revision: NarrativeRevision) -> NarrativeRevisionModel:
    scope = revision.work_scope
    return NarrativeRevisionModel(
        revision_id=revision.revision_id,
        user_id=scope.user_id,
        project_name=scope.project_name,
        plan_id=scope.plan_id,
        scene_contract_id=scope.scene_contract_id,
        canon_branch_id=scope.canon_branch_id,
        base_candidate_id=revision.base_candidate_id,
        predecessor_revision_id=revision.predecessor_revision_id,
        base_canon_version_id=revision.base_canon_version_id,
        plan_version=revision.plan_version,
        scene_contract_version=revision.scene_contract_version,
        context_pack_id=revision.context_pack_id,
        normalized_content=revision.normalized_content,
        content_hash=revision.content_hash,
        review_refs_json=list(revision.review_refs),
        provenance_json=revision.provenance.model_dump(mode="json"),
        created_at=revision.created_at,
        created_by=revision.created_by,
        semantic_fingerprint=revision.semantic_fingerprint,
    )


def _attempt_row(attempt: ExtractionAttempt) -> NarrativeExtractionAttemptModel:
    scope = attempt.work_scope
    return NarrativeExtractionAttemptModel(
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        user_id=scope.user_id,
        project_name=scope.project_name,
        plan_id=scope.plan_id,
        scene_contract_id=scope.scene_contract_id,
        canon_branch_id=scope.canon_branch_id,
        revision_id=attempt.revision_id,
        revision_acceptance_decision_id=attempt.revision_acceptance_decision_id,
        observed_revision_effective_generation=attempt.observed_revision_effective_generation,
        base_canon_version_id=attempt.base_canon_version_id,
        plan_version=attempt.plan_version,
        scene_contract_version=attempt.scene_contract_version,
        context_pack_id=attempt.context_pack_id,
        extractor_kind=attempt.extractor_kind,
        extractor_version=attempt.extractor_version,
        policy_ref=attempt.policy_ref,
        policy_version=attempt.policy_version,
        admitted_at=attempt.admitted_at,
        admitted_by=attempt.admitted_by,
        input_fingerprint=attempt.input_fingerprint,
    )


def _result_row(result: ExtractionResult, *, user_id: str, project_name: str) -> NarrativeExtractionResultModel:
    return NarrativeExtractionResultModel(
        result_id=result.result_id,
        user_id=user_id,
        project_name=project_name,
        attempt_id=result.attempt_id,
        generation=result.generation,
        outcome=result.outcome,
        diagnostics_json=list(result.diagnostics),
        provider_receipt_json=result.provider_receipt,
        completed_at=result.completed_at,
        output_fingerprint=result.output_fingerprint,
    )


def _change_set_row(change_set: NarrativeChangeSet, *, user_id: str, project_name: str) -> NarrativeChangeSetModel:
    return NarrativeChangeSetModel(
        change_set_id=change_set.change_set_id,
        user_id=user_id,
        project_name=project_name,
        change_set_lineage_id=change_set.change_set_lineage_id,
        source_revision_id=change_set.source_revision_id,
        extraction_attempt_id=change_set.extraction_attempt_id,
        extraction_generation=change_set.extraction_generation,
        base_canon_version_id=change_set.base_canon_version_id,
        source_spans_json=[span.model_dump(mode="json") for span in change_set.source_spans],
        semantic_effect_keys_json=[key.model_dump(mode="json") for key in change_set.semantic_effect_keys],
        changes_json=[change.model_dump(mode="json") for change in change_set.changes],
        confidence=change_set.confidence,
        extractor_version=change_set.extractor_version,
        policy_ref=change_set.policy_ref,
        policy_version=change_set.policy_version,
        created_at=change_set.created_at,
        output_fingerprint=change_set.output_fingerprint,
    )


class NarrativeLifecycleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _scalar(self, stmt: Select[Any]) -> Any:
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_exact_draft_candidate(
        self, *, candidate_id: str, project_name: str, user_id: str
    ) -> DraftCandidate | None:
        row = await self._scalar(
            select(NarrativeDraftCandidateModel).where(
                NarrativeDraftCandidateModel.candidate_id == candidate_id,
                NarrativeDraftCandidateModel.project_name == project_name,
                NarrativeDraftCandidateModel.user_id == user_id,
            )
        )
        return _candidate_from_row(row) if row is not None else None

    async def get_exact_revision(
        self, *, revision_id: str, project_name: str, user_id: str
    ) -> NarrativeRevision | None:
        row = await self._scalar(
            select(NarrativeRevisionModel).where(
                NarrativeRevisionModel.revision_id == revision_id,
                NarrativeRevisionModel.project_name == project_name,
                NarrativeRevisionModel.user_id == user_id,
            )
        )
        return _revision_from_row(row) if row is not None else None

    async def get_exact_extraction_attempt(
        self, *, attempt_id: str, project_name: str, user_id: str
    ) -> ExtractionAttempt | None:
        row = await self._scalar(
            select(NarrativeExtractionAttemptModel).where(
                NarrativeExtractionAttemptModel.attempt_id == attempt_id,
                NarrativeExtractionAttemptModel.project_name == project_name,
                NarrativeExtractionAttemptModel.user_id == user_id,
            )
        )
        return _attempt_from_row(row) if row is not None else None

    async def get_extraction_attempt_by_id(self, *, attempt_id: str) -> ExtractionAttempt | None:
        # ``attempt_id`` is database-global (a PK). The lookup is not scope-filtered so a
        # scopeless result / change set can resolve its owning tenant from the admitted
        # attempt; the returned contract carries that ``work_scope``.
        row = await self._scalar(
            select(NarrativeExtractionAttemptModel).where(NarrativeExtractionAttemptModel.attempt_id == attempt_id)
        )
        return _attempt_from_row(row) if row is not None else None

    async def get_exact_extraction_result(
        self, *, attempt_id: str, generation: int, project_name: str, user_id: str
    ) -> ExtractionResult | None:
        row = await self._scalar(
            select(NarrativeExtractionResultModel).where(
                NarrativeExtractionResultModel.attempt_id == attempt_id,
                NarrativeExtractionResultModel.generation == generation,
                NarrativeExtractionResultModel.project_name == project_name,
                NarrativeExtractionResultModel.user_id == user_id,
            )
        )
        if row is None:
            return None
        change_set_ids = tuple(
            (
                await self.session.execute(
                    select(NarrativeExtractionResultChangeSetModel.change_set_id)
                    .where(
                        NarrativeExtractionResultChangeSetModel.result_id == row.result_id,
                        NarrativeExtractionResultChangeSetModel.project_name == project_name,
                        NarrativeExtractionResultChangeSetModel.user_id == user_id,
                    )
                    .order_by(NarrativeExtractionResultChangeSetModel.position)
                )
            )
            .scalars()
            .all()
        )
        return _result_from_row(row, change_set_ids)

    async def get_exact_change_set(
        self, *, change_set_id: str, project_name: str, user_id: str
    ) -> NarrativeChangeSet | None:
        row = await self._scalar(
            select(NarrativeChangeSetModel).where(
                NarrativeChangeSetModel.change_set_id == change_set_id,
                NarrativeChangeSetModel.project_name == project_name,
                NarrativeChangeSetModel.user_id == user_id,
            )
        )
        return _change_set_from_row(row) if row is not None else None

    async def insert_draft_candidate(self, candidate: DraftCandidate) -> None:
        self.session.add(_candidate_row(candidate))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _identity_conflict(exc, f"draft candidate {candidate.candidate_id!r}") from exc

    async def insert_revision(self, revision: NarrativeRevision) -> None:
        self.session.add(_revision_row(revision))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _identity_conflict(exc, f"narrative revision {revision.revision_id!r}") from exc

    async def insert_extraction_attempt(self, attempt: ExtractionAttempt) -> None:
        self.session.add(_attempt_row(attempt))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _identity_conflict(exc, f"extraction attempt {attempt.attempt_id!r}") from exc

    async def _attempt_scope(self, *, attempt_id: str, generation: int) -> tuple[str, str]:
        """The ``(user_id, project_name)`` of the admitted attempt an evidence result or
        change set descends from. An extraction result and change set carry no scope of
        their own — they inherit the attempt's tenant."""
        row = await self._scalar(
            select(NarrativeExtractionAttemptModel).where(
                NarrativeExtractionAttemptModel.attempt_id == attempt_id,
                NarrativeExtractionAttemptModel.generation == generation,
            )
        )
        if row is None:
            raise NarrativeEvidenceIntegrityError(
                f"no admitted extraction attempt {attempt_id!r} generation {generation} for this result"
            )
        return row.user_id, row.project_name

    async def insert_successful_extraction(
        self, result: ExtractionResult, change_sets: tuple[NarrativeChangeSet, ...]
    ) -> None:
        if result.outcome != "SUCCEEDED":
            raise NarrativeEvidenceIntegrityError("insert_successful_extraction requires a SUCCEEDED result")
        declared = tuple(result.change_set_ids)
        supplied = tuple(change_set.change_set_id for change_set in change_sets)
        if not declared or declared != supplied:
            raise NarrativeEvidenceIntegrityError(
                "the SUCCEEDED result's declared change_set_ids must equal the supplied change sets exactly and in order"
            )
        if any(
            (change_set.extraction_attempt_id, change_set.extraction_generation)
            != (result.attempt_id, result.generation)
            for change_set in change_sets
        ):
            raise NarrativeEvidenceIntegrityError("every change set must name the result's exact attempt generation")
        user_id, project_name = await self._attempt_scope(attempt_id=result.attempt_id, generation=result.generation)
        self.session.add(_result_row(result, user_id=user_id, project_name=project_name))
        for change_set in change_sets:
            self.session.add(_change_set_row(change_set, user_id=user_id, project_name=project_name))
        # The ordered association rows carry composite FKs to both the result and every
        # change set, so their targets must be on the wire first. This is one transaction:
        # any failure below rolls the whole bundle back with the unit of work.
        try:
            await self.session.flush()
            for position, change_set in enumerate(change_sets):
                self.session.add(
                    NarrativeExtractionResultChangeSetModel(
                        result_id=result.result_id,
                        change_set_id=change_set.change_set_id,
                        user_id=user_id,
                        project_name=project_name,
                        position=position,
                    )
                )
            await self.session.flush()
        except IntegrityError as exc:
            raise _identity_conflict(exc, f"successful extraction result {result.result_id!r}") from exc

    async def insert_non_successful_extraction(self, result: ExtractionResult) -> None:
        if result.outcome == "SUCCEEDED":
            raise NarrativeEvidenceIntegrityError("insert_non_successful_extraction rejects a SUCCEEDED result")
        if result.change_set_ids:
            raise NarrativeEvidenceIntegrityError("a non-success extraction result declares no change sets")
        user_id, project_name = await self._attempt_scope(attempt_id=result.attempt_id, generation=result.generation)
        self.session.add(_result_row(result, user_id=user_id, project_name=project_name))
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise _identity_conflict(exc, f"extraction result {result.result_id!r}") from exc

    async def flush(self) -> None:
        await self.session.flush()
