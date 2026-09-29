"""Canonical bytes and M8 domain digests (plan Task A1.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical, digest_command, digest_payload
from r2.contracts.advanced_creative import CanvasCandidate, CanvasNode, ExplorationKind, LineageBinding

DIGEST = "sha256:" + "a" * 64


def _lineage(**overrides: object) -> LineageBinding:
    fields: dict[str, object] = {
        "project_name": "demo",
        "content_basis_digest": DIGEST,
        "approved_master_id": None,
        "approved_master_digest": None,
        "creative_profile_id": "profile",
        "creative_profile_version": "1",
        "policy_digest": DIGEST,
    }
    return LineageBinding(**(fields | overrides))


def _canvas(body: dict[str, object] | None = None) -> CanvasCandidate:
    return CanvasCandidate(
        kind=ExplorationKind.CANVAS,
        graph_schema_version="1",
        nodes=(CanvasNode(node_id="n1", node_type="shot", body=body or {"k": 1}),),
        edges=(),
        groups=(),
        storyboard_order=("n1",),
        viewport_bookmarks=(),
    )


def test_canonical_bytes_sort_keys_without_whitespace_and_keep_unicode() -> None:
    assert canonical_json_bytes({"b": 1, "a": ["x", "é"]}) == '{"a":["x","é"],"b":1}'.encode()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("1.500"), b"1.5"),
        (Decimal("-0.0"), b"0"),
        (Decimal("1E+3"), b"1000"),
        (2.50, b"2.5"),
        (10, b"10"),
        (True, b"true"),
        (None, b"null"),
    ],
)
def test_numbers_use_fixed_notation_without_trailing_zeroes(value: object, expected: bytes) -> None:
    assert canonical_json_bytes(value) == expected


def test_non_finite_numbers_are_refused() -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes(float("nan"))


def test_timestamps_are_utc_and_naive_ones_are_refused() -> None:
    plus_seven = datetime(2026, 9, 29, 19, 0, tzinfo=timezone(timedelta(hours=7)))

    assert canonical_json_bytes(plus_seven) == canonical_json_bytes(datetime(2026, 9, 29, 12, 0, tzinfo=UTC))
    with pytest.raises(ValueError, match="aware"):
        canonical_json_bytes(datetime(2026, 9, 29, 12, 0))


def test_digest_canonical_is_lowercase_sha256() -> None:
    digest = digest_canonical({"a": 1})

    assert digest.startswith("sha256:")
    assert digest == digest.lower()
    assert len(digest) == len("sha256:") + 64


def test_the_payload_digest_covers_payload_and_every_lineage_field() -> None:
    base = digest_payload(_canvas(), _lineage())
    changes = {
        "project_name": "other",
        "content_basis_digest": "sha256:" + "b" * 64,
        "approved_master_id": "m1",
        "approved_master_digest": "sha256:" + "b" * 64,
        "creative_profile_id": "other",
        "creative_profile_version": "2",
        "policy_digest": "sha256:" + "b" * 64,
    }

    for field, value in changes.items():
        assert digest_payload(_canvas(), _lineage(**{field: value})) != base, field
    assert digest_payload(_canvas({"k": 2}), _lineage()) != base
    assert digest_payload(_canvas(), _lineage()) == base


def test_the_payload_digest_domain_is_exactly_versioned_kind_payload_lineage() -> None:
    payload, lineage = _canvas(), _lineage()

    expected = digest_canonical({"contract_version": "1", "kind": payload.kind, "payload": payload, "lineage": lineage})

    assert digest_payload(payload, lineage) == expected


def test_the_command_digest_binds_operation_scope_and_request() -> None:
    base = digest_command("APPEND_REVISION", "u1", "demo", "actor", {"x": 1})

    assert digest_command("PREVIEW", "u1", "demo", "actor", {"x": 1}) != base
    assert digest_command("APPEND_REVISION", "u2", "demo", "actor", {"x": 1}) != base
    assert digest_command("APPEND_REVISION", "u1", "other", "actor", {"x": 1}) != base
    assert digest_command("APPEND_REVISION", "u1", "demo", "other", {"x": 1}) != base
    assert digest_command("APPEND_REVISION", "u1", "demo", "actor", {"x": 2}) != base
    assert digest_command("APPEND_REVISION", "u1", "demo", "actor", {"x": 1}) == base
