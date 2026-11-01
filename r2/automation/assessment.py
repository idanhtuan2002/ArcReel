"""Combining two qualified model reviews of one final into a verdict; pure, never grants authority.

A final passes only when exactly two completed reviews from distinct, qualified model identities (neither the
writer's) judged the exact subject in the policy language, every creative dimension scored at least 4 by both,
and neither raised a blocking finding. A reviewer failure, a missing or stale review, a wrong language or an
unqualified reviewer blocks; reviewers that disagree on acceptability block for a Human. When both reject, the
earliest repairable finding names the stage and unit to rework; rejection without a repairable finding fails the
run's quality. Nothing is ever waived.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from r2.contracts.automation import AutomationContract, Digest, ExactIdentity, RunStage

CREATIVE_DIMENSIONS = ("story", "visual", "audio", "continuity", "pacing")
PASSING_SCORE = 4
REPAIRABLE_STAGES = (RunStage.SCRIPT_PLAN, RunStage.SCRIPT, RunStage.MEDIA, RunStage.RENDER)
_ORDER = tuple(RunStage)

Score = Annotated[int, Field(strict=True, ge=1, le=5)]


class AssessmentFinding(AutomationContract):
    code: ExactIdentity
    severity: Literal["CRITICAL", "MAJOR", "MINOR"]
    unit_key: ExactIdentity
    repair_stage: RunStage | None = None
    detail: Annotated[str, StringConstraints(max_length=500)] = ""


class ModelAssessment(AutomationContract):
    reviewer_route_digest: Digest
    model_identity: ExactIdentity
    prompt_digest: Digest
    subject_digest: Digest
    evidence_digest: Digest
    outcome: Literal["COMPLETED", "FAILED"]
    language: ExactIdentity | None = None
    scores: dict[str, Score] = Field(default_factory=dict)
    findings: tuple[AssessmentFinding, ...] = ()

    def accepts(self) -> bool:
        return all(self.scores.get(d, 0) >= PASSING_SCORE for d in CREATIVE_DIMENSIONS) and not any(
            f.severity in {"CRITICAL", "MAJOR"} for f in self.findings
        )


class AssessmentVerdict(AutomationContract):
    kind: Literal["PASS", "REWORK", "BLOCK"]
    reason: ExactIdentity | None = None
    repair_stage: RunStage | None = None
    unit_key: ExactIdentity | None = None


def _block(reason: str) -> AssessmentVerdict:
    return AssessmentVerdict(kind="BLOCK", reason=reason)


def combine(
    *,
    assessments: Iterable[ModelAssessment],
    subject_digest: str,
    language: str,
    writer_identities: frozenset[str],
    qualified_identities: frozenset[str],
) -> AssessmentVerdict:
    reviews = tuple(ModelAssessment.model_validate(a) for a in assessments)
    if len(reviews) != 2:
        return _block("ASSESSMENT_MISSING")
    if any(r.outcome != "COMPLETED" for r in reviews):
        return _block("ASSESSOR_FAILED")
    identities = {r.model_identity for r in reviews}
    if len(identities) != 2 or identities & writer_identities:
        return _block("REVIEWER_INDEPENDENCE_MISSING")
    if not identities <= qualified_identities:
        return _block("REVIEWER_NOT_QUALIFIED")
    if any(r.subject_digest != subject_digest for r in reviews):
        return _block("ASSESSMENT_STALE")
    if any(r.language != language for r in reviews):
        return _block("WRONG_LANGUAGE")
    if any(set(CREATIVE_DIMENSIONS) - set(r.scores) for r in reviews):
        return _block("ASSESSMENT_INCOMPLETE")
    verdicts = [r.accepts() for r in reviews]
    if all(verdicts):
        return AssessmentVerdict(kind="PASS")
    if any(verdicts):
        return _block("REVIEWER_DISAGREEMENT")
    repairable = [
        f
        for r in reviews
        for f in r.findings
        if f.severity in {"CRITICAL", "MAJOR"} and f.repair_stage in REPAIRABLE_STAGES
    ]
    if not repairable:
        return _block("FAILED_QUALITY")
    first = min(repairable, key=lambda f: (_ORDER.index(f.repair_stage or RunStage.RENDER), f.unit_key))
    return AssessmentVerdict(kind="REWORK", repair_stage=first.repair_stage, unit_key=first.unit_key)


__all__ = [
    "CREATIVE_DIMENSIONS",
    "PASSING_SCORE",
    "REPAIRABLE_STAGES",
    "AssessmentFinding",
    "AssessmentVerdict",
    "ModelAssessment",
    "combine",
]
