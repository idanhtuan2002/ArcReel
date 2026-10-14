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
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.learning import LearningEvaluationModel
from lib.db.repositories.learning import LearningObservationRepository
from lib.db.repositories.learning_recommendations import LearningRecommendationRepository, StoredRecommendation
from lib.project_manager import ProjectManager
from r2.advanced_creative.digests import digest_command
from r2.advanced_creative.errors import CommandConflictError
from r2.contracts.advanced_creative import (
    LearningObservation,
    RecommendationDecision,
    RecommendationDisposition,
)
from r2.learning.cohorts import RuleParams, compare_cohorts, recommendation_from
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
    """One evaluate command's outcome as recorded; ``arms`` are the transparent summaries as JSON."""

    fired: bool
    reason: str
    relative_lift: str | None
    evidence_cutoff: datetime | None
    arms: tuple[dict[str, object], ...]
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


def _evaluation_digest(
    *, user_id: str, project_name: str, selection: CohortSelection, params: RuleParams, expires_in: timedelta
) -> str:
    request = {
        "selection": asdict(selection),
        "params": asdict(params),
        "expires_in_seconds": int(expires_in.total_seconds()),
    }
    return digest_command("EVALUATE", user_id, project_name, "learning", request)


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
    """Run the rule at the scope watermark; a fired rule proposes one recommendation.

    Every outcome is recorded under its command: a retry with the same request replays it exactly,
    and the same command id with a different request is a conflict.
    """
    if not command_id:
        raise ValueError("command_id is required")
    if not timedelta(0) < expires_in <= timedelta(days=365):
        raise ValueError("expiry must be within a year")
    request_digest = _evaluation_digest(
        user_id=user_id, project_name=project_name, selection=selection, params=params, expires_in=expires_in
    )
    observations = LearningObservationRepository(session)
    repository = LearningRecommendationRepository(session)
    await observations.lock_scope(user_id=user_id, project_name=project_name)
    recorded = await session.get(LearningEvaluationModel, (user_id, project_name, command_id))
    if recorded is not None:
        if recorded.request_digest != request_digest:
            raise CommandConflictError("command id reused with a different evaluation")
        return await _evaluation(repository, recorded, user_id=user_id, project_name=project_name)

    cutoff = await observations.watermark(user_id=user_id, project_name=project_name)
    reason, lift, arms, recommendation_id = "no observations", None, (), None
    if cutoff is not None:
        current = await observations.list_as_of(user_id=user_id, project_name=project_name, cutoff=cutoff)
        selected = [item for item in current if _in_cohort(item, selection, (params.arm_a, params.arm_b))]
        if not {item.format_profile_ref for item in selected} >= {params.arm_a, params.arm_b}:
            reason = "both arms need observations"
        else:
            result = compare_cohorts(selected, params)
            reason, lift, arms = result.reason, result.relative_lift, tuple(arm.as_json() for arm in result.arms)
            if result.fired:
                recommendation_id = (
                    "rec-" + hashlib.sha256(f"{user_id}\x1f{project_name}\x1f{command_id}".encode()).hexdigest()[:32]
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
    row = LearningEvaluationModel(
        user_id=user_id,
        project_name=project_name,
        command_id=command_id,
        request_digest=request_digest,
        result_json={
            "fired": recommendation_id is not None,
            "reason": reason,
            "relative_lift": None if lift is None else format(lift.normalize(), "f"),
            "evidence_cutoff": None if cutoff is None else cutoff.isoformat(),
            "arms": list(arms),
        },
        recommendation_id=recommendation_id,
        created_at=now or datetime.now(UTC),
    )
    session.add(row)
    await session.flush()
    evaluation = await _evaluation(repository, row, user_id=user_id, project_name=project_name)
    await session.commit()
    return evaluation


async def _evaluation(
    repository: LearningRecommendationRepository, row: LearningEvaluationModel, *, user_id: str, project_name: str
) -> Evaluation:
    result = row.result_json
    cutoff = result.get("evidence_cutoff")
    recommendation = (
        None
        if row.recommendation_id is None
        else await repository.get(user_id=user_id, project_name=project_name, recommendation_id=row.recommendation_id)
    )
    return Evaluation(
        fired=bool(result["fired"]),
        reason=str(result["reason"]),
        relative_lift=result.get("relative_lift"),
        evidence_cutoff=None if cutoff is None else datetime.fromisoformat(cutoff),
        arms=tuple(result.get("arms", [])),
        recommendation=recommendation,
    )


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
