"""Immutable M10-A evidence data; construction grants neither authority nor currentness."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, get_origin
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)

from r2.advanced_creative.digests import canonical_json_bytes
from r2.artifact_identity import decode_episode_video_key, episode_video_key, validate_m3_target_ref
from r2.contracts.advanced_creative import CanonicalJsonObject, Sha256Digest
from r2.contracts.artifact_metadata import R2ArtifactMetadata
from r2.contracts.common import R2ContractModel
from r2.contracts.host_hardening import MasterHeadSnapshot


def _exact(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value)
    ):
        raise ValueError("identity must be exact and nonempty")
    value.encode("utf-8")
    return value


def _entity(value: object) -> str:
    text = _exact(value)
    parsed = UUID(text)
    if parsed.version != 7 or str(parsed) != text:
        raise ValueError("M10 entity identity must be canonical UUIDv7")
    return text


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("text must be nonblank")
    value.encode("utf-8")
    return value


ExactIdentity = Annotated[str, BeforeValidator(_exact)]
M10Uuid7 = Annotated[str, BeforeValidator(_entity)]
NonBlankText = Annotated[str, BeforeValidator(_text)]


def require_ordered_collection(value: object) -> list[Any] | tuple[Any, ...]:
    """Accept JSON arrays and explicit tuples, never infer order from another iterable."""
    if not isinstance(value, (list, tuple)):
        raise ValueError("ordered collection requires list or tuple input")
    return value


class M10ContractModel(R2ContractModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_assignment=True, revalidate_instances="always", allow_inf_nan=False
    )

    @model_validator(mode="before")
    @classmethod
    def explicit_collection_order(cls, value: object) -> object:
        if isinstance(value, M10ContractModel):
            value = dict(value)
        if isinstance(value, Mapping):
            for name, field in cls.model_fields.items():
                if name in value and (get_origin(field.annotation) is tuple or field.annotation is tuple):
                    require_ordered_collection(value[name])
        return value


def _unique(values: Iterable[object]) -> None:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise ValueError("duplicate identity")


def _media(value: str) -> str:
    normalized = value.removeprefix("sha256:").lower()
    if re.fullmatch("[0-9a-f]{64}", normalized) is None:
        raise ValueError("invalid media digest")
    return normalized


def _raw_head(value: object) -> object:
    data = value.model_dump(mode="python") if isinstance(value, MasterHeadSnapshot) else value
    if not isinstance(data, Mapping) or type(data.get("master_version")) is not int:
        raise ValueError("head version must be a strict integer")
    for field in ("artifact_key", "candidate_id", "object_ref", "content_digest", "approval_record"):
        _exact(data.get(field))
    _media(data["content_digest"])
    return data


def _parent(value: Any) -> None:
    expected = None if value.revision == 1 else value.revision - 1
    if value.parent_revision != expected:
        raise ValueError("profile parent is not contiguous")


def _window(start: datetime, end: datetime, maximum: int) -> None:
    if not 0 < (end - start).total_seconds() <= maximum:
        raise ValueError("invalid explicit time window")


def _waivers(values: tuple[Any, ...]) -> tuple[Any, ...]:
    _unique((r.rule_id, r.finding_id, r.scope) for r in values)
    return tuple(sorted(values, key=canonical_json_bytes))


def _decision(decision: str, waivers: tuple[Any, ...]) -> None:
    if (decision == "WAIVE") != bool(waivers):
        raise ValueError("only WAIVE requires nonempty waivers")


def _command(command: Any, subject: Any, operation: str) -> None:
    if command.operation != operation or (command.user_id, command.project_name, command.actor_id) != (
        subject.user_id,
        subject.project_name,
        subject.actor_id,
    ):
        raise ValueError("command scope, actor or action mismatch")


class ArtifactMetadataSnapshot(M10ContractModel):
    artifact_key: ExactIdentity
    body: CanonicalJsonObject
    metadata_digest: Sha256Digest

    @field_validator("body", mode="before")
    @classmethod
    def copy_body(cls, value: object) -> object:
        return value.model_dump(mode="python") if isinstance(value, CanonicalJsonObject) else value

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _, resource = decode_episode_video_key(self.artifact_key)
        validate_m3_target_ref(resource)
        material = self.body.model_dump(mode="json")
        temporary = R2ArtifactMetadata.model_validate(material)
        if canonical_json_bytes(material) != canonical_json_bytes(temporary.model_dump(mode="json")):
            raise ValueError("metadata must already be fully normalized")
        if temporary.contract_ref.id != resource or temporary.approved_master is None:
            raise ValueError("metadata identity or approval mismatch")
        pending: list[object] = [material]
        while pending:
            value = pending.pop()
            if isinstance(value, str):
                _exact(value)
            elif isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return self


class MasterDependencyEdge(M10ContractModel):
    parent_artifact_key: ExactIdentity
    child_artifact_key: ExactIdentity
    dependency_ref: ExactIdentity


class MasterBindingV1(M10ContractModel):
    schema_id: Literal["m10.master-binding.v1"]
    user_id: ExactIdentity
    project_name: ExactIdentity
    root: MasterHeadSnapshot
    dependency_heads: tuple[MasterHeadSnapshot, ...]
    metadata_snapshots: tuple[ArtifactMetadataSnapshot, ...]
    dependency_edges: tuple[MasterDependencyEdge, ...]

    @field_validator("root", mode="before")
    @classmethod
    def strict_root(cls, value: object) -> object:
        return _raw_head(value)

    @field_validator("dependency_heads", mode="before")
    @classmethod
    def strict_dependencies(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("heads must be a collection")
        return tuple(_raw_head(item) for item in value)

    @field_validator("dependency_heads")
    @classmethod
    def heads_order(cls, value: tuple[MasterHeadSnapshot, ...]) -> tuple[MasterHeadSnapshot, ...]:
        _unique(h.artifact_key for h in value)
        return tuple(sorted(value, key=lambda h: h.artifact_key.encode("utf-8")))

    @field_validator("metadata_snapshots")
    @classmethod
    def metadata_order(cls, value: tuple[ArtifactMetadataSnapshot, ...]) -> tuple[ArtifactMetadataSnapshot, ...]:
        _unique(s.artifact_key for s in value)
        return tuple(sorted(value, key=lambda s: s.artifact_key.encode("utf-8")))

    @field_validator("dependency_edges")
    @classmethod
    def edges_order(cls, value: tuple[MasterDependencyEdge, ...]) -> tuple[MasterDependencyEdge, ...]:
        _unique((e.parent_artifact_key, e.dependency_ref, e.child_artifact_key) for e in value)
        return tuple(
            sorted(
                value,
                key=lambda e: (
                    e.parent_artifact_key.encode("utf-8"),
                    e.dependency_ref.encode("utf-8"),
                    e.child_artifact_key.encode("utf-8"),
                ),
            )
        )

    @model_validator(mode="after")
    def coherent(self) -> Self:
        heads = (self.root, *self.dependency_heads)
        _unique(h.artifact_key for h in heads)
        by_key = {h.artifact_key: h for h in heads}
        snapshots = {s.artifact_key: s.body.model_dump(mode="json") for s in self.metadata_snapshots}
        if set(by_key) != set(snapshots):
            raise ValueError("metadata closure mismatch")
        expected: dict[tuple[str, str], dict[str, Any]] = {}
        for head in heads:
            body = snapshots[head.artifact_key]
            if body["approved_master"]["approval_record"] != head.approval_record:
                raise ValueError("approval mismatch")
            for dependency in body["direct_dependencies"]:
                if dependency["ref"].startswith("master:"):
                    expected[(head.artifact_key, dependency["ref"])] = dependency
        _unique((e.parent_artifact_key, e.dependency_ref) for e in self.dependency_edges)
        if set(expected) != {(e.parent_artifact_key, e.dependency_ref) for e in self.dependency_edges}:
            raise ValueError("master edge closure mismatch")
        children: dict[str, list[str]] = {k: [] for k in by_key}
        indegree = dict.fromkeys(by_key, 0)
        for edge in self.dependency_edges:
            if edge.parent_artifact_key not in by_key or edge.child_artifact_key not in by_key:
                raise ValueError("unknown head")
            parent_episode, _ = decode_episode_video_key(edge.parent_artifact_key)
            child_episode, child_resource = decode_episode_video_key(edge.child_artifact_key)
            ref = edge.dependency_ref.removeprefix("master:")
            validate_m3_target_ref(ref)
            child_body = snapshots[edge.child_artifact_key]
            if (
                parent_episode != child_episode
                or child_resource != ref
                or edge.child_artifact_key != episode_video_key(parent_episode, ref)
                or child_body["contract_ref"]["contract_type"] != "ShotSpec"
            ):
                raise ValueError("child resource mismatch")
            dependency = expected[(edge.parent_artifact_key, edge.dependency_ref)]
            approved = child_body["approved_master"]
            if dependency["version"] != approved["selected_candidate_id"] + "@" + approved[
                "host_version_ref"
            ] or _media(dependency["fingerprint"]) != _media(by_key[edge.child_artifact_key].content_digest):
                raise ValueError("dependency version or media mismatch")
            children[edge.parent_artifact_key].append(edge.child_artifact_key)
            indegree[edge.child_artifact_key] += 1
        pending = [k for k, count in indegree.items() if count == 0]
        processed = 0
        while pending:
            node = pending.pop()
            processed += 1
            for child in children[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    pending.append(child)
        if processed != len(heads):
            raise ValueError("master dependency cycle")
        reached: set[str] = set()
        pending = [self.root.artifact_key]
        while pending:
            node = pending.pop()
            if node not in reached:
                reached.add(node)
                pending.extend(children[node])
        if reached != set(by_key):
            raise ValueError("unreachable dependency head")
        return self


class AssessorKind(StrEnum):
    TECHNICAL = "TECHNICAL"
    FACTUAL = "FACTUAL"
    NARRATIVE = "NARRATIVE"
    CONTINUITY = "CONTINUITY"
    PERCEPTUAL = "PERCEPTUAL"
    ACCESSIBILITY = "ACCESSIBILITY"


class ObservationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INAPPLICABLE = "INAPPLICABLE"
    INDETERMINATE = "INDETERMINATE"


class DispositionDecision(StrEnum):
    PASS = "PASS"
    REWORK = "REWORK"
    WAIVE = "WAIVE"


class AssessorClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    AUTHORITY = "AUTHORITY"
    MODEL = "MODEL"
    HUMAN = "HUMAN"


class RequirementMode(StrEnum):
    ALL = "ALL"
    N_OF_M = "N_OF_M"


class SupersessionEffect(StrEnum):
    HISTORICAL_ONLY = "HISTORICAL_ONLY"
    REEVALUATE_CURRENT = "REEVALUATE_CURRENT"


class AssessmentSlot(M10ContractModel):
    slot_id: ExactIdentity
    kind: AssessorKind
    assessor_class: AssessorClass
    qualification_policy_id: ExactIdentity
    qualification_policy_digest: Sha256Digest
    rule_ids: tuple[ExactIdentity, ...]
    allowed_applicability_states: tuple[ObservationStatus, ...]
    producer_conflict_forbidden: StrictBool
    required_independence_groups: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _unique(self.rule_ids)
        _unique(self.allowed_applicability_states)
        if not self.allowed_applicability_states:
            raise ValueError("missing applicability states")
        return self


class AssessmentRequirement(M10ContractModel):
    requirement_id: ExactIdentity
    mode: RequirementMode
    slots: tuple[AssessmentSlot, ...]
    minimum_satisfied_slots: StrictInt = Field(ge=1)
    disagreement_policy_id: ExactIdentity
    disagreement_policy_digest: Sha256Digest
    escalation_requirement_id: ExactIdentity | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _unique(s.slot_id for s in self.slots)
        if (
            not self.slots
            or self.minimum_satisfied_slots > len(self.slots)
            or (self.mode == RequirementMode.ALL and self.minimum_satisfied_slots != len(self.slots))
        ):
            raise ValueError("invalid slot count")
        return self


def validate_requirements(values: tuple[AssessmentRequirement, ...]) -> tuple[AssessmentRequirement, ...]:
    """Validate the self-contained requirement graph without resolving qualifications."""
    _unique(r.requirement_id for r in values)
    _unique(s.slot_id for r in values for s in r.slots)
    graph = {r.requirement_id: r.escalation_requirement_id for r in values}
    for key in graph:
        seen: set[str] = set()
        node: str | None = key
        while node is not None:
            if node not in graph or node in seen:
                raise ValueError("unknown or cyclic escalation")
            seen.add(node)
            node = graph[node]
    return values


class ProbeRule(M10ContractModel):
    rule_id: ExactIdentity
    probe_kind: ExactIdentity
    tool_identity: ExactIdentity
    tool_version_constraint: ExactIdentity
    config_schema_id: ExactIdentity
    config_digest: Sha256Digest
    applicability_policy_id: ExactIdentity
    applicability_policy_digest: Sha256Digest
    threshold_policy_id: ExactIdentity
    threshold_policy_digest: Sha256Digest
    max_runtime_ms: StrictInt = Field(gt=0)
    max_output_bytes: StrictInt = Field(gt=0)


class FreshnessRule(M10ContractModel):
    rule_id: ExactIdentity
    evidence_kind: AssessorKind
    max_age_seconds: StrictInt = Field(gt=0)
    supersession_effect: SupersessionEffect


class DispositionRule(M10ContractModel):
    max_disposition_ttl_seconds: StrictInt = Field(gt=0, le=604800)
    max_waiver_ttl_seconds: StrictInt = Field(gt=0, le=86400)
    waiverable_rule_ids: tuple[ExactIdentity, ...]
    non_waiverable_failure_codes: tuple[ExactIdentity, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _unique(self.waiverable_rule_ids)
        _unique(self.non_waiverable_failure_codes)
        return self


class AccessibilityRule(M10ContractModel):
    conformance_target: ExactIdentity
    language: ExactIdentity
    caption_rubric_id: ExactIdentity
    caption_rubric_digest: Sha256Digest
    audio_description_policy_id: ExactIdentity
    audio_description_policy_digest: Sha256Digest


class QualityPolicyV1(M10ContractModel):
    schema_id: Literal["m10.quality-policy.v1"]
    probe_rules: tuple[ProbeRule, ...]
    assessment_requirements: tuple[AssessmentRequirement, ...]
    freshness_rules: tuple[FreshnessRule, ...]
    disposition_rule: DispositionRule
    accessibility_rules: tuple[AccessibilityRule, ...]
    reference_eligibility_policy_id: ExactIdentity
    reference_eligibility_policy_digest: Sha256Digest
    rule_ids: tuple[ExactIdentity, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if not self.rule_ids:
            raise ValueError("empty rule catalog")
        _unique(self.rule_ids)
        _unique(p.rule_id for p in self.probe_rules)
        _unique((f.rule_id, f.evidence_kind) for f in self.freshness_rules)
        validate_requirements(self.assessment_requirements)
        refs = (
            [p.rule_id for p in self.probe_rules]
            + [f.rule_id for f in self.freshness_rules]
            + list(self.disposition_rule.waiverable_rule_ids)
            + [rule for r in self.assessment_requirements for s in r.slots for rule in s.rule_ids]
        )
        if not set(refs) <= set(self.rule_ids):
            raise ValueError("unknown rule")
        return self


class QualityProfileDraft(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    profile_id: M10Uuid7
    revision: StrictInt = Field(ge=1)
    parent_revision: Annotated[StrictInt, Field(ge=1)] | None
    cohort_id: ExactIdentity
    product_surface: ExactIdentity
    policy: QualityPolicyV1
    policy_digest: Sha256Digest
    supersession_effect: SupersessionEffect
    created_by: ExactIdentity
    created_at: AwareDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _parent(self)
        return self


class QualityProfileRevision(M10ContractModel):
    profile_id: M10Uuid7
    revision: StrictInt = Field(ge=1)
    cohort_id: ExactIdentity
    product_surface: ExactIdentity
    policy: QualityPolicyV1
    policy_digest: Sha256Digest
    profile_digest: Sha256Digest
    parent_revision: Annotated[StrictInt, Field(ge=1)] | None
    supersession_effect: SupersessionEffect
    publication_authorization_id: ExactIdentity
    publication_policy_id: ExactIdentity
    publication_policy_version: ExactIdentity
    publication_evidence_digest: Sha256Digest
    publication_admitted_at: AwareDatetime
    created_by: ExactIdentity
    created_at: AwareDatetime
    user_id: ExactIdentity
    project_name: ExactIdentity
    publication_subject_digest: Sha256Digest
    publication_request_digest: Sha256Digest

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _parent(self)
        return self


class AssessedSubject(M10ContractModel):
    master_binding: MasterBindingV1
    master_binding_digest: Sha256Digest
    artifact_ref: ExactIdentity
    artifact_digest: Sha256Digest
    content_basis_digest: Sha256Digest
    caption_digest: Sha256Digest | None
    audio_digest: Sha256Digest | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.artifact_ref != self.master_binding.root.object_ref or self.artifact_digest != "sha256:" + _media(
            self.master_binding.root.content_digest
        ):
            raise ValueError("subject root mismatch")
        return self


class ObservationType(StrEnum):
    TECHNICAL = "TECHNICAL"
    FACTUAL = "FACTUAL"
    NARRATIVE = "NARRATIVE"
    CONTINUITY = "CONTINUITY"
    PERCEPTUAL_REGRESSION = "PERCEPTUAL_REGRESSION"
    PERCEPTUAL_REVIEW = "PERCEPTUAL_REVIEW"
    ACCESSIBILITY = "ACCESSIBILITY"


class QualityFinding(M10ContractModel):
    finding_id: M10Uuid7
    rule_id: ExactIdentity
    severity: Literal["BLOCKING", "ADVISORY"]
    subject_locator: ExactIdentity
    evidence_digest: Sha256Digest


class ObservationBase[Kind: ObservationType](M10ContractModel):
    observation_id: M10Uuid7
    observation_type: Kind
    requirement_id: ExactIdentity
    slot_id: ExactIdentity
    assessor_identity: ExactIdentity
    assessor_version: ExactIdentity
    assessor_qualification_ref: ExactIdentity
    assessor_qualification_digest: Sha256Digest
    independence_group: ExactIdentity
    producer_conflict: StrictBool
    config_digest: Sha256Digest
    subject_digest: Sha256Digest
    status: ObservationStatus
    findings: tuple[QualityFinding, ...]
    evidence_refs: tuple[ExactIdentity, ...]
    evidence_digest: Sha256Digest
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _unique(f.finding_id for f in self.findings)
        return self


class TechnicalObservation(ObservationBase[Literal[ObservationType.TECHNICAL]]):
    observation_type: Literal[ObservationType.TECHNICAL]
    rule_id: ExactIdentity
    probe_receipt_ref: ExactIdentity
    probe_receipt_digest: Sha256Digest
    tool_identity_digest: Sha256Digest
    measurement_schema_id: ExactIdentity
    measurement_digest: Sha256Digest
    interval_evidence_digest: Sha256Digest | None


class FactualObservation(ObservationBase[Literal[ObservationType.FACTUAL]]):
    observation_type: Literal[ObservationType.FACTUAL]
    claim_ledger_projection_ref: ExactIdentity
    claim_ledger_projection_digest: Sha256Digest
    research_pack_ref: ExactIdentity
    research_pack_digest: Sha256Digest
    correction_head_digest: Sha256Digest
    coverage_digest: Sha256Digest
    withdrawn: StrictBool


class NarrativeObservation(ObservationBase[Literal[ObservationType.NARRATIVE]]):
    observation_type: Literal[ObservationType.NARRATIVE]
    rubric_id: ExactIdentity
    rubric_digest: Sha256Digest
    segment_closure_digest: Sha256Digest
    reviewer_evidence_digest: Sha256Digest


class ContinuityObservation(ObservationBase[Literal[ObservationType.CONTINUITY]]):
    observation_type: Literal[ObservationType.CONTINUITY]
    canon_projection_digest: Sha256Digest
    epistemic_projection_digest: Sha256Digest
    visual_identity_projection_digest: Sha256Digest
    invariant_ids: tuple[ExactIdentity, ...]


class PerceptualRegressionObservation(ObservationBase[Literal[ObservationType.PERCEPTUAL_REGRESSION]]):
    observation_type: Literal[ObservationType.PERCEPTUAL_REGRESSION]
    reference_relationship: ExactIdentity
    reference_subject_digest: Sha256Digest
    distorted_subject_digest: Sha256Digest
    alignment_policy_digest: Sha256Digest
    model_identity_digest: Sha256Digest
    segment_result_digest: Sha256Digest


class PerceptualReviewObservation(ObservationBase[Literal[ObservationType.PERCEPTUAL_REVIEW]]):
    observation_type: Literal[ObservationType.PERCEPTUAL_REVIEW]
    rubric_id: ExactIdentity
    rubric_digest: Sha256Digest
    model_or_human_identity_digest: Sha256Digest
    calibration_cohort_digest: Sha256Digest
    sampling_policy_digest: Sha256Digest


class AccessibilityObservation(ObservationBase[Literal[ObservationType.ACCESSIBILITY]]):
    observation_type: Literal[ObservationType.ACCESSIBILITY]
    conformance_target: ExactIdentity
    language: ExactIdentity
    caption_artifact_digest: Sha256Digest | None
    audio_description_artifact_digest: Sha256Digest | None
    speech_coverage_digest: Sha256Digest
    non_speech_coverage_digest: Sha256Digest
    synchronization_digest: Sha256Digest
    legibility_collision_digest: Sha256Digest


QualityObservation = Annotated[
    TechnicalObservation
    | FactualObservation
    | NarrativeObservation
    | ContinuityObservation
    | PerceptualRegressionObservation
    | PerceptualReviewObservation
    | AccessibilityObservation,
    Field(discriminator="observation_type"),
]


class AssessmentSlotResult(M10ContractModel):
    requirement_id: ExactIdentity
    slot_id: ExactIdentity
    observation_refs: tuple[M10Uuid7, ...]
    observation_digests: tuple[Sha256Digest, ...]
    distinct_independence_groups: tuple[ExactIdentity, ...]
    state: Literal["SATISFIED", "NOT_APPLICABLE", "FAILED", "INDETERMINATE"]
    escalation_observation_refs: tuple[M10Uuid7, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if not self.observation_refs or len(self.observation_refs) != len(self.observation_digests):
            raise ValueError("observation refs/digests not parallel")
        _unique(self.observation_refs)
        _unique(self.distinct_independence_groups)
        _unique(self.escalation_observation_refs)
        return self


class ObservationBinding(M10ContractModel):
    observation_id: M10Uuid7
    observation_type: ObservationType
    observation_digest: Sha256Digest
    requirement_id: ExactIdentity
    slot_id: ExactIdentity


class QualityRun(M10ContractModel):
    run_id: M10Uuid7
    subject: AssessedSubject
    subject_digest: Sha256Digest
    profile_id: M10Uuid7
    profile_revision: StrictInt = Field(ge=1)
    profile_digest: Sha256Digest
    observation_refs: tuple[M10Uuid7, ...]
    observation_closure_digest: Sha256Digest
    slot_results: tuple[AssessmentSlotResult, ...]
    requirements_digest: Sha256Digest
    execution_refs: tuple[ExactIdentity, ...]
    completed_at: AwareDatetime

    @field_validator("execution_refs")
    @classmethod
    def execution_order(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _unique(value)
        return tuple(sorted(value, key=lambda s: s.encode("utf-8")))

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if not self.observation_refs:
            raise ValueError("empty run closure")
        _unique(self.observation_refs)
        _unique((s.requirement_id, s.slot_id) for s in self.slot_results)
        primary = tuple(ref for s in self.slot_results for ref in s.observation_refs)
        _unique(primary)
        if set(primary) != set(self.observation_refs) or not {
            ref for s in self.slot_results for ref in s.escalation_observation_refs
        } <= set(self.observation_refs):
            raise ValueError("run closure mismatch")
        return self


class WaiverBinding(M10ContractModel):
    rule_id: ExactIdentity
    finding_id: M10Uuid7 | None
    scope: ExactIdentity
    justification: NonBlankText


class CommandEnvelope(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    operation: Literal["PUBLISH_PROFILE", "COMPLETE_RUN", "ISSUE_DISPOSITION"]
    command_id: ExactIdentity
    request_digest: Sha256Digest


class CommandReceipt(M10ContractModel):
    command: CommandEnvelope
    result_ref: ExactIdentity
    result_digest: Sha256Digest
    committed_at: AwareDatetime


class ProfilePublicationAuthorizationLease(M10ContractModel):
    authorization_id: ExactIdentity
    action: Literal["PROFILE_PUBLICATION"]
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    command_id: ExactIdentity
    request_digest: Sha256Digest
    subject_digest: Sha256Digest
    policy_id: ExactIdentity
    policy_version: ExactIdentity
    evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _window(self.issued_at, self.admit_not_after, 30)
        return self


class DispositionAuthorizationLease(M10ContractModel):
    authorization_id: ExactIdentity
    action: Literal["QUALITY_DISPOSITION"]
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    command_id: ExactIdentity
    request_digest: Sha256Digest
    subject_digest: Sha256Digest
    policy_id: ExactIdentity
    policy_version: ExactIdentity
    evidence_digest: Sha256Digest
    issued_at: AwareDatetime
    admit_not_after: AwareDatetime

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _window(self.issued_at, self.admit_not_after, 30)
        return self


class QualityDisposition(M10ContractModel):
    disposition_id: M10Uuid7
    subject_digest: Sha256Digest
    quality_run_id: M10Uuid7
    quality_run_digest: Sha256Digest
    profile_digest: Sha256Digest
    decision: DispositionDecision
    waiver_bindings: tuple[WaiverBinding, ...]
    issuer_id: ExactIdentity
    custodian_authorization_id: ExactIdentity
    custodian_policy_id: ExactIdentity
    custodian_policy_version: ExactIdentity
    custodian_evidence_digest: Sha256Digest
    custodian_admitted_at: AwareDatetime
    reason: NonBlankText
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    supersedes_disposition_id: M10Uuid7 | None
    profile_id: M10Uuid7
    profile_revision: StrictInt = Field(ge=1)

    @field_validator("waiver_bindings")
    @classmethod
    def waiver_order(cls, value: tuple[WaiverBinding, ...]) -> tuple[WaiverBinding, ...]:
        return _waivers(value)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _decision(self.decision, self.waiver_bindings)
        _window(self.issued_at, self.expires_at, 86400 if self.decision == DispositionDecision.WAIVE else 604800)
        if self.issued_at != self.custodian_admitted_at:
            raise ValueError("issue/admission time mismatch")
        return self


class ProfilePublicationSubject(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    profile_draft: QualityProfileDraft
    profile_draft_digest: Sha256Digest
    expected_profile_revision: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        draft = self.profile_draft
        if (
            (draft.user_id, draft.project_name, draft.created_by) != (self.user_id, self.project_name, self.actor_id)
            or draft.revision != self.expected_profile_revision + 1
            or draft.parent_revision
            != (None if self.expected_profile_revision == 0 else self.expected_profile_revision)
        ):
            raise ValueError("publication draft binding mismatch")
        return self


class ProfilePublicationAuthorizationRequest(M10ContractModel):
    command: CommandEnvelope
    subject: ProfilePublicationSubject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _command(self.command, self.subject, "PUBLISH_PROFILE")
        return self


class DispositionSubject(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    subject_digest: Sha256Digest
    quality_run_id: M10Uuid7
    quality_run_digest: Sha256Digest
    profile_id: M10Uuid7
    profile_revision: StrictInt = Field(ge=1)
    profile_digest: Sha256Digest
    decision: DispositionDecision
    waiver_bindings: tuple[WaiverBinding, ...]
    reason: NonBlankText
    requested_expires_at: AwareDatetime
    expected_disposition_version: StrictInt = Field(ge=0)

    @field_validator("waiver_bindings")
    @classmethod
    def waiver_order(cls, value: tuple[WaiverBinding, ...]) -> tuple[WaiverBinding, ...]:
        return _waivers(value)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _decision(self.decision, self.waiver_bindings)
        return self


class DispositionAuthorizationRequest(M10ContractModel):
    command: CommandEnvelope
    subject: DispositionSubject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _command(self.command, self.subject, "ISSUE_DISPOSITION")
        return self


class RunCompletionSubject(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    run_id: M10Uuid7
    subject: AssessedSubject
    subject_digest: Sha256Digest
    profile_id: M10Uuid7
    profile_revision: StrictInt = Field(ge=1)
    profile_digest: Sha256Digest
    observations: tuple[ObservationBinding, ...] = Field(min_length=1)
    observation_closure_digest: Sha256Digest
    requirements_digest: Sha256Digest
    execution_refs: tuple[ExactIdentity, ...]

    @field_validator("observations")
    @classmethod
    def observation_order(cls, value: tuple[ObservationBinding, ...]) -> tuple[ObservationBinding, ...]:
        if not value:
            raise ValueError("empty observation closure")
        _unique(o.observation_id for o in value)
        return tuple(
            sorted(
                value,
                key=lambda o: (
                    o.requirement_id.encode("utf-8"),
                    o.slot_id.encode("utf-8"),
                    o.observation_id.encode("utf-8"),
                ),
            )
        )

    @field_validator("execution_refs")
    @classmethod
    def execution_order(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        _unique(value)
        return tuple(sorted(value, key=lambda s: s.encode("utf-8")))

    @model_validator(mode="after")
    def coherent(self) -> Self:
        binding = self.subject.master_binding
        if (binding.user_id, binding.project_name) != (self.user_id, self.project_name):
            raise ValueError("master scope mismatch")
        return self


class CompleteRunCommand(M10ContractModel):
    command: CommandEnvelope
    subject: RunCompletionSubject

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _command(self.command, self.subject, "COMPLETE_RUN")
        return self


__all__ = [
    "AccessibilityObservation",
    "AccessibilityRule",
    "ArtifactMetadataSnapshot",
    "AssessedSubject",
    "AssessmentRequirement",
    "AssessmentSlot",
    "AssessmentSlotResult",
    "AssessorClass",
    "AssessorKind",
    "CommandEnvelope",
    "CommandReceipt",
    "CompleteRunCommand",
    "ContinuityObservation",
    "DispositionAuthorizationLease",
    "DispositionAuthorizationRequest",
    "DispositionDecision",
    "DispositionRule",
    "DispositionSubject",
    "ExactIdentity",
    "FactualObservation",
    "FreshnessRule",
    "M10ContractModel",
    "M10Uuid7",
    "MasterBindingV1",
    "MasterDependencyEdge",
    "NarrativeObservation",
    "ObservationBase",
    "ObservationBinding",
    "ObservationStatus",
    "ObservationType",
    "PerceptualRegressionObservation",
    "PerceptualReviewObservation",
    "ProbeRule",
    "ProfilePublicationAuthorizationLease",
    "ProfilePublicationAuthorizationRequest",
    "ProfilePublicationSubject",
    "QualityDisposition",
    "QualityFinding",
    "QualityObservation",
    "QualityPolicyV1",
    "QualityProfileDraft",
    "QualityProfileRevision",
    "QualityRun",
    "RequirementMode",
    "RunCompletionSubject",
    "SupersessionEffect",
    "TechnicalObservation",
    "WaiverBinding",
    "require_ordered_collection",
    "validate_requirements",
]
