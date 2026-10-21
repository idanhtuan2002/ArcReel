"""Acquisition with original manual custody committed before source dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from pydantic import Field, model_validator

from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.opportunity import (
    AttemptOutcomeReason,
    CapabilityEvaluationRequest,
    CoverageState,
    EffectiveCapabilityEvaluation,
    EvidenceDataClassClock,
    M9ContractModel,
    NormalizedSourceObservation,
    SnapshotPage,
    SourceCapabilityGrant,
    SourceDataRule,
    SourcePageRequest,
    SourcePageResult,
    SourceQuery,
    SourceSnapshot,
)
from r2.contracts.opportunity_acquisition_v2 import (
    AcquireSourceQueryV2,
    AcquisitionAttemptV2,
    AcquisitionReceiptV2,
    AttemptStateV2,
    SnapshotOriginV2,
    SnapshotProvenanceV2,
)
from r2.opportunity.acquisition import (
    AcquisitionProfileReadPort,
    AcquisitionQueryPort,
    NativeFieldMaterial,
    PageCheckpoint,
    verified_query,
)
from r2.opportunity.capabilities import validate_capability
from r2.opportunity.digests import digest_source_observation, digest_source_snapshot
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import (
    AdmissionEnvelope,
    AdmissionReadPermit,
    AdmissionRequest,
    DispatchClaim,
    FrozenManualBinding,
    ManualBindingDescriptor,
    ManualBindingRegistry,
    PublishedAdmission,
)
from r2.opportunity.normalization import normalize_manual_page
from r2.opportunity.ports import SourceCapabilityPort


class ManualUploadMetadata(M9ContractModel):
    """Original host provisioning, independent of incoming acquisition commands."""

    user_id: str
    project_name: str
    opaque_upload_id: str
    upload_version: int = Field(ge=1, strict=True)
    data_rules: tuple[SourceDataRule, ...] = Field(min_length=1)
    original_clocks: tuple[EvidenceDataClassClock, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def exact_classes(self) -> ManualUploadMetadata:
        rules = {r.data_class for r in self.data_rules}
        clocks = {c.data_class for c in self.original_clocks}
        if rules != clocks or len(rules) != len(self.data_rules) or len(clocks) != len(self.original_clocks):
            raise ValueError("original upload metadata requires exact class coverage")
        return self


class ManualAcquisitionRepositoryPort(Protocol):
    async def get_for_command(self, command: AcquireSourceQueryV2) -> AcquisitionAttemptV2 | None: ...
    async def get_attempt(self, attempt_id: str) -> AcquisitionAttemptV2 | None: ...
    async def get_descriptor(self, attempt_id: str) -> ManualBindingDescriptor | None: ...
    async def get_current_receipt(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2 | None: ...
    async def prepare(
        self, command: AcquireSourceQueryV2, *, attempt_id: str, descriptor: ManualBindingDescriptor
    ) -> tuple[AcquisitionAttemptV2, bool]: ...
    async def start(self, attempt_id: str, *, expected_attempt_version: int) -> AcquisitionAttemptV2: ...
    async def get_envelope(self, attempt_id: str) -> AdmissionEnvelope | None: ...
    async def reserve(self, request: AdmissionRequest, *, expected_attempt_version: int) -> AdmissionEnvelope: ...
    async def attach(self, publication: PublishedAdmission, *, expected_envelope_version: int) -> AdmissionEnvelope: ...
    async def claim_dispatch(
        self, attempt_id: str, *, expected_attempt_version: int, expected_envelope_version: int
    ) -> DispatchClaim: ...
    async def begin_read(
        self, attempt_id: str, *, expected_envelope_version: int, operational: bool
    ) -> AdmissionReadPermit: ...
    async def release_read(self, lease_id: str) -> None: ...
    async def append_checkpoint(
        self, attempt_id: str, checkpoint: PageCheckpoint, *, expected_attempt_version: int
    ) -> PageCheckpoint: ...
    async def list_checkpoints(self, attempt_id: str) -> tuple[PageCheckpoint, ...]: ...
    async def append_snapshot(
        self, snapshot: SourceSnapshot, provenance: SnapshotProvenanceV2, *, expected_attempt_version: int
    ) -> None: ...
    async def get_snapshot_for_attempt(self, attempt_id: str) -> tuple[SourceSnapshot, SnapshotProvenanceV2] | None: ...
    async def append_observation(
        self, observation: NormalizedSourceObservation, *, expected_attempt_version: int
    ) -> None: ...
    async def mark_outcome_unknown(self, attempt_id: str, *, expected_attempt_version: int) -> AcquisitionAttemptV2: ...
    async def finish_acquisition(
        self,
        attempt_id: str,
        *,
        expected_attempt_version: int,
        state: AttemptStateV2,
        reason: AttemptOutcomeReason,
        resolver_id: str,
    ) -> AcquisitionReceiptV2: ...
    async def close_expired(
        self, attempt_id: str, *, expected_attempt_version: int, resolver_id: str
    ) -> AcquisitionReceiptV2: ...


class ManualAcquisitionTransactionPort(Protocol):
    @property
    def manual(self) -> ManualAcquisitionRepositoryPort: ...
    @property
    def profiles(self) -> AcquisitionProfileReadPort: ...
    @property
    def queries(self) -> AcquisitionQueryPort: ...


class ManualAcquisitionStorePort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[ManualAcquisitionTransactionPort]: ...


class OpportunityAcquisitionServiceV2:
    def __init__(
        self,
        *,
        store: ManualAcquisitionStorePort,
        registry: ManualBindingRegistry | None,
        descriptor: ManualBindingDescriptor | None,
        upload: ManualUploadMetadata | None,
        capabilities: SourceCapabilityPort | None,
        new_id: Callable[[], str],
        user_id: str,
        project_name: str,
        actor_id: str,
        boundary: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self.store, self.registry, self.descriptor, self.upload = store, registry, descriptor, upload
        self.capabilities, self._new_id, self._boundary = capabilities, new_id, boundary
        self.user_id, self.project_name, self.actor_id = user_id, project_name, actor_id

    def _command(self, command: AcquireSourceQueryV2) -> AcquireSourceQueryV2:
        command = AcquireSourceQueryV2.model_validate(command.model_dump())
        if (command.context.user_id, command.context.project_name, command.context.actor_id) != (
            self.user_id,
            self.project_name,
            self.actor_id,
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        return command

    def _binding(self, descriptor: ManualBindingDescriptor | None) -> FrozenManualBinding:
        if self.registry is None or descriptor is None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        if (descriptor.user_id, descriptor.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        return self.registry.resolve_exact(descriptor)

    async def _at(self, name: str) -> None:
        if self._boundary is not None:
            await self._boundary(name)

    async def _current(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        async with self.store.transaction() as tx:
            receipt = await tx.manual.get_current_receipt(command)
            if receipt is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            return receipt

    async def acquire(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        command = self._command(command)
        try:
            return await self._acquire_command(command)
        except OpportunityError:
            try:
                retained = await self._current(command)
                if retained.state in (
                    AttemptStateV2.SUCCEEDED,
                    AttemptStateV2.FAILED,
                    AttemptStateV2.EXPIRED_UNRECOVERABLE,
                ):
                    return retained
            except Exception:
                pass
            raise
        except Exception:
            try:
                return await self._current(command)
            except Exception:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _acquire_command(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        async with self.store.transaction() as tx:
            receipt = await tx.manual.get_current_receipt(command)
            if receipt is not None:
                return receipt
        binding = self._binding(self.descriptor)
        upload = self.upload
        if (
            upload is None
            or (upload.user_id, upload.project_name) != (self.user_id, self.project_name)
            or self.capabilities is None
        ):
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        async with self.store.transaction() as tx:
            query = await tx.queries.get_exact(command.query_id, command.query_revision)
            if query is None or query.parameters.model_dump() != {"import_ref": upload.opaque_upload_id}:
                raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
            attempt, created = await tx.manual.prepare(
                command, attempt_id=self._new_id(), descriptor=binding.descriptor
            )
        if not created:
            return await self._current(command)
        await self._at("planned-committed")
        async with self.store.transaction() as tx:
            attempt = await tx.manual.start(attempt.attempt_id, expected_attempt_version=attempt.attempt_version)
            envelope = await tx.manual.reserve(
                AdmissionRequest(
                    context=command.context,
                    request_digest=attempt.request_digest,
                    query_id=command.query_id,
                    query_revision=command.query_revision,
                    query_digest=command.query_digest,
                    attempt_id=attempt.attempt_id,
                    attempt_version=attempt.attempt_version,
                    descriptor=binding.descriptor,
                    opaque_upload_id=upload.opaque_upload_id,
                    upload_version=upload.upload_version,
                    publication_key=self._new_id(),
                    data_rules=upload.data_rules,
                    original_clocks=upload.original_clocks,
                ),
                expected_attempt_version=attempt.attempt_version,
            )
        await self._at("reserved-committed")
        binding = self._binding(envelope.request.descriptor)
        publication = await binding.upload_admission.admit(envelope.request)
        publication = PublishedAdmission.model_validate(publication.model_dump())
        self._binding(envelope.request.descriptor)
        if publication.request != envelope.request:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        await self._at("publication-returned")
        async with self.store.transaction() as tx:
            envelope = await tx.manual.attach(publication, expected_envelope_version=envelope.version)
        await self._at("ready-committed")
        self._binding(envelope.request.descriptor)
        async with self.store.transaction() as tx:
            claim = await tx.manual.claim_dispatch(
                attempt.attempt_id,
                expected_attempt_version=attempt.attempt_version,
                expected_envelope_version=envelope.version,
            )
            attempt = await tx.manual.get_attempt(attempt.attempt_id)
            envelope = await tx.manual.get_envelope(claim.attempt_id)
            query = await tx.queries.get_exact(command.query_id, command.query_revision)
        if attempt is None or envelope is None or query is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        query = verified_query(query)
        await self._at("claim-committed")
        try:
            grant, evaluation = await self._capability(query)
            self._binding(envelope.request.descriptor)
            request = SourcePageRequest(
                user_id=self.user_id,
                project_name=self.project_name,
                attempt_id=attempt.attempt_id,
                query_id=query.query_id,
                query_revision=query.revision,
                query_digest=query.query_digest,
                source_kind=query.source_kind,
                source_contract_version=query.source_contract_version,
                operation=query.operation,
                parameters=query.parameters,
                page_ordinal=1,
                cursor=None,
                remaining_record_limit=query.max_records,
                remaining_quota_units=query.max_quota_units,
                credential_ref=query.credential_ref,
                capability_grant_digest=grant.grant_digest,
                capability_evaluation_digest=evaluation.evaluation_digest,
            )
            await self._at("before-source-dispatch")
            self._binding(envelope.request.descriptor)
            async with self.store.transaction() as tx:
                current = await tx.manual.get_for_command(command)
                admitted = await tx.manual.get_envelope(attempt.attempt_id)
                if (
                    current is None
                    or current != attempt
                    or admitted != envelope
                    or current.state != AttemptStateV2.RUNNING
                ):
                    raise OpportunityError(StopCode.M9_STALE_HEAD)
                permit = await tx.manual.begin_read(
                    attempt.attempt_id, expected_envelope_version=envelope.version, operational=True
                )
            try:
                response = SourcePageResult.model_validate((await binding.source.fetch_page(request)).model_dump())
            finally:
                async with self.store.transaction() as tx:
                    await tx.manual.release_read(permit.lease_id)
            if response.provider_request_id != envelope.request.opaque_upload_id:
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            self._binding(envelope.request.descriptor)
            await self._at("source-response-returned")
            checkpoint = await self._checkpoint(envelope, response)
            async with self.store.transaction() as tx:
                response_at = await tx.profiles.database_time()
                await tx.manual.append_checkpoint(
                    attempt.attempt_id, checkpoint, expected_attempt_version=attempt.attempt_version
                )
            await self._at("checkpoint-committed")
            return await self._finalize(command, attempt, envelope, checkpoint, response_at)
        except Exception:
            async with self.store.transaction() as tx:
                current = await tx.manual.get_attempt(attempt.attempt_id)
                if current is not None and current.state == AttemptStateV2.RUNNING:
                    await tx.manual.mark_outcome_unknown(
                        current.attempt_id, expected_attempt_version=current.attempt_version
                    )
            raise

    async def _capability(self, query: SourceQuery) -> tuple[SourceCapabilityGrant, EffectiveCapabilityEvaluation]:
        if self.capabilities is None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        grant = SourceCapabilityGrant.model_validate(
            (await self.capabilities.resolve_grant(query.capability_grant_id)).model_dump()
        )
        if (
            grant.user_id,
            grant.project_name,
            grant.grant_id,
            grant.grant_version,
            grant.grant_digest,
            grant.source_kind,
            grant.source_contract_version,
            grant.credential_ref,
        ) != (
            self.user_id,
            self.project_name,
            query.capability_grant_id,
            query.capability_grant_version,
            query.capability_grant_digest,
            query.source_kind,
            query.source_contract_version,
            query.credential_ref,
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        request = CapabilityEvaluationRequest(
            user_id=self.user_id,
            project_name=self.project_name,
            actor_id=self.actor_id,
            grant_id=grant.grant_id,
            grant_version=grant.grant_version,
            grant_digest=grant.grant_digest,
            source_kind=query.source_kind,
            operation=query.operation,
            purpose=query.intent,
            account_binding_digest=grant.account_binding_digest,
        )
        evaluation = EffectiveCapabilityEvaluation.model_validate(
            (await self.capabilities.evaluate(request)).model_dump()
        )
        if (evaluation.evaluation_id, evaluation.evaluation_digest) != (
            query.capability_evaluation_id,
            query.capability_evaluation_digest,
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        async with self.store.transaction() as tx:
            now = await tx.profiles.database_time()
        validate_capability(grant, evaluation, request, now=now)
        return grant, evaluation

    async def reconcile_publication(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        command = self._command(command)
        async with self.store.transaction() as tx:
            receipt = await tx.manual.get_current_receipt(command)
            if receipt is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            if receipt.state != AttemptStateV2.RUNNING:
                return receipt
            descriptor = await tx.manual.get_descriptor(receipt.attempt_id)
            envelope = await tx.manual.get_envelope(receipt.attempt_id)
        if envelope is None or envelope.phase != "RESERVED":
            return receipt
        binding = self._binding(descriptor)
        publication = PublishedAdmission.model_validate(
            (await binding.upload_admission.admit(envelope.request)).model_dump()
        )
        self._binding(descriptor)
        if publication.request != envelope.request:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        async with self.store.transaction() as tx:
            await tx.manual.attach(publication, expected_envelope_version=envelope.version)
        return await self._current(command)

    async def _checkpoint(self, envelope: AdmissionEnvelope, response: SourcePageResult) -> PageCheckpoint:
        binding = self._binding(envelope.request.descriptor)
        async with self.store.transaction() as tx:
            permit = await tx.manual.begin_read(
                envelope.request.attempt_id, expected_envelope_version=envelope.version, operational=True
            )
        try:
            materials = {}
            for obj in envelope.objects:
                self._binding(envelope.request.descriptor)
                materials[obj.evidence_kind] = await binding.publication.read_verified(
                    envelope, object_ref=obj.payload_ref, permit=permit
                )
                self._binding(envelope.request.descriptor)
            if materials.get("raw-page") != response.raw_payload:
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            rows = normalize_manual_page(response)
            objects = {o.evidence_kind: o for o in envelope.objects}
            expected_fields = []
            identities = {}
            for ordinal, native in enumerate(sorted({str(row["source_native_id"]) for row in rows}), 1):
                kind = f"source-identity-{ordinal}"
                if materials.get(kind) != canonical_json_bytes(
                    {
                        "schema": "m9.manual-source-identity.v1",
                        "source_kind": "manual-import",
                        "source_contract_version": "manual-import.v1",
                        "native_id": native,
                    }
                ):
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                identities[native] = objects[kind].payload_ref
            for ordinal, row in enumerate(rows, 1):
                kind = f"native-field-{ordinal}"
                obj = objects[kind]
                missing = row["missing_reason"] is not None
                expected = dict(
                    schema="m9.manual-native-value.v1",
                    source_kind="manual-import",
                    source_contract_version="manual-import.v1",
                    **{k: v for k, v in row.items() if k not in ("source_native_id", "value", "missing_reason")},
                    **({"missing_reason": row["missing_reason"]} if missing else {"value": row["value"]}),
                )
                if materials[kind] != canonical_json_bytes(expected):
                    raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
                expected_fields.append(
                    NativeFieldMaterial.model_validate(
                        {
                            **{k: v for k, v in row.items() if k not in ("source_native_id", "value")},
                            "source_identity_ref": identities[str(row["source_native_id"])],
                            "material_ref": obj.payload_ref,
                            "material_integrity_ref": obj.integrity_ref,
                            "value_ref": None if missing else obj.payload_ref,
                            "value_integrity_ref": None if missing else obj.integrity_ref,
                            "retained_normalized_value_digest": None if missing else obj.retained_material_digest,
                        }
                    )
                )
            if materials.get("manual-native-index") != canonical_json_bytes(
                {"schema": "m9.manual-native-index.v1", "fields": expected_fields}
            ):
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            raw = objects["raw-page"]
            if (
                envelope.deadlines is None
                or envelope.admitted_at is None
                or not response.terminal_page
                or response.next_cursor is not None
            ):
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            clocks = {c.data_class: c for c in envelope.deadlines.classes}
            return PageCheckpoint(
                page=SnapshotPage(
                    ordinal=1,
                    request_cursor_digest=None,
                    response_cursor_digest=None,
                    provider_request_id=response.provider_request_id,
                    payload_ref=raw.payload_ref,
                    payload_integrity_ref=raw.integrity_ref,
                    retained_source_payload_digest=raw.retained_material_digest,
                    raw_media_type=response.raw_media_type,
                    raw_size_bytes=len(response.raw_payload),
                    data_classes=raw.data_classes,
                    data_class_clocks=tuple(
                        EvidenceDataClassClock(
                            data_class=c,
                            captured_at=envelope.admitted_at,
                            refresh_due_at=clocks[c].refresh_due_at,
                            retention_due_at=clocks[c].retention_due_at,
                        )
                        for c in raw.data_classes
                    ),
                    record_count=len(rows),
                    captured_at=envelope.admitted_at,
                    missing_reason=None,
                ),
                source_identity_refs=tuple(sorted(identities.values())),
                quota_units_observed=response.quota_units_observed,
                next_cursor_ref=None,
                next_cursor_integrity_ref=None,
                terminal_page=True,
                provider_observed_at=response.provider_observed_at,
                native_fields=tuple(expected_fields),
            )
        finally:
            async with self.store.transaction() as tx:
                await tx.manual.release_read(permit.lease_id)

    async def _finalize(
        self,
        command: AcquireSourceQueryV2,
        attempt: AcquisitionAttemptV2,
        envelope: AdmissionEnvelope,
        checkpoint: PageCheckpoint,
        response_at: datetime,
    ) -> AcquisitionReceiptV2:
        self._binding(envelope.request.descriptor)
        async with self.store.transaction() as tx:
            query = await tx.queries.get_exact(command.query_id, command.query_revision)
            if query is None or attempt.started_at is None or envelope.admitted_at is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            now = await tx.profiles.database_time()
            snapshot = SourceSnapshot(
                snapshot_id=self._new_id(),
                revision=1,
                parent_revision=None,
                user_id=self.user_id,
                project_name=self.project_name,
                query_id=query.query_id,
                query_revision=query.revision,
                query_digest=query.query_digest,
                attempt_id=attempt.attempt_id,
                source_kind=query.source_kind,
                source_contract_version=query.source_contract_version,
                source_identity_refs=checkpoint.source_identity_refs,
                pages=(checkpoint.page,),
                coverage_state=CoverageState.COMPLETE_WITHIN_DECLARED_BOUNDS,
                requested_record_limit=query.max_records,
                returned_record_count=checkpoint.page.record_count,
                coverage_note="Original admitted manual material.",
                provider_observed_at=checkpoint.provider_observed_at,
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
                origin=SnapshotOriginV2.SOURCE_RESPONSE_VERIFIED,
                admitted_at=envelope.admitted_at,
                response_recorded_at=response_at,
            )
            await tx.manual.append_snapshot(snapshot, provenance, expected_attempt_version=attempt.attempt_version)
            for field in checkpoint.native_fields:
                observation = NormalizedSourceObservation.model_validate(
                    {
                        **field.model_dump(exclude={"material_ref", "material_integrity_ref"}),
                        "observation_id": self._new_id(),
                        "revision": 1,
                        "parent_revision": None,
                        "user_id": self.user_id,
                        "project_name": self.project_name,
                        "snapshot_id": snapshot.snapshot_id,
                        "snapshot_digest": snapshot.snapshot_digest,
                        "page_ordinal": 1,
                        "source_kind": query.source_kind,
                        "payload_integrity_ref": checkpoint.page.payload_integrity_ref,
                        "retained_source_payload_digest": checkpoint.page.retained_source_payload_digest,
                        "observation_digest": "sha256:" + "0" * 64,
                        "observed_at": envelope.admitted_at,
                    }
                )
                observation = observation.model_copy(
                    update={"observation_digest": digest_source_observation(observation)}
                )
                await tx.manual.append_observation(observation, expected_attempt_version=attempt.attempt_version)
            receipt = await tx.manual.finish_acquisition(
                attempt.attempt_id,
                expected_attempt_version=attempt.attempt_version,
                state=AttemptStateV2.SUCCEEDED,
                reason=AttemptOutcomeReason.COMPLETED,
                resolver_id="manual-acquisition-v2",
            )
        await self._at("finalization-committed")
        return receipt
