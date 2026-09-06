from pydantic import AwareDatetime, Field, model_validator

from .common import NonEmptyStr, R2ContractModel
from .enums import (
    CandidateSelectionStatus,
    GenerationLifecycleStatus,
    ReviewerType,
)


class GenerationCandidate(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    content_fingerprint: NonEmptyStr
    execution_fingerprint: NonEmptyStr
    provider_execution_ref: NonEmptyStr
    output_asset_ref: NonEmptyStr
    quality_report_ref: NonEmptyStr | None = None
    lifecycle_state: GenerationLifecycleStatus
    selection_state: CandidateSelectionStatus

    @model_validator(mode="after")
    def validate_state_combination(self):
        if (
            self.lifecycle_state is GenerationLifecycleStatus.FAILED
            and self.selection_state is CandidateSelectionStatus.SELECTED
        ):
            raise ValueError("FAILED candidate cannot be SELECTED")
        if (
            self.selection_state is CandidateSelectionStatus.SELECTED
            and self.lifecycle_state is not GenerationLifecycleStatus.GENERATED
        ):
            raise ValueError("SELECTED candidate must be GENERATED")
        return self


class ApprovedMaster(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    selected_candidate_id: NonEmptyStr
    approval_record: NonEmptyStr
    selected_at: AwareDatetime
    selected_by: NonEmptyStr


class QualityFinding(R2ContractModel):
    code: NonEmptyStr
    message: NonEmptyStr
    blocking: bool


class QualityReport(R2ContractModel):
    id: NonEmptyStr
    target_ref: NonEmptyStr
    checks: list[NonEmptyStr] = Field(default_factory=list)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    blocking_findings: list[QualityFinding] = Field(default_factory=list)
    advisory_findings: list[QualityFinding] = Field(default_factory=list)
    reviewer_type: ReviewerType
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_finding_planes(self):
        if any(not finding.blocking for finding in self.blocking_findings):
            raise ValueError("blocking_findings must contain only blocking findings")
        if any(finding.blocking for finding in self.advisory_findings):
            raise ValueError("advisory_findings must contain only advisory findings")
        return self
