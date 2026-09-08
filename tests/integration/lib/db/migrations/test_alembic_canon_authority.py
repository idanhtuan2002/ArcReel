"""Alembic coverage for the append-only Canon authority schema."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {"canon_branches", "canon_deltas", "canon_versions", "canon_resolved_projections"}
GLOB = "*_add_canon_authority.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _unique_columns(inspector: sa.Inspector, table: str, name: str) -> set[str]:
    for item in inspector.get_unique_constraints(table):
        if item["name"] == name:
            return set(item["column_names"])
    return set()


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(fk["constrained_columns"]): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_canon_authority_schema(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    revision, parent = migration_revisions(GLOB)
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, parent)

    engine = _engine(db_path)
    try:
        with engine.begin() as connection:
            assert EXPECTED_TABLES.isdisjoint(sa.inspect(connection).get_table_names())

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            assert _unique_columns(inspector, "canon_deltas", "uq_canon_deltas_approval_ref") == {"approval_ref"}

            branch_indexes = {item["name"]: item for item in inspector.get_indexes("canon_branches")}
            assert "uq_canon_branches_one_main_per_scope" in branch_indexes
            assert bool(branch_indexes["uq_canon_branches_one_main_per_scope"]["unique"]) is True
            assert set(branch_indexes["uq_canon_branches_one_main_per_scope"]["column_names"]) == {
                "user_id",
                "project_name",
            }

            branch_fks = _fk_by_local_columns(inspector, "canon_branches")
            assert ("parent_branch_id",) in branch_fks
            assert ("head_version_id",) not in branch_fks
            assert ("parent_version_id",) not in branch_fks

            version_fks = _fk_by_local_columns(inspector, "canon_versions")
            assert version_fks[("branch_id",)]["referred_table"] == "canon_branches"
            assert version_fks[("parent_version_id",)]["referred_table"] == "canon_versions"
            assert version_fks[("committed_delta_id",)]["referred_table"] == "canon_deltas"

            projection_fks = _fk_by_local_columns(inspector, "canon_resolved_projections")
            assert projection_fks[("canon_version_id",)]["referred_table"] == "canon_versions"

            for table in EXPECTED_TABLES:
                for local_columns, fk in _fk_by_local_columns(inspector, table).items():
                    if fk["referred_table"] in EXPECTED_TABLES:
                        ondelete = str((fk["options"] or {}).get("ondelete", "")).upper()
                        assert ondelete == "RESTRICT", (table, local_columns, ondelete)

            version_checks = {item["name"] for item in inspector.get_check_constraints("canon_versions")}
            assert "ck_canon_versions_version_number_positive" in version_checks
            branch_checks = {item["name"] for item in inspector.get_check_constraints("canon_branches")}
            assert "ck_canon_branches_branch_type" in branch_checks
            assert "ck_canon_branches_parent_pairing" in branch_checks

            version_uniques = {item["name"] for item in inspector.get_unique_constraints("canon_versions")}
            assert "uq_canon_versions_committed_delta_id" in version_uniques

            delta_columns = {column["name"]: column for column in inspector.get_columns("canon_deltas")}
            assert delta_columns["operations_json"]["nullable"] is False
            assert delta_columns["payload_hash"]["nullable"] is False
            assert delta_columns["base_canon_version_id"]["nullable"] is True
    finally:
        engine.dispose()


def test_downgrade_removes_only_canon_tables(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    revision, parent = migration_revisions(GLOB)
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, parent)

    engine = _engine(db_path)
    try:
        with engine.begin() as connection:
            before = set(sa.inspect(connection).get_table_names())

        command.upgrade(cfg, revision)
        command.downgrade(cfg, parent)

        with engine.begin() as connection:
            after = set(sa.inspect(connection).get_table_names())

        assert EXPECTED_TABLES.isdisjoint(after)
        assert before == after
    finally:
        engine.dispose()
