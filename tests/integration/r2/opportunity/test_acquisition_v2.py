"""The V2 host composes actual SQL policy and one application-owned transaction."""

import importlib

import pytest
from sqlalchemy import func, select

from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel
from tests.integration.lib.db.repositories.test_opportunity_manual_admission import manual_subject


async def test_host_uow_uses_current_real_project_policy_and_preserves_rollback(session_factory):
    host = importlib.import_module("server.services.opportunity_acquisition_v2")
    command, descriptor, _ = await manual_subject(session_factory, host_policy=True)
    uow = host.HostManualAdmissionUnitOfWork(session_factory, user_id="u1", project_name="show-a")

    async def interrupted():
        async with uow.transaction() as tx:
            planned, created = await tx.manual.prepare(
                command, attempt_id="019a0000-0000-7000-8000-000000000052", descriptor=descriptor
            )
            assert created
            await tx.manual.start(planned.attempt_id, expected_attempt_version=1)
            raise RuntimeError("before application commit")

    with pytest.raises(RuntimeError, match="before application commit"):
        await interrupted()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == 0
    async with uow.transaction() as tx:
        planned, created = await tx.manual.prepare(
            command, attempt_id="019a0000-0000-7000-8000-000000000052", descriptor=descriptor
        )
        assert created
        running = await tx.manual.start(planned.attempt_id, expected_attempt_version=1)
    async with uow.transaction() as tx:
        assert await tx.manual.get_for_command(command) == running


async def test_host_uow_refuses_a_fixture_profile_outside_actual_policy(session_factory):
    from r2.opportunity.errors import OpportunityError

    host = importlib.import_module("server.services.opportunity_acquisition_v2")
    command, descriptor, _ = await manual_subject(session_factory)
    uow = host.HostManualAdmissionUnitOfWork(session_factory, user_id="u1", project_name="show-a")

    async def wrong_policy():
        async with uow.transaction() as tx:
            await tx.manual.prepare(command, attempt_id="019a0000-0000-7000-8000-000000000052", descriptor=descriptor)

    with pytest.raises(OpportunityError, match="M9_COHORT_LEAKAGE"):
        await wrong_policy()
