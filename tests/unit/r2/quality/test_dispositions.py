"""Disposition admissibility follows the sealed run; readiness is recomputed, never stored."""

from __future__ import annotations

import importlib
from datetime import timedelta
from typing import Any

import pytest

import r2.contracts.quality as q
from r2.quality.errors import DispositionStaleError, DispositionUnauthorizedError, WaiverForbiddenError
from tests.unit.r2.contracts.test_quality import DIGEST, NOW
from tests.unit.r2.quality.test_runs import admitted, close, human_slot, profile, requirement, technical_slot


def rules():
    try:
        return importlib.import_module("r2.quality.dispositions")
    except ModuleNotFoundError:
        pytest.fail("disposition rules are unavailable")


def sealed(technical: str = "PASS", human: str = "PASS"):
    revision = profile(
        requirement("technical-required", [technical_slot()]),
        requirement("review-required", [human_slot("human")]),
    )
    run = close(
        revision,
        admitted(revision, "TECHNICAL", "technical-required", "technical", technical),
        admitted(revision, "NARRATIVE", "review-required", "human", human),
    )
    return revision, run


def subject(run, decision: str, *, waivers: list[dict[str, Any]] | None = None, ttl: timedelta = timedelta(hours=1)):
    return q.DispositionSubject.model_validate(
        {
            "user_id": "owner",
            "project_name": "project",
            "actor_id": "actor",
            "subject_digest": run.subject_digest,
            "quality_run_id": run.run_id,
            "quality_run_digest": DIGEST,
            "profile_id": run.profile_id,
            "profile_revision": run.profile_revision,
            "profile_digest": run.profile_digest,
            "decision": decision,
            "waiver_bindings": waivers or [],
            "reason": "reviewed",
            "requested_expires_at": (NOW + ttl).isoformat(),
            "expected_disposition_version": 0,
        }
    )


def waiver(scope: str = "technical-required:technical", rule_id: str = "probe") -> dict[str, Any]:
    return {"rule_id": rule_id, "finding_id": None, "scope": scope, "justification": "accepted for pilot"}


def test_pass_requires_every_requirement_met() -> None:
    revision, run = sealed()
    rules().evaluate_decision(revision, run, subject(run, "PASS"), now=NOW)
    revision, failed = sealed(technical="FAIL")
    with pytest.raises(DispositionUnauthorizedError):
        rules().evaluate_decision(revision, failed, subject(failed, "PASS"), now=NOW)
    assert [slot for _, slot, _ in rules().unmet_slots(revision, failed)] == ["technical"]


def test_rework_is_always_admissible_over_a_sealed_run() -> None:
    revision, run = sealed(technical="FAIL", human="INDETERMINATE")
    rules().evaluate_decision(revision, run, subject(run, "REWORK"), now=NOW)


def test_waive_covers_exactly_the_failed_waiverable_slots() -> None:
    revision = profile(
        requirement("technical-required", [technical_slot()]),
        requirement("review-required", [human_slot("human")]),
    )
    policy = revision.policy.model_dump(mode="json")
    policy["disposition_rule"]["waiverable_rule_ids"] = ["probe", "review"]
    from tests.unit.r2.quality.test_quality_profiles import publication_request, publish

    revision = publish(publication_request(policy=policy))
    run = close(
        revision,
        admitted(revision, "TECHNICAL", "technical-required", "technical", "FAIL"),
        admitted(revision, "NARRATIVE", "review-required", "human"),
    )
    rules().evaluate_decision(revision, run, subject(run, "WAIVE", waivers=[waiver()]), now=NOW)
    for bad in (
        [waiver(scope="review-required:human", rule_id="review")],
        [waiver(), waiver(scope="review-required:human", rule_id="review")],
        [waiver(rule_id="review")],
    ):
        with pytest.raises(WaiverForbiddenError):
            rules().evaluate_decision(revision, run, subject(run, "WAIVE", waivers=bad), now=NOW)


