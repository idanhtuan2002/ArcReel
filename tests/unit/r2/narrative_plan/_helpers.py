from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from r2.contracts import (
    CanonBasis,
    NarrativePlanContent,
    NarrativePlanContentV2,
    NarrativePlanNode,
    SceneContract,
    SceneContractV2,
    SceneContractValue,
    SceneFactConstraint,
    SceneRelationshipConstraint,
    SceneTemporalWindow,
    SceneThreadConstraint,
)
from r2.narrative_plan.hashing import compute_scene_semantic_hash, compute_scene_semantic_hash_v2

FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)

# Regression anchors captured from the frozen v1 implementation. v2 code must not move them.
V1_GOLDEN_SCENE = SceneContract(
    scene_contract_id="golden-scene",
    version=1,
    semantic_hash="sh:placeholder",
    sequence_index=0,
    purpose="discover ring",
    pov="hero",
    location_ref="loc-cave",
    temporal_window=SceneTemporalWindow(effective_from=FROM, effective_until=UNTIL),
    participants=["hero", "mentor"],
    entry_state_constraints=[
        SceneFactConstraint(constraint_id="c1", subject_ref="obj-ring", predicate="owner", comparison="PRESENT")
    ],
)
V1_GOLDEN_SCENE_HASH = "sh:66c8077044977a3fa1245bb4db66a803c5ed0da5502f208e99feb0267acafd24"
V1_GOLDEN_PLAN_HASH = "np:133bf9df6dd1fe175abe1967efa2f657a80bee184100d98c91d9ae26acf28af5"


def scene_contract(
    *,
    scene_id: str = "scene-1",
    version: int = 1,
    purpose: str = "discover ring",
    sequence_index: int = 0,
) -> SceneContract:
    draft = SceneContract(
        scene_contract_id=scene_id,
        version=version,
        semantic_hash="sh:placeholder",
        sequence_index=sequence_index,
        purpose=purpose,
        pov=None,
        location_ref=None,
        temporal_window=SceneTemporalWindow(effective_from=FROM, effective_until=UNTIL),
    )
    return draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash(draft)})


def node(
    node_id: str,
    kind: Literal["VOLUME", "EPISODE", "ARC", "CHAPTER"],
    *,
    parent_id: str | None = None,
    sequence_index: int = 0,
    child_refs: list[str] | None = None,
) -> NarrativePlanNode:
    return NarrativePlanNode(
        node_id=node_id,
        node_kind=kind,
        version=1,
        parent_id=parent_id,
        sequence_index=sequence_index,
        intent=f"intent for {node_id}",
        child_refs=child_refs or [],
    )


def plan_content(
    *,
    scenes: list[SceneContract] | None = None,
    volume_plans: list[NarrativePlanNode] | None = None,
    episode_plans: list[NarrativePlanNode] | None = None,
    arc_plans: list[NarrativePlanNode] | None = None,
    chapter_plans: list[NarrativePlanNode] | None = None,
    canon_version_id: str = "canon-v1",
) -> NarrativePlanContent:
    return NarrativePlanContent(
        canon_basis=CanonBasis(branch_id="main", canon_version_id=canon_version_id),
        story_frame="frame",
        volume_plans=volume_plans or [],
        episode_plans=episode_plans or [],
        arc_plans=arc_plans or [],
        chapter_plans=chapter_plans or [],
        scene_contracts=scenes or [],
    )


def relationship_constraint(
    *,
    constraint_id: str = "rc-1",
    source: str = "hero",
    target: str = "mentor",
    key: str = "trust_level",
    comparison: Literal["PRESENT", "ABSENT", "EQUALS", "NOT_EQUALS"] = "PRESENT",
    expected_state: str | None = None,
) -> SceneRelationshipConstraint:
    return SceneRelationshipConstraint(
        constraint_id=constraint_id,
        source_character_ref=source,
        target_character_ref=target,
        relationship_key=key,
        comparison=comparison,
        expected_state=expected_state,
    )


def thread_constraint(
    *,
    constraint_id: str = "tc-1",
    thread_ref: str = "thread-1",
    required_state: Literal["OPEN", "RESOLVED"] = "OPEN",
    payoff_ref: str | None = None,
) -> SceneThreadConstraint:
    return SceneThreadConstraint(
        constraint_id=constraint_id,
        thread_ref=thread_ref,
        required_state=required_state,
        payoff_ref=payoff_ref,
    )


def scene_contract_v2(
    *,
    scene_id: str = "scene-v2-1",
    version: int = 1,
    purpose: str = "discover ring",
    sequence_index: int = 0,
    omniscient: bool = False,
    entry_state_constraints: list[object] | None = None,
    exit_state_targets: list[object] | None = None,
    active_threads: list[str] | None = None,
    promise_payoff_refs: list[str] | None = None,
) -> SceneContractV2:
    draft = SceneContractV2(
        scene_contract_id=scene_id,
        version=version,
        semantic_hash="sh:placeholder",
        sequence_index=sequence_index,
        purpose=purpose,
        pov=None,
        location_ref=None,
        temporal_window=SceneTemporalWindow(effective_from=FROM, effective_until=UNTIL),
        omniscient_authoring_allowed_by_scene=omniscient,
        entry_state_constraints=entry_state_constraints or [],
        exit_state_targets=exit_state_targets or [],
        active_threads=active_threads or [],
        promise_payoff_refs=promise_payoff_refs or [],
    )
    return draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash_v2(draft)})


def plan_content_v2(
    *,
    scenes: list[SceneContractValue] | None = None,
    volume_plans: list[NarrativePlanNode] | None = None,
    episode_plans: list[NarrativePlanNode] | None = None,
    arc_plans: list[NarrativePlanNode] | None = None,
    chapter_plans: list[NarrativePlanNode] | None = None,
    canon_version_id: str = "canon-v1",
) -> NarrativePlanContentV2:
    return NarrativePlanContentV2(
        canon_basis=CanonBasis(branch_id="main", canon_version_id=canon_version_id),
        story_frame="frame",
        volume_plans=volume_plans or [],
        episode_plans=episode_plans or [],
        arc_plans=arc_plans or [],
        chapter_plans=chapter_plans or [],
        scene_contracts=scenes or [],
    )
