from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from .common import JSONValue, NonEmptyStr, R2ContractModel


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _aware_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


def _sorted_unique(values: list[NonEmptyStr]) -> list[NonEmptyStr]:
    return sorted(set(values))


def _reject_duplicates_then_sort(value: object) -> object:
    if isinstance(value, list):
        seen: list[object] = []
        for item in value:
            if item in seen:
                raise ValueError("duplicate references are not allowed")
            seen.append(item)
        return sorted(value)
    return value


class CanonBranchType(StrEnum):
    MAIN = "MAIN"
    NARRATIVE_BRANCH = "NARRATIVE_BRANCH"


class EntityType(StrEnum):
    CHARACTER = "CHARACTER"
    LOCATION = "LOCATION"
    OBJECT = "OBJECT"
    ORGANIZATION = "ORGANIZATION"


class Entity(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entity_id: NonEmptyStr
    entity_type: EntityType
    canonical_name: NonEmptyStr
    aliases: list[NonEmptyStr] = Field(default_factory=list)
    _aliases_sorted = field_validator("aliases")(_sorted_unique)


class Fact(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fact_id: NonEmptyStr
    subject_ref: NonEmptyStr
    predicate: NonEmptyStr
    value: JSONValue
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    source_event_refs: list[NonEmptyStr] = Field(default_factory=list)
    _effective_from_aware = field_validator("effective_from")(_aware_optional)
    _effective_until_aware = field_validator("effective_until")(_aware_optional)
    _source_event_refs_sorted = field_validator("source_event_refs")(_sorted_unique)


class Event(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: NonEmptyStr
    event_type: NonEmptyStr
    participant_refs: list[NonEmptyStr]
    location_ref: NonEmptyStr | None = None
    temporal_anchor: datetime | None = None
    causal_refs: list[NonEmptyStr] = Field(default_factory=list)
    state_effect_refs: list[NonEmptyStr] = Field(default_factory=list)
    _temporal_anchor_aware = field_validator("temporal_anchor")(_aware_optional)
    _participant_and_causal_refs = field_validator("participant_refs", "causal_refs", mode="before")(
        _reject_duplicates_then_sort
    )
    _state_effect_refs_sorted = field_validator("state_effect_refs")(_sorted_unique)


class AddEntityOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["ADD_ENTITY"] = "ADD_ENTITY"
    target_id: NonEmptyStr
    entity: Entity


class UpdateEntityOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["UPDATE_ENTITY"] = "UPDATE_ENTITY"
    target_id: NonEmptyStr
    entity: Entity


class AddFactOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["ADD_FACT"] = "ADD_FACT"
    target_id: NonEmptyStr
    fact: Fact


class RetireFactOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["RETIRE_FACT"] = "RETIRE_FACT"
    target_id: NonEmptyStr
    effective_until: datetime
    _effective_until_aware = field_validator("effective_until")(_aware)


class AddEventOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["ADD_EVENT"] = "ADD_EVENT"
    target_id: NonEmptyStr
    event: Event


CanonOperation = Annotated[
    AddEntityOperation | UpdateEntityOperation | AddFactOperation | RetireFactOperation | AddEventOperation,
    Field(discriminator="kind"),
]


class CanonContent(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    entities_by_id: dict[NonEmptyStr, Entity]
    facts_by_id: dict[NonEmptyStr, Fact]
    events_by_id: dict[NonEmptyStr, Event]

    @model_validator(mode="after")
    def _keys_match_atom_ids(self) -> CanonContent:
        for key, entity in self.entities_by_id.items():
            if key != entity.entity_id:
                raise ValueError(f"CanonContent entity key {key!r} does not match entity_id {entity.entity_id!r}")
        for key, fact in self.facts_by_id.items():
            if key != fact.fact_id:
                raise ValueError(f"CanonContent fact key {key!r} does not match fact_id {fact.fact_id!r}")
        for key, event in self.events_by_id.items():
            if key != event.event_id:
                raise ValueError(f"CanonContent event key {key!r} does not match event_id {event.event_id!r}")
        return self


class CanonDeltaPayload(R2ContractModel):
    canon_delta_id: NonEmptyStr
    target_branch_id: NonEmptyStr
    base_canon_version_id: NonEmptyStr | None
    operations: list[CanonOperation]
    source_change_set_refs: list[NonEmptyStr]
    author_decision_refs: list[NonEmptyStr]
    validation_report_refs: list[NonEmptyStr]
    payload_hash_algorithm: Literal["sha256"] = "sha256"
    payload_hash_version: Literal["r2-canon-delta-v1"] = "r2-canon-delta-v1"
    content_schema_version: Literal["r2-canon-schema-v1"] = "r2-canon-schema-v1"
    created_at: datetime
    created_by: NonEmptyStr
    _created_at_aware = field_validator("created_at")(_aware)
    _source_change_set_refs_sorted = field_validator("source_change_set_refs")(_sorted_unique)
    _author_decision_refs_sorted = field_validator("author_decision_refs")(_sorted_unique)
    _validation_report_refs_sorted = field_validator("validation_report_refs")(_sorted_unique)

    @model_validator(mode="after")
    def _validate_operation_list(self) -> CanonDeltaPayload:
        if not self.operations:
            raise ValueError("Canon delta must contain at least one operation")
        operation_ids = [operation.operation_id for operation in self.operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Canon delta operation ids must be unique")
        return self


class CanonDelta(CanonDeltaPayload):
    payload_hash: NonEmptyStr


class CanonCommitApproval(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    approval_ref: NonEmptyStr
    canon_delta_id: NonEmptyStr
    payload_hash: NonEmptyStr
    payload_hash_algorithm: Literal["sha256"]
    payload_hash_version: Literal["r2-canon-delta-v1"]
    content_schema_version: Literal["r2-canon-schema-v1"]
    project_name: NonEmptyStr
    user_id: NonEmptyStr
    approved_by: NonEmptyStr
    approved_at: datetime
    status: Literal["APPROVED"]
    _approved_at_aware = field_validator("approved_at")(_aware)


class CreateCanonBranch(R2ContractModel):
    branch_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    branch_type: CanonBranchType
    parent_branch_id: NonEmptyStr | None = None
    parent_version_id: NonEmptyStr | None = None
    created_at: datetime
    created_by: NonEmptyStr
    _created_at_aware = field_validator("created_at")(_aware)


class CanonBranchSnapshot(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    branch_id: NonEmptyStr
    user_id: NonEmptyStr
    project_name: NonEmptyStr
    branch_type: CanonBranchType
    parent_branch_id: NonEmptyStr | None
    parent_version_id: NonEmptyStr | None
    head_version_id: NonEmptyStr | None
    created_at: datetime
    created_by: NonEmptyStr
    _created_at_aware = field_validator("created_at")(_aware)


class CanonVersionSnapshot(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    canon_version_id: NonEmptyStr
    branch_id: NonEmptyStr
    version_number: Annotated[int, Field(ge=1)]
    parent_version_id: NonEmptyStr | None
    committed_delta_id: NonEmptyStr
    committed_at: datetime
    committed_by: NonEmptyStr
    content_hash: NonEmptyStr
    content_hash_algorithm: NonEmptyStr
    content_hash_version: NonEmptyStr
    content_schema_version: NonEmptyStr
    _committed_at_aware = field_validator("committed_at")(_aware)


class AcceptedCanonDeltaSnapshot(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    delta: CanonDelta
    approval: CanonCommitApproval
    committed_version_id: NonEmptyStr


class CanonValidationFinding(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_id: NonEmptyStr
    affected_refs: tuple[NonEmptyStr, ...]
    message: NonEmptyStr


class CanonValidationReport(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    findings: tuple[CanonValidationFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


class CanonCommitResult(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    accepted_delta: AcceptedCanonDeltaSnapshot
    version: CanonVersionSnapshot
    validation_report: CanonValidationReport
