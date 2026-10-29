"""V2 orchestration uses committed custody and real independently sealed files."""

from __future__ import annotations

import asyncio
import importlib
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel, M9SourceSnapshotModel
from r2.contracts.opportunity_acquisition_v2 import AcquireSourceQueryV2
from r2.opportunity.errors import OpportunityError
from r2.opportunity.manual_admission import (
    FrozenManualBinding,
    ManualBindingDescriptor,
    ManualBindingRegistry,
    PublishedAdmission,
)
from tests.integration.lib.db.repositories.test_opportunity_manual_admission import manual_subject
from tests.integration.r2.opportunity.test_acquisition_concurrency import acquire_command, acquisition_service_fixture
from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process
from tests.integration.server.services.test_m9_manual_publication import prepare_publication


async def service_subject(
    factory,
    tmp_path,
    *,
    boundary=None,
    refresh_seconds=60,
    retention_seconds=120,
    cleanup=False,
    read_boundary=None,
    parts=None,
):
    module = importlib.import_module("r2.opportunity.acquisition_v2")
    host = importlib.import_module("server.services.opportunity_acquisition_v2")
    old, declaration, capabilities = await acquisition_service_fixture(factory, tmp_path)
    declared = await old.declare_query(declaration)
    if parts is not None:
        parts.update(query_service=old, declaration=declaration, declared=declared, capabilities=capabilities)
    command = AcquireSourceQueryV2(**acquire_command(declared).model_dump(), protocol_version="m9.acquisition.v2")
    root, provision, publication = await prepare_publication(tmp_path)
    provision.update(
        context=command.context.model_dump(mode="json"),
        opaque_upload_id=declared.query.parameters.model_dump()["import_ref"],
        data_rules=[r.model_dump(mode="json") for r in capabilities.grant.data_rules],
    )
    now = datetime.now(UTC)
    provision["original_clocks"] = [
        {
            "data_class": r.data_class,
            "captured_at": now.isoformat(),
            "refresh_due_at": (
                now + timedelta(seconds=min(r.refresh_interval_seconds or refresh_seconds, refresh_seconds))
            ).isoformat(),
            "retention_due_at": (
                now + timedelta(seconds=min(r.retention_seconds or retention_seconds, retention_seconds))
            ).isoformat(),
        }
        for r in capabilities.grant.data_rules
    ]
    (root / "authority.json").write_text(
        json.dumps({"request": provision, "declared_origin": "synthetic-fixture", "uploader_id": "fixture-human"})
    )
    descriptor = ManualBindingDescriptor.model_validate(provision["descriptor"])
    active = ContextVar("v2_active_transactions", default=0)
    calls = []

    class ObservedStore(host.HostManualAdmissionUnitOfWork):
        @asynccontextmanager
        async def transaction(self):
            token = active.set(active.get() + 1)
            try:
                async with super().transaction() as tx:
                    yield tx
            finally:
                active.reset(token)

    class Issuer:
        async def admit(self, request):
            assert active.get() == 0
            calls.append("admit")
            async with factory() as session, session.begin():
                repo = host.HostManualAdmissionTransaction(session, user_id="u1", project_name="show-a").manual
                assert (await repo.get_for_command(command)).state == "RUNNING"
                assert await repo.get_descriptor(request.attempt_id) == descriptor
                assert (await repo.get_envelope(request.attempt_id)).phase == "RESERVED"
            code, result = await issuer_process(
                root, "admit", request=request.model_dump(mode="json"), publication_root=str(publication.root)
            )
            assert code == 0, result
            return PublishedAdmission.model_validate(result["publication"])

    class Source:
        async def fetch_page(self, request):
            assert active.get() == 0
            calls.append("fetch")
            async with factory() as session, session.begin():
                envelope = await host.HostManualAdmissionTransaction(
                    session, user_id="u1", project_name="show-a"
                ).manual.get_envelope(request.attempt_id)
                assert envelope.phase == "READY"
                assert envelope.dispatch_claim is not None
            return await old.source.fetch_page(request)

    class Capability:
        async def resolve_grant(self, ref):
            assert active.get() == 0
            calls.append("grant")
            return await capabilities.resolve_grant(ref)

        async def evaluate(self, request):
            assert active.get() == 0
            calls.append("evaluate")
            return await capabilities.evaluate(request)

    class Publication:
        async def lookup_receipt(self, key):
            assert active.get() == 0
            calls.append("lookup")
            return await publication.lookup_receipt(key)

        async def read_verified(self, envelope, *, object_ref, permit):
            assert active.get() == 0
            calls.append("read")
            raw = await publication.read_verified(envelope, object_ref=object_ref, permit=permit)
            if read_boundary is not None:
                await read_boundary()
            return raw

        async def delete_exact(self, closure):
            assert active.get() == 0
            return await publication.delete_exact(closure)

    class CustodianClosure:
        async def close_original(self, request, *, claim_ref, closure_id):
            from r2.advanced_creative.digests import canonical_json_bytes

            assert active.get() == 0
            calls.append("spend")
            async with factory() as session, session.begin():
                envelope = await host.HostManualAdmissionTransaction(
                    session, user_id="u1", project_name="show-a"
                ).manual.get_envelope(request.attempt_id)
                assert envelope.phase == "CLEANUP_PENDING"
            code, result = await issuer_process(
                root,
                "close",
                request=request.model_dump(mode="json"),
                claim_ref=claim_ref,
                closure_id=closure_id,
                deny_spend_content_read=True,
            )
            if code != 0:
                raise OpportunityError(result["error"])
            return canonical_json_bytes(result["receipt"])

    cleanup_ports = {}
    if cleanup:
        cleanup_ports["cleanup"] = importlib.import_module(
            "server.services.m9_manual_publication"
        ).VerifiedManualCleanup(
            descriptor=descriptor,
            publication=publication,
            custodian=CustodianClosure(),
            declared_origin="synthetic-fixture",
            uploader_id="fixture-human",
        )

    registry = ManualBindingRegistry(
        (
            FrozenManualBinding(
                descriptor, publication.verifier.public_key, Source(), Issuer(), Publication(), lambda: descriptor
            ),
        )
    )
    metadata = module.ManualUploadMetadata(
        user_id="u1",
        project_name="show-a",
        opaque_upload_id=provision["opaque_upload_id"],
        upload_version=provision["upload_version"],
        data_rules=provision["data_rules"],
        original_clocks=provision["original_clocks"],
    )
    from r2.advanced_creative.exploration import uuid7

    service = module.OpportunityAcquisitionServiceV2(
        store=ObservedStore(factory, user_id="u1", project_name="show-a"),
        registry=registry,
        descriptor=descriptor,
        upload=metadata,
        capabilities=Capability(),
        new_id=uuid7,
        user_id="u1",
        project_name="show-a",
        actor_id="human-a",
        boundary=boundary,
        **cleanup_ports,
    )
    return service, command, calls, publication


async def test_v2_acquire_uses_committed_custody_before_dispatch_and_replays_without_ports(session_factory, tmp_path):
    service, command, calls, publication = await service_subject(session_factory, tmp_path)
    receipt = await service.acquire(command)
    assert receipt.state == "SUCCEEDED"
    assert len(receipt.snapshot_ids) == 1
    assert calls.count("admit") == calls.count("fetch") == 1
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(receipt.attempt_id)
        snapshot, provenance = await tx.manual.get_snapshot_for_attempt(receipt.attempt_id)
        assert snapshot.snapshot_digest == receipt.snapshot_digests[0]
        assert snapshot.capture_completed_at == envelope.admitted_at
        assert provenance.origin == "SOURCE_RESPONSE_VERIFIED"
        assert provenance.response_recorded_at >= envelope.admitted_at
        assert await tx.manual.get_current_receipt(command) == receipt
        assert len(await tx.manual.list_checkpoints(receipt.attempt_id)) == 1
    assert await publication.lookup_receipt(envelope.request.publication_key) is not None
    before = list(calls)
    service.registry = None
    assert await service.acquire(command) == receipt
    assert calls == before


async def test_v2_concurrent_acquire_loser_never_dispatches(session_factory, tmp_path):
    reached, release = asyncio.Event(), asyncio.Event()

    async def boundary(name):
        if name == "reserved-committed":
            reached.set()
            await release.wait()

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=boundary)
    first = asyncio.create_task(service.acquire(command))
    try:
        await asyncio.wait_for(reached.wait(), 15)
        loser = await service.acquire(command)
        assert loser.state == "RUNNING"
        assert "fetch" not in calls
        assert "admit" not in calls
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == 1
    finally:
        release.set()
        winner = await first
    assert winner.state == "SUCCEEDED"
    assert loser.attempt_id == winner.attempt_id
    assert calls.count("fetch") == 1


async def test_v2_default_host_is_unavailable_before_any_attempt(session_factory, tmp_path):
    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    service.registry = None
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        await service.acquire(command)
    assert calls == []
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == 0
        assert await session.scalar(select(func.count()).select_from(M9SourceSnapshotModel)) == 0


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


