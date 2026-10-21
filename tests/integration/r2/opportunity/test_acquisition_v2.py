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


async def service_subject(factory, tmp_path, *, boundary=None, refresh_seconds=60, retention_seconds=120):
    module = importlib.import_module("r2.opportunity.acquisition_v2")
    host = importlib.import_module("server.services.opportunity_acquisition_v2")
    old, declaration, capabilities = await acquisition_service_fixture(factory, tmp_path)
    declared = await old.declare_query(declaration)
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
            return await publication.read_verified(envelope, object_ref=object_ref, permit=permit)

        async def delete_exact(self, closure):
            assert active.get() == 0
            return await publication.delete_exact(closure)

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
