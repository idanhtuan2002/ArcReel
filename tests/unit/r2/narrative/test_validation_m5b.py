from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest

from r2.contracts import (
    AddTemporalRelationOperation,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    Entity,
    EntityType,
    EpistemicProposition,
    EpistemicState,
    Event,
    Fact,
    KnowledgeState,
    NarrativeValidationReport,
    NarrativeValidationSeverity,
    RetireFactOperation,
    TemporalRelation,
    UpdateKnowledgeOperation,
    compute_epistemic_proposition_ref,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.hashing import compute_canon_content_hash, seal_canon_delta
from r2.narrative.validation import NarrativeInvariantValidator, validate_knowledge_interval

AT_09 = datetime(2026, 3, 1, 9, tzinfo=UTC)
AT_10 = datetime(2026, 3, 1, 10, tzinfo=UTC)
AT_11 = datetime(2026, 3, 1, 11, tzinfo=UTC)
AT_12 = datetime(2026, 3, 1, 12, tzinfo=UTC)
AT_14 = datetime(2026, 3, 1, 14, tzinfo=UTC)

RING = compute_epistemic_proposition_ref(subject_ref="obj-ring", predicate="owner", object_or_value="char-b")


def proposition(value: object = "char-b") -> EpistemicProposition:
    return EpistemicProposition(
        proposition_ref=compute_epistemic_proposition_ref(
            subject_ref="obj-ring", predicate="owner", object_or_value=value
        ),
        subject_ref="obj-ring",
        predicate="owner",
        object_or_value=value,
    )


def owner_fact(fact_id: str, value: object, frm: datetime | None, until: datetime | None) -> Fact:
    return Fact(
        fact_id=fact_id,
        subject_ref="obj-ring",
        predicate="owner",
        value=value,
        effective_from=frm,
        effective_until=until,
    )


def knowledge_state(
    state: EpistemicState,
    *,
    frm: datetime = AT_10,
    until: datetime | None = None,
    evidence: Iterable[str] = (),
) -> KnowledgeState:
    return KnowledgeState(
        knowledge_state_id="k-1",
        subject_entity_id="char-a",
        proposition_ref=RING,
        epistemic_state=state,
        effective_from=frm,
        effective_until=until,
        evidence_event_refs=list(evidence),
    )


def rule_ids(report: NarrativeValidationReport) -> list[str]:
    return [finding.rule_id for finding in report.findings]


@pytest.mark.parametrize(
    ("state", "facts", "expected_rule"),
    [
        (EpistemicState.KNOWN, [owner_fact("f-1", "char-b", AT_09, AT_12)], "EPI_TRUTH_INCOMPLETE_COVERAGE"),
        (EpistemicState.FALSE_BELIEF, [owner_fact("f-1", "char-c", AT_09, None)], None),
        (EpistemicState.FALSE_BELIEF, [], "EPI_TRUTH_CONTRADICTION_UNPROVEN"),
    ],
)
def test_truth_is_classified_over_the_complete_state_interval(
    state: EpistemicState, facts: list[Fact], expected_rule: str | None
) -> None:
    report = validate_knowledge_interval(state=knowledge_state(state), supporting_facts=facts)
    observed = report.findings[0].rule_id if report.findings else None
    assert observed == expected_rule


def test_adjacent_facts_jointly_cover_a_known_interval() -> None:
    report = validate_knowledge_interval(
        state=knowledge_state(EpistemicState.KNOWN, frm=AT_10, until=AT_12),
        supporting_facts=[
            owner_fact("f-1", "char-b", AT_09, AT_11),
            owner_fact("f-2", "char-b", AT_11, AT_14),
        ],
    )
    assert report.findings == ()


def test_open_ended_knowledge_requires_open_ended_support() -> None:
    finite = validate_knowledge_interval(
        state=knowledge_state(EpistemicState.KNOWN, frm=AT_10, until=None),
        supporting_facts=[owner_fact("f-1", "char-b", AT_09, AT_14)],
    )
    assert rule_ids(finite) == ["EPI_TRUTH_INCOMPLETE_COVERAGE"]
    open_ended = validate_knowledge_interval(
        state=knowledge_state(EpistemicState.KNOWN, frm=AT_10, until=None),
        supporting_facts=[owner_fact("f-1", "char-b", AT_09, None)],
    )
    assert open_ended.findings == ()


# --- full validate_canon pipeline -------------------------------------------------


def _entities() -> dict[str, Entity]:
    return {
        "char-a": Entity(entity_id="char-a", entity_type=EntityType.CHARACTER, canonical_name="A"),
        "char-b": Entity(entity_id="char-b", entity_type=EntityType.CHARACTER, canonical_name="B"),
        "obj-ring": Entity(entity_id="obj-ring", entity_type=EntityType.OBJECT, canonical_name="Ring"),
    }


def content(
    *,
    events: Iterable[Event] = (),
    facts: Iterable[Fact] = (),
    propositions: Iterable[EpistemicProposition] = (),
    knowledge_states: Iterable[KnowledgeState] = (),
    relations: Iterable[TemporalRelation] = (),
) -> CanonContent:
    return CanonContent(
        entities_by_id=_entities(),
        facts_by_id={fact.fact_id: fact for fact in facts},
        events_by_id={event.event_id: event for event in events},
        epistemic_propositions_by_ref={item.proposition_ref: item for item in propositions},
        knowledge_states_by_id={item.knowledge_state_id: item for item in knowledge_states},
        temporal_relations_by_id={item.temporal_relation_id: item for item in relations},
    )


def resolved(canon: CanonContent) -> ResolvedCanonView:
    return ResolvedCanonView(
        canon_version_id="v-1",
        branch_id="main",
        content_hash=compute_canon_content_hash(canon, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=canon,
    )


def delta(*operations: CanonOperation, author_decision_refs: list[str] | None = None) -> CanonDelta:
    return seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id="delta-1",
            target_branch_id="main",
            base_canon_version_id=None,
            operations=list(operations),
            source_change_set_refs=["s-1"],
            author_decision_refs=author_decision_refs or ["a-1"],
            validation_report_refs=[],
            content_schema_version="r2-canon-schema-v2",
            created_at=AT_09,
            created_by="showrunner",
        )
    )


