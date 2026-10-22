"""Pure run-state transitions: budget reservation and settlement, promotion fencing, restart reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from server.story_authoring.contracts import AttemptKind, StoryFailureCode, StoryLimits
from server.story_authoring.runtime import (
    AttemptState,
    BudgetExhausted,
    RevisionOutcome,
    RunNotRunning,
    RunPhase,
    RunState,
    complete,
    fail,
    mark_dispatched,
    mark_unknown,
    new_run_state,
    orphan_digests,
    promote,
    reconcile,
    require,
    reserve,
    set_phase,
)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _state(**limits) -> RunState:
    fields = {"input_tokens_max": 100_000, "output_tokens_max": 20_000, "wall_clock_max_seconds": 3600}
    fields.update(limits)
    return new_run_state(run_id="run-1", limits=StoryLimits(**fields), now=NOW)


def _reserve(state: RunState, attempt_id: str, kind=AttemptKind.GENERATE, inp=1000, out=500) -> RunState:
    return reserve(
        state,
        attempt_id=attempt_id,
        step_id="scene_draft[1,1]",
        kind=kind,
        request_digest="sha256:" + "a" * 64,
        reserved_input_tokens=inp,
        reserved_output_tokens=out,
        now=NOW,
    )


def test_a_reservation_charges_its_maximum_until_settled():
    state = _reserve(_state(), "a1")
    assert (state.usage.generate_calls, state.usage.input_tokens, state.usage.output_tokens) == (1, 1000, 500)

    state = mark_dispatched(state, attempt_id="a1", ledger_call_id=7)
    state = complete(state, attempt_id="a1", input_tokens=900, output_tokens=120, done_reason="stop", duration_ms=4000)

    assert state.attempt("a1").state is AttemptState.COMPLETED
    assert state.attempt("a1").ledger_call_id == 7
    assert (state.usage.input_tokens, state.usage.output_tokens, state.usage.model_milliseconds) == (900, 120, 4000)


def test_count_and_generate_calls_have_separate_ceilings():
    state = _state(count_calls_max=1, generate_calls_max=1)
    state = _reserve(state, "c1", kind=AttemptKind.COUNT)
    state = _reserve(state, "g1")
    with pytest.raises(BudgetExhausted, match="count_calls 1"):
        _reserve(state, "c2", kind=AttemptKind.COUNT)
    with pytest.raises(BudgetExhausted, match="generate_calls 1"):
        _reserve(state, "g2")


@pytest.mark.parametrize(
    ("limits", "inp", "out", "cap"),
    [
        ({"input_tokens_max": 1500}, 1000, 10, "input_tokens 1500"),
        ({"output_tokens_max": 800}, 10, 500, "output_tokens 800"),
    ],
)
def test_token_ceilings_count_outstanding_reservations(limits, inp, out, cap):
    state = _reserve(_state(**limits), "a1", inp=inp, out=out)
    with pytest.raises(BudgetExhausted, match=cap):
        _reserve(state, "a2", inp=inp, out=out)


def test_the_wall_clock_ceiling_is_model_time():
    state = _reserve(_state(wall_clock_max_seconds=1), "a1")
    state = mark_dispatched(state, attempt_id="a1", ledger_call_id=None)
    state = complete(state, attempt_id="a1", input_tokens=1, output_tokens=1, done_reason="stop", duration_ms=1001)
    with pytest.raises(BudgetExhausted, match="wall_clock"):
        _reserve(state, "a2")


def test_model_time_that_reached_the_ceiling_refuses_the_next_call():
    state = _reserve(_state(wall_clock_max_seconds=1), "a1")
    state = mark_dispatched(state, attempt_id="a1", ledger_call_id=None)
    state = complete(state, attempt_id="a1", input_tokens=1, output_tokens=1, done_reason="stop", duration_ms=1000)
    with pytest.raises(BudgetExhausted, match="wall_clock"):
        _reserve(state, "a2")


def test_a_never_dispatched_failure_releases_everything():
    state = fail(_reserve(_state(), "a1"), attempt_id="a1", code=StoryFailureCode.NOT_DISPATCHED)
    assert state.usage.model_dump() == {
        "count_calls": 0,
        "generate_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "model_milliseconds": 0,
    }


@pytest.mark.parametrize(
    ("code", "input_tokens", "charged"),
    [
        (StoryFailureCode.MODEL_UNAVAILABLE, None, (1000, 0)),
        (StoryFailureCode.INPUT_OVER_CONTEXT, 40001, (40001, 0)),
        (StoryFailureCode.OUTPUT_INVALID, 900, (900, 500)),
        (StoryFailureCode.CJK_IN_OUTPUT, None, (1000, 500)),
    ],
)
def test_a_dispatched_failure_is_charged_conservatively(code, input_tokens, charged):
    state = mark_dispatched(_reserve(_state(), "a1"), attempt_id="a1", ledger_call_id=None)
    state = fail(state, attempt_id="a1", code=code, input_tokens=input_tokens)
    assert (state.usage.input_tokens, state.usage.output_tokens) == charged
    assert state.usage.generate_calls == 1


def test_an_unknown_outcome_keeps_its_full_charge():
    state = mark_unknown(
        mark_dispatched(_reserve(_state(), "a1"), attempt_id="a1", ledger_call_id=None), attempt_id="a1"
    )
    assert state.attempt("a1").state is AttemptState.UNKNOWN
    assert (state.usage.input_tokens, state.usage.output_tokens) == (1000, 500)


def test_nothing_is_reserved_or_dispatched_unless_the_run_is_running():
    state = set_phase(_reserve(_state(), "a1"), RunPhase.DISCARDED)
    with pytest.raises(RunNotRunning):
        _reserve(state, "a2")
    with pytest.raises(RunNotRunning):
        mark_dispatched(state, attempt_id="a1", ledger_call_id=None)


def _promote(state: RunState, revision_id: str, *, fingerprint="f1", expected=None, epoch=1):
    return promote(
        state,
        revision_id=revision_id,
        node_id="scene_draft[1,1]",
        digest="sha256:" + revision_id[-1] * 64,
        fingerprint=fingerprint,
        attempt_id=f"att-{revision_id}",
        expected_head_revision_id=expected,
        generation_epoch=epoch,
        now=NOW,
    )


def test_two_results_dispatched_with_the_same_expectations_promote_exactly_once():
    state = require(_state(), node_id="scene_draft[1,1]", fingerprint="f1")
    snapshot = state.node("scene_draft[1,1]")

    state, first = _promote(state, "r1", expected=snapshot.head_revision_id, epoch=snapshot.generation_epoch)
    state, second = _promote(state, "r2", expected=snapshot.head_revision_id, epoch=snapshot.generation_epoch)

    assert (first, second) == (True, False)
    assert state.node("scene_draft[1,1]").head_revision_id == "r1"
    assert state.revisions["r2"].outcome is RevisionOutcome.STALE_RESULT
    assert state.checkpoint is not None
    assert state.checkpoint.revision_id == "r1"


def test_a_result_after_the_input_changed_is_stale():
    state = require(_state(), node_id="scene_draft[1,1]", fingerprint="f1")
    snapshot = state.node("scene_draft[1,1]")
    state = require(state, node_id="scene_draft[1,1]", fingerprint="f2")

    state, promoted = _promote(state, "r1", fingerprint="f1", epoch=snapshot.generation_epoch)

    assert not promoted
    assert state.node("scene_draft[1,1]").head_revision_id is None


@pytest.mark.parametrize("phase", [RunPhase.DISCARDED, RunPhase.ABORTED_PARTIAL, RunPhase.READY_FOR_APPROVAL])
def test_a_result_arriving_after_the_run_left_running_is_stale(phase):
    state = require(_state(), node_id="scene_draft[1,1]", fingerprint="f1")
    state = set_phase(state, phase)

    state, promoted = _promote(state, "r1", epoch=1)

    assert not promoted
    assert state.revisions["r1"].outcome is RevisionOutcome.STALE_RESULT


def test_a_node_without_a_required_fingerprint_cannot_be_promoted():
    state, promoted = _promote(_state(), "r1", epoch=0)
    assert not promoted
    assert state.revisions["r1"].outcome is RevisionOutcome.STALE_RESULT


def test_requiring_the_same_fingerprint_keeps_the_epoch():
    state = require(_state(), node_id="n", fingerprint="f1")
    assert require(state, node_id="n", fingerprint="f1") is state
    assert require(state, node_id="n", fingerprint="f2").node("n").generation_epoch == 2


def test_reconcile_settles_interrupted_attempts_without_resending():
    state = _reserve(_state(), "never-sent")
    state = mark_dispatched(_reserve(state, "in-flight"), attempt_id="in-flight", ledger_call_id=3)

    state, problems = reconcile(state, blob_exists=lambda _: True)

    assert problems == ()
    assert state.attempt("never-sent").state is AttemptState.FAILED
    assert state.attempt("never-sent").failure_code is StoryFailureCode.NOT_DISPATCHED
    assert state.attempt("in-flight").state is AttemptState.UNKNOWN
    assert (state.usage.generate_calls, state.usage.input_tokens) == (1, 1000)
    assert state.phase is RunPhase.RUNNING


def test_reconcile_stops_the_run_when_a_head_names_missing_content():
    state = require(_state(), node_id="scene_draft[1,1]", fingerprint="f1")
    state, _ = _promote(state, "r1", epoch=1)

    state, problems = reconcile(state, blob_exists=lambda _: False)

    assert state.phase is RunPhase.RECOVERY_INCONSISTENT
    assert len(problems) == 1
    assert "missing content" in problems[0]


def test_reconcile_stops_the_run_when_the_checkpoint_disagrees_with_the_index():
    state = require(_state(), node_id="scene_draft[1,1]", fingerprint="f1")
    state, _ = _promote(state, "r1", epoch=1)
    assert state.checkpoint is not None
    state = state.model_copy(
        update={"checkpoint": state.checkpoint.model_copy(update={"digest": "sha256:" + "0" * 64})}
    )

    state, problems = reconcile(state, blob_exists=lambda _: True)

    assert state.phase is RunPhase.RECOVERY_INCONSISTENT
    assert "checkpoint" in problems[0]


def test_the_state_round_trips_through_json():
    state = require(_reserve(_state(), "a1"), node_id="n", fingerprint="f1")
    assert RunState.model_validate_json(state.model_dump_json()) == state


def test_content_written_before_a_crash_is_an_orphan_not_a_revision():
    state = require(_state(), node_id="scene_draft[1,1]", fingerprint="f1")
    state, _ = _promote(state, "r1", epoch=1)
    kept = state.revisions["r1"].digest

    assert orphan_digests(state, [kept, "sha256:" + "9" * 64]) == ("sha256:" + "9" * 64,)
