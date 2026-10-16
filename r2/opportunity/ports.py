"""Frozen source, custody and downstream authority seams (accepted M9 spec §2)."""

from __future__ import annotations

from typing import Protocol

from r2.contracts.opportunity import (
    AcquireSourceQuery,
    AcquisitionReceipt,
    BuildOpportunityCandidate,
    CandidateReceipt,
    CanvasSeedReceipt,
    CapabilityEvaluationRequest,
    CohortProfileReceipt,
    CustodianAuthorizationLease,
    DecideGreenlight,
    DeclareSourceQuery,
    EffectiveCapabilityEvaluation,
    ErasableEvidencePayload,
    FactualBridgeReceipt,
    FactualEvidenceInvalidation,
    FactualEvidenceReceipt,
    FactualEvidenceSubmission,
    FactualInvalidationReceipt,
    GreenlightDecisionView,
    GreenlightReceipt,
    GreenlightSubject,
    InvalidateSourceEvidence,
    InvalidationReceipt,
    InvalidationSubject,
    M8CanvasSeedReceipt,
    M8CanvasSeedRequest,
    M8LearningEvidenceBundle,
    M8LearningEvidenceRequest,
    OpportunityCandidateView,
    OpportunityCohortProfile,
    OpportunityIdentityRead,
    OpportunityReadPage,
    PayloadDeletionRequest,
    PayloadDeletionResult,
    PayloadRef,
    ProfilePublicationSubject,
    PublishOpportunityCohortProfile,
    QueryReceipt,
    SeedCanvasFromGreenlight,
    SnapshotReadPage,
    SourceCapabilityGrant,
    SourcePageRequest,
    SourcePageResult,
    SourceQuery,
    SourceSnapshotView,
    SubmitFactualEvidence,
)


class OpportunityIntelligence(Protocol):
    async def publish_cohort_profile(self, command: PublishOpportunityCohortProfile) -> CohortProfileReceipt: ...
    async def declare_query(self, command: DeclareSourceQuery) -> QueryReceipt: ...
    async def acquire(self, command: AcquireSourceQuery) -> AcquisitionReceipt: ...
    async def build_candidate(self, command: BuildOpportunityCandidate) -> CandidateReceipt: ...
    async def decide_greenlight(self, command: DecideGreenlight) -> GreenlightReceipt: ...
    async def seed_canvas(self, command: SeedCanvasFromGreenlight) -> CanvasSeedReceipt: ...
    async def submit_factual_evidence(self, command: SubmitFactualEvidence) -> FactualBridgeReceipt: ...
    async def invalidate_source(self, command: InvalidateSourceEvidence) -> InvalidationReceipt: ...


class OpportunityIntelligenceReader(Protocol):
    async def list_capabilities(self, request: OpportunityReadPage) -> tuple[SourceCapabilityGrant, ...]: ...
    async def list_cohort_profiles(self, request: OpportunityReadPage) -> tuple[OpportunityCohortProfile, ...]: ...
    async def get_cohort_profile(self, request: OpportunityIdentityRead) -> OpportunityCohortProfile: ...
    async def get_query(self, request: OpportunityIdentityRead) -> SourceQuery: ...
    async def list_snapshots(self, request: SnapshotReadPage) -> tuple[SourceSnapshotView, ...]: ...
    async def get_snapshot(self, request: OpportunityIdentityRead) -> SourceSnapshotView: ...
    async def list_candidates(self, request: OpportunityReadPage) -> tuple[OpportunityCandidateView, ...]: ...
    async def get_candidate(self, request: OpportunityIdentityRead) -> OpportunityCandidateView: ...
    async def get_greenlight(self, request: OpportunityIdentityRead) -> GreenlightDecisionView | None: ...


class MarketSourcePort(Protocol):
    async def fetch_page(self, request: SourcePageRequest) -> SourcePageResult: ...


class SourceCapabilityPort(Protocol):
    async def resolve_grant(self, ref: str) -> SourceCapabilityGrant: ...
    async def evaluate(self, request: CapabilityEvaluationRequest) -> EffectiveCapabilityEvaluation: ...


class GreenlightCustodianPort(Protocol):
    async def authorize_decision(self, command_id: str, subject: GreenlightSubject) -> CustodianAuthorizationLease: ...


class OpportunityProfileCustodianPort(Protocol):
    async def authorize_publication(
        self, command_id: str, subject: ProfilePublicationSubject
    ) -> CustodianAuthorizationLease: ...


class InvalidationCustodianPort(Protocol):
    async def authorize_invalidation(
        self, command_id: str, subject: InvalidationSubject
    ) -> CustodianAuthorizationLease: ...


class FactualAuthorityPort(Protocol):
    async def submit_evidence(self, submission: FactualEvidenceSubmission) -> FactualEvidenceReceipt: ...
    async def invalidate_evidence(self, request: FactualEvidenceInvalidation) -> FactualInvalidationReceipt: ...


class M8LearningReadPort(Protocol):
    async def read_evidence(self, request: M8LearningEvidenceRequest) -> M8LearningEvidenceBundle: ...


class M8CanvasSeedPort(Protocol):
    async def create_seed(self, request: M8CanvasSeedRequest) -> M8CanvasSeedReceipt: ...


class SnapshotEvidenceStore(Protocol):
    async def put_if_absent(self, payload: ErasableEvidencePayload) -> PayloadRef: ...
    async def verify_and_read(self, payload_ref: str, integrity_ref: str) -> bytes: ...
    async def delete_exact(self, request: PayloadDeletionRequest) -> PayloadDeletionResult: ...