def update_knowledge(
    *,
    state: EpistemicState,
    evidence: list[str] | None = None,
    bootstrap: str | None = None,
    frm: datetime = AT_10,
) -> UpdateKnowledgeOperation:
    return UpdateKnowledgeOperation(
        operation_id="op-k-1",
        target_id="k-1",
        subject_entity_id="char-a",
        proposition=proposition(),
        epistemic_state=state,
        effective_from=frm,
        evidence_event_refs=evidence or [],
        bootstrap_author_decision_ref=bootstrap,
    )


def test_suspected_state_requires_an_evidence_event() -> None:
    canon = content(
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.SUSPECTED)],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(update_knowledge(state=EpistemicState.SUSPECTED)),
        candidate=resolved(canon),
    )
    assert "EPI_EVIDENCE_SUSPECTED_NEEDS_EVENT" in rule_ids(report)


def test_known_state_needs_exactly_one_of_evidence_or_bootstrap() -> None:
    canon = content(
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN)],
        facts=[owner_fact("f-1", "char-b", AT_09, None)],
    )
    neither = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(update_knowledge(state=EpistemicState.KNOWN)),
        candidate=resolved(canon),
    )
    assert "EPI_EVIDENCE_MISSING" in rule_ids(neither)
    both = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(
            update_knowledge(state=EpistemicState.KNOWN, evidence=["ev-x"], bootstrap="a-1"),
        ),
        candidate=resolved(canon),
    )
    assert "EPI_EVIDENCE_BOOTSTRAP_AND_EVENT" in rule_ids(both)


def test_bootstrap_ref_must_be_listed_in_the_delta_author_decisions() -> None:
    canon = content(
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN)],
        facts=[owner_fact("f-1", "char-b", AT_09, None)],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(
            update_knowledge(state=EpistemicState.KNOWN, bootstrap="decision-unlisted"),
            author_decision_refs=["a-1"],
        ),
        candidate=resolved(canon),
    )
    assert "EPI_EVIDENCE_BOOTSTRAP_UNBOUND" in rule_ids(report)


