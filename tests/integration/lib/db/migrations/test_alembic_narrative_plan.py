"""Alembic coverage for the append-only NarrativePlan schema."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {"narrative_plans", "narrative_plan_versions"}
GLOB = "*_add_narrative_plans.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(fk["constrained_columns"]): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_narrative_plan_schema(
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

            plan_fks = _fk_by_local_columns(inspector, "narrative_plans")
            assert ("head_version",) not in plan_fks

            version_fks = _fk_by_local_columns(inspector, "narrative_plan_versions")
            assert version_fks[("plan_id",)]["referred_table"] == "narrative_plans"
            parent_fk = version_fks[("plan_id", "parent_version")]
            assert parent_fk["referred_table"] == "narrative_plan_versions"
            assert set(parent_fk["referred_columns"]) == {"plan_id", "version"}
            for local_columns, fk in version_fks.items():
                if fk["referred_table"] in EXPECTED_TABLES:
                    assert str((fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT", local_columns

            uniques = {item["name"] for item in inspector.get_unique_constraints("narrative_plan_versions")}
            assert "uq_narrative_plan_versions_plan_revision_id" in uniques
            assert "uq_narrative_plan_versions_approval_ref" in uniques

            checks = {item["name"] for item in inspector.get_check_constraints("narrative_plan_versions")}
            assert "ck_narrative_plan_versions_version_positive" in checks
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
