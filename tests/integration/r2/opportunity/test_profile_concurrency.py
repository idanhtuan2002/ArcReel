"""Controlled PostgreSQL interleavings prove guard and head-lock behavior."""

import asyncio

import pytest
from sqlalchemy import text

from lib.db.repositories.opportunity import OpportunityUnitOfWork
from r2.contracts.opportunity import CommandContext
from r2.opportunity.errors import OpportunityError, StopCode
from tests.integration.lib.db.repositories.test_opportunity_profiles import (
    COMMAND,
    ID,
    OPERATION,
    OTHER,
    make_profile,
    publish,
    row_counts,
    stage_publication,
)


async def observe_blocked(factory, waiting_pid, blocker_pid):
    async with factory() as observer:
        assert observer.get_bind().dialect.name == "postgresql", "M9_REQUIRED_EVIDENCE_MISSING"
        async with asyncio.timeout(10):
            while True:
                blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting_pid})
                if blocker_pid in blockers:
                    return
                await asyncio.sleep(0)


@pytest.mark.parametrize("mode", ["equal", "divergent", "collision"])
async def test_absent_receipt_races_serialize_but_full_key_and_digest_remain_authority(session_factory, mode):
    first_locked, second_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    def collision_key(operation, context):
        return (7, 11)

    kwargs = {"guard_key": collision_key} if mode == "collision" else {}
    original = make_profile()
    second_profile = original if mode == "equal" else make_profile(profile_id=OTHER)
    first_context = CommandContext(command_id=COMMAND, user_id="u1", project_name="show-a", actor_id="human-a")
    second_context = first_context.model_copy(update={"command_id": OTHER}) if mode == "collision" else first_context

    async def first():
        async with OpportunityUnitOfWork(session_factory, **kwargs).transaction() as repo:
            pids["first"] = await repo.session.scalar(text("SELECT pg_backend_pid()"))
            await repo.lock_command_key(context=first_context, operation=OPERATION)
            first_locked.set()
            await release.wait()
            return await stage_publication(repo, original, first_context)

    async def second():
        await first_locked.wait()
        async with OpportunityUnitOfWork(session_factory, **kwargs).transaction() as repo:
            pids["second"] = await repo.session.scalar(text("SELECT pg_backend_pid()"))
            second_entered.set()
            return await stage_publication(repo, second_profile, second_context)

    tasks = (asyncio.create_task(first()), asyncio.create_task(second()))
    try:
        await asyncio.wait_for(second_entered.wait(), timeout=10)
        await observe_blocked(session_factory, pids["second"], pids["first"])
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert not isinstance(results[0], BaseException)
    if mode == "equal":
        assert results[0].model_dump_json() == results[1].model_dump_json()
        assert await row_counts(session_factory) == (1, 1, 1, 1)
    elif mode == "divergent":
        assert isinstance(results[1], OpportunityError)
        assert results[1].code is StopCode.M9_COMMAND_REPLAY_CONFLICT
        assert await row_counts(session_factory) == (1, 1, 1, 1)
    else:
        assert not isinstance(results[1], BaseException)
        assert results[0].command_id != results[1].command_id
        assert await row_counts(session_factory) == (2, 2, 2, 2)


async def test_different_commands_racing_genesis_commit_one_complete_aggregate(session_factory):
    both_observed_absence = asyncio.Event()
    arrivals = 0

    async def attempt(command_id):
        nonlocal arrivals
        context = CommandContext(command_id=command_id, user_id="u1", project_name="show-a", actor_id="human-a")
        async with OpportunityUnitOfWork(session_factory).transaction() as repo:
            await repo.lock_command_key(context=context, operation=OPERATION)
            assert await repo.get_head_for_update(user_id="u1", project_name="show-a", profile_id=ID) is None
            arrivals += 1
            if arrivals == 2:
                both_observed_absence.set()
            await asyncio.wait_for(both_observed_absence.wait(), timeout=10)
            return await stage_publication(repo, make_profile(), context)

    results = await asyncio.gather(attempt(COMMAND), attempt(OTHER), return_exceptions=True)
    successes = [value for value in results if not isinstance(value, BaseException)]
    failures = [value for value in results if isinstance(value, OpportunityError)]
    assert len(successes) == len(failures) == 1
    assert failures[0].code is StopCode.M9_STALE_HEAD
    assert await row_counts(session_factory) == (1, 1, 1, 1)


