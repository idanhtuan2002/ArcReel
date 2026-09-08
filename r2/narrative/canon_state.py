from __future__ import annotations

from collections.abc import Mapping
from typing import assert_never

from pydantic import ConfigDict

from r2.contracts import (
    AddEntityOperation,
    AddEventOperation,
    AddFactOperation,
    CanonBranchSnapshot,
    CanonContent,
    CanonDelta,
    Entity,
    Event,
    Fact,
    RetireFactOperation,
    UpdateEntityOperation,
)
from r2.contracts.common import NonEmptyStr, R2ContractModel

from .errors import CanonOperationError
from .hashing import compute_canon_content_hash


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


def apply_canon_delta(base: CanonContent, delta: CanonDelta) -> CanonContent:
    entities: dict[str, Entity] = dict(base.entities_by_id)
    facts: dict[str, Fact] = dict(base.facts_by_id)
    events: dict[str, Event] = dict(base.events_by_id)
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
            case _:  # pragma: no cover - exhaustiveness guard
                assert_never(operation)
    return CanonContent(entities_by_id=entities, facts_by_id=facts, events_by_id=events)
