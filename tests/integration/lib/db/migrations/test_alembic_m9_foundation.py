"""M9's exact five-table migration is reversible on disposable PostgreSQL."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

TABLES = {"m9_cohort_profiles", "m9_cohort_profile_heads", "m9_command_receipts", "m9_events", "host_custodian_leases"}
ROOT = Path(__file__).resolve().parents[5]


def migration(*, include_successors: bool = True):
    path = ROOT / "alembic/versions/9a9c4a0e0001_add_m9_opportunity_foundation.py"
    spec = spec_from_file_location("m9_foundation_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    if not include_successors:
        return module
    from tests.integration.lib.db.migrations.test_alembic_m9_acquisition import migration as acquisition_migration

    acquisition = acquisition_migration()

    def downgrade() -> None:
        acquisition.downgrade()
        module.downgrade()

    def upgrade() -> None:
        module.upgrade()
        acquisition.upgrade()

    return SimpleNamespace(
        revision=module.revision,
        down_revision=module.down_revision,
        branch_labels=module.branch_labels,
        depends_on=module.depends_on,
        upgrade=upgrade,
        downgrade=downgrade,
    )


def test_migration_extends_the_accepted_singleton_with_one_linear_revision():
    module = migration(include_successors=False)
    assert (module.revision, module.down_revision, module.branch_labels, module.depends_on) == (
        "9a9c4a0e0001",
        "918c4a0e0001",
        None,
        None,
    )
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert ScriptDirectory.from_config(cfg).get_heads() == ["9b9c4a0e0002"]


async def test_five_table_round_trip_preserves_every_existing_table(session_factory):
    module = migration(include_successors=False)
    async with session_factory() as session, session.begin():
        assert session.get_bind().dialect.name == "postgresql", (
            "M9_REQUIRED_EVIDENCE_MISSING: disposable PostgreSQL required"
        )
        connection = await session.connection()

        def prove(sync_connection):
            before = set(inspect(sync_connection).get_table_names())
            assert before >= TABLES
            context = MigrationContext.configure(sync_connection)
            from tests.integration.lib.db.migrations.test_alembic_m9_acquisition import (
                migration as acquisition_migration,
            )

            acquisition = acquisition_migration()
            with Operations.context(context):
                acquisition.downgrade()
                predecessor_tables = set(inspect(sync_connection).get_table_names())
                module.downgrade()
                assert set(inspect(sync_connection).get_table_names()) == predecessor_tables - TABLES
                module.upgrade()
                assert set(inspect(sync_connection).get_table_names()) == predecessor_tables
                module.downgrade()
                assert set(inspect(sync_connection).get_table_names()) == predecessor_tables - TABLES
                module.upgrade()
                assert set(inspect(sync_connection).get_table_names()) == predecessor_tables
                acquisition.upgrade()
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
