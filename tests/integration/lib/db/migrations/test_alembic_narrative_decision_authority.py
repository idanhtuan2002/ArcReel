"""Alembic coverage for the additive M5C-2 decision-authority schema."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {
    "narrative_decision_identities",
    "revision_acceptance_decisions",
    "change_set_review_decisions",
    "conflict_resolution_lineages",
    "conflict_resolution_decisions",
    "conflict_resolution_decision_competitors",
    "revision_acceptance_heads",
    "change_set_review_heads",
    "conflict_resolution_heads",
}
GLOB = "*_add_narrative_decision_authority.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(sorted(fk["constrained_columns"])): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_the_authority_schema_additively(
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
            assert "narrative_revisions" in sa.inspect(connection).get_table_names()  # parent schema untouched

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            identity_uniques = {
                tuple(sorted(u["column_names"]))
                for u in inspector.get_unique_constraints("narrative_decision_identities")
            }
            assert ("decision_family", "decision_id") in identity_uniques

            lineage_uniques = {
                tuple(sorted(u["column_names"]))
                for u in inspector.get_unique_constraints("conflict_resolution_lineages")
            }
            assert ("conflict_subject_fingerprint", "revision_acceptance_decision_id") in lineage_uniques

            for table in EXPECTED_TABLES:
                for cols, fk in _fk_by_local_columns(inspector, table).items():
                    if fk["referred_table"] == "users":
                        continue
                    assert str((fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT", (table, cols)

            checks = {c["name"] for c in inspector.get_check_constraints("revision_acceptance_heads")}
            assert "ck_revision_acceptance_heads_latest_zero_generation" in checks
            assert "ck_revision_acceptance_heads_effective_zero_generation" in checks
            assert "ck_revision_acceptance_heads_effective_not_ahead" in checks
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
