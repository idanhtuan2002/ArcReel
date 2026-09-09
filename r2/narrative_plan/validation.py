"""Pure NarrativePlan hierarchy validation and deterministic scene-version identity.

No repositories, clocks, providers, or write methods. Scene identity is enforced
against immutable plan history; approved content is never silently renumbered.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ConfigDict

from r2.contracts import (
    NarrativeValidationFinding,
    NarrativeValidationReport,
    NarrativeValidationSeverity,
)
from r2.contracts.common import R2ContractModel
from r2.contracts.narrative_plan import NarrativePlanContent, NarrativePlanNode, SceneContract

from .errors import NarrativePlanIdentityConflictError

PLAN_HIERARCHY_RULE_ORDER: tuple[str, ...] = (
    "PLAN_HIERARCHY_DUPLICATE_NODE_ID",
    "PLAN_HIERARCHY_MISSING_PARENT",
    "PLAN_HIERARCHY_ILLEGAL_PARENT",
    "PLAN_HIERARCHY_MULTIPLE_PARENTS",
    "PLAN_HIERARCHY_MISSING_CHILD",
    "PLAN_HIERARCHY_CHILD_ASYMMETRY",
    "PLAN_HIERARCHY_CYCLE",
    "PLAN_HIERARCHY_DUPLICATE_SEQUENCE_INDEX",
)
_RULE_INDEX = {rule_id: index for index, rule_id in enumerate(PLAN_HIERARCHY_RULE_ORDER)}
_KIND_RANK = {"VOLUME": 3, "EPISODE": 2, "ARC": 1, "CHAPTER": 0}


class SceneVersionCheck(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ok: bool
    version: int


def validate_scene_version(*, previous: SceneContract, proposed: SceneContract) -> SceneVersionCheck:
    """Prove ``proposed`` legally succeeds ``previous`` for the same ``scene_contract_id``."""
    if proposed.scene_contract_id != previous.scene_contract_id:
        raise NarrativePlanIdentityConflictError(
            f"scene {proposed.scene_contract_id!r} is not a revision of {previous.scene_contract_id!r}"
        )
    unchanged = proposed.semantic_hash == previous.semantic_hash
    if unchanged:
        if proposed.version != previous.version:
            raise NarrativePlanIdentityConflictError(
                f"byte-identical scene {proposed.scene_contract_id!r} must retain version {previous.version}"
            )
        return SceneVersionCheck(ok=True, version=proposed.version)
    if proposed.version != previous.version + 1:
        raise NarrativePlanIdentityConflictError(
            f"changed scene {proposed.scene_contract_id!r} must be version {previous.version + 1}, "
            f"got {proposed.version}"
        )
    return SceneVersionCheck(ok=True, version=proposed.version)


def next_scene_version(*, history: Sequence[SceneContract], semantic_hash: str) -> int:
    """The version a scene with ``semantic_hash`` takes: an existing match keeps its version;
    otherwise one past the greatest historical version."""
    for scene in history:
        if scene.semantic_hash == semantic_hash:
            return scene.version
    if not history:
        return 1
    return max(scene.version for scene in history) + 1


def _finding(rule_id: str, refs: tuple[str, ...], message: str) -> NarrativeValidationFinding:
    return NarrativeValidationFinding(
        rule_id=rule_id,
        severity=NarrativeValidationSeverity.ERROR,
        affected_refs=refs,
        message=message,
    )


def validate_plan_hierarchy(content: NarrativePlanContent) -> NarrativeValidationReport:
    nodes: list[NarrativePlanNode] = [
        *content.volume_plans,
        *content.episode_plans,
        *content.arc_plans,
        *content.chapter_plans,
    ]
    findings: list[NarrativeValidationFinding] = []
    by_id: dict[str, NarrativePlanNode] = {}
    for node in nodes:
        if node.node_id in by_id:
            findings.append(
                _finding(
                    "PLAN_HIERARCHY_DUPLICATE_NODE_ID",
                    (node.node_id,),
                    f"plan node id {node.node_id!r} appears more than once",
                )
            )
        by_id[node.node_id] = node

    parents_seen: dict[str, list[str]] = {}
    for node in nodes:
        if node.parent_id is None:
            continue
        parent = by_id.get(node.parent_id)
        if parent is None:
            findings.append(
                _finding(
                    "PLAN_HIERARCHY_MISSING_PARENT",
                    (node.node_id, node.parent_id),
                    f"plan node {node.node_id!r} names an unknown parent {node.parent_id!r}",
                )
            )
            continue
        if _KIND_RANK[parent.node_kind] <= _KIND_RANK[node.node_kind]:
            findings.append(
                _finding(
                    "PLAN_HIERARCHY_ILLEGAL_PARENT",
                    (node.node_id, parent.node_id),
                    f"{node.node_kind} {node.node_id!r} cannot descend from {parent.node_kind} {parent.node_id!r}",
                )
            )
        parents_seen.setdefault(node.node_id, []).append(node.parent_id)

    for node in nodes:
        for child_id in node.child_refs:
            child = by_id.get(child_id)
            if child is None:
                findings.append(
                    _finding(
                        "PLAN_HIERARCHY_MISSING_CHILD",
                        (node.node_id, child_id),
                        f"plan node {node.node_id!r} names an unknown child {child_id!r}",
                    )
                )
                continue
            if child.parent_id != node.node_id:
                findings.append(
                    _finding(
                        "PLAN_HIERARCHY_CHILD_ASYMMETRY",
                        (node.node_id, child_id),
                        f"plan node {node.node_id!r} lists child {child_id!r} which does not name it as parent",
                    )
                )

    for node in nodes:
        declared_children = set(node.child_refs)
        findings.extend(
            _finding(
                "PLAN_HIERARCHY_CHILD_ASYMMETRY",
                (node.node_id, other.node_id),
                f"plan node {other.node_id!r} names parent {node.node_id!r} which does not list it",
            )
            for other in nodes
            if other.parent_id == node.node_id and other.node_id not in declared_children
        )

    if _has_cycle(by_id):
        findings.append(
            _finding(
                "PLAN_HIERARCHY_CYCLE",
                tuple(sorted(by_id)),
                "the plan hierarchy contains a parent cycle",
            )
        )

    seen_by_parent: dict[str | None, set[int]] = {}
    for node in nodes:
        bucket = seen_by_parent.setdefault(node.parent_id, set())
        if node.sequence_index in bucket:
            findings.append(
                _finding(
                    "PLAN_HIERARCHY_DUPLICATE_SEQUENCE_INDEX",
                    (node.node_id,),
                    f"sequence_index {node.sequence_index} is reused among siblings of {node.parent_id!r}",
                )
            )
        bucket.add(node.sequence_index)

    findings.sort(key=lambda finding: (_RULE_INDEX[finding.rule_id], finding.affected_refs))
    return NarrativeValidationReport(findings=tuple(findings))


def _has_cycle(by_id: dict[str, NarrativePlanNode]) -> bool:
    state: dict[str, int] = {}

    def visit(node_id: str) -> bool:
        marker = state.get(node_id)
        if marker == 1:
            return True
        if marker == 2:
            return False
        state[node_id] = 1
        node = by_id.get(node_id)
        if node is not None and node.parent_id is not None and node.parent_id in by_id and visit(node.parent_id):
            return True
        state[node_id] = 2
        return False

    return any(visit(node_id) for node_id in sorted(by_id))


__all__ = [
    "PLAN_HIERARCHY_RULE_ORDER",
    "SceneVersionCheck",
    "next_scene_version",
    "validate_plan_hierarchy",
    "validate_scene_version",
]
