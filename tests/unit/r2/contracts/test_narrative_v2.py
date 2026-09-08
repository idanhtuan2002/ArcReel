from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import (
    AddTemporalRelationOperation,
    CanonCommitApproval,
    CanonContent,
    CanonDeltaPayload,
    EpistemicProposition,
    EpistemicState,
    KnowledgeState,
    TemporalRelation,
    UpdateKnowledgeOperation,
    compute_epistemic_proposition_ref,
    operation_kinds_for,
)
from tests.unit.r2.contracts.test_narrative import add_entity

AT_10 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
AT_12 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def proposition(subject_ref: str, predicate: str, object_or_value: object) -> EpistemicProposition:
    return EpistemicProposition(
        proposition_ref=compute_epistemic_proposition_ref(
            subject_ref=subject_ref, predicate=predicate, object_or_value=object_or_value
        ),
        subject_ref=subject_ref,
        predicate=predicate,
        object_or_value=object_or_value,
    )


def known_op(**overrides: object) -> UpdateKnowledgeOperation:
    base: dict[str, object] = {
        "operation_id": "op-k-1",
        "target_id": "k-1",
        "subject_entity_id": "character-a",
        "proposition": proposition("ring", "owner", "character-b"),
        "epistemic_state": EpistemicState.KNOWN,
        "effective_from": AT_10,
        "evidence_event_refs": [],
        "bootstrap_author_decision_ref": "decision-7",
    }
    base.update(overrides)
    return UpdateKnowledgeOperation(**base)


def v2_delta_json(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "canon_delta_id": "delta-1",
        "target_branch_id": "main",
        "base_canon_version_id": None,
        "operations": [add_entity("e-1").model_dump(mode="json")],
        "source_change_set_refs": ["s-1"],
        "author_decision_refs": ["decision-7"],
        "validation_report_refs": [],
        "content_schema_version": "r2-canon-schema-v2",
        "created_at": AT_10.isoformat(),
        "created_by": "showrunner",
    }
    base.update(overrides)
    return base


def test_schema_v2_adds_exactly_two_operation_kinds() -> None:
    assert operation_kinds_for("r2-canon-schema-v1") == {
        "ADD_ENTITY",
        "UPDATE_ENTITY",
        "ADD_FACT",
        "RETIRE_FACT",
        "ADD_EVENT",
    }
    assert operation_kinds_for("r2-canon-schema-v2") == {
        "ADD_ENTITY",
        "UPDATE_ENTITY",
        "ADD_FACT",
        "RETIRE_FACT",
        "ADD_EVENT",
        "UPDATE_KNOWLEDGE",
        "ADD_TEMPORAL_RELATION",
    }


def test_operation_kinds_for_rejects_unknown_selector() -> None:
    with pytest.raises(ValueError, match="unknown Canon content schema selector"):
        operation_kinds_for("r2-canon-schema-v9")


def test_epistemic_state_enum_has_exact_membership() -> None:
    assert {member.value for member in EpistemicState} == {"KNOWN", "SUSPECTED", "FALSE_BELIEF", "UNKNOWN"}


def test_update_knowledge_keeps_bootstrap_binding_operation_local() -> None:
    operation = known_op()
    assert operation.kind == "UPDATE_KNOWLEDGE"
    assert operation.bootstrap_author_decision_ref == "decision-7"
    assert operation.supersedes_knowledge_state_id is None


def test_epistemic_proposition_ref_must_match_normalized_content() -> None:
    good = proposition("ring", "owner", "character-b")
    assert good.proposition_ref.startswith("ep:")
    with pytest.raises(ValidationError):
        EpistemicProposition(
            proposition_ref="ep:not-the-real-hash",
            subject_ref="ring",
            predicate="owner",
            object_or_value="character-b",
        )


def test_proposition_subject_is_independent_of_knowledge_holder() -> None:
    state = KnowledgeState(
        knowledge_state_id="k-1",
        subject_entity_id="character-a",
        proposition_ref=proposition("ring", "owner", "character-b").proposition_ref,
        epistemic_state=EpistemicState.SUSPECTED,
        effective_from=AT_10,
        evidence_event_refs=["ev-1"],
    )
    assert state.subject_entity_id == "character-a"
    assert state.proposition_ref == proposition("ring", "owner", "character-b").proposition_ref


