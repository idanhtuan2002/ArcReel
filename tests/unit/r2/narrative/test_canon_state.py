from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    AddEntityOperation,
    AddEventOperation,
    AddTemporalRelationOperation,
    CanonBranchSnapshot,
    CanonBranchType,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    Entity,
    EntityType,
    EpistemicProposition,
    EpistemicState,
    Event,
    Fact,
    KnowledgeState,
    RetireFactOperation,
    TemporalRelation,
    UpdateEntityOperation,
    UpdateKnowledgeOperation,
    compute_epistemic_proposition_ref,
)
from r2.narrative.canon_state import ResolvedCanonView, apply_canon_delta, empty_canon_content
from r2.narrative.errors import CanonOperationError, EpistemicValidationError, NarrativeSchemaVersionError
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


def sealed_delta_v2(*operations: CanonOperation) -> CanonDelta:
    payload = CanonDeltaPayload(
        canon_delta_id="delta-1",
        target_branch_id="main",
        base_canon_version_id=None,
        operations=list(operations),
        source_change_set_refs=["s-1"],
        author_decision_refs=["a-1"],
        validation_report_refs=[],
        content_schema_version="r2-canon-schema-v2",
        created_at=NOW,
        created_by="showrunner",
    )
    return seal_canon_delta(payload)


def test_apply_canon_delta_rejects_a_v2_to_v1_downgrade() -> None:
    with pytest.raises(NarrativeSchemaVersionError):
        apply_canon_delta(
            empty_canon_content(),
            sealed_delta(add_entity("hero")),
            base_schema_version="r2-canon-schema-v2",
        )


def test_apply_canon_delta_upgrades_a_v1_base_under_a_v2_delta() -> None:
    result = apply_canon_delta(
        empty_canon_content(),
        sealed_delta_v2(add_entity("hero")),
        base_schema_version="r2-canon-schema-v1",
    )
    assert result.entities_by_id["hero"].canonical_name == "Ada"
    assert result.knowledge_states_by_id == {}
    assert result.temporal_relations_by_id == {}


def content_with_two_events() -> CanonContent:
    return CanonContent(
        entities_by_id={
            "hero": Entity(entity_id="hero", entity_type=EntityType.CHARACTER, canonical_name="Ada", aliases=[])
        },
        facts_by_id={},
        events_by_id={
            "ev-a": Event(event_id="ev-a", event_type="ARRIVAL", participant_refs=["hero"]),
            "ev-b": Event(event_id="ev-b", event_type="DEPARTURE", participant_refs=["hero"]),
        },
    )


def add_relation(rel_id: str, left: str, right: str) -> AddTemporalRelationOperation:
    return AddTemporalRelationOperation(
        operation_id=f"op-{rel_id}",
        target_id=rel_id,
        temporal_relation=TemporalRelation(
            temporal_relation_id=rel_id, left_event_ref=left, relation="BEFORE", right_event_ref=right
        ),
    )


def test_reducer_stores_an_immutable_temporal_relation() -> None:
    result = apply_canon_delta(
        content_with_two_events(),
        sealed_delta_v2(add_relation("r-1", "ev-a", "ev-b")),
        base_schema_version="r2-canon-schema-v1",
    )
    stored = result.temporal_relations_by_id["r-1"]
    assert (stored.left_event_ref, stored.relation, stored.right_event_ref) == ("ev-a", "BEFORE", "ev-b")


def test_reducer_rejects_a_temporal_relation_referencing_a_missing_event() -> None:
    with pytest.raises(CanonOperationError, match="temporal relation event"):
        apply_canon_delta(
            content_with_two_events(),
            sealed_delta_v2(add_relation("r-1", "ev-a", "ev-ghost")),
            base_schema_version="r2-canon-schema-v1",
        )


def test_reducer_rejects_reusing_a_temporal_relation_id() -> None:
    once = apply_canon_delta(
        content_with_two_events(),
        sealed_delta_v2(add_relation("r-1", "ev-a", "ev-b")),
        base_schema_version="r2-canon-schema-v1",
    )
    with pytest.raises(CanonOperationError, match="already exists"):
        apply_canon_delta(
            once,
            sealed_delta_v2(add_relation("r-1", "ev-b", "ev-a")),
            base_schema_version="r2-canon-schema-v2",
        )


K_AT_10 = datetime(2026, 3, 1, 10, tzinfo=UTC)
K_AT_12 = datetime(2026, 3, 1, 12, tzinfo=UTC)
K_AT_14 = datetime(2026, 3, 1, 14, tzinfo=UTC)


