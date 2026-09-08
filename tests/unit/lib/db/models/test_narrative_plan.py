from __future__ import annotations

from lib.db.base import Base
from lib.db.models.narrative_plan import NarrativePlanModel, NarrativePlanVersionModel


def _table(name: str):
    return Base.metadata.tables[name]


def test_narrative_plans_table_shape() -> None:
    table = _table("narrative_plans")
    assert {column.name for column in table.primary_key} == {"plan_id"}
    columns = {column.name for column in table.columns}
    assert {"user_id", "project_name", "head_version", "created_at", "created_by"} <= columns
    # head_version is a logical pointer: no physical foreign key.
    assert all("narrative_plan_versions" not in str(fk.target_fullname) for fk in table.foreign_keys)
    assert table.columns["head_version"].nullable is True


def test_narrative_plan_versions_immutable_lineage_and_unique_constraints() -> None:
    table = _table("narrative_plan_versions")
    assert {column.name for column in table.primary_key} == {"plan_id", "version"}

    unique = {
        constraint.name: set(constraint.columns.keys()) for constraint in table.constraints if _is_unique(constraint)
    }
    assert unique.get("uq_narrative_plan_versions_plan_revision_id") == {"plan_revision_id"}
    assert unique.get("uq_narrative_plan_versions_approval_ref") == {"approval_ref"}

    fk_by_cols = {tuple(sorted(fk.column_keys)): fk for fk in table.foreign_key_constraints}
    plan_fk = fk_by_cols[("plan_id",)]
    assert "narrative_plans.plan_id" in {element.target_fullname for element in plan_fk.elements}
    assert plan_fk.ondelete == "RESTRICT"

    parent_fk = fk_by_cols[("parent_version", "plan_id")]
    targets = {element.target_fullname for element in parent_fk.elements}
    assert targets == {"narrative_plan_versions.plan_id", "narrative_plan_versions.version"}
    assert parent_fk.ondelete == "RESTRICT"
    assert table.columns["parent_version"].nullable is True


def _is_unique(constraint: object) -> bool:
    return type(constraint).__name__ == "UniqueConstraint"


def test_models_are_registered_on_the_shared_metadata() -> None:
    assert NarrativePlanModel.__tablename__ == "narrative_plans"
    assert NarrativePlanVersionModel.__tablename__ == "narrative_plan_versions"
    assert "narrative_plans" in Base.metadata.tables
    assert "narrative_plan_versions" in Base.metadata.tables
