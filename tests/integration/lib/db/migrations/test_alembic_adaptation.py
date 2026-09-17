"""Alembic coverage for the additive M6 adaptation evidence schema."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {
    "adaptation_branches",
    "adaptation_maps",
    "adaptation_map_entries",
    "adaptation_map_profile_analysis_refs",
    "adaptation_screenplays",
    "adaptation_screenplay_scenes",
    "adaptation_screenplay_profile_analysis_refs",
}
GLOB = "*_add_adaptation_evidence.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(sorted(fk["constrained_columns"])): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_the_adaptation_schema_additively(
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
            assert "narrative_handoff_admissions" in sa.inspect(connection).get_table_names()

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            branch_pk = inspector.get_pk_constraint("adaptation_branches")
            assert set(branch_pk["constrained_columns"]) == {"branch_id", "version"}

            map_fks = _fk_by_local_columns(inspector, "adaptation_maps")
            branch_ref_fk = map_fks[
                ("adaptation_branch_ref_id", "adaptation_branch_ref_version", "project_name", "user_id")
            ]
            assert branch_ref_fk["referred_table"] == "adaptation_branches"
            assert set(branch_ref_fk["referred_columns"]) == {"branch_id", "version", "project_name", "user_id"}

            for table in EXPECTED_TABLES:
                for cols, fk in _fk_by_local_columns(inspector, table).items():
                    if fk["referred_table"] == "users":
                        continue
                    assert str((fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT", (table, cols)

            checks = {c["name"] for c in inspector.get_check_constraints("adaptation_branches")}
            assert "ck_adaptation_branches_version" in checks
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
