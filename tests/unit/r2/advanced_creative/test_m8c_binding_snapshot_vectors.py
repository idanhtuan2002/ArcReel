"""Proposed M8-C binding and snapshot canonical vectors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts import ProductionBinding

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_binding_snapshot_vectors.json"


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


def test_binding_snapshot_vectors_have_fixed_bytes_and_digests() -> None:
    cases = _cases()
    assert set(cases) == {
        "binding_body_v2",
        "binding_envelope_approved",
        "binding_snapshot_approved",
        "binding_envelope_tampered",
        "binding_snapshot_tampered",
    }
    for name, case in cases.items():
        envelope = {"domain": case["domain"], "canonical_version": "1", "body": case["body"]}
        expected_bytes = case["canonical"].encode("utf-8")
        assert canonical_json_bytes(envelope) == expected_bytes, name
        assert digest_canonical(envelope) == case["digest"], name
        assert "sha256:" + hashlib.sha256(expected_bytes).hexdigest() == case["digest"], name
        assert "object_ref" not in case["canonical"], name


def test_snapshot_digest_binds_spatial_set_even_with_identical_binding_body() -> None:
    cases = _cases()
    body = cases["binding_body_v2"]
    assert ProductionBinding.model_validate(body["body"]).model_dump(mode="json") == body["body"]

    approved = cases["binding_envelope_approved"]["body"]
    tampered = cases["binding_envelope_tampered"]["body"]
    assert {key: value for key, value in approved.items() if key != "spatial_set_digest"} == {
        key: value for key, value in tampered.items() if key != "spatial_set_digest"
    }
    assert approved["binding_body_digest"] == tampered["binding_body_digest"] == body["digest"]
    assert approved["binding_version"] == tampered["binding_version"] == 2
    assert approved["spatial_set_id"] == tampered["spatial_set_id"]
    assert approved["spatial_set_digest"] != tampered["spatial_set_digest"]
    assert (approved["target_type"], approved["target_id"]) == (body["body"]["target_type"], body["body"]["target_id"])
    assert cases["binding_envelope_approved"]["digest"] != cases["binding_envelope_tampered"]["digest"]

    approved_snapshot = cases["binding_snapshot_approved"]["body"]
    tampered_snapshot = cases["binding_snapshot_tampered"]["body"]
    assert {key: value for key, value in approved_snapshot.items() if key != "ordered_bindings"} == {
        key: value for key, value in tampered_snapshot.items() if key != "ordered_bindings"
    }
    assert approved_snapshot["target_versions"] == tampered_snapshot["target_versions"]
    assert [target["target_type"] for target in approved_snapshot["target_versions"]] == ["SCENE", "SHOT"]
    shot_target = approved_snapshot["target_versions"][1]
    assert (approved["target_registry_version"], approved["target_digest"]) == (
        shot_target["registry_version"],
        shot_target["digest"],
    )
    assert [
        {key: value for key, value in binding.items() if key != "envelope_digest"}
        for binding in approved_snapshot["ordered_bindings"]
    ] == [
        {key: value for key, value in binding.items() if key != "envelope_digest"}
        for binding in tampered_snapshot["ordered_bindings"]
    ]
    assert approved_snapshot["ordered_bindings"][0]["envelope_digest"] == cases["binding_envelope_approved"]["digest"]
    assert tampered_snapshot["ordered_bindings"][0]["envelope_digest"] == cases["binding_envelope_tampered"]["digest"]
    assert cases["binding_snapshot_approved"]["digest"] != cases["binding_snapshot_tampered"]["digest"]
