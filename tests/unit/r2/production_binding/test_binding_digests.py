"""Fixed Preparation-canonical vectors for the first LOCATION binding packet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from r2.contracts import ProductionBinding
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.production_binding_authority import (
    BindingCreateCommandV1,
    BindingCreateResultV1,
    BindingEnvelopeV1,
    BindingSnapshotV1,
    FrameSourceClaimV1,
)
from r2.production_binding.digests import (
    binding_body_digest,
    binding_core_digest,
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
        "binding_core": lambda body: binding_core_digest(
            body=ProductionBinding.model_validate(cases["binding_body"]["body"]),
            envelope=BindingEnvelopeV1.model_validate(cases["binding_envelope"]["body"]),
        ),
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


def test_pair_core_digest_is_stable_across_binding_version_and_sensitive_to_sources() -> None:
    cases = _cases()
    body = ProductionBinding.model_validate(cases["binding_body"]["body"])
    envelope = BindingEnvelopeV1.model_validate(cases["binding_envelope"]["body"])
    baseline = binding_core_digest(body=body, envelope=envelope)
    assert baseline == cases["binding_core"]["digest"]
    assert cases["binding_core"]["body"] == {
        "user_id": envelope.user_id,
        "project_name": envelope.project_name,
        "binding": body.model_dump(mode="json", exclude={"version"}),
        "scene_ref": envelope.scene_ref.model_dump(mode="json"),
        "target_ref": envelope.target_ref.model_dump(mode="json"),
        "ordered_source_claim_digests": [claim.claim_digest for claim in envelope.ordered_claims],
    }
    advanced_body = body.model_copy(update={"version": 2})
    advanced_envelope = envelope.model_copy(
        update={"binding_version": 2, "binding_body_digest": binding_body_digest(advanced_body)}
    )
    assert binding_core_digest(body=advanced_body, envelope=advanced_envelope) == baseline

    changed_claim_body = envelope.ordered_claims[0].model_dump(mode="json", exclude={"claim_digest"})
    changed_claim_body["frame_content_digest"] = "sha256:" + "f" * 64
    changed_claim = envelope.ordered_claims[0].model_copy(
        update={
            "frame_content_digest": changed_claim_body["frame_content_digest"],
            "claim_digest": frame_source_claim_digest(changed_claim_body),
        }
    )
    assert (
        binding_core_digest(
            body=body,
            envelope=envelope.model_copy(update={"ordered_claims": (changed_claim, envelope.ordered_claims[1])}),
        )
        != baseline
    )
    changed_target = envelope.target_ref.model_copy(update={"version_digest": "sha256:" + "f" * 64})
    assert (
        binding_core_digest(body=body, envelope=envelope.model_copy(update={"target_ref": changed_target})) != baseline
    )

    altered_claim = envelope.ordered_claims[0].model_copy(update={"receipt_digest": "sha256:" + "f" * 64})
    with pytest.raises(ValueError, match="claim digest"):
        binding_core_digest(
            body=body,
            envelope=envelope.model_copy(update={"ordered_claims": (altered_claim, envelope.ordered_claims[1])}),
        )
    with pytest.raises(ValueError, match="body digest"):
        binding_core_digest(
            body=body, envelope=envelope.model_copy(update={"binding_body_digest": "sha256:" + "f" * 64})
        )


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


def test_typed_authority_bodies_match_fixed_vectors() -> None:
    cases = _cases()
    models = {
        "frame_claim_a": FrameSourceClaimV1,
        "frame_claim_b": FrameSourceClaimV1,
        "binding_envelope": BindingEnvelopeV1,
        "binding_create_command": BindingCreateCommandV1,
        "binding_create_result": BindingCreateResultV1,
        "binding_snapshot": BindingSnapshotV1,
    }
    for name, model in models.items():
        assert model.model_validate(cases[name]["body"]).model_dump(mode="json") == cases[name]["body"]


def test_typed_authority_bodies_reject_extra_and_mismatched_fields() -> None:
    cases = _cases()
    claim = cases["frame_claim_a"]["body"]
    with pytest.raises(ValidationError):
        FrameSourceClaimV1.model_validate({**claim, "object_ref": "/tmp/frame.png"})
    with pytest.raises(ValidationError):
        FrameSourceClaimV1.model_validate({**claim, "receipt_id": "m8f:" + "c" * 64})

    envelope = cases["binding_envelope"]["body"]
    with pytest.raises(ValidationError):
        BindingEnvelopeV1.model_validate({**envelope, "binding_version": 0})
    with pytest.raises(ValidationError):
        BindingEnvelopeV1.model_validate({**envelope, "ordered_claims": list(reversed(envelope["ordered_claims"]))})
    changed_claim = {**envelope["ordered_claims"][0], "frame_byte_size": 257}
    with pytest.raises(ValueError, match="claim digest"):
        binding_envelope_digest({**envelope, "ordered_claims": [changed_claim, envelope["ordered_claims"][1]]})

    command = cases["binding_create_command"]["body"]
    with pytest.raises(ValidationError):
        BindingCreateCommandV1.model_validate(
            {**command, "ordered_frame_receipts": command["ordered_frame_receipts"][:1]}
        )
    with pytest.raises(ValidationError):
        binding_create_command_digest({**command, "body": "unexpected"})

    snapshot = cases["binding_snapshot"]["body"]
    with pytest.raises(ValidationError):
        BindingSnapshotV1.model_validate({**snapshot, "target_versions": list(reversed(snapshot["target_versions"]))})


def test_envelope_spatial_set_is_both_or_neither_and_names_its_digest() -> None:
    envelope = _cases()["binding_envelope"]["body"]
    digest = "sha256:" + "e" * 64
    with_set = {**envelope, "spatial_set_id": "m8s:" + "e" * 64, "spatial_set_digest": digest}

    assert binding_envelope_digest(with_set) != binding_envelope_digest(envelope)
    for invalid in (
        {**envelope, "spatial_set_id": "m8s:" + "e" * 64},
        {**envelope, "spatial_set_digest": digest},
        {**with_set, "spatial_set_id": "m8s:" + "f" * 64},
    ):
        with pytest.raises(ValidationError):
            BindingEnvelopeV1.model_validate(invalid)
