"""Protocol selection preserves the existing authoritative command and state guards."""

from __future__ import annotations

import importlib
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel
from r2.contracts.opportunity import AttemptState
from r2.opportunity.errors import OpportunityError
from tests.integration.lib.db.repositories.test_opportunity_acquisition import prepare_attempt, unit_of_work


def manual_module() -> Any:
    return importlib.import_module("lib.db.repositories.opportunity_manual_admission")


async def synthetic_policy_identity():
    from tests.integration.lib.db.repositories.test_opportunity_profiles import make_profile

    payload = make_profile().payload
    return payload.creative_profile_id, payload.creative_profile_version, payload.creative_policy_pack_digest


def manual_repo(session, *, project="show-a", policy=synthetic_policy_identity):
    return manual_module().ManualAdmissionRepository(
        session, user_id="u1", project_name=project, policy_identity=policy
    )


async def manual_subject(factory, *, host_policy=False):
    from lib.db.repositories.opportunity import OpportunityProfileRepository
    from r2.contracts.opportunity import CommandContext, OpportunityCohortProfileHead, SourceQueryHead
    from r2.contracts.opportunity_acquisition_v2 import AcquireSourceQueryV2
    from r2.opportunity.digests import (
        digest_capability_evaluation,
        digest_capability_grant,
        digest_condition_evidence,
        digest_source_query,
    )
    from r2.opportunity.manual_admission import ManualBindingDescriptor
    from tests.integration.lib.db.repositories.test_opportunity_acquisition import fixture_query
    from tests.unit.r2.opportunity.test_manual_admission import descriptor_data

    manual_module()
    from r2.opportunity.digests import digest_cohort_profile, digest_cohort_profile_payload
    from tests.integration.lib.db.repositories.test_opportunity_profiles import make_profile

    profile = make_profile()
    payload = profile.payload.model_copy(
        update={
            "source_rules": tuple(
                rule.model_copy(update={"allowed_data_classes": ("manual-excerpt", "manual-public-metadata")})
                for rule in profile.payload.source_rules
            )
        }
    )
    if host_policy:
        from r2.advanced_creative.lineage import project_profile

        identity = project_profile(())
        payload = payload.model_copy(
            update={
                "creative_profile_id": identity[0],
                "creative_profile_version": identity[1],
                "creative_policy_pack_digest": identity[2],
            }
        )
    profile = profile.model_copy(update={"payload": payload, "payload_digest": digest_cohort_profile_payload(payload)})
    profile = profile.model_copy(update={"profile_digest": digest_cohort_profile(profile)})
    grant, evaluation, query = await fixture_query(factory, profile=profile)
    async with factory() as session, session.begin():
        now = await OpportunityProfileRepository(session).database_time()
    grant = grant.model_copy(
        update={
            "issued_at": now - timedelta(minutes=1),
            "refresh_after": now + timedelta(hours=1),
            "expires_at": now + timedelta(hours=1),
            "policy_documents": tuple(
                d.model_copy(
                    update={
                        "assessed_at": now - timedelta(minutes=2),
                        "effective_at": now - timedelta(minutes=2),
                        "expires_at": now + timedelta(hours=1),
                    }
                )
                for d in grant.policy_documents
            ),
        }
    )
    grant = grant.model_copy(update={"grant_digest": digest_capability_grant(grant)})
    evaluation = evaluation.model_copy(
        update={
            "grant_digest": grant.grant_digest,
            "evaluated_at": now - timedelta(seconds=1),
            "expires_at": now + timedelta(hours=1),
        }
    )
    evaluation = evaluation.model_copy(
        update={
            "condition_evidence_digest": digest_condition_evidence(
                grant_id=grant.grant_id,
                grant_version=grant.grant_version,
                grant_digest=grant.grant_digest,
                condition_evidence=evaluation.condition_evidence,
            )
        }
    )
    evaluation = evaluation.model_copy(
        update={"evaluation_digest": digest_capability_evaluation(evaluation, actor_id="human-a")}
    )
    query = query.model_copy(
        update={
            "capability_grant_digest": grant.grant_digest,
            "capability_evaluation_digest": evaluation.evaluation_digest,
            "created_at": now,
        }
    )
    query = query.model_copy(update={"query_digest": digest_source_query(query)})
    async with unit_of_work(factory).transaction() as tx:
        await tx.capabilities.consume(grant, evaluation, actor_id="human-a")
        await tx.profiles.stage_head(
            user_id="u1",
            project_name="show-a",
            head=OpportunityCohortProfileHead(profile_id=query.cohort_profile_id, current_revision=1, head_version=1),
            expected_head_version=None,
        )
        await tx.queries.append(query)
        await tx.queries.stage_head(
            SourceQueryHead(query_id=query.query_id, current_revision=1, head_version=1), expected_head_version=None
        )
    command = AcquireSourceQueryV2(
        protocol_version="m9.acquisition.v2",
        context=CommandContext(
            user_id="u1", project_name="show-a", actor_id="human-a", command_id="019a0000-0000-7000-8000-000000000051"
        ),
        query_id=query.query_id,
        query_revision=1,
        query_digest=query.query_digest,
        expected_query_head_version=1,
    )
    return command, ManualBindingDescriptor.model_validate(descriptor_data()), grant


async def start_manual(factory):
    command, descriptor, grant = await manual_subject(factory)
    async with factory() as session, session.begin():
        repo = manual_repo(session)
        planned, created = await repo.prepare(
            command, attempt_id="019a0000-0000-7000-8000-000000000052", descriptor=descriptor
        )
        assert created
        running = await repo.start(planned.attempt_id, expected_attempt_version=1)
    return command, descriptor, grant, running


def publication_for(command, descriptor, running, *, suffix="one"):
    from r2.opportunity.manual_admission import AdmissionRequest, PublishedAdmission
    from tests.unit.r2.opportunity.test_manual_admission import object_data

    data = object_data()
    data["original_clocks"][0].update(
        captured_at=running.started_at,
        refresh_due_at=running.started_at + timedelta(seconds=30),
        retention_due_at=running.started_at + timedelta(seconds=90),
    )
    data.update(
        payload_ref="opaque-payload-" + suffix,
        integrity_ref="opaque-integrity-" + suffix,
        attestation_ref="opaque-seal-" + suffix,
    )
    request = AdmissionRequest(
        context=command.context,
        request_digest=running.request_digest,
        query_id=command.query_id,
        query_revision=1,
        query_digest=command.query_digest,
        attempt_id=running.attempt_id,
        attempt_version=running.attempt_version,
        descriptor=descriptor,
        opaque_upload_id="opaque-upload-" + suffix,
        upload_version=1,
        publication_key="opaque-publication-" + suffix,
        data_rules=data["data_rules"],
        original_clocks=data["original_clocks"],
    )
    return PublishedAdmission(
        request=request,
        publication_key=request.publication_key,
        claim_ref="opaque-claim-" + suffix,
        upload_version=1,
        objects=(data,),
    )


async def ready_manual(factory):
    command, descriptor, _grant, running = await start_manual(factory)
    publication = publication_for(command, descriptor, running)
    async with factory() as session, session.begin():
        reserved = await manual_repo(session).reserve(publication.request, expected_attempt_version=2)
    async with factory() as session, session.begin():
        ready = await manual_repo(session).attach(publication, expected_envelope_version=reserved.version)
    return command, publication, ready


async def test_prepare_replay_freezes_full_request_and_descriptor_before_admission(session_factory):
    command, descriptor, _grant = await manual_subject(session_factory)
    async with session_factory() as session, session.begin():
        original, created = await manual_repo(session).prepare(
            command, attempt_id="019a0000-0000-7000-8000-000000000052", descriptor=descriptor
        )
        assert created
        assert original.state == "PLANNED"
    async with session_factory() as session, session.begin():
        replay, created = await manual_repo(session).prepare(
            command, attempt_id="019a0000-0000-7000-8000-000000000053", descriptor=descriptor
        )
        assert not created
        assert replay == original

    async def changed_binding():
        async with session_factory() as session, session.begin():
            await manual_repo(session).prepare(
                command,
                attempt_id=original.attempt_id,
                descriptor=descriptor.model_copy(update={"decoder_digest": "sha256:" + "b" * 64}),
            )

    with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
        await changed_binding()


async def test_reserve_and_attach_ack_loss_replay_keeps_first_ready_anchor(session_factory):
    _command, publication, ready = await ready_manual(session_factory)
    assert ready.phase == "READY"
    assert ready.version == 2
    assert ready.admitted_at >= publication.request.original_clocks[0].captured_at
    async with session_factory() as session, session.begin():
        replay = await manual_repo(session).attach(publication, expected_envelope_version=1)
        assert replay == ready
        assert await manual_repo(session).get_envelope(ready.request.attempt_id) == ready

    async def replacement():
        async with session_factory() as session, session.begin():
            await manual_repo(session).attach(
                publication.model_copy(update={"claim_ref": "replacement-claim"}), expected_envelope_version=1
            )

    with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
        await replacement()


