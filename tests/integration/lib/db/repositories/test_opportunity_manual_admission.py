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


@pytest.mark.parametrize("boundary", ["attach", "claim"])
async def test_native_blocking_contenders_preserve_one_admission_or_dispatch_winner(session_factory, boundary):
    import asyncio

    from sqlalchemy import text

    if boundary == "attach":
        command, descriptor, _grant, running = await start_manual(session_factory)
        publication = publication_for(command, descriptor, running)
        async with session_factory() as session, session.begin():
            ready = await manual_repo(session).reserve(publication.request, expected_attempt_version=2)
    else:
        command, publication, ready = await ready_manual(session_factory)
    holder, contender = session_factory(), session_factory()
    task = None
    try:
        await holder.begin()
        holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
        if boundary == "attach":
            winner = await manual_repo(holder).attach(publication, expected_envelope_version=1)
        else:
            winner = await manual_repo(holder).claim_dispatch(
                ready.request.attempt_id, expected_attempt_version=2, expected_envelope_version=2
            )
        await contender.begin()
        contender_pid = await contender.scalar(text("SELECT pg_backend_pid()"))

        async def compete():
            if boundary == "attach":
                return await manual_repo(contender).attach(publication, expected_envelope_version=1)
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
        if boundary == "attach":
            assert await task == winner
        else:
            with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
                await task
        await contender.rollback()
        async with session_factory() as session:
            retained = await manual_repo(session).get_envelope(ready.request.attempt_id)
            if boundary == "attach":
                assert retained == winner
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
