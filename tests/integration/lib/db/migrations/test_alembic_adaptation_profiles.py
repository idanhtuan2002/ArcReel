"""Alembic coverage for the additive M6 profile-report/waiver schema (plan Task 11)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = {"adaptation_profile_sidecars", "adaptation_evaluation_reports", "adaptation_evaluation_findings"}
GLOB = "*_add_profile_reports_and_waivers.py"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _fk_by_local_columns(inspector: sa.Inspector, table: str) -> dict[tuple[str, ...], Any]:
    return {tuple(sorted(fk["constrained_columns"])): fk for fk in inspector.get_foreign_keys(table)}


def test_upgrade_creates_the_profile_report_schema_additively(
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
            assert "adaptation_decisions" in sa.inspect(connection).get_table_names()

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            sidecar_pk = inspector.get_pk_constraint("adaptation_profile_sidecars")
            assert set(sidecar_pk["constrained_columns"]) == {"sidecar_id", "version"}

            report_pk = inspector.get_pk_constraint("adaptation_evaluation_reports")
            assert set(report_pk["constrained_columns"]) == {"user_id", "project_name", "report_digest"}

            finding_pk = inspector.get_pk_constraint("adaptation_evaluation_findings")
            assert set(finding_pk["constrained_columns"]) == {
                "user_id",
                "project_name",
                "report_digest",
                "finding_id",
            }

            finding_fks = _fk_by_local_columns(inspector, "adaptation_evaluation_findings")
            report_fk = finding_fks[("project_name", "report_digest", "user_id")]
            assert report_fk["referred_table"] == "adaptation_evaluation_reports"
            assert str((report_fk["options"] or {}).get("ondelete", "")).upper() == "RESTRICT"

            sidecar_checks = {c["name"] for c in inspector.get_check_constraints("adaptation_profile_sidecars")}
            assert "ck_adaptation_profile_sidecars_kind" in sidecar_checks
            finding_checks = {c["name"] for c in inspector.get_check_constraints("adaptation_evaluation_findings")}
            assert "ck_adaptation_evaluation_findings_disposition" in finding_checks

            sidecar_unique = {
                tuple(sorted(c["column_names"]))
                for c in inspector.get_unique_constraints("adaptation_profile_sidecars")
            }
            assert tuple(sorted(("project_name", "sidecar_id", "user_id", "version"))) in sidecar_unique
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