def _proposition() -> EpistemicProposition:
    ref = compute_epistemic_proposition_ref(subject_ref="obj-ring", predicate="owner", object_or_value="hero")
    return EpistemicProposition(proposition_ref=ref, subject_ref="obj-ring", predicate="owner", object_or_value="hero")


def content_for_knowledge(*, states: list[KnowledgeState] | None = None) -> CanonContent:
    proposition = _proposition()
    return CanonContent(
        entities_by_id={
            "hero": Entity(entity_id="hero", entity_type=EntityType.CHARACTER, canonical_name="Ada", aliases=[]),
            "obj-ring": Entity(entity_id="obj-ring", entity_type=EntityType.OBJECT, canonical_name="Ring", aliases=[]),
        },
        facts_by_id={},
        events_by_id={"ev-seen": Event(event_id="ev-seen", event_type="SIGHT", participant_refs=["hero"])},
        epistemic_propositions_by_ref={proposition.proposition_ref: proposition} if states else {},
        knowledge_states_by_id={state.knowledge_state_id: state for state in (states or [])},
    )


def known_op(
    ks_id: str,
    *,
    frm: datetime,
    until: datetime | None = None,
    evidence: list[str] | None = None,
    supersedes: str | None = None,
) -> UpdateKnowledgeOperation:
    return UpdateKnowledgeOperation(
        operation_id=f"op-{ks_id}",
        target_id=ks_id,
        subject_entity_id="hero",
        proposition=_proposition(),
        epistemic_state=EpistemicState.KNOWN,
        effective_from=frm,
        effective_until=until,
        evidence_event_refs=evidence or [],
        supersedes_knowledge_state_id=supersedes,
    )


def existing_state(ks_id: str, *, frm: datetime, until: datetime | None = None) -> KnowledgeState:
    proposition = _proposition()
    return KnowledgeState(
        knowledge_state_id=ks_id,
        subject_entity_id="hero",
        proposition_ref=proposition.proposition_ref,
        epistemic_state=EpistemicState.KNOWN,
        effective_from=frm,
        effective_until=until,
        evidence_event_refs=[],
    )


def test_update_knowledge_appends_state_and_dedupes_proposition() -> None:
    result = apply_canon_delta(
        content_for_knowledge(),
        sealed_delta_v2(known_op("k-1", frm=K_AT_10, evidence=["ev-seen"])),
        base_schema_version="r2-canon-schema-v1",
    )
    state = result.knowledge_states_by_id["k-1"]
    assert state.evidence_event_refs == ["ev-seen"]
    assert state.proposition_ref in result.epistemic_propositions_by_ref


def test_update_knowledge_does_not_mutate_historical_events() -> None:
    result = apply_canon_delta(
        content_for_knowledge(),
        sealed_delta_v2(known_op("k-1", frm=K_AT_10, evidence=["ev-seen"])),
        base_schema_version="r2-canon-schema-v1",
    )
    assert result.events_by_id["ev-seen"].state_effect_refs == []


def test_update_knowledge_without_supersession_rejects_an_active_prior_state() -> None:
    base = content_for_knowledge(states=[existing_state("k-old", frm=K_AT_10)])
    with pytest.raises(EpistemicValidationError, match="supersedes_knowledge_state_id is required"):
        apply_canon_delta(
            base,
            sealed_delta_v2(known_op("k-new", frm=K_AT_12)),
            base_schema_version="r2-canon-schema-v2",
        )


def test_update_knowledge_closes_the_named_prior_state_at_the_new_boundary() -> None:
    base = content_for_knowledge(states=[existing_state("k-old", frm=K_AT_10)])
    result = apply_canon_delta(
        base,
        sealed_delta_v2(known_op("k-new", frm=K_AT_12, supersedes="k-old")),
        base_schema_version="r2-canon-schema-v2",
    )
    assert result.knowledge_states_by_id["k-old"].effective_until == K_AT_12
    assert result.knowledge_states_by_id["k-new"].effective_from == K_AT_12


def test_update_knowledge_rejects_superseding_an_already_closed_state() -> None:
    base = content_for_knowledge(states=[existing_state("k-old", frm=K_AT_10, until=K_AT_12)])
    with pytest.raises(EpistemicValidationError, match="not active at the transition instant"):
        apply_canon_delta(
            base,
            sealed_delta_v2(known_op("k-new", frm=K_AT_14, supersedes="k-old")),
            base_schema_version="r2-canon-schema-v2",
        )


def test_update_knowledge_rejects_a_missing_evidence_event() -> None:
    with pytest.raises(CanonOperationError, match="knowledge evidence event"):
        apply_canon_delta(
            content_for_knowledge(),
            sealed_delta_v2(known_op("k-1", frm=K_AT_10, evidence=["ev-ghost"])),
            base_schema_version="r2-canon-schema-v1",
        )


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
