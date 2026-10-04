"""Proposed canonical identity for one M8-C spatial execution receipt."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures/r2"


def _fixture() -> dict[str, Any]:
    return json.loads((FIXTURES / "m8c_spatial_completion_evidence_vector.json").read_text(encoding="utf-8"))["case"]


def test_spatial_execution_receipt_has_fixed_canonical_bytes_and_ordered_frame_links() -> None:
    case = _fixture()
    envelope = {"domain": case["domain"], "canonical_version": "1", "body": case["body"]}
    expected = case["canonical"].encode("utf-8")

    assert canonical_json_bytes(envelope) == expected
    assert digest_canonical(envelope) == case["digest"]
    assert "sha256:" + hashlib.sha256(expected).hexdigest() == case["digest"]
    assert "object_ref" not in case["canonical"]
    assert [source["role"] for source in case["body"]["ordered_source_frames"]] == ["MASTER", "REVERSE"]

    source_vectors = json.loads((FIXTURES / "m8c_source_digest_vectors.json").read_text(encoding="utf-8"))
    receipts = {row["name"]: row for row in source_vectors["cases"]}
    for source, name in zip(
        case["body"]["ordered_source_frames"],
        ("frame_receipt_master", "frame_receipt_reverse"),
        strict=True,
    ):
        receipt = receipts[name]
        assert source["frame_receipt_id"] == receipt["body"]["frame_candidate_id"]
        assert source["frame_receipt_digest"] == receipt["digest"]
        assert source["frame_digest"] == receipt["body"]["identity"]["frame_content_digest"]


def test_receipt_digest_changes_with_raw_response_route_prompt_and_frame_order() -> None:
    case = _fixture()
    envelope = {"domain": case["domain"], "canonical_version": "1", "body": case["body"]}
    original = digest_canonical(envelope)

    for field in ("request_digest", "route_digest", "prompt_digest"):
        altered = deepcopy(envelope)
        altered["body"][field] = "sha256:" + "f" * 64
        assert digest_canonical(altered) != original, field

    for field in ("raw_response", "overlap_response"):
        altered = deepcopy(envelope)
        altered["body"][field]["byte_digest"] = "sha256:" + "f" * 64
        assert digest_canonical(altered) != original, field

    altered = deepcopy(envelope)
    altered["body"]["ordered_source_frames"].reverse()
    assert digest_canonical(altered) != original

    altered = deepcopy(envelope)
    altered["body"]["ordered_source_frames"][0]["frame_receipt_digest"] = "sha256:" + "f" * 64
    assert digest_canonical(altered) != original
