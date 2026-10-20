"""The manual successor adds five scoped families and preserves legacy dispatch identity."""

from __future__ import annotations

import importlib
import sqlite3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint, inspect

from alembic import command

ROOT = Path(__file__).resolve().parents[5]
TABLES = {
    "m9_manual_admissions",
    "m9_manual_publication_intents",
    "m9_manual_upload_leases",
    "m9_manual_read_leases",
    "m9_manual_closure_intents",
}


def successor():
    path = ROOT / "alembic/versions/9b9c4a0e0002_add_m9_manual_admission.py"
    assert path.is_file(), "manual admission successor migration is missing"
    spec = spec_from_file_location("m9_manual_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_successor_head_and_five_restrict_scoped_model_families(alembic_cfg):
    cfg, _ = alembic_cfg
    module = successor()
    assert (module.revision, module.down_revision) == ("9b9c4a0e0002", "9b9c4a0e0001")
    assert ScriptDirectory.from_config(cfg).get_heads() == [module.revision]
    models = importlib.import_module("lib.db.models.opportunity_manual_admission")
    exported = importlib.import_module("lib.db.models")
    names = (
        "M9ManualAdmissionModel",
        "M9ManualPublicationIntentModel",
        "M9ManualUploadLeaseModel",
        "M9ManualReadLeaseModel",
        "M9ManualClosureIntentModel",
    )
    actual = set()
    for name in names:
        cls = getattr(models, name)
        assert getattr(exported, name) is cls
        table = cls.__table__
        actual.add(table.name)
        assert {"user_id", "project_name"} <= {c.name for c in table.primary_key}
        fks = [c for c in table.constraints if isinstance(c, ForeignKeyConstraint)]
        assert all(c.ondelete == "RESTRICT" for c in fks)
        assert {c.referred_table.name for c in fks} == {"users", "m9_acquisition_attempts"}
        assert any(isinstance(c, CheckConstraint) for c in table.constraints)
    assert actual == TABLES
    attempt = exported.M9AcquisitionAttemptModel.__table__
    assert ("user_id", "actor_id", "operation", "command_id") in {
        tuple(col.name for col in c.columns) for c in attempt.constraints if isinstance(c, UniqueConstraint)
    }


def test_sqlite_roundtrip_adds_only_successor_tables_and_preserves_predecessor(alembic_cfg):
    cfg, db = alembic_cfg
    successor()
    command.upgrade(cfg, "9b9c4a0e0001")
    with sqlite3.connect(db) as connection:
        before = {r[0] for r in connection.execute("select name from sqlite_master where type='table'")}
        old_columns = list(connection.execute("pragma table_info(m9_acquisition_attempts)"))
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as connection:
        after = {r[0] for r in connection.execute("select name from sqlite_master where type='table'")}
        assert after - before == TABLES
        columns = {r[1]: r for r in connection.execute("pragma table_info(m9_acquisition_attempts)")}
        assert columns["protocol_version"][3] == 1
        assert columns["protocol_version"][4] == "'m9.acquisition.v1'"
        for table in TABLES:
            assert {row[2] for row in connection.execute(f"pragma foreign_key_list({table})")} == {
                "users",
                "m9_acquisition_attempts",
            }
        sql = connection.execute("select sql from sqlite_master where name='m9_acquisition_attempts'").fetchone()[0]
        assert "EXPIRED_UNRECOVERABLE" in sql
    command.downgrade(cfg, "9b9c4a0e0001")
    with sqlite3.connect(db) as connection:
        assert {r[0] for r in connection.execute("select name from sqlite_master where type='table'")} == before
        assert list(connection.execute("pragma table_info(m9_acquisition_attempts)")) == old_columns
        sql = connection.execute("select sql from sqlite_master where name='m9_acquisition_attempts'").fetchone()[0]
        assert "EXPIRED_UNRECOVERABLE" not in sql
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone() == ("9b9c4a0e0002",)


async def test_postgres_roundtrip_preserves_full_predecessor_and_scoped_constraints(session_factory):
    module = successor()
    async with session_factory() as session, session.begin():
        assert session.get_bind().dialect.name == "postgresql", "disposable PostgreSQL required"
        connection = await session.connection()

        def prove(sync_connection):
            before = set(inspect(sync_connection).get_table_names())
            assert before >= TABLES
            with Operations.context(MigrationContext.configure(sync_connection)):
                module.downgrade()
                assert set(inspect(sync_connection).get_table_names()) == before - TABLES
                assert "protocol_version" not in {
                    c["name"] for c in inspect(sync_connection).get_columns("m9_acquisition_attempts")
                }
                module.upgrade()
                assert set(inspect(sync_connection).get_table_names()) == before
            inspector = inspect(sync_connection)
            for table in TABLES:
                assert all(fk["options"].get("ondelete") == "RESTRICT" for fk in inspector.get_foreign_keys(table))
                assert {"user_id", "project_name"} <= set(inspector.get_pk_constraint(table)["constrained_columns"])
            assert ("user_id", "actor_id", "operation", "command_id") in {
                tuple(c["column_names"]) for c in inspector.get_unique_constraints("m9_acquisition_attempts")
            }

        await connection.run_sync(prove)


@pytest.mark.parametrize("kind", ["v2_attempt", "reserved_admission"])
def test_downgrade_refuses_successor_custody_before_any_drop(alembic_cfg, kind):
    cfg, db = alembic_cfg
    successor()
    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as connection:
        if kind == "v2_attempt":
            connection.execute("""insert into m9_acquisition_attempts
                (user_id,project_name,attempt_id,actor_id,operation,command_id,request_digest,query_id,query_revision,
                 attempt_version,state,transitioned_at,body_json,protocol_version)
                values ('fixture-owner','fixture-project','fixture-attempt','fixture-actor','acquire','fixture-command',
                 'fixture-digest','fixture-query',1,1,'PLANNED','2026-10-20','{}','m9.acquisition.v2')""")
        else:
            connection.execute("""insert into m9_manual_admissions
                (user_id,project_name,attempt_id,phase,version,body_json,metadata_digest)
                values ('fixture-owner','fixture-project','fixture-attempt','RESERVED',1,'{}','fixture-digest')""")
    with pytest.raises(RuntimeError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        command.downgrade(cfg, "9b9c4a0e0001")
    with sqlite3.connect(db) as connection:
        assert {r[0] for r in connection.execute("select name from sqlite_master where type='table'")} >= TABLES
        assert connection.execute("select version_num from alembic_version").fetchone() == ("9b9c4a0e0002",)
