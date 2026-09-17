"""Alembic coverage for the additive M5C-3 compilation schema."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {
    "narrative_compilation_attempts",
    "narrative_compilation_selected_change_sets",
    "narrative_compilation_conflict_resolutions",
    "narrative_compilation_observed_heads",
    "narrative_compilation_results",
    "narrative_compiled_canon_deltas",
}
GLOB = "*_add_narrative_compilation.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(sorted(fk["constrained_columns"])): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_the_compilation_schema_additively(
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
            assert "narrative_compilation_attempts" not in sa.inspect(connection).get_table_names()
            assert "revision_acceptance_decisions" in sa.inspect(connection).get_table_names()

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            attempt_uniques = {
                tuple(sorted(u["column_names"]))
                for u in inspector.get_unique_constraints("narrative_compilation_attempts")
            }
            assert ("attempt_id", "generation") in attempt_uniques

            result_uniques = {
                tuple(sorted(u["column_names"]))
                for u in inspector.get_unique_constraints("narrative_compilation_results")
            }
            assert ("attempt_id", "generation") in result_uniques

            for table in EXPECTED_TABLES:
                for cols, fk in _fk_by_local_columns(inspector, table).items():
                    if fk["referred_table"] == "users":
                        continue
                    assert str((fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT", (table, cols)

            checks = {c["name"] for c in inspector.get_check_constraints("narrative_compilation_results")}
            assert "ck_narrative_compilation_results_outcome" in checks
            assert "ck_narrative_compilation_results_delta_matches_outcome" in checks
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