async def test_claim_is_granted_only_once_and_read_permit_keeps_original_bounds(session_factory):
    _command, _publication, ready = await ready_manual(session_factory)
    async with session_factory() as session, session.begin():
        claim = await manual_repo(session).claim_dispatch(
            ready.request.attempt_id, expected_attempt_version=2, expected_envelope_version=2
        )
        assert claim.attempt_version == 3
        assert claim.envelope_version == 3

    async def redispatch():
        async with session_factory() as session, session.begin():
            await manual_repo(session).claim_dispatch(
                ready.request.attempt_id, expected_attempt_version=2, expected_envelope_version=2
            )

    with pytest.raises(OpportunityError):
        await redispatch()
    async with session_factory() as session, session.begin():
        permit = await manual_repo(session).begin_read(
            ready.request.attempt_id, expected_envelope_version=3, operational=True
        )
        assert permit.expires_at <= ready.deadlines.refresh_due_at
        assert permit.access_deadline == min(ready.deadlines.refresh_due_at, ready.deadlines.retention_due_at)
        await manual_repo(session).release_read(permit.lease_id)
        await manual_repo(session).release_read(permit.lease_id)


async def test_reserve_rollback_leaves_no_intent_or_envelope(session_factory):
    from lib.db.models.opportunity_manual_admission import M9ManualAdmissionModel, M9ManualPublicationIntentModel

    command, descriptor, _grant, running = await start_manual(session_factory)
    publication = publication_for(command, descriptor, running)

    async def interrupted():
        async with session_factory() as session, session.begin():
            await manual_repo(session).reserve(publication.request, expected_attempt_version=2)
            raise RuntimeError("injected before commit")

    with pytest.raises(RuntimeError, match="injected before commit"):
        await interrupted()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9ManualAdmissionModel)) == 0
        assert await session.scalar(select(func.count()).select_from(M9ManualPublicationIntentModel)) == 0


@pytest.mark.parametrize("fault", ["body", "digest", "intent", "binding"])
async def test_typed_envelope_read_refuses_corrupt_authority_even_with_recomputed_hash(session_factory, fault):
    from lib.db.models.opportunity_manual_admission import M9ManualAdmissionModel, M9ManualPublicationIntentModel
    from r2.opportunity.manual_admission import admission_metadata_digest

    _, publication, ready = await ready_manual(session_factory)
    body = ready.model_dump(mode="json")
    table = M9ManualAdmissionModel
    if fault == "binding":
        body["request"]["descriptor"]["decoder_digest"] = "sha256:" + "b" * 64
    elif fault == "body":
        body["objects"][0]["payload_ref"] = "substituted-payload"
    elif fault == "intent":
        table = M9ManualPublicationIntentModel
        body["objects"][0]["attestation_ref"] = "substituted-seal"
    body["metadata_digest"] = admission_metadata_digest(body)
    async with session_factory() as session, session.begin():
        await session.execute(
            update(table).values(
                body_json=body, metadata_digest="sha256:" + "0" * 64 if fault == "digest" else body["metadata_digest"]
            )
        )
    async with session_factory() as session:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await manual_repo(session).get_envelope(publication.request.attempt_id)


async def test_operational_write_has_no_default_policy_authority(session_factory):
    command, descriptor, _grant = await manual_subject(session_factory)

    async def unavailable():
        async with session_factory() as session, session.begin():
            await manual_repo(session, policy=None).prepare(
                command, attempt_id="019a0000-0000-7000-8000-000000000052", descriptor=descriptor
            )

    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        await unavailable()


async def test_attempt_reader_rejects_transition_clock_column_tamper(session_factory):
    command, _descriptor, _grant, running = await start_manual(session_factory)
    async with session_factory() as session, session.begin():
        await session.execute(
            update(M9AcquisitionAttemptModel).values(transitioned_at=running.started_at + timedelta(seconds=1))
        )
    async with session_factory() as session, session.begin():
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await manual_repo(session).get_for_command(command)


async def test_read_lease_release_revalidates_full_sql_binding(session_factory):
    from lib.db.models.opportunity_manual_admission import M9ManualReadLeaseModel

    _, _, ready = await ready_manual(session_factory)
    async with session_factory() as session, session.begin():
        permit = await manual_repo(session).begin_read(
            ready.request.attempt_id, expected_envelope_version=2, operational=True
        )
    async with session_factory() as session, session.begin():
        await session.execute(
            update(M9ManualReadLeaseModel)
            .where(M9ManualReadLeaseModel.lease_id == permit.lease_id)
            .values(operational=False)
        )

    async def release_corrupt():
        async with session_factory() as session, session.begin():
            await manual_repo(session).release_read(permit.lease_id)

    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await release_corrupt()


@pytest.mark.parametrize("fault", ["missing", "version", "phase"])
async def test_read_admission_requires_its_complete_active_upload_lease(session_factory, fault):
    from sqlalchemy import delete

    from lib.db.models.opportunity_manual_admission import M9ManualUploadLeaseModel

    _, _, ready = await ready_manual(session_factory)
    async with session_factory() as session, session.begin():
        if fault == "missing":
            await session.execute(delete(M9ManualUploadLeaseModel))
        else:
            await session.execute(
                update(M9ManualUploadLeaseModel).values(
                    **({"version": 2} if fault == "version" else {"state": "SPENT"})
                )
            )

    async def read_corrupt():
        async with session_factory() as session, session.begin():
            await manual_repo(session).begin_read(
                ready.request.attempt_id, expected_envelope_version=2, operational=True
            )

    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await read_corrupt()


@pytest.mark.parametrize("boundary", ["attach", "claim", "checkpoint"])
async def test_native_blocking_contenders_preserve_one_admission_or_dispatch_winner(session_factory, boundary):
    import asyncio

    from sqlalchemy import text

    publication = None
    checkpoint = None
    if boundary == "attach":
        command, descriptor, _grant, running = await start_manual(session_factory)
        publication = publication_for(command, descriptor, running)
        async with session_factory() as session, session.begin():
            ready = await manual_repo(session).reserve(publication.request, expected_attempt_version=2)
    elif boundary == "checkpoint":
        command, ready, checkpoint = await checkpoint_subject(session_factory)
    else:
        command, publication, ready = await ready_manual(session_factory)
    holder, contender = session_factory(), session_factory()
    task = None
    try:
        await holder.begin()
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        if boundary == "attach":
            assert publication is not None
            winner = await manual_repo(holder).attach(publication, expected_envelope_version=1)
        elif boundary == "checkpoint":
            assert checkpoint is not None
            winner = await manual_repo(holder).append_checkpoint(
                ready.request.attempt_id, checkpoint, expected_attempt_version=3
            )
        else:
            winner = await manual_repo(holder).claim_dispatch(
                ready.request.attempt_id, expected_attempt_version=2, expected_envelope_version=2
            )
        await contender.begin()
        contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))

        async def compete():
            if boundary == "attach":
                assert publication is not None
                return await manual_repo(contender).attach(publication, expected_envelope_version=1)
            if boundary == "checkpoint":
                assert checkpoint is not None
                return await manual_repo(contender).append_checkpoint(
                    ready.request.attempt_id, checkpoint, expected_attempt_version=3
                )
            return await manual_repo(contender).claim_dispatch(
                ready.request.attempt_id, expected_attempt_version=2, expected_envelope_version=2
            )

        task = asyncio.create_task(compete())
        async with asyncio.timeout(10):
            while True:
                async with session_factory() as observer:
                    blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": contender_pid})
                if holder_pid in blockers:
                    break
                if task.done():
                    pytest.fail("contender did not wait on the retained command guard")
        assert not task.done()
        await holder.commit()
        if boundary in ("attach", "checkpoint"):
            assert await task == winner
        else:
            with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
                await task
        await contender.rollback()
        async with session_factory() as session:
            retained = await manual_repo(session).get_envelope(ready.request.attempt_id)
            if boundary == "attach":
                assert retained == winner
            elif boundary == "checkpoint":
                assert await manual_repo(session).list_checkpoints(ready.request.attempt_id) == (winner,)
            else:
                assert retained.dispatch_claim == winner
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await contender.close()
        await holder.close()


async def test_command_lock_plan_refuses_inversion_even_before_row_locks(session_factory):
    command, _, _ = await manual_subject(session_factory)
    earlier = command.context.model_copy(update={"command_id": "019a0000-0000-7000-8000-000000000050"})
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        await repo.lock_commands((command.context,))
        with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
            await repo.lock_commands((earlier,))


@pytest.mark.parametrize("foreign_project", [False, True])
async def test_v2_prepare_never_reallocates_a_legacy_command_across_projects(session_factory, foreign_project):
    from r2.contracts.opportunity import CommandContext
    from r2.contracts.opportunity_acquisition_v2 import AcquireSourceQueryV2
    from r2.opportunity.manual_admission import ManualBindingDescriptor
    from tests.unit.r2.opportunity.test_manual_admission import descriptor_data

    legacy = await prepare_attempt(session_factory)
    project = "other-project" if foreign_project else "show-a"
    command = AcquireSourceQueryV2(
        protocol_version="m9.acquisition.v2",
        context=CommandContext(
            user_id="u1", project_name=project, actor_id=legacy.actor_id, command_id=legacy.command_id
        ),
        query_id=legacy.query_id,
        query_revision=legacy.query_revision,
        query_digest=legacy.query_digest,
        expected_query_head_version=1,
    )
    descriptor = ManualBindingDescriptor.model_validate({**descriptor_data(), "project_name": project})

    async def conflicting():
        async with session_factory() as session, session.begin():
            await manual_repo(session, project=project, policy=None).prepare(
                command, attempt_id="019a0000-0000-7000-8000-000000000053", descriptor=descriptor
            )

    with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
        await conflicting()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == 1


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


