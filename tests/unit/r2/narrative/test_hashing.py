from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    AddEntityOperation,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    Entity,
    EntityType,
)
from r2.narrative.errors import CanonIntegrityError
from r2.narrative.hashing import (
    compute_canon_content_hash,
    compute_canon_delta_hash,
    seal_canon_delta,
    verify_canon_content_hash,
    verify_canon_delta_hash,
)

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def op_a() -> AddEntityOperation:
    return AddEntityOperation(
        operation_id="op-a",
        target_id="e-a",
        entity=Entity(entity_id="e-a", entity_type=EntityType.CHARACTER, canonical_name="Ada", aliases=[]),
    )


def op_b() -> AddEntityOperation:
    return AddEntityOperation(
        operation_id="op-b",
        target_id="e-b",
        entity=Entity(entity_id="e-b", entity_type=EntityType.LOCATION, canonical_name="Keep", aliases=[]),
    )


def payload(
    *,
    operations: list[AddEntityOperation] | None = None,
    source_refs: list[str] | None = None,
    **overrides: object,
) -> CanonDeltaPayload:
    base: dict[str, object] = {
        "canon_delta_id": "delta-1",
        "target_branch_id": "main",
        "base_canon_version_id": None,
        "operations": operations if operations is not None else [op_a()],
        "source_change_set_refs": source_refs if source_refs is not None else ["s-1"],
        "author_decision_refs": ["a-1"],
        "validation_report_refs": [],
        "created_at": NOW,
        "created_by": "showrunner",
    }
    base.update(overrides)
    return CanonDeltaPayload(**base)


def empty_content() -> CanonContent:
    return CanonContent(entities_by_id={}, facts_by_id={}, events_by_id={})


def test_delta_hash_is_order_sensitive_for_operations_and_stable_for_reference_sets() -> None:
    first = payload(operations=[op_a(), op_b()], source_refs=["s-2", "s-1"])
    reordered_refs = payload(operations=[op_a(), op_b()], source_refs=["s-1", "s-2"])
    reordered_ops = payload(operations=[op_b(), op_a()], source_refs=["s-1", "s-2"])
    assert compute_canon_delta_hash(first) == compute_canon_delta_hash(reordered_refs)
    assert compute_canon_delta_hash(first) != compute_canon_delta_hash(reordered_ops)


def test_unsupported_historical_hash_version_fails_closed() -> None:
    with pytest.raises(CanonIntegrityError, match="unsupported Canon content hash version"):
        compute_canon_content_hash(empty_content(), hash_version="r2-canon-content-v2")


def test_delta_hash_ignores_creation_metadata() -> None:
    stable = payload()
    relabelled = payload(created_at=datetime(2030, 1, 1, tzinfo=UTC), created_by="a-different-author")
    assert compute_canon_delta_hash(stable) == compute_canon_delta_hash(relabelled)


def test_seal_then_verify_round_trips_and_detects_tampering() -> None:
    sealed = seal_canon_delta(payload())
    assert isinstance(sealed, CanonDelta)
    assert sealed.payload_hash == compute_canon_delta_hash(payload())
    verify_canon_delta_hash(sealed)
    tampered = sealed.model_copy(update={"payload_hash": "0" * 64})
    with pytest.raises(CanonIntegrityError):
        verify_canon_delta_hash(tampered)


def test_content_hash_is_deterministic_and_key_order_independent() -> None:
    ada = Entity(entity_id="e-1", entity_type=EntityType.CHARACTER, canonical_name="Ada", aliases=[])
    key = Entity(entity_id="e-2", entity_type=EntityType.OBJECT, canonical_name="Key", aliases=[])
    left = CanonContent(entities_by_id={"e-1": ada, "e-2": key}, facts_by_id={}, events_by_id={})
    right = CanonContent(entities_by_id={"e-2": key, "e-1": ada}, facts_by_id={}, events_by_id={})
    assert compute_canon_content_hash(left) == compute_canon_content_hash(right)


def test_verify_content_hash_accepts_match_and_rejects_mismatch() -> None:
    content = empty_content()
    digest = compute_canon_content_hash(content)
    verify_canon_content_hash(
        content,
        expected_hash=digest,
        algorithm="sha256",
        hash_version="r2-canon-content-v1",
        schema_version="r2-canon-schema-v1",
    )
    with pytest.raises(CanonIntegrityError):
        verify_canon_content_hash(
            content,
            expected_hash="not-the-hash",
            algorithm="sha256",
            hash_version="r2-canon-content-v1",
            schema_version="r2-canon-schema-v1",
        )


def test_other_unsupported_content_selectors_fail_closed() -> None:
    with pytest.raises(CanonIntegrityError, match="algorithm"):
        compute_canon_content_hash(empty_content(), algorithm="md5")
    with pytest.raises(CanonIntegrityError, match="schema version"):
        compute_canon_content_hash(empty_content(), schema_version="r2-canon-schema-v2")
