"""Alembic coverage for the additive M6 adaptation authority schema (plan Task 7)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {"adaptation_decisions", "adaptation_heads"}
GLOB = "*_add_adaptation_authority.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(sorted(fk["constrained_columns"])): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_the_adaptation_authority_schema_additively(
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
            assert "adaptation_branches" in sa.inspect(connection).get_table_names()

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            decisions_pk = inspector.get_pk_constraint("adaptation_decisions")
            assert set(decisions_pk["constrained_columns"]) == {"user_id", "project_name", "decision_id"}

            heads_pk = inspector.get_pk_constraint("adaptation_heads")
            assert set(heads_pk["constrained_columns"]) == {"user_id", "project_name", "family", "head_key"}

            head_fks = _fk_by_local_columns(inspector, "adaptation_heads")
            latest_fk = head_fks[("latest_decision_id", "project_name", "user_id")]
            assert latest_fk["referred_table"] == "adaptation_decisions"
            assert set(latest_fk["referred_columns"]) == {"decision_id", "project_name", "user_id"}
            effective_fk = head_fks[("effective_decision_id", "project_name", "user_id")]
            assert effective_fk["referred_table"] == "adaptation_decisions"

            for table in EXPECTED_TABLES:
                for cols, fk in _fk_by_local_columns(inspector, table).items():
                    if fk["referred_table"] == "users":
                        continue
                    assert str((fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT", (table, cols)

            decision_checks = {c["name"] for c in inspector.get_check_constraints("adaptation_decisions")}
            assert "ck_adaptation_decisions_family" in decision_checks
            assert "ck_adaptation_decisions_sequence" in decision_checks
            head_checks = {c["name"] for c in inspector.get_check_constraints("adaptation_heads")}
            assert "ck_adaptation_heads_generation" in head_checks

            decisions_unique = {
                tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints("adaptation_decisions")
            }
            assert tuple(sorted(("family", "head_key", "project_name", "sequence", "user_id"))) in decisions_unique
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
