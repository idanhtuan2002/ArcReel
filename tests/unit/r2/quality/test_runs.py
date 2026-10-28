"""Run closure seals complete, re-verified evidence; validity is a recomputed projection."""

from __future__ import annotations

import importlib
from datetime import timedelta
from typing import Any

import pytest

import r2.contracts.quality as q
from r2.quality.digests import compute_digest
from r2.quality.errors import ProfileStaleError, RequiredEvidenceMissingError, SubjectStaleError
from tests.unit.r2.contracts.test_quality import DIGEST, NOW, observation_data, policy_data
from tests.unit.r2.quality.test_quality_digests import valid_subject

RUN_ID = "0199f00d-0000-7000-8000-0000000000ff"


def runs():
    try:
        return importlib.import_module("r2.quality.runs")
    except ModuleNotFoundError:
        pytest.fail("run closure is unavailable")


def human_slot(slot_id: str, **changes: Any) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "kind": "NARRATIVE",
        "assessor_class": "HUMAN",
        "qualification_policy_id": runs().HUMAN_SHOWRUNNER_POLICY_ID,
        "qualification_policy_digest": runs().human_showrunner_policy_digest(),
        "rule_ids": ["review"],
        "allowed_applicability_states": ["PASS", "FAIL", "INDETERMINATE"],
        "producer_conflict_forbidden": True,
        "required_independence_groups": 1,
    } | changes


def technical_slot(**changes: Any) -> dict[str, Any]:
    return {
        "slot_id": "technical",
        "kind": "TECHNICAL",
        "assessor_class": "DETERMINISTIC",
        "qualification_policy_id": "deterministic",
        "qualification_policy_digest": DIGEST,
        "rule_ids": ["probe"],
        "allowed_applicability_states": ["PASS", "FAIL", "INDETERMINATE", "INAPPLICABLE"],
        "producer_conflict_forbidden": True,
        "required_independence_groups": 1,
    } | changes


def requirement(requirement_id: str, slots: list[dict[str, Any]], **changes: Any) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "mode": "ALL",
        "slots": slots,
        "minimum_satisfied_slots": len(slots),
        "disagreement_policy_id": "disagree",
        "disagreement_policy_digest": DIGEST,
        "escalation_requirement_id": None,
    } | changes


def profile(*requirements: dict[str, Any]) -> q.QualityProfileRevision:
    from tests.unit.r2.quality.test_quality_profiles import publication_request, publish

    policy = policy_data()
    policy["assessment_requirements"] = list(requirements) or [
        requirement("technical-required", [technical_slot()]),
        requirement("review-required", [human_slot("human")]),
    ]
    return publish(publication_request(policy=policy))


def admitted(revision, kind: str, req: str, slot: str, status: str = "PASS", **changes: Any):
    data = observation_data(kind)
    data.update(
        requirement_id=req,
        slot_id=slot,
        status=status,
        subject_digest=compute_digest("m10.assessed-subject.v1", valid_subject()),
        observation_id=f"0199f00d-0000-7000-8000-{abs(hash((req, slot, status, kind))) % 10**12:012d}",
    )
    if kind == "TECHNICAL":
        data.update(config_digest=revision.policy.probe_rules[0].config_digest, rule_id="probe")
    else:
        data.update(independence_group="human:actor")
    data.update(changes)
    model = q.TechnicalObservation if kind == "TECHNICAL" else q.NarrativeObservation
    observation = model.model_validate(data)
    assessor = q.AssessorClass.DETERMINISTIC if kind == "TECHNICAL" else q.AssessorClass.HUMAN
    return runs().AdmittedObservation(observation=observation, assessor_class=assessor)


def close(revision, *observations, **kwargs):
    return runs().close_run(revision, valid_subject(), observations, run_id=RUN_ID, completed_at=NOW, **kwargs)


