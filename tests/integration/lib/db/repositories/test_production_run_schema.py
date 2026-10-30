"""Migration-owned guards on the real orchestration schema."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests.integration.lib.db.repositories.test_production_runs import claim, create_run, intent_for


def migration():
    path = Path(__file__).resolve().parents[5] / "alembic/versions/b7a310300001_autonomous_production.py"
    spec = importlib.util.spec_from_file_location("autonomous_production_migration_fixture", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("target", ["policy_update", "policy_delete", "intent_update", "intent_delete"])
async def test_policy_and_intent_bytes_are_immutable(concurrent_session_factory, target: str):
    from lib.db.models.production_run import ProductionPolicyModel, ProductionStepModel
    from lib.db.repositories.production_runs import ProductionRunRepository

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    async with factory() as session, session.begin():
        await ProductionRunRepository(session).stage_intent(run=run, intent=intent_for(run))
        connection = await session.connection()
        await connection.run_sync(migration().install_immutability)
    model = ProductionPolicyModel if target.startswith("policy") else ProductionStepModel
    stmt = (
        sa.delete(model)
        if target.endswith("delete")
        else (
            sa.update(model).values(policy_json="{}")
            if model is ProductionPolicyModel
            else sa.update(model).values(intent_json="{}")
        )
    )
    with pytest.raises(sa.exc.IntegrityError, match="AUTO_PRODUCTION_IMMUTABLE"):
        async with factory() as session, session.begin():
            await session.execute(stmt)


async def test_snapshot_ceiling_measures_bytes_not_character_count(concurrent_session_factory):
    from lib.db.models.production_run import ProductionRunModel

    factory = concurrent_session_factory
    run = await create_run(factory)
    with pytest.raises(sa.exc.IntegrityError, match="snapshot_json_bytes"):
        async with factory() as session, session.begin():
            await session.execute(
                sa.update(ProductionRunModel)
                .where(ProductionRunModel.run_id == run.run_id)
                .values(snapshot_json='{"data":"' + "ắ" * 400000 + '"}')
            )


async def test_raw_step_insert_cannot_cross_parent_scope(concurrent_session_factory):
    from lib.db.models.production_run import ProductionStepModel
    from r2.automation.identity import policy_digest

    factory = concurrent_session_factory
    run = await create_run(factory)

    async def insert_wrong_scope():
        async with factory() as session, session.begin():
            session.add(
                ProductionStepModel(
                    command_id="wrong-scope",
                    user_id="default",
                    project_name="film",
                    run_id=run.run_id,
                    stage="BRIEF",
                    unit_key="project",
                    generation=1,
                    repair_index=0,
                    input_digest=run.input_digest,
                    policy_digest=policy_digest(run.policy),
                    intent_digest="sha256:" + "d" * 64,
                    intent_json="{}",
                    receipt_json=None,
                )
            )
            await session.flush()

    with pytest.raises(sa.exc.IntegrityError, match="fk_auto_step_run"):
        await insert_wrong_scope()


async def test_upgrade_downgrade_preserves_unrelated_user_rows(concurrent_session_factory):
    factory = concurrent_session_factory
    module = migration()
    async with factory() as session, session.begin():
        connection = await session.connection()
        before = await session.scalar(sa.text("SELECT count(*) FROM users"))

        def roundtrip(sync):
            for table in (
                "auto_authorization_decisions",
                "auto_grant_heads",
                "auto_grant_events",
                "auto_production_usage_refs",
                "auto_production_allocations",
                "auto_production_steps",
                "auto_production_runs",
                "auto_production_policies",
            ):
                sync.exec_driver_sql('DROP TABLE "' + table + '"')
            with Operations.context(MigrationContext.configure(sync)):
                module.upgrade()
                module.downgrade()
                assert "auto_production_runs" not in sa.inspect(sync).get_table_names()
                module.upgrade()
                assert "auto_production_runs" in sa.inspect(sync).get_table_names()

        await connection.run_sync(roundtrip)
        assert await session.scalar(sa.text("SELECT count(*) FROM users")) == before
    run = await create_run(factory)
    assert run.version == 1


async def test_unknown_allocation_cannot_drop_hold_through_sql(concurrent_session_factory):
    from lib.db.models.production_run import ProductionBudgetModel
    from lib.db.repositories.production_runs import ProductionRunRepository
    from r2.contracts.automation import UsageReceipt

    factory = concurrent_session_factory
    await create_run(factory)
    run = await claim(factory)
    async with factory() as session, session.begin():
        connection = await session.connection()
        await connection.run_sync(migration().install_immutability)
        repo = ProductionRunRepository(session)
        intent = intent_for(run)
        await repo.stage_intent(run=run, intent=intent)
        reservation = await repo.reserve_budget(run=run, intent=intent)
        await repo.settle_budget(
            reservation=reservation,
            usage=UsageReceipt(
                owner="story",
                receipt_ref="unknown-1",
                digest="sha256:" + "d" * 64,
                reservation_id=reservation.reservation_id,
                currency="USD",
                cost_minor_units=0,
                model_calls=0,
                tasks=0,
                runtime_seconds=0,
                outcome="UNKNOWN",
            ),
        )
    with pytest.raises(sa.exc.IntegrityError, match="AUTO_PRODUCTION_IMMUTABLE"):
        async with factory() as session, session.begin():
            await session.execute(
                sa.update(ProductionBudgetModel)
                .where(ProductionBudgetModel.reservation_id == reservation.reservation_id)
                .values(held_cost=0)
            )


def test_sqlite_migration_installs_immutable_guard_and_roundtrips():
    module = migration()
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("CREATE TABLE users (id VARCHAR PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO users(id) VALUES ('u1')")
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
                connection.exec_driver_sql(
                    "INSERT INTO auto_production_policies "
                    "(user_id,project_name,run_id,policy_digest,policy_json,created_at) "
                    "VALUES ('u1','film','run','digest','{}','2026-10-30')"
                )
                with pytest.raises(sa.exc.IntegrityError, match="AUTO_PRODUCTION_IMMUTABLE"):
                    connection.exec_driver_sql("UPDATE auto_production_policies SET policy_json='[]'")
                module.downgrade()
                assert connection.exec_driver_sql("SELECT count(*) FROM users").scalar_one() == 1
                module.upgrade()
                assert "auto_production_runs" in sa.inspect(connection).get_table_names()
    finally:
        engine.dispose()
