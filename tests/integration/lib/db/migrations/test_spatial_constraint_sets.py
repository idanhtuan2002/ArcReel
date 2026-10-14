"""Scoped immutable spatial constraint set schema."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

TABLE = "m8_spatial_constraint_sets"


def test_constraint_set_revision_keys_and_downgrade(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["918c4a0e0001"]
    assert script.get_revision("912c4a0e0001").down_revision == "911c4a0e0001"

    command.upgrade(cfg, "head")
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{db_path}"))
    assert inspector.get_pk_constraint(TABLE)["constrained_columns"] == ["user_id", "project_name", "set_id"]
    foreign = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            (fk.get("options") or {}).get("ondelete"),
        )
        for fk in inspector.get_foreign_keys(TABLE)
    }
    assert {
        (
            ("user_id", "project_name", "binding_id"),
            "production_binding_heads",
            ("user_id", "project_name", "binding_id"),
            "RESTRICT",
        ),
        (
            ("user_id", "project_name", "master_receipt_id"),
            "m8_spatial_frame_receipts",
            ("user_id", "project_name", "receipt_id"),
            "RESTRICT",
        ),
        (
            ("user_id", "project_name", "reverse_receipt_id"),
            "m8_spatial_frame_receipts",
            ("user_id", "project_name", "receipt_id"),
            "RESTRICT",
        ),
    } <= foreign
    assert {"ck_m8_spatial_constraint_sets_two_views", "ck_m8_spatial_constraint_sets_id_digest"} <= {
        item["name"] for item in inspector.get_check_constraints(TABLE)
    }

    command.downgrade(cfg, "911c4a0e0001")
    assert TABLE not in sa.inspect(sa.create_engine(f"sqlite:///{db_path}")).get_table_names()
