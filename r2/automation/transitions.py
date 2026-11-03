"""Pure transitions over owner-inspected evidence; never dispatches or mints authority."""

from __future__ import annotations

from r2.automation.identity import digest_value, policy_digest
from r2.automation.policy import checkpoint_for, review_binding
from r2.automation.profiles import resolve_launch_profile
from r2.contracts.automation import PendingReview, RepairCount, RunSnapshot, RunStage, RunStatus, StageOutcome

_STAGES = tuple(RunStage)
_STORY_BLOCKS = {
    "BLOCKED_QUALITY": RunStatus.FAILED_QUALITY,
    "MODEL_UNAVAILABLE": RunStatus.BLOCKED_CONFIGURATION,
    "BLOCKED_BUDGET": RunStatus.BLOCKED_BUDGET,
    "RECOVERY_INCONSISTENT": RunStatus.BLOCKED_UNKNOWN,
}


def _passing_quality_states(run: RunSnapshot) -> frozenset[str]:
    """Quality owner states that let a run continue: a PASS, and under a recording quality gate a recorded REWORK."""
    if resolve_launch_profile(run.policy.launch_profile_id).quality_gate == "record":
        return frozenset({"PASS", "QUALITY_RECORDED_REWORK"})
    return frozenset({"PASS"})


def _updated(run: RunSnapshot, **changes: object) -> RunSnapshot:
    return RunSnapshot.model_validate({**run.model_dump(mode="python"), "version": run.version + 1, **changes})


def _blocked(run: RunSnapshot, status: RunStatus, reason: str) -> RunSnapshot:
    return _updated(run, status=status, reason=reason, pending_review=None)


