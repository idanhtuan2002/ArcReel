"""M5C immutable Narrative-lifecycle evidence contracts (design Section 4-5).

Every model is frozen, rejects extra fields, uses timezone-aware UTC timestamps, and
carries an explicitly versioned canonical hash domain. None of these contracts grants
acceptance or Canon authority: a writer identity, a predecessor link, a review ref, or
an extraction outcome is evidence only. Acceptance exists solely in the Section 6
decision stream (M5C-2). There is no ``accepted`` boolean anywhere in this module.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .common import JSONValue, NonEmptyStr, R2ContractModel
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
    mapping_version: Literal["r2-m5c-semantic-effect-key-v1"] = "r2-m5c-semantic-effect-key-v1"
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
    mapping_version: Literal["r2-m5c-semantic-effect-key-v1"] = "r2-m5c-semantic-effect-key-v1"
    thread_ref: NonEmptyStr
    payoff_ref: NonEmptyStr
    canon_operation_count: Literal[0] = 0


# The Narrative outcome family currently has exactly one member.
NarrativeOutcomeEffectKey = ThreadPayoffEffectKey

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
        return self