@pytest.mark.parametrize(
    "stage",
    ["reserved-committed", "ready-committed", "claim-committed", "checkpoint-committed", "finalization-committed"],
)
async def test_v2_lost_stage_ack_never_repeats_dispatch(session_factory, tmp_path, stage):
    async def lose_ack(name):
        if name == stage:
            raise ConnectionError("synthetic lost acknowledgement")

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=lose_ack)
    first = await service.acquire(command)
    before = calls.count("fetch")
    retained = await service.acquire(command)
    assert retained == first
    assert calls.count("fetch") == before
    assert retained.state == (
        "SUCCEEDED"
        if stage == "finalization-committed"
        else "OUTCOME_UNKNOWN"
        if stage == "checkpoint-committed"
        else "RUNNING"
    )
    async with service.store.transaction() as tx:
        assert await tx.manual.get_current_receipt(command) == retained
        envelope = await tx.manual.get_envelope(retained.attempt_id)
        assert envelope.admitted_at is not None if stage != "reserved-committed" else envelope.admitted_at is None


async def test_v2_publication_reconciliation_attaches_original_without_dispatch(session_factory, tmp_path):
    async def lose_publication_ack(name):
        if name == "publication-returned":
            raise ConnectionError("publication delivered before attach")

    service, command, calls, public = await service_subject(session_factory, tmp_path, boundary=lose_publication_ack)
    first = await service.acquire(command)
    original = await service.acquire(command)
    assert original == first
    async with service.store.transaction() as tx:
        reserved = await tx.manual.get_envelope(original.attempt_id)
        assert reserved.phase == "RESERVED"
    header = await public.lookup_receipt(reserved.request.publication_key)
    assert header is not None
    await service.reconcile_publication(command)
    async with service.store.transaction() as tx:
        ready = await tx.manual.get_envelope(original.attempt_id)
        assert ready.phase == "READY"
        assert ready.claim_ref == header.metadata.claim_ref
        assert {o.payload_ref for o in ready.objects} == {o.payload_ref for o in header.metadata.objects}
        assert ready.dispatch_claim is None
    assert "fetch" not in calls
    await service.reconcile_publication(command)
    async with service.store.transaction() as tx:
        assert await tx.manual.get_envelope(original.attempt_id) == ready


@pytest.mark.parametrize("stage", ["reserved-committed", "ready-committed"])
async def test_v2_live_measurement_replacement_refuses_before_next_port(session_factory, tmp_path, stage):
    from dataclasses import replace

    service = None

    async def replace_measurement(name: str) -> None:
        if name == stage:
            binding = service.registry.bindings[0]
            changed = binding.descriptor.model_copy(update={"decoder_digest": "sha256:" + "a" * 64})
            service.registry = ManualBindingRegistry((replace(binding, measure=lambda: changed),))

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=replace_measurement)
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        await service.acquire(command)
    assert "fetch" not in calls
    assert calls.count("admit") == (0 if stage == "reserved-committed" else 1)
    async with service.store.transaction() as tx:
        attempt = await tx.manual.get_for_command(command)
        assert await tx.manual.get_descriptor(attempt.attempt_id) == service.descriptor
        assert await tx.manual.get_snapshot_for_attempt(attempt.attempt_id) is None


async def test_v2_source_response_must_match_independent_original_bytes(session_factory, tmp_path):
    from dataclasses import replace

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    original = service.registry.bindings[0]

    class ChangedSource:
        async def fetch_page(self, request):
            response = await original.source.fetch_page(request)
            return response.model_copy(
                update={"raw_payload": response.raw_payload.replace(b'"value": 125', b'"value": 126')}
            )

    service.registry = ManualBindingRegistry((replace(original, source=ChangedSource()),))
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await service.acquire(command)
    async with service.store.transaction() as tx:
        attempt = await tx.manual.get_for_command(command)
        assert attempt.state == "OUTCOME_UNKNOWN"
        assert attempt.quota_disposition == "POSSIBLY_CONSUMED"
        assert await tx.manual.get_snapshot_for_attempt(attempt.attempt_id) is None
        assert await tx.manual.list_checkpoints(attempt.attempt_id) == ()
    assert calls.count("fetch") == 1


async def test_v2_untrusted_source_error_is_sanitized_and_preserves_uncertainty(session_factory, tmp_path):
    from dataclasses import replace

    service, command, _calls, _ = await service_subject(session_factory, tmp_path)
    original = service.registry.bindings[0]

    class FailedSource:
        async def fetch_page(self, request):
            raise RuntimeError("CANARY_ORIGINAL_CREDENTIAL_MUST_NOT_ESCAPE")

    service.registry = ManualBindingRegistry((replace(original, source=FailedSource()),))
    receipt = await service.acquire(command)
    assert receipt.state == "OUTCOME_UNKNOWN"
    assert receipt.quota_disposition == "POSSIBLY_CONSUMED"
    assert receipt.snapshot_ids == ()
    assert "CANARY" not in receipt.model_dump_json()
    async with service.store.transaction() as tx:
        assert await tx.manual.get_current_receipt(command) == receipt
        envelope = await tx.manual.get_envelope(receipt.attempt_id)
        assert envelope.dispatch_claim is not None


async def test_v2_response_provider_identity_must_match_original_upload(session_factory, tmp_path):
    from dataclasses import replace

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    original = service.registry.bindings[0]

    class ChangedProvider:
        async def fetch_page(self, request):
            response = await original.source.fetch_page(request)
            return response.model_copy(update={"provider_request_id": "different-original-upload"})

    service.registry = ManualBindingRegistry((replace(original, source=ChangedProvider()),))
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await service.acquire(command)
    async with service.store.transaction() as tx:
        attempt = await tx.manual.get_for_command(command)
        assert await tx.manual.list_checkpoints(attempt.attempt_id) == ()
        assert await tx.manual.get_snapshot_for_attempt(attempt.attempt_id) is None
    assert calls.count("fetch") == 1


async def test_explicit_acquisition_factory_selects_v2_without_downgrade(session_factory):
    from r2.opportunity.acquisition import OpportunityAcquisitionService
    from r2.opportunity.acquisition_v2 import OpportunityAcquisitionServiceV2
    from server.auth import CurrentUserInfo
    from server.services.opportunity import build_acquisition_service, build_acquisition_service_for_protocol

    user = CurrentUserInfo(id="u1", sub="human-a")
    command, _, _ = await manual_subject(session_factory, host_policy=True)
    assert isinstance(
        build_acquisition_service(session_factory, current_user=user, project_name="show-a"),
        OpportunityAcquisitionService,
    )
    service = build_acquisition_service_for_protocol(
        session_factory, current_user=user, project_name="show-a", protocol_version="m9.acquisition.v2"
    )
    assert isinstance(service, OpportunityAcquisitionServiceV2)
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        await service.acquire(command)
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        build_acquisition_service_for_protocol(
            session_factory, current_user=user, project_name="show-a", protocol_version="m9.acquisition.invalid"
        )
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9AcquisitionAttemptModel)) == 0


@pytest.mark.parametrize("stage", ["ready-committed", "claim-committed"])
async def test_v2_no_checkpoint_reconstruction_preserves_original_refs_without_source(session_factory, tmp_path, stage):
    async def stop_after_commit(name):
        if name == stage:
            raise ConnectionError("restart before source response")

    service, command, calls, _publication = await service_subject(session_factory, tmp_path, boundary=stop_after_commit)
    await service.acquire(command)
    before = list(calls)
    async with service.store.transaction() as tx:
        attempt = await tx.manual.get_for_command(command)
        original = await tx.manual.get_envelope(attempt.attempt_id)
        assert await tx.manual.list_checkpoints(attempt.attempt_id) == ()
    receipt = await service.reconcile_manual_admission(command)
    assert receipt.state == "OUTCOME_UNKNOWN"
    assert len(receipt.snapshot_ids) == 1
    assert receipt.quota_disposition == "POSSIBLY_CONSUMED"
    assert calls.count("fetch") == before.count("fetch") == 0
    async with service.store.transaction() as tx:
        retained = await tx.manual.get_envelope(attempt.attempt_id)
        snapshot, provenance = await tx.manual.get_snapshot_for_attempt(attempt.attempt_id)
        assert retained.admitted_at == original.admitted_at
        assert retained.objects == original.objects
        assert retained.deadlines == original.deadlines
        assert provenance.origin == "LOCAL_ADMISSION_RECONSTRUCTION"
        assert provenance.response_recorded_at is None
        assert snapshot.provider_observed_at is None
        assert snapshot.pages[0].provider_request_id is None
        assert snapshot.pages[0].payload_ref in {o.payload_ref for o in original.objects}
    before = list(calls)
    service.registry = None
    assert await service.reconcile_manual_admission(command) == receipt
    assert calls == before


async def wait_for_original_deadline(service, command, *, retention=False):
    async with service.store.transaction() as tx:
        attempt = await tx.manual.get_for_command(command)
        envelope = await tx.manual.get_envelope(attempt.attempt_id)
        deadline = envelope.deadlines.retention_due_at if retention else envelope.deadlines.refresh_due_at
    async with asyncio.timeout(15):
        while True:
            async with service.store.transaction() as tx:
                now = await tx.profiles.database_time()
            if now >= deadline:
                return envelope, now
            await asyncio.sleep(min((deadline - now).total_seconds(), 0.2))


