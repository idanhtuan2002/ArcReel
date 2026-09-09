from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from r2.contracts import CanonContent, Event, TemporalRelation
from r2.narrative.temporal import (
    TemporalFinding,
    TemporalGraph,
    TemporalOrder,
    normalized_relation_key,
    validate_relations,
)

T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 1, 2, tzinfo=UTC)
T3 = datetime(2026, 1, 3, tzinfo=UTC)


def _event(event_id: str, anchor: datetime | None = None) -> Event:
    return Event(event_id=event_id, event_type="MOMENT", participant_refs=[], temporal_anchor=anchor)


def before(left: str, right: str, *, rel_id: str | None = None) -> TemporalRelation:
    return TemporalRelation(
        temporal_relation_id=rel_id or f"r-{left}-{right}",
        left_event_ref=left,
        relation="BEFORE",
        right_event_ref=right,
    )


def simultaneous(left: str, right: str, *, rel_id: str | None = None) -> TemporalRelation:
    return TemporalRelation(
        temporal_relation_id=rel_id or f"r-{min(left, right)}-{max(left, right)}",
        left_event_ref=left,
        relation="SIMULTANEOUS",
        right_event_ref=right,
    )


def canon_with(*relations: TemporalRelation, anchors: Mapping[str, datetime] | None = None) -> CanonContent:
    anchors = anchors or {}
    event_ids: set[str] = set()
    for relation in relations:
        event_ids.update({relation.left_event_ref, relation.right_event_ref})
        event_ids.update(relation.evidence_event_refs)
    events = {event_id: _event(event_id, anchors.get(event_id)) for event_id in sorted(event_ids)}
    return CanonContent(
        entities_by_id={},
        facts_by_id={},
        events_by_id=events,
        temporal_relations_by_id={relation.temporal_relation_id: relation for relation in relations},
    )


def rule_ids(findings: Iterable[TemporalFinding]) -> list[str]:
    return [finding.rule_id for finding in findings]


def test_normalized_key_canonicalizes_simultaneous_and_keeps_before_direction() -> None:
    assert normalized_relation_key(simultaneous("e-b", "e-a")) == ("SIMULTANEOUS", "e-a", "e-b")
    assert normalized_relation_key(simultaneous("e-a", "e-b")) == ("SIMULTANEOUS", "e-a", "e-b")
    assert normalized_relation_key(before("e-b", "e-a")) == ("BEFORE", "e-b", "e-a")


def test_simultaneous_classes_are_collapsed_before_cycle_detection() -> None:
    graph = TemporalGraph.from_canon(canon_with(simultaneous("e-a", "e-b"), before("e-b", "e-c"), before("e-c", "e-a")))
    assert rule_ids(graph.findings) == ["TIME_GRAPH_CYCLE"]


def test_direct_and_transitive_before_cycles_are_rejected() -> None:
    direct = validate_relations([before("e-a", "e-b"), before("e-b", "e-a")])
    assert rule_ids(direct.findings) == ["TIME_GRAPH_CYCLE"]
    transitive = validate_relations([before("e-a", "e-b"), before("e-b", "e-c"), before("e-c", "e-a")])
    assert rule_ids(transitive.findings) == ["TIME_GRAPH_CYCLE"]


def test_duplicate_normalized_relation_keys_under_different_ids_fail() -> None:
    report = validate_relations([simultaneous("e-b", "e-a", rel_id="r-1"), simultaneous("e-a", "e-b", rel_id="r-2")])
    assert rule_ids(report.findings) == ["TIME_GRAPH_DUPLICATE_NORMALIZED_KEY"]


def test_self_relation_is_rejected() -> None:
    report = validate_relations([before("e-a", "e-a")])
    assert rule_ids(report.findings) == ["TIME_GRAPH_SELF_RELATION"]


def test_relation_referencing_an_unknown_event_is_rejected() -> None:
    report = validate_relations([before("e-a", "e-ghost")], events={"e-a": _event("e-a")})
    assert rule_ids(report.findings) == ["TIME_GRAPH_MISSING_EVENT"]


def test_before_inside_one_simultaneous_class_conflicts_without_a_spurious_cycle() -> None:
    report = validate_relations([simultaneous("e-a", "e-b"), before("e-a", "e-b")])
    assert rule_ids(report.findings) == ["TIME_GRAPH_SIMULTANEOUS_BEFORE_CONFLICT"]


def test_anchored_events_must_respect_a_reachable_before_edge() -> None:
    report = validate_relations(
        [before("e-a", "e-b"), before("e-b", "e-c")],
        events={"e-a": _event("e-a", T3), "e-b": _event("e-b", T2), "e-c": _event("e-c", T1)},
    )
    assert rule_ids(report.findings) == ["TIME_GRAPH_ANCHOR_VIOLATION"]


def test_simultaneous_class_with_conflicting_anchors_is_rejected() -> None:
    report = validate_relations(
        [simultaneous("e-a", "e-b")],
        events={"e-a": _event("e-a", T1), "e-b": _event("e-b", T2)},
    )
    assert rule_ids(report.findings) == ["TIME_GRAPH_ANCHOR_VIOLATION"]


def test_reachable_events_compare_before_after_and_expose_a_proof_path() -> None:
    graph = TemporalGraph.from_canon(canon_with(before("e-a", "e-b"), before("e-b", "e-c")))
    assert graph.ok
    assert graph.compare("e-a", "e-c") is TemporalOrder.BEFORE
    assert graph.compare("e-c", "e-a") is TemporalOrder.AFTER
    assert graph.proof_path("e-a", "e-c") == ("e-a", "e-b", "e-c")


def test_proof_path_is_the_lexicographically_first_shortest_path() -> None:
    graph = TemporalGraph.from_canon(
        canon_with(before("e-a", "e-b"), before("e-a", "e-c"), before("e-b", "e-d"), before("e-c", "e-d"))
    )
    assert graph.proof_path("e-a", "e-d") == ("e-a", "e-b", "e-d")


def test_unrelated_events_are_incomparable_with_no_proof_path() -> None:
    graph = TemporalGraph.from_canon(canon_with(before("e-a", "e-b"), simultaneous("e-c", "e-d")))
    assert graph.compare("e-a", "e-c") is TemporalOrder.INCOMPARABLE
    assert graph.proof_path("e-a", "e-c") == ()


def test_members_of_one_simultaneous_class_compare_simultaneous() -> None:
    graph = TemporalGraph.from_canon(canon_with(simultaneous("e-a", "e-b")))
    assert graph.compare("e-a", "e-b") is TemporalOrder.SIMULTANEOUS
