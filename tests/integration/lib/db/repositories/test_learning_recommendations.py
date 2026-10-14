"""The M8-D recommendation lifecycle on a real database (plan 2026-10-14 D3 decisions 6-9)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.learning import LearningObservationRepository
from lib.db.repositories.learning_recommendations import LearningRecommendationRepository, recommendation_digest
from r2.advanced_creative.errors import (
    CommandConflictError,
    RecommendationConflictError,
    RecommendationNotFoundError,
    RecommendationStaleError,
)
from r2.contracts.advanced_creative import LearningObservation, LearningRecommendation, RecommendationDisposition
from r2.learning.cohorts import CausalLanguageError, CohortLeakError, RuleParams, compare_cohorts, recommendation_from
from tests.unit.r2.learning.test_cohorts import arm

type Factory = async_sessionmaker[AsyncSession]

USER = "default"
PROJECT = "demo"
START = datetime(2026, 10, 1, tzinfo=UTC)
PARAMS = RuleParams(arm_a="16x9", arm_b="9x16", min_per_arm=3, min_relative_lift=Decimal("0.10"))


class _Clock:
    def __init__(self) -> None:
        self.now = START + timedelta(days=30)

    def __call__(self) -> datetime:
        return self.now


async def _ingest_all(factory: Factory, clock: _Clock, observations: list[LearningObservation]) -> datetime:
    async with factory() as session:
        repo = LearningObservationRepository(session, clock=clock)
        for item in observations:
            await repo.ingest(
                user_id=USER, project_name=PROJECT, observation=item, command_id=f"ingest-{item.observation_id}"
            )
        watermark = await repo.watermark(user_id=USER, project_name=PROJECT)
        await session.commit()
    assert watermark is not None
    return watermark


def _evidence(b_value: str = "120", prefix: str = "") -> list[LearningObservation]:
    return [
        *arm("16x9", ["100", "100", "100"], prefix=f"{prefix}a"),
        *arm("9x16", [b_value, b_value, b_value], prefix=f"{prefix}b"),
    ]


def _recommend(evidence: list[LearningObservation], rec_id: str = "rec-1", **changes) -> LearningRecommendation:
    rec = recommendation_from(
        compare_cohorts(evidence, PARAMS), evidence, recommendation_id=rec_id, expires_at=START + timedelta(days=60)
    )
    return rec.model_copy(update=changes) if changes else rec


async def _call(factory: Factory, clock: _Clock, method: str, **kwargs):
    async with factory() as session:
        result = await getattr(LearningRecommendationRepository(session, clock=clock), method)(
            user_id=USER, project_name=kwargs.pop("project_name", PROJECT), **kwargs
        )
        await session.commit()
        return result


async def _propose(factory, clock, rec, cutoff, command="p-1"):
    return await _call(factory, clock, "propose", recommendation=rec, evidence_cutoff=cutoff, command_id=command)


async def _decide(factory, clock, rec, disposition, command, *, digest=None, reason="checked"):
    return await _call(
        factory,
        clock,
        "decide",
        recommendation_id=rec.recommendation_id,
        disposition=disposition,
        expected_recommendation_digest=digest or recommendation_digest(rec),
        actor_id="reviewer-a",
        reason=reason,
        command_id=command,
    )


async def test_a_proposal_is_admitted_once_and_replays(session_factory: Factory) -> None:
    clock = _Clock()
    evidence = _evidence()
    cutoff = await _ingest_all(session_factory, clock, evidence)
    rec = _recommend(evidence)

    assert await _propose(session_factory, clock, rec, cutoff) == rec
    assert await _propose(session_factory, clock, rec, cutoff) == rec
    with pytest.raises(CommandConflictError):
        await _propose(session_factory, clock, _recommend(evidence, "rec-2"), cutoff)
    with pytest.raises(RecommendationConflictError):
        await _propose(session_factory, clock, rec, cutoff, command="p-2")
    stored = await _call(session_factory, clock, "get", recommendation_id="rec-1")
    assert (stored.recommendation, stored.evidence_cutoff, stored.rule) == (rec, cutoff, "compare_cohorts@1")
    assert await _call(session_factory, clock, "get", recommendation_id="rec-1", project_name="other") is None


async def test_proposals_need_current_evidence_one_cohort_and_honest_language(session_factory: Factory) -> None:
    clock = _Clock()
    evidence = _evidence()
    cutoff = await _ingest_all(session_factory, clock, evidence)

    with pytest.raises(RecommendationStaleError, match="current records"):
        await _propose(
            session_factory, clock, _recommend(evidence, evidence_observation_ids=("missing-id",)), cutoff, command="c1"
        )
    with pytest.raises(CausalLanguageError):
        await _propose(
            session_factory,
            clock,
            _recommend(evidence, hypothesis="Vertical framing increases views"),
            cutoff,
            command="c2",
        )
    with pytest.raises(RecommendationStaleError, match="expired"):
        await _propose(session_factory, clock, _recommend(evidence, expires_at=START), cutoff, command="c3")
    foreign = _recommend(evidence, lineage=evidence[0].lineage.model_copy(update={"creative_profile_id": "zh-shuang"}))
    with pytest.raises(CohortLeakError):
        await _propose(session_factory, clock, foreign, cutoff, command="c4")
    # A cutoff past the watermark could still gain evidence and is refused.
    with pytest.raises(ValueError, match="watermark"):
        await _propose(session_factory, clock, _recommend(evidence), cutoff + timedelta(days=1), command="c5")

    # Correcting one evidence record makes the old record non-current at a later cutoff.
    async with session_factory() as session:
        await LearningObservationRepository(session, clock=clock).ingest(
            user_id=USER,
            project_name=PROJECT,
            observation=evidence[0].model_copy(
                update={
                    "observation_id": "fix-1",
                    "correction_of": evidence[0].observation_id,
                    "metric_value": Decimal(90),
                }
            ),
            command_id="fix",
        )
        later = await LearningObservationRepository(session).watermark(user_id=USER, project_name=PROJECT)
        await session.commit()
    with pytest.raises(RecommendationStaleError, match="current records"):
        await _propose(session_factory, clock, _recommend(evidence), later, command="c6")


async def test_decisions_are_human_append_only_and_final_once(session_factory: Factory) -> None:
    clock = _Clock()
    evidence = _evidence()
    rec = _recommend(evidence)
    await _propose(session_factory, clock, rec, await _ingest_all(session_factory, clock, evidence))

    with pytest.raises(RecommendationStaleError, match="shown"):
        await _decide(session_factory, clock, rec, RecommendationDisposition.ACCEPT, "d0", digest="sha256:" + "0" * 64)
    deferred = await _decide(session_factory, clock, rec, RecommendationDisposition.DEFER, "d1")
    assert deferred.governed_proposal_ref is None
    accepted = await _decide(session_factory, clock, rec, RecommendationDisposition.ACCEPT, "d2")
    assert accepted.governed_proposal_ref == f"learning-proposal:{accepted.decision_id}"
    assert accepted.actor_id == "reviewer-a"
    assert await _decide(session_factory, clock, rec, RecommendationDisposition.ACCEPT, "d2") == accepted
    with pytest.raises(RecommendationConflictError, match="final decision"):
        await _decide(session_factory, clock, rec, RecommendationDisposition.REJECT, "d3")
    with pytest.raises(CommandConflictError):
        await _decide(session_factory, clock, rec, RecommendationDisposition.REJECT, "d2")
    with pytest.raises(RecommendationNotFoundError):
        await _decide(
            session_factory,
            clock,
            rec.model_copy(update={"recommendation_id": "nope"}),
            RecommendationDisposition.DEFER,
            "d4",
        )
    with pytest.raises(ValueError, match="reason"):
        await _decide(session_factory, clock, rec, RecommendationDisposition.DEFER, "d5", reason="  ")

    stored = await _call(session_factory, clock, "get", recommendation_id=rec.recommendation_id)
    assert [item.disposition for item in stored.decisions] == ["DEFER", "ACCEPT"]


async def test_identical_nonfinal_decisions_under_two_commands_are_two_decisions(session_factory: Factory) -> None:
    clock = _Clock()
    evidence = _evidence()
    rec = _recommend(evidence)
    await _propose(session_factory, clock, rec, await _ingest_all(session_factory, clock, evidence))

    first = await _decide(session_factory, clock, rec, RecommendationDisposition.DEFER, "d1")
    second = await _decide(session_factory, clock, rec, RecommendationDisposition.DEFER, "d2")

    assert first.decision_id != second.decision_id
    stored = await _call(session_factory, clock, "get", recommendation_id=rec.recommendation_id)
    assert len(stored.decisions) == 2


async def test_the_recorded_language_must_match_the_evidence(session_factory: Factory) -> None:
    clock = _Clock()
    evidence = _evidence()
    cutoff = await _ingest_all(session_factory, clock, evidence)
    rec = _recommend(evidence)
    claimed = rec.model_copy(
        update={
            "applicability": rec.applicability.model_validate({**rec.applicability.model_dump(), "language": "causal"})
        }
    )

    with pytest.raises(CausalLanguageError, match="recorded language"):
        await _propose(session_factory, clock, claimed, cutoff)


async def test_expired_or_corrected_evidence_cannot_be_decided(session_factory: Factory) -> None:
    clock = _Clock()
    evidence = _evidence()
    rec = _recommend(evidence)
    await _propose(session_factory, clock, rec, await _ingest_all(session_factory, clock, evidence))

    clock.now = START + timedelta(days=61)
    with pytest.raises(RecommendationStaleError, match="expired"):
        await _decide(session_factory, clock, rec, RecommendationDisposition.ACCEPT, "d1")
    clock.now = START + timedelta(days=31)
    async with session_factory() as session:
        await LearningObservationRepository(session, clock=clock).ingest(
            user_id=USER,
            project_name=PROJECT,
            observation=evidence[3].model_copy(
                update={
                    "observation_id": "fix-b",
                    "correction_of": evidence[3].observation_id,
                    "metric_value": Decimal(1),
                }
            ),
            command_id="fix",
        )
        await session.commit()
    with pytest.raises(RecommendationStaleError, match="corrected"):
        await _decide(session_factory, clock, rec, RecommendationDisposition.ACCEPT, "d2")


async def test_a_rejected_proposal_returns_only_with_new_evidence(session_factory: Factory) -> None:
    clock = _Clock()
    evidence = _evidence()
    cutoff = await _ingest_all(session_factory, clock, evidence)
    first = _recommend(evidence)
    await _propose(session_factory, clock, first, cutoff)
    await _decide(session_factory, clock, first, RecommendationDisposition.REJECT, "d1")

    with pytest.raises(RecommendationConflictError, match="new evidence"):
        await _propose(session_factory, clock, _recommend(evidence, "rec-2"), cutoff, command="p-2")
    more = [*evidence, *arm("9x16", ["125"], prefix="new", day=2)]
    later = await _ingest_all(session_factory, clock, more[-1:])
    again = _recommend(more, "rec-3")
    assert await _propose(session_factory, clock, again, later, command="p-3") == again


async def test_concurrent_final_decisions_have_one_winner(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("concurrent decisions need PostgreSQL locks")
    clock = _Clock()
    evidence = _evidence()
    rec = _recommend(evidence)
    await _propose(session_factory, clock, rec, await _ingest_all(session_factory, clock, evidence))

    results = await asyncio.gather(
        _decide(session_factory, clock, rec, RecommendationDisposition.ACCEPT, "a"),
        _decide(session_factory, clock, rec, RecommendationDisposition.REJECT, "b"),
        return_exceptions=True,
    )

    assert sum(isinstance(item, RecommendationConflictError) for item in results) == 1
    assert sum(not isinstance(item, BaseException) for item in results) == 1
