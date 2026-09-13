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
from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.narrative_lifecycle import (
    ChangeSetReviewDecisionModel,
    ChangeSetReviewHeadModel,
    ConflictResolutionDecisionCompetitorModel,
    ConflictResolutionDecisionModel,
    ConflictResolutionHeadModel,
    ConflictResolutionLineageModel,
    NarrativeChangeSetModel,
    NarrativeDecisionIdentityModel,
    NarrativeDraftCandidateModel,
    NarrativeExtractionAttemptModel,
    NarrativeExtractionResultChangeSetModel,
    NarrativeExtractionResultModel,
    NarrativeRevisionModel,
    RevisionAcceptanceDecisionModel,
    RevisionAcceptanceHeadModel,
)
from lib.db.repositories.base import rowcount
from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewCommand,
    ChangeSetReviewHead,
    ConflictResolutionCommand,
    ConflictResolutionHead,
    ConflictResolutionLineage,
    ConflictSubject,
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeSet,
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeRevision,
    NarrativeWorkScope,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeAuthorityIntegrityError,
    NarrativeDecisionIdentityConflictError,
    NarrativeDecisionPredecessorConflict,
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


# --- M5C-2 decision authority: identity registry, typed decisions, lineage, heads ---


def _authorization_from_row(row: Any) -> NarrativeDecisionAuthorization:
    try:
        return NarrativeDecisionAuthorization(
            authorization_ref=row.authorization_ref,
            user_id=row.user_id,
            project_name=row.project_name,
            actor_id=row.authorization_actor_id,
            authority_role=row.authorization_authority_role,
            decision_family=row.decision_family,
            action=row.action,
            decision_id=row.decision_id,
            stable_subject_fingerprint=row.authorization_stable_subject_fingerprint,
            decision_command_fingerprint=row.authorization_decision_command_fingerprint,
            authenticated_at=_stored_aware(row.authorization_authenticated_at),
            authenticated_via=row.authorization_authenticated_via,
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(f"corrupt decision authorization on {row.decision_id!r}: {exc}") from exc


def _decision_work_scope(row: Any) -> dict[str, str]:
    return {
        "user_id": row.user_id,
        "project_name": row.project_name,
        "plan_id": row.plan_id,
        "scene_contract_id": row.scene_contract_id,
        "canon_branch_id": row.canon_branch_id,
    }


def _revision_command_from_row(row: RevisionAcceptanceDecisionModel) -> RevisionAcceptanceCommand:
    try:
        return RevisionAcceptanceCommand.model_validate(
            {
                "decision_id": row.decision_id,
                "action": row.action,
                "work_scope": _decision_work_scope(row),
                "selected_revision_id": row.selected_revision_id,
                "expected_latest_decision_id": row.expected_latest_decision_id,
                "expected_effective_decision_id": row.expected_effective_decision_id,
                "base_canon_version_id": row.base_canon_version_id,
                "plan_version": row.plan_version,
                "scene_contract_version": row.scene_contract_version,
                "context_pack_id": row.context_pack_id,
                "actor_id": row.actor_id,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(
            f"corrupt revision acceptance decision row {row.decision_id!r}: {exc}"
        ) from exc


def _change_set_review_command_from_row(row: ChangeSetReviewDecisionModel) -> ChangeSetReviewCommand:
    try:
        return ChangeSetReviewCommand.model_validate(
            {
                "decision_id": row.decision_id,
                "action": row.action,
                "work_scope": _decision_work_scope(row),
                "revision_acceptance_decision_id": row.revision_acceptance_decision_id,
                "change_set_lineage_id": row.change_set_lineage_id,
                "selected_change_set_id": row.selected_change_set_id,
                "expected_latest_decision_id": row.expected_latest_decision_id,
                "expected_effective_decision_id": row.expected_effective_decision_id,
                "base_canon_version_id": row.base_canon_version_id,
                "plan_version": row.plan_version,
                "scene_contract_version": row.scene_contract_version,
                "context_pack_id": row.context_pack_id,
                "actor_id": row.actor_id,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(
            f"corrupt change-set review decision row {row.decision_id!r}: {exc}"
        ) from exc


def _conflict_resolution_command_from_row(
    row: ConflictResolutionDecisionModel, *, competitors: tuple[tuple[str, str], ...]
) -> ConflictResolutionCommand:
    try:
        return ConflictResolutionCommand.model_validate(
            {
                "decision_id": row.decision_id,
                "action": row.action,
                "work_scope": _decision_work_scope(row),
                "revision_acceptance_decision_id": row.revision_acceptance_decision_id,
                "conflict_resolution_lineage_id": row.conflict_resolution_lineage_id,
                "competing_change_set_ids": tuple(change_set_id for change_set_id, _ in competitors),
                "competing_review_decision_ids": tuple(review_decision_id for _, review_decision_id in competitors),
                "chosen_resolution": row.chosen_resolution,
                "expected_latest_decision_id": row.expected_latest_decision_id,
                "expected_effective_decision_id": row.expected_effective_decision_id,
                "base_canon_version_id": row.base_canon_version_id,
                "plan_version": row.plan_version,
                "scene_contract_version": row.scene_contract_version,
                "context_pack_id": row.context_pack_id,
                "actor_id": row.actor_id,
            }
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(
            f"corrupt conflict resolution decision row {row.decision_id!r}: {exc}"
        ) from exc


def _decision_row_from_command(
    command: NarrativeDecisionCommand,
    authorization: NarrativeDecisionAuthorization,
    *,
    decision_generation: int,
    stored_at: datetime,
) -> RevisionAcceptanceDecisionModel | ChangeSetReviewDecisionModel | ConflictResolutionDecisionModel:
    common: dict[str, Any] = {
        "decision_id": command.decision_id,
        "user_id": authorization.user_id,
        "project_name": authorization.project_name,
        "decision_family": command.decision_family,
        "action": command.action,
        "expected_latest_decision_id": command.expected_latest_decision_id,
        "expected_effective_decision_id": command.expected_effective_decision_id,
        "base_canon_version_id": command.base_canon_version_id,
        "plan_version": command.plan_version,
        "scene_contract_version": command.scene_contract_version,
        "context_pack_id": command.context_pack_id,
        "actor_id": command.actor_id,
        "decision_generation": decision_generation,
        "authorization_ref": authorization.authorization_ref,
        "authorization_actor_id": authorization.actor_id,
        "authorization_authority_role": authorization.authority_role,
        "authorization_stable_subject_fingerprint": authorization.stable_subject_fingerprint,
        "authorization_decision_command_fingerprint": authorization.decision_command_fingerprint,
        "authorization_authenticated_at": authorization.authenticated_at,
        "authorization_authenticated_via": authorization.authenticated_via,
        "stored_at": stored_at,
    }
    if isinstance(command, RevisionAcceptanceCommand):
        scope = command.work_scope
        return RevisionAcceptanceDecisionModel(
            **common,
            plan_id=scope.plan_id,
            scene_contract_id=scope.scene_contract_id,
            canon_branch_id=scope.canon_branch_id,
            selected_revision_id=command.selected_revision_id,
        )
    if isinstance(command, ChangeSetReviewCommand):
        scope = command.work_scope
        return ChangeSetReviewDecisionModel(
            **common,
            plan_id=scope.plan_id,
            scene_contract_id=scope.scene_contract_id,
            canon_branch_id=scope.canon_branch_id,
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            change_set_lineage_id=command.change_set_lineage_id,
            selected_change_set_id=command.selected_change_set_id,
        )
    scope = command.work_scope
    return ConflictResolutionDecisionModel(
        **common,
        plan_id=scope.plan_id,
        scene_contract_id=scope.scene_contract_id,
        canon_branch_id=scope.canon_branch_id,
        revision_acceptance_decision_id=command.revision_acceptance_decision_id,
        conflict_resolution_lineage_id=command.conflict_resolution_lineage_id,
        chosen_resolution=command.chosen_resolution,
    )


def _lineage_row(
    lineage: ConflictResolutionLineage, *, user_id: str, project_name: str
) -> ConflictResolutionLineageModel:
    return ConflictResolutionLineageModel(
        revision_acceptance_decision_id=lineage.revision_acceptance_decision_id,
        conflict_resolution_lineage_id=lineage.conflict_resolution_lineage_id,
        user_id=user_id,
        project_name=project_name,
        conflict_subject_json=lineage.conflict_subject.model_dump(mode="json"),
        conflict_subject_fingerprint=lineage.conflict_subject_fingerprint,
        created_at=lineage.created_at,
        created_by=lineage.created_by,
    )


def _lineage_from_row(row: ConflictResolutionLineageModel) -> ConflictResolutionLineage:
    try:
        return ConflictResolutionLineage(
            conflict_resolution_lineage_id=row.conflict_resolution_lineage_id,
            revision_acceptance_decision_id=row.revision_acceptance_decision_id,
            conflict_subject=ConflictSubject.model_validate(row.conflict_subject_json),
            conflict_subject_fingerprint=row.conflict_subject_fingerprint,
            created_at=_stored_aware(row.created_at),
            created_by=row.created_by,
        )
    except ValidationError as exc:
        raise NarrativeEvidenceIntegrityError(
            f"corrupt conflict resolution lineage row {row.conflict_resolution_lineage_id!r}: {exc}"
        ) from exc


def _revision_head_from_row(row: RevisionAcceptanceHeadModel) -> RevisionAcceptanceHead:
    return RevisionAcceptanceHead(
        work_scope=NarrativeWorkScope(
            user_id=row.user_id,
            project_name=row.project_name,
            plan_id=row.plan_id,
            scene_contract_id=row.scene_contract_id,
            canon_branch_id=row.canon_branch_id,
        ),
        latest_decision_id=row.latest_decision_id,
        decision_generation=row.decision_generation,
        effective_decision_id=row.effective_decision_id,
        effective_generation=row.effective_generation,
    )


def _change_set_review_head_from_row(row: ChangeSetReviewHeadModel) -> ChangeSetReviewHead:
    return ChangeSetReviewHead(
        revision_acceptance_decision_id=row.revision_acceptance_decision_id,
        change_set_lineage_id=row.change_set_lineage_id,
        latest_decision_id=row.latest_decision_id,
        decision_generation=row.decision_generation,
        effective_decision_id=row.effective_decision_id,
        effective_generation=row.effective_generation,
    )


def _conflict_resolution_head_from_row(row: ConflictResolutionHeadModel) -> ConflictResolutionHead:
    return ConflictResolutionHead(
        revision_acceptance_decision_id=row.revision_acceptance_decision_id,
        conflict_resolution_lineage_id=row.conflict_resolution_lineage_id,
        latest_decision_id=row.latest_decision_id,
        decision_generation=row.decision_generation,
        effective_decision_id=row.effective_decision_id,
        effective_generation=row.effective_generation,
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

    # --- M5C-2 decision authority ---

    def _insert(self, table_class: type) -> Any:
        """Dialect-aware ``INSERT ... ON CONFLICT DO NOTHING`` builder."""
        return (
            pg_insert(table_class)
            if self.session.get_bind().dialect.name == "postgresql"
            else sqlite_insert(table_class)
        )

    async def get_decision_by_id(
        self, decision_id: str, *, user_id: str, project_name: str
    ) -> tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int] | None:
        """A plain scoped read: no lock, no insert (the kernel calls this before any head
        write). Returns ``None`` for an absent id or one that
        resolves outside ``(user_id, project_name)`` — the two cases are indistinguishable
        to the caller, matching every other exact-scope lookup in this repository."""
        identity = await self._scalar(
            select(NarrativeDecisionIdentityModel).where(NarrativeDecisionIdentityModel.decision_id == decision_id)
        )
        if identity is None or identity.user_id != user_id or identity.project_name != project_name:
            return None
        if identity.decision_family == "REVISION_ACCEPTANCE":
            revision_row = await self._scalar(
                select(RevisionAcceptanceDecisionModel).where(
                    RevisionAcceptanceDecisionModel.decision_id == decision_id
                )
            )
            if revision_row is None:
                raise NarrativeAuthorityIntegrityError(f"decision identity {decision_id!r} has no typed decision row")
            return (
                _revision_command_from_row(revision_row),
                _authorization_from_row(revision_row),
                revision_row.decision_generation,
            )
        if identity.decision_family == "CHANGE_SET_REVIEW":
            review_row = await self._scalar(
                select(ChangeSetReviewDecisionModel).where(ChangeSetReviewDecisionModel.decision_id == decision_id)
            )
            if review_row is None:
                raise NarrativeAuthorityIntegrityError(f"decision identity {decision_id!r} has no typed decision row")
            return (
                _change_set_review_command_from_row(review_row),
                _authorization_from_row(review_row),
                review_row.decision_generation,
            )
        conflict_row = await self._scalar(
            select(ConflictResolutionDecisionModel).where(ConflictResolutionDecisionModel.decision_id == decision_id)
        )
        if conflict_row is None:
            raise NarrativeAuthorityIntegrityError(f"decision identity {decision_id!r} has no typed decision row")
        return (
            _conflict_resolution_command_from_row(conflict_row, competitors=await self._competitors_of(decision_id)),
            _authorization_from_row(conflict_row),
            conflict_row.decision_generation,
        )

    async def _competitors_of(self, decision_id: str) -> tuple[tuple[str, str], ...]:
        rows = (
            await self.session.execute(
                select(
                    ConflictResolutionDecisionCompetitorModel.change_set_id,
                    ConflictResolutionDecisionCompetitorModel.review_decision_id,
                )
                .where(ConflictResolutionDecisionCompetitorModel.decision_id == decision_id)
                .order_by(ConflictResolutionDecisionCompetitorModel.position)
            )
        ).all()
        return tuple((row.change_set_id, row.review_decision_id) for row in rows)

    async def list_revision_decisions(
        self, work_scope: NarrativeWorkScope
    ) -> list[tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]]:
        """Every ``REVISION_ACCEPTANCE`` decision for this exact subject, in append
        order — the authoritative chain a head is rebuilt from."""
        rows = (
            await self.session.execute(
                select(RevisionAcceptanceDecisionModel)
                .where(
                    RevisionAcceptanceDecisionModel.user_id == work_scope.user_id,
                    RevisionAcceptanceDecisionModel.project_name == work_scope.project_name,
                    RevisionAcceptanceDecisionModel.plan_id == work_scope.plan_id,
                    RevisionAcceptanceDecisionModel.scene_contract_id == work_scope.scene_contract_id,
                    RevisionAcceptanceDecisionModel.canon_branch_id == work_scope.canon_branch_id,
                )
                .order_by(RevisionAcceptanceDecisionModel.decision_generation)
            )
        ).scalars()
        return [
            (_revision_command_from_row(row), _authorization_from_row(row), row.decision_generation) for row in rows
        ]

    async def list_change_set_review_decisions(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str
    ) -> list[tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]]:
        rows = (
            await self.session.execute(
                select(ChangeSetReviewDecisionModel)
                .where(
                    ChangeSetReviewDecisionModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                    ChangeSetReviewDecisionModel.change_set_lineage_id == change_set_lineage_id,
                )
                .order_by(ChangeSetReviewDecisionModel.decision_generation)
            )
        ).scalars()
        return [
            (_change_set_review_command_from_row(row), _authorization_from_row(row), row.decision_generation)
            for row in rows
        ]

    async def list_conflict_resolution_decisions(
        self, *, revision_acceptance_decision_id: str, conflict_resolution_lineage_id: str
    ) -> list[tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]]:
        rows = (
            await self.session.execute(
                select(ConflictResolutionDecisionModel)
                .where(
                    ConflictResolutionDecisionModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                    ConflictResolutionDecisionModel.conflict_resolution_lineage_id == conflict_resolution_lineage_id,
                )
                .order_by(ConflictResolutionDecisionModel.decision_generation)
            )
        ).scalars()
        return [
            (
                _conflict_resolution_command_from_row(row, competitors=await self._competitors_of(row.decision_id)),
                _authorization_from_row(row),
                row.decision_generation,
            )
            for row in rows
        ]

    async def insert_identity_and_decision(
        self,
        command: NarrativeDecisionCommand,
        authorization: NarrativeDecisionAuthorization,
        *,
        canonical_identity_hash: str,
        decision_generation: int,
        stored_at: datetime,
    ) -> None:
        """Insert the identity-registry row and the one typed decision row (plus, for a
        conflict resolution, its ordered competitor rows) in one transaction. Global
        decision-id reuse — in this family or another — fails closed with no writes.

        The identity row is flushed before the decision row: the decision's composite FK
        into the registry needs it on the wire first, and the two mapped classes share no
        ORM ``relationship()`` for SQLAlchemy to infer that ordering on its own.
        """
        self.session.add(
            NarrativeDecisionIdentityModel(
                decision_id=command.decision_id,
                user_id=authorization.user_id,
                project_name=authorization.project_name,
                decision_family=command.decision_family,
                canonical_identity_hash=canonical_identity_hash,
                stored_at=stored_at,
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise NarrativeDecisionIdentityConflictError(
                f"decision {command.decision_id!r} conflicts with an existing decision"
            ) from exc
        self.session.add(
            _decision_row_from_command(
                command, authorization, decision_generation=decision_generation, stored_at=stored_at
            )
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise NarrativeDecisionIdentityConflictError(
                f"decision {command.decision_id!r} conflicts with an existing decision"
            ) from exc
        if isinstance(command, ConflictResolutionCommand):
            for position, (change_set_id, review_decision_id) in enumerate(
                zip(command.competing_change_set_ids, command.competing_review_decision_ids, strict=True)
            ):
                self.session.add(
                    ConflictResolutionDecisionCompetitorModel(
                        decision_id=command.decision_id,
                        position=position,
                        user_id=authorization.user_id,
                        project_name=authorization.project_name,
                        change_set_id=change_set_id,
                        review_decision_id=review_decision_id,
                    )
                )
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise NarrativeDecisionIdentityConflictError(
                    f"decision {command.decision_id!r} names an invalid competing change set or review"
                ) from exc

    async def get_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None:
        """A plain scoped read: no lock, no insert. For observation reads
        (``get_current_revision_selection``), never for a command in progress — those
        take ``lock_or_insert_revision_head`` instead."""
        row = await self._scalar(
            select(RevisionAcceptanceHeadModel).where(
                RevisionAcceptanceHeadModel.user_id == work_scope.user_id,
                RevisionAcceptanceHeadModel.project_name == work_scope.project_name,
                RevisionAcceptanceHeadModel.plan_id == work_scope.plan_id,
                RevisionAcceptanceHeadModel.scene_contract_id == work_scope.scene_contract_id,
                RevisionAcceptanceHeadModel.canon_branch_id == work_scope.canon_branch_id,
            )
        )
        return _revision_head_from_row(row) if row is not None else None

    async def lock_existing_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None:
        """``SELECT ... FOR UPDATE``, no insert. For a caller that must hold the head
        stable across its own transaction (e.g. an extraction-admission currentness
        guard) without creating a phantom head when none exists yet."""
        row = await self._scalar(
            select(RevisionAcceptanceHeadModel)
            .where(
                RevisionAcceptanceHeadModel.user_id == work_scope.user_id,
                RevisionAcceptanceHeadModel.project_name == work_scope.project_name,
                RevisionAcceptanceHeadModel.plan_id == work_scope.plan_id,
                RevisionAcceptanceHeadModel.scene_contract_id == work_scope.scene_contract_id,
                RevisionAcceptanceHeadModel.canon_branch_id == work_scope.canon_branch_id,
            )
            .with_for_update()
        )
        return _revision_head_from_row(row) if row is not None else None

    async def get_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead | None:
        row = await self._scalar(
            select(ChangeSetReviewHeadModel).where(
                ChangeSetReviewHeadModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                ChangeSetReviewHeadModel.change_set_lineage_id == change_set_lineage_id,
            )
        )
        if row is None or row.user_id != user_id or row.project_name != project_name:
            return None
        return _change_set_review_head_from_row(row)

    async def lock_existing_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead | None:
        """``SELECT ... FOR UPDATE``, no insert — locks an already-existing lineage head
        so a concurrent decision on it cannot land between this read and the caller's
        own later write (e.g. a conflict-resolution genesis reading its competitors)."""
        row = await self._scalar(
            select(ChangeSetReviewHeadModel)
            .where(
                ChangeSetReviewHeadModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                ChangeSetReviewHeadModel.change_set_lineage_id == change_set_lineage_id,
            )
            .with_for_update()
        )
        if row is None or row.user_id != user_id or row.project_name != project_name:
            return None
        return _change_set_review_head_from_row(row)

    async def get_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> ConflictResolutionHead | None:
        row = await self._scalar(
            select(ConflictResolutionHeadModel).where(
                ConflictResolutionHeadModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                ConflictResolutionHeadModel.conflict_resolution_lineage_id == conflict_resolution_lineage_id,
            )
        )
        if row is None or row.user_id != user_id or row.project_name != project_name:
            return None
        return _conflict_resolution_head_from_row(row)

    async def lock_or_insert_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead:
        """``INSERT ... ON CONFLICT DO NOTHING`` the head by its complete stable key
        (null pointers, zero generations), then lock and return it. Called only after
        retry resolution, for a genuinely new decision id."""
        stmt = self._insert(RevisionAcceptanceHeadModel).values(
            user_id=work_scope.user_id,
            project_name=work_scope.project_name,
            plan_id=work_scope.plan_id,
            scene_contract_id=work_scope.scene_contract_id,
            canon_branch_id=work_scope.canon_branch_id,
            latest_decision_id=None,
            decision_generation=0,
            effective_decision_id=None,
            effective_generation=0,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["user_id", "project_name", "plan_id", "scene_contract_id", "canon_branch_id"]
        )
        await self.session.execute(stmt)
        row = await self._scalar(
            select(RevisionAcceptanceHeadModel)
            .where(
                RevisionAcceptanceHeadModel.user_id == work_scope.user_id,
                RevisionAcceptanceHeadModel.project_name == work_scope.project_name,
                RevisionAcceptanceHeadModel.plan_id == work_scope.plan_id,
                RevisionAcceptanceHeadModel.scene_contract_id == work_scope.scene_contract_id,
                RevisionAcceptanceHeadModel.canon_branch_id == work_scope.canon_branch_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NarrativeAuthorityIntegrityError("revision acceptance head vanished immediately after insert")
        return _revision_head_from_row(row)

    async def lock_or_insert_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead:
        stmt = self._insert(ChangeSetReviewHeadModel).values(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            change_set_lineage_id=change_set_lineage_id,
            user_id=user_id,
            project_name=project_name,
            latest_decision_id=None,
            decision_generation=0,
            effective_decision_id=None,
            effective_generation=0,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["revision_acceptance_decision_id", "change_set_lineage_id"])
        await self.session.execute(stmt)
        row = await self._scalar(
            select(ChangeSetReviewHeadModel)
            .where(
                ChangeSetReviewHeadModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                ChangeSetReviewHeadModel.change_set_lineage_id == change_set_lineage_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NarrativeAuthorityIntegrityError("change-set review head vanished immediately after insert")
        return _change_set_review_head_from_row(row)

    async def lock_or_insert_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        user_id: str,
        project_name: str,
    ) -> ConflictResolutionHead:
        stmt = self._insert(ConflictResolutionHeadModel).values(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            conflict_resolution_lineage_id=conflict_resolution_lineage_id,
            user_id=user_id,
            project_name=project_name,
            latest_decision_id=None,
            decision_generation=0,
            effective_decision_id=None,
            effective_generation=0,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["revision_acceptance_decision_id", "conflict_resolution_lineage_id"]
        )
        await self.session.execute(stmt)
        row = await self._scalar(
            select(ConflictResolutionHeadModel)
            .where(
                ConflictResolutionHeadModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                ConflictResolutionHeadModel.conflict_resolution_lineage_id == conflict_resolution_lineage_id,
            )
            .with_for_update()
        )
        if row is None:
            raise NarrativeAuthorityIntegrityError("conflict resolution head vanished immediately after insert")
        return _conflict_resolution_head_from_row(row)

    async def advance_revision_head(
        self,
        work_scope: NarrativeWorkScope,
        *,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None:
        """Update the head with its expected pointers in the predicate; affects exactly
        one row or raises. ``effective_generation`` only advances in the same update that
        changes ``effective_decision_id`` (the caller passes both together)."""
        latest_predicate = (
            RevisionAcceptanceHeadModel.latest_decision_id.is_(None)
            if expected_latest_decision_id is None
            else RevisionAcceptanceHeadModel.latest_decision_id == expected_latest_decision_id
        )
        effective_predicate = (
            RevisionAcceptanceHeadModel.effective_decision_id.is_(None)
            if expected_effective_decision_id is None
            else RevisionAcceptanceHeadModel.effective_decision_id == expected_effective_decision_id
        )
        result = await self.session.execute(
            update(RevisionAcceptanceHeadModel)
            .where(
                RevisionAcceptanceHeadModel.user_id == work_scope.user_id,
                RevisionAcceptanceHeadModel.project_name == work_scope.project_name,
                RevisionAcceptanceHeadModel.plan_id == work_scope.plan_id,
                RevisionAcceptanceHeadModel.scene_contract_id == work_scope.scene_contract_id,
                RevisionAcceptanceHeadModel.canon_branch_id == work_scope.canon_branch_id,
                latest_predicate,
                effective_predicate,
            )
            .values(
                latest_decision_id=new_latest_decision_id,
                decision_generation=new_decision_generation,
                effective_decision_id=new_effective_decision_id,
                effective_generation=new_effective_generation,
            )
        )
        if rowcount(result) != 1:
            raise NarrativeDecisionPredecessorConflict("expected revision acceptance head predecessor is stale")

    async def advance_change_set_review_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        change_set_lineage_id: str,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None:
        latest_predicate = (
            ChangeSetReviewHeadModel.latest_decision_id.is_(None)
            if expected_latest_decision_id is None
            else ChangeSetReviewHeadModel.latest_decision_id == expected_latest_decision_id
        )
        effective_predicate = (
            ChangeSetReviewHeadModel.effective_decision_id.is_(None)
            if expected_effective_decision_id is None
            else ChangeSetReviewHeadModel.effective_decision_id == expected_effective_decision_id
        )
        result = await self.session.execute(
            update(ChangeSetReviewHeadModel)
            .where(
                ChangeSetReviewHeadModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                ChangeSetReviewHeadModel.change_set_lineage_id == change_set_lineage_id,
                latest_predicate,
                effective_predicate,
            )
            .values(
                latest_decision_id=new_latest_decision_id,
                decision_generation=new_decision_generation,
                effective_decision_id=new_effective_decision_id,
                effective_generation=new_effective_generation,
            )
        )
        if rowcount(result) != 1:
            raise NarrativeDecisionPredecessorConflict("expected change-set review head predecessor is stale")

    async def advance_conflict_resolution_head(
        self,
        *,
        revision_acceptance_decision_id: str,
        conflict_resolution_lineage_id: str,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None:
        latest_predicate = (
            ConflictResolutionHeadModel.latest_decision_id.is_(None)
            if expected_latest_decision_id is None
            else ConflictResolutionHeadModel.latest_decision_id == expected_latest_decision_id
        )
        effective_predicate = (
            ConflictResolutionHeadModel.effective_decision_id.is_(None)
            if expected_effective_decision_id is None
            else ConflictResolutionHeadModel.effective_decision_id == expected_effective_decision_id
        )
        result = await self.session.execute(
            update(ConflictResolutionHeadModel)
            .where(
                ConflictResolutionHeadModel.revision_acceptance_decision_id == revision_acceptance_decision_id,
                ConflictResolutionHeadModel.conflict_resolution_lineage_id == conflict_resolution_lineage_id,
                latest_predicate,
                effective_predicate,
            )
            .values(
                latest_decision_id=new_latest_decision_id,
                decision_generation=new_decision_generation,
                effective_decision_id=new_effective_decision_id,
                effective_generation=new_effective_generation,
            )
        )
        if rowcount(result) != 1:
            raise NarrativeDecisionPredecessorConflict("expected conflict resolution head predecessor is stale")

    async def insert_conflict_lineage(
        self, lineage: ConflictResolutionLineage, *, user_id: str, project_name: str
    ) -> ConflictResolutionLineage:
        """``INSERT ... ON CONFLICT DO NOTHING`` by the subject-unique constraint, then
        read back whichever lineage now owns that ``(revision_acceptance_decision_id,
        conflict_subject_fingerprint)`` pair — the caller's own insert, or a competitor's
        that landed first. The caller compares the returned lineage id against its
        proposed one to detect that race; this method never raises on a losing insert."""
        try:
            async with self.session.begin_nested():
                self.session.add(_lineage_row(lineage, user_id=user_id, project_name=project_name))
                await self.session.flush()
            return lineage
        except IntegrityError:
            existing = await self._scalar(
                select(ConflictResolutionLineageModel).where(
                    ConflictResolutionLineageModel.revision_acceptance_decision_id
                    == lineage.revision_acceptance_decision_id,
                    ConflictResolutionLineageModel.conflict_subject_fingerprint == lineage.conflict_subject_fingerprint,
                )
            )
            if existing is None:
                raise
            return _lineage_from_row(existing)
