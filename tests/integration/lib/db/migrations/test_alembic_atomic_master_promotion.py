"""Alembic coverage for M7-B atomic master promotion: ``candidate_objects``,
``master_authorities``, ``master_head_versions``, ``promotion_receipts``,
``backup_sets`` and ``backup_set_media_refs``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

_MIGRATION = "*_add_atomic_master_promotion.py"

EXPECTED_TABLES = {
    "candidate_objects",
    "master_authorities",
    "master_head_versions",
    "promotion_receipts",
    "backup_sets",
    "backup_set_media_refs",
}

_INSERT_CANDIDATE = sa.text(
    "INSERT INTO candidate_objects (user_id, project_name, candidate_id, artifact_key, object_ref, "
    "byte_size, content_digest, media_probe_digest, created_at) "
    "VALUES ('default', :project_name, :candidate_id, :artifact_key, :object_ref, "
    ":byte_size, 'sha256:' || :candidate_id, 'sha256:' || :candidate_id, '2026-09-20 00:00:00')"
)

_INSERT_MASTER_AUTHORITY = sa.text(
    "INSERT INTO master_authorities (user_id, project_name, artifact_key, current_version) "
    "VALUES ('default', :project_name, :artifact_key, :current_version)"
)

_INSERT_MASTER_HEAD_VERSION = sa.text(
    "INSERT INTO master_head_versions (master_head_version_id, user_id, project_name, artifact_key, "
    "master_version, candidate_id, object_ref, content_digest, approval_record, promoted_at) "
    "VALUES (:master_head_version_id, 'default', :project_name, :artifact_key, :master_version, "
    ":candidate_id, :object_ref, 'sha256:' || :candidate_id, :approval_record, '2026-09-20 00:00:00')"
)

_INSERT_PROMOTION_RECEIPT = sa.text(
    "INSERT INTO promotion_receipts (user_id, project_name, artifact_key, command_id, command_digest, "
    "candidate_id, master_version, approval_record, created_at) "
    "VALUES ('default', :project_name, :artifact_key, :command_id, 'sha256:' || :command_id, "
    ":candidate_id, :master_version, :approval_record, '2026-09-20 00:00:00')"
)

_INSERT_BACKUP_SET = sa.text(
    "INSERT INTO backup_sets (user_id, project_name, backup_set_id, state, created_at, updated_at) "
    "VALUES ('default', :project_name, :backup_set_id, :state, '2026-09-20 00:00:00', '2026-09-20 00:00:00')"
)

_INSERT_BACKUP_SET_MEDIA_REF = sa.text(
    "INSERT INTO backup_set_media_refs (backup_set_id, candidate_id) VALUES (:backup_set_id, :candidate_id)"
)


def _engine(db_path: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{db_path}")


def _upgrade_to_revision(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> sa.Engine:
    revision, _parent = migration_revisions(_MIGRATION)
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, revision)
    return _engine(db_path)


def test_upgrade_creates_the_atomic_promotion_schema_additively(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    revision, parent = migration_revisions(_MIGRATION)
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, parent)
    engine = _engine(db_path)
    with engine.begin() as connection:
        before_tables = set(sa.inspect(connection).get_table_names())
    engine.dispose()
    assert not (before_tables & EXPECTED_TABLES)

    command.upgrade(cfg, revision)
    engine = _engine(db_path)
    with engine.begin() as connection:
        after_tables = set(sa.inspect(connection).get_table_names())
    engine.dispose()
    assert after_tables >= EXPECTED_TABLES


def test_downgrade_removes_exactly_the_atomic_promotion_tables(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    revision, parent = migration_revisions(_MIGRATION)
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, revision)
    engine = _engine(db_path)
    with engine.begin() as connection:
        at_head = set(sa.inspect(connection).get_table_names())
    engine.dispose()
    assert at_head >= EXPECTED_TABLES

    command.downgrade(cfg, parent)
    engine = _engine(db_path)
    with engine.begin() as connection:
        after_downgrade = set(sa.inspect(connection).get_table_names())
    engine.dispose()
    assert not (after_downgrade & EXPECTED_TABLES)


def test_master_head_versions_rejects_a_concurrent_same_version_write(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    # The CAS boundary for promotion: two rows claiming the same next version
    # number for the same artifact are structurally impossible, independent of
    # any application-level lock.
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    with engine.begin() as connection:
        connection.execute(
            _INSERT_CANDIDATE,
            {
                "project_name": "demo",
                "candidate_id": "cand-1",
                "artifact_key": "videos/E1S01",
                "object_ref": "/data/demo/videos/cand-1.mp4",
                "byte_size": 1024,
            },
        )
        connection.execute(
            _INSERT_CANDIDATE,
            {
                "project_name": "demo",
                "candidate_id": "cand-2",
                "artifact_key": "videos/E1S01",
                "object_ref": "/data/demo/videos/cand-2.mp4",
                "byte_size": 2048,
            },
        )
        connection.execute(
            _INSERT_MASTER_HEAD_VERSION,
            {
                "master_head_version_id": "mhv-1",
                "project_name": "demo",
                "artifact_key": "videos/E1S01",
                "master_version": 1,
                "candidate_id": "cand-1",
                "object_ref": "/data/demo/videos/cand-1.mp4",
                "approval_record": "approval-1",
            },
        )

    try:
        with engine.begin() as connection:
            connection.execute(
                _INSERT_MASTER_HEAD_VERSION,
                {
                    "master_head_version_id": "mhv-2",
                    "project_name": "demo",
                    "artifact_key": "videos/E1S01",
                    "master_version": 1,
                    "candidate_id": "cand-2",
                    "object_ref": "/data/demo/videos/cand-2.mp4",
                    "approval_record": "approval-2",
                },
            )
        raised = False
    except sa.exc.IntegrityError:
        raised = True
    engine.dispose()
    assert raised


def test_master_head_versions_restricts_deleting_a_referenced_candidate(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    with engine.begin() as connection:
        connection.execute(
            _INSERT_CANDIDATE,
            {
                "project_name": "demo",
                "candidate_id": "cand-1",
                "artifact_key": "videos/E1S01",
                "object_ref": "/data/demo/videos/cand-1.mp4",
                "byte_size": 1024,
            },
        )
        connection.execute(
            _INSERT_MASTER_HEAD_VERSION,
            {
                "master_head_version_id": "mhv-1",
                "project_name": "demo",
                "artifact_key": "videos/E1S01",
                "master_version": 1,
                "candidate_id": "cand-1",
                "object_ref": "/data/demo/videos/cand-1.mp4",
                "approval_record": "approval-1",
            },
        )
        connection.execute(sa.text("PRAGMA foreign_keys=ON"))

    try:
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=ON"))
            connection.execute(sa.text("DELETE FROM candidate_objects WHERE candidate_id = 'cand-1'"))
        raised = False
    except sa.exc.IntegrityError:
        raised = True
    engine.dispose()
    assert raised


def test_backup_sets_rejects_an_unknown_state(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as connection:
            connection.execute(
                _INSERT_BACKUP_SET,
                {"project_name": "demo", "backup_set_id": "bset-1", "state": "BOGUS"},
            )
        raised = False
    except sa.exc.IntegrityError:
        raised = True
    engine.dispose()
    assert raised


def test_promotion_receipt_round_trips_and_references_its_candidate(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    with engine.begin() as connection:
        connection.execute(
            _INSERT_CANDIDATE,
            {
                "project_name": "demo",
                "candidate_id": "cand-1",
                "artifact_key": "videos/E1S01",
                "object_ref": "/data/demo/videos/cand-1.mp4",
                "byte_size": 1024,
            },
        )
        connection.execute(
            _INSERT_MASTER_AUTHORITY,
            {"project_name": "demo", "artifact_key": "videos/E1S01", "current_version": 1},
        )
        connection.execute(
            _INSERT_PROMOTION_RECEIPT,
            {
                "project_name": "demo",
                "artifact_key": "videos/E1S01",
                "command_id": "cmd-1",
                "candidate_id": "cand-1",
                "master_version": 1,
                "approval_record": "approval-1",
            },
        )
        connection.execute(
            _INSERT_BACKUP_SET,
            {"project_name": "demo", "backup_set_id": "bset-1", "state": "PREPARING"},
        )
        connection.execute(
            _INSERT_BACKUP_SET_MEDIA_REF,
            {"backup_set_id": "bset-1", "candidate_id": "cand-1"},
        )

    with engine.begin() as connection:
        receipt = connection.execute(
            sa.text("SELECT candidate_id, master_version FROM promotion_receipts WHERE command_id = 'cmd-1'")
        ).one()
        backup_ref = connection.execute(
            sa.text("SELECT candidate_id FROM backup_set_media_refs WHERE backup_set_id = 'bset-1'")
        ).one()
    engine.dispose()
    assert receipt == ("cand-1", 1)
    assert backup_ref == ("cand-1",)
