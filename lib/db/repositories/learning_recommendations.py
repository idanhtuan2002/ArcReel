"""Persistence for M8-D recommendations and Human decisions (plan 2026-10-14 D3 decisions 6-9).

Rows are append-only and written inside the caller's transaction, serialized per scope with the
observation admissions. A proposal is admitted only when every evidence observation is the current
record of its identity as of the pinned cutoff, the evidence forms one cohort of one lineage, the
hypothesis language matches the evidence design, and it does not repeat a rejected proposal without
new evidence. A decision needs the exact recommendation digest, an unexpired recommendation and
uncorrected evidence; ACCEPT records only a governed proposal reference.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.learning import (
    LearningObservationModel,
    LearningRecommendationDecisionModel,
    LearningRecommendationEvidenceModel,
    LearningRecommendationModel,
)
from lib.db.repositories.learning import LearningObservationRepository
from r2.advanced_creative.digests import digest_canonical, digest_command
from r2.advanced_creative.errors import (
    CommandConflictError,
    RecommendationConflictError,
    RecommendationNotFoundError,
    RecommendationStaleError,
)
from r2.contracts.advanced_creative import LearningRecommendation, RecommendationDecision, RecommendationDisposition
from r2.learning.cohorts import (
    RULE_ID,
    RULE_VERSION,
    CausalLanguageError,
    CohortLeakError,
    causal_surface,
    check_hypothesis_language,
    proposal_key,
    single_cohort,
)

Clock = Callable[[], datetime]
PROPOSE = "PROPOSE_RECOMMENDATION"
DECIDE = "DECIDE_RECOMMENDATION"
_TERMINAL = {RecommendationDisposition.ACCEPT, RecommendationDisposition.REJECT}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def recommendation_digest(recommendation: LearningRecommendation) -> str:
    return digest_canonical({"contract_version": "1", "recommendation": recommendation})


def _decision_digest(decision: RecommendationDecision) -> str:
    return digest_canonical({"contract_version": "1", "decision": decision})


@dataclass(frozen=True)
class StoredRecommendation:
    recommendation: LearningRecommendation
    recommendation_digest: str
    evidence_cutoff: datetime
    rule: str
    created_at: datetime
    decisions: tuple[RecommendationDecision, ...]


class LearningRecommendationRepository:
    """``RecommendationService`` persistence; it has no write port outside the learning tables."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self.session = session
        self._clock = clock or (lambda: datetime.now(UTC))
        self._observations = LearningObservationRepository(session, clock=self._clock)

    def _now(self) -> datetime:
        return _utc(self._clock())

    async def _row(
        self, *, user_id: str, project_name: str, recommendation_id: str
    ) -> LearningRecommendationModel | None:
        return await self.session.get(LearningRecommendationModel, (user_id, project_name, recommendation_id))

    async def _evidence_ids(self, *, user_id: str, project_name: str, recommendation_id: str) -> set[str]:
        model = LearningRecommendationEvidenceModel
        rows = await self.session.scalars(
            select(model.observation_id).where(
                model.user_id == user_id,
                model.project_name == project_name,
                model.recommendation_id == recommendation_id,
            )
        )
        return set(rows.all())

    async def _decisions(
        self, *, user_id: str, project_name: str, recommendation_id: str
    ) -> tuple[RecommendationDecision, ...]:
        model = LearningRecommendationDecisionModel
        rows = await self.session.scalars(
            select(model)
            .where(
                model.user_id == user_id,
                model.project_name == project_name,
                model.recommendation_id == recommendation_id,
            )
            .order_by(model.decided_at, model.decision_id)
        )
        return tuple(RecommendationDecision.model_validate(row.decision_json) for row in rows.all())

    async def _rejected_evidence(self, *, user_id: str, project_name: str, key: str) -> list[set[str]]:
        rec, dec = LearningRecommendationModel, LearningRecommendationDecisionModel
        ids = await self.session.scalars(
            select(rec.recommendation_id)
            .join(
                dec,
                (dec.user_id == rec.user_id)
                & (dec.project_name == rec.project_name)
                & (dec.recommendation_id == rec.recommendation_id),
            )
            .where(
                rec.user_id == user_id,
                rec.project_name == project_name,
                rec.proposal_key == key,
                dec.disposition == RecommendationDisposition.REJECT.value,
            )
        )
        return [
            await self._evidence_ids(user_id=user_id, project_name=project_name, recommendation_id=rid)
            for rid in ids.all()
        ]

    async def propose(
        self,
        *,
        user_id: str,
        project_name: str,
        recommendation: LearningRecommendation,
        evidence_cutoff: datetime,
        command_id: str,
    ) -> LearningRecommendation:
        if not command_id:
            raise ValueError("command_id is required")
        cutoff = _utc(evidence_cutoff)
        command_digest = digest_command(
            PROPOSE, user_id, project_name, "learning", {"recommendation": recommendation, "evidence_cutoff": cutoff}
        )
        await self._observations.lock_scope(user_id=user_id, project_name=project_name)
        model = LearningRecommendationModel
        by_command = await self.session.scalar(
            select(model).where(
                model.user_id == user_id, model.project_name == project_name, model.command_id == command_id
            )
        )
        if by_command is not None:
            if by_command.command_digest != command_digest:
                raise CommandConflictError("command id reused with different content")
            return LearningRecommendation.model_validate(by_command.recommendation_json)
        digest = recommendation_digest(recommendation)
        same_id = await self._row(
            user_id=user_id, project_name=project_name, recommendation_id=recommendation.recommendation_id
        )
        if same_id is not None:
            raise RecommendationConflictError("recommendation id already used")

        if recommendation.lineage.project_name != project_name:
            raise CohortLeakError("recommendation lineage names another project")
        if _utc(recommendation.expires_at) <= self._now():
            raise RecommendationStaleError("recommendation is already expired")
        evidence_ids = recommendation.evidence_observation_ids
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence ids must be present and distinct")
        current = {
            item.observation_id: item
            for item in await self._observations.list_as_of(user_id=user_id, project_name=project_name, cutoff=cutoff)
        }
        if any(observation_id not in current for observation_id in evidence_ids):
            raise RecommendationStaleError("evidence must be the current records as of the cutoff")
        evidence = [current[observation_id] for observation_id in evidence_ids]
        single_cohort(evidence)
        lineage = recommendation.lineage
        if {
            (
                item.lineage.project_name,
                item.lineage.creative_profile_id,
                item.lineage.creative_profile_version,
                item.lineage.policy_digest,
            )
            for item in evidence
        } != {
            (lineage.project_name, lineage.creative_profile_id, lineage.creative_profile_version, lineage.policy_digest)
        }:
            raise CohortLeakError("evidence and recommendation lineage differ")
        surface = causal_surface(evidence)
        scope = recommendation.applicability.model_dump(mode="python")
        if scope.get("language") != ("causal" if surface else "associative") or scope.get("surface") != surface:
            raise CausalLanguageError("the recorded language must match what the evidence supports")
        arms = scope.get("arms")
        if not isinstance(arms, list) or set(map(str, arms)) != {item.format_profile_ref for item in evidence}:
            raise CohortLeakError("the recorded arms must be exactly the evidence formats")
        check_hypothesis_language(
            recommendation.hypothesis,
            causal_allowed=surface is not None,
            neutral_terms=[str(arm) for arm in arms],
        )

        key = proposal_key(recommendation)
        for rejected in await self._rejected_evidence(user_id=user_id, project_name=project_name, key=key):
            if set(evidence_ids) <= rejected:
                raise RecommendationConflictError("a rejected proposal needs new evidence")

        self.session.add(
            LearningRecommendationModel(
                user_id=user_id,
                project_name=project_name,
                recommendation_id=recommendation.recommendation_id,
                recommendation_json=recommendation.model_dump(mode="json"),
                recommendation_digest=digest,
                proposal_key=key,
                rule=f"{RULE_ID}@{RULE_VERSION}",
                evidence_cutoff=cutoff,
                expires_at=_utc(recommendation.expires_at),
                command_id=command_id,
                command_digest=command_digest,
                created_at=self._now(),
            )
        )
        await self.session.flush()
        self.session.add_all(
            LearningRecommendationEvidenceModel(
                user_id=user_id,
                project_name=project_name,
                recommendation_id=recommendation.recommendation_id,
                observation_id=observation_id,
            )
            for observation_id in evidence_ids
        )
        await self.session.flush()
        return recommendation

    async def decide(
        self,
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
        """Append one Human disposition; the server sets the decision id, time and proposal reference."""
        if not command_id:
            raise ValueError("command_id is required")
        if not reason.strip():
            raise ValueError("a decision needs a reason")
        request = {
            "recommendation_id": recommendation_id,
            "disposition": disposition,
            "expected_recommendation_digest": expected_recommendation_digest,
            "reason": reason,
        }
        command_digest = digest_command(DECIDE, user_id, project_name, actor_id, request)
        await self._observations.lock_scope(user_id=user_id, project_name=project_name)
        model = LearningRecommendationDecisionModel
        by_command = await self.session.scalar(
            select(model).where(
                model.user_id == user_id, model.project_name == project_name, model.command_id == command_id
            )
        )
        if by_command is not None:
            if by_command.command_digest != command_digest:
                raise CommandConflictError("command id reused with different content")
            return RecommendationDecision.model_validate(by_command.decision_json)

        row = await self._row(user_id=user_id, project_name=project_name, recommendation_id=recommendation_id)
        if row is None:
            raise RecommendationNotFoundError("unknown recommendation")
        if row.recommendation_digest != expected_recommendation_digest:
            raise RecommendationStaleError("the recommendation shown is not the recorded one")
        if any(
            item.disposition in _TERMINAL
            for item in await self._decisions(
                user_id=user_id, project_name=project_name, recommendation_id=recommendation_id
            )
        ):
            raise RecommendationConflictError("recommendation already has a final decision")
        now = self._now()
        if now >= _utc(row.expires_at):
            raise RecommendationStaleError("recommendation expired")
        obs = LearningObservationModel
        corrected = await self.session.scalar(
            select(obs.observation_id).where(
                obs.user_id == user_id,
                obs.project_name == project_name,
                obs.correction_of.in_(
                    await self._evidence_ids(
                        user_id=user_id, project_name=project_name, recommendation_id=recommendation_id
                    )
                ),
            )
        )
        if corrected is not None:
            raise RecommendationStaleError("evidence was corrected after the proposal")

        # One decision per scoped command; identical requests under two commands are two decisions.
        decision_id = "dec-" + hashlib.sha256(f"{user_id}\x1f{project_name}\x1f{command_id}".encode()).hexdigest()[:32]
        decision = RecommendationDecision(
            decision_id=decision_id,
            recommendation_id=recommendation_id,
            disposition=disposition,
            expected_recommendation_digest=expected_recommendation_digest,
            actor_id=actor_id,
            reason=reason,
            governed_proposal_ref=f"learning-proposal:{decision_id}"
            if disposition is RecommendationDisposition.ACCEPT
            else None,
            decided_at=now,
        )
        self.session.add(
            LearningRecommendationDecisionModel(
                user_id=user_id,
                project_name=project_name,
                decision_id=decision_id,
                recommendation_id=recommendation_id,
                disposition=disposition.value,
                terminal=disposition in _TERMINAL,
                governed_proposal_ref=decision.governed_proposal_ref,
                decision_json=decision.model_dump(mode="json"),
                decision_digest=_decision_digest(decision),
                command_id=command_id,
                command_digest=command_digest,
                decided_at=now,
            )
        )
        await self.session.flush()
        return decision

    async def by_command(self, *, user_id: str, project_name: str, command_id: str) -> StoredRecommendation | None:
        model = LearningRecommendationModel
        row = await self.session.scalar(
            select(model).where(
                model.user_id == user_id, model.project_name == project_name, model.command_id == command_id
            )
        )
        return None if row is None else await self._stored(row)

    async def get(self, *, user_id: str, project_name: str, recommendation_id: str) -> StoredRecommendation | None:
        row = await self._row(user_id=user_id, project_name=project_name, recommendation_id=recommendation_id)
        return None if row is None else await self._stored(row)

    async def _stored(self, row: LearningRecommendationModel) -> StoredRecommendation:
        return StoredRecommendation(
            recommendation=LearningRecommendation.model_validate(row.recommendation_json),
            recommendation_digest=row.recommendation_digest,
            evidence_cutoff=_utc(row.evidence_cutoff),
            rule=row.rule,
            created_at=_utc(row.created_at),
            decisions=await self._decisions(
                user_id=row.user_id, project_name=row.project_name, recommendation_id=row.recommendation_id
            ),
        )

    async def list(self, *, user_id: str, project_name: str) -> tuple[StoredRecommendation, ...]:
        model = LearningRecommendationModel
        rows = await self.session.scalars(
            select(model)
            .where(model.user_id == user_id, model.project_name == project_name)
            .order_by(model.created_at.desc(), model.recommendation_id)
        )
        return tuple([await self._stored(row) for row in rows.all()])


__all__ = ["LearningRecommendationRepository", "StoredRecommendation", "recommendation_digest"]
