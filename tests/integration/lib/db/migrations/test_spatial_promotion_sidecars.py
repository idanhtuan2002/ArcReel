"""Typed spatial promotion sidecars: keys, RESTRICT links and a clean downgrade."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command


def _foreign(inspector: sa.Inspector, table: str) -> set[tuple[tuple[str, ...], str, str | None]]:
    return {
        (tuple(fk["constrained_columns"]), fk["referred_table"], (fk.get("options") or {}).get("ondelete"))
        for fk in inspector.get_foreign_keys(table)
    }


def test_sidecar_tables_link_their_base_rows_and_authorities(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["9b9c4a0e0001"]
    assert script.get_revision("913c4a0e0001").down_revision == "912c4a0e0001"

    command.upgrade(cfg, "head")
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{db_path}"))
    assert {
        (("user_id", "project_name", "preview_id"), "m8_promotion_previews", "RESTRICT"),
        (("user_id", "project_name", "binding_id"), "production_binding_heads", "RESTRICT"),
    } <= _foreign(inspector, "m8_spatial_preview_bindings")
    assert {
        (("receipt_id",), "m8_promotion_receipts", "RESTRICT"),
        (
            ("user_id", "project_name", "binding_id", "binding_version"),
            "production_binding_versions",
            "RESTRICT",
        ),
        (("user_id", "project_name", "set_id"), "m8_spatial_constraint_sets", "RESTRICT"),
    } <= _foreign(inspector, "m8_spatial_promotion_results")

    command.downgrade(cfg, "912c4a0e0001")
    remaining = set(sa.inspect(sa.create_engine(f"sqlite:///{db_path}")).get_table_names())
    assert {"m8_spatial_preview_bindings", "m8_spatial_promotion_results"}.isdisjoint(remaining)
    assert "m8_spatial_constraint_sets" in remaining
