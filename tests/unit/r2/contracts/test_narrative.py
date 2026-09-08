from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import (
    AddEntityOperation,
    AddEventOperation,
    CanonBranchType,
    CanonCommitResult,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    CanonValidationFinding,
    CanonValidationReport,
    CanonVersionSnapshot,
    Entity,
    EntityType,
    Event,
    Fact,
)
from r2.narrative.errors import CanonBaseVersionConflict

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)


def make_entity(entity_id: str = "e-1", *, name: str = "Ada") -> Entity:
    return Entity(entity_id=entity_id, entity_type=EntityType.CHARACTER, canonical_name=name, aliases=[])


def add_entity(target_id: str, *, name: str = "Ada") -> AddEntityOperation:
    return AddEntityOperation(
        operation_id=f"op-{target_id}", target_id=target_id, entity=make_entity(target_id, name=name)
    )


def add_event(target_id: str, *, participants: list[str] | None = None) -> AddEventOperation:
    return AddEventOperation(
        operation_id=f"op-{target_id}",
        target_id=target_id,
        event=Event(event_id=target_id, event_type="ARRIVAL", participant_refs=participants or []),
    )


def delta_payload(**overrides: object) -> CanonDeltaPayload:
    base: dict[str, object] = {
        "canon_delta_id": "delta-1",
        "target_branch_id": "main",
        "base_canon_version_id": None,
        "operations": [add_entity("e-1")],
        "source_change_set_refs": ["s-1"],
        "author_decision_refs": ["a-1"],
        "validation_report_refs": [],
        "created_at": NOW,
        "created_by": "showrunner",
    }
    base.update(overrides)
    return CanonDeltaPayload(**base)


def valid_delta_json() -> dict[str, object]:
    return delta_payload().model_dump(mode="json")


def test_delta_preserves_operation_order_and_normalizes_reference_sets() -> None:
    payload = CanonDeltaPayload(
        canon_delta_id="delta-1",
        target_branch_id="main",
        base_canon_version_id=None,
        operations=[add_entity("e-1"), add_event("ev-1", participants=["e-1"])],
        source_change_set_refs=["s-2", "s-1", "s-2"],
        author_decision_refs=["a-1"],
        validation_report_refs=[],
        payload_hash_algorithm="sha256",
        payload_hash_version="r2-canon-delta-v1",
        content_schema_version="r2-canon-schema-v1",
        created_at=NOW,
        created_by="showrunner",
    )
    assert [item.operation_id for item in payload.operations] == ["op-e-1", "op-ev-1"]
    assert payload.source_change_set_refs == ["s-1", "s-2"]


def test_operation_payload_is_discriminated_and_extra_fields_fail() -> None:
    with pytest.raises(ValidationError):
        CanonDeltaPayload.model_validate({**valid_delta_json(), "operations": [{"kind": "ADD_FACT", "entity": {}}]})
    with pytest.raises(ValidationError):
        Entity.model_validate(
            {"entity_id": "e-1", "entity_type": "CHARACTER", "canonical_name": "Ada", "aliases": [], "extra": "no"}
        )


def test_canon_enums_have_exact_membership_and_wire_values() -> None:
    assert {member.value for member in CanonBranchType} == {"MAIN", "NARRATIVE_BRANCH"}
    assert {member.value for member in EntityType} == {"CHARACTER", "LOCATION", "OBJECT", "ORGANIZATION"}
    assert CanonBranchType("MAIN") is CanonBranchType.MAIN


def test_delta_payload_rejects_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        delta_payload(created_at=datetime(2026, 9, 7, 12, 0, 0))


def test_delta_rejects_empty_and_duplicate_operations() -> None:
    with pytest.raises(ValidationError):
        delta_payload(operations=[])
    with pytest.raises(ValidationError):
        delta_payload(operations=[add_entity("e-1"), add_entity("e-1")])


def test_entity_aliases_and_fact_source_refs_are_sorted_unique() -> None:
    entity = Entity(
        entity_id="e-1",
        entity_type=EntityType.CHARACTER,
        canonical_name="Ada",
        aliases=["Countess", "Ada", "Countess"],
    )
    assert entity.aliases == ["Ada", "Countess"]
    fact = Fact(
        fact_id="f-1",
        subject_ref="e-1",
        predicate="loyal_to",
        value="crown",
        source_event_refs=["ev-2", "ev-1", "ev-2"],
    )
    assert fact.source_event_refs == ["ev-1", "ev-2"]


def test_event_reference_lists_reject_duplicate_input_then_sort() -> None:
    event = Event(event_id="ev-1", event_type="ARRIVAL", participant_refs=["e-2", "e-1"])
    assert event.participant_refs == ["e-1", "e-2"]
    with pytest.raises(ValidationError):
        Event(event_id="ev-1", event_type="ARRIVAL", participant_refs=["e-1", "e-1"])
    with pytest.raises(ValidationError):
        Event(event_id="ev-1", event_type="ARRIVAL", participant_refs=["e-1"], causal_refs=["c-1", "c-1"])


def test_atoms_are_frozen() -> None:
    entity = make_entity("e-1")
    with pytest.raises(ValidationError):
        entity.canonical_name = "Grace"
    content = CanonContent(entities_by_id={"e-1": entity}, facts_by_id={}, events_by_id={})
    with pytest.raises(ValidationError):
        content.facts_by_id = {}


def test_canon_content_keys_must_match_atom_ids() -> None:
    entity = make_entity("e-1")
    with pytest.raises(ValidationError):
        CanonContent(entities_by_id={"wrong-key": entity}, facts_by_id={}, events_by_id={})


def test_canon_delta_requires_payload_hash_but_payload_does_not() -> None:
    payload = delta_payload()
    assert not hasattr(payload, "payload_hash")
    with pytest.raises(ValidationError):
        CanonDelta.model_validate(payload.model_dump(mode="json"))
    sealed = CanonDelta.model_validate({**payload.model_dump(mode="json"), "payload_hash": "deadbeef"})
    assert sealed.payload_hash == "deadbeef"


def test_version_snapshot_is_frozen_and_forbids_extra() -> None:
    snapshot = CanonVersionSnapshot(
        canon_version_id="v-1",
        branch_id="main",
        version_number=1,
        parent_version_id=None,
        committed_delta_id="delta-1",
        committed_at=NOW,
        committed_by="showrunner",
        content_hash="abc",
        content_hash_algorithm="sha256",
        content_hash_version="r2-canon-content-v1",
        content_schema_version="r2-canon-schema-v1",
    )
    with pytest.raises(ValidationError):
        snapshot.content_hash = "zzz"
    with pytest.raises(ValidationError):
        CanonVersionSnapshot.model_validate({**snapshot.model_dump(mode="json"), "surprise": 1})
    with pytest.raises(ValidationError):
        CanonVersionSnapshot.model_validate({**snapshot.model_dump(mode="json"), "version_number": 0})


def test_validation_report_ok_reflects_findings() -> None:
    assert CanonValidationReport(findings=()).ok is True
    populated = CanonValidationReport(
        findings=(CanonValidationFinding(rule_id="M5A_REFERENCE_MISSING", affected_refs=("e-1",), message="missing"),)
    )
    assert populated.ok is False
    assert set(CanonCommitResult.model_fields) == {"accepted_delta", "version", "validation_report"}


def test_base_version_conflict_message_names_both_sides() -> None:
    error = CanonBaseVersionConflict(expected="v-1", current=None)
    assert error.expected == "v-1"
    assert error.current is None
    assert "v-1" in str(error)
    assert "None" in str(error)
