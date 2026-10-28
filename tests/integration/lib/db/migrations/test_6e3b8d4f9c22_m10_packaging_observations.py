"""The packaging-observation migration adds one append-only table and refuses lossy downgrade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from lib.db.models.quality_packaging import PackagingObservationModel

REVISION = "6e3b8d4f9c22"
PREDECESSOR = "5d2a7c3e8b11"
TABLE = PackagingObservationModel.__table__


def test_exact_singleton_head_and_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, _ = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {item.revision for item in script.walk_revisions(base="base", head=heads[0])}
    assert script.get_revision(REVISION).down_revision == PREDECESSOR


def _insert(connection: sqlite3.Connection, *, observation: str = "o1", status: str = "PASS") -> None:
    connection.execute(
        f'INSERT INTO "{TABLE.name}" (user_id,project_name,observation_id,actor_id,command_id,request_digest,'
        "candidate_id,candidate_revision,candidate_payload_digest,quality_run_id,constraint_snapshot_digest,status,"
        "observation_digest,observation_json,recorded_at) VALUES ('f','f',?,'a',?,'d','c',1,'d','r','d',?,'d','{}',"
        "'2026-10-28 00:00:00')",
        (observation, observation, status),
    )


def test_upgrade_matches_the_orm_and_downgrade_restores_the_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert after - before == {TABLE.name}
        reflected = connection.execute(f'PRAGMA table_info("{TABLE.name}")').fetchall()
        assert {row[1]: not bool(row[3]) for row in reflected} == {c.name: c.nullable for c in TABLE.columns}
        foreign = connection.execute(f'PRAGMA foreign_key_list("{TABLE.name}")').fetchall()
        assert {row[2] for row in foreign} == {"users", "m8_candidate_revisions"}
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLE.name,)
        ).fetchone()[0]
        checks = {c.name for c in TABLE.constraints if isinstance(c, sa.CheckConstraint)}
        assert all(f"CONSTRAINT {name} CHECK" in sql for name in checks)
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == before
    command.upgrade(cfg, REVISION)


def test_rows_are_append_only_and_downgrade_refuses_to_discard_them(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _insert(connection)
        with pytest.raises(sqlite3.IntegrityError, match="ck_m10_packaging_observations_status"):
            _insert(connection, observation="o2", status="WAIVED")
        connection.commit()
        for statement in (f'UPDATE "{TABLE.name}" SET status=status', f'DELETE FROM "{TABLE.name}"'):
            with pytest.raises(sqlite3.IntegrityError, match="M10_IMMUTABLE_PACKAGING_ROW"):
                connection.execute(statement)
    with pytest.raises(RuntimeError, match="M10_PACKAGING_HISTORY_PRESENT"):
        command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
