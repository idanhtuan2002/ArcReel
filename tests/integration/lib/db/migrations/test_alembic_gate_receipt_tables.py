"""Alembic coverage for the P1 Gate A-D receipt surface: ``gate_greenlight_decisions``,
``gate_publish_approval_decisions``, ``gate_final_cut_receipts``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

_MIGRATION = "*_add_gate_a_d_receipt_tables.py"

EXPECTED_TABLES = {
    "gate_greenlight_decisions",
    "gate_publish_approval_decisions",
    "gate_final_cut_receipts",
}

_INSERT_GREENLIGHT = sa.text(
    "INSERT INTO gate_greenlight_decisions (user_id, project_name, decision_id, source_digest, action, "
    "sequence, authorization_json, created_at) "
    "VALUES ('default', :project_name, :decision_id, :source_digest, :action, :sequence, '{}', "
    "'2026-09-22 00:00:00')"
)

_INSERT_PUBLISH_APPROVAL = sa.text(
    "INSERT INTO gate_publish_approval_decisions (user_id, project_name, decision_id, deliverable_digest, "
    "platform, visibility, action, sequence, authorization_json, created_at) "
    "VALUES ('default', :project_name, :decision_id, :deliverable_digest, :platform, :visibility, :action, "
    ":sequence, '{}', '2026-09-22 00:00:00')"
)

_INSERT_FINAL_CUT_RECEIPT = sa.text(
    "INSERT INTO gate_final_cut_receipts (final_cut_receipt_id, user_id, project_name, artifact_key, "
    "selected_candidate_id, content_fingerprint, approval_record, selected_by, selected_at, sequence) "
    "VALUES (:final_cut_receipt_id, 'default', :project_name, :artifact_key, :selected_candidate_id, "
    "'sha256:' || :selected_candidate_id, :approval_record, :selected_by, '2026-09-22 00:00:00', :sequence)"
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


def test_upgrade_creates_the_gate_receipt_schema_additively(
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


def test_downgrade_removes_exactly_the_gate_receipt_tables(
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


def test_greenlight_decisions_rejects_a_duplicate_sequence(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    with engine.begin() as connection:
        connection.execute(
            _INSERT_GREENLIGHT,
            {
                "project_name": "demo",
                "decision_id": "d-1",
                "source_digest": "sha256:a",
                "action": "GREENLIGHT",
                "sequence": 1,
            },
        )

    try:
        with engine.begin() as connection:
            connection.execute(
                _INSERT_GREENLIGHT,
                {
                    "project_name": "demo",
                    "decision_id": "d-2",
                    "source_digest": "sha256:b",
                    "action": "GREENLIGHT",
                    "sequence": 1,
                },
            )
        raised = False
    except sa.exc.IntegrityError:
        raised = True
    engine.dispose()
    assert raised


def test_greenlight_decisions_rejects_a_non_positive_sequence(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as connection:
            connection.execute(
                _INSERT_GREENLIGHT,
                {
                    "project_name": "demo",
                    "decision_id": "d-1",
                    "source_digest": "sha256:a",
                    "action": "GREENLIGHT",
                    "sequence": 0,
                },
            )
        raised = False
    except sa.exc.IntegrityError:
        raised = True
    engine.dispose()
    assert raised


def test_publish_approval_decision_round_trips(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    with engine.begin() as connection:
        connection.execute(
            _INSERT_PUBLISH_APPROVAL,
            {
                "project_name": "demo",
                "decision_id": "d-1",
                "deliverable_digest": "sha256:c",
                "platform": "youtube",
                "visibility": "unlisted",
                "action": "APPROVE_PUBLISH",
                "sequence": 1,
            },
        )
    with engine.begin() as connection:
        row = connection.execute(
            sa.text("SELECT platform, visibility FROM gate_publish_approval_decisions WHERE decision_id = 'd-1'")
        ).one()
    engine.dispose()
    assert row == ("youtube", "unlisted")


def test_final_cut_receipt_round_trips_and_rejects_a_duplicate_sequence(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    with engine.begin() as connection:
        connection.execute(
            _INSERT_FINAL_CUT_RECEIPT,
            {
                "final_cut_receipt_id": "r-1",
                "project_name": "demo",
                "artifact_key": "videos:1:SH01",
                "selected_candidate_id": "cand-1",
                "approval_record": "APR-SH01",
                "selected_by": "operator-1",
                "sequence": 1,
            },
        )
    with engine.begin() as connection:
        row = connection.execute(
            sa.text("SELECT selected_candidate_id FROM gate_final_cut_receipts WHERE final_cut_receipt_id = 'r-1'")
        ).one()
    assert row == ("cand-1",)

    try:
        with engine.begin() as connection:
            connection.execute(
                _INSERT_FINAL_CUT_RECEIPT,
                {
                    "final_cut_receipt_id": "r-2",
                    "project_name": "demo",
                    "artifact_key": "videos:1:SH01",
                    "selected_candidate_id": "cand-2",
                    "approval_record": "APR-SH01-2",
                    "selected_by": "operator-1",
                    "sequence": 1,
                },
            )
        raised = False
    except sa.exc.IntegrityError:
        raised = True
    engine.dispose()
    assert raised
