"""M5C immutable Narrative-lifecycle evidence contracts.

Every model is frozen, rejects extra fields, uses timezone-aware UTC timestamps, and
carries an explicitly versioned canonical hash domain. None of these contracts grants
acceptance or Canon authority: a writer identity, a predecessor link, a review ref, or
an extraction outcome is evidence only. Acceptance lives only in the separate acceptance
decision stream. There is no ``accepted`` boolean anywhere in this module.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .common import JSONValue, NonEmptyStr, R2ContractModel
from .narrative import CanonDelta
from .provenance import Provenance

SEMANTIC_EFFECT_KEY_VERSION = "r2-m5c-semantic-effect-key-v1"

_EXTRACTION_OUTCOMES = Literal["SUCCEEDED", "ABSTAINED", "CONFLICT", "FAILED", "OUTCOME_UNKNOWN"]


class NarrativeWorkScope(R2ContractModel):
    """The stable workflow scope. The exact bases (canon version, plan version, scene
    contract version, context pack, policy / compiler / extractor identifiers) are
    immutable bindings carried on each artifact, never scope-key fields, and are never
    replaced by a current or latest value."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    plan_id: NonEmptyStr
    scene_contract_id: NonEmptyStr
    canon_branch_id: NonEmptyStr


class CanonMutationEffectKey(R2ContractModel):
    """Identifies an affected Canon subject/effect. It may map to one or more existing
    M5A Canon operations; ``canon_operation_count`` is that expected multiplicity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["CANON_MUTATION"] = "CANON_MUTATION"
    mapping_version: Literal["r2-m5c-semantic-effect-key-v1"] = SEMANTIC_EFFECT_KEY_VERSION
    canon_subject_kind: Literal["ENTITY", "FACT", "EVENT", "KNOWLEDGE", "TEMPORAL_RELATION"]
    subject_ref: NonEmptyStr
    effect_descriptor: NonEmptyStr
    canon_operation_count: Annotated[int, Field(ge=1)]


class ThreadPayoffEffectKey(R2ContractModel):
    """``THREAD_PAYOFF(thread_ref, payoff_ref)`` — a Narrative outcome key that maps to
    zero Canon operations. It never implies that a PlotThread is Canon state and cannot
    be coerced into a Canon mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["THREAD_PAYOFF"] = "THREAD_PAYOFF"
    mapping_version: Literal["r2-m5c-semantic-effect-key-v1"] = SEMANTIC_EFFECT_KEY_VERSION
    thread_ref: NonEmptyStr
    payoff_ref: NonEmptyStr
    canon_operation_count: Literal[0] = 0


NarrativeSemanticEffectKey = Annotated[
    CanonMutationEffectKey | ThreadPayoffEffectKey,
    Field(discriminator="kind"),
]


class SourceSpan(R2ContractModel):
    """A half-open ``[start, end)`` interval in one normalized coordinate system."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    unit: Literal["NORMALIZED_CHAR"] = "NORMALIZED_CHAR"
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _non_empty_half_open(self) -> SourceSpan:
        if self.end <= self.start:
            raise ValueError("SourceSpan end must be greater than start")
        return self


class ConflictSubject(R2ContractModel):
    """The minimal canonical intersection of competing reviewed change sets: the spans
    every competitor covers and the Canon / thread subjects every competitor touches.

    Lives here (not in ``r2.narrative_lifecycle.coverage``, which computes it) so the
    contracts layer never depends upward on the business-logic layer that consumes it;
    ``coverage.py`` and ``ConflictResolutionLineage`` both import this one definition.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    coverage: tuple[SourceSpan, ...]
    effect_key_subjects: tuple[str, ...]


def _span_union_covers(coverage: tuple[SourceSpan, ...], span: SourceSpan) -> bool:
    """True when ``span`` lies inside the union of ``coverage`` (overlapping or adjacent
    coverage spans count as one). Swept in ascending order; no merged objects built."""
    cursor = span.start
    for covered in sorted(coverage, key=lambda item: item.start):
        if covered.start > cursor:
            break
        cursor = max(cursor, covered.end)
        if cursor >= span.end:
            return True
    return cursor >= span.end


