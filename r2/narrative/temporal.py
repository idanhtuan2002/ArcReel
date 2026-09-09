"""Deterministic temporal-relation graph for Canon schema v2.

Simultaneous events are collapsed with union-find into equivalence classes keyed by
their lexicographically smallest member; the ``BEFORE`` graph is then a sorted
adjacency DAG over those class ids. Every traversal and every finding sorts ids so
insertion or dict order can never change the evidence.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum

from pydantic import ConfigDict

from r2.contracts import CanonContent, Event, TemporalRelation, TemporalRelationKind
from r2.contracts.common import NonEmptyStr, R2ContractModel

TEMPORAL_RULE_ORDER: tuple[str, ...] = (
    "TIME_GRAPH_SELF_RELATION",
    "TIME_GRAPH_MISSING_EVENT",
    "TIME_GRAPH_DUPLICATE_NORMALIZED_KEY",
    "TIME_GRAPH_SIMULTANEOUS_BEFORE_CONFLICT",
    "TIME_GRAPH_CYCLE",
    "TIME_GRAPH_ANCHOR_VIOLATION",
)
_RULE_INDEX = {rule_id: index for index, rule_id in enumerate(TEMPORAL_RULE_ORDER)}


class TemporalOrder(StrEnum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"
    SIMULTANEOUS = "SIMULTANEOUS"
    INCOMPARABLE = "INCOMPARABLE"


class TemporalFinding(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_id: NonEmptyStr
    affected_refs: tuple[NonEmptyStr, ...]
    message: NonEmptyStr
    evidence_path: tuple[NonEmptyStr, ...] = ()


class TemporalValidationReport(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    findings: tuple[TemporalFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


def normalized_relation_key(relation: TemporalRelation) -> tuple[str, str, str]:
    """The canonical identity of a relation: ``BEFORE`` keeps direction, ``SIMULTANEOUS`` sorts."""
    left, right = relation.left_event_ref, relation.right_event_ref
    if relation.relation is TemporalRelationKind.SIMULTANEOUS:
        low, high = sorted((left, right))
        return ("SIMULTANEOUS", low, high)
    return ("BEFORE", left, right)


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self._parent: dict[str, str] = {item: item for item in items}

    def find(self, item: str) -> str:
        self._parent.setdefault(item, item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        low, high = sorted((left_root, right_root))
        self._parent[high] = low


class TemporalGraph:
    """A validated temporal graph. ``findings`` is empty only when the graph is sound."""

    def __init__(
        self,
        *,
        class_of: Mapping[str, str],
        adjacency: Mapping[str, frozenset[str]],
        findings: tuple[TemporalFinding, ...],
    ) -> None:
        self._class_of = dict(class_of)
        self._adjacency = {node: frozenset(successors) for node, successors in adjacency.items()}
        self.findings = findings

    @property
    def ok(self) -> bool:
        return not self.findings

    @classmethod
    def from_canon(cls, content: CanonContent) -> TemporalGraph:
        return _build_graph(
            relations=list(content.temporal_relations_by_id.values()),
            events=dict(content.events_by_id),
        )

    def _reachable(self, source: str, target: str) -> bool:
        seen: set[str] = set()
        stack = [source]
        while stack:
            node = stack.pop()
            if node == target:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self._adjacency.get(node, frozenset()))
        return False

    def compare(self, left_event_id: str, right_event_id: str) -> TemporalOrder:
        left_class = self._class_of.get(left_event_id)
        right_class = self._class_of.get(right_event_id)
        if left_class is None or right_class is None:
            return TemporalOrder.INCOMPARABLE
        if left_class == right_class:
            return TemporalOrder.SIMULTANEOUS
        if self._reachable(left_class, right_class):
            return TemporalOrder.BEFORE
        if self._reachable(right_class, left_class):
            return TemporalOrder.AFTER
        return TemporalOrder.INCOMPARABLE

    def proof_path(self, left_event_id: str, right_event_id: str) -> tuple[str, ...]:
        """The lexicographically first shortest ``BEFORE`` path of class ids, or ``()``."""
        left_class = self._class_of.get(left_event_id)
        right_class = self._class_of.get(right_event_id)
        if left_class is None or right_class is None or left_class == right_class:
            return ()
        predecessor: dict[str, str] = {left_class: left_class}
        queue: deque[str] = deque([left_class])
        while queue:
            node = queue.popleft()
            if node == right_class:
                break
            for successor in sorted(self._adjacency.get(node, frozenset())):
                if successor not in predecessor:
                    predecessor[successor] = node
                    queue.append(successor)
        if right_class not in predecessor:
            return ()
        path = [right_class]
        while path[-1] != left_class:
            path.append(predecessor[path[-1]])
        return tuple(reversed(path))


def validate_relations(
    relations: Iterable[TemporalRelation], *, events: Mapping[str, Event] | None = None
) -> TemporalValidationReport:
    graph = _build_graph(relations=list(relations), events=None if events is None else dict(events))
    return TemporalValidationReport(findings=graph.findings)


def _build_graph(*, relations: list[TemporalRelation], events: Mapping[str, Event] | None) -> TemporalGraph:
    findings: dict[str, set[str]] = {}

    def flag(rule_id: str, refs: Iterable[str]) -> None:
        findings.setdefault(rule_id, set()).update(refs)

    endpoints: set[str] = set()
    for relation in relations:
        endpoints.update({relation.left_event_ref, relation.right_event_ref})
        endpoints.update(relation.evidence_event_refs)

    known_event_ids = set(events) if events is not None else set(endpoints)
    anchors: dict[str, datetime] = {}
    if events is not None:
        anchors = {
            event_id: event.temporal_anchor for event_id, event in events.items() if event.temporal_anchor is not None
        }

    if events is not None:
        missing = {event_id for event_id in endpoints if event_id not in known_event_ids}
        if missing:
            flag("TIME_GRAPH_MISSING_EVENT", missing)

    for relation in relations:
        if relation.left_event_ref == relation.right_event_ref:
            flag("TIME_GRAPH_SELF_RELATION", (relation.temporal_relation_id, relation.left_event_ref))

    keys: dict[tuple[str, str, str], set[str]] = {}
    for relation in relations:
        keys.setdefault(normalized_relation_key(relation), set()).add(relation.temporal_relation_id)
    for relation_ids in keys.values():
        if len(relation_ids) > 1:
            flag("TIME_GRAPH_DUPLICATE_NORMALIZED_KEY", relation_ids)

    union_find = _UnionFind(known_event_ids | endpoints)
    for relation in relations:
        if (
            relation.relation is TemporalRelationKind.SIMULTANEOUS
            and relation.left_event_ref != relation.right_event_ref
        ):
            union_find.union(relation.left_event_ref, relation.right_event_ref)

    class_of = {event_id: union_find.find(event_id) for event_id in known_event_ids | endpoints}

    adjacency: dict[str, set[str]] = {node: set() for node in class_of.values()}
    for relation in relations:
        if relation.relation is not TemporalRelationKind.BEFORE:
            continue
        if relation.left_event_ref == relation.right_event_ref:
            continue
        left_class = class_of[relation.left_event_ref]
        right_class = class_of[relation.right_event_ref]
        if left_class == right_class:
            flag(
                "TIME_GRAPH_SIMULTANEOUS_BEFORE_CONFLICT",
                (relation.left_event_ref, relation.right_event_ref),
            )
            continue
        adjacency[left_class].add(right_class)

    cycle_nodes = _cycle_nodes(adjacency)
    if cycle_nodes:
        flag("TIME_GRAPH_CYCLE", cycle_nodes)
    else:
        flag("TIME_GRAPH_ANCHOR_VIOLATION", _anchor_violations(relations, class_of, adjacency, anchors))

    ordered = tuple(
        TemporalFinding(
            rule_id=rule_id,
            affected_refs=tuple(sorted(findings[rule_id])),
            message=_MESSAGES[rule_id],
        )
        for rule_id in TEMPORAL_RULE_ORDER
        if findings.get(rule_id)
    )
    return TemporalGraph(
        class_of=class_of,
        adjacency={node: frozenset(successors) for node, successors in adjacency.items()},
        findings=ordered,
    )


_MESSAGES = {
    "TIME_GRAPH_SELF_RELATION": "a temporal relation names the same event on both sides",
    "TIME_GRAPH_MISSING_EVENT": "a temporal relation references an event absent from Canon",
    "TIME_GRAPH_DUPLICATE_NORMALIZED_KEY": "one normalized temporal relation is asserted under two ids",
    "TIME_GRAPH_SIMULTANEOUS_BEFORE_CONFLICT": "a BEFORE edge lies inside one simultaneous class",
    "TIME_GRAPH_CYCLE": "the BEFORE graph over simultaneous classes contains a cycle",
    "TIME_GRAPH_ANCHOR_VIOLATION": "anchored event times contradict a reachable BEFORE edge or a simultaneous class",
}


def _cycle_nodes(adjacency: Mapping[str, set[str]]) -> set[str]:
    in_degree = dict.fromkeys(adjacency, 0)
    for successors in adjacency.values():
        for successor in successors:
            in_degree[successor] = in_degree.get(successor, 0) + 1
    queue = deque(sorted(node for node, degree in in_degree.items() if degree == 0))
    processed = 0
    while queue:
        node = queue.popleft()
        processed += 1
        for successor in sorted(adjacency.get(node, set())):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)
    if processed == len(in_degree):
        return set()
    return {node for node, degree in in_degree.items() if degree > 0}


def _anchor_violations(
    relations: list[TemporalRelation],
    class_of: Mapping[str, str],
    adjacency: Mapping[str, set[str]],
    anchors: Mapping[str, datetime],
) -> set[str]:
    violations: set[str] = set()

    class_members: dict[str, set[str]] = {}
    for event_id, class_id in class_of.items():
        class_members.setdefault(class_id, set()).add(event_id)
    class_anchor: dict[str, datetime] = {}
    for class_id, members in class_members.items():
        member_anchors = {anchors[member] for member in members if member in anchors}
        if len(member_anchors) > 1:
            violations.update(member for member in members if member in anchors)
        elif member_anchors:
            class_anchor[class_id] = next(iter(member_anchors))

    nodes = sorted(adjacency)
    for source in nodes:
        for target in nodes:
            if source == target or not _reaches(adjacency, source, target):
                continue
            if source in class_anchor and target in class_anchor and class_anchor[source] >= class_anchor[target]:
                violations.update(member for member in class_members[source] if member in anchors)
                violations.update(member for member in class_members[target] if member in anchors)
    return violations


def _reaches(adjacency: Mapping[str, set[str]], source: str, target: str) -> bool:
    seen: set[str] = set()
    stack = [source]
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, set()))
    return False