@pytest.mark.parametrize("retention", [False, True])
async def test_v2_expiry_uses_original_deadline_without_any_content_or_port_call(session_factory, tmp_path, retention):
    async def stop_claim(name):
        if name in ("claim-committed", "expiry-committed"):
            raise ConnectionError("lost original acknowledgement")

    service, command, calls, _ = await service_subject(
        session_factory,
        tmp_path,
        boundary=stop_claim,
        refresh_seconds=60 if retention else 6,
        retention_seconds=6 if retention else 120,
    )
    running = await service.acquire(command)
    assert running.state == "RUNNING"
    original, now = await wait_for_original_deadline(service, command, retention=retention)
    before = list(calls)
    service.registry = service.capabilities = None
    receipt = await service.expire_admission(command)
    assert receipt.state == "EXPIRED_UNRECOVERABLE"
    assert receipt.outcome_reason == "RESPONSE_OUTCOME_UNKNOWN"
    assert receipt.quota_disposition == "POSSIBLY_CONSUMED"
    assert receipt.quota_units_observed is None
    assert receipt.snapshot_ids == ()
    assert receipt.closure.original_deadline == (
        original.deadlines.retention_due_at if retention else original.deadlines.refresh_due_at
    )
    assert receipt.closure.closed_at >= now
    assert calls == before
    assert await service.expire_admission(command) == receipt
    assert await service.acquire(command) == receipt
    assert calls == before


async def test_v2_reconstruction_fences_an_original_worker_paused_before_dispatch(session_factory, tmp_path):
    reached, release = asyncio.Event(), asyncio.Event()

    async def pause(name):
        if name == "before-source-dispatch":
            reached.set()
            await release.wait()

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=pause)
    task = asyncio.create_task(service.acquire(command))
    try:
        await asyncio.wait_for(reached.wait(), 15)
        reconstructed = await service.reconcile_manual_admission(command)
        assert reconstructed.state == "OUTCOME_UNKNOWN"
        assert len(reconstructed.snapshot_ids) == 1
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert results == [reconstructed]
    assert "fetch" not in calls
    async with service.store.transaction() as tx:
        assert await tx.manual.get_current_receipt(command) == reconstructed


async def test_v2_reconstruction_expiry_during_original_read_discards_operational_work(session_factory, tmp_path):
    from dataclasses import replace

    async def stop_claim(name):
        if name == "claim-committed":
            raise ConnectionError("restart with original claim")

    service, command, calls, _ = await service_subject(
        session_factory, tmp_path, boundary=stop_claim, retention_seconds=6
    )
    await service.acquire(command)
    original = service.registry.bindings[0]

    class DelayedRead:
        first = True

        async def lookup_receipt(self, key):
            return await original.publication.lookup_receipt(key)

        async def read_verified(self, envelope, *, object_ref, permit):
            data = await original.publication.read_verified(envelope, object_ref=object_ref, permit=permit)
            if self.first:
                self.first = False
                await wait_for_original_deadline(service, command, retention=True)
            return data

        async def delete_exact(self, closure):
            return await original.publication.delete_exact(closure)

    service.registry = ManualBindingRegistry((replace(original, publication=DelayedRead()),))
    receipt = await service.reconcile_manual_admission(command)
    assert receipt.state == "EXPIRED_UNRECOVERABLE"
    assert receipt.snapshot_ids == ()
    assert "fetch" not in calls
    async with service.store.transaction() as tx:
        assert await tx.manual.list_checkpoints(receipt.attempt_id) == ()
        assert await tx.manual.get_snapshot_for_attempt(receipt.attempt_id) is None


async def test_v2_concurrent_reconstruction_returns_one_original_snapshot(session_factory, tmp_path):
    arrived, release = asyncio.Event(), asyncio.Event()
    arrivals = 0

    async def hold_finalizers(name):
        nonlocal arrivals
        if name == "claim-committed":
            raise ConnectionError("restart after original claim")
        if name == "reconstruction-checkpoint-committed":
            arrivals += 1
            if arrivals == 2:
                arrived.set()
            await release.wait()

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=hold_finalizers)
    await service.acquire(command)
    tasks = [asyncio.create_task(service.reconcile_manual_admission(command)) for _ in range(2)]
    try:
        await asyncio.wait_for(arrived.wait(), 15)
    finally:
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
    assert results[0] == results[1]
    assert results[0].state == "OUTCOME_UNKNOWN"
    assert len(results[0].snapshot_ids) == 1
    assert "fetch" not in calls
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SourceSnapshotModel)) == 1


async def test_v2_expired_ready_without_claim_closes_without_fabricating_dispatch(session_factory, tmp_path):
    async def stop_ready(name):
        if name == "ready-committed":
            raise ConnectionError("restart with original READY and no claim")

    service, command, calls, _ = await service_subject(
        session_factory, tmp_path, boundary=stop_ready, refresh_seconds=6
    )
    initial = await service.acquire(command)
    assert initial.state == "RUNNING"
    original, _ = await wait_for_original_deadline(service, command)
    assert original.dispatch_claim is None
    before = list(calls)
    service.registry = service.capabilities = None
    receipt = await service.expire_admission(command)
    assert receipt.state == "EXPIRED_UNRECOVERABLE"
    assert receipt.quota_disposition == "UNKNOWN"
    assert receipt.quota_units_observed is None
    assert receipt.snapshot_ids == ()
    assert receipt.outcome_reason == "RESPONSE_OUTCOME_UNKNOWN"
    assert calls == before
    async with service.store.transaction() as tx:
        retained = await tx.manual.get_envelope(receipt.attempt_id)
        assert retained == original
        assert retained.dispatch_claim is None
    assert await service.acquire(command) == receipt


async def test_v2_reconstruction_uses_original_refs_after_ingest_path_replacement(session_factory, tmp_path):
    async def stop_ready(name: str) -> None:
        if name == "ready-committed":
            raise ConnectionError("restart with original admission")

    service, command, calls, publication = await service_subject(session_factory, tmp_path, boundary=stop_ready)
    initial = await service.acquire(command)
    ingest = tmp_path / "issuer" / "original.json"
    original_bytes = ingest.read_bytes()
    ingest.rename(tmp_path / "relocated-original.json")
    ingest.write_bytes(original_bytes.replace(b'"value": 125', b'"value": 126'))
    receipt = await service.reconcile_manual_admission(command)
    assert receipt.attempt_id == initial.attempt_id
    assert calls.count("admit") == 1

    assert "fetch" not in calls
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(receipt.attempt_id)
        snapshot, provenance = await tx.manual.get_snapshot_for_attempt(receipt.attempt_id)
        assert provenance.origin == "LOCAL_ADMISSION_RECONSTRUCTION"
        raw_object = next(o for o in envelope.objects if o.evidence_kind == "raw-page")
        assert snapshot.pages[0].payload_ref == raw_object.payload_ref
        permit = await tx.manual.begin_read(
            receipt.attempt_id, expected_envelope_version=envelope.version, operational=True
        )
    try:
        admitted = await publication.read_verified(envelope, object_ref=raw_object.payload_ref, permit=permit)
        assert admitted == original_bytes
        assert json.loads(admitted)["records"][0]["value"] == 125
    finally:
        async with service.store.transaction() as tx:
            await tx.manual.release_read(permit.lease_id)


async def test_v2_reconstruction_rejects_changed_original_refs_even_with_new_ordinary_hash(session_factory, tmp_path):
    import hashlib

    from r2.advanced_creative.digests import canonical_json_bytes

    async def stop_ready(name: str) -> None:
        if name == "ready-committed":
            raise ConnectionError("restart with original admission")

    service, command, calls, publication = await service_subject(session_factory, tmp_path, boundary=stop_ready)
    initial = await service.acquire(command)
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(initial.attempt_id)
    raw = next(o for o in envelope.objects if o.evidence_kind == "raw-page")
    scope = hashlib.sha256(canonical_json_bytes({"user_id": "u1", "project_name": "show-a"})).hexdigest()
    base = publication.root / "manual-publications" / scope
    target = base / "payloads" / (raw.payload_ref.rsplit(":", 1)[1] + ".bin")
    changed = target.read_bytes().replace(b'"value": 125', b'"value": 126')
    target.write_bytes(changed)
    (base / "integrities" / (raw.integrity_ref.rsplit(":", 1)[1] + ".json")).write_bytes(
        canonical_json_bytes(
            {
                "payload_ref": raw.payload_ref,
                "integrity_ref": raw.integrity_ref,
                "digest": "sha256:" + hashlib.sha256(changed).hexdigest(),
            }
        )
    )
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await service.reconcile_manual_admission(command)
    assert calls.count("admit") == 1
    assert "fetch" not in calls
    async with service.store.transaction() as tx:
        assert await tx.manual.get_snapshot_for_attempt(initial.attempt_id) is None
        assert await tx.manual.list_checkpoints(initial.attempt_id) == ()


@pytest.mark.parametrize("field", ["decoder_digest", "config_digest"])
async def test_v2_reconstruction_refuses_same_label_changed_measurement_before_content(
    session_factory, tmp_path, field
):
    from dataclasses import replace

    async def stop_ready(name: str) -> None:
        if name == "ready-committed":
            raise ConnectionError("restart with original admission")

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=stop_ready)
    initial = await service.acquire(command)
    binding = service.registry.bindings[0]
    changed = binding.descriptor.model_copy(update={field: "sha256:" + "f" * 64})
    service.registry = ManualBindingRegistry((replace(binding, measure=lambda: changed),))
    before = list(calls)
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        await service.reconcile_manual_admission(command)
    assert calls == before
    async with service.store.transaction() as tx:
        assert await tx.manual.get_descriptor(initial.attempt_id) == binding.descriptor
        assert await tx.manual.get_snapshot_for_attempt(initial.attempt_id) is None