@pytest.mark.parametrize(
    ("uncertain_state", "deadline_kind"),
    [("RUNNING", "refresh"), ("OUTCOME_UNKNOWN", "refresh"), ("NEEDS_OPERATOR", "retention")],
)
async def test_expiry_commits_exact_zero_snapshot_receipt_and_preserves_unknown_quota(
    session_factory, uncertain_state, deadline_kind
):
    import asyncio

    from lib.db.models.opportunity import M9CommandReceiptModel, M9EventModel
    from lib.db.repositories.opportunity import OpportunityProfileRepository
    from r2.opportunity.manual_admission import AdmissionRequest, PublishedAdmission

    command, descriptor, _grant, running = await start_manual(session_factory)
    publication = publication_for(command, descriptor, running)
    deadline = running.started_at + timedelta(seconds=5)
    clock_update = {"refresh_due_at": deadline}
    if deadline_kind == "retention":
        clock_update["retention_due_at"] = deadline
    clocks = [c.model_copy(update=clock_update) for c in publication.request.original_clocks]
    request = AdmissionRequest.model_validate({**publication.request.model_dump(), "original_clocks": clocks})
    objects = tuple(obj.model_copy(update={"original_clocks": tuple(clocks)}) for obj in publication.objects)
    publication = PublishedAdmission.model_validate(
        {**publication.model_dump(), "request": request, "objects": objects}
    )
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        await repo.reserve(request, expected_attempt_version=2)
        ready = await repo.attach(publication, expected_envelope_version=1)
        claim = await repo.claim_dispatch(running.attempt_id, expected_attempt_version=2, expected_envelope_version=2)
    expected_version = claim.attempt_version
    if uncertain_state != "RUNNING":
        async with session_factory() as session, session.begin():
            unknown = await manual_repo(session).mark_outcome_unknown(
                running.attempt_id, expected_attempt_version=expected_version
            )
            expected_version = unknown.attempt_version
    if uncertain_state == "NEEDS_OPERATOR":
        async with session_factory() as session, session.begin():
            operator = await manual_repo(session).mark_needs_operator(
                running.attempt_id, expected_attempt_version=expected_version
            )
            expected_version = operator.attempt_version

    async def too_early():
        async with session_factory() as session, session.begin():
            await manual_repo(session).close_expired(
                running.attempt_id, expected_attempt_version=expected_version, resolver_id="fixture-expiry"
            )

    with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
        await too_early()
    async with asyncio.timeout(10):
        async with session_factory() as session:
            while True:
                now = await OpportunityProfileRepository(session).database_time()
                if now >= ready.deadlines.refresh_due_at:
                    break
                arrived = asyncio.Event()
                timer = asyncio.get_running_loop().call_later(
                    (ready.deadlines.refresh_due_at - now).total_seconds(), arrived.set
                )
                try:
                    await arrived.wait()
                finally:
                    timer.cancel()
    if uncertain_state == "RUNNING":

        async def interrupted_expiry():
            async with session_factory() as session, session.begin():
                await manual_repo(session, policy=None).close_expired(
                    running.attempt_id, expected_attempt_version=expected_version, resolver_id="rolled-back-resolver"
                )
                raise RuntimeError("rollback expiry")

        with pytest.raises(RuntimeError, match="rollback expiry"):
            await interrupted_expiry()
        async with session_factory() as session:
            retained = await manual_repo(session).get_attempt(running.attempt_id)
            assert retained.state == "RUNNING"
            assert retained.attempt_version == expected_version
            assert await manual_repo(session).get_receipt(command) is None
            assert await session.scalar(select(func.count()).select_from(M9EventModel)) == 0
        from sqlalchemy import text

        holder, contender = session_factory(), session_factory()
        task = None
        try:
            await holder.begin()
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            receipt = await manual_repo(holder, policy=None).close_expired(
                running.attempt_id, expected_attempt_version=expected_version, resolver_id="fixture-expiry"
            )
            await contender.begin()
            contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))
            task = asyncio.create_task(
                manual_repo(contender, policy=None).close_expired(
                    running.attempt_id, expected_attempt_version=expected_version, resolver_id="competing-resolver"
                )
            )
            async with asyncio.timeout(10):
                while True:
                    async with session_factory() as observer:
                        blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": contender_pid})
                    if holder_pid in blockers:
                        break
                    if task.done():
                        pytest.fail("expiry contender did not wait on the command guard")
            await holder.commit()
            replay = await task
            assert replay.model_dump_json() == receipt.model_dump_json()
            await contender.commit()
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await contender.close()
            await holder.close()
    else:
        async with session_factory() as session, session.begin():
            receipt = await manual_repo(session, policy=None).close_expired(
                running.attempt_id, expected_attempt_version=expected_version, resolver_id="fixture-expiry"
            )
    async with session_factory() as session:
        assert receipt.state == "EXPIRED_UNRECOVERABLE"
        assert receipt.outcome_reason == "RESPONSE_OUTCOME_UNKNOWN"
        assert receipt.snapshot_ids == ()
        assert receipt.quota_disposition == "POSSIBLY_CONSUMED"
        assert receipt.quota_units_observed is None
        assert receipt.closure.original_deadline == deadline
        assert receipt.closure.closed_at >= deadline
        assert receipt.closure.disposition == (
            "ADMISSION_RETENTION_EXPIRED" if deadline_kind == "retention" else "OPERATIONAL_EVIDENCE_STALE"
        )
    async with session_factory() as session, session.begin():
        replay = await manual_repo(session, policy=None).close_expired(
            running.attempt_id, expected_attempt_version=expected_version, resolver_id="different-resolver"
        )
        assert replay.model_dump_json() == receipt.model_dump_json()
        assert await manual_repo(session).get_receipt(command) == receipt
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(M9CommandReceiptModel)
                .where(M9CommandReceiptModel.operation == "acquire")
            )
            == 1
        )
        events = (
            await session.scalars(
                select(M9EventModel)
                .where(M9EventModel.aggregate_id == running.attempt_id)
                .order_by(M9EventModel.aggregate_revision)
            )
        ).all()
        assert [e.event_kind for e in events][-1] == "MANUAL_ATTEMPT_EXPIRED"
        assert "MANUAL_ATTEMPT_OUTCOME_UNKNOWN" in [e.event_kind for e in events]

    if uncertain_state == "NEEDS_OPERATOR":
        async with session_factory() as session, session.begin():
            await session.execute(
                update(M9CommandReceiptModel)
                .where(M9CommandReceiptModel.operation == "acquire")
                .values(result_digest="sha256:" + "f" * 64)
            )
        async with session_factory() as session:
            with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
                await manual_repo(session).get_receipt(command)


async def test_prepare_refuses_query_contract_different_from_frozen_manual_binding(session_factory):
    from lib.db.models.opportunity_acquisition import M9SourceQueryModel
    from r2.contracts.opportunity import SourceQuery
    from r2.opportunity.digests import digest_source_query

    command, descriptor, _ = await manual_subject(session_factory)
    async with session_factory() as session, session.begin():
        row = (await session.scalars(select(M9SourceQueryModel))).one()
        query = SourceQuery.model_validate(row.body_json).model_copy(
            update={"source_contract_version": "manual-import.future"}
        )
        query = query.model_copy(update={"query_digest": digest_source_query(query)})
        row.body_json = query.model_dump(mode="json")
        row.query_digest = query.query_digest
    command = command.model_copy(update={"query_digest": query.query_digest})

    async def wrong_contract():
        async with session_factory() as session, session.begin():
            await manual_repo(session).prepare(
                command, attempt_id="019a0000-0000-7000-8000-000000000052", descriptor=descriptor
            )

    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await wrong_contract()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == 0


