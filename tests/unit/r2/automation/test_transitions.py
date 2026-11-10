from __future__ import annotations

import pytest


def outcome_for(run, **changes):
    from r2.automation.identity import policy_digest
    from r2.contracts.automation import OwnerReceipt, StageOutcome

    return StageOutcome(
        stage=changes.pop("stage", run.stage),
        generation=run.generation,
        input_digest=changes.pop("input_digest", run.input_digest),
        policy_digest=changes.pop("policy_digest", policy_digest(run.policy)),
        kind=changes.pop("kind", "PASS"),
        receipts=(OwnerReceipt(owner="story", receipt_ref="receipt-1", digest="sha256:" + "d" * 64),),
        **changes,
    )


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("BLOCKED_QUALITY", "FAILED_QUALITY"),
        ("MODEL_UNAVAILABLE", "BLOCKED_CONFIGURATION"),
        ("BLOCKED_BUDGET", "BLOCKED_BUDGET"),
        ("RECOVERY_INCONSISTENT", "BLOCKED_UNKNOWN"),
    ],
)
def test_task_success_cannot_advance_blocked_story(run_data: dict, phase: str, expected: str):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot

    run = RunSnapshot.model_validate({**run_data, "stage": "STORY"})
    updated = advance(run=run, outcome=outcome_for(run, owner_state=phase))
    assert updated.status.value == expected
    assert updated.stage == run.stage


def test_ready_story_advances_to_commit_not_media(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStage

    run = RunSnapshot.model_validate({**run_data, "stage": "STORY"})
    updated = advance(run=run, outcome=outcome_for(run, owner_state="READY_FOR_APPROVAL"))
    assert updated.stage is RunStage.STORY_COMMIT


def test_semi_script_checkpoint_waits_for_exact_review(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import Checkpoint, RunSnapshot, RunStatus

    run_data["policy"]["mode"] = "semi"
    run = RunSnapshot.model_validate({**run_data, "stage": "SCRIPT"})
    updated = advance(run=run, outcome=outcome_for(run))
    assert updated.status is RunStatus.WAITING_REVIEW
    assert updated.pending_review.checkpoint is Checkpoint.SCRIPT_PACKAGE
    assert updated.stage == run.stage


def test_auto_script_checkpoint_needs_no_user_action(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStage, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "SCRIPT"})
    updated = advance(run=run, outcome=outcome_for(run))
    assert updated.stage is RunStage.MEDIA
    assert updated.status is RunStatus.RUNNING
    assert updated.pending_review is None


@pytest.mark.parametrize(
    "change", [{"input_digest": "sha256:" + "e" * 64}, {"policy_digest": "sha256:" + "e" * 64}, {"stage": "MEDIA"}]
)
def test_changed_authority_never_advances(run_data: dict, change: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "SCRIPT"})
    updated = advance(run=run, outcome=outcome_for(run, **change))
    assert updated.status is RunStatus.BLOCKED_INPUT_CHANGED
    assert updated.stage == run.stage


def test_unknown_outcome_stops_without_repair(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "MEDIA"})
    updated = advance(run=run, outcome=outcome_for(run, kind="BLOCK", reason="OUTCOME_UNKNOWN"))
    assert updated.status is RunStatus.BLOCKED_UNKNOWN
    assert updated.repair_counts == ()


def test_missing_evidence_cannot_succeed(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "SCRIPT"})
    outcome = outcome_for(run).model_copy(update={"receipts": ()})
    updated = advance(run=run, outcome=outcome)
    assert updated.status is RunStatus.BLOCKED_CONFIGURATION
    assert updated.stage == run.stage


def test_repair_limit_stops_third_repair_of_same_unit(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "SCRIPT"})
    for _ in range(2):
        run = advance(run=run, outcome=outcome_for(run, kind="REWORK", unit_key="episode:1", repair_stage="SCRIPT"))
        assert run.status is RunStatus.RUNNING
    failed = advance(run=run, outcome=outcome_for(run, kind="REWORK", unit_key="episode:1", repair_stage="SCRIPT"))
    assert failed.status is RunStatus.FAILED_QUALITY


def test_third_final_evaluation_cannot_schedule_fourth(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "QUALITY", "final_evaluations": 2})
    updated = advance(run=run, outcome=outcome_for(run, kind="REWORK", unit_key="episode:1", repair_stage="RENDER"))
    assert updated.status is RunStatus.FAILED_QUALITY
    assert updated.final_evaluations == 3


