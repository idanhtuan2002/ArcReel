"""Proposed M8-C source-identity canonical vectors, independent of database models."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_source_digest_vectors.json"


def test_source_vector_envelopes_have_fixed_bytes_and_digests() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    assert {case["name"] for case in cases} == {
        "frame_identity_master",
        "frame_identity_reverse",
        "frame_receipt_master",
        "frame_receipt_reverse",
        "pair_admission_approve",
        "pair_admission_reject",
    }
    for case in cases:
        envelope = {"domain": case["domain"], "canonical_version": "1", "body": case["body"]}
        expected_bytes = case["canonical"].encode("utf-8")
        assert canonical_json_bytes(envelope) == expected_bytes, case["name"]
        assert digest_canonical(envelope) == case["digest"], case["name"]
        assert "sha256:" + hashlib.sha256(expected_bytes).hexdigest() == case["digest"], case["name"]
        assert "object_ref" not in case["canonical"], case["name"]
        if case["name"].startswith("frame_identity_"):
            assert case["derived_candidate_id"] == "m8f:" + case["digest"].removeprefix("sha256:")


def test_source_identity_digest_changes_with_parent_recipe_and_frame() -> None:
    cases = {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}
    original = cases["frame_identity_master"]
    for changed_field, changed_value in (
        ("project_name", "another-project"),
        ("parent_master_version", 2),
        ("decoded_frame_index", 1),
        ("recipe_version", "m8c-frame-rgb24-png-v2"),
        ("frame_content_digest", "sha256:" + "f" * 64),
    ):
        changed_body = original["body"] | {changed_field: changed_value}
        assert (
            digest_canonical({"domain": original["domain"], "canonical_version": "1", "body": changed_body})
            != original["digest"]
        ), changed_field


def test_source_vector_pair_decisions_bind_distinct_frames_and_commands() -> None:
    cases = {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}
    master = cases["frame_receipt_master"]
    reverse = cases["frame_receipt_reverse"]
    assert master["body"]["identity"]["parent_artifact_key"] != reverse["body"]["identity"]["parent_artifact_key"]
    assert master["body"]["identity"]["frame_content_digest"] != reverse["body"]["identity"]["frame_content_digest"]

    approved = cases["pair_admission_approve"]["body"]
    rejected = cases["pair_admission_reject"]["body"]
    assert (
        approved["views"]
        == rejected["views"]
        == [
            {
                "role": "MASTER",
                "frame_receipt_id": master["body"]["frame_candidate_id"],
                "frame_receipt_digest": master["digest"],
            },
            {
                "role": "REVERSE",
                "frame_receipt_id": reverse["body"]["frame_candidate_id"],
                "frame_receipt_digest": reverse["digest"],
            },
        ]
    )
    assert (approved["pair_version"], approved["decision"]) == (1, "APPROVE")
    assert (rejected["pair_version"], rejected["decision"]) == (2, "REJECT")
    assert approved["command_digest"] != rejected["command_digest"]
    assert approved["authorization_ref"] != rejected["authorization_ref"]