async def checkpoint_subject(factory, *, dispatch=True, native=False, refresh_seconds=None):
    from r2.contracts.opportunity import EvidenceDataClassClock, SnapshotPage
    from r2.opportunity.acquisition import PageCheckpoint

    if native or refresh_seconds is not None:
        from r2.opportunity.manual_admission import AdmissionRequest, PublishedAdmission

        command, descriptor, _, running = await start_manual(factory)
        publication = publication_for(command, descriptor, running)
        if refresh_seconds is not None:
            clocks = tuple(
                c.model_copy(update={"refresh_due_at": running.started_at + timedelta(seconds=refresh_seconds)})
                for c in publication.request.original_clocks
            )
            request = AdmissionRequest.model_validate({**publication.request.model_dump(), "original_clocks": clocks})
            objects = tuple(o.model_copy(update={"original_clocks": clocks}) for o in publication.objects)
            publication = PublishedAdmission.model_validate(
                {**publication.model_dump(), "request": request, "objects": objects}
            )
        if native:
            native_object = publication.objects[0].model_copy(
                update={
                    "payload_ref": "original-native",
                    "integrity_ref": "original-native-proof",
                    "attestation_ref": "original-native-seal",
                    "evidence_kind": "native-field-1",
                }
            )
            publication = PublishedAdmission.model_validate(
                {
                    **publication.model_dump(),
                    "objects": (*publication.objects, native_object),
                }
            )
        async with factory() as session, session.begin():
            repo = manual_repo(session)
            await repo.reserve(publication.request, expected_attempt_version=2)
            envelope = await repo.attach(publication, expected_envelope_version=1)
    else:
        command, _, envelope = await ready_manual(factory)
    if dispatch:
        async with factory() as session, session.begin():
            repo = manual_repo(session)
            await repo.claim_dispatch(
                envelope.request.attempt_id, expected_attempt_version=2, expected_envelope_version=2
            )
            envelope = await repo.get_envelope(envelope.request.attempt_id)
    obj = next(o for o in envelope.objects if o.evidence_kind == "raw-page")
    clocks = tuple(
        EvidenceDataClassClock(
            data_class=c.data_class,
            captured_at=envelope.admitted_at,
            refresh_due_at=c.refresh_due_at,
            retention_due_at=c.retention_due_at,
        )
        for c in envelope.deadlines.classes
        if c.data_class in obj.data_classes
    )
    page = SnapshotPage(
        ordinal=1,
        request_cursor_digest=None,
        response_cursor_digest=None,
        provider_request_id=None,
        payload_ref=obj.payload_ref,
        payload_integrity_ref=obj.integrity_ref,
        retained_source_payload_digest=obj.retained_material_digest,
        raw_media_type="application/json",
        raw_size_bytes=2,
        data_classes=obj.data_classes,
        data_class_clocks=clocks,
        record_count=1,
        captured_at=envelope.admitted_at,
        missing_reason=None,
    )
    checkpoint = PageCheckpoint(
        page=page,
        source_identity_refs=("identity:original",),
        quota_units_observed=None,
        next_cursor_ref=None,
        next_cursor_integrity_ref=None,
        terminal_page=True,
        provider_observed_at=None,
    )
    if native:
        from r2.opportunity.acquisition import NativeFieldMaterial

        checkpoint = checkpoint.model_copy(
            update={
                "native_fields": (
                    NativeFieldMaterial(
                        source_identity_ref="identity:original",
                        native_field_name="excerpt",
                        native_field_definition="Original text.",
                        native_field_version="manual.v1",
                        data_class="manual-excerpt",
                        unit=None,
                        window_start=None,
                        window_end=None,
                        missing_reason=None,
                        normalization_version="manual.v1",
                        material_ref="original-native",
                        material_integrity_ref="original-native-proof",
                        value_ref="original-native",
                        value_integrity_ref="original-native-proof",
                        retained_normalized_value_digest=None,
                    ),
                )
            }
        )
    return command, envelope, checkpoint


@pytest.mark.parametrize("native", [False, True])
async def test_v2_checkpoint_reopen_and_ack_replay_preserve_original_admission_clocks(session_factory, native):
    command, envelope, checkpoint = await checkpoint_subject(session_factory, native=native)
    attempt_id = envelope.request.attempt_id
    async with session_factory() as session, session.begin():
        retained = await manual_repo(session).append_checkpoint(attempt_id, checkpoint, expected_attempt_version=3)
        assert retained == checkpoint
    async with session_factory() as session, session.begin():
        repo = manual_repo(session, policy=None)
        assert await repo.list_checkpoints(attempt_id) == (checkpoint,)
        assert await repo.append_checkpoint(attempt_id, checkpoint, expected_attempt_version=2) == checkpoint
        assert (await repo.get_envelope(attempt_id)).admitted_at == envelope.admitted_at
    async with unit_of_work(session_factory).transaction() as tx:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await tx.pages.list_for_attempt(attempt_id)
    async with session_factory() as session, session.begin():
        assert await manual_repo(session).get_for_command(command) is not None


@pytest.mark.parametrize("fault", ["ref", "clock", "proof", "cursor", "native", "version", "unclaimed"])
async def test_v2_checkpoint_rejects_unbound_material_or_execution(session_factory, fault):
    from r2.opportunity.acquisition import NativeFieldMaterial

    _, envelope, checkpoint = await checkpoint_subject(session_factory, dispatch=fault != "unclaimed")
    page = checkpoint.page
    if fault == "ref":
        page = page.model_copy(update={"payload_ref": "replacement-payload"})
    elif fault == "proof":
        page = page.model_copy(update={"retained_source_payload_digest": "sha256:" + "a" * 64})
    elif fault == "clock":
        clocks = []
        for clock in page.data_class_clocks:
            assert clock.retention_due_at is not None
            clocks.append(clock.model_copy(update={"retention_due_at": clock.retention_due_at + timedelta(seconds=1)}))
        page = page.model_copy(update={"data_class_clocks": tuple(clocks)})
    elif fault == "cursor":
        page = page.model_copy(update={"request_cursor_digest": "sha256:" + "a" * 64})
    elif fault == "native":
        field = NativeFieldMaterial(
            source_identity_ref="identity:original",
            native_field_name="excerpt",
            native_field_definition="Original text.",
            native_field_version="manual.v1",
            data_class="manual-excerpt",
            unit=None,
            window_start=None,
            window_end=None,
            missing_reason=None,
            normalization_version="manual.v1",
            material_ref="replacement-native",
            material_integrity_ref="replacement-native-proof",
            value_ref="replacement-native",
            value_integrity_ref="replacement-native-proof",
            retained_normalized_value_digest=None,
        )
        checkpoint = checkpoint.model_copy(update={"native_fields": (field,)})
    checkpoint = checkpoint.model_copy(update={"page": page})

    async def unbound():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_checkpoint(
                envelope.request.attempt_id,
                checkpoint,
                expected_attempt_version=17 if fault == "version" else 2 if fault == "unclaimed" else 3,
            )

    with pytest.raises(OpportunityError):
        await unbound()
    async with session_factory() as session:
        assert await manual_repo(session).list_checkpoints(envelope.request.attempt_id) == ()


async def test_v2_checkpoint_rolls_back_with_application_transaction(session_factory):
    _, envelope, checkpoint = await checkpoint_subject(session_factory)

    async def interrupted():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_checkpoint(
                envelope.request.attempt_id, checkpoint, expected_attempt_version=3
            )
            raise RuntimeError("before checkpoint commit")

    with pytest.raises(RuntimeError, match="before checkpoint commit"):
        await interrupted()
    async with session_factory() as session:
        assert await manual_repo(session).list_checkpoints(envelope.request.attempt_id) == ()


@pytest.mark.parametrize("fault", ["page_column", "rehashed_original_refs"])
async def test_v2_checkpoint_reader_revalidates_independent_original_admission(session_factory, fault):
    from lib.db.models.opportunity_acquisition import M9SnapshotPageModel
    from r2.opportunity.manual_admission import admission_metadata_digest

    _, envelope, checkpoint = await checkpoint_subject(session_factory)
    attempt_id = envelope.request.attempt_id
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_checkpoint(attempt_id, checkpoint, expected_attempt_version=3)
    async with session_factory() as session, session.begin():
        row = (await session.scalars(select(M9SnapshotPageModel))).one()
        if fault == "page_column":
            row.body_json = {**row.body_json, "raw_size_bytes": 3}
        else:
            import copy

            metadata = copy.deepcopy(row.checkpoint_json["metadata"])
            metadata["admission"]["objects"][0]["payload_ref"] = "replacement-raw"
            metadata["admission"]["metadata_digest"] = admission_metadata_digest(metadata["admission"])
            metadata["checkpoint"]["page"]["payload_ref"] = "replacement-raw"
            module = manual_module()
            row.checkpoint_json = module._pack(module._CheckpointRecord.model_validate(metadata))
            row.body_json = metadata["checkpoint"]["page"]
    async with session_factory() as session:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await manual_repo(session).list_checkpoints(attempt_id)


@pytest.mark.parametrize("claim", ["none", "quota", "provider_time"])
async def test_v2_reconstruction_checkpoint_preserves_uncertainty_without_provider_claims(session_factory, claim):
    _, envelope, checkpoint = await checkpoint_subject(session_factory)
    attempt_id = envelope.request.attempt_id
    async with session_factory() as session, session.begin():
        await manual_repo(session).mark_outcome_unknown(attempt_id, expected_attempt_version=3)
    if claim == "quota":
        checkpoint = checkpoint.model_copy(update={"quota_units_observed": 0})
    elif claim == "provider_time":
        checkpoint = checkpoint.model_copy(update={"provider_observed_at": envelope.admitted_at})

    async def stage():
        async with session_factory() as session, session.begin():
            return await manual_repo(session).append_checkpoint(attempt_id, checkpoint, expected_attempt_version=4)

    if claim == "none":
        assert await stage() == checkpoint
    else:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await stage()
    async with session_factory() as session:
        attempt = await manual_repo(session).get_attempt(attempt_id)
        assert attempt.state == "OUTCOME_UNKNOWN"
        assert attempt.quota_disposition == "POSSIBLY_CONSUMED"
        assert attempt.quota_units_observed is None