async def test_v2_reconstruction_expiry_after_checkpoint_wins_before_snapshot(session_factory, tmp_path):
    async def expire_before_finalize(name: str) -> None:
        if name == "claim-committed":
            raise ConnectionError("restart with original claim")
        if name == "reconstruction-checkpoint-committed":
            await wait_for_original_deadline(service, command)

    service, command, calls, _ = await service_subject(
        session_factory, tmp_path, boundary=expire_before_finalize, refresh_seconds=6
    )
    await service.acquire(command)
    receipt = await service.reconcile_manual_admission(command)
    assert receipt.state == "EXPIRED_UNRECOVERABLE"
    assert receipt.snapshot_ids == ()
    assert "fetch" not in calls
    async with service.store.transaction() as tx:
        assert len(await tx.manual.list_checkpoints(receipt.attempt_id)) == 1
        assert await tx.manual.get_snapshot_for_attempt(receipt.attempt_id) is None


async def test_v2_operator_expiry_exception_never_resolves_provider_outcome(session_factory, tmp_path):
    from r2.contracts.opportunity import AttemptOutcomeReason
    from r2.contracts.opportunity_acquisition_v2 import AttemptStateV2

    async def stop_claim(name: str) -> None:
        if name == "claim-committed":
            raise ConnectionError("restart with original claim")

    service, command, calls, _ = await service_subject(
        session_factory, tmp_path, boundary=stop_claim, refresh_seconds=6
    )
    initial = await service.acquire(command)
    async with service.store.transaction() as tx:
        unknown = await tx.manual.mark_outcome_unknown(
            initial.attempt_id, expected_attempt_version=initial.attempt_version
        )
        operator = await tx.manual.mark_needs_operator(
            initial.attempt_id, expected_attempt_version=unknown.attempt_version
        )
        assert operator.state == "NEEDS_OPERATOR"
    await wait_for_original_deadline(service, command)
    before = list(calls)
    service.registry = service.capabilities = None
    receipt = await service.expire_admission(command)
    assert receipt.state == "EXPIRED_UNRECOVERABLE"
    assert receipt.outcome_reason == "RESPONSE_OUTCOME_UNKNOWN"
    assert receipt.quota_disposition == "POSSIBLY_CONSUMED"
    assert receipt.quota_units_observed is None
    assert calls == before
    async with service.store.transaction() as tx:
        assert (
            await tx.manual.finish_acquisition(
                receipt.attempt_id,
                expected_attempt_version=operator.attempt_version,
                state=AttemptStateV2.SUCCEEDED,
                reason=AttemptOutcomeReason.COMPLETED,
                resolver_id="qualified-expiry-only",
            )
            == receipt
        )
        assert await tx.manual.get_snapshot_for_attempt(receipt.attempt_id) is None


async def test_v2_publication_recovery_sanitizes_issuer_failure(session_factory, tmp_path):
    from dataclasses import replace

    async def stop_publication(name):
        if name == "publication-returned":
            raise ConnectionError("restart before SQL attachment")

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=stop_publication)
    initial = await service.acquire(command)
    original = service.registry.bindings[0]

    class FailedIssuer:
        async def admit(self, request):
            raise RuntimeError("CANARY_PRIVATE_ISSUER_CREDENTIAL_MUST_NOT_ESCAPE")

    service.registry = ManualBindingRegistry((replace(original, upload_admission=FailedIssuer()),))
    receipt = await service.reconcile_publication(command)
    assert receipt == initial
    assert "CANARY" not in receipt.model_dump_json()
    assert "fetch" not in calls
    async with service.store.transaction() as tx:
        assert (await tx.manual.get_envelope(initial.attempt_id)).phase == "RESERVED"
        assert await tx.manual.get_snapshot_for_attempt(initial.attempt_id) is None


async def test_v2_worker_paused_through_expiry_cannot_dispatch_after_resume(session_factory, tmp_path):
    arrived, release = asyncio.Event(), asyncio.Event()

    async def pause(name):
        if name == "before-source-dispatch":
            arrived.set()
            await release.wait()

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=pause, refresh_seconds=6)
    task = asyncio.create_task(service.acquire(command))
    try:
        await asyncio.wait_for(arrived.wait(), 15)
        await wait_for_original_deadline(service, command)
        expired = await service.expire_admission(command)
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert results == [expired]
    assert expired.state == "EXPIRED_UNRECOVERABLE"
    assert expired.snapshot_ids == ()
    assert "fetch" not in calls


async def test_v2_missing_original_deadlines_are_custody_failure_even_after_expiry(session_factory, tmp_path):
    from lib.db.models.opportunity_manual_admission import M9ManualAdmissionModel, M9ManualPublicationIntentModel
    from r2.opportunity.manual_admission import admission_metadata_digest

    async def stop_claim(name):
        if name == "claim-committed":
            raise ConnectionError("restart after original claim")

    service, command, calls, _ = await service_subject(
        session_factory, tmp_path, boundary=stop_claim, refresh_seconds=6
    )
    initial = await service.acquire(command)
    await wait_for_original_deadline(service, command)
    async with session_factory() as session, session.begin():
        for kind in (M9ManualAdmissionModel, M9ManualPublicationIntentModel):
            row = (await session.scalars(select(kind))).one()
            body = {**row.body_json, "deadlines": None}
            body["metadata_digest"] = admission_metadata_digest(body)
            row.body_json, row.metadata_digest = body, body["metadata_digest"]
            assert admission_metadata_digest(body) == row.metadata_digest
    before = list(calls)
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await service.expire_admission(command)
    assert calls == before
    async with session_factory() as session:
        row = (await session.scalars(select(M9AcquisitionAttemptModel))).one()
        assert row.state == initial.state == "RUNNING"
        assert row.attempt_version == initial.attempt_version


@pytest.mark.parametrize("shape", ["ready", "published-unattached", "never-published"])
async def test_v2_cleanup_commits_only_after_real_private_and_public_erasure(session_factory, tmp_path, shape):
    target = {"published-unattached": "publication-returned", "never-published": "reserved-committed"}.get(shape)

    async def boundary(name):
        if name == target:
            raise RuntimeError("leave original recovery boundary")

    service, command, calls, publication = await service_subject(
        session_factory,
        tmp_path,
        boundary=boundary,
        cleanup=True,
    )
    receipt = await service.acquire(command)
    assert receipt.state == ("SUCCEEDED" if shape == "ready" else "RUNNING")
    async with service.store.transaction() as tx:
        original = await tx.manual.get_envelope(receipt.attempt_id)
    assert original.phase == ("READY" if shape == "ready" else "RESERVED")
    if shape != "ready":
        assert original.admitted_at is None
        assert original.claim_ref is None
        assert not original.objects
    before = list(calls)
    service.registry = None
    service.descriptor = None
    service.upload = None
    service.capabilities = None
    erased = await service.reconcile_cleanup(command)
    assert erased.phase == "ERASED"
    assert erased.attempt_id == receipt.attempt_id
    assert erased.closure_id
    assert calls.count("fetch") == before.count("fetch")
    assert calls.count("read") == before.count("read")
    assert calls.count("admit") == before.count("admit")
    assert calls.count("spend") == 1
    issuer_root = tmp_path / "issuer"
    assert not (issuer_root / "original.json").exists()
    assert not list(issuer_root.glob("material-*.json"))
    assert not list(issuer_root.glob("seal-*.json"))
    assert await publication.lookup_receipt(original.request.publication_key) is None
    data_directories = {"payloads", "integrities", "attestations", "headers"}
    assert not [p for p in publication.root.rglob("*") if p.is_file() and p.parent.name in data_directories]
    async with service.store.transaction() as tx:
        retained = await tx.manual.get_envelope(receipt.attempt_id)
        assert retained.phase == "ERASED"
        assert retained.admitted_at == original.admitted_at
        assert retained.deadlines == original.deadlines
        assert await tx.manual.get_current_receipt(command) == receipt
        with pytest.raises(
            OpportunityError,
            match="M9_INVALIDATION_INCOMPLETE" if original.deadlines is not None else "M9_STALE_HEAD",
        ):
            await tx.manual.begin_read(
                receipt.attempt_id, expected_envelope_version=retained.version, operational=False
            )
    after = list(calls)
    assert await service.reconcile_cleanup(command) == erased
    assert calls == after
    code, refused = await issuer_process(issuer_root, "claim", request=original.request.model_dump(mode="json"))
    assert code == 2
    assert refused == {"error": "M9_EVIDENCE_RETENTION_EXPIRED"}


async def test_v2_cleanup_drains_admitted_reads_before_any_private_erasure(session_factory, tmp_path):
    service, command, calls, publication = await service_subject(session_factory, tmp_path, cleanup=True)
    receipt = await service.acquire(command)
    async with service.store.transaction() as tx:
        original = await tx.manual.get_envelope(receipt.attempt_id)
        permit = await tx.manual.begin_read(
            receipt.attempt_id,
            expected_envelope_version=original.version,
            operational=False,
        )
    with pytest.raises(OpportunityError, match="M9_INVALIDATION_INCOMPLETE"):
        await service.reconcile_cleanup(command)
    assert "spend" not in calls
    assert (tmp_path / "issuer" / "original.json").exists()
    assert list(publication.root.rglob("payloads/*"))
    async with service.store.transaction() as tx:
        pending = await tx.manual.get_cleanup_state(receipt.attempt_id)
        assert pending.intent.phase == "CLEANUP_PENDING"
        assert pending.intent.version == 1
        assert pending.proof is None
        assert (await tx.manual.get_envelope(receipt.attempt_id)).admitted_at == original.admitted_at
        await tx.manual.release_read(permit.lease_id)
    erased = await service.reconcile_cleanup(command)
    assert (erased.phase, erased.version) == ("ERASED", 4)
    assert erased.closure_id == pending.intent.closure_id
    assert calls.count("spend") == 1
    assert calls.count("fetch") == 1
    assert not (tmp_path / "issuer" / "original.json").exists()
    assert not list(publication.root.rglob("payloads/*"))


