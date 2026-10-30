"""Production checkpoints are decisions on exact stage evidence."""

from __future__ import annotations

from r2.automation.identity import digest_value, policy_digest
from r2.contracts.automation import Checkpoint, RunPolicy, RunSnapshot, RunStage, StageOutcome
from r2.contracts.common import ensure_json_value

_CHECKPOINTS = {
    RunStage.STORY: Checkpoint.STORY_MANUSCRIPT,
    RunStage.SCRIPT: Checkpoint.SCRIPT_PACKAGE,
    RunStage.QUALITY: Checkpoint.FINAL_FILM,
}


def checkpoint_for(*, policy: RunPolicy, stage: RunStage) -> Checkpoint | None:
    checkpoint = _CHECKPOINTS.get(stage)
    return checkpoint if checkpoint in (policy.checkpoints or ()) else None


def review_binding(*, run: RunSnapshot, outcome: StageOutcome) -> str:
    return digest_value(
        "r2.production-review.v1",
        ensure_json_value(
            {
                "user_id": run.user_id,
                "project_name": run.project_name,
                "run_id": run.run_id,
                "generation": run.generation,
                "stage": run.stage.value,
                "input_digest": run.input_digest,
                "policy_digest": policy_digest(run.policy),
                "receipts": [
                    r.model_dump(mode="json")
                    for r in sorted(
                        outcome.receipts, key=lambda receipt: (receipt.owner, receipt.receipt_ref, receipt.digest)
                    )
                ],
            }
        ),
    )
