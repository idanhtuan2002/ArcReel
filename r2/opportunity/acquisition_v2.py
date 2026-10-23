"""Acquisition with original manual custody committed before source dispatch."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Literal, Protocol, Self

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, Field, model_validator

from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.contracts.advanced_creative import Sha256Digest
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
    AdmissionClosureIntent,
    AdmissionDeletionReceipt,
    AdmissionEnvelope,
    AdmissionReadPermit,
    AdmissionRequest,
    DispatchClaim,
    FrozenManualBinding,
    ManualBindingDescriptor,
    ManualBindingRegistry,
    PublicationHeader,
    PublicationObjectRef,
    PublicationReceiptMetadata,
    PublishedAdmission,
    SealedObjectDescriptor,
    manual_binding_digest,
)
from r2.opportunity.normalization import decode_manual_payload, normalize_manual_page
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


class CustodianPublicationDisposition(M9ContractModel):
    request: AdmissionRequest
    state: Literal["ORIGINAL_HEADER", "NEVER_ISSUED", "UNRESOLVED"]
    header: PublicationHeader | None

    @model_validator(mode="after")
    def exact_header(self) -> Self:
        if (self.state == "ORIGINAL_HEADER") != (self.header is not None):
            raise ValueError("publication disposition must carry its original header")
        return self


class CustodianSpendSubject(M9ContractModel):
    """One original private upload and its complete declared publication inventory."""

    root_request: AdmissionRequest
    claim_ref: str | None = Field(min_length=1)
    publications: tuple[CustodianPublicationDisposition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def original_upload(self) -> Self:
        root = self.root_request
        keys = [p.request.publication_key for p in self.publications]
        if len(keys) != len(set(keys)) or root not in tuple(p.request for p in self.publications):
            raise ValueError("private closure must retain its unique original publication inventory")
        for publication in self.publications:
            request = publication.request
            if (
                request.context.user_id,
                request.context.project_name,
                request.context.actor_id,
                request.descriptor,
                request.opaque_upload_id,
                request.upload_version,
                request.data_rules,
                request.original_clocks,
            ) != (
                root.context.user_id,
                root.context.project_name,
                root.context.actor_id,
                root.descriptor,
                root.opaque_upload_id,
                root.upload_version,
                root.data_rules,
                root.original_clocks,
            ):
                raise ValueError("private closure publication belongs to another original upload")
            if publication.header is not None and (
                self.claim_ref is None or publication.header.metadata.claim_ref != self.claim_ref
            ):
                raise ValueError("private closure header has a different original claim")
        return self


class CustodianSpendMetadata(CustodianSpendSubject):
    """Private ingest/comparison erasure with original content-free publication inventory."""

    schema_version: Literal["m9.manual-custodian-spent.v2"]
    operation: Literal["spend-original-upload"]
    closure_id: str = Field(min_length=1)
    spent_at: AwareDatetime
    deleted_at: AwareDatetime
    inventory_complete: bool = Field(strict=True)

    @model_validator(mode="after")
    def erasure_time(self) -> Self:
        if self.deleted_at < self.spent_at:
            raise ValueError("private erasure cannot precede its durable spent fence")
        if self.inventory_complete and any(p.state == "UNRESOLVED" for p in self.publications):
            raise ValueError("complete private inventory cannot contain an unresolved publication")
        return self


def custodian_spend_metadata_digest(metadata: CustodianSpendMetadata) -> str:
    return digest_canonical({"domain": "m9.manual-custodian-spent-metadata.v2", "metadata": metadata})


def custodian_spend_preimage(metadata: CustodianSpendMetadata) -> bytes:
    return b"m9.manual-custodian-spent.v2\x00" + canonical_json_bytes(
        {"metadata": metadata, "metadata_digest": custodian_spend_metadata_digest(metadata)}
    )


class CustodianSpendReceipt(M9ContractModel):
    metadata: CustodianSpendMetadata
    metadata_digest: Sha256Digest
    signature: str = Field(pattern=r"^[A-Za-z0-9_-]{86}$")

    @model_validator(mode="after")
    def exact_metadata(self) -> Self:
        if self.metadata_digest != custodian_spend_metadata_digest(self.metadata):
            raise ValueError("private spending receipt metadata differs")
        return self


def manual_publication_metadata_for_request(
    request: AdmissionRequest, claim: str, objects: tuple[PublicationObjectRef, ...]
) -> PublicationReceiptMetadata:
    return PublicationReceiptMetadata(
        schema_version="m9.manual-publication-receipt.v1",
        context=request.context,
        source_kind=request.descriptor.source_kind,
        source_contract_version=request.descriptor.source_contract_version,
        verification_key_id=request.descriptor.verification_key_id,
        request_digest=request.request_digest,
        query_id=request.query_id,
        query_revision=request.query_revision,
        query_digest=request.query_digest,
        attempt_id=request.attempt_id,
        attempt_version=request.attempt_version,
        publication_key=request.publication_key,
        claim_ref=claim,
        upload_version=request.upload_version,
        descriptor_digest=manual_binding_digest(request.descriptor),
        objects=objects,
    )


def _custody_signature(encoded: str) -> bytes:
    signature = base64.urlsafe_b64decode(encoded + "==")
    if len(signature) != 64 or base64.urlsafe_b64encode(signature).decode().rstrip("=") != encoded:
        raise ValueError("private custody signature encoding differs")
    return signature


def verify_custodian_spent(
    raw: bytes, *, public_key: bytes, expected_request: AdmissionRequest, closure_id: str
) -> CustodianSpendReceipt:
    """Verify original private erasure and header bindings without external I/O."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 16_777_216:
            raise ValueError("private spending receipt exceeds bound")
        receipt = CustodianSpendReceipt.model_validate_json(raw)
        metadata = receipt.metadata
        expected_request = AdmissionRequest.model_validate(expected_request.model_dump())
        if (
            canonical_json_bytes(receipt) != raw
            or metadata.root_request != expected_request
            or metadata.closure_id != closure_id
            or metadata.deleted_at > datetime.now(UTC)
            or type(public_key) is not bytes
            or len(public_key) != 32
            or "sha256:" + hashlib.sha256(public_key).hexdigest() != expected_request.descriptor.verification_key_digest
        ):
            raise ValueError("private spending scope differs")
        key = Ed25519PublicKey.from_public_bytes(public_key)
        key.verify(_custody_signature(receipt.signature), custodian_spend_preimage(metadata))
        for publication in metadata.publications:
            header = publication.header
            if header is None:
                continue
            if metadata.claim_ref is None:
                raise ValueError("private spending original claim missing")
            PublishedAdmission(
                request=publication.request,
                publication_key=publication.request.publication_key,
                claim_ref=metadata.claim_ref,
                upload_version=publication.request.upload_version,
                objects=tuple(SealedObjectDescriptor(**obj.model_dump()) for obj in header.metadata.objects),
            )
            expected = manual_publication_metadata_for_request(
                publication.request, metadata.claim_ref, header.metadata.objects
            )
            if header.metadata != expected or len(canonical_json_bytes(header)) > 65_536:
                raise ValueError("private spending original header binding differs")
            key.verify(
                _custody_signature(header.signature),
                b"m9.manual-publication-receipt.v1\x00"
                + canonical_json_bytes(header.model_dump(exclude={"signature"})),
            )
        return receipt
    except Exception:
        raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH) from None