def test_failed_target_prevents_success_after_export_task(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run_data["policy"]["max_target_episodes"] = 2
    run = RunSnapshot.model_validate({**run_data, "stage": "EXPORT", "targets": ["episode:1", "episode:2"]})
    updated = advance(run=run, outcome=outcome_for(run))
    assert updated.status is not RunStatus.SUCCEEDED


@pytest.mark.parametrize("kind", ["WAIVE", "SUCCESS", "DONE"])
def test_unsupported_labels_are_not_quality_decisions(run_data: dict, kind: str):
    from pydantic import ValidationError

    from r2.contracts.automation import RunSnapshot

    run = RunSnapshot.model_validate(run_data)
    with pytest.raises(ValidationError):
        outcome_for(run, kind=kind)


def test_semi_review_does_not_count_same_quality_evaluation_twice(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import OwnerReceipt, ReviewApproval, RunSnapshot, RunStatus

    run_data["policy"]["mode"] = "semi"
    run = RunSnapshot.model_validate({**run_data, "stage": "QUALITY"})
    outcome = outcome_for(run, owner_state="PASS")
    waiting = advance(run=run, outcome=outcome)
    assert waiting.final_evaluations == 1
    resumed = RunSnapshot.model_validate(
        {
            **waiting.model_dump(mode="python"),
            "status": "RUNNING",
            "pending_review": None,
            "review_approvals": [
                ReviewApproval(
                    checkpoint=waiting.pending_review.checkpoint,
                    binding_digest=waiting.pending_review.binding_digest,
                    actor_id="sponsor",
                    receipt=OwnerReceipt(owner="review", receipt_ref="approve-1", digest="sha256:" + "e" * 64),
                )
            ],
        }
    )
    advanced = advance(run=resumed, outcome=outcome)
    assert advanced.status is RunStatus.RUNNING
    assert advanced.final_evaluations == 1


def test_rework_cannot_jump_forward_past_quality(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "QUALITY"})
    changed = advance(run=run, outcome=outcome_for(run, kind="REWORK", repair_stage="EXPORT", unit_key="episode:1"))
    assert changed.status is RunStatus.BLOCKED_CONFIGURATION
    assert changed.stage == run.stage


def test_repair_fences_late_outcomes_and_preserves_unaffected_target(run_data: dict):
    from r2.automation.identity import policy_digest
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run_data["policy"]["max_target_episodes"] = 2
    run = RunSnapshot.model_validate({**run_data, "stage": "SCRIPT", "targets": ["episode:1", "episode:2"]})
    receipt = {"owner": "quality", "receipt_ref": "receipt-2", "digest": "sha256:" + "d" * 64}
    complete = {
        "target": "episode:2",
        "generation": 1,
        "input_digest": run.input_digest,
        "policy_digest": policy_digest(run.policy),
        "master_digest": "sha256:" + "e" * 64,
        "quality_run": receipt,
        "quality_decision": "PASS",
        "export": {**receipt, "owner": "export"},
        "final_digest": "sha256:" + "f" * 64,
        "archive_digest": "sha256:" + "1" * 64,
        "archive_size": 1234,
        "verified": True,
    }
    run = RunSnapshot.model_validate({**run.model_dump(mode="python"), "completed_targets": [complete]})
    late = outcome_for(run)
    changed = advance(run=run, outcome=outcome_for(run, kind="REWORK", repair_stage="SCRIPT", unit_key="episode:1"))
    assert changed.generation == 2
    assert [o.target for o in changed.completed_targets] == ["episode:2"]
    assert advance(run=changed, outcome=late).status is RunStatus.BLOCKED_INPUT_CHANGED


def test_all_verified_current_targets_allow_export_finality(run_data: dict):
    from r2.automation.identity import policy_digest
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "EXPORT"})
    receipt = {"owner": "quality", "receipt_ref": "receipt-1", "digest": "sha256:" + "d" * 64}
    complete = {
        "target": "episode:1",
        "generation": 1,
        "input_digest": run.input_digest,
        "policy_digest": policy_digest(run.policy),
        "master_digest": "sha256:" + "e" * 64,
        "quality_run": receipt,
        "quality_decision": "PASS",
        "export": {**receipt, "owner": "export"},
        "final_digest": "sha256:" + "f" * 64,
        "archive_digest": "sha256:" + "1" * 64,
        "archive_size": 1234,
        "verified": True,
    }
    run = RunSnapshot.model_validate({**run.model_dump(mode="python"), "completed_targets": [complete]})
    assert advance(run=run, outcome=outcome_for(run)).status is RunStatus.SUCCEEDED


def test_story_only_run_succeeds_at_the_handoff(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStage, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "HANDOFF", "status": "RUNNING", "end_stage": "HANDOFF"})
    updated = advance(run=run, outcome=outcome_for(run))
    assert (updated.status, updated.stage) == (RunStatus.SUCCEEDED, RunStage.HANDOFF)
    assert "end_stage" in updated.model_dump(mode="json")


def test_full_run_passes_the_handoff_and_keeps_its_stored_shape(run_data: dict):
    from r2.automation.transitions import advance
    from r2.contracts.automation import RunSnapshot, RunStage, RunStatus

    run = RunSnapshot.model_validate({**run_data, "stage": "HANDOFF", "status": "RUNNING"})
    updated = advance(run=run, outcome=outcome_for(run))
    assert (updated.status, updated.stage) == (RunStatus.RUNNING, RunStage.ASSET_ANALYSIS)
    assert "end_stage" not in updated.model_dump(mode="json")


def test_story_only_success_is_only_at_the_handoff(run_data: dict):
    from pydantic import ValidationError

    from r2.contracts.automation import RunSnapshot

    with pytest.raises(ValidationError):
        RunSnapshot.model_validate({**run_data, "stage": "STORY", "status": "SUCCEEDED", "end_stage": "HANDOFF"})
    with pytest.raises(ValidationError):
        RunSnapshot.model_validate({**run_data, "end_stage": "MEDIA"})
