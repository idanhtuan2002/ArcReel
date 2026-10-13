"""Identities that bind an admitted R2 spatial shot from its route to the M7 submit.

The task ID is derived from the command scope, so the host request can carry it before
enqueue. The submit fingerprint is computed after the host request digest, so it never feeds
back into the bytes it covers.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from r2.contracts import PromptPlan, ProviderRequest
from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.shot_generation import R2ExecutionProfileV1, R2ShotGenerationTaskV1

SUBMIT_FINGERPRINT_DOMAIN = "r2.m8.spatial.submit.v1"
_TASK_ID_DOMAIN = "r2.m8.spatial.shot_task.v1"


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(value))).hexdigest()


def _envelope(domain: str, body: Mapping[str, Any]) -> str:
    return _digest({"domain": domain, "canonical_version": "1", "body": dict(body)})


def shot_task_id(*, user_id: str, project_name: str, command_id: str) -> str:
    digest = _envelope(_TASK_ID_DOMAIN, {"user_id": user_id, "project_name": project_name, "command_id": command_id})
    return "r2shot-" + digest.removeprefix("sha256:")[:40]


def prompt_plan_digest(plan: PromptPlan) -> str:
    return _digest(plan.model_dump(mode="json"))


def compiled_request_digest(request: ProviderRequest) -> str:
    return _digest(request.model_dump(mode="json"))


def host_request_digest(request: ProviderRequest) -> str:
    """The digest M7 records as the attempt's ``request_digest`` for this exact host request."""
    return _digest(request.model_dump(mode="json"))


def submit_fingerprint(task: Mapping[str, Any], profile: R2ExecutionProfileV1) -> str:
    """``r2.m8.spatial.submit.v1`` over the task's identity fields and the exact profile route."""
    body = {key: value for key, value in task.items() if key != "submit_fingerprint"}
    return _envelope(
        SUBMIT_FINGERPRINT_DOMAIN,
        {
            "task": body,
            "route": {
                "provider": profile.provider_id,
                "model": profile.provider_model_id,
                "endpoint": profile.endpoint_id,
                "adapter_version": profile.adapter_version,
                "capability_profile_ref": profile.capability_profile_ref,
            },
        },
    )


def verify_task_evidence(task: R2ShotGenerationTaskV1, profile: R2ExecutionProfileV1) -> None:
    if task.execution_profile_ref != profile.profile_ref:
        raise ValueError("task evidence names a different execution profile")
    if submit_fingerprint(task.model_dump(mode="json"), profile) != task.submit_fingerprint:
        raise ValueError("task evidence submit fingerprint does not match its fields")
    if task.task_id != shot_task_id(user_id=task.user_id, project_name=task.project_name, command_id=task.command_id):
        raise ValueError("task evidence task ID does not match its command scope")


__all__ = [
    "SUBMIT_FINGERPRINT_DOMAIN",
    "compiled_request_digest",
    "host_request_digest",
    "prompt_plan_digest",
    "shot_task_id",
    "submit_fingerprint",
    "verify_task_evidence",
]
