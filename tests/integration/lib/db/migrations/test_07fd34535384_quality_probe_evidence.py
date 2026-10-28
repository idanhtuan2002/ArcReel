"""The M10 probe evidence migration preserves predecessor data and installs append-only custody."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from lib.db.models.quality_probes import (
    QualityProbeInvocationModel,
    QualityProbeObservationModel,
    QualityProbeResultModel,
)

REVISION = "07fd34535384"
PREDECESSOR = "65f53650f3a8"
MODELS = (QualityProbeInvocationModel, QualityProbeResultModel, QualityProbeObservationModel)
TABLES = {model.__tablename__ for model in MODELS}


def test_exact_singleton_head_and_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, _ = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {item.revision for item in script.walk_revisions(base="base", head=heads[0])}
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
            actual = {
                (
                    tuple(row[3] for row in sorted(rows, key=lambda row: row[1])),
                    rows[0][2],
                    tuple(row[4] for row in sorted(rows, key=lambda row: row[1])),
                )
                for rows in groups.values()
            }
            expected = {
                (
                    tuple(column.name for column in key.columns),
                    key.referred_table.name,
                    tuple(element.column.name for element in key.elements),
                )
                for key in table.foreign_key_constraints
            }
            assert actual == expected
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table.name,)
            ).fetchone()[0]
            checks = {constraint.name for constraint in table.constraints if isinstance(constraint, sa.CheckConstraint)}
            assert checks
            assert all(f"CONSTRAINT {name} CHECK" in sql for name in checks)
        triggers = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'm10_quality_probe_%'"
            )
        }
        assert triggers == {f"{table}_{action}" for table in TABLES for action in ("no_update", "no_delete")}
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        remaining = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert remaining == before
        assert connection.execute("SELECT username FROM users WHERE id='m10-witness'").fetchone() == ("m10-witness",)
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'm10_quality_probe_%'"
        ).fetchone() == (0,)
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
        assert connection.execute("SELECT username FROM users WHERE id='m10-witness'").fetchone() == ("m10-witness",)


def _insert(connection: sqlite3.Connection, table: str, *, json_value: str = "{}") -> None:
    columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    values: dict[str, object] = {}
    for _, name, _kind, notnull, _, primary in columns:
        if name.endswith("_at"):
            values[name] = "2026-10-28 00:00:00"
        elif name.endswith("_json"):
            values[name] = json_value
        elif notnull or primary:
            values[name] = "fixture"
    names = ",".join(f'"{name}"' for name in values)
    connection.execute(
        f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in values)})', tuple(values.values())
    )


@pytest.mark.parametrize("table", sorted(TABLES))
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_immutable_rows_refuse_raw_update_and_delete(
    alembic_cfg: tuple[Config, Path], table: str, operation: str
) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _insert(connection, table)
        connection.commit()
        statement = f'UPDATE "{table}" SET user_id=user_id' if operation == "UPDATE" else f'DELETE FROM "{table}"'
        with pytest.raises(sqlite3.IntegrityError, match="M10_IMMUTABLE_PROBE_ROW"):
            connection.execute(statement)
        assert connection.execute(f'SELECT count(*) FROM "{table}"').fetchone() == (1,)


@pytest.mark.parametrize("table", sorted(TABLES))
def test_json_bodies_are_bounded_to_one_mebibyte(alembic_cfg: tuple[Config, Path], table: str) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(sqlite3.IntegrityError, match="bytes"):
            _insert(connection, table, json_value='"' + "x" * 1048576 + '"')