def test_future_evidence_is_rejected_only_when_provably_later() -> None:
    provable = content(
        events=[
            Event(event_id="ev-late", event_type="SIGHT", participant_refs=["char-a"], temporal_anchor=AT_12),
        ],
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN, frm=AT_10, evidence=["ev-late"])],
        facts=[owner_fact("f-1", "char-b", AT_09, None)],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(update_knowledge(state=EpistemicState.KNOWN, evidence=["ev-late"])),
        candidate=resolved(provable),
    )
    assert "EPI_EVIDENCE_FUTURE" in rule_ids(report)

    incomparable = content(
        events=[Event(event_id="ev-unanchored", event_type="SIGHT", participant_refs=["char-a"])],
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN, frm=AT_10, evidence=["ev-unanchored"])],
        facts=[owner_fact("f-1", "char-b", AT_09, None)],
    )
    ok_report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(update_knowledge(state=EpistemicState.KNOWN, evidence=["ev-unanchored"])),
        candidate=resolved(incomparable),
    )
    assert "EPI_EVIDENCE_FUTURE" not in rule_ids(ok_report)


def test_present_event_backlink_must_be_reciprocal() -> None:
    non_reciprocal = content(
        events=[
            Event(
                event_id="ev-1",
                event_type="SIGHT",
                participant_refs=["char-a"],
                state_effect_refs=["k-1"],
            )
        ],
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN, evidence=[])],
        facts=[owner_fact("f-1", "char-b", AT_09, None)],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(update_knowledge(state=EpistemicState.KNOWN, bootstrap="a-1")),
        candidate=resolved(non_reciprocal),
    )
    assert "EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK" in rule_ids(report)


def test_historical_evidence_event_needs_no_backlink() -> None:
    canon = content(
        events=[Event(event_id="ev-1", event_type="SIGHT", participant_refs=["char-a"], state_effect_refs=[])],
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN, evidence=["ev-1"])],
        facts=[owner_fact("f-1", "char-b", AT_09, None)],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(update_knowledge(state=EpistemicState.KNOWN, evidence=["ev-1"])),
        candidate=resolved(canon),
    )
    assert "EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK" not in rule_ids(report)
    assert "EPI_EVIDENCE_MISSING" not in rule_ids(report)


def test_retiring_a_supporting_fact_without_same_delta_closure_breaks_the_state() -> None:
    supporting = owner_fact("f-1", "char-b", AT_09, None)
    base_canon = content(
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN, frm=AT_10, evidence=["ev-1"])],
        facts=[supporting],
        events=[Event(event_id="ev-1", event_type="SIGHT", participant_refs=["char-a"])],
    )
    retired = supporting.model_copy(update={"effective_until": AT_12})
    candidate_canon = content(
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN, frm=AT_10, evidence=["ev-1"])],
        facts=[retired],
        events=[Event(event_id="ev-1", event_type="SIGHT", participant_refs=["char-a"])],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(base_canon),
        delta=delta(RetireFactOperation(operation_id="op-r", target_id="f-1", effective_until=AT_12)),
        candidate=resolved(candidate_canon),
    )
    assert "EPI_TRUTH_INCOMPLETE_COVERAGE" in rule_ids(report)


def test_findings_are_severity_first_deterministically_sorted() -> None:
    canon = content(
        propositions=[proposition()],
        knowledge_states=[knowledge_state(EpistemicState.KNOWN)],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(update_knowledge(state=EpistemicState.KNOWN)),
        candidate=resolved(canon),
    )
    severities = [finding.severity for finding in report.findings]
    assert severities == sorted(severities, key=lambda value: value.value)
    assert all(finding.severity is NarrativeValidationSeverity.ERROR for finding in report.findings)
    assert not report.ok


def test_temporal_findings_are_folded_into_the_report() -> None:
    canon = content(
        events=[
            Event(event_id="ev-a", event_type="X", participant_refs=["char-a"]),
            Event(event_id="ev-b", event_type="Y", participant_refs=["char-a"]),
        ],
        relations=[
            TemporalRelation(
                temporal_relation_id="r-1", left_event_ref="ev-a", relation="BEFORE", right_event_ref="ev-b"
            ),
            TemporalRelation(
                temporal_relation_id="r-2", left_event_ref="ev-b", relation="BEFORE", right_event_ref="ev-a"
            ),
        ],
    )
    report = NarrativeInvariantValidator().validate_canon(
        base=resolved(content()),
        delta=delta(
            AddTemporalRelationOperation(
                operation_id="op-r-2",
                target_id="r-2",
                temporal_relation=TemporalRelation(
                    temporal_relation_id="r-2", left_event_ref="ev-b", relation="BEFORE", right_event_ref="ev-a"
                ),
            )
        ),
        candidate=resolved(canon),
    )
    assert "TIME_GRAPH_CYCLE" in rule_ids(report)
