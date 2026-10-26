"""Pure M10 port data and interfaces; no descriptor grants runtime authority."""

from __future__ import annotations

from typing import Protocol, Self

from pydantic import AwareDatetime, StrictBool, model_validator

from r2.contracts.advanced_creative import Sha256Digest
from r2.contracts.quality import (
    AssessedSubject,
    AssessorClass,
    AssessorKind,
    CompleteRunCommand,
    DispositionAuthorizationLease,
    DispositionAuthorizationRequest,
    ExactIdentity,
    M10ContractModel,
    M10Uuid7,
    ProbeRule,
    ProfilePublicationAuthorizationLease,
    ProfilePublicationAuthorizationRequest,
    QualityProfileRevision,
    QualityRun,
    TechnicalObservation,
)
from r2.quality.digests import compute_digest


class ProbeRequest(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    execution_ref: ExactIdentity
    requirement_id: ExactIdentity
    slot_id: ExactIdentity
    subject: AssessedSubject
    profile: QualityProfileRevision
    rule: ProbeRule

    @model_validator(mode="after")
    def coherent(self) -> Self:
        scope = (self.user_id, self.project_name)
        binding = self.subject.master_binding
        if scope != (self.profile.user_id, self.profile.project_name) or scope != (
            binding.user_id,
            binding.project_name,
        ):
            raise ValueError("probe request scope invalid")
        if self.rule not in self.profile.policy.probe_rules:
            raise ValueError("probe request rule invalid")
        slot = next(
            (
                slot
                for requirement in self.profile.policy.assessment_requirements
                if requirement.requirement_id == self.requirement_id
                for slot in requirement.slots
                if slot.slot_id == self.slot_id
            ),
            None,
        )
        if (
            slot is None
            or slot.kind != AssessorKind.TECHNICAL
            or slot.assessor_class != AssessorClass.DETERMINISTIC
            or self.rule.rule_id not in slot.rule_ids
        ):
            raise ValueError("probe request placement invalid")
        return self


ProbeReceipt = TechnicalObservation


class FactualReadRequest(M10ContractModel):
    user_id: ExactIdentity
    project_name: ExactIdentity
    actor_id: ExactIdentity
    subject_digest: Sha256Digest
    claim_ledger_projection_ref: ExactIdentity
    research_pack_ref: ExactIdentity


class FactualReadProjection(M10ContractModel):
    """Raw authority data; A5 owns placement and actual receipt/currentness verification."""

    user_id: ExactIdentity
    project_name: ExactIdentity
    subject_digest: Sha256Digest
    claim_ledger_projection_ref: ExactIdentity
    claim_ledger_projection_digest: Sha256Digest
    research_pack_ref: ExactIdentity
    research_pack_digest: Sha256Digest
    correction_head_digest: Sha256Digest
    coverage_digest: Sha256Digest
    withdrawn: StrictBool
    checked_at: AwareDatetime
    validity_receipt_ref: ExactIdentity
    validity_receipt_digest: Sha256Digest


class EvidenceReference(M10ContractModel):
    """Metadata handle only; this does not resolve bytes or prove their existence."""

    user_id: ExactIdentity
    project_name: ExactIdentity
    ref: ExactIdentity
    digest: Sha256Digest


def validate_probe_result_binding(request: ProbeRequest, observation: TechnicalObservation) -> TechnicalObservation:
    """Check data binding; A4 must additionally verify real M7 custody and receipt."""
    try:
        request = ProbeRequest.model_validate(request)
        result = TechnicalObservation.model_validate(observation)
        if (result.requirement_id, result.slot_id, result.rule_id, result.config_digest, result.subject_digest) != (
            request.requirement_id,
            request.slot_id,
            request.rule.rule_id,
            request.rule.config_digest,
            compute_digest("m10.assessed-subject.v1", request.subject),
        ):
            raise ValueError("mismatch")
        return result
    except (ValueError, TypeError):
        raise ValueError("probe result binding invalid") from None


def validate_factual_result_binding(
    request: FactualReadRequest, projection: FactualReadProjection
) -> FactualReadProjection:
    """Match requested authority data; no foreign receipt or currentness is inferred."""
    try:
        request = FactualReadRequest.model_validate(request)
        result = FactualReadProjection.model_validate(projection)
        if (
            result.user_id,
            result.project_name,
            result.subject_digest,
            result.claim_ledger_projection_ref,
            result.research_pack_ref,
        ) != (
            request.user_id,
            request.project_name,
            request.subject_digest,
            request.claim_ledger_projection_ref,
            request.research_pack_ref,
        ):
            raise ValueError("mismatch")
        return result
    except (ValueError, TypeError):
        raise ValueError("factual result binding invalid") from None


class QualityProfileReadPort(Protocol):
    async def get_revision(
        self, *, user_id: ExactIdentity, project_name: ExactIdentity, profile_id: M10Uuid7, revision: int
    ) -> QualityProfileRevision | None: ...


class QualityProfilePublicationService(Protocol):
    async def publish(self, request: ProfilePublicationAuthorizationRequest) -> QualityProfileRevision: ...


class QualityProbePort(Protocol):
    async def observe(self, request: ProbeRequest) -> ProbeReceipt: ...


class QualityRunService(Protocol):
    async def complete(self, command: CompleteRunCommand) -> QualityRun: ...


class ProfilePublicationCustodianPort(Protocol):
    async def authorize_publication(
        self, request: ProfilePublicationAuthorizationRequest
    ) -> ProfilePublicationAuthorizationLease: ...


class QualityDispositionCustodianPort(Protocol):
    async def authorize_disposition(
        self, request: DispositionAuthorizationRequest
    ) -> DispositionAuthorizationLease: ...


class FactualReadPort(Protocol):
    async def read_current(self, request: FactualReadRequest) -> FactualReadProjection | None: ...


class EvidenceReferencePort(Protocol):
    async def get_exact(
        self, *, user_id: ExactIdentity, project_name: ExactIdentity, ref: ExactIdentity, expected_digest: Sha256Digest
    ) -> EvidenceReference | None: ...
