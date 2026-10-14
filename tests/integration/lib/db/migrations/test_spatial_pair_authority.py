"""A pair decision links exact scoped target, binding and frame authorities."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from alembic import command
from lib.db.models.spatial_pair import SpatialPairHeadModel

TABLES = {"m8_spatial_pair_heads", "m8_spatial_pair_decisions", "m8_spatial_pair_commands"}


def test_pair_revision_scoped_keys_and_round_trip(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["915c4a0e0001"]
    assert script.get_revision("8e8c4a0e0001").down_revision == "8d8c4a0e0001"

    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) >= TABLES
    for table, expected in (
        ("m8_spatial_pair_heads", ["user_id", "project_name", "pair_id"]),
        ("m8_spatial_pair_decisions", ["user_id", "project_name", "pair_id", "pair_version"]),
        ("m8_spatial_pair_commands", ["user_id", "project_name", "principal", "command_id"]),
    ):
        assert inspector.get_pk_constraint(table)["constrained_columns"] == expected
        reflected = {
            column["name"]: (str(column["type"]).upper(), column["nullable"]) for column in inspector.get_columns(table)
        }
        declared = {
            column.name: (str(column.type.compile(dialect=engine.dialect)).upper(), column.nullable)
            for column in SpatialPairHeadModel.metadata.tables[table].columns
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
        ("user_id", "project_name", "pair_id", "current_version"),
        "m8_spatial_pair_decisions",
        ("user_id", "project_name", "pair_id", "pair_version"),
    ) in foreign["m8_spatial_pair_heads"]
    links = foreign["m8_spatial_pair_decisions"]
    for pair_cols, target_table, target_cols in (
        (("binding_id", "binding_version"), "production_binding_versions", ("binding_id", "binding_version")),
        (("master_receipt_id",), "m8_spatial_frame_receipts", ("receipt_id",)),
        (("reverse_receipt_id",), "m8_spatial_frame_receipts", ("receipt_id",)),
    ):
        assert (
            ("user_id", "project_name", *pair_cols),
            target_table,
            ("user_id", "project_name", *target_cols),
        ) in links
    for prefix in ("target", "scene"):
        assert (
            ("user_id", "project_name", f"{prefix}_type", f"{prefix}_id", f"{prefix}_registry_version"),
            "production_target_versions",
            ("user_id", "project_name", "target_type", "target_id", "registry_version"),
        ) in links

    command.downgrade(cfg, "8d8c4a0e0001")
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(cfg, "head")
    assert set(sa.inspect(engine).get_table_names()) >= TABLES


def test_pair_schema_rejects_partial_head_and_duplicate_frames(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.execute(
            sa.text(
                "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                "VALUES ('pair-test', 'pair-test', 'user', 1, '2026-10-06', '2026-10-06')"
            )
        )
        head = sa.text(
            "INSERT INTO m8_spatial_pair_heads "
            "(user_id, project_name, pair_id, current_version, current_decision_digest) "
            "VALUES ('pair-test', 'demo', :pair, :version, :digest)"
        )
        conn.execute(head, {"pair": "m8p:valid", "version": None, "digest": None})
        for pair, version, digest in (
            ("m8p:missing-digest", 1, None),
            ("m8p:missing-version", None, "sha256:opaque"),
            ("m8p:missing-row", 1, "sha256:opaque"),
        ):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(head, {"pair": pair, "version": version, "digest": digest})
        decision = sa.text(
            "INSERT INTO m8_spatial_pair_decisions "
            "(user_id, project_name, pair_id, pair_version, decision_body_json, decision_digest, "
            "command_digest, authorization_digest, binding_id, binding_version, binding_envelope_digest, "
            "binding_core_digest, target_type, target_id, target_registry_version, target_version_digest, "
            "scene_type, scene_id, scene_registry_version, scene_version_digest, master_receipt_id, "
            "reverse_receipt_id, decision, created_at) VALUES "
            "('pair-test', 'demo', 'm8p:valid', 1, '{}', 'sha256:decision', 'sha256:command', "
            "'sha256:auth', 'm8b:binding', 1, 'sha256:envelope', 'sha256:core', 'SHOT', 'shot-1', 1, "
            "'sha256:shot', 'SCENE', 'scene-1', 1, 'sha256:scene', :master, :reverse, :decision, '2026-10-06')"
        )
        for values in (
            {"master": "m8f:a", "reverse": "m8f:a", "decision": "APPROVE"},
            {"master": "m8f:a", "reverse": "m8f:b", "decision": "UNKNOWN"},
        ):
            with pytest.raises(IntegrityError, match="CHECK constraint failed"), conn.begin_nested():
                conn.execute(decision, values)