class DraftCandidate(R2ContractModel):
    """Writer output evidence. ``writer_kind`` may identify a Human, local tool, Agent, or
    provider-backed adapter, but it never implies acceptance."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: NonEmptyStr
    work_scope: NarrativeWorkScope
    base_canon_version_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_version: Annotated[int, Field(ge=1)]
    context_pack_id: NonEmptyStr
    normalized_content: NonEmptyStr
    content_hash: NonEmptyStr
    writer_kind: NonEmptyStr
    writer_version: NonEmptyStr
    provenance: Provenance
    created_at: AwareDatetime
    created_by: NonEmptyStr
    semantic_fingerprint: NonEmptyStr


class NarrativeRevision(R2ContractModel):
    """``predecessor_revision_id`` expresses immutable evidence lineage, not effective
    acceptance. There is no ``accepted`` boolean; acceptance lives in the decision stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    revision_id: NonEmptyStr
    work_scope: NarrativeWorkScope
    base_candidate_id: NonEmptyStr
    predecessor_revision_id: NonEmptyStr | None = None
    base_canon_version_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_version: Annotated[int, Field(ge=1)]
    context_pack_id: NonEmptyStr
    normalized_content: NonEmptyStr
    content_hash: NonEmptyStr
    review_refs: list[NonEmptyStr] = Field(default_factory=list)
    provenance: Provenance
    created_at: AwareDatetime
    created_by: NonEmptyStr
    semantic_fingerprint: NonEmptyStr

    @model_validator(mode="after")
    def _predecessor_is_not_self(self) -> NarrativeRevision:
        if self.predecessor_revision_id == self.revision_id:
            raise ValueError("NarrativeRevision predecessor_revision_id must not be the revision itself")
        return self


class ExtractionAttempt(R2ContractModel):
    """Persisted before external extraction begins."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    attempt_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    work_scope: NarrativeWorkScope
    revision_id: NonEmptyStr
    revision_acceptance_decision_id: NonEmptyStr
    observed_revision_effective_generation: Annotated[int, Field(ge=0)]
    base_canon_version_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_version: Annotated[int, Field(ge=1)]
    context_pack_id: NonEmptyStr
    extractor_kind: NonEmptyStr
    extractor_version: NonEmptyStr
    policy_ref: NonEmptyStr
    policy_version: NonEmptyStr
    admitted_at: AwareDatetime
    admitted_by: NonEmptyStr
    input_fingerprint: NonEmptyStr


class ExtractionResult(R2ContractModel):
    """At most one result exists for ``(attempt_id, generation)``. A ``SUCCEEDED`` result
    names a non-empty ordered set of change-set ids; every other outcome names none.
    ``OUTCOME_UNKNOWN`` is terminal for its exact generation and never advances a head."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    result_id: NonEmptyStr
    attempt_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    outcome: _EXTRACTION_OUTCOMES
    change_set_ids: tuple[NonEmptyStr, ...] = ()
    diagnostics: tuple[NonEmptyStr, ...] = ()
    provider_receipt: JSONValue | None = None
    completed_at: AwareDatetime
    output_fingerprint: NonEmptyStr

    @model_validator(mode="after")
    def _change_set_ids_match_outcome(self) -> ExtractionResult:
        if len(set(self.change_set_ids)) != len(self.change_set_ids):
            raise ValueError("ExtractionResult change_set_ids must be unique")
        if self.outcome == "SUCCEEDED":
            if not self.change_set_ids:
                raise ValueError("a SUCCEEDED ExtractionResult must name at least one change set")
        elif self.change_set_ids:
            raise ValueError(f"a {self.outcome} ExtractionResult must name no change sets")
        return self