async def test_v2_checkpoint_paused_before_sql_erasure_fence_cannot_publish(session_factory):
    from lib.db.models.opportunity_acquisition import M9SnapshotPageModel
    from lib.db.models.opportunity_manual_admission import M9ManualAdmissionModel
    from lib.db.repositories.opportunity import OpportunityProfileRepository

    _, envelope, checkpoint = await checkpoint_subject(session_factory)
    async with session_factory() as session, session.begin():
        now = await OpportunityProfileRepository(session).database_time()
        await session.execute(update(M9ManualAdmissionModel).values(erasure_fenced_at=now, erasure_version=1))

    async def resume():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_checkpoint(
                envelope.request.attempt_id, checkpoint, expected_attempt_version=3
            )

    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await resume()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SnapshotPageModel)) == 0


async def test_v2_checkpoint_prepared_before_expiry_cannot_publish_after_closure(session_factory):
    import asyncio

    from lib.db.models.opportunity_acquisition import M9SnapshotPageModel
    from lib.db.repositories.opportunity import OpportunityProfileRepository

    command, envelope, checkpoint = await checkpoint_subject(session_factory, refresh_seconds=5)
    async with asyncio.timeout(10):
        async with session_factory() as session:
            while True:
                now = await OpportunityProfileRepository(session).database_time()
                if now >= envelope.deadlines.refresh_due_at:
                    break
                arrived = asyncio.Event()
                timer = asyncio.get_running_loop().call_later(
                    (envelope.deadlines.refresh_due_at - now).total_seconds(), arrived.set
                )
                try:
                    await arrived.wait()
                finally:
                    timer.cancel()
    async with session_factory() as session, session.begin():
        receipt = await manual_repo(session, policy=None).close_expired(
            envelope.request.attempt_id, expected_attempt_version=3, resolver_id="expiry-winner"
        )

    async def resume():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_checkpoint(
                envelope.request.attempt_id, checkpoint, expected_attempt_version=3
            )

    with pytest.raises(OpportunityError):
        await resume()
    async with session_factory() as session, session.begin():
        assert await session.scalar(select(func.count()).select_from(M9SnapshotPageModel)) == 0
        assert await manual_repo(session).get_receipt(command) == receipt


async def snapshot_subject(
    factory, *, origin="SOURCE_RESPONSE_VERIFIED", persist_checkpoint=True, missing=False, refresh_seconds=None
):
    from r2.contracts.opportunity import SourceSnapshot
    from r2.contracts.opportunity_acquisition_v2 import SnapshotOriginV2, SnapshotProvenanceV2
    from r2.opportunity.digests import digest_source_snapshot

    command, envelope, checkpoint = await checkpoint_subject(factory, native=True, refresh_seconds=refresh_seconds)
    if missing:
        from r2.contracts.opportunity import MissingReason

        field = checkpoint.native_fields[0].model_copy(
            update={
                "value_ref": None,
                "value_integrity_ref": None,
                "missing_reason": MissingReason.NOT_RETURNED,
            }
        )
        checkpoint = checkpoint.model_copy(update={"native_fields": (field,)})
    async with factory() as session, session.begin():
        repo = manual_repo(session)
        if persist_checkpoint:
            await repo.append_checkpoint(envelope.request.attempt_id, checkpoint, expected_attempt_version=3)
        if origin == "LOCAL_ADMISSION_RECONSTRUCTION":
            await repo.mark_outcome_unknown(envelope.request.attempt_id, expected_attempt_version=3)
        attempt = await repo.get_attempt(envelope.request.attempt_id)
        query = await repo.queries.get_exact(command.query_id, command.query_revision)
        now = await repo.profiles.database_time()
        assert attempt.started_at is not None
        snapshot = SourceSnapshot(
            snapshot_id="019a0000-0000-7000-8000-000000000071",
            revision=1,
            parent_revision=None,
            user_id=command.context.user_id,
            project_name=command.context.project_name,
            query_id=query.query_id,
            query_revision=query.revision,
            query_digest=query.query_digest,
            attempt_id=attempt.attempt_id,
            source_kind=query.source_kind,
            source_contract_version=query.source_contract_version,
            source_identity_refs=checkpoint.source_identity_refs,
            pages=(checkpoint.page,),
            coverage_state="COMPLETE_WITHIN_DECLARED_BOUNDS",
            requested_record_limit=query.max_records,
            returned_record_count=checkpoint.page.record_count,
            coverage_note="Original admitted manual material.",
            provider_observed_at=None,
            capture_started_at=attempt.started_at,
            capture_completed_at=envelope.admitted_at,
            adapter_version=attempt.adapter_version,
            capability_grant_digest=query.capability_grant_digest,
            capability_evaluation_digest=query.capability_evaluation_digest,
            snapshot_digest="sha256:" + "0" * 64,
            created_at=now,
        )
        snapshot = snapshot.model_copy(update={"snapshot_digest": digest_source_snapshot(snapshot)})
        provenance = SnapshotProvenanceV2(
            snapshot_id=snapshot.snapshot_id,
            snapshot_digest=snapshot.snapshot_digest,
            attempt_id=attempt.attempt_id,
            attempt_version=attempt.attempt_version,
            admission_metadata_digest=envelope.metadata_digest,
            origin=SnapshotOriginV2(origin),
            admitted_at=envelope.admitted_at,
            response_recorded_at=now if origin == "SOURCE_RESPONSE_VERIFIED" else None,
        )
    return command, envelope, snapshot, provenance


@pytest.mark.parametrize("origin", ["SOURCE_RESPONSE_VERIFIED", "LOCAL_ADMISSION_RECONSTRUCTION"])
async def test_v2_snapshot_persists_exact_original_admission_and_provenance(session_factory, origin):
    command, envelope, snapshot, provenance = await snapshot_subject(session_factory, origin=origin)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_snapshot(
            snapshot, provenance, expected_attempt_version=provenance.attempt_version
        )
    async with session_factory() as session, session.begin():
        repo = manual_repo(session, policy=None)
        assert await repo.get_snapshot(snapshot.snapshot_id, 1) == (snapshot, provenance)
        assert await repo.get_snapshot_for_attempt(snapshot.attempt_id) == (snapshot, provenance)
        await repo.append_snapshot(snapshot, provenance, expected_attempt_version=1)
        assert (await repo.get_envelope(snapshot.attempt_id)).admitted_at == envelope.admitted_at
    async with unit_of_work(session_factory).transaction() as tx:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await tx.snapshots.get_exact(snapshot.snapshot_id, 1)
    async with session_factory() as session, session.begin():
        assert await manual_repo(session).get_for_command(command) is not None


@pytest.mark.parametrize(
    "fault",
    [
        "anchor",
        "query",
        "adapter",
        "admission",
        "version",
        "provenance_version",
        "future",
        "uncheckpointed",
        "local_provider_time",
        "verified_unknown",
    ],
)
async def test_v2_snapshot_refuses_unbound_snapshot_or_provenance(session_factory, fault):
    from lib.db.models.opportunity_acquisition import M9SourceSnapshotModel
    from r2.contracts.opportunity_acquisition_v2 import SnapshotProvenanceV2
    from r2.opportunity.digests import digest_source_snapshot

    local = fault in ("local_provider_time", "verified_unknown")
    _, envelope, snapshot, provenance = await snapshot_subject(
        session_factory,
        origin="LOCAL_ADMISSION_RECONSTRUCTION" if local else "SOURCE_RESPONSE_VERIFIED",
        persist_checkpoint=fault != "uncheckpointed",
    )
    if fault == "anchor":
        snapshot = snapshot.model_copy(update={"capture_completed_at": snapshot.created_at})
    elif fault == "query":
        snapshot = snapshot.model_copy(update={"query_digest": "sha256:" + "b" * 64})
    elif fault == "adapter":
        snapshot = snapshot.model_copy(update={"adapter_version": "replacement-decoder"})
    elif fault == "future":
        snapshot = snapshot.model_copy(update={"created_at": snapshot.created_at + timedelta(minutes=1)})
    elif fault == "local_provider_time":
        snapshot = snapshot.model_copy(update={"provider_observed_at": envelope.admitted_at})
    snapshot = snapshot.model_copy(update={"snapshot_digest": digest_source_snapshot(snapshot)})
    body = {**provenance.model_dump(), "snapshot_digest": snapshot.snapshot_digest}
    if fault == "admission":
        body["admission_metadata_digest"] = "sha256:" + "b" * 64
    elif fault == "provenance_version":
        body["attempt_version"] = 1
    elif fault == "verified_unknown":
        body.update(origin="SOURCE_RESPONSE_VERIFIED", response_recorded_at=snapshot.created_at)
    provenance = SnapshotProvenanceV2.model_validate(body)

    async def unbound():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_snapshot(
                snapshot, provenance, expected_attempt_version=17 if fault == "version" else (4 if local else 3)
            )

    with pytest.raises(OpportunityError):
        await unbound()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SourceSnapshotModel)) == 0


