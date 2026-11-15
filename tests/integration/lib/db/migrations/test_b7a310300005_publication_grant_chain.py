"""The publication-authorization grant-chain migration backfills existing rows and keeps the table append-only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command

REVISION = "b7a310300005"
PREDECESSOR = "b7a310300004"
TABLE = "m10_profile_publication_authorizations"


def _insert(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"INSERT INTO {TABLE} (user_id,project_name,authorization_id,action,actor_id,command_id,request_digest,"
        "subject_digest,policy_id,policy_version,evidence_digest,grant_sequence,issued_at,admit_not_after,"
        "request_json,lease_json) VALUES ('u','show-a','auth-1','PROFILE_PUBLICATION','admin','c',"
        "'sha256:a','sha256:b','p','1','sha256:c',1,'2026-11-01 00:00:00','2026-11-01 00:00:30','{}','{}')"
    )


def test_existing_rows_rest_on_their_project_and_stay_immutable(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        _insert(connection)
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        assert connection.execute(f"SELECT project_name, grant_project_name FROM {TABLE}").fetchall() == [
            ("show-a", "show-a")
        ]
        foreign = [row for row in connection.execute(f'PRAGMA foreign_key_list("{TABLE}")') if row[2] != "users"]
        assert sorted(row[3] for row in foreign) == ["actor_id", "grant_project_name", "grant_sequence", "user_id"]
        with pytest.raises(sqlite3.DatabaseError, match="M10_IMMUTABLE_PUBLICATION_ROW"):
            connection.execute(f"UPDATE {TABLE} SET grant_sequence = 2")
        with pytest.raises(sqlite3.DatabaseError, match="M10_IMMUTABLE_PUBLICATION_ROW"):
            connection.execute(f"DELETE FROM {TABLE}")
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{TABLE}")')}
        assert "grant_project_name" not in columns
        with pytest.raises(sqlite3.DatabaseError, match="M10_IMMUTABLE_PUBLICATION_ROW"):
            connection.execute(f"DELETE FROM {TABLE}")
    command.upgrade(cfg, REVISION)
