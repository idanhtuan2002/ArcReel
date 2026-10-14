"""Scoped target head, immutable version and command receipt schema."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from alembic import command
from lib.db.models.production_target import ProductionTargetHeadModel

TABLES = {"production_target_heads", "production_target_versions", "production_target_commands"}


def test_target_registry_revision_and_scoped_constraints(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["916c4a0e0001"]
    assert script.get_revision("8c9c4a0e0001").down_revision == "8c8c4a0e0001"

    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) >= TABLES
    assert inspector.get_pk_constraint("production_target_heads")["constrained_columns"] == [
        "user_id",
        "project_name",
        "target_type",
        "target_id",
    ]
    assert inspector.get_pk_constraint("production_target_versions")["constrained_columns"] == [
        "user_id",
        "project_name",
        "target_type",
        "target_id",
        "registry_version",
    ]
    assert inspector.get_pk_constraint("production_target_commands")["constrained_columns"] == [
        "user_id",
        "project_name",
        "principal",
        "command_id",
    ]
    for table in TABLES:
        reflected = {
            column["name"]: (str(column["type"]).upper(), column["nullable"]) for column in inspector.get_columns(table)
        }
        declared = {
            column.name: (str(column.type.compile(dialect=engine.dialect)).upper(), column.nullable)
            for column in ProductionTargetHeadModel.metadata.tables[table].columns
        }
        assert reflected == declared, table

    def foreign(table: str) -> set[tuple[tuple[str, ...], str, tuple[str, ...], str]]:
        return {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                str((fk.get("options") or {}).get("ondelete", "NO ACTION")).upper(),
            )
            for fk in inspector.get_foreign_keys(table)
        }

    assert (
        ("user_id", "project_name", "target_type", "target_id", "current_version"),
        "production_target_versions",
        ("user_id", "project_name", "target_type", "target_id", "registry_version"),
        "RESTRICT",
    ) in foreign("production_target_heads")
    version_keys = foreign("production_target_versions")
    assert (
        ("user_id", "project_name", "target_type", "target_id"),
        "production_target_heads",
        ("user_id", "project_name", "target_type", "target_id"),
        "RESTRICT",
    ) in version_keys
    assert (
        ("user_id", "project_name", "scene_target_type", "scene_target_id", "scene_registry_version"),
        "production_target_versions",
        ("user_id", "project_name", "target_type", "target_id", "registry_version"),
        "RESTRICT",
    ) in version_keys
    for table in TABLES:
        assert (("user_id",), "users", ("id",), "RESTRICT") in foreign(table)
    command.downgrade(cfg, "8c8c4a0e0001")
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())


def test_target_registry_rejects_invalid_head_and_scene_links(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        for user_id in ("u1", "u2"):
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                    "VALUES (:id, :id, 'user', 1, '2026-10-05', '2026-10-05')"
                ),
                {"id": user_id},
            )
        head = sa.text(
            "INSERT INTO production_target_heads "
            "(user_id, project_name, target_type, target_id, current_version, current_version_digest) "
            "VALUES (:user, :project, :type, :id, :version, :digest)"
        )
        version = sa.text(
            "INSERT INTO production_target_versions "
            "(user_id, project_name, target_type, target_id, registry_version, target_body_json, "
            "target_body_digest, admitted_screenplay_ref_json, take_derivation_version, version_digest, "
            "scene_target_type, scene_target_id, scene_registry_version, scene_version_digest, created_at) "
            "VALUES (:user, :project, :type, :id, :version, '{}', 'sha256:body', '{}', 'take-v1', "
            "'sha256:version', :scene_type, :scene_id, :scene_version, :scene_digest, '2026-10-05')"
        )
        scene = {"user": "u1", "project": "p1", "type": "SCENE", "id": "scene-1"}
        shot = {"user": "u1", "project": "p1", "type": "SHOT", "id": "shot-1"}
        conn.execute(head, scene | {"version": None, "digest": None})
        conn.execute(
            version,
            scene | {"version": 1, "scene_type": None, "scene_id": None, "scene_version": None, "scene_digest": None},
        )
        conn.execute(
            sa.text(
                "UPDATE production_target_heads SET current_version=1, "
                "current_version_digest='sha256:version' WHERE user_id='u1' AND project_name='p1' "
                "AND target_type='SCENE' AND target_id='scene-1'"
            )
        )
        conn.execute(head, shot | {"version": None, "digest": None})
        conn.execute(
            version,
            shot
            | {
                "version": 1,
                "scene_type": "SCENE",
                "scene_id": "scene-1",
                "scene_version": 1,
                "scene_digest": "sha256:version",
            },
        )
        conn.execute(
            sa.text(
                "UPDATE production_target_heads SET current_version=1, "
                "current_version_digest='sha256:version' WHERE user_id='u1' AND project_name='p1' "
                "AND target_type='SHOT' AND target_id='shot-1'"
            )
        )

        invalid_heads = [
            scene | {"id": "missing-version", "version": 1, "digest": "sha256:x"},
            scene | {"user": "u2", "version": 1, "digest": "sha256:version"},
            scene | {"project": "p2", "version": 1, "digest": "sha256:version"},
            scene | {"id": "half-head", "version": 1, "digest": None},
        ]
        for invalid in invalid_heads:
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(head, invalid)
        invalid_versions = [
            shot
            | {
                "id": "shot-foreign",
                "version": 1,
                "scene_type": "SCENE",
                "scene_id": "scene-1",
                "scene_version": 1,
                "scene_digest": "sha256:version",
                "user": "u2",
            },
            shot
            | {
                "id": "shot-foreign-project",
                "version": 1,
                "scene_type": "SCENE",
                "scene_id": "scene-1",
                "scene_version": 1,
                "scene_digest": "sha256:version",
                "project": "p2",
            },
            shot
            | {
                "id": "shot-partial",
                "version": 1,
                "scene_type": "SCENE",
                "scene_id": "scene-1",
                "scene_version": None,
                "scene_digest": "sha256:version",
            },
            shot
            | {
                "id": "shot-wrong-type",
                "version": 1,
                "scene_type": "SHOT",
                "scene_id": "shot-1",
                "scene_version": 1,
                "scene_digest": "sha256:version",
            },
            scene
            | {
                "id": "scene-dependent",
                "version": 1,
                "scene_type": "SCENE",
                "scene_id": "scene-1",
                "scene_version": 1,
                "scene_digest": "sha256:version",
            },
        ]
        for invalid in invalid_versions:
            conn.execute(
                head,
                {key: invalid[key] for key in ("user", "project", "type", "id")} | {"version": None, "digest": None},
            )
            try:
                with conn.begin_nested():
                    conn.execute(version, invalid)
            except IntegrityError:
                pass
            else:
                pytest.fail(f"accepted invalid target version {invalid['id']}")