async def test_v2_snapshot_and_its_audit_rollback_together(session_factory):
    from lib.db.models.opportunity import M9EventModel
    from lib.db.models.opportunity_acquisition import M9SourceSnapshotModel

    _, _, snapshot, provenance = await snapshot_subject(session_factory)

    async def interrupted():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_snapshot(snapshot, provenance, expected_attempt_version=3)
            raise RuntimeError("before snapshot commit")

    with pytest.raises(RuntimeError, match="before snapshot commit"):
        await interrupted()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SourceSnapshotModel)) == 0
        assert await session.scalar(select(func.count()).select_from(M9EventModel)) == 0


@pytest.mark.parametrize("fault", ["scalar", "rehashed_body", "audit"])
async def test_v2_snapshot_reader_checks_independent_audit_and_columns(session_factory, fault):
    from lib.db.models.opportunity import M9EventModel
    from lib.db.models.opportunity_acquisition import M9SourceSnapshotModel
    from r2.opportunity.acquisition_v2_digests import digest_snapshot_provenance_v2
    from r2.opportunity.digests import digest_source_snapshot

    _, _, snapshot, provenance = await snapshot_subject(session_factory)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_snapshot(snapshot, provenance, expected_attempt_version=3)
    async with session_factory() as session, session.begin():
        row = (await session.scalars(select(M9SourceSnapshotModel))).one()
        if fault == "scalar":
            row.snapshot_digest = "sha256:" + "a" * 64
        elif fault == "audit":
            event = (await session.scalars(select(M9EventModel))).one()
            event.payload_digest = "sha256:" + "a" * 64
        else:
            module = manual_module()
            stored = module._unpack(module._SnapshotRecord, row.body_json)
            replacement = snapshot.model_copy(update={"coverage_note": "Replaced metadata."})
            replacement = replacement.model_copy(update={"snapshot_digest": digest_source_snapshot(replacement)})
            changed_provenance = provenance.model_copy(update={"snapshot_digest": replacement.snapshot_digest})
            row.body_json = module._pack(
                stored.model_copy(
                    update={
                        "snapshot": replacement,
                        "provenance": changed_provenance,
                        "provenance_digest": digest_snapshot_provenance_v2(changed_provenance),
                    }
                )
            )
            row.snapshot_digest = replacement.snapshot_digest
    async with session_factory() as session:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await manual_repo(session).get_snapshot(snapshot.snapshot_id)


@pytest.mark.parametrize("changed", [False, True])
async def test_v2_snapshot_native_contender_retains_one_snapshot_and_audit(session_factory, changed):
    import asyncio

    from sqlalchemy import text

    from lib.db.models.opportunity import M9EventModel
    from lib.db.models.opportunity_acquisition import M9SourceSnapshotModel
    from r2.opportunity.digests import digest_source_snapshot

    _, _, snapshot, provenance = await snapshot_subject(session_factory)
    candidate = snapshot
    candidate_provenance = provenance
    if changed:
        candidate = snapshot.model_copy(update={"snapshot_id": "019a0000-0000-7000-8000-000000000072"})
        candidate = candidate.model_copy(update={"snapshot_digest": digest_source_snapshot(candidate)})
        candidate_provenance = provenance.model_copy(
            update={"snapshot_id": candidate.snapshot_id, "snapshot_digest": candidate.snapshot_digest}
        )
    holder, contender = session_factory(), session_factory()
    task = None
    try:
        await holder.begin()
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        await manual_repo(holder).append_snapshot(snapshot, provenance, expected_attempt_version=3)
        await contender.begin()
        contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(
            manual_repo(contender).append_snapshot(candidate, candidate_provenance, expected_attempt_version=3)
        )
        async with asyncio.timeout(10):
            while True:
                async with session_factory() as observer:
                    blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": contender_pid})
                if holder_pid in blockers:
                    break
                if task.done():
                    pytest.fail("snapshot contender did not wait on the command guard")
        assert not task.done()
        await holder.commit()
        if changed:
            with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
                await task
        else:
            assert await task is None
        await contender.commit()
        async with session_factory() as session:
            assert await manual_repo(session).get_snapshot_for_attempt(snapshot.attempt_id) == (snapshot, provenance)
            assert await session.scalar(select(func.count()).select_from(M9SourceSnapshotModel)) == 1
            assert await session.scalar(select(func.count()).select_from(M9EventModel)) == 1
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await contender.close()
        await holder.close()


async def observation_subject(factory, *, missing=False):
    from r2.contracts.opportunity import NormalizedSourceObservation
    from r2.opportunity.digests import digest_source_observation

    _, _, snapshot, provenance = await snapshot_subject(factory, missing=missing)
    async with factory() as session, session.begin():
        repo = manual_repo(session)
        await repo.append_snapshot(snapshot, provenance, expected_attempt_version=3)
        checkpoint = (await repo.list_checkpoints(snapshot.attempt_id))[0]
    field = checkpoint.native_fields[0]
    observation = NormalizedSourceObservation.model_validate(
        {
            **field.model_dump(exclude={"material_ref", "material_integrity_ref"}),
            "observation_id": "019a0000-0000-7000-8000-000000000081",
            "revision": 1,
            "parent_revision": None,
            "user_id": snapshot.user_id,
            "project_name": snapshot.project_name,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_digest": snapshot.snapshot_digest,
            "page_ordinal": 1,
            "source_kind": snapshot.source_kind,
            "payload_integrity_ref": checkpoint.page.payload_integrity_ref,
            "retained_source_payload_digest": checkpoint.page.retained_source_payload_digest,
            "observation_digest": "sha256:" + "0" * 64,
            "observed_at": checkpoint.page.captured_at,
        }
    )
    return snapshot, observation.model_copy(update={"observation_digest": digest_source_observation(observation)})


async def test_v2_observation_retains_native_lineage_correction_and_exact_replay(session_factory):
    from r2.opportunity.digests import digest_source_observation

    _, observation = await observation_subject(session_factory)
    corrected = observation.model_copy(update={"revision": 2, "parent_revision": 1})
    corrected = corrected.model_copy(update={"observation_digest": digest_source_observation(corrected)})
    for value in (observation, corrected):
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_observation(value, expected_attempt_version=3)
    async with session_factory() as session, session.begin():
        repo = manual_repo(session, policy=None)
        assert await repo.get_observation(observation.observation_id, 1) == observation
        assert await repo.get_current_observation(observation.observation_id) == corrected
        await repo.append_observation(observation, expected_attempt_version=1)
        await repo.append_observation(corrected, expected_attempt_version=1)
    async with unit_of_work(session_factory).transaction() as tx:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await tx.observations.get_exact(observation.observation_id, 1)


@pytest.mark.parametrize(
    "fault",
    [
        "identity",
        "field",
        "definition",
        "field_version",
        "class",
        "unit",
        "window",
        "missing",
        "normalization",
        "value",
        "proof",
        "raw",
        "clock",
        "digest",
        "version",
        "revision",
    ],
)
async def test_v2_observation_refuses_unbound_native_metadata(session_factory, fault):
    from lib.db.models.opportunity_acquisition import M9SourceObservationModel
    from r2.contracts.opportunity import MissingReason
    from r2.opportunity.digests import digest_source_observation

    _, observation = await observation_subject(session_factory)
    changes = {
        "identity": {"source_identity_ref": "identity:replacement"},
        "field": {"native_field_name": "replacement"},
        "definition": {"native_field_definition": "Replacement definition."},
        "field_version": {"native_field_version": "replacement.v2"},
        "class": {"data_class": "manual-public-metadata"},
        "unit": {"unit": "count"},
        "window": {"window_start": observation.observed_at, "window_end": observation.observed_at},
        "missing": {"value_ref": None, "value_integrity_ref": None, "missing_reason": MissingReason.NOT_RETURNED},
        "normalization": {"normalization_version": "replacement.v2"},
        "value": {"value_ref": "replacement", "value_integrity_ref": "replacement-proof"},
        "proof": {"retained_normalized_value_digest": "sha256:" + "b" * 64},
        "raw": {"payload_integrity_ref": "replacement-raw"},
        "clock": {"observed_at": observation.observed_at + timedelta(seconds=1)},
        "digest": {"observation_digest": "sha256:" + "b" * 64},
        "version": {},
        "revision": {"revision": 2, "parent_revision": 1},
    }
    observation = observation.model_copy(update=changes[fault])
    if fault != "digest":
        observation = observation.model_copy(update={"observation_digest": digest_source_observation(observation)})

    async def unbound():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_observation(
                observation, expected_attempt_version=17 if fault == "version" else 3
            )

    with pytest.raises(OpportunityError):
        await unbound()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SourceObservationModel)) == 0


