"""M8-D learning API: observations, rule evaluation, recommendations and Human decisions (plan D3).

The user comes from the session and the project from the path. A decision needs an interactive
session (an API key is refused): only a person disposes of a recommendation. A foreign or unknown
recommendation reads as not found.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from lib.api_errors import ApiError, ConflictError, NotFoundError, UnprocessableError
from lib.db import async_session_factory
from lib.db.repositories.learning_recommendations import StoredRecommendation
from lib.project_manager import get_project_manager
from r2.advanced_creative.errors import M8Error, ObservationNotFoundError, RecommendationNotFoundError
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    LearningObservation,
    LearningRecommendation,
    M8ContractModel,
    RecommendationDecision,
    RecommendationDisposition,
)
from r2.learning.cohorts import CohortLeakError, RuleParams
from server.auth import CurrentUser, InteractiveUser
from server.services import learning as service

router = APIRouter()

LEARNING_REQUEST_INVALID = "m8_learning_request_invalid"
PROFILE_COHORT_LEAK = "m8_profile_cohort_leak"


def _api_error(error: Exception) -> ApiError:
    if isinstance(error, (ObservationNotFoundError, RecommendationNotFoundError)):
        return NotFoundError(error.code)
    if isinstance(error, M8Error):
        return ConflictError(error.code)
    if isinstance(error, CohortLeakError):
        return UnprocessableError(PROFILE_COHORT_LEAK)
    return UnprocessableError(LEARNING_REQUEST_INVALID)


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except (M8Error, ValueError) as error:
        # ValueError covers observation, cohort and causal-language admission failures.
        raise _api_error(error) from error


class IngestObservationRequest(M8ContractModel):
    episode: int = Field(ge=1)
    observation: LearningObservation
    raw_payload: CanonicalJsonObject | None = None
    command_id: str = Field(min_length=1, max_length=255)


class EvaluateRequest(M8ContractModel):
    source_family: str = Field(min_length=1, max_length=255)
    metric_name: str = Field(min_length=1, max_length=255)
    metric_definition_version: str = Field(min_length=1, max_length=255)
    aggregation: str = Field(min_length=1, max_length=64)
    creative_profile_id: str = Field(min_length=1, max_length=255)
    creative_profile_version: str = Field(min_length=1, max_length=255)
    arm_a: str = Field(min_length=1, max_length=255)
    arm_b: str = Field(min_length=1, max_length=255)
    min_per_arm: int = Field(ge=2, le=100_000)
    min_relative_lift: Decimal = Field(gt=0, le=100)
    expires_in_days: int = Field(ge=1, le=365)
    command_id: str = Field(min_length=1, max_length=255)


class ArmSummary(M8ContractModel):
    arm: str | None
    n: int
    present: int
    missing: dict[str, int]
    mean: str | None
    median: str | None
    min: str | None
    max: str | None
    observation_ids: tuple[str, ...]


class RecommendationView(M8ContractModel):
    recommendation: LearningRecommendation
    recommendation_digest: str
    language: Literal["causal", "associative"]
    rule: str
    evidence_cutoff: datetime
    created_at: datetime
    decisions: tuple[RecommendationDecision, ...]
    final: bool


class EvaluateResponse(M8ContractModel):
    fired: bool
    reason: str
    relative_lift: str | None
    evidence_cutoff: datetime | None
    arms: tuple[ArmSummary, ...]
    recommendation: RecommendationView | None


class DecideRequest(M8ContractModel):
    disposition: RecommendationDisposition
    expected_recommendation_digest: str = Field(min_length=1, max_length=71)
    reason: str = Field(min_length=1, max_length=2000)
    command_id: str = Field(min_length=1, max_length=255)


def _view(stored: StoredRecommendation) -> RecommendationView:
    terminal = {RecommendationDisposition.ACCEPT, RecommendationDisposition.REJECT}
    return RecommendationView(
        recommendation=stored.recommendation,
        recommendation_digest=stored.recommendation_digest,
        language="causal"
        if stored.recommendation.applicability.model_dump().get("language") == "causal"
        else "associative",
        rule=stored.rule,
        evidence_cutoff=stored.evidence_cutoff,
        created_at=stored.created_at,
        decisions=stored.decisions,
        final=any(item.disposition in terminal for item in stored.decisions),
    )


@router.post("/projects/{project_name}/m8/learning/observations")
async def ingest_observation(
    project_name: str, req: IngestObservationRequest, user: CurrentUser
) -> LearningObservation:
    async def operation() -> LearningObservation:
        async with async_session_factory() as session:
            return await service.ingest_observation(
                session,
                get_project_manager(),
                user_id=user.id,
                project_name=project_name,
                episode=req.episode,
                observation=req.observation,
                raw_payload=None if req.raw_payload is None else req.raw_payload.model_dump(mode="python"),
                command_id=req.command_id,
            )

    return await _run(operation)


@router.post("/projects/{project_name}/m8/learning/recommendations/evaluate")
async def evaluate(project_name: str, req: EvaluateRequest, user: CurrentUser) -> EvaluateResponse:
    async def operation() -> EvaluateResponse:
        selection = service.CohortSelection(
            source_family=req.source_family,
            metric_name=req.metric_name,
            metric_definition_version=req.metric_definition_version,
            aggregation=req.aggregation,
            creative_profile_id=req.creative_profile_id,
            creative_profile_version=req.creative_profile_version,
        )
        params = RuleParams(
            arm_a=req.arm_a, arm_b=req.arm_b, min_per_arm=req.min_per_arm, min_relative_lift=req.min_relative_lift
        )
        async with async_session_factory() as session:
            result = await service.evaluate(
                session,
                user_id=user.id,
                project_name=project_name,
                selection=selection,
                params=params,
                expires_in=timedelta(days=req.expires_in_days),
                command_id=req.command_id,
            )
        return EvaluateResponse(
            fired=result.fired,
            reason=result.reason,
            relative_lift=result.relative_lift,
            evidence_cutoff=result.evidence_cutoff,
            arms=tuple(ArmSummary.model_validate(item) for item in result.arms),
            recommendation=None if result.recommendation is None else _view(result.recommendation),
        )

    return await _run(operation)


@router.get("/projects/{project_name}/m8/learning/recommendations")
async def list_recommendations(project_name: str, user: CurrentUser) -> list[RecommendationView]:
    async def operation() -> list[RecommendationView]:
        async with async_session_factory() as session:
            stored = await service.list_recommendations(session, user_id=user.id, project_name=project_name)
        return [_view(item) for item in stored]

    return await _run(operation)


@router.post("/projects/{project_name}/m8/learning/recommendations/{recommendation_id}/decisions")
async def decide(
    project_name: str, recommendation_id: str, req: DecideRequest, user: InteractiveUser
) -> RecommendationDecision:
    async def operation() -> RecommendationDecision:
        async with async_session_factory() as session:
            return await service.decide(
                session,
                user_id=user.id,
                project_name=project_name,
                recommendation_id=recommendation_id,
                disposition=req.disposition,
                expected_recommendation_digest=req.expected_recommendation_digest,
                actor_id=user.sub,
                reason=req.reason,
                command_id=req.command_id,
            )

    return await _run(operation)