def test_knowledge_state_rejects_naive_times_and_empty_interval() -> None:
    with pytest.raises(ValidationError):
        KnowledgeState(
            knowledge_state_id="k-1",
            subject_entity_id="character-a",
            proposition_ref=proposition("ring", "owner", "b").proposition_ref,
            epistemic_state=EpistemicState.KNOWN,
            effective_from=datetime(2026, 3, 1, 10, 0, 0),
        )
    with pytest.raises(ValidationError):
        KnowledgeState(
            knowledge_state_id="k-1",
            subject_entity_id="character-a",
            proposition_ref=proposition("ring", "owner", "b").proposition_ref,
            epistemic_state=EpistemicState.KNOWN,
            effective_from=AT_12,
            effective_until=AT_10,
        )


def test_update_knowledge_evidence_refs_are_sorted_and_duplicate_free() -> None:
    operation = known_op(
        bootstrap_author_decision_ref=None,
        evidence_event_refs=["ev-2", "ev-1", "ev-1"],
    )
    assert operation.evidence_event_refs == ["ev-1", "ev-2"]


def test_temporal_relation_normalizes_simultaneous_endpoints_by_id() -> None:
    relation = TemporalRelation(
        temporal_relation_id="r-1",
        left_event_ref="ev-b",
        relation="SIMULTANEOUS",
        right_event_ref="ev-a",
        evidence_event_refs=[],
    )
    assert (relation.left_event_ref, relation.right_event_ref) == ("ev-a", "ev-b")


def test_temporal_relation_keeps_before_endpoint_order() -> None:
    relation = TemporalRelation(
        temporal_relation_id="r-1",
        left_event_ref="ev-b",
        relation="BEFORE",
        right_event_ref="ev-a",
        evidence_event_refs=[],
    )
    assert (relation.left_event_ref, relation.right_event_ref) == ("ev-b", "ev-a")


def test_add_temporal_relation_target_id_must_equal_relation_id() -> None:
    relation = TemporalRelation(
        temporal_relation_id="r-1",
        left_event_ref="ev-a",
        relation="BEFORE",
        right_event_ref="ev-b",
        evidence_event_refs=[],
    )
    operation = AddTemporalRelationOperation(operation_id="op-r-1", target_id="r-1", temporal_relation=relation)
    assert operation.kind == "ADD_TEMPORAL_RELATION"
    with pytest.raises(ValidationError):
        AddTemporalRelationOperation(operation_id="op-r-1", target_id="mismatch", temporal_relation=relation)


def test_v2_operations_are_rejected_in_a_v1_delta_payload() -> None:
    with pytest.raises(ValidationError):
        CanonDeltaPayload.model_validate(
            v2_delta_json(
                content_schema_version="r2-canon-schema-v1",
                operations=[known_op().model_dump(mode="json")],
            )
        )


def test_v2_operations_are_accepted_in_a_v2_delta_payload() -> None:
    payload = CanonDeltaPayload.model_validate(v2_delta_json(operations=[known_op().model_dump(mode="json")]))
    assert [operation.kind for operation in payload.operations] == ["UPDATE_KNOWLEDGE"]


def test_canon_content_v2_maps_default_empty_and_keys_match_ids() -> None:
    content = CanonContent(entities_by_id={}, facts_by_id={}, events_by_id={})
    assert content.epistemic_propositions_by_ref == {}
    assert content.knowledge_states_by_id == {}
    assert content.temporal_relations_by_id == {}
    prop = proposition("ring", "owner", "character-b")
    with pytest.raises(ValidationError):
        CanonContent(
            entities_by_id={},
            facts_by_id={},
            events_by_id={},
            epistemic_propositions_by_ref={"wrong-key": prop},
        )


def test_update_knowledge_rejects_provider_and_runtime_fields() -> None:
    with pytest.raises(ValidationError):
        UpdateKnowledgeOperation.model_validate({**known_op().model_dump(mode="json"), "provider": "openai"})
    with pytest.raises(ValidationError):
        UpdateKnowledgeOperation.model_validate({**known_op().model_dump(mode="json"), "runtime_task_id": "t-1"})


def test_commit_approval_accepts_the_v2_schema_selector() -> None:
    approval = CanonCommitApproval(
        approval_ref="ap-1",
        canon_delta_id="delta-1",
        payload_hash="abc",
        payload_hash_algorithm="sha256",
        payload_hash_version="r2-canon-delta-v1",
        content_schema_version="r2-canon-schema-v2",
        project_name="proj",
        user_id="user-1",
        approved_by="lead",
        approved_at=AT_10,
        status="APPROVED",
    )
    assert approval.content_schema_version == "r2-canon-schema-v2"