class NarrativeChangeItem(R2ContractModel):
    """One granular proposed edit inside a change set. Its ``evidence_span`` must be
    contained by the change set's declared coverage (checked by the pure coverage rules),
    and its ``effect_keys`` must all be declared on the parent change set."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    change_id: NonEmptyStr
    evidence_span: SourceSpan
    effect_keys: tuple[NarrativeSemanticEffectKey, ...]
    summary: NonEmptyStr

    @model_validator(mode="after")
    def _effect_keys_non_empty(self) -> NarrativeChangeItem:
        if not self.effect_keys:
            raise ValueError("NarrativeChangeItem must declare at least one effect key")
        return self


class NarrativeChangeSet(R2ContractModel):
    """Proposal-only evidence. ``change_set_lineage_id`` is opaque workflow identity that
    partitions alternative proposals for the same semantic change; it is not inferred from
    prose, overlap, or hash equality. An extractor can append a proposal but receives no
    review or decision write port."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    change_set_id: NonEmptyStr
    change_set_lineage_id: NonEmptyStr
    source_revision_id: NonEmptyStr
    extraction_attempt_id: NonEmptyStr
    extraction_generation: Annotated[int, Field(ge=0)]
    base_canon_version_id: NonEmptyStr
    source_spans: tuple[SourceSpan, ...]
    semantic_effect_keys: tuple[NarrativeSemanticEffectKey, ...]
    changes: tuple[NarrativeChangeItem, ...]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    extractor_version: NonEmptyStr
    policy_ref: NonEmptyStr
    policy_version: NonEmptyStr
    created_at: AwareDatetime
    output_fingerprint: NonEmptyStr

    @model_validator(mode="after")
    def _proposes_a_covered_effect(self) -> NarrativeChangeSet:
        if not self.source_spans:
            raise ValueError("NarrativeChangeSet must declare at least one source span")
        if not self.semantic_effect_keys:
            raise ValueError("NarrativeChangeSet must declare at least one semantic effect key")
        if not self.changes:
            raise ValueError("NarrativeChangeSet must contain at least one change")
        declared = set(self.semantic_effect_keys)
        for item in self.changes:
            if not declared.issuperset(item.effect_keys):
                raise ValueError(f"change {item.change_id!r} names an effect key that the change set does not declare")
            if not _span_union_covers(self.source_spans, item.evidence_span):
                raise ValueError(
                    f"change {item.change_id!r} evidence span is not contained by the declared source-span coverage"
                )
        return self


# --- M5C-2 Narrative decision authority: decision, authorization, head, and lineage ---
#
# None of these contracts is itself authority: they are the shapes the (not-yet-built)
# authority kernel reads and writes. Acceptance becomes effective only through the kernel
# applying `RevisionDecisionAction` / `ChangeSetReviewAction` / `ConflictResolutionAction`
# under the rules in spec sections 6.2-6.7; a `NarrativeDecisionReceipt` never carries a
# `currently_effective` flag because currentness can change after the receipt is issued.

NarrativeDecisionFamily = Literal["REVISION_ACCEPTANCE", "CHANGE_SET_REVIEW", "CONFLICT_RESOLUTION"]
RevisionDecisionAction = Literal["ACCEPT", "REJECT", "SUPERSEDE"]
ChangeSetReviewAction = Literal["ACCEPT", "REJECT", "SUPERSEDE"]
ConflictResolutionAction = Literal["RESOLVE", "REJECT", "SUPERSEDE"]
NarrativeDecisionActionAny = Literal["ACCEPT", "REJECT", "SUPERSEDE", "RESOLVE"]


class NarrativeDecisionAuthorization(R2ContractModel):
    """The original, immutable Human Showrunner approval evidence for one exact canonical
    command. Persisted with its typed decision and included in stored decision identity,
    including its own ``authenticated_at`` receipt time. Reuse for a different
    family, action, scope, decision ID, or command fingerprint is a kernel-enforced
    identity conflict, not something this shape can reject on its own."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    authorization_ref: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    actor_id: NonEmptyStr
    authority_role: Literal["HUMAN_SHOWRUNNER"]
    decision_family: NarrativeDecisionFamily
    action: NarrativeDecisionActionAny
    decision_id: NonEmptyStr
    stable_subject_fingerprint: NonEmptyStr
    decision_command_fingerprint: NonEmptyStr
    authenticated_at: AwareDatetime
    authenticated_via: NonEmptyStr


class NarrativeDecisionRetryAuthentication(R2ContractModel):
    """Proves only that the original ``actor_id`` is currently authenticated and may
    request replay in this exact scope. Never persisted as decision identity and
    never substitutes for the original ``NarrativeDecisionAuthorization``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    retry_authentication_ref: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    actor_id: NonEmptyStr
    authority_role: Literal["HUMAN_SHOWRUNNER"]
    decision_id: NonEmptyStr
    authenticated_at: AwareDatetime
    authenticated_via: NonEmptyStr


