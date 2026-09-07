"""Alembic coverage for durable C04 budget authorization state."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

REVISION = "c04b7d93e5a1"
DOWN_REVISION = "9f3c7a52d1b4"


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def test_upgrade_adds_budget_tables_constraints_and_indexes(
    alembic_cfg: tuple[Config, Path],
) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, DOWN_REVISION)

    engine = _engine(db_path)
    try:
        with engine.begin() as connection:
            assert {"budget_scopes", "budget_reservations"}.isdisjoint(sa.inspect(connection).get_table_names())

        command.upgrade(cfg, REVISION)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert {"budget_scopes", "budget_reservations"} <= set(inspector.get_table_names())

            uniques = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("budget_reservations")}
            assert ("execution_decision_ref",) in uniques

            indexes = {tuple(item["column_names"]) for item in inspector.get_indexes("budget_reservations")}
            assert ("budget_scope_ref",) in indexes
            assert ("cost_record_ref",) in indexes

            scope_checks = {item["name"] for item in inspector.get_check_constraints("budget_scopes")}
            assert scope_checks == {
                "ck_budget_scopes_authorized_limit_nonnegative",
                "ck_budget_scopes_committed_total_nonnegative",
                "ck_budget_scopes_reserved_total_nonnegative",
                "ck_budget_scopes_version_nonnegative",
            }
            reservation_checks = {
                item["name"] for item in inspector.get_check_constraints("budget_reservations")
            }
            assert reservation_checks == {
                "ck_budget_reservations_reserved_amount_positive",
                "ck_budget_reservations_state",
                "ck_budget_reservations_version_nonnegative",
            }

            foreign_keys = inspector.get_foreign_keys("budget_reservations")
            assert any(
                item["constrained_columns"] == ["budget_scope_ref"] and item["referred_table"] == "budget_scopes"
                for item in foreign_keys
            )
    finally:
        engine.dispose()


def test_downgrade_removes_only_budget_tables(
    alembic_cfg: tuple[Config, Path],
) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, DOWN_REVISION)

    engine = _engine(db_path)
    try:
        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            protected_columns = {
                table: tuple(column["name"] for column in inspector.get_columns(table))
                for table in ("tasks", "api_calls")
            }

        command.upgrade(cfg, REVISION)
        command.downgrade(cfg, DOWN_REVISION)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            table_names = set(inspector.get_table_names())
            assert {"budget_scopes", "budget_reservations"}.isdisjoint(table_names)
            assert {"tasks", "api_calls"} <= table_names
            assert {
                table: tuple(column["name"] for column in inspector.get_columns(table))
                for table in ("tasks", "api_calls")
            } == protected_columns
    finally:
        engine.dispose()
