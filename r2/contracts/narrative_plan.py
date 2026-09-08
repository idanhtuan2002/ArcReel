"""Authorial Intent contracts: the versioned NarrativePlan aggregate and typed SceneContract.

These describe *future intent*. Nothing here is a Canon fact or event, and no value
carries a repository, clock, provider, or write method. ``canon_basis`` is a read-only
cross-authority dependency, never permission to modify Canon.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from .common import JSONValue, NonEmptyStr, R2ContractModel
from .narrative import EpistemicState

PLAN_SCHEMA_VERSION = "r2-narrative-plan-v1"
PLAN_CONTENT_HASH_VERSION = "r2-narrative-plan-content-v1"
SCENE_CONTRACT_CONTENT_HASH_VERSION = "r2-scene-contract-content-v1"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _sorted_unique(values: list[NonEmptyStr]) -> list[NonEmptyStr]:
    return sorted(set(values))


class CanonBasis(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    branch_id: NonEmptyStr
    canon_version_id: NonEmptyStr


class SceneTemporalWindow(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    effective_from: datetime
    effective_until: datetime
    _effective_from_aware = field_validator("effective_from")(_aware)
    _effective_until_aware = field_validator("effective_until")(_aware)

    @model_validator(mode="after")
    def _window_is_non_empty_half_open(self) -> SceneTemporalWindow:
        if self.effective_until <= self.effective_from:
            raise ValueError("SceneTemporalWindow effective_until must be after effective_from")
        return self


class SceneFactConstraint(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    constraint_id: NonEmptyStr
    constraint_kind: Literal["FACT"] = "FACT"
    subject_ref: NonEmptyStr
    predicate: NonEmptyStr
    comparison: Literal["PRESENT", "ABSENT", "EQUALS", "NOT_EQUALS"]
    expected_value: JSONValue | None = None

    @model_validator(mode="after")
    def _value_matches_comparison(self) -> SceneFactConstraint:
        needs_value = self.comparison in ("EQUALS", "NOT_EQUALS")
        if needs_value and self.expected_value is None:
            raise ValueError(f"{self.comparison} SceneFactConstraint requires expected_value")
        if not needs_value and self.expected_value is not None:
            raise ValueError(f"{self.comparison} SceneFactConstraint forbids expected_value")
        return self


class SceneKnowledgeConstraint(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    constraint_id: NonEmptyStr
    constraint_kind: Literal["KNOWLEDGE"] = "KNOWLEDGE"
    subject_entity_id: NonEmptyStr
    proposition_ref: NonEmptyStr
    states: list[EpistemicState]
    include_absent: bool = False

    @model_validator(mode="after")
    def _states_non_empty(self) -> SceneKnowledgeConstraint:
        if not self.states:
            raise ValueError("SceneKnowledgeConstraint states must be non-empty")
        return self


SceneStateConstraint = Annotated[SceneFactConstraint | SceneKnowledgeConstraint, Field(discriminator="constraint_kind")]


class SceneEventConstraint(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    constraint_id: NonEmptyStr
    event_ref: NonEmptyStr | None = None
    event_type: NonEmptyStr | None = None
    participant_refs_all: list[NonEmptyStr] = Field(default_factory=list)
    location_ref: NonEmptyStr | None = None
    _participant_refs_all_sorted = field_validator("participant_refs_all")(_sorted_unique)

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> SceneEventConstraint:
        if (self.event_ref is None) == (self.event_type is None):
            raise ValueError("SceneEventConstraint requires exactly one of event_ref or event_type")
        return self


class CharacterRevealRecipient(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    recipient_kind: Literal["CHARACTER"] = "CHARACTER"
    subject_entity_id: NonEmptyStr
    resulting_state: Literal["KNOWN", "SUSPECTED", "FALSE_BELIEF"]


class AudienceRevealRecipient(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    recipient_kind: Literal["AUDIENCE"] = "AUDIENCE"
    audience_scope: Literal["STORY_AUDIENCE"] = "STORY_AUDIENCE"


RevealRecipient = Annotated[CharacterRevealRecipient | AudienceRevealRecipient, Field(discriminator="recipient_kind")]


class SceneRevealConstraint(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    constraint_id: NonEmptyStr
    proposition_ref: NonEmptyStr
    recipients: list[RevealRecipient]

    @model_validator(mode="after")
    def _recipients_non_empty(self) -> SceneRevealConstraint:
        if not self.recipients:
            raise ValueError("SceneRevealConstraint requires at least one recipient")
        return self


class AudienceRevealEvidence(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reveal_constraint_id: NonEmptyStr
    accepted_narrative_ref: NonEmptyStr
    source_descriptor_ref: NonEmptyStr
    audience_scope: Literal["STORY_AUDIENCE"] = "STORY_AUDIENCE"
    content_hash: NonEmptyStr


class NarrativePlanNode(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    node_id: NonEmptyStr
    node_kind: Literal["VOLUME", "EPISODE", "ARC", "CHAPTER"]
    version: Annotated[int, Field(ge=1)]
    parent_id: NonEmptyStr | None
    sequence_index: Annotated[int, Field(ge=0)]
    intent: NonEmptyStr
    expected_progression: list[NonEmptyStr] = Field(default_factory=list)
    child_refs: list[NonEmptyStr] = Field(default_factory=list)
    constraints: list[NonEmptyStr] = Field(default_factory=list)
    approval_refs: list[NonEmptyStr] = Field(default_factory=list)
    _child_refs_sorted = field_validator("child_refs")(_sorted_unique)
    _constraints_sorted = field_validator("constraints")(_sorted_unique)
    _approval_refs_sorted = field_validator("approval_refs")(_sorted_unique)


class SceneContract(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    scene_contract_id: NonEmptyStr
    version: Annotated[int, Field(ge=1)]
    semantic_hash: NonEmptyStr
    semantic_hash_algorithm: Literal["sha256"] = "sha256"
    semantic_hash_version: Literal["r2-scene-contract-content-v1"] = "r2-scene-contract-content-v1"
    sequence_index: Annotated[int, Field(ge=0)]
    purpose: NonEmptyStr
    pov: NonEmptyStr | None
    location_ref: NonEmptyStr | None
    temporal_window: SceneTemporalWindow
    participants: list[NonEmptyStr] = Field(default_factory=list)
    required_events: list[SceneEventConstraint] = Field(default_factory=list)
    forbidden_events: list[SceneEventConstraint] = Field(default_factory=list)
    required_reveals: list[SceneRevealConstraint] = Field(default_factory=list)
    forbidden_knowledge: list[SceneKnowledgeConstraint] = Field(default_factory=list)
    entry_state_constraints: list[SceneStateConstraint] = Field(default_factory=list)
    exit_state_targets: list[SceneStateConstraint] = Field(default_factory=list)
    active_threads: list[NonEmptyStr] = Field(default_factory=list)
    promise_payoff_refs: list[NonEmptyStr] = Field(default_factory=list)
    creative_constraints: list[NonEmptyStr] = Field(default_factory=list)
    _participants_sorted = field_validator("participants")(_sorted_unique)
    _active_threads_sorted = field_validator("active_threads")(_sorted_unique)
    _promise_payoff_refs_sorted = field_validator("promise_payoff_refs")(_sorted_unique)
    _creative_constraints_sorted = field_validator("creative_constraints")(_sorted_unique)


class NarrativePlanContent(R2ContractModel):
    """The semantic bytes of a plan revision. Commit-receipt fields live outside it."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["r2-narrative-plan-v1"] = "r2-narrative-plan-v1"
    parent_version: Annotated[int, Field(ge=1)] | None = None
    canon_basis: CanonBasis
    story_frame: NonEmptyStr
    volume_plans: list[NarrativePlanNode] = Field(default_factory=list)
    episode_plans: list[NarrativePlanNode] = Field(default_factory=list)
    arc_plans: list[NarrativePlanNode] = Field(default_factory=list)
    chapter_plans: list[NarrativePlanNode] = Field(default_factory=list)
    scene_contracts: list[SceneContract] = Field(default_factory=list)