def _validate_decision_predecessors(
    *,
    action: str,
    accepting_action: str,
    expected_latest_decision_id: str | None,
    expected_effective_decision_id: str | None,
) -> None:
    """The predecessor rules shared by all three decision families.

    Genesis (no expected latest decision) must also expect no effective decision. The
    family's "select a new effective candidate" action (``ACCEPT`` or ``RESOLVE``)
    forbids an existing effective selection; ``SUPERSEDE`` requires one. ``REJECT`` is
    unconstrained here: it may name a candidate whether or not an effective selection
    already exists, and never changes the effective pointer.
    """
    if expected_latest_decision_id is None and expected_effective_decision_id is not None:
        raise ValueError("a genesis decision (no expected latest decision) must also expect no effective decision")
    if action == accepting_action and expected_effective_decision_id is not None:
        raise ValueError(f"{accepting_action} forbids an existing effective selection")
    if action == "SUPERSEDE" and expected_effective_decision_id is None:
        raise ValueError("SUPERSEDE requires the exact current effective decision")


class RevisionAcceptanceCommand(R2ContractModel):
    """One ``decide_revision`` request. ``work_scope`` is the stable subject key of the
    ``RevisionAcceptanceHead`` this decision targets; ``selected_revision_id`` is the
    exact ``NarrativeRevision`` this decision names. ``retry_authentication`` is supplied
    only when this request may be an exact retry of an already-stored ``decision_id``; it
    is excluded from canonical decision identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    decision_family: Literal["REVISION_ACCEPTANCE"] = "REVISION_ACCEPTANCE"
    action: RevisionDecisionAction
    work_scope: NarrativeWorkScope
    selected_revision_id: NonEmptyStr
    expected_latest_decision_id: NonEmptyStr | None = None
    expected_effective_decision_id: NonEmptyStr | None = None
    base_canon_version_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_version: Annotated[int, Field(ge=1)]
    context_pack_id: NonEmptyStr
    actor_id: NonEmptyStr
    retry_authentication: NarrativeDecisionRetryAuthentication | None = None

    @model_validator(mode="after")
    def _predecessor_rules(self) -> RevisionAcceptanceCommand:
        _validate_decision_predecessors(
            action=self.action,
            accepting_action="ACCEPT",
            expected_latest_decision_id=self.expected_latest_decision_id,
            expected_effective_decision_id=self.expected_effective_decision_id,
        )
        return self


class ChangeSetReviewCommand(R2ContractModel):
    """One ``review_change_set`` request. Its stable subject key is
    ``(revision_acceptance_decision_id, change_set_lineage_id)``;
    ``selected_change_set_id`` is the exact ``NarrativeChangeSet`` this decision names."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    decision_family: Literal["CHANGE_SET_REVIEW"] = "CHANGE_SET_REVIEW"
    action: ChangeSetReviewAction
    work_scope: NarrativeWorkScope
    revision_acceptance_decision_id: NonEmptyStr
    change_set_lineage_id: NonEmptyStr
    selected_change_set_id: NonEmptyStr
    expected_latest_decision_id: NonEmptyStr | None = None
    expected_effective_decision_id: NonEmptyStr | None = None
    base_canon_version_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_version: Annotated[int, Field(ge=1)]
    context_pack_id: NonEmptyStr
    actor_id: NonEmptyStr
    retry_authentication: NarrativeDecisionRetryAuthentication | None = None

    @model_validator(mode="after")
    def _predecessor_rules(self) -> ChangeSetReviewCommand:
        _validate_decision_predecessors(
            action=self.action,
            accepting_action="ACCEPT",
            expected_latest_decision_id=self.expected_latest_decision_id,
            expected_effective_decision_id=self.expected_effective_decision_id,
        )
        return self


