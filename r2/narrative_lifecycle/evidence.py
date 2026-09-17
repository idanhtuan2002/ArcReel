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

from pydantic import AwareDatetime, ConfigDict, Field

from r2.contracts.common import NonEmptyStr, R2ContractModel
from r2.contracts.narrative import CanonDelta
from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewCommand,
    CompilationAttempt,
    CompilationResult,
    CompilationSelectedChangeSet,
    CompiledCanonDeltaEvidence,
    ConflictResolutionCommand,
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeSet,
    NarrativeRevision,
    NarrativeWorkScope,
    ObservedEffectiveHead,
)
from r2.narrative.hashing import compute_canon_delta_hash
from r2.narrative_lifecycle.coverage import effect_keys_collide, normalize_source_spans, spans_overlap
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeConflictCoverageError,
    NarrativeDecisionApplicabilityError,
    NarrativeEvidenceIdentityConflictError,
    NarrativeEvidenceIntegrityError,
)
from r2.narrative_lifecycle.hashing import compute_compilation_input_fingerprint, compute_extraction_input_fingerprint
from r2.narrative_lifecycle.ports import (
    NarrativeLifecycleEvidenceRepositoryPort,
    NarrativeLifecycleRepositoryPort,
    NarrativeLifecycleUnitOfWorkFactory,
)

_SHARED_BASIS_FIELDS = ("base_canon_version_id", "plan_version", "scene_contract_version", "context_pack_id")

# ``head_lock_sort_key`` (r2.narrative_lifecycle.authority_kernel) is off limits here —
# the "M5C narrative evidence service holds no head-mutation capability" import-linter
# contract forbids ``evidence`` from importing ``authority_kernel``. This admission guard
# only ever *reads* heads (``lock_existing_*_head``, never ``lock_or_insert_*``), but it
# must still lock the ones it reads in the same canonical cross-transaction order the
# kernel uses, or a concurrent decision could deadlock against it. The formula below is
# the same one, reproduced rather than imported.
_HEAD_FAMILY_RANK = {"CHANGE_SET_REVIEW": 1, "CONFLICT_RESOLUTION": 2}


def _head_lock_sort_key(
    family: str, *, user_id: str, project_name: str, logical_key: tuple[str, ...]
) -> tuple[int, bytes, bytes, bytes]:
    return (
        _HEAD_FAMILY_RANK[family],
        user_id.encode("utf-8"),
        project_name.encode("utf-8"),
        "\x1f".join(logical_key).encode("utf-8"),
    )


_NON_SUCCESS_COMPILATION_OUTCOMES = frozenset({"NO_CANON_MUTATION", "ABSTAINED", "CONFLICT", "FAILED"})


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


