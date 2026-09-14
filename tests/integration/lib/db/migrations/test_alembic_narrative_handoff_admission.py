"""Alembic coverage for the additive M5C-4 handoff-admission schema."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {
    "narrative_handoff_admissions",
    "narrative_handoff_admission_observed_heads",
}
GLOB = "*_add_narrative_handoff_admission.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(sorted(fk["constrained_columns"])): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_the_handoff_admission_schema_additively(
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
            assert "narrative_compilation_attempts" in sa.inspect(connection).get_table_names()

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            admission_uniques = {
                tuple(sorted(u["column_names"]))
                for u in inspector.get_unique_constraints("narrative_handoff_admissions")
            }
            assert tuple(sorted(("user_id", "project_name", "admission_id"))) in admission_uniques

            observed_head_pk = inspector.get_pk_constraint("narrative_handoff_admission_observed_heads")
            assert set(observed_head_pk["constrained_columns"]) == {"admission_id", "position"}

            for table in EXPECTED_TABLES:
                for cols, fk in _fk_by_local_columns(inspector, table).items():
                    if fk["referred_table"] == "users":
                        continue
                    assert str((fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT", (table, cols)

            checks = {c["name"] for c in inspector.get_check_constraints("narrative_handoff_admissions")}
            assert "ck_narrative_handoff_admissions_fingerprint_algorithm" in checks
            assert "ck_narrative_handoff_admissions_fingerprint_version" in checks

            head_checks = {
                c["name"] for c in inspector.get_check_constraints("narrative_handoff_admission_observed_heads")
            }
            assert "ck_narrative_handoff_admission_observed_heads_family" in head_checks
            assert "ck_narrative_handoff_admission_observed_heads_not_ahead" in head_checks
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