class ConflictResolutionCommand(R2ContractModel):
    """One ``resolve_change_set_conflict`` request. Its genesis form both allocates the
    ``ConflictResolutionLineage`` and appends the first decision to its head; its stable
    subject key is
    ``(revision_acceptance_decision_id, conflict_resolution_lineage_id)``.
    ``chosen_resolution`` is the typed semantic instruction the compiler understands, or
    (for ``REJECT``) the proposed resolution being named and rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    decision_family: Literal["CONFLICT_RESOLUTION"] = "CONFLICT_RESOLUTION"
    action: ConflictResolutionAction
    work_scope: NarrativeWorkScope
    revision_acceptance_decision_id: NonEmptyStr
    conflict_resolution_lineage_id: NonEmptyStr
    competing_change_set_ids: tuple[NonEmptyStr, ...]
    competing_review_decision_ids: tuple[NonEmptyStr, ...]
    chosen_resolution: NonEmptyStr
    expected_latest_decision_id: NonEmptyStr | None = None
    expected_effective_decision_id: NonEmptyStr | None = None
    base_canon_version_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_version: Annotated[int, Field(ge=1)]
    context_pack_id: NonEmptyStr
    actor_id: NonEmptyStr
    retry_authentication: NarrativeDecisionRetryAuthentication | None = None

    @model_validator(mode="after")
    def _predecessor_rules(self) -> ConflictResolutionCommand:
        _validate_decision_predecessors(
            action=self.action,
            accepting_action="RESOLVE",
            expected_latest_decision_id=self.expected_latest_decision_id,
            expected_effective_decision_id=self.expected_effective_decision_id,
        )
        return self

    @model_validator(mode="after")
    def _competing_sets_are_plural_and_paired(self) -> ConflictResolutionCommand:
        if len(self.competing_change_set_ids) < 2:
            raise ValueError("a conflict resolution names at least two competing change sets")
        if len(set(self.competing_change_set_ids)) != len(self.competing_change_set_ids):
            raise ValueError("competing_change_set_ids must be unique")
        if len(self.competing_review_decision_ids) != len(self.competing_change_set_ids):
            raise ValueError(
                "competing_review_decision_ids must name exactly one review decision per competing change set"
            )
        if len(set(self.competing_review_decision_ids)) != len(self.competing_review_decision_ids):
            raise ValueError("competing_review_decision_ids must be unique")
        return self


NarrativeDecisionCommand = RevisionAcceptanceCommand | ChangeSetReviewCommand | ConflictResolutionCommand


class NarrativeDecisionReceipt(R2ContractModel):
    """Returned by all three decision commands. Names the exact decision made and the
    resulting head generations. ``currently_effective`` is deliberately absent: exact
    retry can return this receipt long after currentness has changed."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    decision_family: NarrativeDecisionFamily
    action: NarrativeDecisionActionAny
    decision_generation: Annotated[int, Field(ge=0)]
    effective_decision_id: NonEmptyStr | None = None
    effective_generation: Annotated[int, Field(ge=0)]


def _validate_head_generations(
    *,
    latest_decision_id: str | None,
    decision_generation: int,
    effective_decision_id: str | None,
    effective_generation: int,
) -> None:
    """The "null-pointer/zero-generation genesis" invariant shared by every logical
    head: a pointer is absent exactly when its generation is zero, and the effective
    generation can never run ahead of the decision generation that produced it."""
    if (latest_decision_id is None) != (decision_generation == 0):
        raise ValueError("decision_generation must be zero exactly when latest_decision_id is absent")
    if (effective_decision_id is None) != (effective_generation == 0):
        raise ValueError("effective_generation must be zero exactly when effective_decision_id is absent")
    if effective_generation > decision_generation:
        raise ValueError("effective_generation cannot exceed decision_generation")


