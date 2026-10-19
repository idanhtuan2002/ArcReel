"""The story pipeline's node graph, its order and the fingerprints that decide staleness.

Nodes are the generated artifacts of one run (amendment Change D): ``seed``, ``story_bible``, ``style_bible``,
``outline``, one ``chapter_plan[c]`` per chapter (the scene contracts of that chapter), one ``scene_draft[c,s]``
per scene, ``chapter_review[c]``, ``manuscript_review`` and ``packaging``. The brief is the run's input, and
Human revision intents are sources attached to a node. Edges are data dependencies; a scene draft depends on
every earlier scene through its compiled context, never on a chapter or review node, so the graph is acyclic.

A node's fingerprint covers everything that produced it: its kind's template version, the model route and
decoding, the digests of its inputs' current heads, its intents and any extra binding (a scene's context pack).
The driver walks :func:`topological_order` and regenerates a node only when its recomputed fingerprint
differs from its head's, after its inputs have already converged, which is topological dirty propagation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

TEMPLATE_VERSIONS = {
    "seed": "story-seed-v1",
    "story_bible": "story-bible-v1",
    "style_bible": "style-bible-v1",
    "outline": "story-outline-v1",
    "chapter_plan": "chapter-plan-v1",
    "scene_draft": "scene-draft-v1",
    "chapter_review": "chapter-review-v1",
    "manuscript_review": "manuscript-review-v1",
    "packaging": "packaging-v2",
}

PLANNING_NODES = ("seed", "story_bible", "style_bible", "outline")


def chapter_plan(chapter: int) -> str:
    return f"chapter_plan[{chapter}]"


def scene_draft(chapter: int, scene: int) -> str:
    return f"scene_draft[{chapter},{scene}]"


def chapter_review(chapter: int) -> str:
    return f"chapter_review[{chapter}]"


def node_kind(node: str) -> str:
    return node.split("[", 1)[0]


def build_graph(scenes_per_chapter: Sequence[int]) -> dict[str, tuple[str, ...]]:
    """``node -> inputs`` for a story with ``len(scenes_per_chapter)`` chapters (0 scenes = not planned yet)."""
    graph: dict[str, tuple[str, ...]] = {
        "seed": (),
        "story_bible": ("seed",),
        "style_bible": ("seed", "story_bible"),
        "outline": ("seed",),
    }
    drafts: list[str] = []
    for c, count in enumerate(scenes_per_chapter, start=1):
        graph[chapter_plan(c)] = ("seed", "story_bible", "outline", *(chapter_plan(p) for p in range(1, c)))
        chapter_drafts = []
        for s in range(1, count + 1):
            node = scene_draft(c, s)
            graph[node] = (chapter_plan(c), "seed", "story_bible", "style_bible", *drafts)
            drafts.append(node)
            chapter_drafts.append(node)
        if count:
            graph[chapter_review(c)] = (chapter_plan(c), *chapter_drafts)
    if drafts and all(scenes_per_chapter):
        graph["manuscript_review"] = ("outline", *drafts)
        graph["packaging"] = ("seed", "manuscript_review", *drafts)
    return graph


class CycleError(ValueError):
    pass


def topological_order(graph: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    """Kahn's algorithm, ties broken by insertion order, so the order is deterministic."""
    pending = {node: {i for i in inputs if i in graph} for node, inputs in graph.items()}
    order: list[str] = []
    ready = [node for node in graph if not pending[node]]
    while ready:
        node = ready.pop(0)
        order.append(node)
        for other in graph:
            if node in pending[other]:
                pending[other].discard(node)
                if not pending[other] and other not in order and other not in ready:
                    ready.append(other)
    if len(order) != len(graph):
        raise CycleError(f"cycle among {sorted(set(graph) - set(order))}")
    return tuple(order)


def forward_closure(graph: Mapping[str, Sequence[str]], node: str) -> frozenset[str]:
    """The node and everything that depends on it, transitively."""
    closure = {node}
    changed = True
    while changed:
        changed = False
        for other, inputs in graph.items():
            if other not in closure and closure & set(inputs):
                closure.add(other)
                changed = True
    return frozenset(closure)


def intent_targets(target: str, scenes_per_chapter: Sequence[int]) -> tuple[str, ...]:
    """Where a Human revision request lands: a chapter request goes to every scene of that chapter."""
    if target.startswith("chapter[") and target.endswith("]"):
        chapter = int(target[len("chapter[") : -1])
        return tuple(scene_draft(chapter, s) for s in range(1, scenes_per_chapter[chapter - 1] + 1))
    return (target,)


def fingerprint(
    *,
    node: str,
    route_digest: str,
    decoding: Mapping[str, Any],
    inputs: Sequence[tuple[str, str]],
    intents: Sequence[str] = (),
    extra: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "node": node,
        "template": TEMPLATE_VERSIONS[node_kind(node)],
        "route": route_digest,
        "decoding": dict(decoding),
        "inputs": [list(pair) for pair in inputs],
        "intents": list(intents),
        "extra": dict(extra or {}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
