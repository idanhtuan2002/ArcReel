"""The M10 publication migration preserves predecessor data and scoped immutable custody."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from lib.db.models.quality import (
    ProfilePublicationAuthorizationModel,
    QualityCommandModel,
    QualityOutboxModel,
    QualityProfileHeadModel,
    QualityProfileRevisionModel,
)

REVISION = "65f53650f3a8"
PREDECESSOR = "918c4a0e0001"
MODELS = (
    QualityProfileHeadModel,
    QualityProfileRevisionModel,
    ProfilePublicationAuthorizationModel,
    QualityCommandModel,
    QualityOutboxModel,
)
TABLES = {model.__tablename__ for model in MODELS}


def test_exact_singleton_head_and_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, _ = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREDECESSOR


def test_upgrade_downgrade_upgrade_preserves_predecessor_and_matches_orm(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        connection.execute(
            "INSERT INTO users (id,username,created_at,updated_at) VALUES ('m10-witness','m10-witness','2026-10-27 00:00:00','2026-10-27 00:00:00')"
        )
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert after - before == TABLES
        for model in MODELS:
            table = model.__table__
            reflected = connection.execute(f'PRAGMA table_info("{table.name}")').fetchall()
            assert {row[1] for row in reflected} == {column.name for column in table.columns}
            assert [row[1] for row in sorted(reflected, key=lambda row: row[5]) if row[5]] == [
                column.name for column in table.primary_key
            ]
            assert {row[1]: not bool(row[3]) for row in reflected} == {
                column.name: column.nullable for column in table.columns
            }
            foreign = connection.execute(f'PRAGMA foreign_key_list("{table.name}")').fetchall()
            assert any(row[2:5] == ("users", "user_id", "id") and row[6] == "RESTRICT" for row in foreign)
            groups: dict[int, list[tuple]] = {}
            for row in foreign:
                groups.setdefault(row[0], []).append(row)
            actual_keys = {
                (
                    tuple(row[3] for row in sorted(rows, key=lambda row: row[1])),
                    rows[0][2],
                    tuple(row[4] for row in sorted(rows, key=lambda row: row[1])),
                )
                for rows in groups.values()
            }
            expected_keys = {
                (
                    tuple(column.name for column in key.columns),
                    key.referred_table.name,
                    tuple(element.column.name for element in key.elements),
                )
                for key in table.foreign_key_constraints
            }
            assert actual_keys == expected_keys
        triggers = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'm10_%'")
        }
        assert triggers == {
            f"{table}_{action}"
            for table in TABLES - {"m10_quality_profile_heads"}
            for action in ("no_update", "no_delete")
        }
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        remaining = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert remaining == before
        assert connection.execute("SELECT username FROM users WHERE id='m10-witness'").fetchone() == ("m10-witness",)
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'm10_%'"
        ).fetchone() == (0,)
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
        assert connection.execute("SELECT username FROM users WHERE id='m10-witness'").fetchone() == ("m10-witness",)


@pytest.mark.parametrize("table", sorted(TABLES - {"m10_quality_profile_heads"}))
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_immutable_rows_refuse_raw_update_and_delete(
    alembic_cfg: tuple[Config, Path], table: str, operation: str
) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        values = {}
        for _, name, _kind, notnull, _, primary in columns:
            if name in {"revision", "result_revision", "grant_sequence"}:
                values[name] = 1
            elif name in {"parent_revision", "previous_revision"}:
                values[name] = None
            elif name == "operation":
                values[name] = "PUBLISH_PROFILE"
            elif name == "action":
                values[name] = "PROFILE_PUBLICATION"
            elif name == "supersession_effect":
                values[name] = "HISTORICAL_ONLY"
            elif name in {"issued_at", "admitted_at", "committed_at", "created_at"}:
                values[name] = "2026-10-27 00:00:00"
            elif name == "admit_not_after":
                values[name] = "2026-10-27 00:00:30"
            elif "json" in name:
                values[name] = "{}"
            elif notnull or primary:
                values[name] = "fixture"
        names = ",".join(f'"{name}"' for name in values)
        connection.execute(
            f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in values)})', tuple(values.values())
        )
        connection.commit()
        statement = f'UPDATE "{table}" SET user_id=user_id' if operation == "UPDATE" else f'DELETE FROM "{table}"'
        with pytest.raises(sqlite3.IntegrityError, match="M10_IMMUTABLE_PUBLICATION_ROW"):
            connection.execute(statement)
        assert connection.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (1,)


@pytest.mark.parametrize(("revision", "digest"), [(None, "sha256:a"), (1, None), (0, "sha256:a")])
def test_head_revision_digest_pair_is_coherent(
    alembic_cfg: tuple[Config, Path], revision: int | None, digest: str | None
) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO m10_quality_profile_heads (user_id,project_name,profile_id,current_revision,current_digest) VALUES ('default','project','profile',?,?)",
            (revision, digest),
        )
