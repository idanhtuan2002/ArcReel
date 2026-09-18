"""Alembic coverage for the execution-identity persistence boundary:
``execution_attempts``, ``provider_observations``,
``attempt_integrity_incidents``, ``operator_resolution_receipts``,
``command_receipts`` and ``project_events``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command

_MIGRATION = "*_add_execution_attempts.py"

EXPECTED_TABLES = {
    "execution_attempts",
    "provider_observations",
    "attempt_integrity_incidents",
    "operator_resolution_receipts",
    "command_receipts",
    "project_events",
}

_INSERT_ATTEMPT = sa.text(
    "INSERT INTO execution_attempts (user_id, project_name, execution_id, task_id, attempt_no, "
    "request_digest, route_json, client_token, provider_job_id, state, state_version, "
    "created_at, updated_at, terminal_at) "
    "VALUES ('default', :project_name, :execution_id, :task_id, :attempt_no, 'sha256:' || :execution_id, "
    "'{}', :client_token, :provider_job_id, :state, 1, "
    "'2026-09-16 00:00:00', '2026-09-16 00:00:00', :terminal_at)"
)

_INSERT_OBSERVATION = sa.text(
    "INSERT INTO provider_observations (user_id, project_name, execution_id, received_seq, "
    "observation_id, kind, observed_at, evidence_digest, received_at) "
    "VALUES ('default', :project_name, :execution_id, :received_seq, :observation_id, :kind, "
    "'2026-09-16 00:00:00', 'sha256:' || :observation_id, '2026-09-16 00:00:00')"
)

_INSERT_COMMAND_RECEIPT = sa.text(
    "INSERT INTO command_receipts (user_id, project_name, actor_scope, command_id, "
    "command_digest, task_id, result_digest, created_at) "
    "VALUES ('default', :project_name, :actor_scope, :command_id, "
    "'sha256:' || :command_id, :task_id, 'sha256:' || :command_id, '2026-09-16 00:00:00')"
)

_INSERT_PROJECT_EVENT = sa.text(
    "INSERT INTO project_events (user_id, project_name, event_type, public_payload_json, "
    "payload_schema_version, dedupe_key) "
    "VALUES ('default', :project_name, 'ATTEMPT_TRANSITIONED', '{}', 1, :dedupe_key)"
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


def test_upgrade_creates_the_execution_identity_schema_additively(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    revision, parent = migration_revisions(_MIGRATION)
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, parent)
    engine = _engine(db_path)
    try:
        with engine.begin() as connection:
            assert EXPECTED_TABLES.isdisjoint(sa.inspect(connection).get_table_names())

        command.upgrade(cfg, revision)

        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            assert set(inspector.get_table_names()) >= EXPECTED_TABLES

            pk = inspector.get_pk_constraint("execution_attempts")
            assert set(pk["constrained_columns"]) == {"execution_id"}

            observation_pk = inspector.get_pk_constraint("provider_observations")
            assert set(observation_pk["constrained_columns"]) == {"execution_id", "received_seq"}

            receipt_pk = inspector.get_pk_constraint("command_receipts")
            assert set(receipt_pk["constrained_columns"]) == {"user_id", "project_name", "actor_scope", "command_id"}

            unique = {tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints("execution_attempts")}
            assert tuple(sorted(("user_id", "project_name", "task_id", "attempt_no"))) in unique

            api_call_columns = {column["name"]: column for column in inspector.get_columns("api_calls")}
            assert api_call_columns["execution_id"]["nullable"] is True
            api_call_indexes = {index["name"]: index for index in inspector.get_indexes("api_calls")}
            assert api_call_indexes["uq_api_calls_execution_id"]["unique"] == 1
            assert api_call_indexes["uq_api_calls_execution_id"]["column_names"] == ["execution_id"]
            api_call_fks = {foreign_key["name"]: foreign_key for foreign_key in inspector.get_foreign_keys("api_calls")}
            execution_fk = api_call_fks["fk_api_calls_execution_attempt"]
            assert execution_fk["constrained_columns"] == ["user_id", "project_name", "execution_id"]
            assert execution_fk["referred_columns"] == ["user_id", "project_name", "execution_id"]
    finally:
        engine.dispose()


def test_downgrade_then_upgrade_round_trips(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
) -> None:
    revision, parent = migration_revisions(_MIGRATION)
    cfg, db_path = alembic_cfg
    command.upgrade(cfg, parent)
    engine = _engine(db_path)
    try:
        with engine.begin() as connection:
            before = set(sa.inspect(connection).get_table_names())
        command.upgrade(cfg, revision)
        command.downgrade(cfg, parent)
        with engine.begin() as connection:
            after = set(sa.inspect(connection).get_table_names())
        assert EXPECTED_TABLES.isdisjoint(after)
        assert before == after
        command.upgrade(cfg, revision)
        with engine.begin() as connection:
            assert set(sa.inspect(connection).get_table_names()) >= EXPECTED_TABLES
    finally:
        engine.dispose()


def test_task_attempt_no_pair_is_unique_within_scope(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "task_id": "task-1",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "PLANNED",
                    "terminal_at": None,
                },
            )
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-2",
                    "task_id": "task-1",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "PLANNED",
                    "terminal_at": None,
                },
            )
        # a different attempt_no for the same task is not a conflict
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-3",
                    "task_id": "task-1",
                    "attempt_no": 2,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "PLANNED",
                    "terminal_at": None,
                },
            )
    finally:
        engine.dispose()


def test_provider_job_id_is_unique_within_scope_when_bound(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "task_id": "task-1",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": "remote-1",
                    "state": "ACCEPTED",
                    "terminal_at": None,
                },
            )
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-2",
                    "task_id": "task-2",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": "remote-1",
                    "state": "ACCEPTED",
                    "terminal_at": None,
                },
            )
        # two NULL provider_job_id rows never conflict (the partial index excludes NULLs)
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-3",
                    "task_id": "task-3",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "PLANNED",
                    "terminal_at": None,
                },
            )
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-4",
                    "task_id": "task-4",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "PLANNED",
                    "terminal_at": None,
                },
            )
    finally:
        engine.dispose()


def test_invalid_state_is_rejected(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "task_id": "task-1",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "NOT_A_REAL_STATE",
                    "terminal_at": None,
                },
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("state", "terminal_at"),
    [
        ("SUCCEEDED", None),  # terminal state without terminal_at
        ("PLANNED", "2026-09-16 00:00:00"),  # non-terminal state with terminal_at
    ],
)
def test_terminal_at_must_match_terminal_state(
    alembic_cfg: tuple[Config, Path],
    migration_revisions: Callable[[str], tuple[str, str]],
    state: str,
    terminal_at: str | None,
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "task_id": "task-1",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": state,
                    "terminal_at": terminal_at,
                },
            )
    finally:
        engine.dispose()


def test_attempt_no_must_be_at_least_one(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "task_id": "task-1",
                    "attempt_no": 0,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "PLANNED",
                    "terminal_at": None,
                },
            )
    finally:
        engine.dispose()


def test_lease_token_must_be_at_least_one_when_present(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO execution_attempts (user_id, project_name, execution_id, task_id, attempt_no, "
                    "request_digest, route_json, state, state_version, lease_token, "
                    "created_at, updated_at) "
                    "VALUES ('default', 'demo', 'exec-1', 'task-1', 1, 'sha256:x', '{}', 'PLANNED', 1, 0, "
                    "'2026-09-16 00:00:00', '2026-09-16 00:00:00')"
                )
            )
    finally:
        engine.dispose()


def test_received_seq_must_be_at_least_one(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "task_id": "task-1",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "SUBMIT_OUTCOME_UNKNOWN",
                    "terminal_at": None,
                },
            )
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_OBSERVATION,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "received_seq": 0,
                    "observation_id": "obs-1",
                    "kind": "ACCEPTED",
                },
            )
    finally:
        engine.dispose()


def test_duplicate_observation_id_within_one_attempt_is_rejected(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_ATTEMPT,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "task_id": "task-1",
                    "attempt_no": 1,
                    "client_token": None,
                    "provider_job_id": None,
                    "state": "SUBMIT_OUTCOME_UNKNOWN",
                    "terminal_at": None,
                },
            )
            conn.execute(
                _INSERT_OBSERVATION,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "received_seq": 1,
                    "observation_id": "obs-1",
                    "kind": "ACCEPTED",
                },
            )
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_OBSERVATION,
                {
                    "project_name": "demo",
                    "execution_id": "exec-1",
                    "received_seq": 2,
                    "observation_id": "obs-1",
                    "kind": "ACCEPTED",
                },
            )
    finally:
        engine.dispose()


def test_command_receipt_key_is_unique_within_scope(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn:
            conn.execute(
                _INSERT_COMMAND_RECEIPT,
                {"project_name": "demo", "actor_scope": "user:alice", "command_id": "cmd-1", "task_id": "task-1"},
            )
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                _INSERT_COMMAND_RECEIPT,
                {"project_name": "demo", "actor_scope": "user:alice", "command_id": "cmd-1", "task_id": "task-2"},
            )
        # a different actor_scope with the same command_id is not a conflict
        with engine.begin() as conn:
            conn.execute(
                _INSERT_COMMAND_RECEIPT,
                {"project_name": "demo", "actor_scope": "user:bob", "command_id": "cmd-1", "task_id": "task-3"},
            )
    finally:
        engine.dispose()


def test_project_event_dedupe_key_is_unique_within_scope(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn:
            conn.execute(_INSERT_PROJECT_EVENT, {"project_name": "demo", "dedupe_key": "dedupe-1"})
        with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
            conn.execute(_INSERT_PROJECT_EVENT, {"project_name": "demo", "dedupe_key": "dedupe-1"})
    finally:
        engine.dispose()


def test_project_event_id_is_a_monotonic_autoincrement(
    alembic_cfg: tuple[Config, Path], migration_revisions: Callable[[str], tuple[str, str]]
) -> None:
    engine = _upgrade_to_revision(alembic_cfg, migration_revisions)
    try:
        with engine.begin() as conn:
            conn.execute(_INSERT_PROJECT_EVENT, {"project_name": "demo", "dedupe_key": "dedupe-1"})
            conn.execute(_INSERT_PROJECT_EVENT, {"project_name": "demo", "dedupe_key": "dedupe-2"})
            rows = conn.execute(sa.text("SELECT event_id FROM project_events ORDER BY event_id")).fetchall()
        assert [row[0] for row in rows] == sorted(row[0] for row in rows)
        assert rows[1][0] > rows[0][0]
    finally:
        engine.dispose()
