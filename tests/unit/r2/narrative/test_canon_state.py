from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    AddEntityOperation,
    AddEventOperation,
    CanonBranchSnapshot,
    CanonBranchType,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    Entity,
    EntityType,
    Event,
    Fact,
    RetireFactOperation,
    UpdateEntityOperation,
)
from r2.narrative.canon_state import ResolvedCanonView, apply_canon_delta, empty_canon_content
from r2.narrative.errors import CanonOperationError
from r2.narrative.hashing import compute_canon_content_hash, seal_canon_delta

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
UNTIL = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)


def add_entity(
    entity_id: str, *, name: str = "Ada", entity_type: EntityType = EntityType.CHARACTER
) -> AddEntityOperation:
    return AddEntityOperation(
        operation_id=f"op-add-{entity_id}",
        target_id=entity_id,
        entity=Entity(entity_id=entity_id, entity_type=entity_type, canonical_name=name, aliases=[]),
    )


def add_event(event_id: str, participant: str) -> AddEventOperation:
    return AddEventOperation(
        operation_id=f"op-add-{event_id}",
        target_id=event_id,
        event=Event(event_id=event_id, event_type="ARRIVAL", participant_refs=[participant]),
    )


def retire_fact(fact_id: str, until: datetime) -> RetireFactOperation:
    return RetireFactOperation(operation_id=f"op-retire-{fact_id}", target_id=fact_id, effective_until=until)


def update_entity(entity: Entity) -> UpdateEntityOperation:
    return UpdateEntityOperation(
        operation_id=f"op-update-{entity.entity_id}", target_id=entity.entity_id, entity=entity
    )


def sealed_delta(*operations: CanonOperation) -> CanonDelta:
    payload = CanonDeltaPayload(
        canon_delta_id="delta-1",
        target_branch_id="main",
        base_canon_version_id=None,
        operations=list(operations),
        source_change_set_refs=["s-1"],
        author_decision_refs=["a-1"],
        validation_report_refs=[],
        created_at=NOW,
        created_by="showrunner",
    )
    return seal_canon_delta(payload)


def content_with_entity() -> CanonContent:
    return CanonContent(
        entities_by_id={
            "hero": Entity(entity_id="hero", entity_type=EntityType.CHARACTER, canonical_name="Ada", aliases=[])
        },
        facts_by_id={},
        events_by_id={},
    )


def content_with_open_fact() -> CanonContent:
    return CanonContent(
        entities_by_id={
            "hero": Entity(entity_id="hero", entity_type=EntityType.CHARACTER, canonical_name="Ada", aliases=[])
        },
        facts_by_id={"fact-1": Fact(fact_id="fact-1", subject_ref="hero", predicate="alive", value=True)},
        events_by_id={},
    )


def test_ordered_delta_can_add_entity_then_reference_it_from_event() -> None:
    result = apply_canon_delta(empty_canon_content(), sealed_delta(add_entity("hero"), add_event("arrival", "hero")))
    assert result.entities_by_id["hero"].canonical_name == "Ada"
    assert result.events_by_id["arrival"].participant_refs == ["hero"]


def test_retirement_uses_payload_time_and_does_not_delete_history() -> None:
    retired = apply_canon_delta(content_with_open_fact(), sealed_delta(retire_fact("fact-1", UNTIL)))
    assert retired.facts_by_id["fact-1"].effective_until == UNTIL
    assert retired.facts_by_id["fact-1"].predicate == "alive"


def test_reference_must_exist_before_the_referencing_operation() -> None:
    with pytest.raises(CanonOperationError, match="missing participant entity hero"):
        apply_canon_delta(empty_canon_content(), sealed_delta(add_event("arrival", "hero"), add_entity("hero")))


def test_equivalent_update_produces_equal_content_for_transaction_noop_rejection() -> None:
    base = content_with_entity()
    candidate = apply_canon_delta(base, sealed_delta(update_entity(base.entities_by_id["hero"])))
    assert candidate == base


def test_apply_is_copy_on_write_and_leaves_the_base_untouched() -> None:
    base = empty_canon_content()
    apply_canon_delta(base, sealed_delta(add_entity("hero")))
    assert base.entities_by_id == {}


def test_adding_an_existing_target_is_rejected() -> None:
    with pytest.raises(CanonOperationError):
        apply_canon_delta(content_with_entity(), sealed_delta(add_entity("hero")))


def test_update_entity_type_is_immutable() -> None:
    relabelled = Entity(entity_id="hero", entity_type=EntityType.LOCATION, canonical_name="Ada", aliases=[])
    with pytest.raises(CanonOperationError, match="entity type is immutable"):
        apply_canon_delta(content_with_entity(), sealed_delta(update_entity(relabelled)))


def test_retiring_a_closed_fact_is_rejected() -> None:
    closed = apply_canon_delta(content_with_open_fact(), sealed_delta(retire_fact("fact-1", UNTIL)))
    with pytest.raises(CanonOperationError, match="already retired"):
        apply_canon_delta(closed, sealed_delta(retire_fact("fact-1", datetime(2028, 1, 1, tzinfo=UTC))))


def test_operation_target_must_match_its_atom_id() -> None:
    mismatched = AddEntityOperation(
        operation_id="op-x",
        target_id="left",
        entity=Entity(entity_id="right", entity_type=EntityType.CHARACTER, canonical_name="B", aliases=[]),
    )
    with pytest.raises(CanonOperationError):
        apply_canon_delta(empty_canon_content(), sealed_delta(mismatched))


def test_empty_branch_view_pins_null_version_and_matching_hash() -> None:
    branch = CanonBranchSnapshot(
        branch_id="main",
        user_id="u",
        project_name="p",
        branch_type=CanonBranchType.MAIN,
        parent_branch_id=None,
        parent_version_id=None,
        head_version_id=None,
        created_at=NOW,
        created_by="showrunner",
    )
    view = ResolvedCanonView.for_empty_branch(branch)
    assert view.canon_version_id is None
    assert view.branch_id == "main"
    assert view.content == empty_canon_content()
    assert view.content_hash == compute_canon_content_hash(empty_canon_content())
