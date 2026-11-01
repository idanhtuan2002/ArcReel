from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.automation.identity import policy_digest
from r2.contracts.automation import (
    AutomationMode,
    Checkpoint,
    PendingReview,
    RepairCount,
    RunCommand,
    RunPolicy,
    RunSnapshot,
    RunStage,
    RunStatus,
)
from server.production_run.controller import ProductionController
from server.production_run.ports import StepPlan
from server.production_run.service import ProductionRunRefused, ProductionRunService, policy_for_mode, refusal

INPUT = "sha256:" + "c" * 64
NEW_INPUT = "sha256:" + "e" * 64


def _policy(**changes) -> RunPolicy:
    return RunPolicy.model_validate(
        {
            "profile_id": "fiction_narration_vi_v1",
            "profile_digest": "sha256:" + "a" * 64,
            "currency": "USD",
            "max_cost_minor_units": 500,
            "max_model_calls": 200,
            "max_tasks": 100,
            "max_runtime_seconds": 21600,
            "route_digests": ["sha256:" + "b" * 64],
            **changes,
        }
    )


def _run(**changes) -> RunSnapshot:
    return RunSnapshot.model_validate(
        {
            "user_id": "u1",
            "project_name": "film",
            "run_id": "run-1",
            "policy": _policy(),
            "input_digest": INPUT,
            "status": RunStatus.RUNNING,
            "targets": ["episode:1"],
            "version": 4,
            "fencing_epoch": 2,
            "created_at": datetime(2026, 10, 30, tzinfo=UTC),
            **changes,
        }
    )


def _command(run: RunSnapshot, action, **changes) -> RunCommand:
    return RunCommand.model_validate(
        {
            "user_id": run.user_id,
            "project_name": run.project_name,
            "run_id": run.run_id,
            "command_id": "command-1",
            "action": action,
            "expected_version": run.version,
            "expected_input_digest": run.input_digest,
            "policy_digest": policy_digest(run.policy),
            **changes,
        }
    )


def _service() -> ProductionRunService:
    return ProductionRunService.__new__(ProductionRunService)


PLAN = StepPlan(
    unit_key="episode:1",
    estimated_cost_minor_units=10,
    estimated_model_calls=1,
    estimated_tasks=1,
    estimated_runtime_seconds=30,
)


def test_replanned_step_has_the_same_command_and_task_identity():
    run = _run(stage=RunStage.SCRIPT)

    first = ProductionController._intent(run, "script", PLAN)
    replay = ProductionController._intent(run.model_copy(update={"version": 9, "fencing_epoch": 5}), "script", PLAN)

    assert replay == first
    assert first.identity.repair_index == 0


def test_repair_and_generation_change_the_step_identity():
    run = _run(stage=RunStage.SCRIPT)
    repaired = run.model_copy(
        update={"repair_counts": (RepairCount(stage=RunStage.SCRIPT, unit_key="episode:1", count=1),)}
    )
    next_generation = run.model_copy(update={"generation": 2})

    base = ProductionController._intent(run, "script", PLAN).identity
    assert ProductionController._intent(repaired, "script", PLAN).identity.repair_index == 1
    assert ProductionController._intent(repaired, "script", PLAN).identity.task_id != base.task_id
    assert ProductionController._intent(next_generation, "script", PLAN).identity.task_id != base.task_id


def test_mode_policy_keeps_caps_and_takes_the_mode_default_checkpoints():
    auto = _policy()

    semi = policy_for_mode(auto, AutomationMode.SEMI)

    assert semi.checkpoints == {Checkpoint.SCRIPT_PACKAGE, Checkpoint.FINAL_FILM}
    assert semi.model_dump(exclude={"mode", "checkpoints"}) == auto.model_dump(exclude={"mode", "checkpoints"})
    assert policy_for_mode(semi, AutomationMode.AUTO) == auto
    assert policy_digest(semi) != policy_digest(auto)


@pytest.mark.parametrize("action", ["PAUSE", "CANCEL"])
def test_stop_accepts_an_older_seen_version_and_fences_the_lease(action):
    run = _run(status=RunStatus.WAITING_TASK)

    stopped = _service()._stop(run, _command(run, action, expected_version=run.version - 2))

    assert stopped.status is (RunStatus.PAUSED if action == "PAUSE" else RunStatus.CANCELLED)
    assert (stopped.version, stopped.fencing_epoch) == (run.version + 1, run.fencing_epoch + 1)