class NarrativePlan(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    plan_id: NonEmptyStr
    version: Annotated[int, Field(ge=1)]
    content: NarrativePlanContent
    content_hash: NonEmptyStr
    content_hash_algorithm: Literal["sha256"] = "sha256"
    content_hash_version: Literal["r2-narrative-plan-content-v1"] = "r2-narrative-plan-content-v1"
    committed_at: datetime
    committed_by: NonEmptyStr
    approval_ref: NonEmptyStr
    _committed_at_aware = field_validator("committed_at")(_aware)


class NarrativePlanRevisionProposal(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    plan_revision_id: NonEmptyStr
    plan_id: NonEmptyStr
    expected_version: Annotated[int, Field(ge=1)] | None
    proposed_content: NarrativePlanContent
    content_hash: NonEmptyStr
    created_at: datetime
    created_by: NonEmptyStr
    _created_at_aware = field_validator("created_at")(_aware)


class NarrativePlanApproval(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    approval_ref: NonEmptyStr
    plan_revision_id: NonEmptyStr
    plan_id: NonEmptyStr
    expected_version: Annotated[int, Field(ge=1)] | None
    content_hash: NonEmptyStr
    project_name: NonEmptyStr
    user_id: NonEmptyStr
    approved_by: NonEmptyStr
    approved_at: datetime
    status: Literal["APPROVED"] = "APPROVED"
    _approved_at_aware = field_validator("approved_at")(_aware)


class NarrativePlanNodeKind(StrEnum):
    VOLUME = "VOLUME"
    EPISODE = "EPISODE"
    ARC = "ARC"
    CHAPTER = "CHAPTER"


class NarrativePlanCommitResult(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    plan: NarrativePlan
    plan_revision_id: NonEmptyStr
