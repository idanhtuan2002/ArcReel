"""``NarrativeLifecycleEvidenceService`` — the only public append capability for
non-authority lifecycle evidence.

Every write is immutable and idempotent: an exact retry compares the full stored tuple
and performs no write; any partial or mismatched retry fails with no write. The service
holds no head-*mutation* port — but ``admit_extraction`` does read-lock the revision
head to prove currentness atomically with admitting the attempt, via the same
transaction-bound repository every other method here already uses.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from pydantic import ConfigDict, Field

from r2.contracts.common import NonEmptyStr, R2ContractModel
from r2.contracts.narrative_lifecycle import (
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeSet,
    NarrativeRevision,
    NarrativeWorkScope,
)
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeDecisionApplicabilityError,
    NarrativeEvidenceIdentityConflictError,
    NarrativeEvidenceIntegrityError,
)
from r2.narrative_lifecycle.hashing import compute_extraction_input_fingerprint
from r2.narrative_lifecycle.ports import NarrativeLifecycleEvidenceRepositoryPort, NarrativeLifecycleUnitOfWorkFactory

_SHARED_BASIS_FIELDS = ("base_canon_version_id", "plan_version", "scene_contract_version", "context_pack_id")


class ExtractionAdmissionCommand(R2ContractModel):
    """The request to admit an extraction attempt against its exact currently
    effective revision selection. ``attempt_id`` is deterministically
    ``f"{revision_id}:{generation}"`` — a revision's extraction attempts are its own
    generation-numbered sequence, so a continuation after an ``OUTCOME_UNKNOWN`` result
    is simply a fresh command naming the next generation for the same revision."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    work_scope: NarrativeWorkScope
    revision_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    revision_acceptance_decision_id: NonEmptyStr
    extractor_kind: NonEmptyStr
    extractor_version: NonEmptyStr
    policy_ref: NonEmptyStr
    policy_version: NonEmptyStr
    authenticated_principal: NonEmptyStr


def _require_matching_bases(candidate: DraftCandidate, revision: NarrativeRevision) -> None:
    for field in _SHARED_BASIS_FIELDS:
        if getattr(candidate, field) != getattr(revision, field):
            raise NarrativeEvidenceIntegrityError(
                f"revision {revision.revision_id!r} {field} disagrees with its base draft candidate"
            )


async def _stored_change_sets(
    repo: NarrativeLifecycleEvidenceRepositoryPort, *, ids: Sequence[str], scope: NarrativeWorkScope
) -> tuple[NarrativeChangeSet, ...]:
    loaded: list[NarrativeChangeSet] = []
    for change_set_id in ids:
        found = await repo.get_exact_change_set(
            change_set_id=change_set_id, project_name=scope.project_name, user_id=scope.user_id
        )
        if found is None:
            raise NarrativeEvidenceIntegrityError(
                f"stored extraction result references a missing change set {change_set_id!r}"
            )
        loaded.append(found)
    return tuple(loaded)