async def additional_observation_snapshot(factory, snapshot):
    from r2.contracts.opportunity import EvidenceDataClassClock
    from r2.contracts.opportunity_acquisition_v2 import SnapshotProvenanceV2
    from r2.opportunity.digests import digest_source_snapshot
    from r2.opportunity.manual_admission import PublishedAdmission

    async with factory() as session, session.begin():
        repo = manual_repo(session)
        row = await repo._row(snapshot.attempt_id)
        original = await repo._record(row)
        old_checkpoint = (await repo.list_checkpoints(snapshot.attempt_id))[0]
        command = original.command.model_copy(
            update={
                "context": original.command.context.model_copy(
                    update={"command_id": "019a0000-0000-7000-8000-000000000091"}
                )
            }
        )
        attempt, _ = await repo.prepare(
            command, attempt_id="019a0000-0000-7000-8000-000000000092", descriptor=original.descriptor
        )
        running = await repo.start(attempt.attempt_id, expected_attempt_version=1)
    publication = publication_for(command, original.descriptor, running, suffix="two")
    native = publication.objects[0].model_copy(
        update={
            "payload_ref": "second-native",
            "integrity_ref": "second-native-proof",
            "attestation_ref": "second-native-seal",
            "evidence_kind": "native-field-1",
        }
    )
    publication = PublishedAdmission.model_validate(
        {**publication.model_dump(), "objects": (*publication.objects, native)}
    )
    async with factory() as session, session.begin():
        repo = manual_repo(session)
        await repo.reserve(publication.request, expected_attempt_version=2)
        await repo.attach(publication, expected_envelope_version=1)
    async with factory() as session, session.begin():
        repo = manual_repo(session)
        await repo.claim_dispatch(attempt.attempt_id, expected_attempt_version=2, expected_envelope_version=2)
        envelope = await repo.get_envelope(attempt.attempt_id)
        obj = publication.objects[0]
        page = old_checkpoint.page.model_copy(
            update={
                "payload_ref": obj.payload_ref,
                "payload_integrity_ref": obj.integrity_ref,
                "captured_at": envelope.admitted_at,
                "data_class_clocks": tuple(
                    EvidenceDataClassClock(
                        data_class=c.data_class,
                        captured_at=envelope.admitted_at,
                        refresh_due_at=c.refresh_due_at,
                        retention_due_at=c.retention_due_at,
                    )
                    for c in envelope.deadlines.classes
                ),
            }
        )
        field = old_checkpoint.native_fields[0].model_copy(
            update={
                "material_ref": native.payload_ref,
                "material_integrity_ref": native.integrity_ref,
                "value_ref": native.payload_ref,
                "value_integrity_ref": native.integrity_ref,
            }
        )
        await repo.append_checkpoint(
            attempt.attempt_id,
            old_checkpoint.model_copy(update={"page": page, "native_fields": (field,)}),
            expected_attempt_version=3,
        )
        now = await repo.profiles.database_time()
        replacement = snapshot.model_copy(
            update={
                "snapshot_id": "019a0000-0000-7000-8000-000000000093",
                "attempt_id": attempt.attempt_id,
                "pages": (page,),
                "capture_started_at": running.started_at,
                "capture_completed_at": envelope.admitted_at,
                "created_at": now,
            }
        )
        replacement = replacement.model_copy(update={"snapshot_digest": digest_source_snapshot(replacement)})
        provenance = SnapshotProvenanceV2(
            snapshot_id=replacement.snapshot_id,
            snapshot_digest=replacement.snapshot_digest,
            attempt_id=attempt.attempt_id,
            attempt_version=3,
            admission_metadata_digest=envelope.metadata_digest,
            origin="SOURCE_RESPONSE_VERIFIED",
            admitted_at=envelope.admitted_at,
            response_recorded_at=now,
        )
        await repo.append_snapshot(replacement, provenance, expected_attempt_version=3)
    return replacement


@pytest.mark.parametrize("reverse", [False, True])
async def test_v2_observation_cross_attempt_correction_prelocks_complete_command_plan(session_factory, reverse):
    from r2.opportunity.digests import digest_source_observation

    first_snapshot, observation = await observation_subject(session_factory)
    second_snapshot = await additional_observation_snapshot(session_factory, first_snapshot)
    second_page = second_snapshot.pages[0]
    second = observation.model_copy(
        update={
            "snapshot_id": second_snapshot.snapshot_id,
            "snapshot_digest": second_snapshot.snapshot_digest,
            "value_ref": "second-native",
            "value_integrity_ref": "second-native-proof",
            "payload_integrity_ref": second_page.payload_integrity_ref,
            "observed_at": second_page.captured_at,
        }
    )
    first, correction = (second, observation) if reverse else (observation, second)
    first = first.model_copy(update={"observation_digest": digest_source_observation(first)})
    correction = correction.model_copy(update={"revision": 2, "parent_revision": 1})
    correction = correction.model_copy(update={"observation_digest": digest_source_observation(correction)})
    for value in (first, correction):
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_observation(value, expected_attempt_version=3)
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        assert await repo.get_current_observation(first.observation_id) == correction
        state = session.info["m9_manual_command_plan"]
        assert {key[-1] for key in state["keys"]} == {
            "019a0000-0000-7000-8000-000000000051",
            "019a0000-0000-7000-8000-000000000091",
        }
        assert await repo.get_observation(first.observation_id, 1) == first


@pytest.mark.parametrize("fault", ["scalar", "rehashed_body", "head", "audit"])
async def test_v2_observation_reader_revalidates_body_head_and_independent_audit(session_factory, fault):
    from lib.db.models.opportunity import M9EventModel
    from lib.db.models.opportunity_acquisition import M9ObservationHeadModel, M9SourceObservationModel

    _, observation = await observation_subject(session_factory)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_observation(observation, expected_attempt_version=3)
    async with session_factory() as session, session.begin():
        row = (await session.scalars(select(M9SourceObservationModel))).one()
        if fault == "scalar":
            row.observation_digest = "sha256:" + "a" * 64
        elif fault == "head":
            head = (await session.scalars(select(M9ObservationHeadModel))).one()
            head.head_version = 2
        elif fault == "audit":
            event = (
                await session.scalars(
                    select(M9EventModel).where(M9EventModel.event_kind == "MANUAL_OBSERVATION_STORED")
                )
            ).one()
            event.payload_digest = "sha256:" + "a" * 64
        else:
            module = manual_module()
            stored = module._unpack(module._ObservationRecord, row.body_json)
            row.body_json = module._pack(
                stored.model_copy(update={"stored_at": stored.stored_at + timedelta(microseconds=1)})
            )
    async with session_factory() as session:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await manual_repo(session).get_current_observation(observation.observation_id)


async def test_v2_observation_head_body_and_audit_roll_back_together(session_factory):
    from lib.db.models.opportunity import M9EventModel
    from lib.db.models.opportunity_acquisition import M9ObservationHeadModel, M9SourceObservationModel

    _, observation = await observation_subject(session_factory)

    async def interrupted():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_observation(observation, expected_attempt_version=3)
            raise RuntimeError("before observation commit")

    with pytest.raises(RuntimeError, match="before observation commit"):
        await interrupted()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SourceObservationModel)) == 0
        assert await session.scalar(select(func.count()).select_from(M9ObservationHeadModel)) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(M9EventModel)
                .where(M9EventModel.event_kind == "MANUAL_OBSERVATION_STORED")
            )
            == 0
        )


async def test_v2_observation_preserves_sealed_explicit_missingness_without_a_value(session_factory):
    from r2.contracts.opportunity import MissingReason

    _, observation = await observation_subject(session_factory, missing=True)
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        await repo.append_observation(observation, expected_attempt_version=3)
    async with session_factory() as session:
        retained = await manual_repo(session).get_current_observation(observation.observation_id)
        assert retained == observation
        assert retained.missing_reason == MissingReason.NOT_RETURNED
        assert retained.value_ref is None
        assert retained.retained_normalized_value_digest is None


async def test_v2_observation_prepared_before_sql_erasure_fence_cannot_publish(session_factory):
    from lib.db.models.opportunity_acquisition import M9SourceObservationModel
    from lib.db.models.opportunity_manual_admission import M9ManualAdmissionModel

    _, observation = await observation_subject(session_factory)
    async with session_factory() as session, session.begin():
        now = await manual_repo(session).profiles.database_time()
        await session.execute(update(M9ManualAdmissionModel).values(erasure_fenced_at=now, erasure_version=1))

    async def resume():
        async with session_factory() as session, session.begin():
            await manual_repo(session).append_observation(observation, expected_attempt_version=3)

    with pytest.raises(OpportunityError):
        await resume()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SourceObservationModel)) == 0


