"""Immutable scoped profiles, CAS and receipt recovery on real PostgreSQL."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from lib.db.models.opportunity import M9CohortProfileModel, M9CommandReceiptModel, M9EventModel, M9ProfileHeadModel
from lib.db.repositories.opportunity import OpportunityProfileRepository, OpportunityUnitOfWork
from r2.contracts.opportunity import (
    CohortProfileReceipt,
    CommandContext,
    OpportunityCohortProfile,
    OpportunityCohortProfileHead,
    OpportunityCohortProfilePayload,
)
from r2.opportunity.digests import (
    digest_cohort_profile,
    digest_cohort_profile_payload,
    digest_command_request,
    digest_command_result,
)
from r2.opportunity.errors import OpportunityError, StopCode
from tests.unit.r2.contracts.test_opportunity import profile_payload

NOW = datetime(2026, 10, 16, tzinfo=UTC)
ID = "019a0000-0000-7000-8000-000000000001"
OTHER = "019a0000-0000-7000-8000-000000000002"
COMMAND = "019a0000-0000-7000-8000-000000000010"
H = "sha256:" + "a" * 64
OPERATION = "publish_cohort_profile"


def make_profile(*, profile_id=ID, revision=1, user_id="u1", project_name="show-a", actor_id="human-a"):
    payload = OpportunityCohortProfilePayload.model_validate(profile_payload())
    shell = OpportunityCohortProfile.model_construct(
        profile_id=profile_id,
        revision=revision,
        parent_revision=None if revision == 1 else revision - 1,
        user_id=user_id,
        project_name=project_name,
        payload=payload,
        payload_digest=digest_cohort_profile_payload(payload),
        profile_digest=H,
        created_by=actor_id,
        custodian_authorization_id=OTHER,
        custodian_policy_id="arcreel.showrunner-grant",
        custodian_policy_version="governance.showrunner_grant_event.v1",
        custodian_evidence_digest=H,
        custodian_admitted_at=NOW,
        created_at=NOW + timedelta(seconds=revision),
    )
    return OpportunityCohortProfile.model_validate(
        {**shell.model_dump(), "profile_digest": digest_cohort_profile(shell)}
    )


def make_receipt(profile, context, *, head_version=None):
    request_digest = digest_command_request(
        OPERATION,
        context,
        {
            "profile_id": profile.profile_id,
            "parent_revision": profile.parent_revision,
            "payload": profile.payload,
            "expected_head_version": None if profile.revision == 1 else profile.revision - 1,
        },
    )
    receipt = CohortProfileReceipt(
        command_id=context.command_id,
        request_digest=request_digest,
        profile=profile,
        head=OpportunityCohortProfileHead(
            profile_id=profile.profile_id,
            current_revision=profile.revision,
            head_version=head_version or profile.revision,
        ),
        result_digest=H,
        committed_at=profile.created_at,
    )
    return receipt.model_copy(update={"result_digest": digest_command_result(OPERATION, request_digest, receipt)})


async def stage_publication(repo, profile, context, *, fail_after=None):
    receipt = make_receipt(profile, context)
    await repo.lock_command_key(context=context, operation=OPERATION)
    old = await repo.get_command_receipt(context=context, operation=OPERATION, request_digest=receipt.request_digest)
    if old is not None:
        return old
    await repo.stage_profile(profile)
    if fail_after == "profile":
        raise RuntimeError("injected crash")
    await repo.stage_head(
        user_id=context.user_id,
        project_name=context.project_name,
        head=receipt.head,
        expected_head_version=None if profile.revision == 1 else profile.revision - 1,
    )
    if fail_after == "head":
        raise RuntimeError("injected crash")
    await repo.stage_event(profile=profile, committed_at=receipt.committed_at)
    if fail_after == "event":
        raise RuntimeError("injected crash")
    await repo.stage_command_receipt(context=context, operation=OPERATION, receipt=receipt)
    if fail_after == "receipt":
        raise RuntimeError("injected crash")
    return receipt


async def publish(factory, profile, *, command_id=COMMAND, actor_id="human-a", fail_after=None):
    context = CommandContext(
        command_id=command_id, user_id=profile.user_id, project_name=profile.project_name, actor_id=actor_id
    )
    async with OpportunityUnitOfWork(factory).transaction() as repo:
        return await stage_publication(repo, profile, context, fail_after=fail_after)


async def row_counts(factory):
    async with factory() as session:
        return tuple(
            [
                int((await session.execute(select(func.count()).select_from(model))).scalar_one())
                for model in (M9CohortProfileModel, M9ProfileHeadModel, M9EventModel, M9CommandReceiptModel)
            ]
        )


async def test_profile_history_and_receipts_survive_later_head_changes(session_factory):
    original = make_profile()
    first = await publish(session_factory, original)
    second = await publish(session_factory, make_profile(revision=2), command_id=OTHER)
    assert second.head.current_revision == 2
    replay = await publish(session_factory, original)
    assert replay.model_dump_json() == first.model_dump_json()
    async with session_factory() as session:
        repo = OpportunityProfileRepository(session)
        assert await repo.get_exact(user_id="u1", project_name="show-a", profile_id=ID, revision=1) == original
        assert await repo.get_head_for_update(user_id="u1", project_name="show-a", profile_id=ID) == second.head
    assert await row_counts(session_factory) == (2, 1, 2, 2)


@pytest.mark.parametrize("stage", ["profile", "head", "event", "receipt"])
async def test_every_staged_flush_rolls_back_with_the_authority_transaction(session_factory, stage):
    with pytest.raises(RuntimeError, match="injected crash"):
        await publish(session_factory, make_profile(), fail_after=stage)
    assert await row_counts(session_factory) == (0, 0, 0, 0)


async def test_scope_reads_are_indistinguishable_and_lists_return_current_heads(session_factory):
    await publish(session_factory, make_profile())
    await publish(session_factory, make_profile(revision=2), command_id=OTHER)
    next_id = "019a0000-0000-7000-8000-000000000003"
    other_command = "019a0000-0000-7000-8000-000000000011"
    await publish(session_factory, make_profile(profile_id=next_id), command_id=other_command)
    async with session_factory() as session:
        repo = OpportunityProfileRepository(session)
        for project, identity in (("foreign", ID), ("show-a", OTHER)):
            assert await repo.get_exact(user_id="u1", project_name=project, profile_id=identity, revision=1) is None
            assert await repo.get_head_for_update(user_id="u1", project_name=project, profile_id=identity) is None
        listed = await repo.list_heads(user_id="u1", project_name="show-a", after_id=None, limit=1)
        assert [(profile.profile_id, profile.revision) for profile in listed] == [(ID, 2)]
        rest = await repo.list_heads(user_id="u1", project_name="show-a", after_id=ID, limit=100)
        assert [profile.profile_id for profile in rest] == [next_id]
        assert await repo.list_heads(user_id="default", project_name="show-a", after_id=None, limit=100) == ()


async def test_command_reuse_conflicts_without_disclosing_foreign_project_receipt(session_factory):
    original = await publish(session_factory, make_profile())
    context = CommandContext(command_id=COMMAND, user_id="u1", project_name="foreign", actor_id="human-a")
    async with session_factory() as session:
        repo = OpportunityProfileRepository(session)
        with pytest.raises(OpportunityError) as foreign:
            await repo.get_command_receipt(context=context, operation=OPERATION, request_digest=original.request_digest)
        assert foreign.value.code is StopCode.M9_COMMAND_REPLAY_CONFLICT
        assert str(foreign.value) == "M9_COMMAND_REPLAY_CONFLICT"
        with pytest.raises(OpportunityError) as changed:
            await repo.get_command_receipt(
                context=context.model_copy(update={"project_name": "show-a"}),
                operation=OPERATION,
                request_digest="sha256:" + "b" * 64,
            )
        assert changed.value.code is StopCode.M9_COMMAND_REPLAY_CONFLICT
    assert await row_counts(session_factory) == (1, 1, 1, 1)


async def test_stale_head_cas_rolls_back_an_already_staged_revision(session_factory):
    await publish(session_factory, make_profile())

    async def stale_append():
        async with session_factory() as session, session.begin():
            repo = OpportunityProfileRepository(session)
            await repo.stage_profile(make_profile(revision=2))
            await repo.stage_head(
                user_id="u1",
                project_name="show-a",
                head=OpportunityCohortProfileHead(profile_id=ID, current_revision=2, head_version=3),
                expected_head_version=2,
            )

    with pytest.raises(OpportunityError) as stale:
        await stale_append()
    assert stale.value.code is StopCode.M9_STALE_HEAD
    assert await row_counts(session_factory) == (1, 1, 1, 1)


@pytest.mark.parametrize(
    ("field", "value"), [("payload_json", {"cohort_id": "forged"}), ("custodian_evidence_digest", "sha256:" + "b" * 64)]
)
async def test_reads_recompute_the_complete_profile_not_only_stored_digest_columns(session_factory, field, value):
    await publish(session_factory, make_profile())
    async with session_factory() as session, session.begin():
        await session.execute(update(M9CohortProfileModel).values({field: value}))
    async with session_factory() as session:
        with pytest.raises(OpportunityError) as corrupt:
            await OpportunityProfileRepository(session).get_exact(
                user_id="u1", project_name="show-a", profile_id=ID, revision=1
            )
        assert corrupt.value.code is StopCode.M9_REQUIRED_EVIDENCE_MISSING


@pytest.mark.parametrize("schema_source", ["orm", "migration"])
async def test_append_parent_cannot_be_null_even_when_contract_validation_is_bypassed(session_factory, schema_source):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import IntegrityError

    from tests.integration.lib.db.migrations.test_alembic_m9_foundation import migration

    profile = make_profile(revision=2)
    values = profile.model_dump(mode="python", exclude={"payload"})
    values.update(parent_revision=None, payload_json=profile.payload.model_dump(mode="json"))
    async with session_factory() as session:
        if schema_source == "migration":
            module = migration()
            connection = await session.connection()

            def rebuild(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    module.downgrade()
                    module.upgrade()

            await connection.run_sync(rebuild)
        session.add(M9CohortProfileModel(**values))
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


async def test_receipt_ref_cannot_substitute_a_different_valid_profile(session_factory):
    first = await publish(session_factory, make_profile())
    await publish(session_factory, make_profile(profile_id=OTHER), command_id=OTHER)
    async with session_factory() as session, session.begin():
        await session.execute(
            update(M9CommandReceiptModel)
            .where(M9CommandReceiptModel.command_id == COMMAND)
            .values(result_ref=f"{OTHER}:1:1")
        )
    context = CommandContext(command_id=COMMAND, user_id="u1", project_name="show-a", actor_id="human-a")
    async with session_factory() as session:
        with pytest.raises(OpportunityError) as corrupt:
            await OpportunityProfileRepository(session).get_command_receipt(
                context=context, operation=OPERATION, request_digest=first.request_digest
            )
        assert corrupt.value.code is StopCode.M9_REQUIRED_EVIDENCE_MISSING


async def test_command_uuid_is_actor_scoped_even_within_one_owner_and_project(session_factory):
    first = await publish(session_factory, make_profile())
    second = await publish(session_factory, make_profile(profile_id=OTHER, actor_id="human-b"), actor_id="human-b")
    assert first.command_id == second.command_id == COMMAND
    assert first.profile.profile_id != second.profile.profile_id
    assert await row_counts(session_factory) == (2, 2, 2, 2)


async def test_database_driver_failures_do_not_expose_profile_payload_in_exception_paths(session_factory):
    import traceback

    from r2.contracts.opportunity import CanonicalJsonObject

    canary = "m9-profile-payload-private-canary"
    original = make_profile(actor_id="x" * 256)
    payload = original.payload.model_copy(
        update={"freshness_policy": CanonicalJsonObject.model_validate({"private": canary})}
    )
    shell = original.model_copy(update={"payload": payload, "payload_digest": digest_cohort_profile_payload(payload)})
    profile = shell.model_copy(update={"profile_digest": digest_cohort_profile(shell)})

    async def persist():
        async with OpportunityUnitOfWork(session_factory).transaction() as repo:
            await repo.stage_profile(profile)

    with pytest.raises(OpportunityError) as safe:
        await persist()
    assert safe.value.code is StopCode.M9_REQUIRED_EVIDENCE_MISSING
    assert canary not in "".join(traceback.format_exception(safe.value))
    assert await row_counts(session_factory) == (0, 0, 0, 0)