@pytest.mark.parametrize("directory", ["payloads", "attestations"])
async def test_v2_material_loss_is_audited_and_blocks_reuse_after_files_reappear(session_factory, tmp_path, directory):
    from lib.db.models.opportunity import M9EventModel

    async def stop_ready(name):
        if name == "ready-committed":
            raise RuntimeError("leave original ready admission")

    service, command, calls, publication = await service_subject(
        session_factory, tmp_path, boundary=stop_ready, cleanup=True
    )
    acquired = await service.acquire(command)
    assert acquired.state == "RUNNING"
    target = next(publication.root.rglob(directory + "/*"))
    original = target.read_bytes()
    target.unlink()
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await service.reconcile_manual_admission(command)
    async with session_factory() as session:
        events = (
            await session.scalars(select(M9EventModel).where(M9EventModel.event_kind == "MANUAL_MATERIAL_UNAVAILABLE"))
        ).all()
        assert len(events) == 1
        marker = events[0]
        assert marker.aggregate_id == acquired.attempt_id
    target.write_bytes(original)
    before = list(calls)
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await service.reconcile_manual_admission(command)
    assert calls == before
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(acquired.attempt_id)
        assert envelope.phase == "READY"
        assert await tx.manual.get_snapshot_for_attempt(acquired.attempt_id) is None
        assert await tx.manual.list_checkpoints(acquired.attempt_id) == ()
        for operational in (False, True):
            with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
                await tx.manual.begin_read(
                    acquired.attempt_id, expected_envelope_version=envelope.version, operational=operational
                )
    erased = await service.reconcile_cleanup(command)
    assert erased.phase == "ERASED"
    assert "fetch" not in calls
    assert calls.count("admit") == 1


@pytest.mark.parametrize(
    ("stop", "version", "private_erased", "public_erased"),
    [
        ("cleanup-fence-before-commit", None, False, False),
        ("cleanup-fenced-committed", 1, False, False),
        ("cleanup-publication-fenced", 1, False, False),
        ("cleanup-drain-before-commit", 1, False, False),
        ("cleanup-drained-committed", 2, False, False),
        ("cleanup-private-erasure-returned", 2, True, False),
        ("cleanup-authorization-before-commit", 2, True, False),
        ("cleanup-authorized-committed", 3, True, False),
        ("cleanup-public-erasure-returned", 3, True, True),
        ("cleanup-completion-before-commit", 3, True, True),
        ("cleanup-erased-committed", 4, True, True),
    ],
)
async def test_v2_cleanup_retry_reconciles_physical_erasure_with_sql_rollback(
    session_factory, tmp_path, stop, version, private_erased, public_erased
):
    from lib.db.models.opportunity_manual_admission import M9ManualClosureIntentModel

    reached = []

    async def interrupt(name):
        if name == stop and not reached:
            reached.append(name)
            raise RuntimeError("CLEANUP_ACK_CANARY")

    service, command, calls, publication = await service_subject(
        session_factory, tmp_path, boundary=interrupt, cleanup=True
    )
    acquired = await service.acquire(command)
    assert acquired.state == "SUCCEEDED"
    interrupted = None
    if version is None:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await service.reconcile_cleanup(command)
    else:
        interrupted = await service.reconcile_cleanup(command)
        assert interrupted.version == version
        assert interrupted.phase == ("ERASED" if version == 4 else "CLEANUP_PENDING")
    assert reached == [stop]
    assert (not (tmp_path / "issuer" / "original.json").exists()) == private_erased
    assert (not list(publication.root.rglob("payloads/*"))) == public_erased
    async with service.store.transaction() as tx:
        pending = await tx.manual.get_cleanup_state(acquired.attempt_id)
        envelope = await tx.manual.get_envelope(acquired.attempt_id)
        assert envelope.phase == ("READY" if version is None else "ERASED" if version == 4 else "CLEANUP_PENDING")
        assert (pending is None) == (version is None)
        if pending is not None:
            assert interrupted is not None
            assert pending.intent == interrupted
    async with session_factory() as session:
        row = await session.scalar(select(M9ManualClosureIntentModel))
        retained = row.body_json["metadata"] if row is not None else None
    erased = await service.reconcile_cleanup(command)
    assert (erased.phase, erased.version) == ("ERASED", 4)
    if pending is not None:
        assert erased.closure_id == pending.intent.closure_id
        assert erased.fenced_at == pending.intent.fenced_at
    async with session_factory() as session:
        row = (await session.scalars(select(M9ManualClosureIntentModel))).one()
        completed = row.body_json["metadata"]
    if retained is not None:
        for field in ("proof", "public_key", "reads_drained_at", "authorized_at", "receipt", "finished_at"):
            if retained.get(field) is not None:
                assert completed[field] == retained[field]
    assert completed["proof"]["metadata"]["closure_id"] == erased.closure_id
    assert completed["receipt"]["closure"]["closure_id"] == erased.closure_id
    assert not (tmp_path / "issuer" / "original.json").exists()
    assert not list(publication.root.rglob("payloads/*"))
    assert calls.count("fetch") == calls.count("admit") == 1
    before = list(calls)
    service.cleanup = None
    assert await service.reconcile_cleanup(command) == erased
    assert calls == before


@pytest.mark.parametrize("terminal", [False, True])
@pytest.mark.parametrize("lost", ["admission", "intent", "both"])
async def test_v2_cleanup_uses_retained_sql_anchor_without_recreating_ready(session_factory, tmp_path, terminal, lost):
    from sqlalchemy import delete

    from lib.db.models.opportunity_manual_admission import (
        M9ManualAdmissionModel,
        M9ManualPublicationIntentModel,
    )

    async def stop_ready(name):
        if not terminal and name == "ready-committed":
            raise RuntimeError("original READY retained before dispatch")

    service, command, calls, publication = await service_subject(
        session_factory, tmp_path, boundary=stop_ready, cleanup=True
    )
    acquired = await service.acquire(command)
    assert acquired.state == ("SUCCEEDED" if terminal else "RUNNING")
    async with service.store.transaction() as tx:
        original = await tx.manual.get_envelope(acquired.attempt_id)
    async with session_factory() as session, session.begin():
        if lost in ("admission", "both"):
            await session.execute(delete(M9ManualAdmissionModel))
        if lost in ("intent", "both"):
            await session.execute(delete(M9ManualPublicationIntentModel))
    async with service.store.transaction() as tx:
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await tx.manual.get_envelope(acquired.attempt_id)
    before = list(calls)
    if lost == "both":
        with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
            await service.reconcile_cleanup(command)
        assert calls == before
        assert (tmp_path / "issuer" / "original.json").exists()
        assert list(publication.root.rglob("payloads/*"))
        return
    erased = await service.reconcile_cleanup(command)
    assert (erased.phase, erased.version) == ("ERASED", 4)
    async with service.store.transaction() as tx:
        retained = await tx.manual.get_envelope(acquired.attempt_id)
        assert retained.phase == "ERASED"
        assert retained.admitted_at == original.admitted_at
        assert retained.deadlines == original.deadlines
        assert retained.objects == original.objects
        assert retained.version == original.version + 2
    assert calls.count("admit") == before.count("admit")
    assert calls.count("fetch") == before.count("fetch")
    assert calls.count("read") == before.count("read")
    assert calls.count("spend") == 1
    assert not (tmp_path / "issuer" / "original.json").exists()
    assert not list(publication.root.rglob("payloads/*"))


@pytest.mark.parametrize("peer_shape", ["reserved", "ready-with-read"])
async def test_v2_cleanup_preserves_live_shared_upload_then_erases_expired_dependency_group(
    session_factory, tmp_path, peer_shape
):
    from r2.advanced_creative.exploration import uuid7
    from r2.opportunity.manual_admission import AdmissionRequest

    async def stop_ready(name):
        if name == "ready-committed":
            raise RuntimeError("keep original admission before dispatch")

    service, command, calls, publication = await service_subject(
        session_factory, tmp_path, boundary=stop_ready, cleanup=True, refresh_seconds=60, retention_seconds=30
    )
    original_receipt = await service.acquire(command)
    async with service.store.transaction() as tx:
        original = await tx.manual.get_envelope(original_receipt.attempt_id)
    peer = command.model_copy(update={"context": command.context.model_copy(update={"command_id": uuid7()})})
    assert service.descriptor is not None
    async with service.store.transaction() as tx:
        prepared, created = await tx.manual.prepare(peer, attempt_id=uuid7(), descriptor=service.descriptor)
        assert created
        running = await tx.manual.start(prepared.attempt_id, expected_attempt_version=prepared.attempt_version)
        request = AdmissionRequest.model_validate(
            {
                **original.request.model_dump(),
                "context": peer.context,
                "request_digest": running.request_digest,
                "attempt_id": running.attempt_id,
                "attempt_version": running.attempt_version,
                "publication_key": "original-peer-publication",
            }
        )
        reserved = await tx.manual.reserve(request, expected_attempt_version=running.attempt_version)
    peer_original = reserved
    if peer_shape == "ready-with-read":
        code, result = await issuer_process(
            tmp_path / "issuer",
            "admit",
            request=request.model_dump(mode="json"),
            publication_root=str(publication.root),
        )
        assert code == 0, result
        async with service.store.transaction() as tx:
            peer_original = await tx.manual.attach(
                PublishedAdmission.model_validate(result["publication"]), expected_envelope_version=reserved.version
            )
            await tx.manual.begin_read(
                running.attempt_id, expected_envelope_version=peer_original.version, operational=False
            )
    with pytest.raises(OpportunityError, match="M9_INVALIDATION_INCOMPLETE"):
        await service.reconcile_cleanup(command)
    assert "spend" not in calls
    assert (tmp_path / "issuer" / "original.json").exists()
    assert list(publication.root.rglob("payloads/*"))
    async with service.store.transaction() as tx:
        assert await tx.manual.get_cleanup_state(original_receipt.attempt_id) is None
        assert await tx.manual.get_envelope(running.attempt_id) == peer_original
        now = await tx.profiles.database_time()
    deadline = min(c.retention_due_at for c in request.original_clocks if c.retention_due_at is not None)
    await asyncio.sleep(max(0, (deadline - now).total_seconds()) + 0.05)
    erased = await service.reconcile_cleanup(command)
    assert erased.phase == "ERASED"
    async with service.store.transaction() as tx:
        for attempt_id, prior in ((original_receipt.attempt_id, original), (running.attempt_id, peer_original)):
            current = await tx.manual.get_envelope(attempt_id)
            assert current.phase == "ERASED"
            assert current.admitted_at == prior.admitted_at
            assert current.objects == prior.objects
            state = await tx.manual.get_cleanup_state(attempt_id)
            assert state.intent == erased
    assert calls.count("spend") == 1
    assert "fetch" not in calls
    assert not (tmp_path / "issuer" / "original.json").exists()
    assert not list(publication.root.rglob("payloads/*"))


