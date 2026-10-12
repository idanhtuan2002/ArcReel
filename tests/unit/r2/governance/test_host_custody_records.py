"""Host custody records retain exact bytes without assigning operator trust."""

from __future__ import annotations

from copy import deepcopy

import pytest

from lib.content_digest import canonical_json_bytes
from r2.contracts.governance_host_records import (
    HostRecordInvalid,
    parse_approved_deployment,
    parse_checkpoint_high_water,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _approval() -> dict[str, object]:
    return {
        "schema": "governance.approved_deployment.v1",
        "deployment_id": "deploy-a",
        "approval_sequence": 1,
        "previous_approval_digest": None,
        "image_ref": "arcreel/arcreel@" + _digest("a"),
        "image_platform": "linux/amd64",
        "registry_sequence": 1,
        "registry_file_digest": _digest("b"),
        "grant_event_key_id": "grant-key-a",
        "checkpoint_key_id": "checkpoint-key-a",
        "approved_at": "2026-10-12T00:00:00Z",
        "operator_id": "operator-a",
    }


def _high_water() -> dict[str, object]:
    return {
        "schema": "governance.checkpoint_high_water.v1",
        "deployment_id": "deploy-a",
        "approved_deployment_digest": _digest("c"),
        "checkpoint_sequence": 1,
        "checkpoint_body_digest": _digest("d"),
        "checkpoint_file_digest": _digest("e"),
        "previous_checkpoint_body_digest": None,
        "previous_high_water_digest": None,
        "signer_key_id": "checkpoint-key-a",
        "checkpoint_issued_at": "2026-10-12T00:00:00Z",
        "recorded_at": "2026-10-12T00:00:01Z",
        "operator_id": "operator-a",
    }


def test_canonical_host_records_return_exact_content_digests() -> None:
    approval_raw = canonical_json_bytes(_approval(), allow_nan=False)
    high_water_raw = canonical_json_bytes(_high_water(), allow_nan=False)
    approval = parse_approved_deployment(approval_raw)
    high_water = parse_checkpoint_high_water(high_water_raw)

    assert approval.deployment_id == high_water.deployment_id == "deploy-a"
    assert approval.approval_sequence == high_water.checkpoint_sequence == 1
    assert approval.record_digest == "sha256:10821094b4664e16af5cabc57f64f4eb137b55b962f6e1f044fec47e0c3cf22a"
    assert high_water.record_digest == "sha256:29ff54f8621dc84938bb8a49bce246c161c2ea18be479c924329b6082edc3bcb"


def test_successor_records_parse_without_authorizing_publication() -> None:
    approval = _approval() | {"approval_sequence": 2, "previous_approval_digest": _digest("a")}
    high_water = _high_water() | {
        "checkpoint_sequence": 2,
        "previous_checkpoint_body_digest": _digest("b"),
        "previous_high_water_digest": _digest("c"),
    }
    assert parse_approved_deployment(canonical_json_bytes(approval, allow_nan=False)).approval_sequence == 2
    assert parse_checkpoint_high_water(canonical_json_bytes(high_water, allow_nan=False)).checkpoint_sequence == 2


@pytest.mark.parametrize("record", ["approval", "high_water"])
@pytest.mark.parametrize("mutation", ["duplicate", "noncanonical", "invalid_utf8", "oversized", "empty"])
def test_host_records_reject_invalid_wire_bytes(record: str, mutation: str) -> None:
    value = _approval() if record == "approval" else _high_water()
    raw = canonical_json_bytes(value, allow_nan=False)
    if mutation == "duplicate":
        raw = raw.replace(b'"deployment_id":"deploy-a"', b'"deployment_id":"deploy-a","deployment_id":"deploy-a"')
    elif mutation == "noncanonical":
        raw = b" " + raw
    elif mutation == "invalid_utf8":
        raw += b"\xff"
    elif mutation == "oversized":
        raw = b"x" * 8193
    elif mutation == "empty":
        raw = b""
    parser = parse_approved_deployment if record == "approval" else parse_checkpoint_high_water
    with pytest.raises(HostRecordInvalid):
        parser(raw)


@pytest.mark.parametrize(
    ("record", "field", "bad"),
    [
        ("approval", "approval_sequence", True),
        ("approval", "schema", "governance.approved_deployment.v2"),
        ("approval", "previous_approval_digest", _digest("a")),
        ("approval", "image_ref", "arcreel/arcreel:latest"),
        ("approval", "image_platform", "linux/amd64 "),
        ("approval", "registry_file_digest", "sha256:BAD"),
        ("approval", "grant_event_key_id", "checkpoint-key-a"),
        ("approval", "approved_at", "2026-10-12T00:00:00+00:00"),
        ("high_water", "checkpoint_sequence", True),
        ("high_water", "schema", "governance.checkpoint_high_water.v2"),
        ("high_water", "previous_high_water_digest", _digest("a")),
        ("high_water", "previous_checkpoint_body_digest", _digest("a")),
        ("high_water", "checkpoint_file_digest", "sha256:BAD"),
        ("high_water", "recorded_at", "2026-10-12T00:00:00+00:00"),
    ],
)
def test_host_records_reject_invalid_shape(record: str, field: str, bad: object) -> None:
    value = deepcopy(_approval() if record == "approval" else _high_water())
    value[field] = bad
    parser = parse_approved_deployment if record == "approval" else parse_checkpoint_high_water
    with pytest.raises(HostRecordInvalid) as exc:
        parser(canonical_json_bytes(value, allow_nan=False))
    assert "operator-a" not in str(exc.value)


@pytest.mark.parametrize("record", ["approval", "high_water"])
def test_host_records_reject_unknown_fields(record: str) -> None:
    value = _approval() if record == "approval" else _high_water()
    value["unexpected"] = "x"
    parser = parse_approved_deployment if record == "approval" else parse_checkpoint_high_water
    with pytest.raises(HostRecordInvalid):
        parser(canonical_json_bytes(value, allow_nan=False))