def test_rules_outside_the_waiverable_set_and_incomplete_evidence_cannot_be_waived() -> None:
    revision, failed = sealed(technical="FAIL")
    with pytest.raises(WaiverForbiddenError):
        rules().evaluate_decision(revision, failed, subject(failed, "WAIVE", waivers=[waiver()]), now=NOW)
    revision, incomplete = sealed(human="INDETERMINATE")
    with pytest.raises(WaiverForbiddenError):
        rules().evaluate_decision(
            revision,
            incomplete,
            subject(incomplete, "WAIVE", waivers=[waiver(scope="review-required:human", rule_id="review")]),
            now=NOW,
        )
    revision, clean = sealed()
    with pytest.raises(WaiverForbiddenError):
        rules().evaluate_decision(
            revision,
            clean,
            subject(clean, "WAIVE", waivers=[waiver(scope="review-required:human", rule_id="review")]),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("decision", "ttl", "error"),
    [
        ("PASS", timedelta(seconds=0), DispositionStaleError),
        ("PASS", timedelta(days=7, seconds=1), WaiverForbiddenError),
        ("REWORK", timedelta(days=8), WaiverForbiddenError),
    ],
)
def test_expiry_is_mandatory_and_bounded_on_the_supplied_database_time(decision: str, ttl: timedelta, error) -> None:
    revision, run = sealed()
    data = subject(run, decision).model_dump(mode="json") | {"requested_expires_at": (NOW + ttl).isoformat()}
    with pytest.raises(error):
        rules().evaluate_decision(revision, run, q.DispositionSubject.model_validate(data), now=NOW)


def test_waiver_ttl_is_bounded_by_the_profile_waiver_limit() -> None:
    revision = profile(requirement("technical-required", [technical_slot()]))
    policy = revision.policy.model_dump(mode="json")
    policy["disposition_rule"].update(waiverable_rule_ids=["probe"], max_waiver_ttl_seconds=3600)
    from tests.unit.r2.quality.test_quality_profiles import publication_request, publish

    revision = publish(publication_request(policy=policy))
    run = close(revision, admitted(revision, "TECHNICAL", "technical-required", "technical", "FAIL"))
    with pytest.raises(WaiverForbiddenError):
        rules().evaluate_decision(
            revision, run, subject(run, "WAIVE", waivers=[waiver()], ttl=timedelta(hours=2)), now=NOW
        )


def disposition(run, decision: str, *, expires: timedelta = timedelta(hours=1), waivers=()) -> q.QualityDisposition:
    return q.QualityDisposition.model_validate(
        {
            "disposition_id": "0199f00d-0000-7000-8000-0000000000d1",
            "subject_digest": run.subject_digest,
            "quality_run_id": run.run_id,
            "quality_run_digest": DIGEST,
            "profile_digest": run.profile_digest,
            "decision": decision,
            "waiver_bindings": list(waivers),
            "issuer_id": "actor",
            "custodian_authorization_id": "authorization",
            "custodian_policy_id": "policy",
            "custodian_policy_version": "1",
            "custodian_evidence_digest": DIGEST,
            "custodian_admitted_at": NOW.isoformat(),
            "reason": "reviewed",
            "issued_at": NOW.isoformat(),
            "expires_at": (NOW + expires).isoformat(),
            "supersedes_disposition_id": None,
            "profile_id": run.profile_id,
            "profile_revision": run.profile_revision,
        }
    )


def test_readiness_is_ready_only_for_a_current_unexpired_pass_on_the_head_run() -> None:
    revision, run = sealed()
    ready = rules().project_readiness(
        disposition(run, "PASS"), revision, run, run_state="CURRENT", run_is_head=True, now=NOW
    )
    assert (ready.state, ready.reasons) == ("READY", ())
    for kwargs, reason in (
        ({"run_state": "STALE", "run_is_head": True, "now": NOW}, "RUN_STALE"),
        ({"run_state": "CURRENT", "run_is_head": False, "now": NOW}, "NEWER_RUN"),
        ({"run_state": "CURRENT", "run_is_head": True, "now": NOW + timedelta(hours=2)}, "DISPOSITION_EXPIRED"),
    ):
        projected = rules().project_readiness(disposition(run, "PASS"), revision, run, **kwargs)
        assert projected.state == "NOT_READY"
        assert reason in projected.reasons
    assert rules().project_readiness(None, revision, run, run_state="CURRENT", run_is_head=True, now=NOW).reasons == (
        "NO_DISPOSITION",
    )


def test_rework_is_not_ready_and_routes_the_unmet_slots() -> None:
    revision, run = sealed(technical="FAIL")
    projected = rules().project_readiness(
        disposition(run, "REWORK"), revision, run, run_state="CURRENT", run_is_head=True, now=NOW
    )
    assert projected.state == "NOT_READY"
    assert projected.repair_slots == (("technical-required", "technical"),)