class RevisionAcceptanceHead(R2ContractModel):
    """The rebuildable lock/index projection keyed by
    ``(user_id, project_name, plan_id, scene_contract_id, canon_branch_id)`` — exactly
    ``NarrativeWorkScope``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    work_scope: NarrativeWorkScope
    latest_decision_id: NonEmptyStr | None = None
    decision_generation: Annotated[int, Field(ge=0)]
    effective_decision_id: NonEmptyStr | None = None
    effective_generation: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _generation_invariant(self) -> RevisionAcceptanceHead:
        _validate_head_generations(
            latest_decision_id=self.latest_decision_id,
            decision_generation=self.decision_generation,
            effective_decision_id=self.effective_decision_id,
            effective_generation=self.effective_generation,
        )
        return self


class ChangeSetReviewHead(R2ContractModel):
    """The rebuildable lock/index projection keyed by
    ``(revision_acceptance_decision_id, change_set_lineage_id)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    revision_acceptance_decision_id: NonEmptyStr
    change_set_lineage_id: NonEmptyStr
    latest_decision_id: NonEmptyStr | None = None
    decision_generation: Annotated[int, Field(ge=0)]
    effective_decision_id: NonEmptyStr | None = None
    effective_generation: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _generation_invariant(self) -> ChangeSetReviewHead:
        _validate_head_generations(
            latest_decision_id=self.latest_decision_id,
            decision_generation=self.decision_generation,
            effective_decision_id=self.effective_decision_id,
            effective_generation=self.effective_generation,
        )
        return self


class ConflictResolutionHead(R2ContractModel):
    """The rebuildable lock/index projection keyed by
    ``(revision_acceptance_decision_id, conflict_resolution_lineage_id)``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    revision_acceptance_decision_id: NonEmptyStr
    conflict_resolution_lineage_id: NonEmptyStr
    latest_decision_id: NonEmptyStr | None = None
    decision_generation: Annotated[int, Field(ge=0)]
    effective_decision_id: NonEmptyStr | None = None
    effective_generation: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _generation_invariant(self) -> ConflictResolutionHead:
        _validate_head_generations(
            latest_decision_id=self.latest_decision_id,
            decision_generation=self.decision_generation,
            effective_decision_id=self.effective_decision_id,
            effective_generation=self.effective_generation,
        )
        return self


class ConflictResolutionLineage(R2ContractModel):
    """The opaque conflict-resolution lineage allocated by the genesis form of
    ``resolve_change_set_conflict()``. Its revision and conflict subject are
    immutable; the service derives ``conflict_subject_fingerprint`` from the minimal
    canonical intersection of the exact currently effective competing reviewed change
    sets, never from caller-supplied widened, partial, reordered, or free-form coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    conflict_resolution_lineage_id: NonEmptyStr
    revision_acceptance_decision_id: NonEmptyStr
    conflict_subject: ConflictSubject
    conflict_subject_fingerprint: NonEmptyStr
    created_at: AwareDatetime
    created_by: NonEmptyStr


# --- M5C-3 CanonDelta compilation: attempt/result/compiled-delta evidence ---
#
# The pure compiler (a later task) consumes a CompilationAttempt's exact immutable
# inputs by reference — decision IDs and observed head generations, never re-reading
# currentness itself. None of these contracts grants Canon authority: a SUCCEEDED
# CompilationResult only proposes a CanonDelta for the separate M5A handoff/approval
# path to admit.

_COMPILATION_OUTCOMES = Literal["SUCCEEDED", "NO_CANON_MUTATION", "ABSTAINED", "CONFLICT", "FAILED"]


class CompilationSelectedChangeSet(R2ContractModel):
    """One accepted change set entering a compilation attempt, paired with the exact
    review decision that selected it — never re-derived from the change set alone."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    change_set_id: NonEmptyStr
    review_decision_id: NonEmptyStr


class ObservedEffectiveHead(R2ContractModel):
    """One head's effective decision as observed at admission time: the revision head,
    or one change-set-review / conflict-resolution lineage head. Durable proof of what
    was current when the attempt was admitted — a head can move on afterward without
    invalidating an attempt already admitted against it."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    effective_generation: Annotated[int, Field(ge=1)]


