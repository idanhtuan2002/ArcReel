"""Transparent cohort summaries and the V1 evidence rule (spec §9; plan D3 decisions 1-4).

A cohort pools observations of one creative profile and version, one source family, one metric under
one definition, and one window aggregation. ``generic-western`` and ``zh-shuang`` are never pooled:
mixing profiles, families, metrics, definitions or aggregations is a cohort leak. Summaries count
missing values by reason and never impute them.

The only V1 rule, ``compare_cohorts@1``, compares two arms of ``format_profile_ref``. Its hypothesis is
generated from a template: associative unless every evidence observation comes from a concurrent
randomized or platform-managed experiment on one exposure surface.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    ExperimentDesign,
    LearningObservation,
    LearningRecommendation,
    LineageBinding,
)

RULE_ID = "compare_cohorts"
RULE_VERSION = "1"
CAUSAL_DESIGNS = frozenset({ExperimentDesign.CONCURRENT_RANDOMIZED, ExperimentDesign.PLATFORM_MANAGED})
_CAUSAL_WORDS = re.compile(
    r"\b(caus\w*|because|leads? to|led to|drives?|drove|results? in|increases?|decreases?|boosts?|improves?|reduces?)\b"
    r"|导致|因为|提升|提高|降低|引起|促使"
    r"|gây ra|vì vậy|làm tăng|làm giảm|dẫn đến",
    re.IGNORECASE,
)


class CohortLeakError(ValueError):
    """Evidence crossed an undeclared profile or cohort boundary (``M8_PROFILE_COHORT_LEAK``)."""

    code = "M8_PROFILE_COHORT_LEAK"


class CausalLanguageError(ValueError):
    """An associative hypothesis uses causal language."""


@dataclass(frozen=True, order=True)
class CohortKey:
    creative_profile_id: str
    creative_profile_version: str
    source_family: str
    metric_name: str
    metric_definition_version: str
    aggregation: str


@dataclass(frozen=True)
class CohortSummary:
    key: CohortKey
    arm: str | None
    n: int
    missing: tuple[tuple[str, int], ...]
    mean: Decimal | None
    median: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    observation_ids: tuple[str, ...]

    @property
    def present(self) -> int:
        return self.n - sum(count for _reason, count in self.missing)

    def as_json(self) -> dict[str, object]:
        def text(value: Decimal | None) -> str | None:
            return None if value is None else format(value.normalize(), "f")

        return {
            "arm": self.arm,
            "n": self.n,
            "present": self.present,
            "missing": dict(self.missing),
            "mean": text(self.mean),
            "median": text(self.median),
            "min": text(self.minimum),
            "max": text(self.maximum),
            "observation_ids": list(self.observation_ids),
        }


def cohort_key(observation: LearningObservation) -> CohortKey:
    return CohortKey(
        creative_profile_id=observation.lineage.creative_profile_id,
        creative_profile_version=observation.lineage.creative_profile_version,
        source_family=observation.source_family,
        metric_name=observation.metric_name,
        metric_definition_version=observation.metric_definition_version,
        aggregation=observation.window.aggregation,
    )


def single_cohort(observations: Sequence[LearningObservation]) -> CohortKey:
    keys = {cohort_key(item) for item in observations}
    if len(keys) != 1:
        raise CohortLeakError("evidence must share one profile, family, metric, definition and aggregation")
    return next(iter(keys))


def summarize(observations: Sequence[LearningObservation], *, arm: str | None = None) -> CohortSummary:
    key = single_cohort(observations)
    if len({item.observation_id for item in observations}) != len(observations):
        raise ValueError("an observation appears twice in a cohort")
    values = sorted(item.metric_value for item in observations if item.metric_value is not None)
    missing = Counter(item.missing_reason or "MISSING" for item in observations if item.metric_value is None)
    return CohortSummary(
        key=key,
        arm=arm,
        n=len(observations),
        missing=tuple(sorted(missing.items())),
        mean=sum(values, Decimal(0)) / len(values) if values else None,
        median=Decimal(median(values)) if values else None,
        minimum=values[0] if values else None,
        maximum=values[-1] if values else None,
        observation_ids=tuple(sorted(item.observation_id for item in observations)),
    )


def is_causal_evidence(observations: Sequence[LearningObservation]) -> bool:
    """Causal language is allowed only for one concurrent randomized or platform-managed surface."""
    if not observations or any(item.experiment_design not in CAUSAL_DESIGNS for item in observations):
        return False
    surfaces = {item.exposure_ref for item in observations}
    return len(surfaces) == 1 and None not in surfaces


def check_hypothesis_language(hypothesis: str, *, causal_allowed: bool) -> None:
    if not causal_allowed and _CAUSAL_WORDS.search(hypothesis):
        raise CausalLanguageError("associative evidence cannot support causal language")


@dataclass(frozen=True)
class RuleParams:
    arm_a: str
    arm_b: str
    min_per_arm: int
    min_relative_lift: Decimal

    def __post_init__(self) -> None:
        if self.arm_a == self.arm_b:
            raise ValueError("a comparison needs two arms")
        if self.min_per_arm < 2:
            raise ValueError("each arm needs at least two values")
        if not Decimal(0) < self.min_relative_lift:
            raise ValueError("the lift threshold must be positive")


@dataclass(frozen=True)
class RuleResult:
    fired: bool
    reason: str
    key: CohortKey
    arms: tuple[CohortSummary, CohortSummary]
    relative_lift: Decimal | None
    causal: bool


def compare_cohorts(observations: Sequence[LearningObservation], params: RuleParams) -> RuleResult:
    """Compare the two arms' means; fires only with enough present values and a large enough lift."""
    key = single_cohort(observations)
    arms = {params.arm_a: [], params.arm_b: []}
    for item in observations:
        if item.format_profile_ref in arms:
            arms[item.format_profile_ref].append(item)
    if not arms[params.arm_a] or not arms[params.arm_b]:
        raise ValueError("both arms need observations")
    a, b = summarize(arms[params.arm_a], arm=params.arm_a), summarize(arms[params.arm_b], arm=params.arm_b)
    evidence = [*arms[params.arm_a], *arms[params.arm_b]]
    causal = is_causal_evidence(evidence)
    if min(a.present, b.present) < params.min_per_arm:
        return RuleResult(False, "insufficient present values", key, (a, b), None, causal)
    if a.mean is None or b.mean is None:
        return RuleResult(False, "insufficient present values", key, (a, b), None, causal)
    if a.mean == 0:
        return RuleResult(False, "baseline mean is zero", key, (a, b), None, causal)
    lift = (b.mean - a.mean) / abs(a.mean)
    if abs(lift) < params.min_relative_lift:
        return RuleResult(False, "lift below threshold", key, (a, b), lift, causal)
    return RuleResult(True, "lift at or above threshold", key, (a, b), lift, causal)