def test_complete_evidence_seals_a_run_with_recomputed_digests() -> None:
    revision = profile()
    technical = admitted(revision, "TECHNICAL", "technical-required", "technical")
    human = admitted(revision, "NARRATIVE", "review-required", "human")
    run = close(revision, technical, human)
    assert set(run.observation_refs) == {technical.observation.observation_id, human.observation.observation_id}
    assert run.subject_digest == compute_digest("m10.assessed-subject.v1", valid_subject())
    assert run.profile_digest == revision.profile_digest
    assert run.requirements_digest == compute_digest(
        "m10.assessment-requirements.v1", revision.policy.assessment_requirements
    )
    assert run.execution_refs == (technical.observation.probe_receipt_ref,)
    assert {result.state for result in run.slot_results} == {"SATISFIED"}
    assert runs().run_digest(run) == runs().run_digest(close(revision, human, technical))


def test_failed_evidence_still_seals_because_sealing_records_completeness() -> None:
    revision = profile()
    run = close(
        revision,
        admitted(revision, "TECHNICAL", "technical-required", "technical", "FAIL"),
        admitted(revision, "NARRATIVE", "review-required", "human"),
    )
    assert {r.slot_id: r.state for r in run.slot_results}["technical"] == "FAILED"


def test_missing_slot_evidence_refuses_sealing() -> None:
    revision = profile()
    with pytest.raises(RequiredEvidenceMissingError):
        close(revision, admitted(revision, "TECHNICAL", "technical-required", "technical"))


@pytest.mark.parametrize(
    "change",
    [
        {"requirement_id": "unknown"},
        {"slot_id": "unknown"},
        {"status": "INAPPLICABLE"},
        {"producer_conflict": True},
    ],
)
def test_unbound_invalid_state_or_conflicted_human_evidence_is_refused(change: dict[str, Any]) -> None:
    revision = profile()
    human = admitted(revision, "NARRATIVE", "review-required", "human", **change)
    with pytest.raises(RequiredEvidenceMissingError):
        close(revision, admitted(revision, "TECHNICAL", "technical-required", "technical"), human)


def test_duplicate_observation_is_refused() -> None:
    revision = profile()
    technical = admitted(revision, "TECHNICAL", "technical-required", "technical")
    with pytest.raises(RequiredEvidenceMissingError):
        close(revision, technical, technical, admitted(revision, "NARRATIVE", "review-required", "human"))


def test_mixed_subject_is_stale_and_changed_tool_config_is_a_stale_profile_binding() -> None:
    revision = profile()
    human = admitted(revision, "NARRATIVE", "review-required", "human")
    with pytest.raises(SubjectStaleError):
        close(
            revision,
            admitted(revision, "TECHNICAL", "technical-required", "technical", subject_digest=DIGEST),
            human,
        )
    with pytest.raises(ProfileStaleError):
        close(
            revision,
            admitted(revision, "TECHNICAL", "technical-required", "technical", config_digest="sha256:" + "b" * 64),
            human,
        )


def test_model_evidence_cannot_satisfy_a_human_slot_and_unqualified_policy_refuses() -> None:
    revision = profile()
    technical = admitted(revision, "TECHNICAL", "technical-required", "technical")
    model = admitted(revision, "NARRATIVE", "review-required", "human")
    model = runs().AdmittedObservation(observation=model.observation, assessor_class=q.AssessorClass.MODEL)
    with pytest.raises(RequiredEvidenceMissingError):
        close(revision, technical, model)
    unqualified = profile(
        requirement("technical-required", [technical_slot()]),
        requirement("review-required", [human_slot("human", qualification_policy_id="anyone")]),
    )
    with pytest.raises(RequiredEvidenceMissingError):
        close(
            unqualified,
            admitted(unqualified, "TECHNICAL", "technical-required", "technical"),
            admitted(unqualified, "NARRATIVE", "review-required", "human"),
        )