async def test_append_waiter_reads_the_committed_head_before_admission(session_factory):
    await publish(session_factory, make_profile())
    head_locked, waiter_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    async def winner():
        context = CommandContext(command_id=OTHER, user_id="u1", project_name="show-a", actor_id="human-a")
        async with OpportunityUnitOfWork(session_factory).transaction() as repo:
            pids["winner"] = await repo.session.scalar(text("SELECT pg_backend_pid()"))
            await repo.lock_command_key(context=context, operation=OPERATION)
            head = await repo.get_head_for_update(user_id="u1", project_name="show-a", profile_id=ID)
            assert head.current_revision == 1
            head_locked.set()
            await release.wait()
            return await stage_publication(repo, make_profile(revision=2), context)

    async def waiter():
        await head_locked.wait()
        async with OpportunityUnitOfWork(session_factory).transaction() as repo:
            pids["waiter"] = await repo.session.scalar(text("SELECT pg_backend_pid()"))
            waiter_entered.set()
            head = await repo.get_head_for_update(user_id="u1", project_name="show-a", profile_id=ID)
            assert head.current_revision == 2
            return head

    tasks = (asyncio.create_task(winner()), asyncio.create_task(waiter()))
    try:
        await asyncio.wait_for(waiter_entered.wait(), timeout=10)
        await observe_blocked(session_factory, pids["waiter"], pids["winner"])
    finally:
        release.set()
        receipt, head = await asyncio.gather(*tasks)
    assert receipt.head == head
    assert await row_counts(session_factory) == (2, 1, 2, 2)


@pytest.mark.parametrize("writer_first", [True, False])
async def test_project_policy_read_serializes_real_admission_in_both_directions(session_factory, writer_first):
    from lib.db.adaptation_uow import SqlAlchemyAdaptationUnitOfWork, adaptation_uow_factory
    from r2.adaptation.authority import AdaptationAuthorityService
    from r2.adaptation.evaluation import ProfileEvaluationService, report_ref_of
    from r2.adaptation.evidence import AdaptationEvidenceService
    from r2.advanced_creative.lineage import host_policy_digest
    from server.services.opportunity import HostProfileUnitOfWork
    from tests.integration.r2.adaptation._fakes import FakeAuthority
    from tests.integration.r2.adaptation.test_screenplay_admission import (
        _PRINCIPAL,
        _admit_command,
        _seed_admissible_proposal,
    )

    factory = adaptation_uow_factory(session_factory)
    branch, map_receipt, proposal, report = await _seed_admissible_proposal(
        AdaptationEvidenceService(factory),
        AdaptationAuthorityService(factory, FakeAuthority()),
        ProfileEvaluationService(factory),
    )
    command = _admit_command(
        proposal=proposal,
        profile_ref=branch.profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
    )
    writer_entered, writer_staged = asyncio.Event(), asyncio.Event()
    reader_entered, reader_resolved, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    class ObservedAdmissionUnitOfWork(SqlAlchemyAdaptationUnitOfWork):
        async def __aenter__(self):
            await super().__aenter__()
            pids["writer"] = await self.session.scalar(text("SELECT pg_backend_pid()"))
            writer_entered.set()
            return self

        async def commit(self):
            writer_staged.set()
            if writer_first:
                await release.wait()
            await super().commit()

    authority = AdaptationAuthorityService(lambda: ObservedAdmissionUnitOfWork(session_factory), FakeAuthority())

    async def read_policy():
        async with HostProfileUnitOfWork(session_factory).transaction() as repo:
            pids["reader"] = await repo.session.scalar(text("SELECT pg_backend_pid()"))
            reader_entered.set()
            policy = await repo.creative_policy_identity(user_id="u1", project_name="project-a")
            reader_resolved.set()
            if not writer_first:
                await release.wait()
            return policy

    async def admit():
        return await authority.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)

    tasks = []
    try:
        if writer_first:
            tasks.append(asyncio.create_task(admit()))
            await asyncio.wait_for(writer_staged.wait(), timeout=10)
            tasks.append(asyncio.create_task(read_policy()))
            await asyncio.wait_for(reader_entered.wait(), timeout=10)
            await observe_blocked(session_factory, pids["reader"], pids["writer"])
        else:
            tasks.append(asyncio.create_task(read_policy()))
            await asyncio.wait_for(reader_resolved.wait(), timeout=10)
            tasks.append(asyncio.create_task(admit()))
            await asyncio.wait_for(writer_entered.wait(), timeout=10)
            await observe_blocked(session_factory, pids["writer"], pids["reader"])
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert not any(isinstance(result, BaseException) for result in results), results
    expected = (
        branch.profile_ref.profile_id.value,
        branch.profile_ref.profile_version,
        branch.profile_ref.policy_pack_digest,
    )
    assert results[1] == expected if writer_first else results[0] == ("arcreel.host", "1", host_policy_digest())
    async with HostProfileUnitOfWork(session_factory).transaction() as repo:
        assert await repo.creative_policy_identity(user_id="u1", project_name="project-a") == expected
