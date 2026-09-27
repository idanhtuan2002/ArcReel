"""Alembic migration adding the H7 request/task correlation columns."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa

from alembic import command

REVISION = "a7c3e9d1f200"
DOWN_REVISION = "d80b64c4edcf"


def _columns(db_path: Path, table: str) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    engine.dispose()
    return {row[1] for row in rows}


def _indexes(db_path: Path, table: str) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        rows = conn.execute(sa.text(f"PRAGMA index_list('{table}')")).fetchall()
    engine.dispose()
    return {row[1] for row in rows}


def test_upgrade_adds_nullable_correlation_columns_without_backfill(alembic_cfg) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, DOWN_REVISION)
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO tasks (task_id, project_name, task_type, media_type, resource_id, status, "
                "source, queued_at, updated_at) VALUES ('T-old', 'demo', 'image', 'image', 'E1S01', "
                "'succeeded', 'webui', '2026-09-01 00:00:00', '2026-09-01 00:00:00')"
            )
        )
    engine.dispose()

    command.upgrade(cfg, REVISION)

    assert "request_id" in _columns(db_path, "tasks")
    assert "task_id" in _columns(db_path, "api_calls")
    assert "idx_tasks_request_id" in _indexes(db_path, "tasks")
    assert "idx_api_calls_task_id" in _indexes(db_path, "api_calls")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT request_id FROM tasks WHERE task_id='T-old'")).scalar() is None
    engine.dispose()


def test_downgrade_drops_correlation_columns_and_preserves_existing_indexes(alembic_cfg) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, REVISION)
    command.downgrade(cfg, DOWN_REVISION)

    assert "request_id" not in _columns(db_path, "tasks")
    assert "task_id" not in _columns(db_path, "api_calls")
    assert "idx_tasks_dedupe_active" in _indexes(db_path, "tasks")
    assert "uq_api_calls_execution_id" in _indexes(db_path, "api_calls")
