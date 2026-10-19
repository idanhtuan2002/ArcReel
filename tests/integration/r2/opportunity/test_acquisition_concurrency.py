"""Controlled PostgreSQL races exercise absent attempts and version fences."""

import asyncio

import pytest
from sqlalchemy import func, select, text

from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel
from lib.db.repositories.opportunity_acquisition import OpportunityAcquisitionUnitOfWork
from r2.contracts.opportunity import AttemptState
from r2.opportunity.errors import OpportunityError, StopCode
from tests.integration.lib.db.repositories.test_opportunity_acquisition import (
    planned_attempt,
    prepare_attempt,
    stage_query,
    unit_of_work,
)
from tests.integration.r2.opportunity.test_profile_concurrency import observe_blocked


@pytest.mark.parametrize("mode", ["equal", "divergent", "collision", "foreign"])
async def test_concurrent_prepare_has_one_dispatch_winner_per_full_command_key(session_factory, mode):
    query = await stage_query(session_factory)
    first_attempt = planned_attempt(query)
    second_attempt = first_attempt
    if mode == "divergent":
        second_attempt = first_attempt.model_copy(update={"request_digest": "sha256:" + "b" * 64})
    elif mode == "foreign":
        second_attempt = first_attempt.model_copy(update={"project_name": "foreign"})
    elif mode == "collision":
        second_attempt = first_attempt.model_copy(
            update={
                "command_id": "019a0000-0000-7000-8000-000000000043",
                "attempt_id": "019a0000-0000-7000-8000-000000000044",
            }
        )
    entered, locked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    def collision_key(operation, context):
        return 7, 11

    kwargs = {"guard_key": collision_key} if mode == "collision" else {}

    async def first():
        uow = OpportunityAcquisitionUnitOfWork(session_factory, user_id="u1", project_name="show-a", **kwargs)
        async with uow.transaction() as tx:
            pids["first"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            result = await tx.attempts.prepare(first_attempt)
            locked.set()
            await release.wait()
            return result

    async def second():
        await locked.wait()
        uow = OpportunityAcquisitionUnitOfWork(
            session_factory, user_id="u1", project_name=second_attempt.project_name, **kwargs
        )
        async with uow.transaction() as tx:
            pids["second"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            entered.set()
            return await tx.attempts.prepare(second_attempt)

    tasks = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        await observe_blocked(session_factory, pids["second"], pids["first"])
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert results[0] == (first_attempt, True)
    if mode == "equal":
        assert results[1] == (first_attempt, False)
    elif mode == "collision":
        assert results[1] == (second_attempt, True)
    else:
        assert isinstance(results[1], OpportunityError)
        assert results[1].code == StopCode.M9_COMMAND_REPLAY_CONFLICT
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == (
            2 if mode == "collision" else 1
        )


async def test_concurrent_running_cas_grants_dispatch_once(session_factory):
    attempt = await prepare_attempt(session_factory)
    entered, locked, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pids = {}

    async def first():
        async with unit_of_work(session_factory).transaction() as tx:
            pids["first"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            result = await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
            locked.set()
            await release.wait()
            return result

    async def second():
        await locked.wait()
        async with unit_of_work(session_factory).transaction() as tx:
            pids["second"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            entered.set()
            return await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)

    tasks = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        await observe_blocked(session_factory, pids["second"], pids["first"])
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert results[0].state == AttemptState.RUNNING
    assert results[0].attempt_version == 2
    assert isinstance(results[1], OpportunityError)
    assert results[1].code == StopCode.M9_STALE_HEAD
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.attempts.get_exact(attempt.attempt_id) == results[0]


async def test_observation_reader_does_not_hold_head_while_waiting_for_attempt_lineage(session_factory):
    from tests.integration.lib.db.repositories.test_opportunity_acquisition import stage_snapshot

    snapshot, observation = await stage_snapshot(session_factory)
    entered, release = asyncio.Event(), asyncio.Event()

    async def reader():
        async with unit_of_work(session_factory).transaction() as tx:
            original = tx.observations._validate

            async def pause_before_attempt(value):
                entered.set()
                await release.wait()
                return await original(value)

            tx.observations._validate = pause_before_attempt
            return await tx.observations.get_current(observation.observation_id)

    task = asyncio.create_task(reader())
    try:
        await asyncio.wait_for(entered.wait(), timeout=10)
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.session.execute(text("SET LOCAL lock_timeout='1000ms'"))
            assert await tx.attempts.get_exact(snapshot.attempt_id) is not None
            assert await tx.observations._head(observation.observation_id) is not None
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert results == [observation]


async def test_cross_snapshot_corrections_lock_both_attempts_in_identity_order(session_factory):
    from r2.opportunity.digests import digest_source_observation, digest_source_snapshot
    from tests.integration.lib.db.repositories.test_opportunity_acquisition import (
        checkpoint_fixture,
        observation_fixture,
        snapshot_fixture,
        stage_snapshot,
    )

    first_snapshot, first_observation = await stage_snapshot(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        query = await tx.queries.get_exact(first_snapshot.query_id, first_snapshot.query_revision)
        second_attempt = planned_attempt(query, command_id="019a0000-0000-7000-8000-000000000061").model_copy(
            update={"attempt_id": "019a0000-0000-7000-8000-000000000062"}
        )
        await tx.attempts.prepare(second_attempt)
        running = await tx.attempts.transition(
            second_attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING
        )
        checkpoint = await checkpoint_fixture(tx)
        await tx.pages.append(second_attempt.attempt_id, checkpoint, expected_attempt_version=2)
        second_snapshot = (await snapshot_fixture(tx, running)).model_copy(
            update={"snapshot_id": "019a0000-0000-7000-8000-000000000063"}
        )
        second_snapshot = second_snapshot.model_copy(
            update={"snapshot_digest": digest_source_snapshot(second_snapshot)}
        )
        await tx.snapshots.append(second_snapshot)
        second_observation = observation_fixture(second_snapshot).model_copy(
            update={"observation_id": "019a0000-0000-7000-8000-000000000064"}
        )
        second_observation = second_observation.model_copy(
            update={"observation_digest": digest_source_observation(second_observation)}
        )
        await tx.observations.append(second_observation, expected_head_version=None)
    corrections = []
    for original, target in ((first_observation, second_snapshot), (second_observation, first_snapshot)):
        corrected = original.model_copy(
            update={
                "revision": 2,
                "parent_revision": 1,
                "snapshot_id": target.snapshot_id,
                "snapshot_digest": target.snapshot_digest,
                "payload_integrity_ref": target.pages[0].payload_integrity_ref,
                "observed_at": target.pages[0].captured_at,
            }
        )
        corrections.append(corrected.model_copy(update={"observation_digest": digest_source_observation(corrected)}))
    entered = (asyncio.Event(), asyncio.Event())
    pids = {}

    async def writer(index):
        async with unit_of_work(session_factory).transaction() as tx:
            pids[index] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            entered[index].set()
            await tx.observations.append(corrections[index], expected_head_version=1)

    tasks = ()
    try:
        async with unit_of_work(session_factory).transaction() as gate:
            assert await gate.attempts.get_exact(first_snapshot.attempt_id) is not None
            gate_pid = await gate.session.scalar(text("SELECT pg_backend_pid()"))
            tasks = (asyncio.create_task(writer(0)), asyncio.create_task(writer(1)))
            for index in range(2):
                await asyncio.wait_for(entered[index].wait(), timeout=10)
                async with session_factory() as observer:
                    async with asyncio.timeout(10):
                        while True:
                            pending, seen = [pids[index]], set()
                            while pending:
                                pid = pending.pop()
                                if pid in seen:
                                    continue
                                seen.add(pid)
                                pending.extend(
                                    await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid})
                                )
                            if gate_pid in seen:
                                break
                            await asyncio.sleep(0)
            async with session_factory() as observer, observer.begin():
                row = await observer.scalar(
                    select(M9AcquisitionAttemptModel.attempt_id)
                    .where(
                        M9AcquisitionAttemptModel.attempt_id == second_attempt.attempt_id,
                    )
                    .with_for_update(nowait=True)
                )
                assert row == second_attempt.attempt_id
    finally:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert results == [None, None]
    async with unit_of_work(session_factory).transaction() as tx:
        for corrected in corrections:
            assert await tx.observations.get_current(corrected.observation_id) == corrected


async def acquisition_service_fixture(factory, tmp_path):
    import hashlib
    import importlib
    from datetime import UTC, datetime

    from lib.db.repositories.opportunity import OpportunityUnitOfWork
    from r2.advanced_creative.lineage import host_policy_digest
    from r2.contracts.opportunity import OpportunityCohortProfileHead
    from r2.opportunity.digests import digest_cohort_profile, digest_cohort_profile_payload
    from r2.opportunity.manual_import import ManualImportSource
    from server.services.m9_evidence_store import FileSnapshotEvidenceStore
    from tests.integration.lib.db.repositories.test_opportunity_profiles import make_profile
    from tests.unit.r2.opportunity.test_capabilities import NOW, _resign
    from tests.unit.r2.opportunity.test_manual_import import ORIGIN, UPLOAD, source_inputs

    module = importlib.import_module("r2.opportunity.acquisition")
    assert hasattr(module, "OpportunityAcquisitionService"), "B3 acquisition application is missing"
    from contextlib import asynccontextmanager
    from contextvars import ContextVar

    from server.services.opportunity import HostAcquisitionUnitOfWork

    active_transactions = ContextVar("m9_test_active_transactions", default=0)

    class ObservedStore(HostAcquisitionUnitOfWork):
        lose_ack = False

        @property
        def active_transactions(self):
            return active_transactions.get()

        @asynccontextmanager
        async def transaction(self):
            token = active_transactions.set(active_transactions.get() + 1)
            try:
                async with super().transaction() as tx:
                    yield tx
                if self.lose_ack:
                    self.lose_ack = False
                    raise ConnectionError("injected lost commit acknowledgement")
            finally:
                active_transactions.reset(token)

    store = ObservedStore(factory, user_id="u1", project_name="show-a")
    profile = make_profile()
    rule = profile.payload.source_rules[0].model_copy(
        update={
            "allowed_data_classes": ("manual-excerpt", "manual-public-metadata"),
        }
    )
    payload = profile.payload.model_copy(
        update={
            "creative_profile_id": "arcreel.host",
            "creative_profile_version": "1",
            "creative_policy_pack_digest": host_policy_digest(),
            "source_rules": (rule,),
        }
    )
    profile = profile.model_copy(update={"payload": payload, "payload_digest": digest_cohort_profile_payload(payload)})
    profile = profile.model_copy(update={"profile_digest": digest_cohort_profile(profile)})
    async with OpportunityUnitOfWork(factory).transaction() as repo:
        await repo.stage_profile(profile)
        await repo.stage_head(
            user_id="u1",
            project_name="show-a",
            head=OpportunityCohortProfileHead(
                profile_id=profile.profile_id,
                current_revision=1,
                head_version=1,
            ),
            expected_head_version=None,
        )
    raw, grant, evaluation = source_inputs()
    offset = datetime.now(UTC) - NOW
    documents = tuple(
        doc.model_copy(
            update={
                "assessed_at": doc.assessed_at + offset,
                "expires_at": doc.expires_at + offset,
                "effective_at": None if doc.effective_at is None else doc.effective_at + offset,
            }
        )
        for doc in grant.policy_documents
    )
    grant = grant.model_copy(
        update={
            "issued_at": grant.issued_at + offset,
            "expires_at": grant.expires_at + offset,
            "refresh_after": grant.refresh_after + offset,
            "policy_documents": documents,
        }
    )
    evaluation = evaluation.model_copy(
        update={
            "evaluated_at": evaluation.evaluated_at + offset,
            "expires_at": evaluation.expires_at + offset,
        }
    )
    from r2.contracts.opportunity import CapabilityEvaluationRequest

    request = CapabilityEvaluationRequest(
        user_id="u1",
        project_name="show-a",
        actor_id="human-a",
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        grant_digest=grant.grant_digest,
        source_kind=grant.source_kind,
        operation="import",
        purpose="LANDSCAPE",
        account_binding_digest=None,
    )
    grant, evaluation, request = _resign(grant, evaluation, request)

    class CapabilityFixture:
        calls = 0

        async def resolve_grant(self, ref):
            assert store.active_transactions == 0
            self.calls += 1
            assert ref == grant.grant_id
            return self.grant

        async def evaluate(self, request):
            assert store.active_transactions == 0
            self.calls += 1
            return self.evaluation

    capabilities = CapabilityFixture()
    capabilities.grant, capabilities.evaluation = grant, evaluation
    source = ManualImportSource(
        payload=raw,
        grant=grant,
        evaluation=evaluation,
        actor_id="human-a",
        upload_ref=UPLOAD,
        origin_ref=ORIGIN,
        declared_origin="synthetic-fixture",
        uploader_id="fixture-human",
        payload_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
    )
    evidence = FileSnapshotEvidenceStore(tmp_path / "evidence", user_id="u1", project_name="show-a")
    service = module.OpportunityAcquisitionService(
        store=store,
        capabilities=capabilities,
        source=source,
        evidence=evidence,
        user_id="u1",
        project_name="show-a",
        actor_id="human-a",
    )
    from r2.contracts.opportunity import CommandContext, DeclareSourceQuery, SourceQueryDraft

    command = DeclareSourceQuery(
        context=CommandContext(
            command_id="019a0000-0000-7000-8000-000000000081", user_id="u1", project_name="show-a", actor_id="human-a"
        ),
        query_id="019a0000-0000-7000-8000-000000000082",
        parent_revision=None,
        expected_head_version=None,
        draft=SourceQueryDraft(
            source_kind="manual-import",
            source_contract_version="manual-import.v1",
            operation="import",
            intent="LANDSCAPE",
            parameters={"import_ref": UPLOAD},
            cohort_id=profile.payload.cohort_id,
            cohort_version=profile.payload.cohort_version,
            cohort_profile_id=profile.profile_id,
            cohort_profile_revision=1,
            cohort_profile_digest=profile.profile_digest,
            capability_grant_id=grant.grant_id,
            capability_grant_version=grant.grant_version,
            capability_grant_digest=grant.grant_digest,
            capability_evaluation_id=evaluation.evaluation_id,
            capability_evaluation_digest=evaluation.evaluation_digest,
            credential_ref=None,
            max_pages=1,
            max_records=1000,
            max_quota_units=0,
        ),
    )
    return service, command, capabilities


async def test_declare_query_runs_real_host_policy_and_replays_without_new_capability_calls(session_factory, tmp_path):
    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    receipt = await service.declare_query(command)
    calls = capabilities.calls
    assert calls == 2
    assert receipt.query.created_by == "human-a"
    assert receipt.head.current_revision == 1
    assert await service.declare_query(command) == receipt
    assert capabilities.calls == calls
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.receipts.get_query_for_revision(command.query_id, 1) == receipt


@pytest.mark.parametrize(
    "fault",
    ["scope", "profile_digest", "profile_revision", "grant_digest", "evaluation_digest", "intent", "external_source"],
)
async def test_declare_query_refuses_scope_and_admission_drift_before_query_commit(session_factory, tmp_path, fault):
    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    updates = {
        "profile_digest": {"cohort_profile_digest": "sha256:" + "b" * 64},
        "profile_revision": {"cohort_profile_revision": 2},
        "grant_digest": {"capability_grant_digest": "sha256:" + "b" * 64},
        "evaluation_digest": {"capability_evaluation_digest": "sha256:" + "b" * 64},
        "intent": {"intent": "AUDIENCE"},
        "external_source": {"source_kind": "youtube-data"},
    }
    if fault == "scope":
        command = command.model_copy(update={"context": command.context.model_copy(update={"project_name": "foreign"})})
    else:
        command = command.model_copy(update={"draft": command.draft.model_copy(update=updates[fault])})
    with pytest.raises(OpportunityError):
        await service.declare_query(command)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.queries.get_exact(command.query_id, 1) is None
    if fault in {"scope", "external_source"}:
        assert capabilities.calls == 0


@pytest.mark.parametrize("fault", ["missing_evidence", "condition_shape", "port_canary"])
async def test_declare_query_missing_host_seam_and_malformed_policy_fail_closed_without_raw_errors(
    session_factory, tmp_path, fault
):
    from r2.contracts.advanced_creative import CanonicalJsonObject
    from r2.contracts.opportunity import CapabilityEvaluationRequest
    from tests.unit.r2.opportunity.test_capabilities import _resign

    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    if fault == "missing_evidence":
        service.evidence = None
    elif fault == "port_canary":

        async def unavailable(ref):
            raise RuntimeError("m9-secret-canary-do-not-log")

        capabilities.resolve_grant = unavailable
    else:
        grant, evaluation = capabilities.grant, capabilities.evaluation
        condition = {**grant.conditions[0].model_dump(), "data_classes": 7}
        grant = grant.model_copy(update={"conditions": (CanonicalJsonObject.model_validate(condition),)})
        evaluation = evaluation.model_copy(
            update={
                "condition_evidence": (CanonicalJsonObject.model_validate({"condition": condition, "satisfied": True}),)
            }
        )
        request = CapabilityEvaluationRequest(
            user_id="u1",
            project_name="show-a",
            actor_id="human-a",
            grant_id=grant.grant_id,
            grant_version=grant.grant_version,
            grant_digest=grant.grant_digest,
            source_kind=grant.source_kind,
            operation="import",
            purpose="LANDSCAPE",
            account_binding_digest=None,
        )
        grant, evaluation, _ = _resign(grant, evaluation, request)
        capabilities.grant, capabilities.evaluation = grant, evaluation
        command = command.model_copy(
            update={
                "draft": command.draft.model_copy(
                    update={
                        "capability_grant_digest": grant.grant_digest,
                        "capability_evaluation_digest": evaluation.evaluation_digest,
                    }
                )
            }
        )
    with pytest.raises(OpportunityError) as error:
        await service.declare_query(command)
    assert "m9-secret-canary" not in str(error.value)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.queries.get_exact(command.query_id, 1) is None


@pytest.mark.parametrize("mode", ["equal", "divergent"])
async def test_query_application_race_rechecks_receipt_before_any_metadata_write(session_factory, tmp_path, mode):
    from lib.db.models.opportunity import M9CommandReceiptModel, M9EventModel
    from lib.db.models.opportunity_acquisition import M9SourceQueryModel

    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    both_evaluating = asyncio.Event()
    arrivals = 0
    original = capabilities.evaluate

    async def evaluate(request):
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            both_evaluating.set()
        await asyncio.wait_for(both_evaluating.wait(), timeout=10)
        return await original(request)

    capabilities.evaluate = evaluate
    other = (
        command
        if mode == "equal"
        else command.model_copy(
            update={
                "query_id": "019a0000-0000-7000-8000-000000000083",
            }
        )
    )
    results = await asyncio.gather(service.declare_query(command), service.declare_query(other), return_exceptions=True)
    if mode == "equal":
        assert results[0] == results[1]
        assert not isinstance(results[0], BaseException)
    else:
        errors = [item for item in results if isinstance(item, OpportunityError)]
        assert len(errors) == 1
        assert errors[0].code == StopCode.M9_COMMAND_REPLAY_CONFLICT
    async with session_factory() as session:
        for model in (M9SourceQueryModel, M9CommandReceiptModel, M9EventModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 1


async def test_query_revision_and_receipt_history_survive_later_host_unavailability(session_factory, tmp_path):
    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    first = await service.declare_query(command)
    next_command = command.model_copy(
        update={
            "context": command.context.model_copy(update={"command_id": "019a0000-0000-7000-8000-000000000084"}),
            "parent_revision": 1,
            "expected_head_version": 1,
        }
    )
    second = await service.declare_query(next_command)
    assert second.query.parent_revision == 1
    assert second.query.revision == 2
    calls = capabilities.calls
    service.capabilities = None
    service.source = None
    service.evidence = None
    assert await service.declare_query(command) == first
    assert await service.declare_query(next_command) == second
    assert capabilities.calls == calls
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.receipts.get_query_for_revision(command.query_id, 1) == first
        assert await tx.receipts.get_query_for_revision(command.query_id, 2) == second


async def test_query_application_rolls_back_every_staged_row_if_receipt_commit_fails(
    session_factory, tmp_path, monkeypatch
):
    from lib.db.models.opportunity import M9CommandReceiptModel, M9EventModel
    from lib.db.models.opportunity_acquisition import (
        M9CapabilityEvaluationModel,
        M9ConsumedCapabilityGrantModel,
        M9SourceQueryHeadModel,
        M9SourceQueryModel,
    )
    from lib.db.repositories.opportunity_acquisition import AcquisitionReceiptRepository

    service, command, _ = await acquisition_service_fixture(session_factory, tmp_path)
    original = AcquisitionReceiptRepository.stage_query

    async def interrupted(self, *, context, receipt):
        await original(self, context=context, receipt=receipt)
        raise RuntimeError("injected after receipt flush")

    monkeypatch.setattr(AcquisitionReceiptRepository, "stage_query", interrupted)
    with pytest.raises(RuntimeError, match="injected after receipt flush"):
        await service.declare_query(command)
    async with session_factory() as session:
        for model in (
            M9CapabilityEvaluationModel,
            M9ConsumedCapabilityGrantModel,
            M9SourceQueryHeadModel,
            M9SourceQueryModel,
            M9CommandReceiptModel,
            M9EventModel,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_query_commit_ack_loss_is_recovered_by_original_receipt_without_repeating_ports(
    session_factory, tmp_path
):
    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    original = capabilities.evaluate

    async def lose_ack_after_resolve(request):
        result = await original(request)
        service.store.lose_ack = True
        return result

    capabilities.evaluate = lose_ack_after_resolve
    with pytest.raises(ConnectionError, match="injected lost commit acknowledgement"):
        await service.declare_query(command)
    calls = capabilities.calls
    replay = await service.declare_query(command)
    assert capabilities.calls == calls
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.receipts.get_query_for_revision(command.query_id, 1) == replay


async def test_query_profile_superseded_while_capability_port_is_outside_transaction_refuses_admission(
    session_factory, tmp_path
):
    from lib.db.repositories.opportunity import OpportunityUnitOfWork
    from r2.contracts.opportunity import OpportunityCohortProfileHead
    from r2.opportunity.digests import digest_cohort_profile

    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    original = capabilities.evaluate

    async def supersede(request):
        result = await original(request)
        async with OpportunityUnitOfWork(session_factory).transaction() as repo:
            profile = await repo.get_exact(
                user_id="u1", project_name="show-a", profile_id=command.draft.cohort_profile_id, revision=1
            )
            newer = profile.model_copy(update={"revision": 2, "parent_revision": 1})
            newer = newer.model_copy(update={"profile_digest": digest_cohort_profile(newer)})
            await repo.stage_profile(newer)
            await repo.stage_head(
                user_id="u1",
                project_name="show-a",
                head=OpportunityCohortProfileHead(
                    profile_id=profile.profile_id,
                    current_revision=2,
                    head_version=2,
                ),
                expected_head_version=1,
            )
        return result

    capabilities.evaluate = supersede
    with pytest.raises(OpportunityError, match="M9_COHORT_LEAKAGE"):
        await service.declare_query(command)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.queries.get_exact(command.query_id, 1) is None


async def test_query_locks_capability_before_cohort_head_as_required_by_global_rank(
    session_factory, tmp_path, monkeypatch
):
    from lib.db.models.opportunity import M9ProfileHeadModel
    from server.services.opportunity import HostAcquisitionTransaction

    service, command, capabilities = await acquisition_service_fixture(session_factory, tmp_path)
    entered = asyncio.Event()
    pids = {}
    original = HostAcquisitionTransaction.creative_policy_identity

    async def observed_policy(self):
        value = await original(self)
        pids["service"] = await self.session.scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        return value

    monkeypatch.setattr(HostAcquisitionTransaction, "creative_policy_identity", observed_policy)
    task = None
    try:
        async with unit_of_work(session_factory).transaction() as writer:
            pids["writer"] = await writer.session.scalar(text("SELECT pg_backend_pid()"))
            await writer.capabilities.consume(capabilities.grant, capabilities.evaluation, actor_id="human-a")
            task = asyncio.create_task(service.declare_query(command))
            await asyncio.wait_for(entered.wait(), timeout=10)
            await observe_blocked(session_factory, pids["service"], pids["writer"])
            row = await writer.session.scalar(
                select(M9ProfileHeadModel.profile_id)
                .where(
                    M9ProfileHeadModel.user_id == "u1",
                    M9ProfileHeadModel.project_name == "show-a",
                    M9ProfileHeadModel.profile_id == command.draft.cohort_profile_id,
                )
                .with_for_update(nowait=True)
            )
            assert row == command.draft.cohort_profile_id
    finally:
        results = [] if task is None else await asyncio.gather(task, return_exceptions=True)
    assert len(results) == 1
    assert not isinstance(results[0], BaseException)


async def test_capability_admission_guards_follow_evidence_id_order(session_factory):
    import struct

    from r2.advanced_creative.digests import digest_canonical
    from tests.unit.r2.opportunity.test_capabilities import _authority, _resign

    grant, evaluation, request = _authority()
    grant = grant.model_copy(update={"grant_id": "z-native-grant"})
    evaluation = evaluation.model_copy(update={"evaluation_id": "a-native-evaluation", "grant_id": grant.grant_id})
    request = request.model_copy(update={"grant_id": grant.grant_id})
    grant, evaluation, _ = _resign(grant, evaluation, request)

    def key(identity):
        digest = digest_canonical(
            {
                "domain": "m9.capability-admission-lock.v1",
                "user_id": "u1",
                "project_name": "show-a",
                "identity": identity,
            }
        )
        return struct.unpack(">ii", bytes.fromhex(digest.removeprefix("sha256:"))[:8])

    grant_key = key(("grant", grant.grant_id, str(grant.grant_version)))
    evaluation_key = key(("evaluation", evaluation.evaluation_id))
    entered = asyncio.Event()
    pids = {}

    async def consume():
        async with unit_of_work(session_factory).transaction() as tx:
            pids["consumer"] = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            entered.set()
            await tx.capabilities.consume(grant, evaluation, actor_id="human-a")

    task = None
    try:
        async with session_factory() as gate, gate.begin():
            gate_pid = await gate.scalar(text("SELECT pg_backend_pid()"))
            await gate.execute(
                text("SELECT pg_advisory_xact_lock(:first,:second)"),
                {"first": evaluation_key[0], "second": evaluation_key[1]},
            )
            task = asyncio.create_task(consume())
            await asyncio.wait_for(entered.wait(), timeout=10)
            await observe_blocked(session_factory, pids["consumer"], gate_pid)
            acquired = await gate.scalar(
                text("SELECT pg_try_advisory_xact_lock(:first,:second)"),
                {"first": grant_key[0], "second": grant_key[1]},
            )
            assert acquired is True
    finally:
        results = [] if task is None else await asyncio.gather(task, return_exceptions=True)
    assert results == [None]
