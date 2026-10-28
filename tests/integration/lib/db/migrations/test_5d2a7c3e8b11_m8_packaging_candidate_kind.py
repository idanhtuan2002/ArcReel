"""The PACKAGING kind migration broadens only the M8 kind CHECK, keeps predecessor rows and refuses lossy downgrade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from lib.db.models.advanced_creative import M8CandidateRevisionModel

REVISION = "5d2a7c3e8b11"
PREDECESSOR = "4c1f0e2a9b10"
TABLE = M8CandidateRevisionModel.__table__.name


def test_exact_singleton_head_and_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, _ = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {item.revision for item in script.walk_revisions(base="base", head=heads[0])}
    assert script.get_revision(REVISION).down_revision == PREDECESSOR


def _insert(connection: sqlite3.Connection, *, candidate: str, kind: str) -> None:
    connection.execute(
        "INSERT INTO m8_candidate_heads (user_id,project_name,candidate_id,current_revision,head_version,"
        "created_at,updated_at) VALUES ('fixture','fixture',?,1,1,'2026-10-28 00:00:00','2026-10-28 00:00:00')",
        (candidate,),
    )
    connection.execute(
        f'INSERT INTO "{TABLE}" (user_id,project_name,candidate_id,revision,parent_revision,kind,payload_json,'
        "payload_digest,lineage_json,created_by,created_at) "
        "VALUES ('fixture','fixture',?,1,NULL,?,'{}',?,'{}','fixture','2026-10-28 00:00:00')",
        (candidate, kind, "sha256:" + "a" * 64),
    )


def _check_sql(connection: sqlite3.Connection) -> str:
    return connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone()[0]


def test_upgrade_admits_packaging_and_keeps_predecessor_rows(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _insert(connection, candidate="format", kind="FORMAT")
        with pytest.raises(sqlite3.IntegrityError, match="ck_m8_candidate_revisions_kind"):
            _insert(connection, candidate="early", kind="PACKAGING")
        connection.commit()
        before = _check_sql(connection)
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        assert connection.execute(f'SELECT candidate_id, kind FROM "{TABLE}"').fetchall() == [("format", "FORMAT")]
        _insert(connection, candidate="package", kind="PACKAGING")
        with pytest.raises(sqlite3.IntegrityError, match="ck_m8_candidate_revisions_kind"):
            _insert(connection, candidate="unknown", kind="OTHER")
        after = _check_sql(connection)
    declared = next(
        c for c in M8CandidateRevisionModel.__table__.constraints if c.name == "ck_m8_candidate_revisions_kind"
    )
    assert "'PACKAGING'" in str(declared.sqltext)
    assert "'PACKAGING'" in after
    assert "'PACKAGING'" not in before
    for other in ("ck_m8_candidate_revisions_parent", "ck_m8_candidate_revisions_revision"):
        assert other in after


def test_downgrade_refuses_while_packaging_revisions_exist(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _insert(connection, candidate="package", kind="PACKAGING")
        connection.commit()
    with pytest.raises(RuntimeError, match="M10_PACKAGING_HISTORY_PRESENT"):
        command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)


def test_downgrade_without_packaging_restores_the_predecessor_check(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        assert "'PACKAGING'" not in _check_sql(connection)
        _insert(connection, candidate="format", kind="FORMAT")
    command.upgrade(cfg, REVISION)
