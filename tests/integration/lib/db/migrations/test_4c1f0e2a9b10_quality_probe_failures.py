"""The M10 probe-failure migration preserves predecessor data, installs append-only custody and refuses lossy downgrade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from lib.db.models.quality_probes import QualityProbeFailureModel

REVISION = "4c1f0e2a9b10"
PREDECESSOR = "bed415be3608"
TABLE = QualityProbeFailureModel.__table__


def test_exact_singleton_head_and_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, _ = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {item.revision for item in script.walk_revisions(base="base", head=heads[0])}
    assert script.get_revision(REVISION).down_revision == PREDECESSOR


def _insert(connection: sqlite3.Connection, *, code: str = "M10_PROBE_FAILED", resources: str | None = "{}") -> None:
    connection.execute(
        "INSERT INTO m10_quality_probe_failures "
        "(user_id,project_name,execution_id,error_code,resources_json,resources_digest,recorded_at) "
        "VALUES ('fixture','fixture','fixture',?,?,?,'2026-10-28 00:00:00')",
        (code, resources, None if resources is None else "sha256:" + "a" * 64),
    )


def test_upgrade_downgrade_upgrade_preserves_predecessor_and_matches_orm(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        connection.execute(
            "INSERT INTO users (id,username,created_at,updated_at) VALUES ('m10-witness','m10-witness','2026-10-28 00:00:00','2026-10-28 00:00:00')"
        )
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert after - before == {TABLE.name}
        reflected = connection.execute(f'PRAGMA table_info("{TABLE.name}")').fetchall()
        assert {row[1]: not bool(row[3]) for row in reflected} == {
            column.name: column.nullable for column in TABLE.columns
        }
        assert [row[1] for row in sorted(reflected, key=lambda row: row[5]) if row[5]] == [
            column.name for column in TABLE.primary_key
        ]
        foreign = connection.execute(f'PRAGMA foreign_key_list("{TABLE.name}")').fetchall()
        assert {row[2] for row in foreign} == {"users", "m10_quality_probe_invocations"}
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (TABLE.name,)
        ).fetchone()[0]
        checks = {constraint.name for constraint in TABLE.constraints if isinstance(constraint, sa.CheckConstraint)}
        assert len(checks) == 3
        assert all(f"CONSTRAINT {name} CHECK" in sql for name in checks)
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == before
        assert connection.execute("SELECT username FROM users WHERE id='m10-witness'").fetchone() == ("m10-witness",)
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)


def test_downgrade_refuses_to_discard_recorded_failures(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _insert(connection)
        connection.commit()
    with pytest.raises(RuntimeError, match="M10_PROBE_FAILURE_HISTORY_PRESENT"):
        command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
        assert connection.execute(f'SELECT count(*) FROM "{TABLE.name}"').fetchone() == (1,)


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_rows_refuse_raw_update_and_delete(alembic_cfg: tuple[Config, Path], operation: str) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _insert(connection)
        connection.commit()
        statement = (
            f'UPDATE "{TABLE.name}" SET user_id=user_id' if operation == "UPDATE" else f'DELETE FROM "{TABLE.name}"'
        )
        with pytest.raises(sqlite3.IntegrityError, match="M10_IMMUTABLE_PROBE_ROW"):
            connection.execute(statement)


@pytest.mark.parametrize(
    ("code", "resources", "match"),
    [
        ("M10_REQUIRED_EVIDENCE_MISSING", "{}", "code"),
        ("M10_PROBE_FAILED", '"' + "x" * 1048576 + '"', "bytes"),
    ],
)
def test_unknown_codes_and_oversized_evidence_are_refused(
    alembic_cfg: tuple[Config, Path], code: str, resources: str, match: str
) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        with pytest.raises(sqlite3.IntegrityError, match=match):
            _insert(connection, code=code, resources=resources)


def test_evidence_json_and_digest_are_present_together(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _insert(connection, resources=None)
        with pytest.raises(sqlite3.IntegrityError, match="resources"):
            connection.execute(
                "INSERT INTO m10_quality_probe_failures "
                "(user_id,project_name,execution_id,error_code,resources_json,resources_digest,recorded_at) "
                "VALUES ('fixture','fixture','other','M10_PROBE_FAILED','{}',NULL,'2026-10-28 00:00:00')"
            )
