"""Spatial execution evidence keeps exact scoped links to its attempt, revision and two frames."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

TABLE = "m8_spatial_execution_evidence"


def test_evidence_migration_has_scoped_restrict_keys_and_downgrades_alone(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["918c4a0e0001"]
    assert script.get_revision("8c8c4a0e0001").down_revision == "8b8c4a0e0001"

    command.upgrade(cfg, "head")
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{db_path}"))
    assert inspector.get_pk_constraint(TABLE)["constrained_columns"] == ["user_id", "project_name", "execution_id"]
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
            ("user_id", "project_name", "execution_id"),
            "execution_attempts",
            ("user_id", "project_name", "execution_id"),
            "RESTRICT",
        ),
        (
            ("user_id", "project_name", "candidate_id", "revision"),
            "m8_candidate_revisions",
            ("user_id", "project_name", "candidate_id", "revision"),
            "RESTRICT",
        ),
        (
            ("user_id", "project_name", "master_frame_receipt_id"),
            "m8_spatial_frame_receipts",
            ("user_id", "project_name", "receipt_id"),
            "RESTRICT",
        ),
        (
            ("user_id", "project_name", "reverse_frame_receipt_id"),
            "m8_spatial_frame_receipts",
            ("user_id", "project_name", "receipt_id"),
            "RESTRICT",
        ),
    } <= foreign
    assert {
        "uq_m8_spatial_execution_evidence_revision",
        "uq_m8_spatial_execution_evidence_command",
        "ck_m8_spatial_execution_evidence_two_views",
    } <= {item["name"] for item in inspector.get_unique_constraints(TABLE) + inspector.get_check_constraints(TABLE)}

    before = set(inspector.get_table_names())
    command.downgrade(cfg, "8b8c4a0e0001")
    after = set(sa.inspect(sa.create_engine(f"sqlite:///{db_path}")).get_table_names())
    assert TABLE in before - after
    assert "m8_spatial_frame_receipts" in after
