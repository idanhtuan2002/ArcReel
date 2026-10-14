"""Format projection tables keep scoped restrict keys from plans to profiles, overlays and reports."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command


def test_format_migration_has_scoped_restrict_keys_and_downgrades_alone(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["917c4a0e0001"]
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
        "m8_format_review_packets",
    }
    before = set(inspector.get_table_names())
    command.downgrade(cfg, "915c4a0e0001")
    after = set(sa.inspect(sa.create_engine(f"sqlite:///{db_path}")).get_table_names())
    assert tables <= before - after
    assert "m8_learning_evaluations" in after


def test_format_genesis_previews_are_admitted_only_for_format_slots(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    insert = sa.text(
        "INSERT INTO m8_promotion_previews (user_id, preview_id, project_name, preview_command_id, candidate_id,"
        " candidate_revision, candidate_payload_digest, target_kind, target_ref, expected_target_version,"
        " expected_master_id, expected_master_digest, impact_json, impact_digest, preview_digest,"
        " authorization_scope, issued_at, expires_at, ttl_seconds)"
        " VALUES ('default', :id, 'demo', :id, 'c', 1, 'sha256:a', 'ARTIFACT_SLOT', :ref, :version, NULL, NULL,"
        " '{}', 'sha256:a', 'sha256:a', 'default', '2026-10-14 00:00:00', '2026-10-14 00:10:00', 600)"
    )
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT OR IGNORE INTO users (id, username) VALUES ('default', 'default')"))
        connection.execute(insert, {"id": "p1", "ref": "m8-format:abc:square@1", "version": 0})
    for ref, version in (("m8-slot:x", 0), ("m8-format:abc:square@1", 1)):
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(insert, {"id": f"p-{ref}-{version}", "ref": ref, "version": version})

    with pytest.raises(RuntimeError, match="genesis previews exist"):
        command.downgrade(cfg, "916c4a0e0001")
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM m8_promotion_previews"))
    command.downgrade(cfg, "916c4a0e0001")
    command.upgrade(cfg, "head")
