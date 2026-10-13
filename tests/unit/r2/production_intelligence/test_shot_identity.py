"""R2 shot identities: a command-scoped task ID and a submit fingerprint over every evidence field."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from r2.contracts import ProviderRequest
from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.shot_generation import R2ShotGenerationTaskV1
from r2.production_intelligence.shot_identity import (
    host_request_digest,
    shot_task_id,
    submit_fingerprint,
    verify_task_evidence,
)
from r2.production_intelligence.shot_profiles import WAN27_TWO_VIEW_PROFILE

D = "sha256:" + "a" * 64


def _evidence(**overrides: Any) -> R2ShotGenerationTaskV1:
    body: dict[str, Any] = {
        "schema_version": "r2_shot_generation_v1",
        "user_id": "default",
        "project_name": "demo",
        "task_id": shot_task_id(user_id="default", project_name="demo", command_id="shot-1"),
        "command_id": "shot-1",
        "target_type": "SHOT",
        "target_id": "take:shot-1",
        "target_registry_version": 1,
        "target_digest": D,
        "binding_snapshot_digest": D,
        "spatial_set_digests": [D],
        "ordered_source_frames": [
            {
                "image_index": 1,
                "view": "MASTER",
                "receipt_id": "m8f:" + "1" * 64,
                "receipt_digest": D,
                "frame_content_digest": D,
            },
            {
                "image_index": 2,
                "view": "REVERSE",
                "receipt_id": "m8f:" + "2" * 64,
                "receipt_digest": D,
                "frame_content_digest": D,
            },
        ],
        "execution_profile_ref": WAN27_TWO_VIEW_PROFILE.profile_ref,
        "prompt_plan_digest": D,
        "compiled_request_digest": D,
        "provider_prompt_digest": D,
        "provider_payload_digest": D,
        "host_request_digest": D,
        "submit_fingerprint": D,
    }
    body.update(overrides)
    body["submit_fingerprint"] = submit_fingerprint(body, WAN27_TWO_VIEW_PROFILE)
    return R2ShotGenerationTaskV1.model_validate(body)


def test_the_task_id_is_stable_and_scoped_to_the_command() -> None:
    first = shot_task_id(user_id="default", project_name="demo", command_id="shot-1")

    assert first == shot_task_id(user_id="default", project_name="demo", command_id="shot-1")
    assert first != shot_task_id(user_id="default", project_name="demo", command_id="shot-2")
    assert first != shot_task_id(user_id="other", project_name="demo", command_id="shot-1")


def test_valid_evidence_verifies() -> None:
    verify_task_evidence(_evidence(), WAN27_TWO_VIEW_PROFILE)


@pytest.mark.parametrize(
    "field", ["binding_snapshot_digest", "provider_payload_digest", "host_request_digest", "compiled_request_digest"]
)
def test_any_changed_evidence_field_breaks_the_fingerprint(field: str) -> None:
    evidence = _evidence()
    changed = evidence.model_copy(update={field: "sha256:" + "b" * 64})

    with pytest.raises(ValueError, match="fingerprint"):
        verify_task_evidence(changed, WAN27_TWO_VIEW_PROFILE)


def test_a_task_id_outside_its_command_scope_is_refused() -> None:
    with pytest.raises(ValueError, match="task ID"):
        verify_task_evidence(_evidence(task_id="r2shot-forged"), WAN27_TWO_VIEW_PROFILE)


def test_the_host_request_digest_is_the_m7_request_digest() -> None:
    request = ProviderRequest(
        id="t:video-submit",
        host_task_ref="t",
        provider="dashscope",
        model="wan2.7-r2v-2026-06-12",
        endpoint="video-synthesis",
        payload={"prompt": "p"},
        execution_options={"provider_payload_digest": D},
        adapter_version="host-video-v1",
    )
    m7 = (
        "sha256:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(request.model_dump(mode="json")))).hexdigest()
    )

    assert host_request_digest(request) == m7
