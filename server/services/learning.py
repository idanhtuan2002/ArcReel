"""M8-D learning service: observation ingest, rule evaluation and Human decisions (plan D3).

The service owns each transaction. Observation lineage must be the server-resolved episode lineage
(ADR-0098), so a client cannot place evidence in another profile's cohort. Evaluation runs
``compare_cohorts@1`` over the scope's current observations at the watermark and proposes only when
the rule fires. Nothing here writes outside the learning tables: an accepted recommendation yields a
governed proposal reference and nothing else.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.learning import LearningObservationRepository
from lib.db.repositories.learning_recommendations import LearningRecommendationRepository, StoredRecommendation
from lib.project_manager import ProjectManager
from r2.advanced_creative.digests import digest_command
from r2.contracts.advanced_creative import (
    LearningObservation,
    RecommendationDecision,
    RecommendationDisposition,
)
from r2.learning.cohorts import CohortSummary, RuleParams, compare_cohorts, recommendation_from
from r2.learning.observations import ObservationInvalidError
from server.services.advanced_creative import episode_lineage


@dataclass(frozen=True)
class CohortSelection:
    source_family: str
    metric_name: str
    metric_definition_version: str
    aggregation: str
    creative_profile_id: str
    creative_profile_version: str


@dataclass(frozen=True)
class Evaluation:
    fired: bool
    reason: str
    relative_lift: Decimal | None
    causal: bool
    evidence_cutoff: datetime | None
    arms: tuple[CohortSummary, ...]
    recommendation: StoredRecommendation | None


async def ingest_observation(
    session: AsyncSession,
    projects: ProjectManager,
    *,
    user_id: str,
    project_name: str,
    episode: int,
    observation: LearningObservation,
    raw_payload: Mapping[str, object] | None,
    command_id: str,
) -> LearningObservation:
    lineage = await episode_lineage(projects, project_name, episode)
    if observation.lineage != lineage:
        raise ObservationInvalidError("observation lineage must be the server-resolved episode lineage")
    stored = await LearningObservationRepository(session).ingest(
        user_id=user_id,
        project_name=project_name,
        observation=observation,
        command_id=command_id,
        raw_payload=raw_payload,
    )
    await session.commit()
    return stored


def _in_cohort(item: LearningObservation, selection: CohortSelection, arms: tuple[str, str]) -> bool:
    return (
        item.source_family == selection.source_family
        and item.metric_name == selection.metric_name
        and item.metric_definition_version == selection.metric_definition_version
        and item.window.aggregation == selection.aggregation
        and item.lineage.creative_profile_id == selection.creative_profile_id
        and item.lineage.creative_profile_version == selection.creative_profile_version
        and item.format_profile_ref in arms
    )


async def evaluate(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    selection: CohortSelection,
    params: RuleParams,
    expires_in: timedelta,
    command_id: str,
    now: datetime | None = None,
) -> Evaluation:
    """Run the rule at the scope watermark; a fired rule proposes one recommendation."""
    if not timedelta(0) < expires_in <= timedelta(days=365):
        raise ValueError("expiry must be within a year")
    repository = LearningRecommendationRepository(session)
    await LearningObservationRepository(session).lock_scope(user_id=user_id, project_name=project_name)
    replayed = await repository.by_command(user_id=user_id, project_name=project_name, command_id=command_id)
    if replayed is not None:
        # The command already proposed; its stored result is the answer, whatever is current now.
        return Evaluation(True, "replayed", None, False, replayed.evidence_cutoff, (), replayed)
    observations = LearningObservationRepository(session)
    cutoff = await observations.watermark(user_id=user_id, project_name=project_name)
    if cutoff is None:
        return Evaluation(False, "no observations", None, False, None, (), None)
    current = await observations.list_as_of(user_id=user_id, project_name=project_name, cutoff=cutoff)
    selected = [item for item in current if _in_cohort(item, selection, (params.arm_a, params.arm_b))]
    if not {item.format_profile_ref for item in selected} >= {params.arm_a, params.arm_b}:
        return Evaluation(False, "both arms need observations", None, False, cutoff, (), None)
    result = compare_cohorts(selected, params)
    if not result.fired:
        return Evaluation(False, result.reason, result.relative_lift, result.causal, cutoff, result.arms, None)
    recommendation_id = (
        "rec-"
        + hashlib.sha256(
            digest_command("EVALUATE", user_id, project_name, "learning", command_id).encode()
        ).hexdigest()[:32]
    )
    proposed = recommendation_from(
        result,
        selected,
        recommendation_id=recommendation_id,
        expires_at=(now or datetime.now(UTC)) + expires_in,
    )
    await repository.propose(
        user_id=user_id,
        project_name=project_name,
        recommendation=proposed,
        evidence_cutoff=cutoff,
        command_id=command_id,
    )
    stored = await repository.get(user_id=user_id, project_name=project_name, recommendation_id=recommendation_id)
    await session.commit()
    return Evaluation(True, result.reason, result.relative_lift, result.causal, cutoff, result.arms, stored)


async def decide(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    recommendation_id: str,
    disposition: RecommendationDisposition,
    expected_recommendation_digest: str,
    actor_id: str,
    reason: str,
    command_id: str,
) -> RecommendationDecision:
    decision = await LearningRecommendationRepository(session).decide(
        user_id=user_id,
        project_name=project_name,
        recommendation_id=recommendation_id,
        disposition=disposition,
        expected_recommendation_digest=expected_recommendation_digest,
        actor_id=actor_id,
        reason=reason,
        command_id=command_id,
    )
    await session.commit()
    return decision


async def list_recommendations(
    session: AsyncSession, *, user_id: str, project_name: str
) -> tuple[StoredRecommendation, ...]:
    return await LearningRecommendationRepository(session).list(user_id=user_id, project_name=project_name)


__all__ = [
    "CohortSelection",
    "Evaluation",
    "decide",
    "evaluate",
    "ingest_observation",
    "list_recommendations",
]
