from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    AddEntityOperation,
    AddFactOperation,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    Entity,
    EntityType,
    Event,
    Fact,
    RetireFactOperation,
)
from r2.narrative.hashing import seal_canon_delta
from r2.narrative.validation import intervals_overlap, validate_canon_candidate

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 6, 1, tzinfo=UTC)
T3 = datetime(2026, 12, 1, tzinfo=UTC)


def entity(entity_id: str) -> Entity:
    return Entity(entity_id=entity_id, entity_type=EntityType.CHARACTER, canonical_name=entity_id.title(), aliases=[])


def fact(
    fact_id: str,
    *,
    subject: str = "hero",
    predicate: str = "mood",
    value: object = "calm",
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
    source_event_refs: list[str] | None = None,
) -> Fact:
    return Fact(
        fact_id=fact_id,
        subject_ref=subject,
        predicate=predicate,
        value=value,
        effective_from=effective_from,
        effective_until=effective_until,
        source_event_refs=source_event_refs or [],
    )


def content(
    *, entities: list[Entity] | None = None, facts: list[Fact] | None = None, events: list[Event] | None = None
) -> CanonContent:
    return CanonContent(
        entities_by_id={item.entity_id: item for item in (entities or [entity("hero")])},
        facts_by_id={item.fact_id: item for item in (facts or [])},
        events_by_id={item.event_id: item for item in (events or [])},
    )


def _noop_operation() -> AddEntityOperation:
    return AddEntityOperation(
        operation_id="op-noop",
        target_id="noop-entity",
        entity=Entity(entity_id="noop-entity", entity_type=EntityType.OBJECT, canonical_name="Noop", aliases=[]),
    )


def sealed_delta(*operations: CanonOperation) -> CanonDelta:
    return seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id="delta-1",
            target_branch_id="main",
            base_canon_version_id=None,
            operations=list(operations) or [_noop_operation()],
            source_change_set_refs=["s-1"],
            author_decision_refs=["a-1"],
            validation_report_refs=[],
            created_at=NOW,
            created_by="showrunner",
        )
    )


def add_fact_op(fact_model: Fact) -> AddFactOperation:
    return AddFactOperation(operation_id=f"op-{fact_model.fact_id}", target_id=fact_model.fact_id, fact=fact_model)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ((None, T2), (T2, None), False),
        ((None, None), (T1, T2), True),
        ((T1, T3), (T2, None), True),
        ((T1, T2), (T2, T3), False),
    ],
)
def test_half_open_interval_overlap(
    left: tuple[datetime | None, datetime | None],
    right: tuple[datetime | None, datetime | None],
    expected: bool,
) -> None:
    assert intervals_overlap(*left, *right) is expected


def test_overlapping_different_fact_values_are_rejected() -> None:
    red = fact("fact-red", value="red", effective_from=T1, effective_until=T3)
    blue = fact("fact-blue", value="blue", effective_from=T2, effective_until=None)
    candidate = CanonContent(
        entities_by_id={"hero": entity("hero")},
        facts_by_id={"fact-red": red, "fact-blue": blue},
        events_by_id={},
    )
    report = validate_canon_candidate(
        base=content(facts=[red]), delta=sealed_delta(add_fact_op(blue)), candidate=candidate
    )
    assert [(item.rule_id, item.affected_refs) for item in report.findings] == [
        ("M5A_FACT_ACTIVE_COLLISION", ("fact-red", "fact-blue"))
    ]


def test_overlapping_equal_fact_values_are_allowed() -> None:
    a = fact("fact-a", value="red", effective_from=T1, effective_until=T3)
    b = fact("fact-b", value="red", effective_from=T2, effective_until=None)
    candidate = CanonContent(
        entities_by_id={"hero": entity("hero")}, facts_by_id={"fact-a": a, "fact-b": b}, events_by_id={}
    )
    report = validate_canon_candidate(base=content(), delta=sealed_delta(add_fact_op(b)), candidate=candidate)
    assert report.ok is True


def test_missing_references_in_candidate_are_reported() -> None:
    orphan_fact = fact("fact-1", subject="ghost")
    stray_event = Event(event_id="ev-1", event_type="MEET", participant_refs=["nobody"], causal_refs=["ev-missing"])
    candidate = CanonContent(
        entities_by_id={"hero": entity("hero")},
        facts_by_id={"fact-1": orphan_fact},
        events_by_id={"ev-1": stray_event},
    )
    report = validate_canon_candidate(base=content(), delta=sealed_delta(add_fact_op(orphan_fact)), candidate=candidate)
    assert {item.rule_id for item in report.findings} == {"M5A_REFERENCE_MISSING"}
    assert ("fact-1", "ghost") in {item.affected_refs for item in report.findings}


def test_event_cannot_causally_reference_itself() -> None:
    loop = Event(event_id="ev-1", event_type="MEET", participant_refs=["hero"], causal_refs=["ev-1"])
    candidate = CanonContent(entities_by_id={"hero": entity("hero")}, facts_by_id={}, events_by_id={"ev-1": loop})
    report = validate_canon_candidate(base=content(), delta=sealed_delta(), candidate=candidate)
    assert [item.rule_id for item in report.findings] == ["M5A_EVENT_CAUSAL_SELF_REFERENCE"]


def test_fact_with_end_before_start_is_interval_invalid() -> None:
    inverted = fact("fact-1", effective_from=T3, effective_until=T1)
    candidate = content(facts=[inverted])
    report = validate_canon_candidate(base=content(), delta=sealed_delta(add_fact_op(inverted)), candidate=candidate)
    assert [item.rule_id for item in report.findings] == ["M5A_FACT_INTERVAL_INVALID"]


def test_retiring_a_fact_before_its_start_is_reported() -> None:
    open_fact = fact("fact-1", effective_from=T2, effective_until=None)
    retired = open_fact.model_copy(update={"effective_until": T1})
    base = content(facts=[open_fact])
    candidate = content(facts=[retired])
    report = validate_canon_candidate(
        base=base,
        delta=sealed_delta(RetireFactOperation(operation_id="op-r", target_id="fact-1", effective_until=T1)),
        candidate=candidate,
    )
    # The retirement is invalid, and the resulting interval is structurally inverted.
    assert {item.rule_id for item in report.findings} == {
        "M5A_FACT_INTERVAL_INVALID",
        "M5A_FACT_RETIREMENT_INVALID",
    }


def test_retiring_a_fact_absent_from_the_resolved_base_is_reported() -> None:
    added = fact("fact-1", effective_from=T2, effective_until=None)
    retired = added.model_copy(update={"effective_until": T1})
    candidate = content(facts=[retired])
    report = validate_canon_candidate(
        base=content(),
        delta=sealed_delta(
            add_fact_op(added),
            RetireFactOperation(operation_id="op-retire-fact-1", target_id="fact-1", effective_until=T1),
        ),
        candidate=candidate,
    )
    rule_ids = {item.rule_id for item in report.findings}
    assert "M5A_FACT_RETIREMENT_INVALID" in rule_ids
    assert "M5A_FACT_INTERVAL_INVALID" in rule_ids


def test_clean_candidate_yields_empty_report() -> None:
    good_fact = fact("fact-1", effective_from=T1, effective_until=T2)
    candidate = content(facts=[good_fact])
    report = validate_canon_candidate(base=content(), delta=sealed_delta(add_fact_op(good_fact)), candidate=candidate)
    assert report.findings == ()
    assert report.ok is True
