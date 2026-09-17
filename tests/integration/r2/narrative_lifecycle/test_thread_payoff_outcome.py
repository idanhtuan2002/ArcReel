"""Integration coverage for ``validate_thread_payoff_outcome`` (Task 25, spec §4.3.4):
the pure exact-input validator that proves — or fails to prove — a planned thread
resolution against an ``AcceptedThreadPayoffProof``, the exact ``NarrativeChangeSet`` it
names, and the exact decision ids currently effective at validation time.

Pure-function coverage; no database, no service, no fixtures beyond the shared
factories. Lives alongside the DB-backed adapter suite because both close out the same
Task 25 F9 thread-payoff outcome-proof feature.
"""

from __future__ import annotations

from r2.contracts.narrative_lifecycle import (
    AcceptedThreadPayoffProof,
    NarrativeChangeSet,
    SourceSpan,
    ThreadPayoffEffectKey,
)
from r2.narrative.validation import validate_thread_payoff_outcome
from tests.factories import make_canon_mutation_effect_key, make_narrative_change_set

_THREAD = "thread-1"
_PAYOFF = "payoff-1"
_SPAN = SourceSpan(start=0, end=10)
_DECISION_ID = "dec-1"
_REVIEW_DECISION_ID = "dec-2"


def _payoff_key(*, thread_ref: str = _THREAD, payoff_ref: str = _PAYOFF) -> ThreadPayoffEffectKey:
    return ThreadPayoffEffectKey(thread_ref=thread_ref, payoff_ref=payoff_ref)


def _change_set(
    *, change_set_id: str = "cs-1", span: SourceSpan = _SPAN, key: object | None = None
) -> NarrativeChangeSet:
    return make_narrative_change_set(change_set_id=change_set_id, key=key or _payoff_key(), span=span)


def _proof(
    *,
    thread_ref: str = _THREAD,
    payoff_ref: str = _PAYOFF,
    change_set_id: str = "cs-1",
    revision_acceptance_decision_id: str = _DECISION_ID,
    review_decision_id: str = _REVIEW_DECISION_ID,
    conflict_resolution_decision_ids: tuple[str, ...] = (),
    source_spans: tuple[SourceSpan, ...] = (_SPAN,),
) -> AcceptedThreadPayoffProof:
    return AcceptedThreadPayoffProof(
        thread_ref=thread_ref,
        payoff_ref=payoff_ref,
        revision_id="rev-1",
        revision_acceptance_decision_id=revision_acceptance_decision_id,
        change_set_id=change_set_id,
        review_decision_id=review_decision_id,
        conflict_resolution_decision_ids=conflict_resolution_decision_ids,
        source_spans=source_spans,
    )


def proof_without_accepted_decisions() -> AcceptedThreadPayoffProof:
    return _proof()


CS = _change_set()


def _rule_ids(report) -> list[str]:
    return [finding.rule_id for finding in report.findings]


async def test_structural_payoff_without_effective_decisions_fails_outcome_validation() -> None:
    report = validate_thread_payoff_outcome(
        proof_without_accepted_decisions(), change_set=CS, effective_decisions=set()
    )
    assert "SCENE_EXIT_THREAD_UNMET" in _rule_ids(report)


async def test_accepted_and_currently_effective_proof_passes() -> None:
    report = validate_thread_payoff_outcome(
        _proof(), change_set=CS, effective_decisions={_DECISION_ID, _REVIEW_DECISION_ID}
    )
    assert report.findings == ()


async def test_change_set_missing_thread_payoff_key_entirely_fails() -> None:
    change_set = _change_set(key=make_canon_mutation_effect_key())
    report = validate_thread_payoff_outcome(
        _proof(), change_set=change_set, effective_decisions={_DECISION_ID, _REVIEW_DECISION_ID}
    )
    assert "SCENE_EXIT_THREAD_UNMET" in _rule_ids(report)


async def test_wrong_thread_or_payoff_proof_fails() -> None:
    change_set = _change_set(key=_payoff_key(payoff_ref="payoff-other"))
    report = validate_thread_payoff_outcome(
        _proof(), change_set=change_set, effective_decisions={_DECISION_ID, _REVIEW_DECISION_ID}
    )
    assert "SCENE_EXIT_THREAD_UNMET" in _rule_ids(report)


async def test_wrong_change_set_supplied_fails() -> None:
    change_set = _change_set(change_set_id="cs-other")
    report = validate_thread_payoff_outcome(
        _proof(change_set_id="cs-1"), change_set=change_set, effective_decisions={_DECISION_ID, _REVIEW_DECISION_ID}
    )
    assert "SCENE_EXIT_THREAD_UNMET" in _rule_ids(report)


async def test_uncovered_source_span_fails() -> None:
    proof = _proof(source_spans=(SourceSpan(start=100, end=110),))
    report = validate_thread_payoff_outcome(
        proof, change_set=CS, effective_decisions={_DECISION_ID, _REVIEW_DECISION_ID}
    )
    assert "SCENE_EXIT_THREAD_UNMET" in _rule_ids(report)


async def test_named_conflict_resolution_decision_not_effective_fails() -> None:
    proof = _proof(conflict_resolution_decision_ids=("dec-3",))
    report = validate_thread_payoff_outcome(
        proof, change_set=CS, effective_decisions={_DECISION_ID, _REVIEW_DECISION_ID}
    )
    assert "SCENE_EXIT_THREAD_UNMET" in _rule_ids(report)


async def test_historical_replay_resolves_same_proof_without_asserting_current_authority() -> None:
    """The validator is exact-input and pure: replaying the same proof against a
    decisions set captured at an earlier instant reproduces the same structural result —
    it neither queries nor asserts that those decisions remain live current authority."""
    historical_effective_decisions = {_DECISION_ID, _REVIEW_DECISION_ID}
    report = validate_thread_payoff_outcome(_proof(), change_set=CS, effective_decisions=historical_effective_decisions)
    assert report.findings == ()
