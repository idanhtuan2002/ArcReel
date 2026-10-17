"""Spatial frame receipt schema retains exact scoped candidate and parent references."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from alembic import command


def test_frame_receipt_migration_has_scoped_restrict_keys(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["9b9c4a0e0001"]
    assert script.get_revision("8b8c4a0e0001").down_revision == "8a8c4a0e0001"

    command.upgrade(cfg, "head")
    inspector = sa.inspect(sa.create_engine(f"sqlite:///{db_path}"))
    table = "m8_spatial_frame_receipts"
    assert table in inspector.get_table_names()
    assert inspector.get_pk_constraint(table)["constrained_columns"] == ["user_id", "project_name", "receipt_id"]
    foreign = {
        (
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            (fk.get("options") or {}).get("ondelete"),
        )
        for fk in inspector.get_foreign_keys(table)
    }
    assert (
        ("user_id", "project_name", "frame_candidate_id"),
        "candidate_objects",
        ("user_id", "project_name", "candidate_id"),
        "RESTRICT",
    ) in foreign
    assert (
        ("user_id", "project_name", "parent_artifact_key", "parent_master_version"),
        "master_head_versions",
        ("user_id", "project_name", "artifact_key", "master_version"),
        "RESTRICT",
    ) in foreign
    assert {"uq_m8_spatial_frame_receipts_command", "ck_m8_spatial_frame_receipts_id_match"} <= {
        item["name"] for item in inspector.get_unique_constraints(table) + inspector.get_check_constraints(table)
    }

    command.downgrade(cfg, "8a8c4a0e0001")
    assert table not in sa.inspect(sa.create_engine(f"sqlite:///{db_path}")).get_table_names()


def test_frame_receipt_rejects_foreign_scope_candidate_and_parent(alembic_cfg: tuple[Config, Path]) -> None:
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        for user_id in ("u1", "u2"):
            conn.execute(
                sa.text(
                    "INSERT INTO users (id, username, role, is_active, created_at, updated_at) VALUES (:id, :id, 'user', 1, '2026-10-04', '2026-10-04')"
                ),
                {"id": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO candidate_objects (candidate_id, user_id, project_name, artifact_key, object_ref, byte_size, content_digest, media_probe_digest, created_at) VALUES (:candidate, :user, 'demo', 'video:1', 'objects/video.mp4', 1, 'sha256:x', 'sha256:y', '2026-10-04')"
                ),
                {"candidate": f"candidate-{user_id}", "user": user_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO master_head_versions (master_head_version_id, user_id, project_name, artifact_key, master_version, candidate_id, object_ref, content_digest, approval_record, promoted_at) VALUES (:version_id, :user, 'demo', :artifact, 1, :candidate, 'objects/video.mp4', 'sha256:x', 'approval', '2026-10-04')"
                ),
                {
                    "version_id": f"master-{user_id}",
                    "user": user_id,
                    "candidate": f"candidate-{user_id}",
                    "artifact": "video:1" if user_id == "u1" else "video:other",
                },
            )
        insert = sa.text(
            "INSERT INTO m8_spatial_frame_receipts (user_id, project_name, receipt_id, frame_candidate_id, parent_artifact_key, parent_master_version, parent_candidate_id, command_id, command_digest, frame_byte_size, frame_probe_digest, receipt_body_json, receipt_digest, created_at) VALUES ('u1', 'demo', :candidate, :candidate, :artifact, 1, 'candidate-u1', :command, 'sha256:x', 1, 'sha256:y', '{}', 'sha256:z', '2026-10-04')"
        )
        with pytest.raises(IntegrityError):
            conn.execute(insert, {"candidate": "candidate-u2", "artifact": "video:1", "command": "cross-candidate"})
        with pytest.raises(IntegrityError):
            conn.execute(insert, {"candidate": "candidate-u1", "artifact": "video:other", "command": "cross-parent"})
        conn.execute(insert, {"candidate": "candidate-u1", "artifact": "video:1", "command": "valid"})
