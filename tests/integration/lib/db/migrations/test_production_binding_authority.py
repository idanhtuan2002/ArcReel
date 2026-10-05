"""The first LOCATION binding tables retain exact scoped authority links."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from alembic import command
from lib.db.models.production_binding import ProductionBindingHeadModel

TABLES = {"production_binding_heads", "production_binding_versions", "production_binding_commands"}


def test_binding_authority_revision_and_scoped_keys(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["8d8c4a0e0001"]
    assert script.get_revision("8d8c4a0e0001").down_revision == "8c8c4a0e0001"

    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) >= TABLES
    assert inspector.get_pk_constraint("production_binding_heads")["constrained_columns"] == [
        "user_id",
        "project_name",
        "binding_id",
    ]
    assert inspector.get_pk_constraint("production_binding_versions")["constrained_columns"] == [
        "user_id",
        "project_name",
        "binding_id",
        "binding_version",
    ]
    assert inspector.get_pk_constraint("production_binding_commands")["constrained_columns"] == [
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
            for column in ProductionBindingHeadModel.metadata.tables[table].columns
        }
        assert reflected == declared, table

    foreign = {
        table: {
            (tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
            for fk in inspector.get_foreign_keys(table)
        }
        for table in TABLES
    }
    assert (
        ("user_id", "project_name", "binding_id", "current_version"),
        "production_binding_versions",
        ("user_id", "project_name", "binding_id", "binding_version"),
    ) in foreign["production_binding_heads"]
    links = foreign["production_binding_versions"]
    assert (
        ("user_id", "project_name", "binding_id"),
        "production_binding_heads",
        ("user_id", "project_name", "binding_id"),
    ) in links
    for prefix in ("target", "scene"):
        assert (
            ("user_id", "project_name", f"{prefix}_type", f"{prefix}_id", f"{prefix}_registry_version"),
            "production_target_versions",
            ("user_id", "project_name", "target_type", "target_id", "registry_version"),
        ) in links
    for suffix in ("a", "b"):
        assert (
            ("user_id", "project_name", f"receipt_{suffix}_id"),
            "m8_spatial_frame_receipts",
            ("user_id", "project_name", "receipt_id"),
        ) in links

    command.downgrade(cfg, "8c8c4a0e0001")
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(cfg, "head")
    assert set(sa.inspect(engine).get_table_names()) >= TABLES


def test_binding_authority_rejects_partial_head_and_duplicate_frame_links(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.execute(
            sa.text(
                "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                "VALUES ('binding-test', 'binding-test', 'user', 1, '2026-10-05', '2026-10-05')"
            )
        )
        head = sa.text(
            "INSERT INTO production_binding_heads "
            "(user_id, project_name, binding_id, current_version, current_envelope_digest) "
            "VALUES ('binding-test', 'demo', :binding, :version, :digest)"
        )
        conn.execute(head, {"binding": "m8b:valid", "version": None, "digest": None})
        for binding, version, digest in (
            ("m8b:missing-digest", 1, None),
            ("m8b:missing-version", None, "sha256:opaque"),
            ("m8b:missing-row", 1, "sha256:opaque"),
        ):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(head, {"binding": binding, "version": version, "digest": digest})

        version = sa.text(
            "INSERT INTO production_binding_versions "
            "(user_id, project_name, binding_id, binding_version, binding_body_json, binding_body_digest, "
            "envelope_json, envelope_digest, target_type, target_id, target_registry_version, "
            "target_version_digest, scene_type, scene_id, scene_registry_version, scene_version_digest, "
            "receipt_a_id, receipt_b_id, created_at) VALUES "
            "('binding-test', 'demo', 'm8b:valid', 1, '{}', 'sha256:body', '{}', 'sha256:envelope', "
            ":target_type, 'shot-1', 1, 'sha256:shot', 'SCENE', 'scene-1', 1, 'sha256:scene', "
            ":receipt_a, :receipt_b, '2026-10-05')"
        )
        for values in (
            {"target_type": "SHOT", "receipt_a": "m8f:a", "receipt_b": "m8f:a"},
            {"target_type": "SCENE", "receipt_a": "m8f:a", "receipt_b": "m8f:b"},
        ):
            with pytest.raises(IntegrityError, match="CHECK constraint failed"), conn.begin_nested():
                conn.execute(version, values)