@pytest.mark.parametrize("hold_object_guard", [False, True])
async def test_v2_cleanup_rechecks_newly_discovered_public_refs_before_deleting_a_shared_object(
    session_factory, tmp_path, hold_object_guard
):
    import struct

    from sqlalchemy import text

    from lib.db.models.opportunity_manual_admission import M9ManualClosureIntentModel
    from r2.advanced_creative.digests import digest_canonical
    from r2.advanced_creative.exploration import uuid7
    from r2.opportunity.manual_admission import AdmissionRequest

    async def stop_publication(name):
        if name == "publication-returned":
            raise RuntimeError("original publication not attached")

    service, command, calls, publication = await service_subject(
        session_factory, tmp_path, boundary=stop_publication, cleanup=True
    )
    acquired = await service.acquire(command)
    async with service.store.transaction() as tx:
        original = await tx.manual.get_envelope(acquired.attempt_id)
    assert original.phase == "RESERVED"
    code, result = await issuer_process(
        tmp_path / "issuer",
        "admit",
        request=original.request.model_dump(mode="json"),
        publication_root=str(publication.root),
    )
    assert code == 0, result
    published = PublishedAdmission.model_validate(result["publication"])
    peer = command.model_copy(update={"context": command.context.model_copy(update={"command_id": uuid7()})})
    assert service.descriptor is not None
    async with service.store.transaction() as tx:
        prepared, _ = await tx.manual.prepare(peer, attempt_id=uuid7(), descriptor=service.descriptor)
        running = await tx.manual.start(prepared.attempt_id, expected_attempt_version=prepared.attempt_version)
        request = AdmissionRequest.model_validate(
            {
                **original.request.model_dump(),
                "context": peer.context,
                "request_digest": running.request_digest,
                "attempt_id": running.attempt_id,
                "attempt_version": running.attempt_version,
                "publication_key": uuid7(),
                "opaque_upload_id": "independent-sql-upload",
            }
        )
        reserved = await tx.manual.reserve(request, expected_attempt_version=running.attempt_version)
        shared = PublishedAdmission.model_validate(
            {
                **published.model_dump(),
                "request": request,
                "publication_key": request.publication_key,
            }
        )
        peer_ready = await tx.manual.attach(shared, expected_envelope_version=reserved.version)
    if hold_object_guard:
        holder = session_factory()
        cleanup_task = None
        try:
            await holder.begin()
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            digest = digest_canonical(
                {
                    "domain": "m9.manual-object-lock.v1",
                    "user_id": "u1",
                    "project_name": "show-a",
                    "ref": published.objects[0].payload_ref,
                }
            )
            first, second = struct.unpack(">ii", bytes.fromhex(digest.removeprefix("sha256:"))[:8])
            await holder.execute(
                text("SELECT pg_advisory_xact_lock(:first,:second)"), {"first": first, "second": second}
            )
            cleanup_task = asyncio.create_task(service.reconcile_cleanup(command))
            async with asyncio.timeout(20):
                while True:
                    async with session_factory() as observer:
                        waiting = await observer.scalar(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                "WHERE :holder = ANY(pg_blocking_pids(pid)))"
                            ),
                            {"holder": holder_pid},
                        )
                    if waiting:
                        break
                    if cleanup_task.done():
                        pytest.fail("expanded custody refs did not wait for their native object guard")
                    await asyncio.sleep(0.01)
            assert not cleanup_task.done()
            assert calls.count("spend") == 1
            assert list(publication.root.rglob("payloads/*"))
            async with session_factory() as observer:
                assert await observer.scalar(select(M9ManualClosureIntentModel.version)) == 2
            await holder.commit()
            with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
                await cleanup_task
        finally:
            await holder.rollback()
            await holder.close()
            if cleanup_task is not None and not cleanup_task.done():
                cleanup_task.cancel()
                await asyncio.gather(cleanup_task, return_exceptions=True)
    else:
        with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
            await service.reconcile_cleanup(command)
    assert calls.count("spend") == 1
    assert list(publication.root.rglob("payloads/*"))
    async with service.store.transaction() as tx:
        assert await tx.manual.get_envelope(running.attempt_id) == peer_ready
    async with service.store.transaction() as tx:
        state = await tx.manual.get_cleanup_state(acquired.attempt_id)
        assert (state.intent.phase, state.intent.version) == ("CLEANUP_PENDING", 2)
        assert state.proof is None


@pytest.mark.parametrize("reconstruction", [False, True])
async def test_v2_snapshot_readers_verify_original_material_and_keep_provenance(
    session_factory, tmp_path, reconstruction
):
    from r2.contracts.opportunity import OpportunityIdentityRead, SnapshotReadPage

    async def stop_after_claim(name):
        if reconstruction and name == "claim-committed":
            raise ConnectionError("synthetic lost claim acknowledgement")

    service, command, calls, _ = await service_subject(session_factory, tmp_path, boundary=stop_after_claim)
    receipt = await service.acquire(command)
    if reconstruction:
        receipt = await service.reconcile_manual_admission(command)
    assert len(receipt.snapshot_ids) == 1
    before = calls.count("fetch"), calls.count("admit"), calls.count("read")
    request = OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    view = await service.get_snapshot(request)
    assert view.protocol_version == "m9.acquisition.v2"
    assert view.snapshot_view.snapshot.snapshot_id == receipt.snapshot_ids[0]
    assert view.snapshot_view.validity.state == "CURRENT"
    assert view.snapshot_view.validity.erasable_content_available is True
    assert view.provenance.origin == (
        "LOCAL_ADMISSION_RECONSTRUCTION" if reconstruction else "SOURCE_RESPONSE_VERIFIED"
    )
    assert view.provenance.admitted_at == view.snapshot_view.snapshot.capture_completed_at
    assert view.snapshot_view.snapshot.provider_observed_at is None
    page = await service.list_snapshots(
        SnapshotReadPage(user_id="u1", project_name="show-a", query_id=command.query_id, after_id=None, limit=10)
    )
    assert page == (view,)
    assert (calls.count("fetch"), calls.count("admit")) == before[:2]
    assert calls.count("read") > before[2]


@pytest.mark.parametrize("foreign", ["user_id", "project_name", "identity"])
async def test_v2_snapshot_read_scope_and_missing_identity_never_open_material(session_factory, tmp_path, foreign):
    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    receipt = await service.acquire(command)
    body = {"user_id": "u1", "project_name": "show-a", "identity": receipt.snapshot_ids[0]}
    body[foreign] = "foreign"
    before = list(calls)
    if foreign == "identity":
        with pytest.raises(LookupError):
            await service.get_snapshot(OpportunityIdentityRead(**body))
    else:
        with pytest.raises(OpportunityError, match="M9_SOURCE_POLICY_FORBIDDEN"):
            await service.get_snapshot(OpportunityIdentityRead(**body))
    assert calls == before


async def await_snapshot_deadline(service, attempt_id, field):
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(attempt_id)
        deadline = getattr(envelope.deadlines, field)
    assert deadline is not None
    async with asyncio.timeout(50):
        while True:
            async with service.store.transaction() as tx:
                now = await tx.profiles.database_time()
            if now >= deadline:
                return
            reached = asyncio.Event()
            timer = asyncio.get_running_loop().call_later((deadline - now).total_seconds(), reached.set)
            try:
                await reached.wait()
            finally:
                timer.cancel()


async def test_v2_snapshot_history_becomes_stale_then_unavailable_at_original_deadlines(session_factory, tmp_path):
    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, _ = await service_subject(
        session_factory, tmp_path, refresh_seconds=20, retention_seconds=35
    )
    receipt = await service.acquire(command)
    request = OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    await await_snapshot_deadline(service, receipt.attempt_id, "refresh_due_at")
    stale = await service.get_snapshot(request)
    assert stale.snapshot_view.validity.state == "STALE"
    assert stale.snapshot_view.validity.erasable_content_available is True
    await await_snapshot_deadline(service, receipt.attempt_id, "retention_due_at")
    before = list(calls)
    expired = await service.get_snapshot(request)
    assert expired.snapshot_view.validity.state == "STALE"
    assert expired.snapshot_view.validity.erasable_content_available is False
    assert expired.snapshot_view.snapshot == stale.snapshot_view.snapshot
    assert expired.provenance == stale.provenance
    assert calls == before


