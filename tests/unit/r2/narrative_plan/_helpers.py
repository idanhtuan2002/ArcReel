from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from r2.contracts import (
    CanonBasis,
    NarrativePlanContent,
    NarrativePlanNode,
    SceneContract,
    SceneTemporalWindow,
)
from r2.narrative_plan.hashing import compute_scene_semantic_hash

FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)


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
