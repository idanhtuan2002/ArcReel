"""M6 dual-profile adaptation contracts (spec section 4; plan Task 1).

Provider-neutral, immutable evidence/decision shapes for the adaptation authority
kernel: one shared branch/map/screenplay lineage per Canon parent, dual profile
evaluation sidecars (Western-generic, Chinese short-drama Shuangwen), and the
three typed decision families (map approval, profile waiver, screenplay
admission) an operator-authenticated ``AdaptationShowrunnerAuthorityPort`` (a
later task) authorizes. No field or contract name here is optional scope beyond
what the accepted design names; a later task adds ports, services and
persistence, not new shapes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, ConfigDict, Field

from .common import JSONValue, NonEmptyStr, R2ContractModel
from .content_basis import ContentBasis
from .enums import CreativeApprovalStatus

# --- enums ---------------------------------------------------------------------------


class AdaptationProfileId(StrEnum):
    WESTERN_GENERIC = "WESTERN_GENERIC"
    CN_SHORT_DRAMA_SHUANGWEN = "CN_SHORT_DRAMA_SHUANGWEN"


class AdaptationPolicy(StrEnum):
    STRICT = "STRICT"
    FAITHFUL = "FAITHFUL"
    FREE = "FREE"
    INSPIRED_BY = "INSPIRED_BY"


class AdaptationOperation(StrEnum):
    PRESERVE = "PRESERVE"
    EXTERNALIZE = "EXTERNALIZE"
    CONDENSE = "CONDENSE"
    COMBINE = "COMBINE"
    SPLIT = "SPLIT"
    OMIT = "OMIT"
    REORDER = "REORDER"
    REFRAME_POV = "REFRAME_POV"
    MODIFY_FOR_MEDIUM = "MODIFY_FOR_MEDIUM"


class FindingDisposition(StrEnum):
    INTEGRITY_BLOCK = "INTEGRITY_BLOCK"
    PROFILE_BLOCK = "PROFILE_BLOCK"
    ADVISORY = "ADVISORY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AdaptationAuthorityFamily(StrEnum):
    MAP_APPROVAL = "MAP_APPROVAL"
    PROFILE_WAIVER = "PROFILE_WAIVER"
    SCREENPLAY_ADMISSION = "SCREENPLAY_ADMISSION"


class AdaptationDecisionAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    WAIVE = "WAIVE"
    DENY_WAIVER = "DENY_WAIVER"
    ADMIT = "ADMIT"
    REVOKE = "REVOKE"


class ShuangwenType(StrEnum):
    """The six closed Shuangwen archetypes (spec section 4); no others exist."""

    HARD_TEAR = "硬撕"
    REFUSE_TO_SIGN = "拒签"
    EXPOSE_FAKE_ACCOUNT = "揭穿假账"
    FEIGN_WEAKNESS_TO_FISH = "示弱钓鱼"
    PUBLIC_BET = "当众对赌"
    BORROW_THIRD_PARTY_FORCE = "借力第三方"


# --- exact immutable refs -------------------------------------------------------------


class ArtifactVersionRef(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    artifact_id: NonEmptyStr
    version: int = Field(ge=1)
    content_hash: NonEmptyStr


class AdaptationProfileRef(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_id: AdaptationProfileId
    profile_version: NonEmptyStr
    policy_pack_digest: NonEmptyStr


class DecisionRef(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_id: NonEmptyStr
    decision_digest: NonEmptyStr


# --- branch / map / screenplay evidence -----------------------------------------------


class AdaptationBranchV2(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    branch_id: NonEmptyStr
    schema_version: Literal["r2-adaptation-branch-v2"]
    version: int = Field(ge=1)
    parent_branch_id: NonEmptyStr | None
    parent_canon_version: ArtifactVersionRef
    medium: NonEmptyStr
    adaptation_policy: AdaptationPolicy
    overlay_version: int = Field(ge=1)
    profile_ref: AdaptationProfileRef
    created_at: AwareDatetime
    created_by: NonEmptyStr


class AdaptationMapEntry(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entry_id: NonEmptyStr
    source_refs: list[NonEmptyStr] = Field(min_length=1)
    target_refs: list[NonEmptyStr] = Field(min_length=1)
    operation: AdaptationOperation
    rationale: NonEmptyStr
    fidelity_risk: NonEmptyStr
    approval_status: CreativeApprovalStatus


class AdaptationMapV2(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    adaptation_map_id: NonEmptyStr
    schema_version: Literal["r2-adaptation-map-v2"]
    version: int = Field(ge=1)
    adaptation_branch_ref: ArtifactVersionRef
    entries: list[AdaptationMapEntry] = Field(min_length=1)
    profile_analysis_refs: list[ArtifactVersionRef] = Field(default_factory=list)
    content_hash: NonEmptyStr


class ScreenplayScene(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    scene_id: NonEmptyStr
    purpose: NonEmptyStr
    duration_target: float = Field(gt=0)
    location_ref: NonEmptyStr | None
    character_refs: list[NonEmptyStr]
    source_mapping_refs: list[NonEmptyStr] = Field(min_length=1)
    dramatic_text: NonEmptyStr


class ScreenplayArtifactV2(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    screenplay_id: NonEmptyStr
    schema_version: Literal["r2-screenplay-artifact-v2"]
    version: int = Field(ge=1)
    adaptation_branch_ref: ArtifactVersionRef
    content_basis: ContentBasis
    scenes: list[ScreenplayScene] = Field(min_length=1)
    characters: list[NonEmptyStr] = Field(min_length=1)
    source_mapping_refs: list[NonEmptyStr] = Field(min_length=1)
    approval_status: CreativeApprovalStatus
    locked_for_direction: bool
    content_hash: NonEmptyStr
    adaptation_map_ref: ArtifactVersionRef
    profile_analysis_refs: list[ArtifactVersionRef] = Field(default_factory=list)


# --- profile findings, sidecars and evaluation reports ---------------------------------


class ProfileFinding(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    finding_id: NonEmptyStr
    rule_id: NonEmptyStr
    rule_version: NonEmptyStr
    disposition: FindingDisposition
    applicability: NonEmptyStr
    severity: NonEmptyStr
    target_path: NonEmptyStr
    source_span: NonEmptyStr
    evidence_refs: list[NonEmptyStr] = Field(default_factory=list)
    message_params: dict[str, JSONValue] = Field(default_factory=dict)


class WesternDramaAnalysis(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["r2-western-drama-analysis-v1"]
    content_hash: NonEmptyStr
    format_findings: list[ProfileFinding] = Field(default_factory=list)
    rubric_observations: list[NonEmptyStr] = Field(default_factory=list)
    evidence_locations: list[NonEmptyStr] = Field(default_factory=list)


class ShuangwenAnalysis(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["r2-shuangwen-analysis-v1"]
    content_hash: NonEmptyStr
    chapter_start: int = Field(ge=1)
    chapter_end: int = Field(ge=1)
    hen_evidence: NonEmptyStr | None
    shuang_evidence: NonEmptyStr | None
    ji_evidence: NonEmptyStr | None
    pan_evidence: NonEmptyStr | None
    shuang_type: ShuangwenType | None
    findings: list[ProfileFinding] = Field(default_factory=list)


class ProfileEvaluationReport(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["r2-profile-evaluation-report-v1"]
    artifact_hash: NonEmptyStr
    profile_ref: AdaptationProfileRef
    evaluator_version: NonEmptyStr
    sidecar_ref: ArtifactVersionRef
    sidecar_digest: NonEmptyStr
    findings: list[ProfileFinding] = Field(default_factory=list)
    report_digest: NonEmptyStr
    created_at: AwareDatetime


# --- commands --------------------------------------------------------------------------


class MapApprovalCommand(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    decision_id: NonEmptyStr
    branch_id: NonEmptyStr
    map_ref: ArtifactVersionRef
    profile_ref: AdaptationProfileRef
    relied_report_refs: list[DecisionRef]
    expected_predecessor_id: NonEmptyStr | None
    action: Literal[AdaptationDecisionAction.APPROVE, AdaptationDecisionAction.REJECT]


class ProfileWaiverCommand(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    decision_id: NonEmptyStr
    branch_id: NonEmptyStr
    artifact_ref: ArtifactVersionRef
    profile_ref: AdaptationProfileRef
    report_ref: DecisionRef
    finding_ids: list[NonEmptyStr] = Field(min_length=1)
    rule_versions: list[NonEmptyStr] = Field(min_length=1)
    rationale: NonEmptyStr
    expected_predecessor_id: NonEmptyStr | None
    action: Literal[AdaptationDecisionAction.WAIVE, AdaptationDecisionAction.DENY_WAIVER]


class ScreenplayAdmissionCommand(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    decision_id: NonEmptyStr
    branch_id: NonEmptyStr
    proposal_ref: ArtifactVersionRef
    admitted_screenplay: ScreenplayArtifactV2
    profile_ref: AdaptationProfileRef
    effective_map_approval_ref: DecisionRef
    report_refs: list[DecisionRef] = Field(min_length=1)
    waiver_refs: list[DecisionRef] = Field(default_factory=list)
    expected_predecessor_id: NonEmptyStr | None
    action: Literal[AdaptationDecisionAction.ADMIT, AdaptationDecisionAction.REVOKE]


# --- authorization and stored decisions -------------------------------------------------


class AdaptationDecisionAuthorization(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    authenticated_principal: NonEmptyStr
    authority_role: Literal["HUMAN_SHOWRUNNER"]
    action: AdaptationDecisionAction
    command_identity_hash: NonEmptyStr
    approval_receipt: NonEmptyStr
    authorized_at: AwareDatetime


class MapApprovalDecision(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_kind: Literal["MAP_APPROVAL"] = "MAP_APPROVAL"
    command: MapApprovalCommand
    authorization: AdaptationDecisionAuthorization
    sequence: int = Field(ge=1)
    decision_digest: NonEmptyStr
    created_at: AwareDatetime


class ProfileWaiverDecision(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_kind: Literal["PROFILE_WAIVER"] = "PROFILE_WAIVER"
    command: ProfileWaiverCommand
    authorization: AdaptationDecisionAuthorization
    sequence: int = Field(ge=1)
    decision_digest: NonEmptyStr
    created_at: AwareDatetime


class ScreenplayAdmissionDecision(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_kind: Literal["SCREENPLAY_ADMISSION"] = "SCREENPLAY_ADMISSION"
    command: ScreenplayAdmissionCommand
    authorization: AdaptationDecisionAuthorization
    sequence: int = Field(ge=1)
    decision_digest: NonEmptyStr
    created_at: AwareDatetime


AdaptationDecision = Annotated[
    MapApprovalDecision | ProfileWaiverDecision | ScreenplayAdmissionDecision,
    Field(discriminator="decision_kind"),
]


# --- heads and receipts ------------------------------------------------------------------


class AdaptationHead(R2ContractModel):
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    family: AdaptationAuthorityFamily
    head_key: NonEmptyStr
    latest_decision_id: NonEmptyStr
    effective_decision_id: NonEmptyStr | None
    selected_artifact_ref: ArtifactVersionRef | None
    generation: int = Field(ge=1)


class AdaptationDecisionReceipt(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    decision_ref: DecisionRef
    family: AdaptationAuthorityFamily
    head_key: NonEmptyStr
    outcome: Literal["RECORDED", "EXACT_RETRY"]
    current_at_return: bool


class AdmittedScreenplayRef(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    screenplay_ref: ArtifactVersionRef
    admission_ref: DecisionRef
    profile_ref: AdaptationProfileRef


__all__ = [
    "AdaptationAuthorityFamily",
    "AdaptationBranchV2",
    "AdaptationDecision",
    "AdaptationDecisionAction",
    "AdaptationDecisionAuthorization",
    "AdaptationDecisionReceipt",
    "AdaptationHead",
    "AdaptationMapEntry",
    "AdaptationMapV2",
    "AdaptationOperation",
    "AdaptationPolicy",
    "AdaptationProfileId",
    "AdaptationProfileRef",
    "AdmittedScreenplayRef",
    "ArtifactVersionRef",
    "DecisionRef",
    "FindingDisposition",
    "MapApprovalCommand",
    "MapApprovalDecision",
    "ProfileEvaluationReport",
    "ProfileFinding",
    "ProfileWaiverCommand",
    "ProfileWaiverDecision",
    "ScreenplayAdmissionCommand",
    "ScreenplayAdmissionDecision",
    "ScreenplayArtifactV2",
    "ScreenplayScene",
    "ShuangwenAnalysis",
    "ShuangwenType",
    "WesternDramaAnalysis",
]