async def test_v2_erased_snapshot_history_never_reopens_material(session_factory, tmp_path):
    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, _ = await service_subject(session_factory, tmp_path, cleanup=True)
    receipt = await service.acquire(command)
    erased = await service.reconcile_cleanup(command)
    assert erased.phase == "ERASED"
    before = list(calls)
    view = await service.get_snapshot(
        OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    )
    assert view.snapshot_view.validity.state == "STALE"
    assert view.snapshot_view.validity.erasable_content_available is False
    assert view.provenance.snapshot_id == receipt.snapshot_ids[0]
    assert calls == before


async def record_known_source_revocation(service, command, *, entered=None, held=None, release=None):
    from r2.advanced_creative.exploration import uuid7
    from r2.contracts.opportunity import PermissionDisposition
    from r2.opportunity.digests import (
        digest_capability_evaluation,
        digest_capability_grant,
        digest_condition_evidence,
    )

    async with service.store.transaction() as tx:
        if entered is not None:
            from sqlalchemy import text

            entered.set_result(await tx.session.scalar(text("SELECT pg_backend_pid()")))
        query = await tx.queries.get_exact(command.query_id, command.query_revision)
        grant = await tx.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
        original = await tx.capabilities.get_evaluation(query.capability_evaluation_id)
        grant = grant.model_copy(
            update={"grant_version": grant.grant_version + 1, "permission": PermissionDisposition.FORBIDDEN}
        )
        grant = grant.model_copy(update={"grant_digest": digest_capability_grant(grant)})
        evaluation = original.model_copy(
            update={
                "evaluation_id": uuid7(),
                "grant_version": grant.grant_version,
                "grant_digest": grant.grant_digest,
                "effective_permission": PermissionDisposition.FORBIDDEN,
                "condition_evidence_digest": digest_condition_evidence(
                    grant_id=grant.grant_id,
                    grant_version=grant.grant_version,
                    grant_digest=grant.grant_digest,
                    condition_evidence=original.condition_evidence,
                ),
            }
        )
        evaluation = evaluation.model_copy(
            update={"evaluation_digest": digest_capability_evaluation(evaluation, actor_id=command.context.actor_id)}
        )
        await tx.capabilities.consume(grant, evaluation, actor_id=command.context.actor_id)
        if held is not None:
            held.set()
        if release is not None:
            await release.wait()


async def test_v2_snapshot_reader_refuses_current_from_known_newer_source_revocation(session_factory, tmp_path):
    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    receipt = await service.acquire(command)
    await record_known_source_revocation(service, command)
    before = list(calls)
    view = await service.get_snapshot(
        OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    )
    assert view.snapshot_view.validity.state == "STALE"
    assert view.snapshot_view.validity.erasable_content_available is False
    assert calls == before


async def test_v2_snapshot_reader_checks_the_configured_source_grant_without_issuing_evaluation(
    session_factory, tmp_path
):
    from r2.contracts.opportunity import OpportunityIdentityRead, PermissionDisposition
    from r2.opportunity.digests import digest_capability_grant

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    receipt = await service.acquire(command)
    trusted = service.capabilities

    class KnownRevokedSource:
        async def resolve_grant(self, ref):
            original = await trusted.resolve_grant(ref)
            changed = original.model_copy(
                update={"grant_version": original.grant_version + 1, "permission": PermissionDisposition.FORBIDDEN}
            )
            return changed.model_copy(update={"grant_digest": digest_capability_grant(changed)})

        async def evaluate(self, request):
            raise AssertionError("a snapshot GET cannot issue a capability evaluation")

    service.capabilities = KnownRevokedSource()
    before = calls.count("read")
    view = await service.get_snapshot(
        OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    )
    assert view.snapshot_view.validity.state == "STALE"
    assert view.snapshot_view.validity.erasable_content_available is False
    assert calls.count("read") == before


@pytest.mark.parametrize("change", ["revocation", "retention", "erase-fence"])
async def test_v2_snapshot_read_rechecks_authority_after_verified_material(session_factory, tmp_path, change):
    from r2.contracts.opportunity import OpportunityIdentityRead

    armed = False
    remaining = 0

    async def pause_cleanup(name):
        if armed and name == "cleanup-fenced-committed":
            raise ConnectionError("synthetic lost acknowledgement after the erasure fence")

    async def after_verified_read():
        nonlocal remaining
        if not armed:
            return
        remaining -= 1
        if remaining != 0:
            return
        if change == "revocation":
            await record_known_source_revocation(service, command)
        elif change == "retention":
            await await_snapshot_deadline(service, receipt.attempt_id, "retention_due_at")
        else:
            closure = await service.reconcile_cleanup(command)
            assert closure.version == 1

    service, command, calls, _ = await service_subject(
        session_factory,
        tmp_path,
        boundary=pause_cleanup,
        read_boundary=after_verified_read,
        refresh_seconds=20 if change == "retention" else 60,
        retention_seconds=35 if change == "retention" else 120,
        cleanup=True,
    )
    receipt = await service.acquire(command)
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(receipt.attempt_id)
        remaining = len(envelope.objects)
    armed = True
    view = await service.get_snapshot(
        OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    )
    armed = False
    assert remaining == 0
    assert view.snapshot_view.validity.state == "STALE"
    assert view.snapshot_view.validity.erasable_content_available is False
    assert calls.count("fetch") == calls.count("admit") == 1
    if change == "erase-fence":
        assert (await service.reconcile_cleanup(command)).phase == "ERASED"


async def test_v2_snapshot_reader_marks_forged_material_unavailable_even_after_file_restore(session_factory, tmp_path):
    import hashlib

    from lib.db.models.opportunity import M9EventModel
    from r2.advanced_creative.digests import canonical_json_bytes
    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, publication = await service_subject(session_factory, tmp_path, cleanup=True)
    receipt = await service.acquire(command)
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(receipt.attempt_id)
    obj = next(o for o in envelope.objects if o.evidence_kind == "raw-page")
    payload = next(publication.root.rglob(obj.payload_ref.rsplit(":", 1)[1] + ".bin"))
    integrity = next(publication.root.rglob(obj.integrity_ref.rsplit(":", 1)[1] + ".json"))
    old_payload, old_integrity = payload.read_bytes(), integrity.read_bytes()
    altered = b"PRIVATE_NATIVE_SOURCE_CANARY"
    payload.write_bytes(altered)
    integrity.write_bytes(
        canonical_json_bytes(
            {
                "payload_ref": obj.payload_ref,
                "integrity_ref": obj.integrity_ref,
                "digest": "sha256:" + hashlib.sha256(altered).hexdigest(),
            }
        )
    )
    request = OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH") as refused:
        await service.get_snapshot(request)
    assert "PRIVATE_NATIVE_SOURCE_CANARY" not in str(refused.value)
    payload.write_bytes(old_payload)
    integrity.write_bytes(old_integrity)
    before = list(calls)
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await service.get_snapshot(request)
    assert await service.acquire(command) == receipt
    assert calls == before
    async with session_factory() as session:
        events = await session.scalar(
            select(func.count())
            .select_from(M9EventModel)
            .where(
                M9EventModel.aggregate_id == receipt.attempt_id,
                M9EventModel.event_kind == "MANUAL_MATERIAL_UNAVAILABLE",
            )
        )
    assert events == 1
    assert (await service.reconcile_cleanup(command)).phase == "ERASED"


async def test_v2_snapshot_reader_sanitizes_transport_failure_and_retries_without_dispatch(session_factory, tmp_path):
    from r2.contracts.opportunity import OpportunityIdentityRead

    armed = False

    async def lose_read_ack():
        if armed:
            raise ConnectionError("SYNTHETIC_PRIVATE_RESPONSE_CANARY")

    service, command, calls, _ = await service_subject(session_factory, tmp_path, read_boundary=lose_read_ack)
    receipt = await service.acquire(command)
    request = OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    armed = True
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING") as refused:
        await service.get_snapshot(request)
    assert "SYNTHETIC_PRIVATE_RESPONSE_CANARY" not in str(refused.value)
    armed = False
    recovered = await service.get_snapshot(request)
    assert recovered.snapshot_view.validity.state == "CURRENT"
    assert recovered.provenance.snapshot_id == receipt.snapshot_ids[0]
    assert calls.count("fetch") == calls.count("admit") == 1


async def test_v2_snapshot_permission_changed_while_resolving_grant_blocks_first_material_read(
    session_factory, tmp_path
):
    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    receipt = await service.acquire(command)
    trusted = service.capabilities

    class ChangedDuringResolution:
        async def resolve_grant(self, ref):
            original = await trusted.resolve_grant(ref)
            await record_known_source_revocation(service, command)
            return original

        async def evaluate(self, request):
            raise AssertionError("snapshot reads cannot issue evaluations")

    service.capabilities = ChangedDuringResolution()
    before = calls.count("read")
    view = await service.get_snapshot(
        OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    )
    assert view.snapshot_view.validity.state == "STALE"
    assert view.snapshot_view.validity.erasable_content_available is False
    assert calls.count("read") == before


