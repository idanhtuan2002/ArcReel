"""Actual Alembic roundtrip of owner attempts and step outcomes."""

import sqlite3

from alembic.script import ScriptDirectory

from alembic import command

REVISION = "b7a310300003"
PREDECESSOR = "b7a310300002"
TABLES = {"auto_owner_attempts", "auto_step_outcomes", "auto_reviewer_qualifications", "auto_model_observations"}


def test_real_alembic_upgrade_downgrade_preserves_predecessor(alembic_cfg):
    cfg, database = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_revision(REVISION).down_revision == PREDECESSOR
    assert len(script.get_heads()) == 1
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert after - before == TABLES
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == before
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
