"""Exact typed bodies for proposed spatial pair decisions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.spatial_pair import PairAuthorizationV1, PairDecisionCommandV1, PairDecisionV1
from r2.spatial_pair.digests import pair_authorization_digest, pair_command_digest, pair_decision_digest, scoped_pair_id

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_location_binding_v1_vectors.json"
PAIR_FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_pair_contract_vectors.json"


def _binding_cases() -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in json.loads(FIXTURE.read_text())["cases"]}


def _pair_cases() -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in json.loads(PAIR_FIXTURE.read_text())["cases"]}


def test_fixed_pair_identity_command_and_decision_bytes() -> None:
    cases = _pair_cases()
    assert set(cases) == {
        "pair_identity",
        "pair_command_approve",
        "pair_authorization_approve",
        "pair_decision_approve",
        "pair_command_reject",
        "pair_authorization_reject",
        "pair_decision_reject",
    }
    for name, case in cases.items():
        canonical = canonical_json_bytes({"domain": case["domain"], "canonical_version": "1", "body": case["body"]})
        assert canonical == case["canonical"].encode("utf-8"), name
        expected = ("m8p:" if name == "pair_identity" else "sha256:") + hashlib.sha256(canonical).hexdigest()
        assert expected == case["digest"], name
        if name == "pair_identity":
            actual = scoped_pair_id(**case["body"])
        elif name.startswith("pair_command"):
            actual = pair_command_digest(case["body"])
        elif name.startswith("pair_authorization"):
            actual = pair_authorization_digest(case["body"])
        else:
            actual = pair_decision_digest(case["body"])
            command_name = name.replace("decision", "command")
            authorization_name = name.replace("decision", "authorization")
            assert case["body"]["command"] == cases[command_name]["body"]
            assert case["body"]["command_digest"] == cases[command_name]["digest"]
            assert case["body"]["authorization"] == cases[authorization_name]["body"]
            assert case["body"]["authorization_digest"] == cases[authorization_name]["digest"]
            assert case["body"]["pair_id"] == cases["pair_identity"]["digest"]
        assert actual == expected, name
        assert "object_ref" not in case["canonical"]


def test_pair_vector_changes_with_review_or_role_assignment() -> None:
    cases = _pair_cases()
    approve = cases["pair_command_approve"]["body"]
    altered_review = {**approve, "observations": {**approve["observations"], "yaw_relation": "Different angle."}}
    assert pair_command_digest(altered_review) != cases["pair_command_approve"]["digest"]
    altered_views = [approve["views"][0] | {"receipt_id": approve["views"][1]["receipt_id"]}, approve["views"][1]]
    with pytest.raises(ValidationError):
        pair_command_digest({**approve, "views": altered_views})


def _command(*, decision: str = "APPROVE") -> dict[str, Any]:
    cases = _binding_cases()
    envelope = cases["binding_envelope"]["body"]
    claims = envelope["ordered_claims"]
    return {
        "user_id": "u1",
        "project_name": "demo",
        "principal": "human:reviewer-1",
        "command_id": "pair-command-1",
        "expected_scene_ref": envelope["scene_ref"],
        "expected_target_ref": envelope["target_ref"],
        "binding_id": envelope["binding_id"],
        "expected_binding_version": 1,
        "expected_envelope_digest": cases["binding_envelope"]["digest"],
        "expected_core_digest": cases["binding_core"]["digest"],
        "views": [
            {"role": "MASTER", "receipt_id": claims[0]["receipt_id"], "receipt_digest": claims[0]["receipt_digest"]},
            {"role": "REVERSE", "receipt_id": claims[1]["receipt_id"], "receipt_digest": claims[1]["receipt_digest"]},
        ],
        "decision": decision,
        "observations": {
            "view_coverage": "Both views show the same doorway and floor edge.",
            "camera_center": "The doorway alignment supports a common camera center.",
            "yaw_relation": "The reverse view faces approximately opposite the master view.",
            "rejection_reason": None,
        },
    }


def test_pair_contract_binds_role_order_command_and_authorization() -> None:
    command = PairDecisionCommandV1.model_validate(_command())
    digest = pair_command_digest(command.model_dump(mode="json"))
    pair_id = scoped_pair_id(user_id=command.user_id, project_name=command.project_name, binding_id=command.binding_id)
    authorization = PairAuthorizationV1(
        user_id=command.user_id,
        project_name=command.project_name,
        authenticated_principal=command.principal,
        authority_role="HUMAN_SHOWRUNNER",
        command_digest=digest,
        authorization_ref="grant-receipt-1",
        authenticated_at=datetime(2026, 10, 6, 1, 0, tzinfo=UTC),
    )
    decision = PairDecisionV1(
        command=command,
        command_digest=digest,
        pair_id=pair_id,
        pair_version=1,
        reviewer_id=command.principal,
        authorization=authorization,
        authorization_digest=pair_authorization_digest(authorization.model_dump(mode="json")),
        decided_at=datetime(2026, 10, 6, 1, 1, tzinfo=UTC),
    )
    assert pair_decision_digest(decision.model_dump(mode="json")).startswith("sha256:")
    assert PairDecisionV1.model_validate(decision.model_dump(mode="json")) == decision


def test_pair_command_rejects_duplicate_roles_frames_and_missing_review() -> None:
    base = _command()
    for changed in (
        {"views": [base["views"][0], base["views"][0]]},
        {"views": list(reversed(base["views"]))},
        {"views": [base["views"][0], {**base["views"][1], "receipt_id": base["views"][0]["receipt_id"]}]},
        {"observations": {**base["observations"], "yaw_relation": None}},
        {"expected_binding_version": 0},
    ):
        with pytest.raises(ValidationError):
            PairDecisionCommandV1.model_validate(base | changed)


def test_pair_reject_requires_reason_and_decision_checks_authorization_binding() -> None:
    reject = _command(decision="REJECT")
    with pytest.raises(ValidationError):
        PairDecisionCommandV1.model_validate(reject)
    reject["observations"] = {
        "view_coverage": None,
        "camera_center": None,
        "yaw_relation": "Views face the same direction.",
        "rejection_reason": "No reverse view is present.",
    }
    command = PairDecisionCommandV1.model_validate(reject)
    digest = pair_command_digest(command.model_dump(mode="json"))
    authorization = PairAuthorizationV1(
        user_id="u1",
        project_name="demo",
        authenticated_principal="human:reviewer-1",
        authority_role="HUMAN_SHOWRUNNER",
        command_digest=digest,
        authorization_ref="grant-receipt-2",
        authenticated_at=datetime(2026, 10, 6, 1, 0, tzinfo=UTC),
    )
    base = {
        "command": command.model_dump(mode="json"),
        "command_digest": digest,
        "pair_id": scoped_pair_id(user_id="u1", project_name="demo", binding_id=command.binding_id),
        "pair_version": 2,
        "reviewer_id": "human:reviewer-1",
        "authorization": authorization.model_dump(mode="json"),
        "authorization_digest": pair_authorization_digest(authorization.model_dump(mode="json")),
        "decided_at": "2026-10-06T01:01:00Z",
    }
    assert PairDecisionV1.model_validate(base).command.decision == "REJECT"
    for changed in (
        {"command_digest": "sha256:" + "f" * 64},
        {"pair_id": "m8p:" + "f" * 64},
        {"reviewer_id": "someone-else"},
        {"authorization": {**base["authorization"], "project_name": "other"}},
        {"authorization_digest": "sha256:" + "f" * 64},
        {"authorization": {**base["authorization"], "authorization_ref": "other-grant"}},
        {
            "command": {
                **base["command"],
                "observations": {**base["command"]["observations"], "rejection_reason": "Changed finding."},
            }
        },
    ):
        with pytest.raises((ValidationError, ValueError)):
            pair_decision_digest(base | changed)
