"""Frame derivation identity and receipt validation against fixed M8-C vectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts.spatial_source import FrameDerivationReceiptV1, FrameIdentityV1

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_source_digest_vectors.json"


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


def test_frame_receipts_validate_both_source_vectors_and_derived_ids() -> None:
    cases = _cases()
    for side in ("master", "reverse"):
        identity = cases[f"frame_identity_{side}"]
        receipt = cases[f"frame_receipt_{side}"]
        validated_identity = FrameIdentityV1.model_validate(identity["body"])
        validated_receipt = FrameDerivationReceiptV1.model_validate(receipt["body"])

        assert validated_identity.model_dump(mode="json") == identity["body"]
        assert validated_receipt.model_dump(mode="json") == receipt["body"]
        assert validated_receipt.frame_candidate_id == identity["derived_candidate_id"]
        assert validated_identity.candidate_id == identity["derived_candidate_id"]
        envelope = {"body": validated_receipt, "canonical_version": "1", "domain": receipt["domain"]}
        assert canonical_json_bytes(envelope).decode("utf-8") == receipt["canonical"]
        assert digest_canonical(envelope) == receipt["digest"]


@pytest.mark.parametrize("field", ["parent_master_version", "recipe_version", "frame_content_digest"])
def test_frame_receipt_rejects_changed_identity_under_same_candidate_id(field: str) -> None:
    cases = _cases()
    body = json.loads(json.dumps(cases["frame_receipt_master"]["body"]))
    body["identity"][field] = {
        "parent_master_version": 2,
        "recipe_version": "m8c-frame-rgb24-png-v2",
        "frame_content_digest": "sha256:" + "f" * 64,
    }[field]

    with pytest.raises(ValidationError, match="frame candidate id"):
        FrameDerivationReceiptV1.model_validate(body)


@pytest.mark.parametrize("field", ["frame_byte_size", "frame_probe_digest", "created_at", "frame_candidate_id"])
def test_frame_receipt_rejects_invalid_metadata(field: str) -> None:
    body = json.loads(json.dumps(_cases()["frame_receipt_master"]["body"]))
    body[field] = {
        "frame_byte_size": 0,
        "frame_probe_digest": "sha256:x",
        "created_at": "today",
        "frame_candidate_id": "m8f:x",
    }[field]

    with pytest.raises(ValidationError):
        FrameDerivationReceiptV1.model_validate(body)
