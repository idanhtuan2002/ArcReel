"""V2 pair custody keeps scoped references to a decision and review session."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from alembic import command
from lib.db.models.spatial_pair import SpatialPairV2CustodyModel


def test_v2_custody_migration_and_scoped_foreign_keys(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["911c4a0e0001"]
    assert script.get_revision("911c4a0e0001").down_revision == "901c4a0e0001"

    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    table = "m8_spatial_pair_v2_custody"
    assert table in inspector.get_table_names()
    reflected = {
        column["name"]: (str(column["type"]).upper(), column["nullable"]) for column in inspector.get_columns(table)
    }
    declared = {
        column.name: (str(column.type.compile(dialect=engine.dialect)).upper(), column.nullable)
        for column in SpatialPairV2CustodyModel.__table__.columns
    }
    assert reflected == declared
    assert inspector.get_pk_constraint(table)["constrained_columns"] == [
        "user_id",
        "project_name",
        "pair_id",
        "pair_version",
    ]
    fks = inspector.get_foreign_keys(table)
    assert any(
        fk["referred_table"] == "m8_spatial_pair_decisions"
        and fk["constrained_columns"] == ["user_id", "project_name", "pair_id", "pair_version"]
        for fk in fks
    )
    assert any(
        fk["referred_table"] == "m8_spatial_review_sessions"
        and fk["constrained_columns"] == ["user_id", "project_name", "review_session_id"]
        for fk in fks
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.execute(
            sa.text(
                "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                "VALUES ('review-v2-test', 'review-v2-test', 'user', 1, '2026-10-11', '2026-10-11')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO m8_spatial_review_sessions "
                "(user_id, project_name, session_id, principal, snapshot_body_json, snapshot_digest, "
                "created_at, expires_at) VALUES "
                "('review-v2-test', 'demo', :session, 'reviewer', '{}', 'sha256:opaque', "
                "'2026-10-11T00:00:00Z', '2026-10-11T00:10:00Z')"
            ),
            {"session": "a" * 32},
        )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                sa.text(
                    "INSERT INTO m8_spatial_pair_v2_custody "
                    "(user_id, project_name, pair_id, pair_version, review_session_id, "
                    "review_evidence_digest, decision_digest) VALUES "
                    "('review-v2-test', 'demo', 'm8p:missing', 1, :session, 'sha256:opaque', 'sha256:opaque')"
                ),
                {"session": "a" * 32},
            )

    command.downgrade(cfg, "901c4a0e0001")
    assert table not in sa.inspect(engine).get_table_names()
    command.upgrade(cfg, "head")
    assert table in sa.inspect(engine).get_table_names()
