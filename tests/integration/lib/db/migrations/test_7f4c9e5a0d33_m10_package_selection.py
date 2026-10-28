"""The package-selection migration adds four tables matching the ORM, append-only custody and refusing downgrade."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command
from lib.db.models.quality_packaging import (
    PackagePreviewModel,
    PackageSelectionAuthorizationModel,
    PackageSelectionModel,
    PackagingHeadModel,
)

REVISION = "7f4c9e5a0d33"
PREDECESSOR = "6e3b8d4f9c22"
TABLES = [
    m.__table__
    for m in (PackagePreviewModel, PackageSelectionAuthorizationModel, PackageSelectionModel, PackagingHeadModel)
]


def test_exact_singleton_head_and_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, _ = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {item.revision for item in script.walk_revisions(base="base", head=heads[0])}
    assert script.get_revision(REVISION).down_revision == PREDECESSOR


def test_upgrade_matches_the_orm_and_downgrade_restores_the_predecessor(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert after - before == {t.name for t in TABLES}
        for table in TABLES:
            reflected = connection.execute(f'PRAGMA table_info("{table.name}")').fetchall()
            assert {row[1]: not bool(row[3]) for row in reflected} == {c.name: c.nullable for c in table.columns}
            assert [row[1] for row in sorted(reflected, key=lambda row: row[5]) if row[5]] == [
                c.name for c in table.primary_key
            ]
            foreign = {
                (row[2], row[3]) for row in connection.execute(f'PRAGMA foreign_key_list("{table.name}")').fetchall()
            }
            declared = {
                (element.column.table.name, element.parent.name)
                for constraint in table.foreign_key_constraints
                for element in constraint.elements
            }
            assert foreign == declared, table.name
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table.name,)
            ).fetchone()[0]
            names = {c.name for c in table.constraints if isinstance(c, (sa.CheckConstraint, sa.UniqueConstraint))}
            assert all(f"CONSTRAINT {name}" in sql for name in names), table.name
    command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == before
    command.upgrade(cfg, REVISION)


def _authorization(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO m10_package_selection_authorizations (user_id,project_name,authorization_id,lease_json,"
        "grant_sequence,recorded_at) VALUES ('f','f','lease','{}',1,'2026-10-29 00:00:00')"
    )


def test_append_only_custody_and_refusing_downgrade(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, database = alembic_cfg
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        _authorization(connection)
        connection.execute(
            "INSERT INTO m10_packaging_heads (user_id,project_name,source_artifact_key,cohort_id,product_surface,"
            "current_selection_id,head_version,updated_at) VALUES ('f','f','k','c','s','sel',1,'2026-10-29 00:00:00')"
        )
        connection.commit()
        for statement in (
            "UPDATE m10_package_selection_authorizations SET grant_sequence=2",
            "DELETE FROM m10_package_selection_authorizations",
            "DELETE FROM m10_packaging_heads",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="M10_IMMUTABLE_PACKAGING_ROW"):
                connection.execute(statement)
        connection.execute("UPDATE m10_packaging_heads SET head_version=2")
        with pytest.raises(sqlite3.IntegrityError, match="ck_m10_packaging_heads_version"):
            connection.execute("UPDATE m10_packaging_heads SET head_version=0")
        connection.commit()
    with pytest.raises(RuntimeError, match="M10_PACKAGING_HISTORY_PRESENT"):
        command.downgrade(cfg, PREDECESSOR)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (REVISION,)