def test_factual_slots_cannot_even_be_published() -> None:
    from r2.quality.errors import PrerequisiteNotAcceptedError

    with pytest.raises(PrerequisiteNotAcceptedError):
        profile(requirement("other", [technical_slot(kind="FACTUAL", assessor_class="AUTHORITY", slot_id="x")]))


@pytest.mark.parametrize("kind", ["CONTINUITY", "ACCESSIBILITY"])
def test_slots_without_an_admitted_producer_fail_closed(kind: str) -> None:
    revision = profile(requirement("other", [technical_slot(kind=kind, assessor_class="AUTHORITY", slot_id="x")]))
    with pytest.raises(RequiredEvidenceMissingError):
        close(revision, admitted(revision, "TECHNICAL", "other", "x"))


def test_policy_authorized_technical_inapplicability_is_not_applicable() -> None:
    revision = profile(requirement("technical-required", [technical_slot()]))
    run = close(revision, admitted(revision, "TECHNICAL", "technical-required", "technical", "INAPPLICABLE"))
    assert run.slot_results[0].state == "NOT_APPLICABLE"


def test_insufficient_independence_or_unescalated_disagreement_is_indeterminate() -> None:
    two = profile(requirement("review-required", [human_slot("human", required_independence_groups=2)]))
    run = close(two, admitted(two, "NARRATIVE", "review-required", "human"))
    assert run.slot_results[0].state == "INDETERMINATE"
    pair = profile(requirement("review-required", [human_slot("a"), human_slot("b")]))
    run = close(
        pair,
        admitted(pair, "NARRATIVE", "review-required", "a", "PASS"),
        admitted(pair, "NARRATIVE", "review-required", "b", "FAIL", independence_group="human:other"),
    )
    assert {r.state for r in run.slot_results} == {"INDETERMINATE"}


def test_disagreement_resolved_by_escalation_records_the_escalation_evidence() -> None:
    pair = profile(
        requirement("review-required", [human_slot("a"), human_slot("b")], escalation_requirement_id="escalate"),
        requirement("escalate", [human_slot("arbiter")]),
    )
    arbiter = admitted(pair, "NARRATIVE", "escalate", "arbiter", "FAIL", independence_group="human:arbiter")
    run = close(
        pair,
        admitted(pair, "NARRATIVE", "review-required", "a", "PASS"),
        admitted(pair, "NARRATIVE", "review-required", "b", "FAIL", independence_group="human:other"),
        arbiter,
    )
    results = {r.slot_id: r for r in run.slot_results}
    assert results["a"].state == results["b"].state == "FAILED"
    assert results["a"].escalation_observation_refs == (arbiter.observation.observation_id,)
    no_disagreement = close(
        pair,
        admitted(pair, "NARRATIVE", "review-required", "a"),
        admitted(pair, "NARRATIVE", "review-required", "b", independence_group="human:other"),
    )
    assert {r.slot_id for r in no_disagreement.slot_results} == {"a", "b"}


def test_n_of_m_needs_at_least_the_minimum_evaluated_slots() -> None:
    revision = profile(
        requirement("review-required", [human_slot("a"), human_slot("b")], mode="N_OF_M", minimum_satisfied_slots=1)
    )
    run = close(revision, admitted(revision, "NARRATIVE", "review-required", "a"))
    assert [r.slot_id for r in run.slot_results] == ["a"]
    strict = profile(
        requirement("review-required", [human_slot("a"), human_slot("b")], mode="N_OF_M", minimum_satisfied_slots=2)
    )
    with pytest.raises(RequiredEvidenceMissingError):
        close(strict, admitted(strict, "NARRATIVE", "review-required", "a"))


