"""Protocol selection preserves the existing authoritative command and state guards."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel
from r2.contracts.opportunity import AttemptState
from r2.opportunity.errors import OpportunityError
from tests.integration.lib.db.repositories.test_opportunity_acquisition import prepare_attempt, unit_of_work


@pytest.mark.parametrize("operation", ["read", "replay", "transition"])
async def test_v1_attempt_access_refuses_v2_even_with_a_parseable_legacy_body(session_factory, operation):
    attempt = await prepare_attempt(session_factory)
    async with session_factory() as session, session.begin():
        await session.execute(update(M9AcquisitionAttemptModel).values(protocol_version="m9.acquisition.v2"))

    async def access_legacy():
        async with unit_of_work(session_factory).transaction() as tx:
            if operation == "read":
                await tx.attempts.get_exact(attempt.attempt_id)
            elif operation == "replay":
                await tx.attempts.prepare(attempt)
            else:
                await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)

    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await access_legacy()


async def test_protocol_version_cannot_allocate_a_second_global_command_identity(session_factory):
    attempt = await prepare_attempt(session_factory)
    async with session_factory() as session:
        original = await session.get(M9AcquisitionAttemptModel, ("u1", "show-a", attempt.attempt_id))
        values = {column.name: getattr(original, column.name) for column in M9AcquisitionAttemptModel.__table__.columns}
    values.update(attempt_id="019a0000-0000-7000-8000-000000000042", protocol_version="m9.acquisition.v2")

    async def duplicate_command():
        async with session_factory() as session, session.begin():
            session.add(M9AcquisitionAttemptModel(**values))
            await session.flush()

    with pytest.raises(IntegrityError):
        await duplicate_command()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == 1


@pytest.mark.parametrize("protocol", ["m9.acquisition.v1", "unrecognized"])
async def test_sql_state_guard_never_widens_legacy_or_unknown_protocol(session_factory, protocol):
    await prepare_attempt(session_factory)
    with pytest.raises(IntegrityError):
        async with session_factory() as session, session.begin():
            await session.execute(
                update(M9AcquisitionAttemptModel).values(protocol_version=protocol, state="EXPIRED_UNRECOVERABLE")
            )
    async with session_factory() as session:
        row = (await session.scalars(select(M9AcquisitionAttemptModel))).one()
        assert row.protocol_version == "m9.acquisition.v1"
        assert row.state == "PLANNED"


async def test_native_successor_roundtrip_preserves_a_real_legacy_attempt_and_query(session_factory):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.integration.lib.db.migrations.test_alembic_m9_manual_admission import successor

    attempt = await prepare_attempt(session_factory)
    async with session_factory() as session, session.begin():
        original = await session.get(M9AcquisitionAttemptModel, ("u1", "show-a", attempt.attempt_id))
        before = original.body_json
        connection = await session.connection()

        def roundtrip(sync_connection):
            migration = successor()
            with Operations.context(MigrationContext.configure(sync_connection)):
                migration.downgrade()
                migration.upgrade()

        await connection.run_sync(roundtrip)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.attempts.get_exact(attempt.attempt_id) == attempt
    async with session_factory() as session:
        retained = await session.get(M9AcquisitionAttemptModel, ("u1", "show-a", attempt.attempt_id))
        assert retained.body_json == before
        assert retained.protocol_version == "m9.acquisition.v1"
