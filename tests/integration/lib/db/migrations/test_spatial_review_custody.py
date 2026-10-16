"""Review custody rows retain scoped sessions, deliveries and acknowledgments."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from alembic import command
from lib.db.models.spatial_review import (
    SpatialReviewAcknowledgmentModel,
    SpatialReviewDeliveryModel,
    SpatialReviewSessionModel,
)

TABLES = {
    "m8_spatial_review_sessions",
    "m8_spatial_review_deliveries",
    "m8_spatial_review_acknowledgments",
}


def test_review_custody_revision_and_scoped_child_keys(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["9a9c4a0e0001"]
    assert script.get_revision("901c4a0e0001").down_revision == "8f8c4a0e0001"

    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) >= TABLES
    for model in (SpatialReviewSessionModel, SpatialReviewDeliveryModel, SpatialReviewAcknowledgmentModel):
        reflected = {
            column["name"]: (str(column["type"]).upper(), column["nullable"])
            for column in inspector.get_columns(model.__tablename__)
        }
        declared = {
            column.name: (str(column.type.compile(dialect=engine.dialect)).upper(), column.nullable)
            for column in model.__table__.columns
        }
        assert reflected == declared
    assert inspector.get_pk_constraint("m8_spatial_review_sessions")["constrained_columns"] == [
        "user_id",
        "project_name",
        "session_id",
    ]
    assert inspector.get_pk_constraint("m8_spatial_review_deliveries")["constrained_columns"] == [
        "user_id",
        "project_name",
        "session_id",
        "attempt_id",
    ]
    assert inspector.get_pk_constraint("m8_spatial_review_acknowledgments")["constrained_columns"] == [
        "user_id",
        "project_name",
        "session_id",
        "role",
    ]
    delivery_fks = inspector.get_foreign_keys("m8_spatial_review_deliveries")
    acknowledgment_fks = inspector.get_foreign_keys("m8_spatial_review_acknowledgments")
    assert any(
        fk["referred_table"] == "m8_spatial_review_sessions"
        and fk["constrained_columns"] == ["user_id", "project_name", "session_id"]
        for fk in delivery_fks
    )
    assert any(
        fk["referred_table"] == "m8_spatial_review_deliveries"
        and fk["constrained_columns"] == ["user_id", "project_name", "session_id", "attempt_id", "role", "png_digest"]
        for fk in acknowledgment_fks
    )

    command.downgrade(cfg, "8f8c4a0e0001")
    assert TABLES.isdisjoint(sa.inspect(engine).get_table_names())
    command.upgrade(cfg, "head")
    assert set(sa.inspect(engine).get_table_names()) >= TABLES


def test_review_delivery_cannot_cross_session_scope(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        for user_id in ("u1", "u2"):
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, username, role, is_active, created_at, updated_at) "
                    "VALUES (:id, :id, 'user', 1, '2026-10-11', '2026-10-11')"
                ),
                {"id": user_id},
            )
        conn.execute(
            sa.text(
                "INSERT INTO m8_spatial_review_sessions "
                "(user_id, project_name, session_id, principal, snapshot_body_json, snapshot_digest, "
                "created_at, expires_at) VALUES "
                "('u1', 'demo', :session, 'human:reviewer-1', '{}', 'sha256:opaque', "
                "'2026-10-11T00:00:00Z', '2026-10-11T00:10:00Z')"
            ),
            {"session": "a" * 32},
        )
        delivery = sa.text(
            "INSERT INTO m8_spatial_review_deliveries "
            "(user_id, project_name, session_id, attempt_id, role, png_digest, recorded_at) "
            "VALUES (:user, :project, :session, 'attempt-1', 'MASTER', 'sha256:opaque', '2026-10-11')"
        )
        for user, project in (("u2", "demo"), ("u1", "other")):
            with pytest.raises(IntegrityError), conn.begin_nested():
                conn.execute(delivery, {"user": user, "project": project, "session": "a" * 32})
        conn.execute(delivery, {"user": "u1", "project": "demo", "session": "a" * 32})
        acknowledgment = sa.text(
            "INSERT INTO m8_spatial_review_acknowledgments "
            "(user_id, project_name, session_id, role, attempt_id, principal, png_digest, decoded, recorded_at) "
            "VALUES ('u1', 'demo', :session, 'MASTER', :attempt, 'human:reviewer-1', "
            "'sha256:opaque', 1, '2026-10-11')"
        )
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(acknowledgment, {"session": "b" * 32, "attempt": "attempt-1"})
        conn.execute(acknowledgment, {"session": "a" * 32, "attempt": "attempt-1"})
