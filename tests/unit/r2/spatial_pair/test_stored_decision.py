"""Stored pair decisions must rehash and match their scoped FK columns."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from lib.db.models.spatial_pair import SpatialPairDecisionModel
from lib.db.repositories.spatial_pair import SpatialPairIntegrityError, verify_stored_pair_decision
from r2.contracts.production_target import TargetVersionRef

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_pair_contract_vectors.json"


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text())["cases"]}


def _row() -> SpatialPairDecisionModel:
    cases = _cases()
    body = cases["pair_decision_approve"]["body"]
    command = body["command"]
    return SpatialPairDecisionModel(
        user_id=command["user_id"],
        project_name=command["project_name"],
        pair_id=body["pair_id"],
        pair_version=body["pair_version"],
        decision_body_json=body,
        decision_digest=cases["pair_decision_approve"]["digest"],
        command_digest=body["command_digest"],
        authorization_digest=body["authorization_digest"],
        binding_id=command["binding_id"],
        binding_version=command["expected_binding_version"],
        binding_envelope_digest=command["expected_envelope_digest"],
        binding_core_digest=command["expected_core_digest"],
        target_type=command["expected_target_ref"]["target_type"],
        target_id=command["expected_target_ref"]["target_id"],
        target_registry_version=command["expected_target_ref"]["registry_version"],
        target_version_digest=command["expected_target_ref"]["version_digest"],
        scene_type=command["expected_scene_ref"]["target_type"],
        scene_id=command["expected_scene_ref"]["target_id"],
        scene_registry_version=command["expected_scene_ref"]["registry_version"],
        scene_version_digest=command["expected_scene_ref"]["version_digest"],
        master_receipt_id=command["views"][0]["receipt_id"],
        reverse_receipt_id=command["views"][1]["receipt_id"],
        decision=command["decision"],
        created_at=datetime.now(UTC),
    )


def _verify(row: SpatialPairDecisionModel) -> None:
    command = _cases()["pair_decision_approve"]["body"]["command"]
    verified = verify_stored_pair_decision(
        row,
        user_id=command["user_id"],
        project_name=command["project_name"],
        binding_id=command["binding_id"],
        expected_binding_version=command["expected_binding_version"],
        expected_envelope_digest=command["expected_envelope_digest"],
        expected_core_digest=command["expected_core_digest"],
        expected_target_ref=TargetVersionRef.model_validate(command["expected_target_ref"]),
        expected_scene_ref=TargetVersionRef.model_validate(command["expected_scene_ref"]),
    )
    assert verified.decision_digest == _cases()["pair_decision_approve"]["digest"]


def test_stored_pair_decision_matches_exact_vector() -> None:
    _verify(_row())


@pytest.mark.parametrize(
    "tamper",
    [
        "body",
        "decision_digest",
        "authorization",
        "command_digest",
        "binding",
        "target",
        "scene",
        "frame",
        "action",
        "scope",
    ],
)
def test_stored_pair_decision_rejects_drift(tamper: str) -> None:
    row = _row()
    if tamper == "body":
        row.decision_body_json = row.decision_body_json | {"reviewer_id": "other"}
    elif tamper == "decision_digest":
        row.decision_digest = "sha256:" + "f" * 64
    elif tamper == "authorization":
        row.authorization_digest = "sha256:" + "f" * 64
    elif tamper == "command_digest":
        row.command_digest = "sha256:" + "f" * 64
    elif tamper == "binding":
        row.binding_core_digest = "sha256:" + "f" * 64
    elif tamper == "target":
        row.target_version_digest = "sha256:" + "f" * 64
    elif tamper == "scene":
        row.scene_version_digest = "sha256:" + "f" * 64
    elif tamper == "frame":
        row.reverse_receipt_id = row.master_receipt_id
    elif tamper == "action":
        row.decision = "REJECT"
    else:
        row.project_name = "other"
    with pytest.raises(SpatialPairIntegrityError, match="pair decision integrity"):
        _verify(row)
