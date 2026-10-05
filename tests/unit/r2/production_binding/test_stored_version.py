"""A stored LOCATION binding is rehashed before its columns are trusted."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lib.db.models.production_binding import ProductionBindingVersionModel
from lib.db.repositories.production_binding import ProductionBindingIntegrityError, verify_stored_binding_version
from r2.contracts.production_target import TargetVersionRef

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_location_binding_v1_vectors.json"


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


def _row() -> ProductionBindingVersionModel:
    cases = _cases()
    body = cases["binding_body"]["body"]
    envelope = cases["binding_envelope"]["body"]
    return ProductionBindingVersionModel(
        user_id="u1",
        project_name="demo",
        binding_id=body["id"],
        binding_version=body["version"],
        binding_body_json=body,
        binding_body_digest=cases["binding_body"]["digest"],
        envelope_json=envelope,
        envelope_digest=cases["binding_envelope"]["digest"],
        target_type="SHOT",
        target_id=envelope["target_ref"]["target_id"],
        target_registry_version=envelope["target_ref"]["registry_version"],
        target_version_digest=envelope["target_ref"]["version_digest"],
        scene_type="SCENE",
        scene_id=envelope["scene_ref"]["target_id"],
        scene_registry_version=envelope["scene_ref"]["registry_version"],
        scene_version_digest=envelope["scene_ref"]["version_digest"],
        receipt_a_id=body["asset_refs"][0],
        receipt_b_id=body["asset_refs"][1],
        created_at=datetime.now(UTC),
    )


def _verify(row: ProductionBindingVersionModel) -> None:
    envelope = _cases()["binding_envelope"]["body"]
    verified = verify_stored_binding_version(
        row,
        user_id="u1",
        project_name="demo",
        expected_target_ref=TargetVersionRef.model_validate(envelope["target_ref"]),
        expected_scene_ref=TargetVersionRef.model_validate(envelope["scene_ref"]),
    )
    assert verified.envelope_digest == _cases()["binding_envelope"]["digest"]


def test_stored_binding_version_matches_exact_vector() -> None:
    _verify(_row())


@pytest.mark.parametrize(
    "tamper",
    ["body", "body_digest", "claim", "envelope_digest", "target", "scene", "receipt", "parent", "scope"],
)
def test_stored_binding_version_rejects_drift(tamper: str) -> None:
    row = _row()
    if tamper == "body":
        row.binding_body_json = row.binding_body_json | {"semantic_ref": "location:changed"}
    elif tamper == "body_digest":
        row.binding_body_digest = "sha256:" + "f" * 64
    elif tamper == "claim":
        row.envelope_json = row.envelope_json | {
            "ordered_claims": [
                row.envelope_json["ordered_claims"][0] | {"frame_byte_size": 257},
                row.envelope_json["ordered_claims"][1],
            ]
        }
    elif tamper == "envelope_digest":
        row.envelope_digest = "sha256:" + "f" * 64
    elif tamper == "target":
        row.target_version_digest = "sha256:" + "f" * 64
    elif tamper == "scene":
        row.scene_version_digest = "sha256:" + "f" * 64
    elif tamper == "receipt":
        row.receipt_a_id = "m8f:" + "f" * 64
    elif tamper == "parent":
        claims = row.envelope_json["ordered_claims"]
        row.envelope_json = row.envelope_json | {
            "ordered_claims": [claims[0], claims[1] | {"parent_artifact_key": claims[0]["parent_artifact_key"]}]
        }
    else:
        row.project_name = "other"
    with pytest.raises(ProductionBindingIntegrityError, match="binding version integrity"):
        _verify(row)
