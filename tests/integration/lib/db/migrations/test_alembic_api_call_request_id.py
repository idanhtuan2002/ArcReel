"""Alembic migration adding api_calls.request_id."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from alembic import command

REVISION = "b8d4f0e2a300"
DOWN_REVISION = "a7c3e9d1f200"


def _columns(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = conn.execute(sa.text("PRAGMA table_info(api_calls)")).fetchall()
    engine.dispose()
    return {row[1] for row in rows}


def _indexes(db_path: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = conn.execute(sa.text("PRAGMA index_list('api_calls')")).fetchall()
    engine.dispose()
    return {row[1] for row in rows}


def test_upgrade_adds_nullable_request_id(alembic_cfg) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, REVISION)

    assert "request_id" in _columns(db_path)
    assert "idx_api_calls_request_id" in _indexes(db_path)


def test_downgrade_drops_request_id_and_keeps_existing_indexes(alembic_cfg) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, REVISION)
    command.downgrade(cfg, DOWN_REVISION)

    assert "request_id" not in _columns(db_path)
    assert {"idx_api_calls_task_id", "uq_api_calls_execution_id"} <= _indexes(db_path)
