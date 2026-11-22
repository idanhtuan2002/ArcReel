from __future__ import annotations

import pytest

from r2.automation.assessment import AssessmentFinding, ModelAssessment, combine
from r2.contracts.automation import RunStage

SUBJECT = "sha256:" + "1" * 64
GOOD = dict.fromkeys(("story", "visual", "audio", "continuity", "pacing"), 4)


def _review(identity: str, **changes) -> ModelAssessment:
    return ModelAssessment.model_validate(
        {
            "reviewer_route_digest": "sha256:" + "2" * 64,
            "model_identity": identity,
            "prompt_digest": "sha256:" + "3" * 64,
            "subject_digest": SUBJECT,
            "evidence_digest": "sha256:" + "4" * 64,
            "outcome": "COMPLETED",
            "language": "vi",
            "scores": GOOD,
            **changes,
        }
    )


def _combine(*reviews, writers=frozenset({"writer"}), reviewers=frozenset({"a", "b"})):
    return combine(
        assessments=reviews,
        subject_digest=SUBJECT,
        language="vi",
        writer_identities=writers,
        reviewer_identities=reviewers,
    )


def test_two_configured_accepting_reviews_pass():
    assert _combine(_review("a"), _review("b")).kind == "PASS"


@pytest.mark.parametrize(
    ("reviews", "reason"),
    [
        ((_review("a"),), "ASSESSMENT_MISSING"),
        ((_review("a"), _review("b", outcome="FAILED")), "ASSESSOR_FAILED"),
        ((_review("a"), _review("a")), "REVIEWER_INDEPENDENCE_MISSING"),
        ((_review("a"), _review("writer")), "REVIEWER_INDEPENDENCE_MISSING"),
        ((_review("a"), _review("c")), "REVIEWER_NOT_CONFIGURED"),
        ((_review("a"), _review("b", subject_digest="sha256:" + "9" * 64)), "ASSESSMENT_STALE"),
        ((_review("a"), _review("b", language="zh")), "WRONG_LANGUAGE"),
        ((_review("a"), _review("b", scores={"story": 5})), "ASSESSMENT_INCOMPLETE"),
        ((_review("a"), _review("b", scores={**GOOD, "audio": 3})), "REVIEWER_DISAGREEMENT"),
    ],
)
def test_reviewer_exception_never_passes_quality(reviews, reason):
    verdict = _combine(*reviews)
    assert (verdict.kind, verdict.reason) == ("BLOCK", reason)


def test_both_rejecting_rework_the_earliest_repairable_unit():
    media = AssessmentFinding(code="AUDIO_DRIFT", severity="MAJOR", unit_key="episode:1", repair_stage=RunStage.MEDIA)
    script = AssessmentFinding(
        code="PLOT_HOLE", severity="CRITICAL", unit_key="episode:1", repair_stage=RunStage.SCRIPT
    )
    verdict = _combine(_review("a", findings=(media,)), _review("b", findings=(script,)))
    assert (verdict.kind, verdict.repair_stage, verdict.unit_key) == ("REWORK", RunStage.SCRIPT, "episode:1")


def test_critical_rejection_without_a_repair_target_fails_and_is_never_waived():
    critical = AssessmentFinding(code="UNSAFE", severity="CRITICAL", unit_key="episode:1")
    verdict = _combine(_review("a", findings=(critical,)), _review("b", findings=(critical,)))
    assert (verdict.kind, verdict.reason) == ("BLOCK", "FAILED_QUALITY")


def test_a_configured_reviewer_is_attested_by_its_model_route_and_method():
    from r2.automation.assessment import configured_reviewer_digest

    base = {"model_identity": "a", "config_digest": "sha256:" + "5" * 64, "prompt_digest": "sha256:" + "6" * 64}
    digest = configured_reviewer_digest(**base)

    assert digest == configured_reviewer_digest(**base)
    for field in base:
        assert configured_reviewer_digest(**{**base, field: base[field] + "x"}) != digest