@pytest.mark.parametrize("cross_attempt", [False, True])
@pytest.mark.parametrize("changed", [False, True])
async def test_v2_observation_native_contender_serializes_correction_and_replay(
    session_factory, changed, cross_attempt
):
    import asyncio

    from sqlalchemy import text

    from lib.db.models.opportunity import M9EventModel
    from lib.db.models.opportunity_acquisition import M9SourceObservationModel
    from r2.opportunity.digests import digest_source_observation

    snapshot, observation = await observation_subject(session_factory)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_observation(observation, expected_attempt_version=3)
    updates = {"revision": 2, "parent_revision": 1}
    if cross_attempt:
        second = await additional_observation_snapshot(session_factory, snapshot)
        updates.update(
            snapshot_id=second.snapshot_id,
            snapshot_digest=second.snapshot_digest,
            value_ref="second-native",
            value_integrity_ref="second-native-proof",
            payload_integrity_ref=second.pages[0].payload_integrity_ref,
            observed_at=second.pages[0].captured_at,
        )
    corrected = observation.model_copy(update=updates)
    corrected = corrected.model_copy(update={"observation_digest": digest_source_observation(corrected)})
    candidate = corrected
    if changed:
        candidate = corrected.model_copy(
            update={"value_ref": "replacement", "value_integrity_ref": "replacement-proof"}
        )
        candidate = candidate.model_copy(update={"observation_digest": digest_source_observation(candidate)})
    holder, contender = session_factory(), session_factory()
    task = None
    try:
        await holder.begin()
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        await manual_repo(holder).append_observation(corrected, expected_attempt_version=3)
        await contender.begin()
        contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(manual_repo(contender).append_observation(candidate, expected_attempt_version=3))
        async with asyncio.timeout(10):
            while True:
                async with session_factory() as observer:
                    blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": contender_pid})
                if holder_pid in blockers:
                    break
                if task.done():
                    pytest.fail("observation contender did not wait on the original command plan")
        assert not task.done()
        await holder.commit()
        # Planning saw revision one before waiting; the new head must force a retry.
        with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
            await task
        await contender.rollback()
        async with session_factory() as session, session.begin():
            if changed:
                with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
                    await manual_repo(session).append_observation(candidate, expected_attempt_version=3)
            else:
                await manual_repo(session).append_observation(candidate, expected_attempt_version=1)
        async with session_factory() as session:
            assert await manual_repo(session).get_current_observation(observation.observation_id) == corrected
            assert await session.scalar(select(func.count()).select_from(M9SourceObservationModel)) == 2
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(M9EventModel)
                    .where(M9EventModel.event_kind == "MANUAL_OBSERVATION_STORED")
                )
                == 2
            )
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await contender.close()
        await holder.close()


async def await_original_refresh(factory, envelope):
    import asyncio

    assert envelope.deadlines is not None
    deadline = envelope.deadlines.refresh_due_at
    assert deadline is not None
    async with asyncio.timeout(10):
        async with factory() as session:
            while await manual_repo(session).profiles.database_time() < deadline:
                # A fresh DB statement establishes expiry; the timer only paces polling.
                arrived = asyncio.Event()
                timer = asyncio.get_running_loop().call_later(0.05, arrived.set)
                try:
                    await arrived.wait()
                finally:
                    timer.cancel()


@pytest.mark.parametrize("origin", ["SOURCE_RESPONSE_VERIFIED", "LOCAL_ADMISSION_RECONSTRUCTION"])
async def test_v2_expiry_preserves_existing_snapshot_provenance_and_unknown_outcome(session_factory, origin):
    from r2.opportunity.acquisition_v2_digests import digest_snapshot_provenance_v2

    command, envelope, snapshot, provenance = await snapshot_subject(session_factory, origin=origin, refresh_seconds=5)
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        await repo.append_snapshot(snapshot, provenance, expected_attempt_version=provenance.attempt_version)
        original_checkpoints = await repo.list_checkpoints(snapshot.attempt_id)
    await await_original_refresh(session_factory, envelope)
    async with session_factory() as session, session.begin():
        receipt = await manual_repo(session, policy=None).close_expired(
            snapshot.attempt_id, expected_attempt_version=provenance.attempt_version, resolver_id="snapshot-expiry"
        )
    assert receipt.state == "EXPIRED_UNRECOVERABLE"
    assert receipt.outcome_reason == "RESPONSE_OUTCOME_UNKNOWN"
    assert receipt.snapshot_ids == (snapshot.snapshot_id,)
    assert receipt.snapshot_digests == (snapshot.snapshot_digest,)
    assert receipt.snapshot_provenance_digests == (digest_snapshot_provenance_v2(provenance),)
    assert receipt.quota_disposition == "POSSIBLY_CONSUMED"
    assert receipt.quota_units_observed is None
    async with session_factory() as session, session.begin():
        repo = manual_repo(session, policy=None)
        assert await repo.get_receipt(command) == receipt
        assert await repo.close_expired(snapshot.attempt_id, expected_attempt_version=1, resolver_id="late") == receipt
        assert await repo.get_snapshot_for_attempt(snapshot.attempt_id) == (snapshot, provenance)
        assert await repo.list_checkpoints(snapshot.attempt_id) == original_checkpoints
        await repo.append_snapshot(snapshot, provenance, expected_attempt_version=1)
        assert (await repo.get_envelope(snapshot.attempt_id)).admitted_at == envelope.admitted_at


async def test_v2_expiry_preserves_checkpoints_without_manufacturing_a_snapshot(session_factory):
    from lib.db.models.opportunity_acquisition import M9SourceSnapshotModel

    command, envelope, checkpoint = await checkpoint_subject(session_factory, native=True, refresh_seconds=5)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_checkpoint(
            envelope.request.attempt_id, checkpoint, expected_attempt_version=3
        )
    await await_original_refresh(session_factory, envelope)
    async with session_factory() as session, session.begin():
        receipt = await manual_repo(session, policy=None).close_expired(
            envelope.request.attempt_id, expected_attempt_version=3, resolver_id="checkpoint-expiry"
        )
    assert receipt.snapshot_ids == ()
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        assert await repo.get_receipt(command) == receipt
        assert await repo.list_checkpoints(envelope.request.attempt_id) == (checkpoint,)
        assert await session.scalar(select(func.count()).select_from(M9SourceSnapshotModel)) == 0


async def test_v2_expiry_refuses_to_drop_unverifiable_existing_snapshot(session_factory):
    from lib.db.models.opportunity import M9EventModel

    command, envelope, snapshot, provenance = await snapshot_subject(session_factory, refresh_seconds=5)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_snapshot(snapshot, provenance, expected_attempt_version=3)
        await session.execute(update(M9EventModel).values(payload_digest="sha256:" + "a" * 64))
    await await_original_refresh(session_factory, envelope)

    async def close():
        async with session_factory() as session, session.begin():
            await manual_repo(session, policy=None).close_expired(
                snapshot.attempt_id, expected_attempt_version=3, resolver_id="corrupt"
            )

    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await close()
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        assert (await repo.get_attempt(snapshot.attempt_id)).state == "RUNNING"
        assert await repo.get_receipt(command) is None


async def test_v2_expiry_reader_cannot_drop_retained_snapshot_by_rehashing_receipt(session_factory):
    from lib.db.models.opportunity import M9CommandReceiptModel
    from r2.opportunity.acquisition_v2_digests import digest_acquisition_result_v2

    command, envelope, snapshot, provenance = await snapshot_subject(session_factory, refresh_seconds=5)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_snapshot(snapshot, provenance, expected_attempt_version=3)
    await await_original_refresh(session_factory, envelope)
    async with session_factory() as session, session.begin():
        await manual_repo(session, policy=None).close_expired(
            snapshot.attempt_id, expected_attempt_version=3, resolver_id="original"
        )
    async with session_factory() as session, session.begin():
        module = manual_module()
        row = (await session.scalars(select(M9AcquisitionAttemptModel))).one()
        record = module._unpack(module._AttemptRecord, row.body_json)
        changed = record.receipt.model_copy(
            update={"snapshot_ids": (), "snapshot_digests": (), "snapshot_provenance_digests": ()}
        )
        changed = changed.model_copy(update={"result_digest": digest_acquisition_result_v2(changed)})
        row.body_json = module._pack(record.model_copy(update={"receipt": changed}))
        receipt_row = (await session.scalars(select(M9CommandReceiptModel))).one()
        receipt_row.result_digest = changed.result_digest
    async with session_factory() as session, session.begin():
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await manual_repo(session).get_receipt(command)


async def test_v2_snapshot_expiry_transaction_rollback_preserves_original_attempt_and_audits(session_factory):
    from lib.db.models.opportunity import M9CommandReceiptModel, M9EventModel

    command, envelope, snapshot, provenance = await snapshot_subject(session_factory, refresh_seconds=5)
    async with session_factory() as session, session.begin():
        await manual_repo(session).append_snapshot(snapshot, provenance, expected_attempt_version=3)
    await await_original_refresh(session_factory, envelope)

    async def interrupted():
        async with session_factory() as session, session.begin():
            await manual_repo(session, policy=None).close_expired(
                snapshot.attempt_id, expected_attempt_version=3, resolver_id="rolled-back"
            )
            raise RuntimeError("before expiry snapshot commit")

    with pytest.raises(RuntimeError, match="before expiry snapshot commit"):
        await interrupted()
    async with session_factory() as session, session.begin():
        repo = manual_repo(session)
        attempt = await repo.get_attempt(snapshot.attempt_id)
        assert (attempt.state, attempt.attempt_version) == ("RUNNING", 3)
        assert await repo.get_snapshot(snapshot.snapshot_id) == (snapshot, provenance)
        assert await session.scalar(select(func.count()).select_from(M9CommandReceiptModel)) == 0
        assert await session.scalar(select(func.count()).select_from(M9EventModel)) == 1
        receipt = await repo.close_expired(snapshot.attempt_id, expected_attempt_version=3, resolver_id="committed")
    async with session_factory() as session, session.begin():
        assert await manual_repo(session).get_receipt(command) == receipt
