"""The B migration owns exactly nine scoped tables and preserves the A predecessor."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[5]
TABLES = {
    "m9_consumed_capability_grants",
    "m9_capability_evaluations",
    "m9_source_queries",
    "m9_source_query_heads",
    "m9_acquisition_attempts",
    "m9_snapshot_pages",
    "m9_source_snapshots",
    "m9_source_observations",
    "m9_observation_heads",
}


def migration():
    path = ROOT / "alembic/versions/9b9c4a0e0001_add_m9_acquisition_observations.py"
    assert path.is_file(), "B3 nine-table migration is missing"
    spec = spec_from_file_location("m9b_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_linear_migration_and_singleton_head():
    module = migration()
    assert (module.revision, module.down_revision, module.branch_labels, module.depends_on) == (
        "9b9c4a0e0001",
        "9a9c4a0e0001",
        None,
        None,
    )
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["9b9c4a0e0001"]


async def test_nine_table_round_trip_preserves_every_predecessor_table(session_factory):
    module = migration()
    async with session_factory() as session, session.begin():
        assert session.get_bind().dialect.name == "postgresql", (
            "M9_REQUIRED_EVIDENCE_MISSING: disposable PostgreSQL required"
        )
        connection = await session.connection()

        def prove(sync_connection):
            before = set(inspect(sync_connection).get_table_names())
            assert before >= TABLES
            with Operations.context(MigrationContext.configure(sync_connection)):
                for _ in range(2):
                    module.downgrade()
                    assert set(inspect(sync_connection).get_table_names()) == before - TABLES
                    module.upgrade()
                    assert set(inspect(sync_connection).get_table_names()) == before
            inspector = inspect(sync_connection)
            for table in TABLES:
                assert {"user_id", "project_name"} <= set(inspector.get_pk_constraint(table)["constrained_columns"])
                owner = [f for f in inspector.get_foreign_keys(table) if f["referred_table"] == "users"]
                assert len(owner) == 1
                assert owner[0]["options"]["ondelete"] == "RESTRICT"
            attempts = {
                tuple(item["column_names"]) for item in inspector.get_unique_constraints("m9_acquisition_attempts")
            }
            assert ("user_id", "actor_id", "operation", "command_id") in attempts
            query_parents = [
                f for f in inspector.get_foreign_keys("m9_source_queries") if f["referred_table"] == "m9_source_queries"
            ]
            assert len(query_parents) == 1
            assert query_parents[0]["constrained_columns"] == ["user_id", "project_name", "query_id", "parent_revision"]

        await connection.run_sync(prove)
