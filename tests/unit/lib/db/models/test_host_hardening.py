from __future__ import annotations

from sqlalchemy import Table

from lib.db.base import Base
from lib.db.models.host_hardening import (
    AttemptIntegrityIncidentModel,
    CommandReceiptModel,
    ExecutionAttemptModel,
    OperatorResolutionReceiptModel,
    ProjectEventModel,
    ProviderObservationModel,
)

_TABLES = {
    "execution_attempts",
    "provider_observations",
    "attempt_integrity_incidents",
    "operator_resolution_receipts",
    "command_receipts",
    "project_events",
}


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _is_unique(constraint: object) -> bool:
    return type(constraint).__name__ == "UniqueConstraint"


def _unique_column_sets(table: Table) -> set[frozenset[str]]:
    return {frozenset(c.columns.keys()) for c in table.constraints if _is_unique(c)}


def test_every_model_registers_its_table() -> None:
    assert set(Base.metadata.tables) >= _TABLES


def test_execution_attempts_primary_key_is_execution_id() -> None:
    table = _table("execution_attempts")
    assert {c.name for c in table.primary_key.columns} == {"execution_id"}


def test_execution_attempts_enforces_the_plan_idempotent_identity() -> None:
    unique = _unique_column_sets(_table("execution_attempts"))
    assert frozenset({"user_id", "project_name", "task_id", "attempt_no"}) in unique


def test_provider_observations_primary_key_is_execution_and_received_seq() -> None:
    table = _table("provider_observations")
    assert {c.name for c in table.primary_key.columns} == {"execution_id", "received_seq"}


def test_provider_observations_duplicate_observation_id_is_unique_per_attempt() -> None:
    unique = _unique_column_sets(_table("provider_observations"))
    assert frozenset({"execution_id", "observation_id"}) in unique


def test_command_receipts_primary_key_is_the_actor_scoped_command_identity() -> None:
    table = _table("command_receipts")
    assert {c.name for c in table.primary_key.columns} == {"user_id", "project_name", "actor_scope", "command_id"}


def test_project_events_dedupe_key_is_unique_within_scope() -> None:
    unique = _unique_column_sets(_table("project_events"))
    assert frozenset({"user_id", "project_name", "dedupe_key"}) in unique


def test_project_events_event_id_is_the_sole_primary_key() -> None:
    table = _table("project_events")
    assert {c.name for c in table.primary_key.columns} == {"event_id"}


def test_attempt_integrity_incidents_and_operator_resolution_receipts_reference_execution_attempts() -> None:
    for model, table_name in (
        (AttemptIntegrityIncidentModel, "attempt_integrity_incidents"),
        (OperatorResolutionReceiptModel, "operator_resolution_receipts"),
    ):
        assert model.__tablename__ == table_name
        table = _table(table_name)
        fk_targets = {
            fk.column.table.name for fk_constraint in table.foreign_key_constraints for fk in fk_constraint.elements
        }
        assert "execution_attempts" in fk_targets


def test_command_receipt_and_project_event_and_provider_observation_models_export_their_tablenames() -> None:
    assert CommandReceiptModel.__tablename__ == "command_receipts"
    assert ProjectEventModel.__tablename__ == "project_events"
    assert ProviderObservationModel.__tablename__ == "provider_observations"
    assert ExecutionAttemptModel.__tablename__ == "execution_attempts"
