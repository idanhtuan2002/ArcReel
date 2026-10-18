from __future__ import annotations

import random

import pytest

from server.story_authoring.pipeline import (
    CycleError,
    build_graph,
    chapter_plan,
    chapter_review,
    fingerprint,
    forward_closure,
    intent_targets,
    scene_draft,
    topological_order,
)

SHAPE = (2, 3, 2)
GRAPH = build_graph(SHAPE)
ALL_DRAFTS = [scene_draft(c, s) for c, n in enumerate(SHAPE, start=1) for s in range(1, n + 1)]


@pytest.mark.parametrize("shape", [(0, 0, 0), (3, 0, 0), (3, 4, 0), (3, 4, 5), (5, 5, 5), (1, 1, 1)])
def test_every_story_shape_is_acyclic(shape):
    graph = build_graph(shape)
    assert set(topological_order(graph)) == set(graph)


def test_the_expanded_graph_with_random_intents_stays_acyclic():
    rnd = random.Random(7)
    for _ in range(50):
        graph = dict(build_graph(SHAPE))
        for i, target in enumerate(rnd.sample(sorted(GRAPH), 6)):
            intent = f"intent:{i}"
            graph[intent] = ()
            graph[target] = (*graph[target], intent)
        assert len(topological_order(graph)) == len(graph)


def test_a_cycle_is_reported():
    with pytest.raises(CycleError):
        topological_order({"a": ("b",), "b": ("a",)})


def test_the_order_puts_inputs_first_and_scenes_in_story_order():
    order = topological_order(GRAPH)
    for node, inputs in GRAPH.items():
        assert all(order.index(i) < order.index(node) for i in inputs)
    drafts = [n for n in order if n.startswith("scene_draft")]
    assert drafts == ALL_DRAFTS
    assert order[0] == "seed"


def test_a_chapter_two_revision_stales_exactly_chapter_two_onward():
    targets = intent_targets("chapter[2]", SHAPE)
    stale = frozenset().union(*(forward_closure(GRAPH, t) for t in targets))
    assert targets == (scene_draft(2, 1), scene_draft(2, 2), scene_draft(2, 3))
    assert stale == {
        *targets,
        scene_draft(3, 1),
        scene_draft(3, 2),
        chapter_review(2),
        chapter_review(3),
        "manuscript_review",
        "packaging",
    }


@pytest.mark.parametrize(
    ("changed", "expected_absent", "expected_present"),
    [
        ("seed", set(), set(GRAPH)),
        ("story_bible", {"seed", "outline"}, {"style_bible", chapter_plan(1), *ALL_DRAFTS, "packaging"}),
        ("style_bible", {"seed", "story_bible", "outline", chapter_plan(1)}, {*ALL_DRAFTS, "manuscript_review"}),
        ("outline", {"seed", "story_bible", "style_bible"}, {chapter_plan(1), chapter_plan(3), *ALL_DRAFTS}),
        (
            chapter_plan(2),
            {chapter_plan(1), scene_draft(1, 2), chapter_review(1)},
            {chapter_plan(3), scene_draft(2, 1)},
        ),
        (scene_draft(1, 2), {scene_draft(1, 1), chapter_plan(2)}, {scene_draft(2, 1), chapter_review(1), "packaging"}),
        ("packaging", set(GRAPH) - {"packaging"}, {"packaging"}),
        ("manuscript_review", set(ALL_DRAFTS), {"manuscript_review", "packaging"}),
    ],
)
def test_each_change_type_stales_exactly_its_dependents(changed, expected_absent, expected_present):
    stale = forward_closure(GRAPH, changed)
    assert expected_present <= stale
    assert not (expected_absent & stale)


def test_a_scene_request_targets_that_scene_only():
    assert intent_targets(scene_draft(1, 2), SHAPE) == (scene_draft(1, 2),)
    assert intent_targets("packaging", SHAPE) == ("packaging",)


def test_reviews_and_packaging_wait_for_every_chapter_to_be_planned():
    partial = build_graph((3, 0, 0))
    assert chapter_review(1) in partial
    assert "manuscript_review" not in partial
    assert "packaging" not in partial


def _fp(**overrides):
    fields = {
        "node": scene_draft(1, 1),
        "route_digest": "sha256:r",
        "decoding": {"temperature": 0.7, "seed": 1},
        "inputs": [(chapter_plan(1), "sha256:a")],
        "intents": [],
        "extra": {"context_pack_id": "ncp:1"},
    }
    fields.update(overrides)
    return fingerprint(**fields)


def test_fingerprints_are_deterministic_and_sensitive_to_every_input():
    base = _fp()
    assert base == _fp()
    for change in (
        {"route_digest": "sha256:other"},
        {"decoding": {"temperature": 0.8, "seed": 1}},
        {"inputs": [(chapter_plan(1), "sha256:b")]},
        {"intents": ["Cho Lan nói nhiều hơn."]},
        {"extra": {"context_pack_id": "ncp:2"}},
        {"node": scene_draft(1, 2)},
    ):
        assert _fp(**change) != base