class CompilationAttempt(R2ContractModel):
    """Persisted before the pure compiler runs. Names its exact immutable inputs by
    reference — decision IDs and observed head generations, not their content — so
    recomputing the same exact ``(attempt_id, generation)`` always compiles the same
    snapshot, even after currentness has since moved on."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    attempt_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    work_scope: NarrativeWorkScope
    revision_id: NonEmptyStr
    revision_acceptance_decision_id: NonEmptyStr
    selected_change_sets: tuple[CompilationSelectedChangeSet, ...]
    conflict_resolution_decision_ids: tuple[NonEmptyStr, ...] = ()
    observed_effective_heads: tuple[ObservedEffectiveHead, ...]
    base_canon_version_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_version: Annotated[int, Field(ge=1)]
    context_pack_id: NonEmptyStr
    creative_policy_ref: NonEmptyStr
    creative_policy_version: NonEmptyStr
    compiler_version: NonEmptyStr
    requested_canon_delta_id: NonEmptyStr
    delta_created_at: AwareDatetime
    delta_created_by: NonEmptyStr
    admitted_at: AwareDatetime
    admitted_by: NonEmptyStr
    input_fingerprint: NonEmptyStr

    @model_validator(mode="after")
    def _selected_change_sets_are_present_and_unique(self) -> CompilationAttempt:
        if not self.selected_change_sets:
            raise ValueError("a compilation attempt must select at least one change set")
        change_set_ids = [item.change_set_id for item in self.selected_change_sets]
        if len(set(change_set_ids)) != len(change_set_ids):
            raise ValueError("selected_change_sets change_set_id values must be unique")
        review_decision_ids = [item.review_decision_id for item in self.selected_change_sets]
        if len(set(review_decision_ids)) != len(review_decision_ids):
            raise ValueError("selected_change_sets review_decision_id values must be unique")
        return self

    @model_validator(mode="after")
    def _conflict_resolution_decision_ids_are_unique(self) -> CompilationAttempt:
        if len(set(self.conflict_resolution_decision_ids)) != len(self.conflict_resolution_decision_ids):
            raise ValueError("conflict_resolution_decision_ids must be unique")
        return self

    @model_validator(mode="after")
    def _observed_effective_heads_are_present_and_unique(self) -> CompilationAttempt:
        if not self.observed_effective_heads:
            raise ValueError("a compilation attempt must observe at least the revision head")
        decision_ids = [item.decision_id for item in self.observed_effective_heads]
        if len(set(decision_ids)) != len(decision_ids):
            raise ValueError("observed_effective_heads decision_id values must be unique")
        return self


class CompilationResult(R2ContractModel):
    """At most one result exists for ``(attempt_id, generation)``. A ``SUCCEEDED`` result
    names a non-null delta id and payload hash; every other outcome names neither.
    ``NO_CANON_MUTATION`` is a valid deterministic terminal result, not an abstention or
    failure: it means the complete valid selection is outcome-only and names no delta."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    result_id: NonEmptyStr
    attempt_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    outcome: _COMPILATION_OUTCOMES
    canon_delta_id: NonEmptyStr | None = None
    canon_delta_payload_hash: NonEmptyStr | None = None
    diagnostics: tuple[NonEmptyStr, ...] = ()
    completed_at: AwareDatetime
    output_fingerprint: NonEmptyStr

    @model_validator(mode="after")
    def _delta_fields_match_outcome(self) -> CompilationResult:
        has_delta = self.canon_delta_id is not None or self.canon_delta_payload_hash is not None
        if self.outcome == "SUCCEEDED":
            if self.canon_delta_id is None or self.canon_delta_payload_hash is None:
                raise ValueError(
                    "a SUCCEEDED CompilationResult must name both canon_delta_id and canon_delta_payload_hash"
                )
        elif has_delta:
            raise ValueError(f"a {self.outcome} CompilationResult must name no canon delta")
        return self


class CompiledCanonDeltaEvidence(R2ContractModel):
    """The durable, lossless copy of a ``SUCCEEDED`` compilation's exact immutable M5A
    ``CanonDelta`` payload, keyed one-to-one by ``compilation_result_id``. Handoff and
    recovery reload this persisted payload; rerunning the compiler is an integrity
    check, never the normative path for obtaining the proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    compilation_result_id: NonEmptyStr
    compilation_attempt_id: NonEmptyStr
    generation: Annotated[int, Field(ge=0)]
    canon_delta: CanonDelta
    canon_delta_payload_hash: NonEmptyStr
    stored_at: AwareDatetime

    @model_validator(mode="after")
    def _payload_hash_matches_the_embedded_delta(self) -> CompiledCanonDeltaEvidence:
        if self.canon_delta_payload_hash != self.canon_delta.payload_hash:
            raise ValueError("canon_delta_payload_hash must equal the embedded CanonDelta's own payload_hash")
        return self
