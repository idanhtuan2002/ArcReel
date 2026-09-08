"""Narrative context contracts: immutable source descriptors, requests, packs, traces.

Descriptor metadata is a claim, never a new authority. Prose is never a visibility
input. Selection traces are visibility-tiered: a source rejected before the visibility
gate carries only non-secret ids, status, and reason.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from .common import NonEmptyStr, R2ContractModel, ensure_json_value

SOURCE_DESCRIPTOR_HASH_VERSION = "r2-narrative-source-descriptor-v1"
SOURCE_CONTENT_HASH_VERSION = "r2-narrative-source-content-v1"

_PRE_VISIBILITY_REASONS = frozenset(
    {"WRONG_SCOPE", "MISSING_SOURCE_METADATA", "UNRESOLVED_VISIBILITY_BASIS", "OUT_OF_TIME", "NOT_VISIBLE"}
)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _aware_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


def _sorted_unique(values: list[NonEmptyStr]) -> list[NonEmptyStr]:
    return sorted(set(values))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        ensure_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def compute_source_content_hash(prose: str) -> str:
    normalized = unicodedata.normalize("NFC", prose).replace("\r\n", "\n").replace("\r", "\n")
    return "nsc:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class DescriptorAuthorityClass(StrEnum):
    ACCEPTED_NARRATIVE = "ACCEPTED_NARRATIVE"
    RETRIEVED_REFERENCE = "RETRIEVED_REFERENCE"
    SUMMARY = "SUMMARY"


class DescriptorVisibilityPolicy(StrEnum):
    AUTHOR_ONLY = "AUTHOR_ONLY"
    SUBJECTS = "SUBJECTS"


class ContextMode(StrEnum):
    AUTHOR_DRAFT = "AUTHOR_DRAFT"
    CHARACTER_SIMULATION = "CHARACTER_SIMULATION"


class ContextChannel(StrEnum):
    AUTHOR_TRUTH = "AUTHOR_TRUTH"
    POV_KNOWN = "POV_KNOWN"
    POV_SUSPECTED = "POV_SUSPECTED"
    POV_FALSE_BELIEF = "POV_FALSE_BELIEF"
    EXPLICIT_UNKNOWN = "EXPLICIT_UNKNOWN"
    AUTHORIAL_INTENT = "AUTHORIAL_INTENT"
    CREATIVE_POLICY = "CREATIVE_POLICY"
    RECENT_ACCEPTED = "RECENT_ACCEPTED"
    RETRIEVED_REFERENCE = "RETRIEVED_REFERENCE"
    SUMMARY = "SUMMARY"


class ContextDescriptorBasis(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    branch_id: NonEmptyStr | None = None
    canon_version_id: NonEmptyStr | None = None
    plan_id: NonEmptyStr | None = None
    plan_version: Annotated[int, Field(ge=1)] | None = None


class NarrativeSourceDescriptor(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    descriptor_ref: NonEmptyStr
    descriptor_hash_algorithm: Literal["sha256"] = "sha256"
    descriptor_hash_version: Literal["r2-narrative-source-descriptor-v1"] = "r2-narrative-source-descriptor-v1"
    source_ref: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    authority_class: DescriptorAuthorityClass
    source_basis_refs: list[NonEmptyStr]
    canon_basis: ContextDescriptorBasis | None = None
    plan_basis: ContextDescriptorBasis | None = None
    effective_from: datetime | None
    effective_until: datetime | None
    visibility_policy: DescriptorVisibilityPolicy
    proposition_refs: list[NonEmptyStr] = Field(default_factory=list)
    visibility_subjects: list[NonEmptyStr] = Field(default_factory=list)
    visibility_knowledge_state_refs: list[NonEmptyStr] = Field(default_factory=list)
    content_hash: NonEmptyStr
    content_hash_algorithm: Literal["sha256"] = "sha256"
    content_hash_version: Literal["r2-narrative-source-content-v1"] = "r2-narrative-source-content-v1"
    _effective_from_aware = field_validator("effective_from")(_aware_optional)
    _effective_until_aware = field_validator("effective_until")(_aware_optional)
    _source_basis_refs_sorted = field_validator("source_basis_refs")(_sorted_unique)
    _proposition_refs_sorted = field_validator("proposition_refs")(_sorted_unique)
    _visibility_subjects_sorted = field_validator("visibility_subjects")(_sorted_unique)
    _visibility_knowledge_state_refs_sorted = field_validator("visibility_knowledge_state_refs")(_sorted_unique)

    @model_validator(mode="after")
    def _validate_descriptor(self) -> NarrativeSourceDescriptor:
        if not self.source_basis_refs:
            raise ValueError("source_basis_refs must be non-empty")
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("descriptor effective_until must be after effective_from")

        canon_ok = self.canon_basis is not None and self.canon_basis.canon_version_id is not None
        plan_ok = (
            self.plan_basis is not None
            and self.plan_basis.plan_id is not None
            and self.plan_basis.plan_version is not None
        )

        if self.visibility_policy is DescriptorVisibilityPolicy.AUTHOR_ONLY:
            if self.visibility_subjects or self.proposition_refs or self.visibility_knowledge_state_refs:
                raise ValueError("AUTHOR_ONLY descriptors carry no subject/proposition/knowledge claims")
        else:  # SUBJECTS
            if not self.visibility_subjects or not self.proposition_refs or not self.visibility_knowledge_state_refs:
                raise ValueError("SUBJECTS descriptors require subjects, propositions, and knowledge-state refs")
            if not canon_ok:
                raise ValueError("SUBJECTS descriptors require an exact canon_basis")

        requires_both_bases = self.authority_class in (
            DescriptorAuthorityClass.ACCEPTED_NARRATIVE,
            DescriptorAuthorityClass.SUMMARY,
        )
        if requires_both_bases and not (canon_ok and plan_ok):
            raise ValueError(f"{self.authority_class.value} descriptors require exact canon_basis and plan_basis")

        expected = compute_descriptor_ref(self)
        if self.descriptor_ref != expected:
            raise ValueError(
                f"descriptor_ref {self.descriptor_ref!r} does not match the canonical descriptor {expected!r}"
            )
        return self


def compute_descriptor_ref(descriptor: NarrativeSourceDescriptor) -> str:
    payload = descriptor.model_dump(mode="json", exclude={"descriptor_ref"})
    return "nsd:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


class RetrievalCandidate(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: NonEmptyStr
    source_descriptor: NarrativeSourceDescriptor
    content: str
    score: float


class RetrievalSnapshot(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    snapshot_ref: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    query_fingerprint: NonEmptyStr
    candidates: list[RetrievalCandidate] = Field(default_factory=list)
    created_at: datetime
    retriever_version: NonEmptyStr
    _created_at_aware = field_validator("created_at")(_aware)


class NarrativeContextRequest(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    canon_branch_id: NonEmptyStr
    canon_version_id: NonEmptyStr
    plan_id: NonEmptyStr
    plan_version: Annotated[int, Field(ge=1)]
    scene_contract_id: NonEmptyStr
    scene_contract_version: Annotated[int, Field(ge=1)]
    creative_policy_ref: NonEmptyStr
    creative_policy_version: NonEmptyStr
    mode: ContextMode
    pov_subject_entity_id: NonEmptyStr | None = None
    story_time: datetime
    recent_accepted_refs: list[NonEmptyStr] = Field(default_factory=list)
    retrieval_snapshot_ref: NonEmptyStr | None = None
    token_budget: Annotated[int, Field(gt=0)]
    compiler_version: NonEmptyStr
    _story_time_aware = field_validator("story_time")(_aware)
    _recent_accepted_refs_sorted = field_validator("recent_accepted_refs")(_sorted_unique)

    @model_validator(mode="after")
    def _mode_requires_pov(self) -> NarrativeContextRequest:
        if self.mode is ContextMode.CHARACTER_SIMULATION and self.pov_subject_entity_id is None:
            raise ValueError("CHARACTER_SIMULATION requires a POV subject")
        return self


class NarrativeContextSegment(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    channel: ContextChannel
    source_ref: NonEmptyStr
    descriptor_ref: NonEmptyStr | None = None
    basis_refs: tuple[NonEmptyStr, ...] = ()
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    visibility_subjects: tuple[NonEmptyStr, ...] = ()
    priority: Annotated[int, Field(ge=1)]
    token_count: Annotated[int, Field(ge=0)]
    content_hash: NonEmptyStr
    content: str


class SelectionTraceStatus(StrEnum):
    INCLUDED = "INCLUDED"
    OMITTED = "OMITTED"


class SelectionTraceReason(StrEnum):
    INCLUDED = "INCLUDED"
    WRONG_SCOPE = "WRONG_SCOPE"
    MISSING_SOURCE_METADATA = "MISSING_SOURCE_METADATA"
    UNRESOLVED_VISIBILITY_BASIS = "UNRESOLVED_VISIBILITY_BASIS"
    OUT_OF_TIME = "OUT_OF_TIME"
    NOT_VISIBLE = "NOT_VISIBLE"
    DUPLICATE = "DUPLICATE"
    BUDGET = "BUDGET"


class SelectionTrace(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: NonEmptyStr
    source_ref: NonEmptyStr
    status: SelectionTraceStatus
    reason: SelectionTraceReason
    content_hash: NonEmptyStr | None = None
    token_count: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def _visibility_tiered(self) -> SelectionTrace:
        if self.reason.value in _PRE_VISIBILITY_REASONS and (
            self.content_hash is not None or self.token_count is not None
        ):
            raise ValueError("a pre-visibility rejection trace carries no content hash or token count")
        if self.status is SelectionTraceStatus.INCLUDED and self.reason is not SelectionTraceReason.INCLUDED:
            raise ValueError("an INCLUDED trace must carry reason INCLUDED")
        if self.status is SelectionTraceStatus.OMITTED and self.reason is SelectionTraceReason.INCLUDED:
            raise ValueError("an OMITTED trace must carry an omission reason")
        return self


class NarrativeContextPack(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    context_pack_id: NonEmptyStr
    base_canon_version: NonEmptyStr
    epistemic_view_ref: NonEmptyStr | None = None
    narrative_plan_refs: tuple[NonEmptyStr, ...] = ()
    creative_policy_ref: NonEmptyStr
    scene_contract_ref: NonEmptyStr
    pov: NonEmptyStr | None = None
    temporal_context: datetime
    segments: tuple[NarrativeContextSegment, ...] = ()
    recent_accepted_context: tuple[NarrativeContextSegment, ...] = ()
    retrieved_context: tuple[NarrativeContextSegment, ...] = ()
    token_budget: Annotated[int, Field(gt=0)]
    tokens_used: Annotated[int, Field(ge=0)]
    compiler_version: NonEmptyStr
    retrieval_snapshot_ref: NonEmptyStr | None = None
    dependency_refs: tuple[NonEmptyStr, ...] = ()
    selection_trace: tuple[SelectionTrace, ...] = ()
    content_hash: NonEmptyStr
    _temporal_context_aware = field_validator("temporal_context")(_aware)
