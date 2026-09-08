from __future__ import annotations

from collections.abc import Mapping
from typing import assert_never

from pydantic import ConfigDict

from r2.contracts import (
    AddEntityOperation,
    AddEventOperation,
    AddFactOperation,
    AddTemporalRelationOperation,
    CanonBranchSnapshot,
    CanonContent,
    CanonDelta,
    Entity,
    EpistemicProposition,
    Event,
    Fact,
    KnowledgeState,
    RetireFactOperation,
    TemporalRelation,
    UpdateEntityOperation,
    UpdateKnowledgeOperation,
)
from r2.contracts.common import NonEmptyStr, R2ContractModel

from .errors import CanonOperationError
from .hashing import compute_canon_content_hash
from .schema_upgrade import upgrade_canon_content


class ResolvedCanonView(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    canon_version_id: NonEmptyStr | None
    branch_id: NonEmptyStr
    content_hash: NonEmptyStr
    content_hash_algorithm: NonEmptyStr = "sha256"
    content_hash_version: NonEmptyStr = "r2-canon-content-v1"
    content_schema_version: NonEmptyStr = "r2-canon-schema-v1"
    content: CanonContent

    @classmethod
    def for_empty_branch(cls, branch: CanonBranchSnapshot) -> ResolvedCanonView:
        content = empty_canon_content()
        return cls(
            canon_version_id=None,
            branch_id=branch.branch_id,
            content_hash=compute_canon_content_hash(content),
            content=content,
        )


def empty_canon_content() -> CanonContent:
    return CanonContent(entities_by_id={}, facts_by_id={}, events_by_id={})


def _require_target(target_id: str, atom_id: str) -> None:
    if target_id != atom_id:
        raise CanonOperationError(f"operation target {target_id!r} does not match atom id {atom_id!r}")


def _require_absent(mapping: Mapping[str, object], key: str, *, label: str = "atom") -> None:
    if key in mapping:
        raise CanonOperationError(f"{label} {key} already exists in the base state")


def _require_present[T](mapping: Mapping[str, T], key: str, *, label: str = "entity") -> T:
    try:
        return mapping[key]
    except KeyError:
        raise CanonOperationError(f"missing {label} {key}") from None


def apply_canon_delta(base: CanonContent, delta: CanonDelta, *, base_schema_version: str | None = None) -> CanonContent:
    """Apply an ordered delta to a base view.

    ``base_schema_version`` is the recorded content schema selector of ``base`` (``None`` for
    genesis). The base view is upgraded to the delta's content schema before any operation
    runs; ``r2/narrative/schema_upgrade.py`` rejects an illegal transition. The result is
    serialized under the delta's selector.
    """
    upgraded = upgrade_canon_content(base, from_schema=base_schema_version, to_schema=delta.content_schema_version)
    entities: dict[str, Entity] = dict(upgraded.entities_by_id)
    facts: dict[str, Fact] = dict(upgraded.facts_by_id)
    events: dict[str, Event] = dict(upgraded.events_by_id)
    propositions: dict[str, EpistemicProposition] = dict(upgraded.epistemic_propositions_by_ref)
    knowledge_states: dict[str, KnowledgeState] = dict(upgraded.knowledge_states_by_id)
    temporal_relations: dict[str, TemporalRelation] = dict(upgraded.temporal_relations_by_id)
    for operation in delta.operations:
        match operation:
            case AddEntityOperation():
                _require_target(operation.target_id, operation.entity.entity_id)
                _require_absent(entities, operation.target_id, label="entity")
                entities[operation.target_id] = operation.entity
            case UpdateEntityOperation():
                _require_target(operation.target_id, operation.entity.entity_id)
                current = _require_present(entities, operation.target_id, label="entity")
                if current.entity_type is not operation.entity.entity_type:
                    raise CanonOperationError("entity type is immutable")
                entities[operation.target_id] = operation.entity
            case AddFactOperation():
                _require_target(operation.target_id, operation.fact.fact_id)
                _require_absent(facts, operation.target_id, label="fact")
                _require_present(entities, operation.fact.subject_ref, label="subject entity")
                for event_ref in operation.fact.source_event_refs:
                    _require_present(events, event_ref, label="source event")
                facts[operation.target_id] = operation.fact
            case RetireFactOperation():
                current = _require_present(facts, operation.target_id, label="fact")
                if current.effective_until is not None:
                    raise CanonOperationError("fact is already retired")
                facts[operation.target_id] = current.model_copy(update={"effective_until": operation.effective_until})
            case AddEventOperation():
                _require_target(operation.target_id, operation.event.event_id)
                _require_absent(events, operation.target_id, label="event")
                for entity_ref in operation.event.participant_refs:
                    _require_present(entities, entity_ref, label="participant entity")
                if operation.event.location_ref is not None:
                    _require_present(entities, operation.event.location_ref, label="location entity")
                for event_ref in operation.event.causal_refs:
                    _require_present(events, event_ref, label="causal event")
                events[operation.target_id] = operation.event
            case AddTemporalRelationOperation():
                relation = operation.temporal_relation
                _require_target(operation.target_id, relation.temporal_relation_id)
                _require_absent(temporal_relations, operation.target_id, label="temporal relation")
                for event_ref in (relation.left_event_ref, relation.right_event_ref):
                    _require_present(events, event_ref, label="temporal relation event")
                for event_ref in relation.evidence_event_refs:
                    _require_present(events, event_ref, label="temporal relation evidence event")
                temporal_relations[operation.target_id] = relation
            case UpdateKnowledgeOperation():
                # Epistemic supersession lands in the next M5B-1 reducer stage.
                raise CanonOperationError(f"operation kind {operation.kind} is not applied by this reducer stage")
            case _:  # pragma: no cover - exhaustiveness guard
                assert_never(operation)
    return CanonContent(
        entities_by_id=entities,
        facts_by_id=facts,
        events_by_id=events,
        epistemic_propositions_by_ref=propositions,
        knowledge_states_by_id=knowledge_states,
        temporal_relations_by_id=temporal_relations,
    )
