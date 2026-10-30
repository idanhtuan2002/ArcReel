"""Actual Alembic roundtrip preserves predecessor rows and scoped schema."""

import sqlite3

from alembic.script import ScriptDirectory

from alembic import command

REVISION = "b7a310300002"
PREDECESSOR = "b7a310300001"
TABLES = {"auto_grant_events", "auto_authorization_decisions", "auto_grant_heads"}


def test_real_alembic_upgrade_downgrade_preserves_predecessor(alembic_cfg):
    cfg, database = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_revision(REVISION).down_revision == PREDECESSOR
    assert len(script.get_heads()) == 1
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        connection.execute(
            "INSERT INTO users (id,username,created_at,updated_at) "
            "VALUES ('auto-witness','auto-witness','2026-10-30','2026-10-30')"
        )
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert after - before == TABLES
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        remaining = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert remaining == before
        assert connection.execute("SELECT username FROM users WHERE id='auto-witness'").fetchone() == ("auto-witness",)
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
