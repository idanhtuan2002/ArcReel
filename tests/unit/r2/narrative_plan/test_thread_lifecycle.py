from __future__ import annotations

from r2.narrative_plan.validation import validate_plan_thread_lifecycle
from tests.unit.r2.narrative_plan._helpers import plan_content_v2, scene_contract_v2, thread_constraint


def _rules(content_scenes: list[object]) -> list[str]:
    report = validate_plan_thread_lifecycle(plan_content_v2(scenes=content_scenes))
    return [f.rule_id for f in report.findings]


def _scene(seq: int, **kw: object) -> object:
    return scene_contract_v2(scene_id=f"sc-{seq}", sequence_index=seq, **kw)


def test_thread_may_be_omitted_from_an_intermediate_scene_without_resolving() -> None:
    scenes = [
        _scene(0, active_threads=["t1"], exit_state_targets=[thread_constraint(constraint_id="e0", thread_ref="t1")]),
        _scene(1),  # t1 omitted entirely
        _scene(
            2,
            active_threads=["t1"],
            promise_payoff_refs=["p1"],
            exit_state_targets=[
                thread_constraint(constraint_id="e2", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
            ],
        ),
    ]
    assert _rules(scenes) == []


def test_presentation_order_is_by_sequence_index_not_list_order() -> None:
    later = _scene(
        2,
        active_threads=["t1"],
        promise_payoff_refs=["p1"],
        exit_state_targets=[
            thread_constraint(constraint_id="e2", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
        ],
    )
    opener = _scene(0, active_threads=["t1"])
    assert _rules([later, opener]) == []


def test_entry_open_requires_the_thread_open_and_in_active_threads() -> None:
    scenes = [
        _scene(0, active_threads=["t1"]),
        _scene(1, entry_state_constraints=[thread_constraint(constraint_id="x", thread_ref="t1")]),  # not in active
    ]
    assert "SCENE_THREAD_LIFECYCLE_ENTRY_OPEN_UNMET" in _rules(scenes)


def test_entry_resolved_requires_a_prior_resolution_with_the_matching_payoff() -> None:
    resolve = _scene(
        0,
        active_threads=["t1"],
        promise_payoff_refs=["p1"],
        exit_state_targets=[
            thread_constraint(constraint_id="r0", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
        ],
    )
    wrong_payoff = _scene(
        1,
        entry_state_constraints=[
            thread_constraint(constraint_id="c1", thread_ref="t1", required_state="RESOLVED", payoff_ref="p2")
        ],
    )
    assert "SCENE_THREAD_LIFECYCLE_ENTRY_RESOLVED_PAYOFF_MISMATCH" in _rules([resolve, wrong_payoff])

    no_prior = _scene(
        0,
        active_threads=["t1"],
        entry_state_constraints=[
            thread_constraint(constraint_id="c1", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
        ],
    )
    assert "SCENE_THREAD_LIFECYCLE_ENTRY_RESOLVED_UNMET" in _rules([no_prior])


def test_exit_open_requires_the_thread_still_open_with_no_resolution_this_scene() -> None:
    scenes = [
        _scene(
            0,
            active_threads=["t1"],
            promise_payoff_refs=["p1"],
            exit_state_targets=[
                thread_constraint(constraint_id="o", thread_ref="t1", required_state="OPEN"),
                thread_constraint(constraint_id="r", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1"),
            ],
        )
    ]
    assert "SCENE_THREAD_LIFECYCLE_EXIT_OPEN_UNMET" in _rules(scenes)


def test_exit_resolved_needs_the_exact_payoff_ref_in_promise_payoff_refs() -> None:
    scenes = [
        _scene(
            0,
            active_threads=["t1"],
            exit_state_targets=[
                thread_constraint(constraint_id="r", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
            ],
        )
    ]
    assert "SCENE_THREAD_LIFECYCLE_ORPHAN_PAYOFF" in _rules(scenes)


def test_resolution_without_a_prior_or_open_thread_fails_closed() -> None:
    scenes = [
        _scene(
            0,
            promise_payoff_refs=["p1"],
            exit_state_targets=[
                thread_constraint(constraint_id="r", thread_ref="ghost", required_state="RESOLVED", payoff_ref="p1")
            ],
        )
    ]
    assert "SCENE_THREAD_LIFECYCLE_RESOLUTION_WITHOUT_THREAD" in _rules(scenes)


def test_two_resolutions_of_the_same_thread_fail_closed() -> None:
    scenes = [
        _scene(
            0,
            active_threads=["t1"],
            promise_payoff_refs=["p1"],
            exit_state_targets=[
                thread_constraint(constraint_id="r0", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
            ],
        ),
        _scene(
            1,
            promise_payoff_refs=["p2"],
            exit_state_targets=[
                thread_constraint(constraint_id="r1", thread_ref="t1", required_state="RESOLVED", payoff_ref="p2")
            ],
        ),
    ]
    assert "SCENE_THREAD_LIFECYCLE_DOUBLE_RESOLUTION" in _rules(scenes)


def test_a_resolved_thread_that_reappears_in_active_threads_fails_closed() -> None:
    scenes = [
        _scene(
            0,
            active_threads=["t1"],
            promise_payoff_refs=["p1"],
            exit_state_targets=[
                thread_constraint(constraint_id="r0", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
            ],
        ),
        _scene(1, active_threads=["t1"]),
    ]
    assert "SCENE_THREAD_LIFECYCLE_REOPENED_RESOLVED" in _rules(scenes)


def test_clean_open_then_resolve_across_scenes_produces_no_findings() -> None:
    scenes = [
        _scene(0, active_threads=["t1"], exit_state_targets=[thread_constraint(constraint_id="o", thread_ref="t1")]),
        _scene(
            1,
            active_threads=["t1"],
            entry_state_constraints=[thread_constraint(constraint_id="e", thread_ref="t1")],
            promise_payoff_refs=["p1"],
            exit_state_targets=[
                thread_constraint(constraint_id="r", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
            ],
        ),
        _scene(
            2,
            entry_state_constraints=[
                thread_constraint(constraint_id="e2", thread_ref="t1", required_state="RESOLVED", payoff_ref="p1")
            ],
        ),
    ]
    assert _rules(scenes) == []