def hypothesis_text(result: RuleResult) -> str:
    a, b = result.arms
    assert result.relative_lift is not None
    direction = "higher" if result.relative_lift > 0 else "lower"
    percent = (abs(result.relative_lift) * 100).quantize(Decimal("0.1"))
    verb = "caused" if result.causal else "is associated with"
    return (
        f"Format {b.arm} {verb} {percent}% {direction} mean {result.key.metric_name} than format {a.arm} "
        f"({result.key.source_family}, {result.key.creative_profile_id}@{result.key.creative_profile_version})."
    )


def applicability(result: RuleResult) -> dict[str, object]:
    key = result.key
    return {
        "rule": f"{RULE_ID}@{RULE_VERSION}",
        "creative_profile_id": key.creative_profile_id,
        "creative_profile_version": key.creative_profile_version,
        "source_family": key.source_family,
        "metric_name": key.metric_name,
        "metric_definition_version": key.metric_definition_version,
        "aggregation": key.aggregation,
        "split": "format_profile_ref",
        "arms": [result.arms[0].arm, result.arms[1].arm],
    }


def proposal_key(recommendation: LearningRecommendation) -> str:
    """The identity a repeated proposal shares with an earlier one, whatever its evidence or summaries."""
    scope = {
        key: value
        for key, value in recommendation.applicability.model_dump(mode="python").items()
        if key != "summaries"
    }
    return digest_canonical({"contract_version": "1", "applicability": scope})


def recommendation_from(
    result: RuleResult,
    observations: Sequence[LearningObservation],
    *,
    recommendation_id: str,
    expires_at: datetime,
) -> LearningRecommendation:
    """The recommendation a fired rule proposes; every input observation is evidence."""
    if not result.fired:
        raise ValueError("only a fired rule proposes a recommendation")
    a, b = result.arms
    evidence = tuple(sorted({*a.observation_ids, *b.observation_ids}))
    lineages = [item.lineage for item in observations if item.observation_id in evidence]
    shared = {
        (item.project_name, item.creative_profile_id, item.creative_profile_version, item.policy_digest)
        for item in lineages
    }
    if len(shared) != 1:
        raise CohortLeakError("evidence must share one project, profile and policy lineage")
    project_name, profile_id, profile_version, policy_digest = next(iter(shared))
    lineage = LineageBinding(
        project_name=project_name,
        content_basis_digest=digest_canonical(
            {
                "basis_kind": "learning_evidence",
                "content_basis_digests": sorted({item.content_basis_digest for item in lineages}),
            }
        ),
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id=profile_id,
        creative_profile_version=profile_version,
        policy_digest=policy_digest,
    )
    hypothesis = hypothesis_text(result)
    check_hypothesis_language(hypothesis, causal_allowed=result.causal)
    exclusions = tuple(
        f"{summary.arm}: {count} {reason}" for summary in (a, b) for reason, count in summary.missing if count
    )
    return LearningRecommendation(
        recommendation_id=recommendation_id,
        evidence_observation_ids=evidence,
        hypothesis=hypothesis,
        applicability=CanonicalJsonObject.model_validate(
            {**applicability(result), "summaries": [a.as_json(), b.as_json()]}
        ),
        exclusions=exclusions,
        confidence=float(Decimal(a.present + b.present) / Decimal(a.n + b.n)),
        expected_guardrails=(
            "proposal only; acceptance creates a governed proposal reference and changes nothing else",
            "re-evaluate when any evidence observation is corrected",
        ),
        lineage=lineage,
        expires_at=expires_at,
    )


__all__ = [
    "CAUSAL_DESIGNS",
    "RULE_ID",
    "RULE_VERSION",
    "CausalLanguageError",
    "CohortKey",
    "CohortLeakError",
    "CohortSummary",
    "RuleParams",
    "RuleResult",
    "applicability",
    "check_hypothesis_language",
    "cohort_key",
    "compare_cohorts",
    "hypothesis_text",
    "is_causal_evidence",
    "proposal_key",
    "recommendation_from",
    "single_cohort",
    "summarize",
]
