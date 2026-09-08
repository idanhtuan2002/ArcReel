"""Canon authority ORM registration and metadata shape."""

from __future__ import annotations

from lib.db.base import Base
from lib.db.models import register_models

register_models()

CANON_TABLES = {"canon_branches", "canon_deltas", "canon_versions", "canon_resolved_projections"}


def test_all_four_canon_tables_are_registered() -> None:
    assert set(Base.metadata.tables) >= CANON_TABLES


def test_branch_version_pointers_have_no_physical_foreign_key() -> None:
    branch = Base.metadata.tables["canon_branches"]
    fk_local_columns = {fk.parent.name for fk in branch.foreign_keys}
    assert "head_version_id" not in fk_local_columns
    assert "parent_version_id" not in fk_local_columns
    assert "parent_branch_id" in fk_local_columns


def test_every_canon_to_canon_foreign_key_restricts_delete() -> None:
    for table_name in CANON_TABLES:
        table = Base.metadata.tables[table_name]
        for fk in table.foreign_keys:
            if fk.column.table.name in CANON_TABLES:
                assert fk.ondelete == "RESTRICT", (table_name, fk.parent.name)


def test_one_main_branch_per_scope_is_a_partial_unique_index() -> None:
    branch = Base.metadata.tables["canon_branches"]
    matches = [ix for ix in branch.indexes if ix.name == "uq_canon_branches_one_main_per_scope"]
    assert len(matches) == 1
    assert matches[0].unique is True
    assert {col.name for col in matches[0].columns} == {"user_id", "project_name"}


def test_delta_carries_the_approval_and_committed_version_columns() -> None:
    delta = Base.metadata.tables["canon_deltas"]
    assert {"approval_ref", "approved_by", "approved_at", "approval_status", "committed_version_id"} <= set(
        delta.columns.keys()
    )
    assert delta.columns["operations_json"].nullable is False
