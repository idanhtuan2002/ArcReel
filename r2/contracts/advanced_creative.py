"""M8 advanced-creative public contracts (spec 2026-09-13 §4, normative shapes).

Frozen, extra-field-forbid Pydantic v2 models. Canonical JSON values are recursively immutable
and key-sorted, so hashing never depends on caller-owned mutable mappings.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from math import isfinite
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    FiniteFloat,
    RootModel,
    SerializationInfo,
    StringConstraints,
    model_serializer,
    model_validator,
)

from r2.contracts.common import R2ContractModel


class ExplorationKind(StrEnum):
    CANVAS = "CANVAS"
    SPATIAL = "SPATIAL"
    FORMAT = "FORMAT"


class EvidenceClass(StrEnum):
    VISIBLE = "VISIBLE"
    INFERRED = "INFERRED"
    GAP = "GAP"


class ExperimentDesign(StrEnum):
    CONCURRENT_RANDOMIZED = "CONCURRENT_RANDOMIZED"
    PLATFORM_MANAGED = "PLATFORM_MANAGED"
    SEQUENTIAL_OBSERVATIONAL = "SEQUENTIAL_OBSERVATIONAL"
    OFFLINE_REPLAY = "OFFLINE_REPLAY"


class RecommendationDisposition(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"
    REQUEST_EXPERIMENT = "REQUEST_EXPERIMENT"


class ParityDisposition(StrEnum):
    PARITY = "PARITY"
    IMPROVED = "IMPROVED"
    EXCLUDED = "EXCLUDED"
    UNVERIFIED = "UNVERIFIED"


class ParityVerdict(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


class PromotionTargetKind(StrEnum):
    ARTIFACT_SLOT = "ARTIFACT_SLOT"
    PRODUCTION_BINDING = "PRODUCTION_BINDING"


Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]

# A custom Pydantic RootModel whose root is a recursively immutable, key-sorted
# tuple representation. Its validator accepts JSON mappings, rejects non-string
# keys/non-finite numbers, maps arrays to tuples and maps objects to sorted tuples.
type CanonicalJsonScalar = str | int | Decimal | bool | None
type CanonicalJsonValue = CanonicalJsonScalar | tuple[CanonicalJsonValue, ...] | CanonicalJsonObject


def _freeze_json_value(value: object) -> CanonicalJsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical JSON numbers must be finite")
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("canonical JSON numbers must be finite")
        return Decimal(str(value))
    if isinstance(value, Mapping):
        return CanonicalJsonObject.model_validate(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise ValueError("value is outside the canonical JSON domain")


class CanonicalJsonObject(RootModel[tuple[tuple[str, CanonicalJsonValue], ...]]):
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def freeze_object(cls, value: object) -> object:
        if isinstance(value, cls):
            return value.root
        if not isinstance(value, Mapping):
            raise ValueError("canonical JSON object root must be a mapping")
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical JSON object keys must be strings")
        return tuple((key, _freeze_json_value(item)) for key, item in sorted(value.items()))

    @model_serializer(mode="plain")
    def as_mapping(self, info: SerializationInfo) -> dict[str, object]:
        """Dump as a JSON object, so a dumped value validates back to an equal value."""
        return {key: _thaw_json_value(item, json_mode=info.mode_is_json()) for key, item in self.root}


def _thaw_json_value(value: CanonicalJsonValue, *, json_mode: bool) -> object:
    if isinstance(value, CanonicalJsonObject):
        return {key: _thaw_json_value(item, json_mode=json_mode) for key, item in value.root}
    if isinstance(value, tuple):
        return [_thaw_json_value(item, json_mode=json_mode) for item in value]
    if isinstance(value, Decimal) and json_mode:
        if value == value.to_integral_value():
            return int(value)
        as_float = float(value)
        if Decimal(str(as_float)) != value:
            raise ValueError(f"canonical JSON number {value} has no exact JSON representation")
        return as_float
    return value


class M8ContractModel(R2ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        frozen=True,
        use_enum_values=False,
    )


class LineageBinding(M8ContractModel):
    project_name: str
    content_basis_digest: Sha256Digest
    approved_master_id: str | None
    approved_master_digest: Sha256Digest | None
    creative_profile_id: str
    creative_profile_version: str
    policy_digest: Sha256Digest


class CanvasNode(M8ContractModel):
    node_id: str
    node_type: str
    body: CanonicalJsonObject


class CanvasEdge(M8ContractModel):
    edge_id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    body: CanonicalJsonObject


class CanvasCandidate(M8ContractModel):
    kind: Literal[ExplorationKind.CANVAS]
    graph_schema_version: str
    nodes: tuple[CanvasNode, ...]
    edges: tuple[CanvasEdge, ...]
    groups: tuple[CanonicalJsonObject, ...]
    storyboard_order: tuple[str, ...]
    viewport_bookmarks: tuple[CanonicalJsonObject, ...]


class ExplorationRevision(M8ContractModel):
    candidate_id: str
    revision: int = Field(ge=1)
    kind: ExplorationKind
    parent_revision: int | None
    payload: CandidatePayload
    payload_digest: Sha256Digest
    lineage: LineageBinding
    created_by: str
    created_at: AwareDatetime

    @model_validator(mode="after")
    def require_matching_payload_kind(self) -> Self:
        if self.kind != self.payload.kind:
            raise ValueError("revision kind must equal payload kind")
        return self


class CandidateHead(M8ContractModel):
    candidate_id: str
    current_revision: int = Field(ge=1)
    head_version: int = Field(ge=1)


class PromotionTarget(M8ContractModel):
    kind: PromotionTargetKind
    target_ref: str
    expected_target_version: int = Field(ge=0)


class PromotionPreview(M8ContractModel):
    preview_id: str
    preview_command_id: str
    project_name: str
    candidate_id: str
    candidate_revision: int
    candidate_payload_digest: Sha256Digest
    target: PromotionTarget
    expected_master_id: str | None
    expected_master_digest: Sha256Digest | None
    impact: CanonicalJsonObject
    impact_digest: Sha256Digest
    authorization_scope: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def require_bounded_target_binding(self) -> Self:
        ttl_seconds = (self.expires_at - self.issued_at).total_seconds()
        if not 0 < ttl_seconds <= 3600:
            raise ValueError("preview TTL must be in (0, 3600] seconds")
        has_master = self.expected_master_id is not None and self.expected_master_digest is not None
        no_master = self.expected_master_id is None and self.expected_master_digest is None
        # M8-E amendment: only a format slot's first promotion binds "no master yet" at version 0.
        format_genesis = (
            self.target.target_ref.startswith("m8-format:") and self.target.expected_target_version == 0 and no_master
        )
        if self.target.kind is PromotionTargetKind.ARTIFACT_SLOT and not (has_master or format_genesis):
            raise ValueError("artifact preview requires exact master identity")
        if self.target.kind is PromotionTargetKind.PRODUCTION_BINDING and (
            self.expected_master_id is not None or self.expected_master_digest is not None
        ):
            raise ValueError("binding preview cannot bind a master identity")
        return self


class PromotionAuthorization(M8ContractModel):
    command_id: str
    project_name: str
    preview_id: str
    preview_digest: Sha256Digest
    actor_id: str
    actor_scope: str
    decision: Literal["APPROVE"]
    authorized_at: AwareDatetime


class PromotionReceipt(M8ContractModel):
    receipt_id: str
    command_id: str
    project_name: str
    preview_digest: Sha256Digest
    candidate_id: str
    candidate_revision: int
    target: PromotionTarget
    result_artifact_ref: str
    result_master_id: str | None
    result_digest: Sha256Digest
    promoted_at: AwareDatetime

    @model_validator(mode="after")
    def require_target_specific_result(self) -> Self:
        has_master = self.result_master_id is not None
        expects_master = self.target.kind is PromotionTargetKind.ARTIFACT_SLOT
        if has_master != expects_master:
            raise ValueError("receipt master identity does not match target kind")
        return self


class SpatialImageSpan(M8ContractModel):
    source_ref: str = Field(min_length=1)
    source_digest: Sha256Digest
    view: Literal["MASTER", "REVERSE"]
    x0: FiniteFloat = Field(ge=0, le=1)
    y0: FiniteFloat = Field(ge=0, le=1)
    x1: FiniteFloat = Field(ge=0, le=1)
    y1: FiniteFloat = Field(ge=0, le=1)

    @model_validator(mode="after")
    def require_positive_area(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("spatial source span must have positive area")
        return self


class SpatialAssertion(M8ContractModel):
    assertion_id: str
    evidence_class: EvidenceClass
    source_refs: tuple[str, ...]
    source_spans: tuple[SpatialImageSpan, ...] = Field(default=(), exclude_if=lambda value: not value)
    evidence_detail: CanonicalJsonObject | None = Field(default=None, exclude_if=lambda value: value is None)
    relation: str
    subject_refs: tuple[str, ...]
    confidence: float | None
    warnings: tuple[str, ...]

    @model_validator(mode="after")
    def require_span_source(self) -> Self:
        if any(span.source_ref not in self.source_refs for span in self.source_spans):
            raise ValueError("spatial source spans must name assertion sources")
        identities: dict[str, tuple[str, str]] = {}
        for span in self.source_spans:
            identity = (span.source_digest, span.view)
            previous = identities.setdefault(span.source_ref, identity)
            if previous != identity:
                raise ValueError("spatial source ref must have one identity")
        if len({(span.source_ref, span.x0, span.y0, span.x1, span.y1) for span in self.source_spans}) != len(
            self.source_spans
        ):
            raise ValueError("spatial source spans must be unique")
        return self


class SpatialPayload(M8ContractModel):
    assertions: tuple[SpatialAssertion, ...]
    seam_locks: tuple[CanonicalJsonObject, ...]
    direction_locks: tuple[CanonicalJsonObject, ...]
    duplicate_warnings: tuple[CanonicalJsonObject, ...]
    execution_id: str | None
    normalizer_version: str

    @model_validator(mode="after")
    def require_unique_assertion_ids(self) -> Self:
        ids = [assertion.assertion_id for assertion in self.assertions]
        if len(ids) != len(set(ids)):
            raise ValueError("spatial payload requires unique assertion ids")
        return self


class SpatialCandidate(M8ContractModel):
    kind: Literal[ExplorationKind.SPATIAL]
    spatial: SpatialPayload


class MetricWindow(M8ContractModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    timezone_name: str
    aggregation: str


class LearningObservation(M8ContractModel):
    observation_id: str
    source_family: str
    source_record_id: str
    metric_name: str
    metric_definition_version: str
    metric_value: Decimal | None
    metric_unit: str
    window: MetricWindow
    platform_artifact_id: str | None
    format_profile_ref: str | None
    lineage: LineageBinding
    experiment_design: ExperimentDesign | None
    exposure_ref: str | None
    raw_payload_digest: Sha256Digest
    transformation_version: str | None
    correction_of: str | None
    missing_reason: str | None
    observed_at: AwareDatetime
    ingested_at: AwareDatetime


class LearningRecommendation(M8ContractModel):
    recommendation_id: str
    evidence_observation_ids: tuple[str, ...]
    hypothesis: str
    applicability: CanonicalJsonObject
    exclusions: tuple[str, ...]
    confidence: float
    expected_guardrails: tuple[str, ...]
    lineage: LineageBinding
    expires_at: AwareDatetime


class RecommendationDecision(M8ContractModel):
    decision_id: str
    recommendation_id: str
    disposition: RecommendationDisposition
    expected_recommendation_digest: Sha256Digest
    actor_id: str
    reason: str
    governed_proposal_ref: str | None
    decided_at: AwareDatetime


class OutputProfile(M8ContractModel):
    profile_ref: str
    platform: str
    surface: str
    width: int
    height: int
    fps: Fraction
    duration_limit_seconds: Decimal | None
    container: str
    video_codec: str
    audio_codec: str | None
    source_refs: tuple[str, ...]
    effective_at: AwareDatetime


class OverlayConstraintSet(M8ContractModel):
    constraint_ref: str
    platform: str
    surface: str
    locale: str
    ui_variant: str
    regions: tuple[CanonicalJsonObject, ...]
    source_refs: tuple[str, ...]
    effective_at: AwareDatetime


class ReframeDecision(M8ContractModel):
    decision_id: str
    kind: str
    source_span: CanonicalJsonObject
    target_span: CanonicalJsonObject
    rationale: str
    semantic_risk: str


class FormatProjectionPlan(M8ContractModel):
    plan_id: str
    source_master_id: str
    source_master_digest: Sha256Digest
    output_profile: OutputProfile
    overlay_constraints: OverlayConstraintSet
    reframe_decisions: tuple[ReframeDecision, ...]
    plan_digest: Sha256Digest


class TechnicalValidationReport(M8ContractModel):
    report_id: str
    plan_digest: Sha256Digest
    artifact_digest: Sha256Digest
    checks: tuple[CanonicalJsonObject, ...]
    passed: bool


class SemanticParityReport(M8ContractModel):
    report_id: str
    plan_digest: Sha256Digest
    source_master_digest: Sha256Digest
    artifact_digest: Sha256Digest
    rubric_version: str
    reviews: tuple[CanonicalJsonObject, ...]
    material_disagreement: bool
    passed: bool


class FormatCandidate(M8ContractModel):
    kind: Literal[ExplorationKind.FORMAT]
    plan_digest: Sha256Digest
    rendered_artifact_ref: str
    rendered_artifact_digest: Sha256Digest
    technical_report_id: str
    technical_report_digest: Sha256Digest
    semantic_report_id: str
    semantic_report_digest: Sha256Digest
    execution_id: str


CandidatePayload = Annotated[
    CanvasCandidate | SpatialCandidate | FormatCandidate,
    Field(discriminator="kind"),
]

ExplorationRevision.model_rebuild()


class DonorSurfaceRef(M8ContractModel):
    repository_url: str
    commit_sha: str
    selected_paths: tuple[str, ...]
    reachable_surface_digest: Sha256Digest
    runtime_identity: str
    behavior_inventory_digest: Sha256Digest
    donor_test_inventory_digest: Sha256Digest
    fixture_set_digest: Sha256Digest


class BehaviorParityRow(M8ContractModel):
    behavior_id: str
    donor_test_refs: tuple[str, ...]
    fixture_refs: tuple[str, ...]
    intentional_difference: str | None
    functionality: ParityDisposition
    correctness: ParityDisposition
    determinism: ParityDisposition
    failure_safety: ParityDisposition
    data_integrity: ParityDisposition
    observability: ParityDisposition
    performance: ParityDisposition
    resources: ParityDisposition
    evidence_refs: tuple[str, ...]


class DonorParityReport(M8ContractModel):
    contract_version: Literal["1"]
    donor: DonorSurfaceRef
    integrated_head: str
    rows: tuple[BehaviorParityRow, ...]
    commands: tuple[CanonicalJsonObject, ...]
    required_skips: tuple[str, ...]
    material_unknowns: tuple[str, ...]
    reviewer: str
    verdict: ParityVerdict
