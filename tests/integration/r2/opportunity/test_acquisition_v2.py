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


async def service_subject(factory, tmp_path, *, boundary=None):
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
            "refresh_due_at": (now + timedelta(seconds=min(r.refresh_interval_seconds or 60, 60))).isoformat(),
            "retention_due_at": (now + timedelta(seconds=min(r.retention_seconds or 120, 120))).isoformat(),
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
