"""M8 ports and write authorities (spec §5, normative protocols)."""

from __future__ import annotations

from typing import Protocol

from r2.contracts.advanced_creative import (
    CandidateHead,
    ExplorationRevision,
    LearningObservation,
    LearningRecommendation,
    PromotionAuthorization,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
    RecommendationDecision,
)


class ExplorationRepository(Protocol):
    async def append_revision(
        self,
        *,
        user_id: str,
        project_name: str,
        candidate: ExplorationRevision,
        expected_head_version: int | None,
        command_id: str,
    ) -> CandidateHead: ...
    async def get_exact(
        self, *, user_id: str, project_name: str, candidate_id: str, revision: int
    ) -> ExplorationRevision | None: ...
    async def history(
        self, *, user_id: str, project_name: str, candidate_id: str, after_revision: int | None, limit: int
    ) -> tuple[ExplorationRevision, ...]: ...


class PromotionPreviewService(Protocol):
    async def create_preview(
        self,
        *,
        user_id: str,
        project_name: str,
        candidate_id: str,
        revision: int,
        target: PromotionTarget,
        command_id: str,
    ) -> PromotionPreview: ...


class ExplorationPromotionService(Protocol):
    async def promote(
        self,
        *,
        user_id: str,
        project_name: str,
        authorization: PromotionAuthorization,
        expected_candidate_head_version: int,
    ) -> PromotionReceipt: ...


class ObservationRepository(Protocol):
    async def ingest(
        self, *, user_id: str, project_name: str, observation: LearningObservation, command_id: str
    ) -> LearningObservation: ...


class RecommendationService(Protocol):
    async def propose(
        self, *, user_id: str, project_name: str, recommendation: LearningRecommendation, command_id: str
    ) -> LearningRecommendation: ...
    async def decide(
        self, *, user_id: str, project_name: str, decision: RecommendationDecision, command_id: str
    ) -> RecommendationDecision: ...


__all__ = [
    "ExplorationPromotionService",
    "ExplorationRepository",
    "ObservationRepository",
    "PromotionPreviewService",
    "RecommendationService",
]