def test_stop_replay_is_idempotent_and_a_future_version_is_refused():
    run = _run(status=RunStatus.PAUSED)

    assert _service()._stop(run, _command(run, "PAUSE")) is run
    with pytest.raises(ProductionRunRefused, match="STALE_PRODUCTION_RUN"):
        _service()._stop(run, _command(run, "PAUSE", expected_version=run.version + 1))


def test_stop_of_a_finished_run_is_refused():
    run = _run(status=RunStatus.FAILED_QUALITY, reason="REPAIR_LIMIT")

    with pytest.raises(ProductionRunRefused, match="RUN_FINISHED"):
        _service()._stop(run, _command(run, "CANCEL"))


def test_pause_of_a_review_wait_drops_the_pending_binding():
    run = _run(
        status=RunStatus.WAITING_REVIEW,
        pending_review=PendingReview(checkpoint=Checkpoint.SCRIPT_PACKAGE, binding_digest="sha256:" + "9" * 64),
    )

    paused = _service()._stop(run, _command(run, "PAUSE"))

    assert paused.pending_review is None


def test_resume_requires_the_exact_version_of_a_stopped_run():
    run = _run(status=RunStatus.PAUSED)

    with pytest.raises(ProductionRunRefused, match="STALE_PRODUCTION_RUN"):
        _service()._resume(run, _command(run, "RESUME", expected_version=run.version - 1), rebind=False)
    resumed = _service()._resume(run, _command(run, "RESUME"), rebind=False)
    assert (resumed.status, resumed.generation, resumed.input_digest) == (RunStatus.RUNNING, 1, INPUT)


def test_resume_of_a_running_run_is_a_replay():
    run = _run(status=RunStatus.WAITING_TASK)

    assert _service()._resume(run, _command(run, "RESUME", expected_version=1), rebind=False) is run


def test_input_rebind_starts_a_new_lineage_from_the_brief():
    run = _run(status=RunStatus.BLOCKED_INPUT_CHANGED, reason="EXTERNAL_INPUT_CHANGED", stage=RunStage.MEDIA)

    rebound = _service()._resume(run, _command(run, "RESUME", expected_input_digest=NEW_INPUT), rebind=True)

    assert (rebound.stage, rebound.generation, rebound.input_digest, rebound.status) == (
        RunStage.BRIEF,
        run.generation + 1,
        NEW_INPUT,
        RunStatus.RUNNING,
    )


def test_only_an_input_changed_block_can_rebind_input():
    run = _run(status=RunStatus.PAUSED)

    with pytest.raises(ProductionRunRefused, match="STALE_PRODUCTION_RUN"):
        _service()._resume(run, _command(run, "RESUME", expected_input_digest=NEW_INPUT), rebind=True)
    with pytest.raises(ProductionRunRefused, match="STALE_PRODUCTION_RUN"):
        _service()._resume(run, _command(run, "RESUME", expected_input_digest=NEW_INPUT), rebind=False)


@pytest.mark.parametrize("status", [RunStatus.CANCELLED, RunStatus.FAILED, RunStatus.WAITING_REVIEW])
def test_finished_or_review_runs_are_not_resumable(status):
    changes: dict[str, object] = {"status": status}
    if status is RunStatus.WAITING_REVIEW:
        changes["pending_review"] = PendingReview(checkpoint=Checkpoint.FINAL_FILM, binding_digest="sha256:" + "9" * 64)
    run = _run(**changes)

    with pytest.raises(ProductionRunRefused, match="RUN_NOT_RESUMABLE"):
        _service()._resume(run, _command(run, "RESUME"), rebind=False)


def test_refusal_bodies_carry_codes_and_no_exception_internals():
    assert refusal(ProductionRunRefused("PREFLIGHT_BLOCKED", 409, ("DISK_LOW",))) == (
        409,
        {"code": "PREFLIGHT_BLOCKED", "reasons": ["DISK_LOW"]},
    )
    assert refusal(PermissionError("AUTOMATION_GRANT_MOVED"))[0] == 403
