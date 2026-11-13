"""Canonical identities for receipt replay and generation fencing."""

from __future__ import annotations

import hashlib
from uuid import NAMESPACE_URL, uuid5

from r2.contracts.automation import RunPolicy, RunStage, StepIdentity
from r2.contracts.common import JSONValue, ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes


def digest_value(domain: str, body: JSONValue) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes({"domain": domain, "body": body})).hexdigest()


_LATER_DEFAULTS = {
    "image_candidates": 1,
    "image_judge_identity": None,
    "image_judge_prompt_digest": None,
    "continuity_judge_identity": None,
    "continuity_judge_prompt_digest": None,
    "continuity_judge_max_pictures": None,
}


def policy_digest(policy: RunPolicy) -> str:
    policy = RunPolicy.model_validate(policy)
    body = policy.model_dump(mode="json")
    body["checkpoints"] = sorted(c.value for c in policy.checkpoints or ())
    # Fields added after runs were frozen leave the digest unchanged at their defaults, so earlier runs keep theirs.
    for field, default in _LATER_DEFAULTS.items():
        if body.get(field) == default:
            body.pop(field, None)
    return digest_value("r2.production-policy.v1", ensure_json_value(body))


def derive_step_identity(
    *,
    run_id: str,
    stage: RunStage,
    unit_key: str,
    generation: int,
    input_digest: str,
    policy_digest: str,
    repair_index: int,
) -> StepIdentity:
    provisional = StepIdentity(
        run_id=run_id,
        stage=stage,
        unit_key=unit_key,
        generation=generation,
        input_digest=input_digest,
        policy_digest=policy_digest,
        repair_index=repair_index,
        command_id="pending",
        task_id="pending",
    )
    body = provisional.model_dump(mode="json", exclude={"command_id", "task_id"})
    digest = digest_value("r2.production-step.v1", ensure_json_value(body))
    return provisional.model_copy(
        update={
            "command_id": "auto-" + digest.removeprefix("sha256:"),
            "task_id": str(uuid5(NAMESPACE_URL, "r2.production-task.v1:" + digest)),
        }
    )
