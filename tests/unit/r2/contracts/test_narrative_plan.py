from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from r2.contracts import (
    AudienceRevealRecipient,
    CharacterRevealRecipient,
    NarrativePlanNode,
    SceneEventConstraint,
    SceneFactConstraint,
    SceneKnowledgeConstraint,
    SceneRevealConstraint,
    SceneTemporalWindow,
)

FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)


def test_scene_temporal_window_must_be_a_non_empty_half_open_utc_interval() -> None:
    with pytest.raises(ValidationError):
        SceneTemporalWindow(effective_from=UNTIL, effective_until=FROM)
    with pytest.raises(ValidationError):
        SceneTemporalWindow(effective_from=datetime(2026, 3, 1, 10), effective_until=UNTIL)
    window = SceneTemporalWindow(effective_from=FROM, effective_until=UNTIL)
    assert window.effective_until > window.effective_from


def test_fact_constraint_value_presence_follows_the_comparison() -> None:
    assert (
        SceneFactConstraint(
            constraint_id="c-1", subject_ref="obj-ring", predicate="owner", comparison="PRESENT"
        ).expected_value
        is None
    )
    with pytest.raises(ValidationError):
        SceneFactConstraint(
            constraint_id="c-1", subject_ref="obj-ring", predicate="owner", comparison="PRESENT", expected_value="x"
        )
    with pytest.raises(ValidationError):
        SceneFactConstraint(constraint_id="c-1", subject_ref="obj-ring", predicate="owner", comparison="EQUALS")
    ok = SceneFactConstraint(
        constraint_id="c-1", subject_ref="obj-ring", predicate="owner", comparison="EQUALS", expected_value="char-b"
    )
    assert ok.constraint_kind == "FACT"


def test_knowledge_constraint_states_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        SceneKnowledgeConstraint(constraint_id="c-1", subject_entity_id="char-a", proposition_ref="ep:x", states=[])
    ok = SceneKnowledgeConstraint(
        constraint_id="c-1", subject_entity_id="char-a", proposition_ref="ep:x", states=["KNOWN"]
    )
    assert ok.constraint_kind == "KNOWLEDGE"
    assert ok.include_absent is False


def test_event_constraint_requires_exactly_one_selector() -> None:
    with pytest.raises(ValidationError):
        SceneEventConstraint(constraint_id="c-1")
    with pytest.raises(ValidationError):
        SceneEventConstraint(constraint_id="c-1", event_ref="ev-1", event_type="ARRIVAL")
    exact = SceneEventConstraint(constraint_id="c-1", event_ref="ev-1")
    pattern = SceneEventConstraint(constraint_id="c-2", event_type="ARRIVAL", participant_refs_all=["b", "a"])
    assert exact.event_type is None
    assert pattern.participant_refs_all == ["a", "b"]


def test_reveal_recipients_are_a_discriminated_character_audience_union() -> None:
    constraint = SceneRevealConstraint(
        constraint_id="c-1",
        proposition_ref="ep:x",
        recipients=[
            CharacterRevealRecipient(subject_entity_id="char-a", resulting_state="KNOWN"),
            AudienceRevealRecipient(),
        ],
    )
    assert [recipient.recipient_kind for recipient in constraint.recipients] == ["CHARACTER", "AUDIENCE"]
    with pytest.raises(ValidationError):
        SceneRevealConstraint(constraint_id="c-1", proposition_ref="ep:x", recipients=[])
    with pytest.raises(ValidationError):
        CharacterRevealRecipient(subject_entity_id="char-a", resulting_state="UNKNOWN")


def test_plan_node_rejects_zero_version_and_negative_sequence_index() -> None:
    with pytest.raises(ValidationError):
        NarrativePlanNode(
            node_id="n-1",
            node_kind="VOLUME",
            version=0,
            parent_id=None,
            sequence_index=0,
            intent="i",
        )
    with pytest.raises(ValidationError):
        NarrativePlanNode(
            node_id="n-1",
            node_kind="VOLUME",
            version=1,
            parent_id=None,
            sequence_index=-1,
            intent="i",
        )


def test_scene_and_plan_contracts_reject_provider_and_runtime_fields() -> None:
    with pytest.raises(ValidationError):
        SceneTemporalWindow.model_validate({"effective_from": FROM, "effective_until": UNTIL, "provider": "openai"})
    with pytest.raises(ValidationError):
        NarrativePlanNode.model_validate(
            {
                "node_id": "n-1",
                "node_kind": "ARC",
                "version": 1,
                "parent_id": None,
                "sequence_index": 0,
                "intent": "i",
                "runtime_task_id": "t-1",
            }
        )