def advance(*, run: RunSnapshot, outcome: StageOutcome) -> RunSnapshot:
    run = RunSnapshot.model_validate(run)
    outcome = StageOutcome.model_validate(outcome)
    if run.status not in {RunStatus.RUNNING, RunStatus.WAITING_TASK}:
        raise ValueError("run is not advancing")
    if (outcome.stage, outcome.generation, outcome.input_digest, outcome.policy_digest) != (
        run.stage,
        run.generation,
        run.input_digest,
        policy_digest(run.policy),
    ):
        return _blocked(run, RunStatus.BLOCKED_INPUT_CHANGED, "INPUT_OR_AUTHORITY_MOVED")
    if outcome.kind == "WAIT":
        return _updated(run, status=RunStatus.WAITING_TASK)
    if outcome.kind == "BLOCK":
        reason = outcome.reason or "REQUIRED_EVIDENCE_MISSING"
        status = {
            "OUTCOME_UNKNOWN": RunStatus.BLOCKED_UNKNOWN,
            "USAGE_UNKNOWN": RunStatus.BLOCKED_UNKNOWN,
            "BUDGET_EXHAUSTED": RunStatus.BLOCKED_BUDGET,
            "RESOURCE_UNAVAILABLE": RunStatus.BLOCKED_RESOURCE,
            "EXTERNAL_INPUT_CHANGED": RunStatus.BLOCKED_INPUT_CHANGED,
            "FAILED_QUALITY": RunStatus.FAILED_QUALITY,
        }.get(reason, RunStatus.BLOCKED_CONFIGURATION)
        return _blocked(run, status, reason)
    if not outcome.receipts:
        return _blocked(run, RunStatus.BLOCKED_CONFIGURATION, "REQUIRED_EVIDENCE_MISSING")
    if run.stage in {RunStage.STORY, RunStage.STORY_COMMIT}:
        expected = "READY_FOR_APPROVAL" if run.stage is RunStage.STORY else "COMMITTED"
        if outcome.owner_state != expected:
            return _blocked(
                run,
                _STORY_BLOCKS.get(outcome.owner_state or "", RunStatus.BLOCKED_UNKNOWN),
                outcome.owner_state or "STORY_PHASE_MISSING",
            )
    if run.stage is RunStage.QUALITY:
        evaluation = digest_value(
            "r2.final-evaluation.v1",
            {
                "binding": review_binding(run=run, outcome=outcome),
                "owner_state": outcome.owner_state,
            },
        )
        if evaluation not in run.final_evaluation_receipts:
            if run.final_evaluations >= run.policy.final_evaluation_limit:
                return _blocked(run, RunStatus.FAILED_QUALITY, "FINAL_EVALUATION_LIMIT")
            run = run.model_copy(
                update={
                    "final_evaluations": run.final_evaluations + 1,
                    "final_evaluation_receipts": (*run.final_evaluation_receipts, evaluation),
                }
            )
    if outcome.kind == "REWORK":
        if outcome.repair_stage is None or outcome.unit_key is None:
            return _blocked(run, RunStatus.BLOCKED_CONFIGURATION, "INVALID_REWORK_SCOPE")
        if _STAGES.index(outcome.repair_stage) > _STAGES.index(run.stage):
            return _blocked(run, RunStatus.BLOCKED_CONFIGURATION, "INVALID_REWORK_SCOPE")
        counts = {(r.stage, r.unit_key): r.count for r in run.repair_counts}
        key = (outcome.repair_stage, outcome.unit_key)
        if counts.get(key, 0) >= run.policy.unit_repair_limit or (
            run.stage is RunStage.QUALITY and run.final_evaluations >= run.policy.final_evaluation_limit
        ):
            return _blocked(run, RunStatus.FAILED_QUALITY, "REPAIR_LIMIT")
        counts[key] = counts.get(key, 0) + 1
        affected = {
            target
            for target in run.targets
            if (outcome.unit_key == target or outcome.unit_key.startswith(target + ":"))
        }
        if not affected or _STAGES.index(outcome.repair_stage) <= _STAGES.index(RunStage.EPISODE_PLAN):
            affected = set(run.targets)
        return _updated(
            run,
            stage=outcome.repair_stage,
            status=RunStatus.RUNNING,
            pending_review=None,
            repair_counts=tuple(RepairCount(stage=s, unit_key=u, count=n) for (s, u), n in counts.items()),
            generation=run.generation + 1,
            reason=None,
            completed_targets=tuple(o for o in run.completed_targets if o.target not in affected),
        )
    if run.stage is RunStage.QUALITY and outcome.owner_state not in _passing_quality_states(run):
        return _blocked(run, RunStatus.FAILED_QUALITY, "CURRENT_QUALITY_PASS_REQUIRED")
    checkpoint = checkpoint_for(policy=run.policy, stage=run.stage)
    if checkpoint is not None:
        binding = review_binding(run=run, outcome=outcome)
        approved = any(a.checkpoint == checkpoint and a.binding_digest == binding for a in run.review_approvals)
        if not approved:
            return _updated(
                run,
                status=RunStatus.WAITING_REVIEW,
                pending_review=PendingReview(checkpoint=checkpoint, binding_digest=binding),
            )
    if run.stage is RunStage.EXPORT:
        produced = {output.target: output for output in run.completed_targets}
        produced.update({output.target: output for output in outcome.outputs if output.target in run.targets})
        run = run.model_copy(update={"completed_targets": tuple(produced[t] for t in run.targets if t in produced)})
        targets = {
            output.target
            for output in run.completed_targets
            if (
                output.generation <= run.generation
                and output.input_digest == run.input_digest
                and output.policy_digest == policy_digest(run.policy)
            )
        }
        if not run.targets or targets != set(run.targets):
            return _blocked(run, RunStatus.BLOCKED_CONFIGURATION, "OUTPUTS_INCOMPLETE")
        return _updated(run, status=RunStatus.SUCCEEDED, reason=None, pending_review=None)
    return _updated(
        run, stage=_STAGES[_STAGES.index(run.stage) + 1], status=RunStatus.RUNNING, reason=None, pending_review=None
    )
