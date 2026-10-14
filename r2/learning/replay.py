"""Offline replay with a pre-registered protocol and a project-disjoint, then future-time, holdout (spec §9).

Projects go wholly to train or evaluation by a stable hash, so sibling revisions of one project never
split. Evaluation keeps only observations whose window starts after the train cutoff. A protocol freezes
the rule, its parameters, the cohort, the baseline arm, the effect threshold, the window and the
exclusions before any evaluation observation exists; replay refuses an evaluation set that contains an
observation ingested before the protocol was registered.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import LearningObservation
from r2.learning.cohorts import RULE_ID, RULE_VERSION, CohortKey, RuleParams, compare_cohorts


class EvaluationNotPreregisteredError(ValueError):
    """Cohort, baseline, effect, window or exclusions were not locked before results."""

    code = "M8_EVALUATION_NOT_PREREGISTERED"


@dataclass(frozen=True)
class Holdout:
    train: tuple[LearningObservation, ...]
    evaluation: tuple[LearningObservation, ...]
    train_projects: tuple[str, ...]
    evaluation_projects: tuple[str, ...]


def _bucket(project_name: str, salt: str) -> Decimal:
    digest = hashlib.sha256(f"{salt}:{project_name}".encode()).hexdigest()
    return Decimal(int(digest[:12], 16)) / Decimal(16**12)


def split_holdout(
    observations: Sequence[LearningObservation], *, evaluation_share: Decimal, train_cutoff: datetime, salt: str
) -> Holdout:
    """Whole projects go to one side; evaluation keeps only windows starting after ``train_cutoff``."""
    if not Decimal(0) < evaluation_share < Decimal(1):
        raise ValueError("the evaluation share is strictly between 0 and 1")
    projects = sorted({item.lineage.project_name for item in observations})
    evaluation_projects = {name for name in projects if _bucket(name, salt) < evaluation_share}
    train = tuple(
        item
        for item in observations
        if item.lineage.project_name not in evaluation_projects and item.window.ends_at <= train_cutoff
    )
    evaluation = tuple(
        item
        for item in observations
        if item.lineage.project_name in evaluation_projects and item.window.starts_at > train_cutoff
    )
    return Holdout(
        train=train,
        evaluation=evaluation,
        train_projects=tuple(name for name in projects if name not in evaluation_projects),
        evaluation_projects=tuple(sorted(evaluation_projects)),
    )


@dataclass(frozen=True)
class Protocol:
    cohort: CohortKey
    params: RuleParams
    baseline_arm: str
    window_starts_at: datetime
    window_ends_at: datetime
    exclusions: tuple[str, ...]
    registered_at: datetime

    def __post_init__(self) -> None:
        if self.baseline_arm != self.params.arm_a:
            raise ValueError("the baseline arm is the rule's first arm")
        if self.window_starts_at >= self.window_ends_at:
            raise ValueError("the evaluation window must have positive length")

    @property
    def digest(self) -> str:
        return digest_canonical(
            {
                "rule": f"{RULE_ID}@{RULE_VERSION}",
                "cohort": self.cohort.__dict__,
                "params": self.params.__dict__,
                "baseline_arm": self.baseline_arm,
                "window": [self.window_starts_at, self.window_ends_at],
                "exclusions": list(self.exclusions),
                "registered_at": self.registered_at,
            }
        )


@dataclass(frozen=True)
class ReplayReport:
    protocol_digest: str
    train_fired: bool
    train_lift: Decimal | None
    evaluation_fired: bool
    evaluation_lift: Decimal | None
    direction_held: bool
    train_ids: tuple[str, ...]
    evaluation_ids: tuple[str, ...]


def _admit(protocol: Protocol, observations: Sequence[LearningObservation]) -> tuple[LearningObservation, ...]:
    return tuple(
        item
        for item in observations
        if item.source_record_id not in protocol.exclusions
        and protocol.window_starts_at <= item.window.starts_at
        and item.window.ends_at <= protocol.window_ends_at
    )


def replay(protocol: Protocol, holdout: Holdout) -> ReplayReport:
    """Fit on train, check the same direction on evaluation; refuses an unregistered evaluation."""
    evaluation = _admit(protocol, holdout.evaluation)
    if any(item.ingested_at < protocol.registered_at for item in evaluation):
        raise EvaluationNotPreregisteredError("evaluation data existed before the protocol was registered")
    train = _admit(protocol, holdout.train)
    if {item.lineage.project_name for item in train} & {item.lineage.project_name for item in evaluation}:
        raise ValueError("train and evaluation share a project")
    fitted = compare_cohorts(train, protocol.params)
    checked = compare_cohorts(evaluation, protocol.params)
    if fitted.key != protocol.cohort or checked.key != protocol.cohort:
        raise ValueError("replay data is outside the registered cohort")
    held = (
        fitted.fired
        and fitted.relative_lift is not None
        and checked.relative_lift is not None
        and (fitted.relative_lift > 0) == (checked.relative_lift > 0)
        and abs(checked.relative_lift) >= protocol.params.min_relative_lift
    )
    return ReplayReport(
        protocol_digest=protocol.digest,
        train_fired=fitted.fired,
        train_lift=fitted.relative_lift,
        evaluation_fired=checked.fired,
        evaluation_lift=checked.relative_lift,
        direction_held=held,
        train_ids=tuple(sorted(item.observation_id for item in train)),
        evaluation_ids=tuple(sorted(item.observation_id for item in evaluation)),
    )


__all__ = ["EvaluationNotPreregisteredError", "Holdout", "Protocol", "ReplayReport", "replay", "split_holdout"]
