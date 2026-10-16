"""M9's exact five-table migration is reversible on disposable PostgreSQL."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

TABLES = {"m9_cohort_profiles", "m9_cohort_profile_heads", "m9_command_receipts", "m9_events", "host_custodian_leases"}
ROOT = Path(__file__).resolve().parents[5]


def migration():
    path = ROOT / "alembic/versions/9a9c4a0e0001_add_m9_opportunity_foundation.py"
    spec = spec_from_file_location("m9_foundation_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_extends_the_accepted_singleton_with_one_linear_revision():
    module = migration()
    assert (module.revision, module.down_revision, module.branch_labels, module.depends_on) == (
        "9a9c4a0e0001",
        "918c4a0e0001",
        None,
        None,
    )
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["9a9c4a0e0001"]


async def test_five_table_round_trip_preserves_every_existing_table(session_factory):
    module = migration()
    async with session_factory() as session, session.begin():
        assert session.get_bind().dialect.name == "postgresql", (
            "M9_REQUIRED_EVIDENCE_MISSING: disposable PostgreSQL required"
        )
        connection = await session.connection()

        def prove(sync_connection):
            before = set(inspect(sync_connection).get_table_names())
            assert before >= TABLES
            context = MigrationContext.configure(sync_connection)
            with Operations.context(context):
                module.downgrade()
                assert set(inspect(sync_connection).get_table_names()) == before - TABLES
                module.upgrade()
                assert set(inspect(sync_connection).get_table_names()) == before
                module.downgrade()
                assert set(inspect(sync_connection).get_table_names()) == before - TABLES
                module.upgrade()
                assert set(inspect(sync_connection).get_table_names()) == before
            assert sync_connection.scalar(text("SELECT count(*) FROM users")) >= 1
            inspector = inspect(sync_connection)
            assert inspector.get_pk_constraint("m9_cohort_profiles")["constrained_columns"] == [
                "user_id",
                "project_name",
                "profile_id",
                "revision",
            ]
            unique_receipts = {
                tuple(row["column_names"]) for row in inspector.get_unique_constraints("m9_command_receipts")
            }
            assert ("user_id", "actor_id", "operation", "command_id") in unique_receipts
            assert ("user_id", "project_name", "actor_id", "operation", "command_id") in {
                tuple(row["column_names"]) for row in inspector.get_unique_constraints("host_custodian_leases")
            }
            checks = {row["name"] for row in inspector.get_check_constraints("m9_cohort_profiles")}
            assert "ck_m9_cohort_profiles_parent" in checks
            for table in TABLES:
                assert inspector.get_pk_constraint(table)["name"] is not None
                owner = [fk for fk in inspector.get_foreign_keys(table) if fk["referred_table"] == "users"]
                assert len(owner) == 1
                assert owner[0]["options"]["ondelete"] == "RESTRICT"

        await connection.run_sync(prove)