def test_validity_is_a_projection_with_fixed_precedence() -> None:
    revision = profile()
    observations = [
        admitted(revision, "TECHNICAL", "technical-required", "technical"),
        admitted(revision, "NARRATIVE", "review-required", "human"),
    ]
    run = close(revision, *observations)

    def state(**changes: Any) -> str:
        now = changes.pop("now", NOW)
        inputs = runs().ValidityInputs(
            evidence_intact=changes.get("evidence_intact", True),
            subject_current=changes.get("subject_current", True),
            newer_run=changes.get("newer_run", False),
            newer_profile_reevaluates=changes.get("newer_profile_reevaluates", False),
        )
        return runs().project_validity(run, revision, [o.observation for o in observations], inputs, now=now).state

    assert state() == "CURRENT"
    assert state(now=NOW + timedelta(seconds=61)) == "EXPIRED"
    assert state(newer_run=True, now=NOW + timedelta(seconds=61)) == "SUPERSEDED"
    assert state(newer_profile_reevaluates=True) == "SUPERSEDED"
    assert state(subject_current=False, newer_run=True) == "STALE"
    assert state(evidence_intact=False, subject_current=False) == "INVALIDATED"


def test_one_assessor_cannot_satisfy_several_slots_of_a_requirement() -> None:
    pair = profile(requirement("review-required", [human_slot("a"), human_slot("b")]))
    run = close(
        pair,
        admitted(pair, "NARRATIVE", "review-required", "a"),
        admitted(pair, "NARRATIVE", "review-required", "b"),
    )
    assert {r.state for r in run.slot_results} == {"INDETERMINATE"}


def test_escalation_never_overrides_insufficient_independence() -> None:
    pair = profile(
        requirement(
            "review-required",
            [human_slot("a", required_independence_groups=2), human_slot("b"), human_slot("c")],
            escalation_requirement_id="escalate",
        ),
        requirement("escalate", [human_slot("arbiter")]),
    )
    run = close(
        pair,
        admitted(pair, "NARRATIVE", "review-required", "a", independence_group="human:a"),
        admitted(pair, "NARRATIVE", "review-required", "b", "PASS", independence_group="human:b"),
        admitted(pair, "NARRATIVE", "review-required", "c", "FAIL", independence_group="human:c"),
        admitted(pair, "NARRATIVE", "escalate", "arbiter", "PASS", independence_group="human:arbiter"),
    )
    states = {r.slot_id: r.state for r in run.slot_results}
    assert states["a"] == "INDETERMINATE"
    assert states["b"] == states["c"] == "SATISFIED"


def test_forged_profile_or_subject_cache_is_refused() -> None:
    revision = profile()
    forged = revision.model_copy(update={"profile_digest": "sha256:" + "f" * 64})
    with pytest.raises(RequiredEvidenceMissingError):
        close(
            forged,
            admitted(forged, "TECHNICAL", "technical-required", "technical"),
            admitted(forged, "NARRATIVE", "review-required", "human"),
        )


def test_human_request_scope_must_match_profile_and_subject_scope() -> None:
    from pydantic import ValidationError

    revision = profile()
    body = {
        "user_id": "owner",
        "project_name": "other-project",
        "actor_id": "actor",
        "command_id": "human-1",
        "subject": valid_subject().model_dump(mode="json"),
        "profile": revision.model_dump(mode="json"),
        "requirement_id": "review-required",
        "slot_id": "human",
        "status": "PASS",
        "rubric_id": "rubric",
        "rubric_digest": DIGEST,
        "segment_closure_digest": DIGEST,
        "reviewer_evidence_digest": DIGEST,
        "findings": [],
        "evidence_refs": ["notes"],
        "evidence_digest": DIGEST,
    }
    with pytest.raises(ValidationError):
        runs().HumanObservationRequest.model_validate(body)


def test_a_shared_assessor_does_not_erase_a_concrete_failure() -> None:
    pair = profile(requirement("review-required", [human_slot("a"), human_slot("b")]))
    run = close(
        pair,
        admitted(pair, "NARRATIVE", "review-required", "a", "FAIL"),
        admitted(pair, "NARRATIVE", "review-required", "b", "FAIL"),
    )
    assert {r.state for r in run.slot_results} == {"FAILED"}
