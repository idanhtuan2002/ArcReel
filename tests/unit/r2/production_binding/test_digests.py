"""Fixed Preparation-canonical vectors for the first LOCATION binding packet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from r2.contracts import ProductionBinding
from r2.contracts.fingerprints import canonical_json_bytes
from r2.production_binding.digests import (
    binding_body_digest,
    binding_create_command_digest,
    binding_create_result_digest,
    binding_envelope_digest,
    binding_snapshot_digest,
    frame_source_claim_digest,
    scoped_location_binding_id,
    source_group_ref,
)

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_location_binding_v1_vectors.json"


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


def test_fixed_location_binding_v1_bytes_and_digests() -> None:
    cases = _cases()
    functions = {
        "binding_identity": lambda body: scoped_location_binding_id(
            user_id=body["user_id"], project_name=body["project_name"], target_id=body["target_id"]
        ),
        "source_group": lambda body: source_group_ref(**body),
        "binding_body": lambda body: binding_body_digest(ProductionBinding.model_validate(body)),
        "frame_claim_a": frame_source_claim_digest,
        "frame_claim_b": frame_source_claim_digest,
        "binding_envelope": binding_envelope_digest,
        "binding_create_command": binding_create_command_digest,
        "binding_create_result": binding_create_result_digest,
        "binding_snapshot": binding_snapshot_digest,
    }
    assert set(cases) == set(functions)
    for name, function in functions.items():
        case = cases[name]
        assert canonical_json_bytes({"domain": case["domain"], "canonical_version": "1", "body": case["body"]}) == case[
            "canonical"
        ].encode("utf-8"), name
        assert function(case["body"]) == case["digest"], name
        assert "object_ref" not in case["canonical"], name


def test_source_group_requires_two_distinct_sorted_frame_ids() -> None:
    cases = _cases()
    group = cases["source_group"]["body"]
    assert group["frame_candidate_ids"] == sorted(set(group["frame_candidate_ids"]))
    with pytest.raises(ValueError, match="two distinct"):
        source_group_ref(**{**group, "frame_candidate_ids": [group["frame_candidate_ids"][0]] * 2})
    with pytest.raises(ValueError, match="sorted"):
        source_group_ref(**{**group, "frame_candidate_ids": list(reversed(group["frame_candidate_ids"]))})


def test_binding_claim_and_snapshot_change_with_source_or_target() -> None:
    cases = _cases()
    claim = cases["frame_claim_a"]["body"]
    changed_claim = {**claim, "frame_content_digest": "sha256:" + "f" * 64}
    assert frame_source_claim_digest(changed_claim) != cases["frame_claim_a"]["digest"]

    snapshot = cases["binding_snapshot"]["body"]
    shot = snapshot["target_versions"][1]
    changed_snapshot = {
        **snapshot,
        "target_versions": [snapshot["target_versions"][0], {**shot, "version_digest": "sha256:" + "f" * 64}],
    }
    assert binding_snapshot_digest(changed_snapshot) != cases["binding_snapshot"]["digest"]


def test_vector_links_exact_body_claims_command_result_and_snapshot() -> None:
    cases = _cases()
    body = cases["binding_body"]["body"]
    envelope = cases["binding_envelope"]["body"]
    command = cases["binding_create_command"]["body"]
    result = cases["binding_create_result"]["body"]
    snapshot = cases["binding_snapshot"]["body"]

    assert body["id"] == cases["binding_identity"]["digest"] == envelope["binding_id"]
    assert body["production_ref"] == cases["source_group"]["digest"]
    assert body["asset_refs"] == cases["source_group"]["body"]["frame_candidate_ids"]
    assert envelope["binding_body_digest"] == cases["binding_body"]["digest"]
    assert envelope["target_ref"] == command["expected_target_ref"] == result["target_ref"]
    assert envelope["scene_ref"] == snapshot["target_versions"][0]
    assert envelope["target_ref"] == snapshot["target_versions"][1]
    assert [claim["frame_candidate_id"] for claim in envelope["ordered_claims"]] == body["asset_refs"]
    for letter, claim in zip("ab", envelope["ordered_claims"], strict=True):
        assert claim["claim_digest"] == cases[f"frame_claim_{letter}"]["digest"]
        assert {key: value for key, value in claim.items() if key != "claim_digest"} == cases[f"frame_claim_{letter}"][
            "body"
        ]
    assert command["ordered_frame_receipts"] == [
        {"receipt_id": claim["receipt_id"], "receipt_digest": claim["receipt_digest"]}
        for claim in envelope["ordered_claims"]
    ]
    assert result["command_digest"] == cases["binding_create_command"]["digest"]
    assert result["envelope_digest"] == cases["binding_envelope"]["digest"]
    assert snapshot["ordered_bindings"] == [
        {"binding_id": body["id"], "version": body["version"], "envelope_digest": cases["binding_envelope"]["digest"]}
    ]


def test_v1_location_body_rejects_other_roles_and_frame_counts() -> None:
    body = _cases()["binding_body"]["body"]
    for changed in (
        {"role": "PROP"},
        {"target_type": "SCENE"},
        {"asset_refs": body["asset_refs"][:1]},
        {"variant_ref": "camera-a"},
        {"id": "m8b:invalid"},
    ):
        with pytest.raises(ValueError, match="outside the LOCATION"):
            binding_body_digest(ProductionBinding.model_validate({**body, **changed}))
