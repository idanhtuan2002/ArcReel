"""Alembic coverage for the additive M6 screenplay-admission schema (plan Task 12)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {"adaptation_screenplay_admissions"}
GLOB = "*_add_screenplay_admission.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(sorted(fk["constrained_columns"])): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_the_screenplay_admission_schema_additively(
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
            assert "adaptation_screenplays" in sa.inspect(connection).get_table_names()

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            pk = inspector.get_pk_constraint("adaptation_screenplay_admissions")
            assert set(pk["constrained_columns"]) == {"screenplay_id", "screenplay_version"}

            fks = _fk_by_local_columns(inspector, "adaptation_screenplay_admissions")
            screenplay_fk = fks[("project_name", "screenplay_id", "screenplay_version", "user_id")]
            assert screenplay_fk["referred_table"] == "adaptation_screenplays"
            assert str((screenplay_fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT"
            decision_fk = fks[("admission_decision_id", "project_name", "user_id")]
            assert decision_fk["referred_table"] == "adaptation_decisions"

            unique = {
                tuple(sorted(c["column_names"]))
                for c in inspector.get_unique_constraints("adaptation_screenplay_admissions")
            }
            assert tuple(sorted(("project_name", "screenplay_id", "screenplay_version", "user_id"))) in unique
    finally:
        engine.dispose()


def test_downgrade_then_upgrade_round_trips(
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
        command.upgrade(cfg, revision)
        with engine.begin() as connection:
            assert set(sa.inspect(connection).get_table_names()) >= EXPECTED_TABLES
    finally:
        engine.dispose()
