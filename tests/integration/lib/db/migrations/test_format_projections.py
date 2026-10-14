"""Format projection tables keep scoped restrict keys from plans to profiles, overlays and reports."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command


def test_format_migration_has_scoped_restrict_keys_and_downgrades_alone(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["916c4a0e0001"]
    assert script.get_revision("916c4a0e0001").down_revision == "915c4a0e0001"

    command.upgrade(cfg, "head")
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{db_path}"))
    plans = {
        (tuple(fk["constrained_columns"]), fk["referred_table"], (fk.get("options") or {}).get("ondelete"))
        for fk in inspector.get_foreign_keys("m8_format_plans")
    }
    assert (("user_id", "project_name", "profile_ref"), "m8_format_profiles", "RESTRICT") in plans
    assert (("user_id", "project_name", "constraint_ref"), "m8_overlay_constraint_sets", "RESTRICT") in plans
    for table in ("m8_format_technical_reports", "m8_format_semantic_reports"):
        keys = {(tuple(fk["constrained_columns"]), fk["referred_table"]) for fk in inspector.get_foreign_keys(table)}
        assert (("user_id", "project_name", "plan_id"), "m8_format_plans") in keys

    tables = {
        "m8_format_profiles",
        "m8_overlay_constraint_sets",
        "m8_format_plans",
        "m8_format_technical_reports",
        "m8_format_semantic_reports",
        "m8_format_renders",
    }
    before = set(inspector.get_table_names())
    command.downgrade(cfg, "915c4a0e0001")
    after = set(sa.inspect(sa.create_engine(f"sqlite:///{db_path}")).get_table_names())
    assert tables <= before - after
    assert "m8_learning_evaluations" in after