async def test_v2_known_newer_source_revocation_prevents_admission_and_dispatch(session_factory, tmp_path):
    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    await record_known_source_revocation(service, command)
    with pytest.raises(OpportunityError, match="M9_SOURCE_CAPABILITY_UNAVAILABLE"):
        await service.acquire(command)
    assert "fetch" not in calls
    assert "admit" not in calls
    async with service.store.transaction() as tx:
        attempt = await tx.manual.get_for_command(command)
        assert attempt is None


async def wait_for_capability_blocker(session_factory, waiting, blocking, task):
    from sqlalchemy import text

    async with asyncio.timeout(10), session_factory() as observer:
        while True:
            blockers = await observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting})
            if blocking in blockers:
                return
            if task.done():
                await task
                pytest.fail("a newer grant committed while the original grant was being validated")


async def test_v2_snapshot_authority_guard_serializes_a_newer_grant_writer(session_factory, tmp_path):
    from sqlalchemy import text

    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    receipt = await service.acquire(command)
    async with service.store.transaction() as tx:
        envelope = await tx.manual.get_envelope(receipt.attempt_id)
    start = asyncio.Event()
    writer_pid = asyncio.get_running_loop().create_future()

    async def write_revocation():
        await start.wait()
        await record_known_source_revocation(service, command, entered=writer_pid)

    writer = asyncio.create_task(write_revocation())
    try:
        async with service.store.transaction() as tx:
            reader_pid = await tx.session.scalar(text("SELECT pg_backend_pid()"))
            await tx.manual.require_snapshot_read(
                receipt.attempt_id, expected_envelope_version=envelope.version, operational=True
            )
            start.set()
            waiting = await asyncio.wait_for(writer_pid, timeout=10)
            await wait_for_capability_blocker(session_factory, waiting, reader_pid, writer)
    finally:
        start.set()
        await asyncio.gather(writer, return_exceptions=True)
    await writer
    before = list(calls)
    view = await service.get_snapshot(
        OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
    )
    assert view.snapshot_view.validity.state == "STALE"
    assert view.snapshot_view.validity.erasable_content_available is False
    assert calls == before


async def test_v2_snapshot_waiting_for_newer_grant_commit_refuses_current_without_material_io(
    session_factory, tmp_path
):
    from uuid import uuid4

    from sqlalchemy import text

    from r2.contracts.opportunity import OpportunityIdentityRead

    service, command, calls, _ = await service_subject(session_factory, tmp_path)
    receipt = await service.acquire(command)
    held, release = asyncio.Event(), asyncio.Event()
    writer_pid = asyncio.get_running_loop().create_future()
    writer = asyncio.create_task(
        record_known_source_revocation(service, command, entered=writer_pid, held=held, release=release)
    )
    reader = None
    trusted = service.store
    tag = "m9-snapshot-head-" + uuid4().hex

    class TaggedReader:
        @asynccontextmanager
        async def transaction(self):
            async with trusted.transaction() as tx:
                await tx.session.execute(text("SELECT set_config('application_name',:tag,true)"), {"tag": tag})
                yield tx

    try:
        await asyncio.wait_for(held.wait(), timeout=10)
        blocking = await writer_pid
        service.store = TaggedReader()
        before = list(calls)
        async with asyncio.timeout(10), session_factory() as observer:
            await observer.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"))
            reader = asyncio.create_task(
                service.get_snapshot(
                    OpportunityIdentityRead(user_id="u1", project_name="show-a", identity=receipt.snapshot_ids[0])
                )
            )
            while True:
                await observer.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = await observer.scalar(
                    text(
                        "SELECT pid FROM pg_stat_activity WHERE application_name=:tag "
                        "AND :blocking = ANY(pg_blocking_pids(pid))"
                    ),
                    {"tag": tag, "blocking": blocking},
                )
                if waiting is not None:
                    break
                if reader.done():
                    await reader
                    pytest.fail("snapshot read did not wait for the newer grant authority")
        release.set()
        await writer
        view = await reader
        assert view.snapshot_view.validity.state == "STALE"
        assert view.snapshot_view.validity.erasable_content_available is False
        assert calls == before
    finally:
        release.set()
        await asyncio.gather(writer, *([] if reader is None else [reader]), return_exceptions=True)
        service.store = trusted


def _http(service, query_service):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
    from server.error_handlers import register_error_handlers
    from server.routers import opportunity_acquisition

    user = CurrentUserInfo(id="u1", sub="human-a", role="user")
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(opportunity_acquisition.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_interactive_user] = lambda: user
    app.dependency_overrides[opportunity_acquisition.acquisition_service_factory] = lambda: lambda _u, _p: service
    app.dependency_overrides[opportunity_acquisition.query_service_factory] = lambda: lambda _u, _p: query_service
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


HTTP_BASE = "/api/v1/projects/show-a/m9/opportunity"


async def test_v2_http_declares_acquires_replays_and_reads_through_the_scoped_service(session_factory, tmp_path):
    parts: dict = {}
    service, command, calls, _ = await service_subject(session_factory, tmp_path, parts=parts)
    declaration, declared = parts["declaration"], parts["declared"]
    async with _http(service, parts["query_service"]) as client:
        replayed = await client.post(
            HTTP_BASE + "/queries",
            json={
                "command_id": declaration.context.command_id,
                "query_id": declaration.query_id,
                "parent_revision": declaration.parent_revision,
                "expected_head_version": declaration.expected_head_version,
                "draft": declaration.draft.model_dump(mode="json"),
            },
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json() == declared.model_dump(mode="json")
        body = {
            "protocol_version": "m9.acquisition.v2",
            "command_id": command.context.command_id,
            "query_id": command.query_id,
            "query_revision": command.query_revision,
            "query_digest": command.query_digest,
            "expected_query_head_version": command.expected_query_head_version,
        }
        first = await client.post(HTTP_BASE + "/acquisitions", json=body)
        assert first.status_code == 200, first.text
        receipt = first.json()
        assert receipt["protocol_version"] == "m9.acquisition.v2"
        assert len(receipt["snapshot_ids"]) == 1
        fetched = calls.count("fetch")
        again = await client.post(HTTP_BASE + "/acquisitions", json=body)
        assert again.content == first.content
        assert calls.count("fetch") == fetched
        conflict = await client.post(HTTP_BASE + "/acquisitions", json={**body, "expected_query_head_version": 9})
        assert conflict.status_code == 409
        assert conflict.json()["diagnostic"]["stop_code"] == "M9_COMMAND_REPLAY_CONFLICT"
        snapshot_id = receipt["snapshot_ids"][0]
        view = await client.get(HTTP_BASE + "/snapshots/" + snapshot_id)
        assert view.status_code == 200, view.text
        assert view.json()["protocol_version"] == "m9.acquisition.v2"
        assert view.json()["provenance"]["snapshot_id"] == snapshot_id
        assert view.json()["snapshot_view"]["validity"]["state"] == "CURRENT"
        page = await client.get(HTTP_BASE + "/snapshots", params={"query_id": command.query_id})
        assert page.json() == [view.json()]
        query = await client.get(HTTP_BASE + "/queries/" + command.query_id)
        exact = await client.get(HTTP_BASE + "/queries/" + command.query_id, params={"revision": 1})
        assert query.status_code == exact.status_code == 200
        assert query.json() == exact.json() == declared.query.model_dump(mode="json")
        missing = await client.get(HTTP_BASE + "/queries/019a0000-0000-7000-8000-00000000dead")
        assert missing.status_code == 404
        assert (await client.get(HTTP_BASE + "/snapshots/019a0000-0000-7000-8000-00000000dead")).status_code == 404
        grants = await client.get(HTTP_BASE + "/capabilities")
        assert grants.status_code == 200
        assert [g["grant_id"] for g in grants.json()] == [declared.query.capability_grant_id]
        assert grants.json()[0]["grant_version"] == declared.query.capability_grant_version


async def test_v2_http_on_an_unconfigured_host_refuses_before_source_or_custody_contact(session_factory, tmp_path):
    from server.auth import CurrentUserInfo
    from server.services.opportunity_acquisition_v2 import build_acquisition_service_v2

    parts: dict = {}
    service, command, calls, _ = await service_subject(session_factory, tmp_path, parts=parts)
    bare = build_acquisition_service_v2(
        session_factory, current_user=CurrentUserInfo(id="u1", sub="human-a", role="user"), project_name="show-a"
    )
    async with _http(bare, parts["query_service"]) as client:
        response = await client.post(
            HTTP_BASE + "/acquisitions",
            json={
                "protocol_version": "m9.acquisition.v2",
                "command_id": command.context.command_id,
                "query_id": command.query_id,
                "query_revision": command.query_revision,
                "query_digest": command.query_digest,
                "expected_query_head_version": command.expected_query_head_version,
            },
            headers={"Accept-Language": "vi"},
        )
        assert response.status_code == 503
        assert response.json()["diagnostic"]["stop_code"] == "M9_SOURCE_CAPABILITY_UNAVAILABLE"
        assert response.json()["detail"].startswith("Nguồn này chưa sẵn sàng")
        assert calls == []
        receipt = await service.acquire(command)
        reads = calls.count("read")
        read = await client.get(HTTP_BASE + "/snapshots/" + receipt.snapshot_ids[0])
        assert calls.count("read") == reads
        assert read.status_code == 503
        assert read.json()["diagnostic"]["stop_code"] == "M9_SOURCE_CAPABILITY_UNAVAILABLE"
        assert (await client.get(HTTP_BASE + "/queries/" + command.query_id)).status_code == 200