class NarrativeLifecycleEvidenceService:
    def __init__(self, uow_factory: NarrativeLifecycleUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def record_draft_candidate(self, candidate: DraftCandidate) -> DraftCandidate:
        scope = candidate.work_scope
        async with self._uow_factory() as uow:
            existing = await uow.repository.get_exact_draft_candidate(
                candidate_id=candidate.candidate_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if existing is not None:
                if existing == candidate:
                    return existing
                raise NarrativeEvidenceIdentityConflictError(
                    f"draft candidate {candidate.candidate_id!r} was already recorded with different content"
                )
            await uow.repository.insert_draft_candidate(candidate)
            await uow.commit()
            return candidate

    async def record_revision(self, revision: NarrativeRevision) -> NarrativeRevision:
        scope = revision.work_scope
        async with self._uow_factory() as uow:
            repo = uow.repository
            existing = await repo.get_exact_revision(
                revision_id=revision.revision_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if existing is not None:
                if existing == revision:
                    return existing
                raise NarrativeEvidenceIdentityConflictError(
                    f"narrative revision {revision.revision_id!r} was already recorded with different content"
                )

            candidate = await repo.get_exact_draft_candidate(
                candidate_id=revision.base_candidate_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if candidate is None:
                raise NarrativeEvidenceIntegrityError(
                    f"base draft candidate {revision.base_candidate_id!r} is absent or outside this scope"
                )
            if candidate.work_scope != scope:
                raise NarrativeEvidenceIntegrityError("base draft candidate belongs to a different work scope")
            _require_matching_bases(candidate, revision)

            if revision.predecessor_revision_id is not None:
                predecessor = await repo.get_exact_revision(
                    revision_id=revision.predecessor_revision_id,
                    project_name=scope.project_name,
                    user_id=scope.user_id,
                )
                if predecessor is None:
                    raise NarrativeEvidenceIntegrityError(
                        f"predecessor revision {revision.predecessor_revision_id!r} is absent or outside this scope"
                    )
                if predecessor.work_scope != scope:
                    raise NarrativeEvidenceIntegrityError("predecessor revision belongs to a different work scope")

            await repo.insert_revision(revision)
            await uow.commit()
            return revision

    async def record_successful_extraction(
        self, result: ExtractionResult, change_sets: Sequence[NarrativeChangeSet]
    ) -> ExtractionResult:
        if result.outcome != "SUCCEEDED":
            raise NarrativeEvidenceIntegrityError("record_successful_extraction requires a SUCCEEDED result")
        supplied = tuple(change_sets)
        async with self._uow_factory() as uow:
            repo = uow.repository
            scope = await self._attempt_scope(repo, result)
            existing = await repo.get_exact_extraction_result(
                attempt_id=result.attempt_id,
                generation=result.generation,
                project_name=scope.project_name,
                user_id=scope.user_id,
            )
            if existing is not None:
                stored_change_sets = await _stored_change_sets(repo, ids=existing.change_set_ids, scope=scope)
                if existing == result and stored_change_sets == supplied:
                    return existing
                raise NarrativeAttemptGenerationConflict(
                    "a different result is already recorded for this attempt generation"
                )
            await repo.insert_successful_extraction(result, supplied)
            await uow.commit()
            return result

    async def record_non_successful_extraction(self, result: ExtractionResult) -> ExtractionResult:
        if result.outcome == "SUCCEEDED":
            raise NarrativeEvidenceIntegrityError("record_non_successful_extraction rejects a SUCCEEDED result")
        if result.change_set_ids:
            raise NarrativeEvidenceIntegrityError("a non-success extraction result declares no change sets")
        async with self._uow_factory() as uow:
            repo = uow.repository
            scope = await self._attempt_scope(repo, result)
            existing = await repo.get_exact_extraction_result(
                attempt_id=result.attempt_id,
                generation=result.generation,
                project_name=scope.project_name,
                user_id=scope.user_id,
            )
            if existing is not None:
                if existing == result:
                    return existing
                raise NarrativeAttemptGenerationConflict(
                    "a different result is already recorded for this attempt generation"
                )
            await repo.insert_non_successful_extraction(result)
            await uow.commit()
            return result

    async def admit_extraction(self, command: ExtractionAdmissionCommand) -> ExtractionAttempt:
        """The attempt's admission instant is atomic with its currentness proof.
        ``revision_acceptance_decision_id`` must be the exact current effective
        revision selection at lock time — a later supersession blocks new admissions
        for that revision but never deletes an attempt/result already recorded."""
        scope = command.work_scope
        async with self._uow_factory() as uow:
            repo = uow.repository
            revision = await repo.get_exact_revision(
                revision_id=command.revision_id, project_name=scope.project_name, user_id=scope.user_id
            )
            if revision is None:
                raise NarrativeEvidenceIntegrityError(f"revision {command.revision_id!r} does not resolve")
            if revision.work_scope != scope:
                raise NarrativeEvidenceIntegrityError("revision belongs to a different work scope")

            head = await repo.lock_existing_revision_head(scope)
            if head is None or head.effective_decision_id != command.revision_acceptance_decision_id:
                raise NarrativeDecisionApplicabilityError(
                    f"revision acceptance {command.revision_acceptance_decision_id!r} "
                    "is not the current effective revision"
                )

            attempt_id = f"{command.revision_id}:{command.generation}"
            existing = await repo.get_exact_extraction_attempt(
                attempt_id=attempt_id, project_name=scope.project_name, user_id=scope.user_id
            )
            candidate = ExtractionAttempt(
                attempt_id=attempt_id,
                generation=command.generation,
                work_scope=scope,
                revision_id=command.revision_id,
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                observed_revision_effective_generation=head.effective_generation,
                base_canon_version_id=revision.base_canon_version_id,
                plan_version=revision.plan_version,
                scene_contract_version=revision.scene_contract_version,
                context_pack_id=revision.context_pack_id,
                extractor_kind=command.extractor_kind,
                extractor_version=command.extractor_version,
                policy_ref=command.policy_ref,
                policy_version=command.policy_version,
                admitted_at=existing.admitted_at if existing is not None else datetime.now(UTC),
                admitted_by=command.authenticated_principal,
                input_fingerprint=compute_extraction_input_fingerprint(
                    revision_content_hash=revision.content_hash,
                    extractor_kind=command.extractor_kind,
                    extractor_version=command.extractor_version,
                    policy_ref=command.policy_ref,
                    policy_version=command.policy_version,
                ),
            )
            if existing is not None:
                if existing == candidate:
                    return existing
                raise NarrativeEvidenceIdentityConflictError(
                    f"extraction attempt {attempt_id!r} was already admitted with a different tuple"
                )
            await repo.insert_extraction_attempt(candidate)
            await uow.commit()
            return candidate

    async def get_exact_draft_candidate(
        self, *, candidate_id: str, project_name: str, user_id: str
    ) -> DraftCandidate | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_draft_candidate(
                candidate_id=candidate_id, project_name=project_name, user_id=user_id
            )

    async def get_exact_revision(
        self, *, revision_id: str, project_name: str, user_id: str
    ) -> NarrativeRevision | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_revision(
                revision_id=revision_id, project_name=project_name, user_id=user_id
            )

    async def get_exact_extraction_attempt(
        self, *, attempt_id: str, project_name: str, user_id: str
    ) -> ExtractionAttempt | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_extraction_attempt(
                attempt_id=attempt_id, project_name=project_name, user_id=user_id
            )

    async def get_exact_extraction_result(
        self, *, attempt_id: str, generation: int, project_name: str, user_id: str
    ) -> ExtractionResult | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_extraction_result(
                attempt_id=attempt_id, generation=generation, project_name=project_name, user_id=user_id
            )

    async def get_exact_change_set(
        self, *, change_set_id: str, project_name: str, user_id: str
    ) -> NarrativeChangeSet | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_change_set(
                change_set_id=change_set_id, project_name=project_name, user_id=user_id
            )

    @staticmethod
    async def _attempt_scope(
        repo: NarrativeLifecycleEvidenceRepositoryPort, result: ExtractionResult
    ) -> NarrativeWorkScope:
        attempt = await repo.get_extraction_attempt_by_id(attempt_id=result.attempt_id)
        if attempt is None:
            raise NarrativeEvidenceIntegrityError(
                f"no admitted extraction attempt {result.attempt_id!r} for this result"
            )
        if attempt.generation != result.generation:
            raise NarrativeAttemptGenerationConflict(
                "the result generation does not match the admitted attempt generation"
            )
        return attempt.work_scope