class CompilationAdmissionCommand(R2ContractModel):
    """The request to admit a compilation attempt against every named decision's exact
    current effectiveness (spec §10.1). ``attempt_id`` is deterministically
    ``f"{revision_id}:{generation}"``, mirroring ``ExtractionAdmissionCommand`` — a
    revision's compilation attempts are its own generation-numbered sequence. The
    attempt's shared-basis fields (``base_canon_version_id`` / ``plan_version`` /
    ``scene_contract_version`` / ``context_pack_id``) are never caller-supplied: they are
    read from the named revision, exactly as ``admit_extraction`` does."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    work_scope: NarrativeWorkScope
    revision_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    revision_acceptance_decision_id: NonEmptyStr
    selected_change_sets: tuple[CompilationSelectedChangeSet, ...]
    conflict_resolution_decision_ids: tuple[NonEmptyStr, ...] = ()
    creative_policy_ref: NonEmptyStr
    creative_policy_version: NonEmptyStr
    compiler_version: NonEmptyStr
    requested_canon_delta_id: NonEmptyStr
    delta_created_at: AwareDatetime
    delta_created_by: NonEmptyStr
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


def _change_sets_overlap(left: NarrativeChangeSet, right: NarrativeChangeSet) -> bool:
    """True when two change sets would collide under the compiler's own overlap
    analysis (``compiler.py``'s ``_change_sets_conflict``, reproduced here from
    ``coverage.py``'s pure primitives rather than imported — admission never imports the
    compiler). Uses the ``SAME_SUBJECT`` collision policy, the compiler policy's own
    default: the strictest of the two supported policies, so admission never under-
    detects an overlap a laxer active policy would also have to resolve."""
    left_spans = normalize_source_spans(left.source_spans)
    right_spans = normalize_source_spans(right.source_spans)
    if any(spans_overlap(a, b) for a in left_spans for b in right_spans):
        return True
    return any(
        effect_keys_collide(a, b, policy="SAME_SUBJECT")
        for a in left.semantic_effect_keys
        for b in right.semantic_effect_keys
    )


def _require_no_unresolved_overlap(
    change_sets: Sequence[NarrativeChangeSet], resolutions: Sequence[ConflictResolutionCommand]
) -> None:
    """Spec §10.1: compilation admission requires no unresolved overlap. Every pairwise
    overlap among the named selection must have at least one named conflict-resolution
    decision whose competing change sets cover that exact pair — the same "applicable"
    test the compiler itself re-runs later over the same exact inputs."""
    for index, left in enumerate(change_sets):
        for right in change_sets[index + 1 :]:
            if not _change_sets_overlap(left, right):
                continue
            pair = {left.change_set_id, right.change_set_id}
            if not any(pair.issubset(set(resolution.competing_change_set_ids)) for resolution in resolutions):
                raise NarrativeConflictCoverageError(
                    f"an unresolved overlap exists between change sets {left.change_set_id!r} "
                    f"and {right.change_set_id!r}"
                )


async def _resolve_selected_reviews(
    repo: NarrativeLifecycleRepositoryPort, command: CompilationAdmissionCommand, scope: NarrativeWorkScope
) -> list[tuple[CompilationSelectedChangeSet, str]]:
    """Resolve every named review decision, verifying it selects the exact named change
    set and shares the compilation's exact scope and revision-acceptance basis. Returns
    each selection paired with its lineage id — not yet proven current."""
    resolved: list[tuple[CompilationSelectedChangeSet, str]] = []
    for selected in command.selected_change_sets:
        stored = await repo.get_decision_by_id(
            selected.review_decision_id, user_id=scope.user_id, project_name=scope.project_name
        )
        if stored is None:
            raise NarrativeDecisionApplicabilityError(
                f"review decision {selected.review_decision_id!r} does not resolve"
            )
        review_command, _, _ = stored
        if (
            not isinstance(review_command, ChangeSetReviewCommand)
            or review_command.selected_change_set_id != selected.change_set_id
        ):
            raise NarrativeDecisionApplicabilityError(
                f"review decision {selected.review_decision_id!r} does not select change set {selected.change_set_id!r}"
            )
        if (
            review_command.work_scope != scope
            or review_command.revision_acceptance_decision_id != command.revision_acceptance_decision_id
        ):
            raise NarrativeDecisionApplicabilityError(
                f"review decision {selected.review_decision_id!r} is mutually invalid with this compilation's "
                "exact scope and revision-acceptance basis"
            )
        resolved.append((selected, review_command.change_set_lineage_id))
    return resolved


async def _lock_review_heads(
    repo: NarrativeLifecycleRepositoryPort,
    command: CompilationAdmissionCommand,
    resolved: Sequence[tuple[CompilationSelectedChangeSet, str]],
    scope: NarrativeWorkScope,
) -> list[ObservedEffectiveHead]:
    """Lock every named change-set-review lineage head, in the canonical cross-family
    lock order, and require each to still be the exact current effective selection."""
    observed: list[ObservedEffectiveHead] = []
    ordered = sorted(
        resolved,
        key=lambda item: _head_lock_sort_key(
            "CHANGE_SET_REVIEW",
            user_id=scope.user_id,
            project_name=scope.project_name,
            logical_key=(command.revision_acceptance_decision_id, item[1]),
        ),
    )
    for selected, lineage_id in ordered:
        head = await repo.lock_existing_change_set_review_head(
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            change_set_lineage_id=lineage_id,
            user_id=scope.user_id,
            project_name=scope.project_name,
        )
        if head is None or head.effective_decision_id != selected.review_decision_id:
            raise NarrativeDecisionApplicabilityError(
                f"review decision {selected.review_decision_id!r} is not the current effective selection "
                "for its lineage"
            )
        observed.append(
            ObservedEffectiveHead(
                decision_id=selected.review_decision_id, effective_generation=head.effective_generation
            )
        )
    return observed


async def _load_and_verify_change_sets(
    repo: NarrativeLifecycleRepositoryPort,
    command: CompilationAdmissionCommand,
    revision: NarrativeRevision,
    scope: NarrativeWorkScope,
) -> dict[str, NarrativeChangeSet]:
    """Load every selected change set and require exact mutual basis equality with the
    named revision (spec §10.1): the same source revision, the same Canon base."""
    change_sets: dict[str, NarrativeChangeSet] = {}
    for selected in command.selected_change_sets:
        change_set = await repo.get_exact_change_set(
            change_set_id=selected.change_set_id, project_name=scope.project_name, user_id=scope.user_id
        )
        if change_set is None:
            raise NarrativeEvidenceIntegrityError(
                f"compilation selection references a missing change set {selected.change_set_id!r}"
            )
        if (
            change_set.source_revision_id != revision.revision_id
            or change_set.base_canon_version_id != revision.base_canon_version_id
        ):
            raise NarrativeDecisionApplicabilityError(
                f"change set {selected.change_set_id!r} is mutually invalid with revision "
                f"{revision.revision_id!r}'s exact basis"
            )
        change_sets[selected.change_set_id] = change_set
    return change_sets


async def _resolve_and_lock_resolutions(
    repo: NarrativeLifecycleRepositoryPort, command: CompilationAdmissionCommand, scope: NarrativeWorkScope
) -> tuple[list[ObservedEffectiveHead], dict[str, ConflictResolutionCommand]]:
    """Resolve, lock, and prove applicable every named conflict-resolution decision:
    it must be a ``RESOLVE`` decision sharing this compilation's exact scope and
    revision-acceptance basis, its own head must be the exact current effective
    resolution for its lineage, and every review decision it names must still be the
    effective selection for its own lineage (the same applicability
    ``NarrativeAcceptanceService.is_conflict_resolution_applicable`` proves, re-read here
    inside the same admission transaction rather than a separate one)."""
    resolutions: dict[str, ConflictResolutionCommand] = {}
    for decision_id in command.conflict_resolution_decision_ids:
        stored = await repo.get_decision_by_id(decision_id, user_id=scope.user_id, project_name=scope.project_name)
        if stored is None:
            raise NarrativeDecisionApplicabilityError(f"conflict resolution {decision_id!r} does not resolve")
        resolution_command, _, _ = stored
        if not isinstance(resolution_command, ConflictResolutionCommand) or resolution_command.action != "RESOLVE":
            raise NarrativeDecisionApplicabilityError(
                f"conflict resolution {decision_id!r} is not an applicable RESOLVE decision"
            )
        if (
            resolution_command.work_scope != scope
            or resolution_command.revision_acceptance_decision_id != command.revision_acceptance_decision_id
        ):
            raise NarrativeDecisionApplicabilityError(
                f"conflict resolution {decision_id!r} is mutually invalid with this compilation's exact scope "
                "and revision-acceptance basis"
            )
        resolutions[decision_id] = resolution_command

    observed: list[ObservedEffectiveHead] = []
    ordered = sorted(
        resolutions.items(),
        key=lambda item: _head_lock_sort_key(
            "CONFLICT_RESOLUTION",
            user_id=scope.user_id,
            project_name=scope.project_name,
            logical_key=(command.revision_acceptance_decision_id, item[1].conflict_resolution_lineage_id),
        ),
    )
    for decision_id, resolution_command in ordered:
        head = await repo.lock_existing_conflict_resolution_head(
            revision_acceptance_decision_id=command.revision_acceptance_decision_id,
            conflict_resolution_lineage_id=resolution_command.conflict_resolution_lineage_id,
            user_id=scope.user_id,
            project_name=scope.project_name,
        )
        if head is None or head.effective_decision_id != decision_id:
            raise NarrativeDecisionApplicabilityError(
                f"conflict resolution {decision_id!r} is not the current effective resolution for its lineage"
            )
        for review_decision_id in resolution_command.competing_review_decision_ids:
            review_head = await repo.get_change_set_review_head(
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                change_set_lineage_id=await _lineage_for_review_decision(repo, review_decision_id, scope),
                user_id=scope.user_id,
                project_name=scope.project_name,
            )
            if review_head is None or review_head.effective_decision_id != review_decision_id:
                raise NarrativeDecisionApplicabilityError(
                    f"conflict resolution {decision_id!r} names review decision {review_decision_id!r}, "
                    "which is no longer the current effective selection for its lineage"
                )
        observed.append(ObservedEffectiveHead(decision_id=decision_id, effective_generation=head.effective_generation))
    return observed, resolutions


async def _lineage_for_review_decision(
    repo: NarrativeLifecycleRepositoryPort, review_decision_id: str, scope: NarrativeWorkScope
) -> str:
    stored = await repo.get_decision_by_id(review_decision_id, user_id=scope.user_id, project_name=scope.project_name)
    if stored is None or not isinstance(stored[0], ChangeSetReviewCommand):
        raise NarrativeDecisionApplicabilityError(f"review decision {review_decision_id!r} does not resolve")
    return stored[0].change_set_lineage_id


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

    async def admit_compilation(self, command: CompilationAdmissionCommand) -> CompilationAttempt:
        """Mirrors ``admit_extraction`` at a higher fan-out (spec §10.1): the attempt's
        admission instant is atomic with proof that the exact current revision
        acceptance, every named change-set-review decision (matched against its exact
        selected change set), and every named conflict-resolution decision are all
        currently effective — plus that the named selection has no unresolved overlap
        and shares one exact scope and basis with the accepted revision. A later
        supersession of any named decision blocks new admissions for this attempt id but
        never deletes one already recorded. Compilation itself runs outside this
        transaction, over the exact immutable inputs this attempt now names."""
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

            revision_head = await repo.lock_existing_revision_head(scope)
            if revision_head is None or revision_head.effective_decision_id != command.revision_acceptance_decision_id:
                raise NarrativeDecisionApplicabilityError(
                    f"revision acceptance {command.revision_acceptance_decision_id!r} "
                    "is not the current effective revision"
                )
            observed_heads = [
                ObservedEffectiveHead(
                    decision_id=command.revision_acceptance_decision_id,
                    effective_generation=revision_head.effective_generation,
                )
            ]

            resolved_reviews = await _resolve_selected_reviews(repo, command, scope)
            observed_heads.extend(await _lock_review_heads(repo, command, resolved_reviews, scope))
            change_sets_by_id = await _load_and_verify_change_sets(repo, command, revision, scope)
            resolution_observed, resolutions = await _resolve_and_lock_resolutions(repo, command, scope)
            observed_heads.extend(resolution_observed)

            ordered_change_sets = [change_sets_by_id[item.change_set_id] for item in command.selected_change_sets]
            _require_no_unresolved_overlap(ordered_change_sets, list(resolutions.values()))

            attempt_id = f"{command.revision_id}:{command.generation}"
            existing = await repo.get_exact_compilation_attempt(
                attempt_id=attempt_id, project_name=scope.project_name, user_id=scope.user_id
            )
            draft = CompilationAttempt(
                attempt_id=attempt_id,
                generation=command.generation,
                work_scope=scope,
                revision_id=command.revision_id,
                revision_acceptance_decision_id=command.revision_acceptance_decision_id,
                selected_change_sets=command.selected_change_sets,
                conflict_resolution_decision_ids=command.conflict_resolution_decision_ids,
                observed_effective_heads=tuple(observed_heads),
                base_canon_version_id=revision.base_canon_version_id,
                plan_version=revision.plan_version,
                scene_contract_version=revision.scene_contract_version,
                context_pack_id=revision.context_pack_id,
                creative_policy_ref=command.creative_policy_ref,
                creative_policy_version=command.creative_policy_version,
                compiler_version=command.compiler_version,
                requested_canon_delta_id=command.requested_canon_delta_id,
                delta_created_at=command.delta_created_at,
                delta_created_by=command.delta_created_by,
                admitted_at=existing.admitted_at if existing is not None else datetime.now(UTC),
                admitted_by=command.authenticated_principal,
                input_fingerprint="pending",
            )
            candidate = draft.model_copy(update={"input_fingerprint": compute_compilation_input_fingerprint(draft)})
            if existing is not None:
                if existing == candidate:
                    return existing
                raise NarrativeEvidenceIdentityConflictError(
                    f"compilation attempt {attempt_id!r} was already admitted with a different tuple"
                )
            await repo.insert_compilation_attempt(candidate)
            await uow.commit()
            return candidate

    async def record_successful_compilation(
        self, result: CompilationResult, canon_delta: CanonDelta
    ) -> CompilationResult:
        """Inserts a ``SUCCEEDED`` result and its exact ``CompiledCanonDeltaEvidence``
        payload atomically, in one transaction. Requires exact hash equality between the
        recomputed M5A hash, the result's own ``canon_delta_payload_hash``, and the
        embedded delta's own ``payload_hash`` — a caller-supplied mismatch is rejected,
        never silently trusted. An exact retry (identical result and identical delta)
        returns the original unchanged and writes nothing; a mismatched retry fails
        closed with no write."""
        if result.outcome != "SUCCEEDED":
            raise NarrativeEvidenceIntegrityError("record_successful_compilation requires a SUCCEEDED result")
        recomputed = compute_canon_delta_hash(canon_delta)
        if recomputed != result.canon_delta_payload_hash or recomputed != canon_delta.payload_hash:
            raise NarrativeEvidenceIntegrityError(
                "the recomputed canon delta payload hash does not match both the result and the embedded delta"
            )
        async with self._uow_factory() as uow:
            repo = uow.repository
            scope = await self._compilation_attempt_scope(repo, result)
            existing_result = await repo.get_exact_compilation_result(
                attempt_id=result.attempt_id,
                generation=result.generation,
                project_name=scope.project_name,
                user_id=scope.user_id,
            )
            if existing_result is not None:
                existing_evidence = await repo.get_exact_compiled_canon_delta(
                    compilation_result_id=existing_result.result_id,
                    project_name=scope.project_name,
                    user_id=scope.user_id,
                )
                if (
                    existing_result == result
                    and existing_evidence is not None
                    and existing_evidence.canon_delta == canon_delta
                ):
                    return existing_result
                raise NarrativeAttemptGenerationConflict(
                    "a different result is already recorded for this attempt generation"
                )
            evidence = CompiledCanonDeltaEvidence(
                compilation_result_id=result.result_id,
                compilation_attempt_id=result.attempt_id,
                generation=result.generation,
                canon_delta=canon_delta,
                canon_delta_payload_hash=recomputed,
                stored_at=datetime.now(UTC),
            )
            await repo.insert_successful_compilation(result, evidence)
            await uow.commit()
            return result

    async def record_compilation_without_delta(self, result: CompilationResult) -> CompilationResult:
        """Accepts exactly ``NO_CANON_MUTATION`` / ``ABSTAINED`` / ``CONFLICT`` /
        ``FAILED``; rejects a populated delta field. No compiled-delta row is ever
        written for an outcome-only result."""
        if result.outcome not in _NON_SUCCESS_COMPILATION_OUTCOMES:
            raise NarrativeEvidenceIntegrityError(
                f"record_compilation_without_delta rejects outcome {result.outcome!r}"
            )
        if result.canon_delta_id is not None or result.canon_delta_payload_hash is not None:
            raise NarrativeEvidenceIntegrityError("a non-success compilation result declares no canon delta")
        async with self._uow_factory() as uow:
            repo = uow.repository
            scope = await self._compilation_attempt_scope(repo, result)
            existing = await repo.get_exact_compilation_result(
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
            await repo.insert_non_successful_compilation(result)
            await uow.commit()
            return result

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

    async def get_exact_compilation_attempt(
        self, *, attempt_id: str, project_name: str, user_id: str
    ) -> CompilationAttempt | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_compilation_attempt(
                attempt_id=attempt_id, project_name=project_name, user_id=user_id
            )

    async def get_exact_compilation_result(
        self, *, attempt_id: str, generation: int, project_name: str, user_id: str
    ) -> CompilationResult | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_compilation_result(
                attempt_id=attempt_id, generation=generation, project_name=project_name, user_id=user_id
            )

    async def get_exact_compiled_delta(
        self, *, compilation_result_id: str, project_name: str, user_id: str
    ) -> CompiledCanonDeltaEvidence | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_compiled_canon_delta(
                compilation_result_id=compilation_result_id, project_name=project_name, user_id=user_id
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

    @staticmethod
    async def _compilation_attempt_scope(
        repo: NarrativeLifecycleEvidenceRepositoryPort, result: CompilationResult
    ) -> NarrativeWorkScope:
        attempt = await repo.get_compilation_attempt_by_id(attempt_id=result.attempt_id)
        if attempt is None:
            raise NarrativeEvidenceIntegrityError(
                f"no admitted compilation attempt {result.attempt_id!r} for this result"
            )
        if attempt.generation != result.generation:
            raise NarrativeAttemptGenerationConflict(
                "the result generation does not match the admitted attempt generation"
            )
        return attempt.work_scope
