from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from r2.contracts import (
    CanonContent,
    CanonDelta,
    CanonValidationFinding,
    CanonValidationReport,
    Fact,
    RetireFactOperation,
)

RULES = (
    "M5A_REFERENCE_MISSING",
    "M5A_EVENT_CAUSAL_SELF_REFERENCE",
    "M5A_FACT_INTERVAL_INVALID",
    "M5A_FACT_RETIREMENT_INVALID",
    "M5A_FACT_ACTIVE_COLLISION",
)
_RULE_ORDER = {rule_id: index for index, rule_id in enumerate(RULES)}


def intervals_overlap(
    left_from: datetime | None,
    left_until: datetime | None,
    right_from: datetime | None,
    right_until: datetime | None,
) -> bool:
    """Half-open ``[from, until)`` overlap with null infinities; equal adjacent endpoints do not overlap."""
    return _starts_before(left_from, right_until) and _starts_before(right_from, left_until)


def _starts_before(start: datetime | None, end: datetime | None) -> bool:
    if start is None or end is None:
        return True
    return start < end


def _finding(rule_id: str, affected_refs: tuple[str, ...], message: str) -> CanonValidationFinding:
    return CanonValidationFinding(rule_id=rule_id, affected_refs=affected_refs, message=message)


def _reference_missing(candidate: CanonContent) -> Iterator[CanonValidationFinding]:
    entity_ids = set(candidate.entities_by_id)
    event_ids = set(candidate.events_by_id)
    for fact in sorted(candidate.facts_by_id.values(), key=lambda item: item.fact_id):
        if fact.subject_ref not in entity_ids:
            yield _finding(
                "M5A_REFERENCE_MISSING",
                (fact.fact_id, fact.subject_ref),
                f"fact {fact.fact_id} references unknown subject entity {fact.subject_ref}",
            )
        for event_ref in fact.source_event_refs:
            if event_ref not in event_ids:
                yield _finding(
                    "M5A_REFERENCE_MISSING",
                    (fact.fact_id, event_ref),
                    f"fact {fact.fact_id} references unknown source event {event_ref}",
                )
    for event in sorted(candidate.events_by_id.values(), key=lambda item: item.event_id):
        for participant in event.participant_refs:
            if participant not in entity_ids:
                yield _finding(
                    "M5A_REFERENCE_MISSING",
                    (event.event_id, participant),
                    f"event {event.event_id} references unknown participant entity {participant}",
                )
        if event.location_ref is not None and event.location_ref not in entity_ids:
            yield _finding(
                "M5A_REFERENCE_MISSING",
                (event.event_id, event.location_ref),
                f"event {event.event_id} references unknown location entity {event.location_ref}",
            )
        for causal_ref in event.causal_refs:
            if causal_ref not in event_ids:
                yield _finding(
                    "M5A_REFERENCE_MISSING",
                    (event.event_id, causal_ref),
                    f"event {event.event_id} references unknown causal event {causal_ref}",
                )


def _event_causal_self_reference(candidate: CanonContent) -> Iterator[CanonValidationFinding]:
    for event in sorted(candidate.events_by_id.values(), key=lambda item: item.event_id):
        if event.event_id in event.causal_refs:
            yield _finding(
                "M5A_EVENT_CAUSAL_SELF_REFERENCE",
                (event.event_id,),
                f"event {event.event_id} causally references itself",
            )


def _fact_interval_invalid(candidate: CanonContent, delta: CanonDelta) -> Iterator[CanonValidationFinding]:
    retired_targets = {op.target_id for op in delta.operations if isinstance(op, RetireFactOperation)}
    for fact in sorted(candidate.facts_by_id.values(), key=lambda item: item.fact_id):
        if fact.fact_id in retired_targets:
            continue
        if _interval_is_inverted(fact):
            yield _finding(
                "M5A_FACT_INTERVAL_INVALID",
                (fact.fact_id,),
                f"fact {fact.fact_id} effective_until is not after effective_from",
            )


def _fact_retirement_invalid(base: CanonContent, delta: CanonDelta) -> Iterator[CanonValidationFinding]:
    for op in delta.operations:
        if not isinstance(op, RetireFactOperation):
            continue
        base_fact = base.facts_by_id.get(op.target_id)
        if base_fact is None:
            continue
        if base_fact.effective_until is not None:
            yield _finding(
                "M5A_FACT_RETIREMENT_INVALID",
                (op.target_id,),
                f"fact {op.target_id} is already retired in the resolved base",
            )
            continue
        if base_fact.effective_from is not None and op.effective_until <= base_fact.effective_from:
            yield _finding(
                "M5A_FACT_RETIREMENT_INVALID",
                (op.target_id,),
                f"retirement time for fact {op.target_id} is not after its effective_from",
            )


def _fact_active_collision(candidate: CanonContent) -> Iterator[CanonValidationFinding]:
    facts = list(candidate.facts_by_id.values())
    for index, left in enumerate(facts):
        for right in facts[index + 1 :]:
            if (left.subject_ref, left.predicate) != (right.subject_ref, right.predicate):
                continue
            if left.value == right.value:
                continue
            if intervals_overlap(
                left.effective_from, left.effective_until, right.effective_from, right.effective_until
            ):
                yield _finding(
                    "M5A_FACT_ACTIVE_COLLISION",
                    (left.fact_id, right.fact_id),
                    (
                        f"facts {left.fact_id} and {right.fact_id} assign different values to "
                        f"({left.subject_ref}, {left.predicate}) over overlapping intervals"
                    ),
                )


def _interval_is_inverted(fact: Fact) -> bool:
    return (
        fact.effective_from is not None
        and fact.effective_until is not None
        and fact.effective_until <= fact.effective_from
    )


def validate_canon_candidate(
    *, base: CanonContent, delta: CanonDelta, candidate: CanonContent
) -> CanonValidationReport:
    findings: list[CanonValidationFinding] = [
        *_reference_missing(candidate),
        *_event_causal_self_reference(candidate),
        *_fact_interval_invalid(candidate, delta),
        *_fact_retirement_invalid(base, delta),
        *_fact_active_collision(candidate),
    ]
    findings.sort(key=lambda item: (_RULE_ORDER[item.rule_id], item.affected_refs))
    return CanonValidationReport(findings=tuple(findings))