class ManualCustodianClosurePort(Protocol):
    async def close_original(self, request: AdmissionRequest, *, claim_ref: str | None, closure_id: str) -> bytes: ...


class ManualCleanupPort(Protocol):
    @property
    def descriptor(self) -> ManualBindingDescriptor: ...
    @property
    def public_key(self) -> bytes: ...
    async def fence_publications(
        self, requests: tuple[AdmissionRequest, ...], *, closure_id: str
    ) -> tuple[PublicationHeader, ...]: ...
    async def spend_original(
        self, request: AdmissionRequest, *, claim_ref: str | None, closure_id: str
    ) -> CustodianSpendReceipt: ...
    async def delete_exact(
        self, closure: AdmissionClosureIntent, *, proof: CustodianSpendReceipt, requests: tuple[AdmissionRequest, ...]
    ) -> AdmissionDeletionReceipt: ...


class ManualCleanupState(M9ContractModel):
    intent: AdmissionClosureIntent
    root_request: AdmissionRequest
    requests: tuple[AdmissionRequest, ...] = Field(min_length=1)
    claim_ref: str | None
    proof: CustodianSpendReceipt | None


class ManualAcquisitionRepositoryPort(Protocol):
    async def get_cleanup_subject(
        self, command: AcquireSourceQueryV2
    ) -> tuple[AcquisitionAttemptV2, ManualBindingDescriptor] | None: ...
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
    async def mark_material_unavailable(self, attempt_id: str, *, expected_envelope_version: int) -> None: ...
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
    async def get_cleanup_state(self, attempt_id: str) -> ManualCleanupState | None: ...
    async def plan_recovery_closure(self, attempt_id: str) -> object: ...
    async def begin_recovery_closure(self, attempt_id: str, *, dependency_plan: object) -> ManualCleanupState: ...
    async def drain_recovery_closure(self, closure_id: str, *, expected_closure_version: int) -> ManualCleanupState: ...
    async def authorize_recovery_deletion(
        self, closure_id: str, *, proof: CustodianSpendReceipt, public_key: bytes, expected_closure_version: int
    ) -> ManualCleanupState: ...
    async def finish_recovery_closure(
        self, receipt: AdmissionDeletionReceipt, *, expected_closure_version: int
    ) -> ManualCleanupState: ...


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
        cleanup: ManualCleanupPort | None = None,
    ) -> None:
        self.cleanup = cleanup
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
        except OpportunityError as error:
            try:
                retained = await self._current(command)
                if retained.state in (
                    AttemptStateV2.SUCCEEDED,
                    AttemptStateV2.FAILED,
                    AttemptStateV2.EXPIRED_UNRECOVERABLE,
                ):
                    return retained
                if error.code == StopCode.M9_STALE_HEAD and retained.snapshot_ids:
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

    async def reconcile_cleanup(self, command: AcquireSourceQueryV2) -> AdmissionClosureIntent:
        command = self._command(command)
        async with self.store.transaction() as tx:
            subject = await tx.manual.get_cleanup_subject(command)
        if subject is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        attempt, descriptor = subject
        try:
            return await self._reconcile_cleanup(attempt.attempt_id, descriptor)
        except OpportunityError:
            async with self.store.transaction() as tx:
                retained = await tx.manual.get_cleanup_state(attempt.attempt_id)
            if retained is not None and retained.intent.phase == "ERASED":
                return retained.intent
            raise
        except Exception:
            try:
                async with self.store.transaction() as tx:
                    retained = await tx.manual.get_cleanup_state(attempt.attempt_id)
                if retained is not None:
                    return retained.intent
            except Exception:
                pass
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _reconcile_cleanup(self, attempt_id: str, descriptor: ManualBindingDescriptor) -> AdmissionClosureIntent:
        async with self.store.transaction() as tx:
            state = await tx.manual.get_cleanup_state(attempt_id)
        if state is not None and state.intent.phase == "ERASED":
            return state.intent
        cleanup = self.cleanup
        if cleanup is None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        if cleanup.descriptor != descriptor:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        if state is None:
            async with self.store.transaction() as tx:
                plan = await tx.manual.plan_recovery_closure(attempt_id)
            async with self.store.transaction() as tx:
                state = await tx.manual.begin_recovery_closure(attempt_id, dependency_plan=plan)
                await self._at("cleanup-fence-before-commit")
            await self._at("cleanup-fenced-committed")
        if state.intent.phase == "ERASED":
            return state.intent
        await cleanup.fence_publications(state.requests, closure_id=state.intent.closure_id)
        await self._at("cleanup-publication-fenced")
        if state.intent.version == 1:
            async with self.store.transaction() as tx:
                state = await tx.manual.drain_recovery_closure(state.intent.closure_id, expected_closure_version=1)
                await self._at("cleanup-drain-before-commit")
            await self._at("cleanup-drained-committed")
        if state.intent.phase == "ERASED":
            return state.intent
        if state.intent.version == 2:
            public_key = cleanup.public_key
            proof = await cleanup.spend_original(
                state.root_request, claim_ref=state.claim_ref, closure_id=state.intent.closure_id
            )
            proof = verify_custodian_spent(
                canonical_json_bytes(proof),
                public_key=public_key,
                expected_request=state.root_request,
                closure_id=state.intent.closure_id,
            )
            await self._at("cleanup-private-erasure-returned")
            async with self.store.transaction() as tx:
                state = await tx.manual.authorize_recovery_deletion(
                    state.intent.closure_id, proof=proof, public_key=public_key, expected_closure_version=2
                )
                await self._at("cleanup-authorization-before-commit")
            await self._at("cleanup-authorized-committed")
        if state.intent.phase == "ERASED":
            return state.intent
        if state.intent.version != 3 or state.proof is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        receipt = await cleanup.delete_exact(state.intent, proof=state.proof, requests=state.requests)
        await self._at("cleanup-public-erasure-returned")
        async with self.store.transaction() as tx:
            state = await tx.manual.finish_recovery_closure(receipt, expected_closure_version=3)
            await self._at("cleanup-completion-before-commit")
        await self._at("cleanup-erased-committed")
        return state.intent

    async def reconcile_publication(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        command = self._command(command)
        try:
            return await self._reconcile_publication(command)
        except OpportunityError:
            raise
        except Exception:
            try:
                return await self._current(command)
            except Exception:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _reconcile_publication(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
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

    async def reconcile_manual_admission(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        command = self._command(command)
        try:
            return await self._reconstruct_manual_admission(command)
        except OpportunityError as error:
            try:
                return await self.expire_admission(command)
            except OpportunityError:
                raise error from None
        except Exception:
            try:
                return await self._current(command)
            except Exception:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def expire_admission(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        command = self._command(command)
        try:
            async with self.store.transaction() as tx:
                receipt = await tx.manual.get_current_receipt(command)
                if receipt is None:
                    raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
                if receipt.state in (
                    AttemptStateV2.SUCCEEDED,
                    AttemptStateV2.FAILED,
                    AttemptStateV2.EXPIRED_UNRECOVERABLE,
                ):
                    return receipt
                receipt = await tx.manual.close_expired(
                    receipt.attempt_id,
                    expected_attempt_version=receipt.attempt_version,
                    resolver_id="manual-recovery-expiry-v2",
                )
            await self._at("expiry-committed")
            return receipt
        except OpportunityError:
            raise
        except Exception:
            try:
                receipt = await self._current(command)
                if receipt.state in (
                    AttemptStateV2.SUCCEEDED,
                    AttemptStateV2.FAILED,
                    AttemptStateV2.EXPIRED_UNRECOVERABLE,
                ):
                    return receipt
            except Exception:
                pass
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _reconstruct_manual_admission(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2:
        async with self.store.transaction() as tx:
            receipt = await tx.manual.get_current_receipt(command)
            if receipt is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            if receipt.snapshot_ids or receipt.state in (
                AttemptStateV2.SUCCEEDED,
                AttemptStateV2.FAILED,
                AttemptStateV2.EXPIRED_UNRECOVERABLE,
            ):
                return receipt
            descriptor = await tx.manual.get_descriptor(receipt.attempt_id)
        self._binding(descriptor)
        async with self.store.transaction() as tx:
            attempt = await tx.manual.get_for_command(command)
            envelope = await tx.manual.get_envelope(receipt.attempt_id)
            if attempt is None or envelope is None or envelope.phase != "READY":
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            if attempt.state == AttemptStateV2.RUNNING:
                if envelope.dispatch_claim is None:
                    claim = await tx.manual.claim_dispatch(
                        attempt.attempt_id,
                        expected_attempt_version=attempt.attempt_version,
                        expected_envelope_version=envelope.version,
                    )
                    version = claim.attempt_version
                else:
                    version = attempt.attempt_version
                attempt = await tx.manual.mark_outcome_unknown(attempt.attempt_id, expected_attempt_version=version)
                envelope = await tx.manual.get_envelope(attempt.attempt_id)
            if envelope is None or attempt.state not in (AttemptStateV2.OUTCOME_UNKNOWN, AttemptStateV2.NEEDS_OPERATOR):
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            checkpoints = await tx.manual.list_checkpoints(attempt.attempt_id)
        await self._at("reconstruction-fenced")
        checkpoint = await self._checkpoint(envelope, None)
        if checkpoints:
            if len(checkpoints) != 1:
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            original = checkpoints[0]
            normalized = original.model_copy(
                update={
                    "page": original.page.model_copy(update={"provider_request_id": None}),
                    "provider_observed_at": None,
                    "quota_units_observed": None,
                }
            )
            if normalized != checkpoint:
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            checkpoint = original
        else:
            async with self.store.transaction() as tx:
                await tx.manual.append_checkpoint(
                    attempt.attempt_id, checkpoint, expected_attempt_version=attempt.attempt_version
                )
        await self._at("reconstruction-checkpoint-committed")
        return await self._finalize(
            command, attempt, envelope, checkpoint, None, origin=SnapshotOriginV2.LOCAL_ADMISSION_RECONSTRUCTION
        )

    async def _checkpoint(self, envelope: AdmissionEnvelope, response: SourcePageResult | None) -> PageCheckpoint:
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
            if response is None:
                raw = materials["raw-page"]
                _, rows = decode_manual_payload(raw)
                raw_object = next(o for o in envelope.objects if o.evidence_kind == "raw-page")
                response = SourcePageResult(
                    provider_request_id=None,
                    next_cursor=None,
                    raw_payload=raw,
                    raw_media_type="application/json",
                    source_native_ids=tuple(sorted({str(row["source_native_id"]) for row in rows})),
                    data_classes=raw_object.data_classes,
                    returned_record_count=len(rows),
                    quota_units_observed=None,
                    provider_observed_at=None,
                    terminal_page=True,
                )
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
        except OpportunityError as error:
            if error.code == StopCode.M9_RAW_DIGEST_MISMATCH:
                async with self.store.transaction() as tx:
                    await tx.manual.mark_material_unavailable(
                        envelope.request.attempt_id, expected_envelope_version=envelope.version
                    )
            raise
        finally:
            async with self.store.transaction() as tx:
                await tx.manual.release_read(permit.lease_id)

    async def _finalize(
        self,
        command: AcquireSourceQueryV2,
        attempt: AcquisitionAttemptV2,
        envelope: AdmissionEnvelope,
        checkpoint: PageCheckpoint,
        response_at: datetime | None,
        *,
        origin: SnapshotOriginV2 = SnapshotOriginV2.SOURCE_RESPONSE_VERIFIED,
    ) -> AcquisitionReceiptV2:
        self._binding(envelope.request.descriptor)
        async with self.store.transaction() as tx:
            retained = await tx.manual.get_current_receipt(command)
            if retained is not None and (
                retained.snapshot_ids or retained.state == AttemptStateV2.EXPIRED_UNRECOVERABLE
            ):
                return retained
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
                provider_observed_at=(
                    checkpoint.provider_observed_at if origin == SnapshotOriginV2.SOURCE_RESPONSE_VERIFIED else None
                ),
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
                origin=origin,
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
            if origin == SnapshotOriginV2.SOURCE_RESPONSE_VERIFIED:
                receipt = await tx.manual.finish_acquisition(
                    attempt.attempt_id,
                    expected_attempt_version=attempt.attempt_version,
                    state=AttemptStateV2.SUCCEEDED,
                    reason=AttemptOutcomeReason.COMPLETED,
                    resolver_id="manual-acquisition-v2",
                )
            else:
                receipt = await tx.manual.get_current_receipt(command)
                if receipt is None:
                    raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        await self._at("finalization-committed")
        return receipt
