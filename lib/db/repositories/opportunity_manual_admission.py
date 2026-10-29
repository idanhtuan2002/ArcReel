"""Typed manual custody metadata under command, policy, upload and row guards."""

from __future__ import annotations

import struct
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransaction

from lib.db.models.opportunity import M9CommandReceiptModel, M9EventModel
from lib.db.models.opportunity_acquisition import (
    M9AcquisitionAttemptModel,
    M9ObservationHeadModel,
    M9SnapshotPageModel,
    M9SourceObservationModel,
    M9SourceSnapshotModel,
)
from lib.db.models.opportunity_manual_admission import (
    M9ManualAdmissionModel,
    M9ManualClosureIntentModel,
    M9ManualPublicationIntentModel,
    M9ManualReadLeaseModel,
    M9ManualUploadLeaseModel,
)
from lib.db.repositories.opportunity import OpportunityProfileRepository
from lib.db.repositories.opportunity_acquisition import CapabilityEvidenceRepository, SourceQueryRepository
from r2.advanced_creative.digests import canonical_json_bytes, digest_canonical
from r2.advanced_creative.exploration import uuid7
from r2.contracts.opportunity import (
    AttemptOutcomeReason,
    CapabilityEvaluationRequest,
    CommandContext,
    CoverageState,
    EvidenceDataClassClock,
    M9ContractModel,
    NormalizedSourceObservation,
    SourceCapabilityGrant,
    SourceQuery,
    SourceSnapshot,
)
from r2.contracts.opportunity_acquisition_v2 import (
    AcquireSourceQueryV2,
    AcquisitionAttemptV2,
    AcquisitionReceiptV2,
    AttemptStateV2,
    ExpiryClosureV2,
    ExpiryDispositionV2,
    QuotaDispositionV2,
    SnapshotOriginV2,
    SnapshotProvenanceV2,
)
from r2.opportunity.acquisition import PageCheckpoint
from r2.opportunity.acquisition_v2 import (
    CustodianPublicationDisposition,
    CustodianSpendReceipt,
    CustodianSpendSubject,
    ManualCleanupState,
    manual_publication_metadata_for_request,
    verify_custodian_spent,
)
from r2.opportunity.acquisition_v2_digests import (
    digest_acquisition_request_v2,
    digest_acquisition_result_v2,
    digest_snapshot_provenance_v2,
)
from r2.opportunity.capabilities import validate_capability
from r2.opportunity.digests import digest_source_observation, digest_source_snapshot
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import (
    AdmissionClosureIntent,
    AdmissionDeletionReceipt,
    AdmissionEnvelope,
    AdmissionPhase,
    AdmissionReadPermit,
    AdmissionRequest,
    DispatchClaim,
    ManualBindingDescriptor,
    PublicationObjectRef,
    PublishedAdmission,
    admission_metadata_digest,
    effective_admission_deadlines,
    require_admission_access,
)

PolicyIdentity = Callable[[], Awaitable[tuple[str, str, str]]]
_MISSING = StopCode.M9_REQUIRED_EVIDENCE_MISSING
_STALE = StopCode.M9_STALE_HEAD
_CONFLICT = StopCode.M9_COMMAND_REPLAY_CONFLICT


class _Transition(M9ContractModel):
    from_state: AttemptStateV2
    to_state: AttemptStateV2
    from_version: int = Field(ge=1, strict=True)
    to_version: int = Field(ge=2, strict=True)
    at: AwareDatetime
    resolver_id: str

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        allowed = {
            AttemptStateV2.RUNNING: {
                AttemptStateV2.OUTCOME_UNKNOWN,
                AttemptStateV2.SUCCEEDED,
                AttemptStateV2.FAILED,
            },
            AttemptStateV2.OUTCOME_UNKNOWN: {AttemptStateV2.NEEDS_OPERATOR, AttemptStateV2.EXPIRED_UNRECOVERABLE},
            AttemptStateV2.NEEDS_OPERATOR: {AttemptStateV2.EXPIRED_UNRECOVERABLE},
        }
        if self.to_version != self.from_version + 1 or self.to_state not in allowed.get(self.from_state, set()):
            raise ValueError("uncertainty audit transition differs")
        return self


class _AttemptRecord(M9ContractModel):
    schema_version: Literal["m9.manual-attempt.v1"] = "m9.manual-attempt.v1"
    command: AcquireSourceQueryV2
    descriptor: ManualBindingDescriptor
    attempt: AcquisitionAttemptV2
    request: AdmissionRequest | None
    changed_at: AwareDatetime
    transitions: tuple[_Transition, ...] = ()
    receipt: AcquisitionReceiptV2 | None = None


class _UploadLeaseRecord(M9ContractModel):
    schema_version: Literal["m9.manual-upload-lease.v1"] = "m9.manual-upload-lease.v1"
    request: AdmissionRequest
    claim_ref: str
    version: int = Field(ge=1, strict=True)
    state: Literal["ACTIVE", "CLOSING", "SPENT"]
    closure_id: str | None


class _ReadLeaseRecord(M9ContractModel):
    schema_version: Literal["m9.manual-read-lease.v1"] = "m9.manual-read-lease.v1"
    permit: AdmissionReadPermit
    attempt_version: int = Field(ge=1, strict=True)
    released_at: AwareDatetime | None


class _CheckpointRecord(M9ContractModel):
    schema_version: Literal["m9.manual-checkpoint.v1"] = "m9.manual-checkpoint.v1"
    admission: AdmissionEnvelope
    checkpoint: PageCheckpoint


class _SnapshotRecord(M9ContractModel):
    schema_version: Literal["m9.manual-snapshot.v1"] = "m9.manual-snapshot.v1"
    admission: AdmissionEnvelope
    snapshot: SourceSnapshot
    provenance: SnapshotProvenanceV2
    provenance_digest: str
    stored_at: AwareDatetime


class _ObservationRecord(M9ContractModel):
    schema_version: Literal["m9.manual-observation.v1"] = "m9.manual-observation.v1"
    observation: NormalizedSourceObservation
    snapshot_provenance_digest: str
    attempt_version: int = Field(ge=1, strict=True)
    stored_at: AwareDatetime


class _ClosureMember(M9ContractModel):
    record: _AttemptRecord
    admission: AdmissionEnvelope


@dataclass(frozen=True)
class ManualClosurePlan:
    """Read-transaction snapshot, revalidated under all dependency guards."""

    attempt_id: str
    members: tuple[_ClosureMember, ...]
    planning_transaction: object


class _ClosureRecord(M9ContractModel):
    schema_version: Literal["m9.manual-closure.v1"] = "m9.manual-closure.v1"
    fence: AdmissionClosureIntent
    intent: AdmissionClosureIntent
    members: tuple[_ClosureMember, ...]
    reads: tuple[_ReadLeaseRecord, ...]
    authorized_at: AwareDatetime | None = None
    receipt: AdmissionDeletionReceipt | None = None
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_phases(self) -> Self:
        object.__setattr__(self, "members", tuple(sorted(self.members, key=lambda m: m.record.attempt.attempt_id)))
        object.__setattr__(self, "reads", tuple(sorted(self.reads, key=lambda r: r.permit.lease_id)))
        if self.fence.phase != "CLEANUP_PENDING" or self.fence.version != 1:
            raise ValueError("closure fence must be its original intent")
        if self.intent.model_dump(exclude={"phase", "version"}) != self.fence.model_dump(exclude={"phase", "version"}):
            raise ValueError("closure authority cannot change after fencing")
        if self.intent.version == 1:
            valid = (
                self.intent == self.fence
                and self.authorized_at is None
                and self.receipt is None
                and self.finished_at is None
            )
        elif self.intent.version == 2:
            valid = (
                self.intent.phase == "CLEANUP_PENDING"
                and self.authorized_at is not None
                and self.receipt is None
                and self.finished_at is None
            )
        elif self.intent.version == 3:
            valid = (
                self.intent.phase == "ERASED"
                and self.authorized_at is not None
                and self.receipt is not None
                and self.finished_at is not None
            )
        else:
            valid = False
        if not valid or (self.authorized_at is not None and self.authorized_at < self.fence.fenced_at):
            raise ValueError("closure phase and authorization differ")
        if self.receipt is not None and (
            self.authorized_at is None
            or self.finished_at is None
            or (
                self.receipt.closure != self.fence.model_copy(update={"version": 2})
                or self.receipt.deleted_at < self.authorized_at
                or self.finished_at < self.receipt.deleted_at
            )
        ):
            raise ValueError("deletion must follow authorization and precede SQL completion")
        return self


class _RecoveryClosureMember(M9ContractModel):
    record: _AttemptRecord
    admission: AdmissionEnvelope | None
    admission_present: bool = Field(strict=True)
    intent_present: bool = Field(strict=True)
    leases: tuple[_UploadLeaseRecord, ...]

    @model_validator(mode="after")
    def original_metadata(self) -> Self:
        request = self.record.request
        if request is None or (self.admission is None) != (not self.admission_present and not self.intent_present):
            raise ValueError("recovery member must preserve its original metadata presence")
        if self.admission is not None and (
            self.admission.request != request
            or self.admission.phase not in (AdmissionPhase.RESERVED, AdmissionPhase.READY)
        ):
            raise ValueError("recovery member is not its original reservation or admission")
        if len(self.leases) > 1 or any(
            lease.request != request or (lease.state, lease.version, lease.closure_id) != ("ACTIVE", 1, None)
            for lease in self.leases
        ):
            raise ValueError("recovery member original upload lease differs")
        if self.admission is not None:
            claim = self.admission.claim_ref
            if (claim is None and self.leases) or (
                claim is not None and (len(self.leases) != 1 or self.leases[0].claim_ref != claim)
            ):
                raise ValueError("recovery member claim and original lease differ")
        return self


def _recovery_request(member: _RecoveryClosureMember) -> AdmissionRequest:
    if member.record.request is None:
        raise OpportunityError(_MISSING)
    return member.record.request


def _recovery_envelope(member: _RecoveryClosureMember, *, erased: bool) -> AdmissionEnvelope:
    original = member.admission
    body = (
        original.model_dump(exclude={"metadata_digest"})
        if original is not None
        else {
            "schema_version": "m9.manual-admission.v1",
            "request": _recovery_request(member),
            "claim_ref": None,
            "objects": (),
            "admitted_at": None,
            "deadlines": None,
            "dispatch_claim": None,
        }
    )
    body.update(
        phase=AdmissionPhase.ERASED if erased else AdmissionPhase.CLEANUP_PENDING,
        version=(0 if original is None else original.version) + (2 if erased else 1),
    )
    return AdmissionEnvelope.model_validate({**body, "metadata_digest": admission_metadata_digest(body)})


def _recovery_refs(members: tuple[_RecoveryClosureMember, ...], proof: CustodianSpendReceipt | None) -> tuple[str, ...]:
    refs = {_recovery_request(member).publication_key for member in members}
    for member in members:
        if member.admission is not None:
            refs.update(
                ref
                for obj in member.admission.objects
                for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)
            )
    if proof is not None:
        publications = {publication.request.publication_key: publication for publication in proof.metadata.publications}
        for member in members:
            request = _recovery_request(member)
            original = publications.get(request.publication_key)
            if original is not None and original.request != request:
                raise ValueError("recovery proof request differs from fenced original")
            if original is None:
                publications[request.publication_key] = CustodianPublicationDisposition(
                    request=request,
                    state="NEVER_ISSUED",
                    header=None,
                )
            if member.admission is not None and member.admission.phase == AdmissionPhase.READY:
                if original is None or original.header is None or member.admission.claim_ref is None:
                    raise ValueError("ready recovery member lacks its original signed header")
                expected = manual_publication_metadata_for_request(
                    request,
                    member.admission.claim_ref,
                    tuple(PublicationObjectRef.from_descriptor(obj) for obj in member.admission.objects),
                )
                if original.header.metadata != expected:
                    raise ValueError("recovery proof original refs differ from admitted refs")
            if member.leases and member.leases[0].claim_ref != proof.metadata.claim_ref:
                raise ValueError("recovery proof differs from the original SQL upload claim")
        CustodianSpendSubject(
            root_request=proof.metadata.root_request,
            claim_ref=proof.metadata.claim_ref,
            publications=tuple(publications.values()),
        )
        for publication in publications.values():
            refs.add(publication.request.publication_key)
            if publication.header is not None:
                refs.update(
                    ref
                    for obj in publication.header.metadata.objects
                    for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)
                )
    return tuple(sorted(refs))


@dataclass(frozen=True)
class ManualRecoveryClosurePlan:
    attempt_id: str
    members: tuple[_RecoveryClosureMember, ...]
    planning_transaction: object


class _RecoveryClosureRecord(M9ContractModel):
    schema_version: Literal["m9.manual-recovery-closure.v1"] = "m9.manual-recovery-closure.v1"
    fence: AdmissionClosureIntent
    intent: AdmissionClosureIntent
    members: tuple[_RecoveryClosureMember, ...] = Field(min_length=1)
    reads: tuple[_ReadLeaseRecord, ...]
    reads_drained_at: AwareDatetime | None = None
    public_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proof: CustodianSpendReceipt | None = None
    authorized_at: AwareDatetime | None = None
    receipt: AdmissionDeletionReceipt | None = None
    finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def recovery_stages(self) -> Self:
        object.__setattr__(
            self, "members", tuple(sorted(self.members, key=lambda member: member.record.attempt.attempt_id))
        )
        object.__setattr__(self, "reads", tuple(sorted(self.reads, key=lambda read: read.permit.lease_id)))
        ids = [member.record.attempt.attempt_id for member in self.members]
        keys = [_recovery_request(member).publication_key for member in self.members]
        root = next(
            (member for member in self.members if member.record.attempt.attempt_id == self.fence.attempt_id), None
        )
        if root is None or len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("recovery closure must freeze unique original members")
        request = _recovery_request(root)
        if (
            (self.fence.user_id, self.fence.project_name) != (request.context.user_id, request.context.project_name)
            or self.fence.phase != "CLEANUP_PENDING"
            or self.fence.version != 1
            or self.fence.attempt_version != root.record.attempt.attempt_version
            or self.fence.envelope_version != _recovery_envelope(root, erased=False).version
            or self.fence.object_refs != _recovery_refs(self.members, None)
            or self.intent.model_dump(exclude={"phase", "version", "object_refs"})
            != self.fence.model_dump(exclude={"phase", "version", "object_refs"})
        ):
            raise ValueError("recovery closure changed its original SQL fence")
        for member in self.members:
            original = _recovery_request(member)
            if (original.context.user_id, original.context.project_name) != (
                request.context.user_id,
                request.context.project_name,
            ):
                raise ValueError("recovery closure contains another scope")
        if len({read.permit.lease_id for read in self.reads}) != len(self.reads) or any(
            read.permit.attempt_id not in ids
            or (read.permit.user_id, read.permit.project_name)
            != (request.context.user_id, request.context.project_name)
            or read.permit.issued_at > self.fence.fenced_at
            for read in self.reads
        ):
            raise ValueError("recovery closure read inventory differs")
        version = self.intent.version
        if version not in (1, 2, 3, 4) or self.intent.phase != ("ERASED" if version == 4 else "CLEANUP_PENDING"):
            raise ValueError("unknown recovery closure stage")
        if (version >= 2) != (self.reads_drained_at is not None) or (
            self.reads_drained_at is not None and self.reads_drained_at < self.fence.fenced_at
        ):
            raise ValueError("recovery erasure requires durable read drainage")
        if version < 3:
            if (
                any(
                    value is not None
                    for value in (self.public_key, self.proof, self.authorized_at, self.receipt, self.finished_at)
                )
                or self.intent.object_refs != self.fence.object_refs
            ):
                raise ValueError("recovery proof cannot precede read drainage")
        else:
            if (
                self.proof is None
                or self.public_key is None
                or self.authorized_at is None
                or self.reads_drained_at is None
            ):
                raise ValueError("recovery public deletion requires original private proof")
            verify_custodian_spent(
                canonical_json_bytes(self.proof),
                public_key=bytes.fromhex(self.public_key),
                expected_request=request,
                closure_id=self.fence.closure_id,
            )
            if (
                not self.proof.metadata.inventory_complete
                or not self.reads_drained_at <= self.proof.metadata.deleted_at <= self.authorized_at
            ):
                raise ValueError("recovery proof must follow drainage and precede public authorization")
            if self.intent.object_refs != _recovery_refs(self.members, self.proof):
                raise ValueError("recovery deletion refs differ from authenticated original inventory")
            if version == 3 and (self.receipt is not None or self.finished_at is not None):
                raise ValueError("recovery public deletion is still pending")
            if version == 4 and (
                self.receipt is None
                or self.finished_at is None
                or self.receipt.closure != self.intent.model_copy(update={"phase": "CLEANUP_PENDING", "version": 3})
                or self.receipt.retained_proofs
                or not self.authorized_at <= self.receipt.deleted_at <= self.finished_at
            ):
                raise ValueError("recovery completion requires both physical receipts")
        return self

    def state(self) -> ManualCleanupState:
        root = next(member for member in self.members if member.record.attempt.attempt_id == self.fence.attempt_id)
        claim = (
            root.admission.claim_ref
            if root.admission is not None
            else (root.leases[0].claim_ref if root.leases else None)
        )
        return ManualCleanupState(
            intent=self.intent,
            root_request=_recovery_request(root),
            requests=tuple(_recovery_request(member) for member in self.members),
            claim_ref=claim,
            proof=self.proof,
        )


def _record_digest(record: M9ContractModel) -> str:
    record = type(record).model_validate(record.model_dump())
    return digest_canonical({"domain": "m9.manual-sql-record.v1", "body": record})


def _pack(record: M9ContractModel) -> dict[str, Any]:
    record = type(record).model_validate(record.model_dump())
    return {"metadata": record.model_dump(mode="json"), "metadata_digest": _record_digest(record)}


def _unpack[T: M9ContractModel](kind: type[T], raw: dict[str, Any], *, digest: str | None = None) -> T:
    try:
        if set(raw) != {"metadata", "metadata_digest"}:
            raise ValueError("unexpected SQL record fields")
        result = kind.model_validate(raw["metadata"])
        if _record_digest(result) != raw["metadata_digest"] or (
            digest is not None and digest != raw["metadata_digest"]
        ):
            raise ValueError("SQL record metadata digest differs")
        return result
    except (ValueError, TypeError, KeyError):
        raise OpportunityError(_MISSING) from None


async def _flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except SQLAlchemyError:
        raise OpportunityError(_MISSING) from None


def _upload_lease(row: M9ManualUploadLeaseModel) -> _UploadLeaseRecord:
    value = _unpack(_UploadLeaseRecord, row.body_json, digest=row.metadata_digest)
    request = value.request
    if (
        row.user_id,
        row.project_name,
        row.claim_ref,
        row.upload_version,
        row.attempt_id,
        row.source_kind,
        row.source_contract_version,
        row.state,
        row.version,
        row.closure_id,
    ) != (
        request.context.user_id,
        request.context.project_name,
        value.claim_ref,
        request.upload_version,
        request.attempt_id,
        request.descriptor.source_kind,
        request.descriptor.source_contract_version,
        value.state,
        value.version,
        value.closure_id,
    ):
        raise OpportunityError(_MISSING)
    return value


def _read_lease(row: M9ManualReadLeaseModel) -> _ReadLeaseRecord:
    value = _unpack(_ReadLeaseRecord, row.body_json, digest=row.metadata_digest)
    permit = value.permit
    if any(
        getattr(row, name) != getattr(permit, name)
        for name in (
            "user_id",
            "project_name",
            "lease_id",
            "attempt_id",
            "envelope_version",
            "operational",
            "issued_at",
            "expires_at",
        )
    ) or (row.attempt_version, row.released_at) != (value.attempt_version, value.released_at):
        raise OpportunityError(_MISSING)
    return value


class ManualAdmissionRepository:
    """SQL only. Callers authenticate published material before invoking attach."""

    def __init__(
        self, session: AsyncSession, *, user_id: str, project_name: str, policy_identity: PolicyIdentity | None = None
    ) -> None:
        self.session, self.user_id, self.project_name = session, user_id, project_name
        self.policy_identity = policy_identity
        self.profiles = OpportunityProfileRepository(session)
        self.queries = SourceQueryRepository(session, user_id=user_id, project_name=project_name)
        self.capabilities = CapabilityEvidenceRepository(session, user_id=user_id, project_name=project_name)

    def _scope(self, context: CommandContext) -> None:
        if (context.user_id, context.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)

    async def lock_commands(self, contexts: Sequence[CommandContext]) -> None:
        """Acquire a complete sorted command plan before any lower-ranked lock."""
        transaction = self.session.sync_session.get_transaction()
        if transaction is None:
            raise OpportunityError(_MISSING)
        state = self.session.info.get("m9_manual_command_plan")
        if state is None or state["transaction"] is not transaction:
            state = {"transaction": transaction, "keys": set(), "lower": False}
            self.session.info["m9_manual_command_plan"] = state
        ordered = sorted(contexts, key=lambda c: (c.user_id, c.actor_id, c.command_id))
        for context in ordered:
            self._scope(context)
            key = (context.user_id, context.actor_id, "acquire", context.command_id)
            if key in state["keys"]:
                continue
            if state["lower"] or (state["keys"] and key < max(state["keys"])):
                raise OpportunityError(_STALE)
            await self.profiles.lock_command_key(context=context, operation="acquire")
            state["keys"].add(key)

    async def _row(self, attempt_id: str, *, lock: bool = False) -> M9AcquisitionAttemptModel | None:
        statement = (
            select(M9AcquisitionAttemptModel)
            .where(
                M9AcquisitionAttemptModel.user_id == self.user_id,
                M9AcquisitionAttemptModel.project_name == self.project_name,
                M9AcquisitionAttemptModel.attempt_id == attempt_id,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def _record(self, row: M9AcquisitionAttemptModel, *, cleanup_only: bool = False) -> _AttemptRecord:
        if row.protocol_version != "m9.acquisition.v2":
            raise OpportunityError(_MISSING)
        record = _unpack(_AttemptRecord, row.body_json)
        command, attempt = record.command, record.attempt
        self._scope(command.context)
        if (
            digest_acquisition_request_v2(command) != attempt.request_digest
            or any(
                getattr(row, name) != getattr(attempt, name)
                for name in (
                    "protocol_version",
                    "user_id",
                    "project_name",
                    "actor_id",
                    "command_id",
                    "attempt_id",
                    "attempt_version",
                    "request_digest",
                    "query_id",
                    "query_revision",
                    "state",
                )
            )
            or (
                attempt.query_id,
                attempt.query_revision,
                attempt.query_digest,
                attempt.user_id,
                attempt.project_name,
                attempt.actor_id,
                attempt.command_id,
            )
            != (
                command.query_id,
                command.query_revision,
                command.query_digest,
                command.context.user_id,
                command.context.project_name,
                command.context.actor_id,
                command.context.command_id,
            )
        ):
            raise OpportunityError(_MISSING)
        if (
            row.operation != "acquire"
            or row.transitioned_at != record.changed_at
            or (
                record.descriptor.user_id,
                record.descriptor.project_name,
                record.descriptor.source_contract_version,
            )
            != (self.user_id, self.project_name, attempt.adapter_version)
        ):
            raise OpportunityError(_MISSING)
        query = await self.queries.get_exact(attempt.query_id, attempt.query_revision)
        if (
            query is None
            or query.query_digest != attempt.query_digest
            or (query.source_kind, query.source_contract_version)
            != (record.descriptor.source_kind, record.descriptor.source_contract_version)
        ):
            raise OpportunityError(_MISSING)
        if attempt.started_at is not None and attempt.started_at > row.transitioned_at:
            raise OpportunityError(_MISSING)
        if attempt.completed_at is not None and attempt.completed_at != row.transitioned_at:
            raise OpportunityError(_MISSING)
        request = record.request
        if request is not None and (
            request.context != command.context
            or request.descriptor != record.descriptor
            or (
                request.attempt_id,
                request.request_digest,
                request.query_id,
                request.query_revision,
                request.query_digest,
            )
            != (
                attempt.attempt_id,
                attempt.request_digest,
                attempt.query_id,
                attempt.query_revision,
                attempt.query_digest,
            )
            or request.attempt_version > attempt.attempt_version
        ):
            raise OpportunityError(_MISSING)
        await self._verify_history(record)
        if attempt.state in (AttemptStateV2.EXPIRED_UNRECOVERABLE, AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED):
            await self._verify_terminal_receipt(record, cleanup_only=cleanup_only)
        elif record.receipt is not None or attempt.state in (AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED):
            raise OpportunityError(_MISSING)
        return record

    async def _subject(self, record: _AttemptRecord, *, operational: bool) -> SourceQuery:
        if operational and await self._material_unavailable(record):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        state = self.session.info["m9_manual_command_plan"]
        state["lower"] = True
        await self.session.execute(text("LOCK TABLE adaptation_heads IN SHARE MODE"))
        policy = None
        if operational:
            if self.policy_identity is None:
                raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
            policy = await self.policy_identity()
        query = await self.queries.get_exact(record.command.query_id, record.command.query_revision)
        if (
            query is None
            or query.query_digest != record.command.query_digest
            or (query.source_kind, query.source_contract_version)
            != (record.descriptor.source_kind, record.descriptor.source_contract_version)
        ):
            raise OpportunityError(_MISSING)
        grant = await self.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
        evaluation = await self.capabilities.get_evaluation(query.capability_evaluation_id)
        if (
            grant is None
            or evaluation is None
            or (grant.source_kind, grant.source_contract_version) != (query.source_kind, query.source_contract_version)
            or (grant.grant_digest, evaluation.evaluation_digest)
            != (query.capability_grant_digest, query.capability_evaluation_digest)
        ):
            raise OpportunityError(_MISSING)
        await self.capabilities.consume(grant, evaluation, actor_id=record.command.context.actor_id)
        head = await self.profiles.get_head_for_update(
            user_id=self.user_id, project_name=self.project_name, profile_id=query.cohort_profile_id
        )
        profile = await self.profiles.get_exact(
            user_id=self.user_id,
            project_name=self.project_name,
            profile_id=query.cohort_profile_id,
            revision=query.cohort_profile_revision,
        )
        query_head = await self.queries.get_head(query.query_id)
        if operational:
            if policy is None:
                raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
            if (
                profile is None
                or head is None
                or (
                    profile.profile_digest,
                    head.current_revision,
                    profile.payload.cohort_id,
                    profile.payload.cohort_version,
                    profile.payload.creative_profile_id,
                    profile.payload.creative_profile_version,
                    profile.payload.creative_policy_pack_digest,
                )
                != (
                    query.cohort_profile_digest,
                    query.cohort_profile_revision,
                    query.cohort_id,
                    query.cohort_version,
                    *policy,
                )
            ):
                raise OpportunityError(StopCode.M9_COHORT_LEAKAGE)
            rules = [r for r in profile.payload.source_rules if r.source_kind == query.source_kind]
            if (
                len(rules) != 1
                or query.intent not in rules[0].allowed_intents
                or not {r.data_class for r in grant.data_rules} <= set(rules[0].allowed_data_classes)
            ):
                raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
            if query_head is None or (query_head.current_revision, query_head.head_version) != (
                record.command.query_revision,
                record.command.expected_query_head_version,
            ):
                raise OpportunityError(_STALE)
            await self._require_capability(record, query)
        return query

    async def _require_capability(self, record: _AttemptRecord, query: SourceQuery) -> None:
        grant = await self.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
        evaluation = await self.capabilities.get_evaluation(query.capability_evaluation_id)
        if grant is None or evaluation is None:
            raise OpportunityError(_MISSING)
        request = CapabilityEvaluationRequest(
            user_id=self.user_id,
            project_name=self.project_name,
            actor_id=record.command.context.actor_id,
            grant_id=grant.grant_id,
            grant_version=grant.grant_version,
            grant_digest=grant.grant_digest,
            source_kind=query.source_kind,
            operation=query.operation,
            purpose=query.intent,
            account_binding_digest=grant.account_binding_digest,
        )
        validate_capability(grant, evaluation, request, now=await self.profiles.database_time())
        latest = await self.capabilities.get_latest_grant(query.capability_grant_id)
        if latest is None:
            raise OpportunityError(_MISSING)
        if (latest.grant_version, latest.grant_digest) != (
            query.capability_grant_version,
            query.capability_grant_digest,
        ):
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)

    async def _upload_guard(self, claim_ref: str, upload_version: int) -> None:
        digest = digest_canonical(
            {
                "domain": "m9.manual-upload-lock.v1",
                "user_id": self.user_id,
                "project_name": self.project_name,
                "claim_ref": claim_ref,
                "upload_version": upload_version,
            }
        )
        first, second = struct.unpack(">ii", bytes.fromhex(digest.removeprefix("sha256:"))[:8])
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:first,:second)"), {"first": first, "second": second}
        )

    @staticmethod
    def _original_upload_identity(request: AdmissionRequest) -> tuple[str, str, str, str, str, int]:
        return (
            request.context.user_id,
            request.context.project_name,
            request.descriptor.source_kind,
            request.descriptor.source_contract_version,
            request.opaque_upload_id,
            request.upload_version,
        )

    async def _original_upload_guards(self, requests: Sequence[AdmissionRequest]) -> None:
        for identity in sorted({self._original_upload_identity(request) for request in requests}):
            digest = digest_canonical({"domain": "m9.manual-original-upload-lock.v1", "identity": identity})
            first, second = struct.unpack(">ii", bytes.fromhex(digest.removeprefix("sha256:"))[:8])
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(:first,:second)"), {"first": first, "second": second}
            )

    async def _reject_closed_original_upload(self, request: AdmissionRequest) -> None:
        rows = (
            await self.session.scalars(
                select(M9ManualClosureIntentModel)
                .where(
                    M9ManualClosureIntentModel.user_id == self.user_id,
                    M9ManualClosureIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        identity = self._original_upload_identity(request)
        for row in rows:
            stored = (
                await self._recovery_closure_value(row)
                if self._is_recovery_closure(row)
                else await self._closure_value(row)
            )
            if any(
                self._original_upload_identity(
                    _recovery_request(member)
                    if isinstance(member, _RecoveryClosureMember)
                    else member.admission.request
                )
                == identity
                for member in stored.members
            ):
                raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)

    async def _guard(
        self,
        attempt_id: str,
        *,
        operational: bool,
        claim: tuple[str, int] | None = None,
        object_refs: Sequence[str] = (),
        reservation: AdmissionRequest | None = None,
    ) -> tuple[M9AcquisitionAttemptModel, _AttemptRecord]:
        row = await self._row(attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        record = await self._record(row)
        await self.lock_commands((record.command.context,))
        row = await self._row(attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        record = await self._record(row)
        await self._subject(record, operational=operational)
        await self._original_upload_guards(
            tuple(request for request in (record.request, reservation) if request is not None)
        )
        hint = await self._envelope(record)
        claims = set(() if claim is None else (claim,))
        if hint is not None and hint.claim_ref is not None:
            claims.add((hint.claim_ref, hint.request.upload_version))
        for identity in sorted(claims):
            await self._upload_guard(*identity)
        await self._object_guards((*object_refs, *(self._admission_refs(hint) if hint is not None else ())))
        row = await self._row(attempt_id, lock=True)
        if row is None:
            raise OpportunityError(_MISSING)
        return row, await self._record(row)

    async def _save_attempt(
        self, row: M9AcquisitionAttemptModel, record: _AttemptRecord, *, transitioned_at: datetime | None = None
    ) -> None:
        if transitioned_at is not None:
            record = record.model_copy(update={"changed_at": transitioned_at})
        attempt = record.attempt
        values = {"attempt_version": attempt.attempt_version, "state": attempt.state, "body_json": _pack(record)}
        if transitioned_at is not None:
            values["transitioned_at"] = transitioned_at
        result = await self.session.execute(
            update(M9AcquisitionAttemptModel)
            .where(
                M9AcquisitionAttemptModel.user_id == self.user_id,
                M9AcquisitionAttemptModel.project_name == self.project_name,
                M9AcquisitionAttemptModel.attempt_id == attempt.attempt_id,
                M9AcquisitionAttemptModel.protocol_version == "m9.acquisition.v2",
                M9AcquisitionAttemptModel.attempt_version == row.attempt_version,
            )
            .values(**values)
            .returning(M9AcquisitionAttemptModel.attempt_id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise OpportunityError(_STALE)
        await _flush(self.session)

    async def get_for_command(self, command: AcquireSourceQueryV2) -> AcquisitionAttemptV2 | None:
        record = await self._command_record(command, cleanup_only=False)
        return None if record is None else record.attempt

    async def get_cleanup_subject(
        self, command: AcquireSourceQueryV2
    ) -> tuple[AcquisitionAttemptV2, ManualBindingDescriptor] | None:
        record = await self._command_record(command, cleanup_only=True)
        return None if record is None else (record.attempt, record.descriptor)

    async def _command_record(self, command: AcquireSourceQueryV2, *, cleanup_only: bool) -> _AttemptRecord | None:
        command = AcquireSourceQueryV2.model_validate(command.model_dump())
        self._scope(command.context)
        await self.lock_commands((command.context,))
        row = (
            await self.session.execute(
                select(M9AcquisitionAttemptModel)
                .where(
                    M9AcquisitionAttemptModel.user_id == self.user_id,
                    M9AcquisitionAttemptModel.actor_id == command.context.actor_id,
                    M9AcquisitionAttemptModel.operation == "acquire",
                    M9AcquisitionAttemptModel.command_id == command.context.command_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.project_name != self.project_name or row.request_digest != digest_acquisition_request_v2(command):
            raise OpportunityError(_CONFLICT)
        record = await self._record(row, cleanup_only=cleanup_only)
        if record.command != command:
            raise OpportunityError(_CONFLICT)
        return record

    async def get_attempt(self, attempt_id: str) -> AcquisitionAttemptV2 | None:
        row = await self._row(attempt_id)
        if row is None:
            return None
        record = await self._record(row)
        return await self.get_for_command(record.command)

    async def get_descriptor(self, attempt_id: str) -> ManualBindingDescriptor | None:
        """Read the original deployment identity even before an envelope exists."""
        attempt = await self.get_attempt(attempt_id)
        if attempt is None:
            return None
        row = await self._row(attempt.attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        return (await self._record(row)).descriptor

    async def prepare(
        self, command: AcquireSourceQueryV2, *, attempt_id: str, descriptor: ManualBindingDescriptor
    ) -> tuple[AcquisitionAttemptV2, bool]:
        command = AcquireSourceQueryV2.model_validate(command.model_dump())
        descriptor = ManualBindingDescriptor.model_validate(descriptor.model_dump())
        self._scope(command.context)
        if (descriptor.user_id, descriptor.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        existing = await self.get_for_command(command)
        if existing is not None:
            row = await self._row(existing.attempt_id)
            if row is None or (await self._record(row)).descriptor != descriptor:
                raise OpportunityError(_CONFLICT)
            return existing, False
        attempt = AcquisitionAttemptV2(
            protocol_version="m9.acquisition.v2",
            attempt_id=attempt_id,
            attempt_version=1,
            user_id=self.user_id,
            project_name=self.project_name,
            actor_id=command.context.actor_id,
            command_id=command.context.command_id,
            request_digest=digest_acquisition_request_v2(command),
            query_id=command.query_id,
            query_revision=command.query_revision,
            query_digest=command.query_digest,
            page_cursor_digest=None,
            state=AttemptStateV2.PLANNED,
            adapter_version=descriptor.source_contract_version,
            started_at=None,
            completed_at=None,
            provider_request_id=None,
            outcome_reason=None,
            closure=None,
            quota_disposition=QuotaDispositionV2.UNKNOWN,
            quota_units_observed=None,
        )
        record = _AttemptRecord(
            command=command,
            descriptor=descriptor,
            attempt=attempt,
            request=None,
            changed_at=await self.profiles.database_time(),
        )
        await self._subject(record, operational=True)
        self.session.add(
            M9AcquisitionAttemptModel(
                **{
                    name: getattr(attempt, name)
                    for name in (
                        "protocol_version",
                        "user_id",
                        "project_name",
                        "actor_id",
                        "command_id",
                        "attempt_id",
                        "attempt_version",
                        "request_digest",
                        "query_id",
                        "query_revision",
                        "state",
                    )
                },
                operation="acquire",
                transitioned_at=record.changed_at,
                body_json=_pack(record),
            )
        )
        await _flush(self.session)
        return attempt, True

    async def start(self, attempt_id: str, *, expected_attempt_version: int) -> AcquisitionAttemptV2:
        row, record = await self._guard(attempt_id, operational=True)
        if record.attempt.attempt_version != expected_attempt_version or record.attempt.state != AttemptStateV2.PLANNED:
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
        attempt = AcquisitionAttemptV2.model_validate(
            {
                **record.attempt.model_dump(),
                "attempt_version": expected_attempt_version + 1,
                "state": AttemptStateV2.RUNNING,
                "started_at": now,
            }
        )
        await self._save_attempt(row, record.model_copy(update={"attempt": attempt}), transitioned_at=now)
        return attempt

    async def _envelope(self, record: _AttemptRecord, *, lock: bool = False) -> AdmissionEnvelope | None:
        statement = (
            select(M9ManualAdmissionModel)
            .where(
                M9ManualAdmissionModel.user_id == self.user_id,
                M9ManualAdmissionModel.project_name == self.project_name,
                M9ManualAdmissionModel.attempt_id == record.attempt.attempt_id,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        row = (await self.session.execute(statement)).scalar_one_or_none()
        intent = (
            await self.session.execute(
                select(M9ManualPublicationIntentModel)
                .where(
                    M9ManualPublicationIntentModel.user_id == self.user_id,
                    M9ManualPublicationIntentModel.project_name == self.project_name,
                    M9ManualPublicationIntentModel.attempt_id == record.attempt.attempt_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            if intent is not None or record.request is not None:
                raise OpportunityError(_MISSING)
            return None
        try:
            envelope = AdmissionEnvelope.model_validate(row.body_json)
            if (
                intent is None
                or AdmissionEnvelope.model_validate(intent.body_json) != envelope
                or (
                    row.user_id,
                    row.project_name,
                    row.attempt_id,
                    row.phase,
                    row.version,
                    row.admitted_at,
                    row.metadata_digest,
                )
                != (
                    self.user_id,
                    self.project_name,
                    record.attempt.attempt_id,
                    envelope.phase,
                    envelope.version,
                    envelope.admitted_at,
                    envelope.metadata_digest,
                )
                or (intent.publication_key, intent.phase, intent.version, intent.metadata_digest)
                != (envelope.request.publication_key, envelope.phase, envelope.version, envelope.metadata_digest)
            ):
                raise ValueError("independent publication intent or envelope columns differ")
            if record.request != envelope.request:
                raise ValueError("original request differs from the frozen attempt")
            if row.erasure_fenced_at is not None and envelope.phase == AdmissionPhase.READY:
                raise ValueError("ready admission cannot ignore a SQL erasure fence")
            witness = await self._recovery_witness(envelope, row)
            if witness is None:
                witness = await self._closure_witness(envelope, row)
            if envelope.claim_ref is not None:
                lease_row = await self.session.get(
                    M9ManualUploadLeaseModel,
                    (
                        self.user_id,
                        self.project_name,
                        envelope.claim_ref,
                        envelope.request.upload_version,
                        record.attempt.attempt_id,
                    ),
                    populate_existing=True,
                )
                if lease_row is None:
                    raise ValueError("admission upload lease is missing")
                lease = _upload_lease(lease_row)
                expected_state = {
                    AdmissionPhase.READY: "ACTIVE",
                    AdmissionPhase.CLEANUP_PENDING: "CLOSING",
                    AdmissionPhase.ERASED: "SPENT",
                }.get(envelope.phase)
                if lease.request != envelope.request or lease.state != expected_state:
                    raise ValueError("admission upload lease differs")
                if witness is not None and lease.closure_id != witness.intent.closure_id:
                    raise ValueError("admission upload closure differs")
            return envelope
        except (ValueError, TypeError):
            raise OpportunityError(_MISSING) from None

    async def _cleanup_envelope(self, record: _AttemptRecord) -> AdmissionEnvelope | None:
        """Read one retained original SQL anchor solely for erasure validation."""
        identity = (self.user_id, self.project_name, record.attempt.attempt_id)
        admission = await self.session.get(M9ManualAdmissionModel, identity, populate_existing=True)
        intent = await self.session.scalar(
            select(M9ManualPublicationIntentModel)
            .where(
                M9ManualPublicationIntentModel.user_id == self.user_id,
                M9ManualPublicationIntentModel.project_name == self.project_name,
                M9ManualPublicationIntentModel.attempt_id == record.attempt.attempt_id,
            )
            .execution_options(populate_existing=True)
        )
        if admission is not None and intent is not None:
            return await self._envelope(record)
        retained = admission if admission is not None else intent
        if retained is None:
            raise OpportunityError(_MISSING)
        try:
            envelope = AdmissionEnvelope.model_validate(retained.body_json)
            if (
                envelope.request != record.request
                or envelope.phase not in (AdmissionPhase.RESERVED, AdmissionPhase.READY)
                or (
                    retained.user_id,
                    retained.project_name,
                    retained.attempt_id,
                    retained.phase,
                    retained.version,
                    retained.metadata_digest,
                )
                != (*identity, envelope.phase, envelope.version, envelope.metadata_digest)
                or (intent is not None and intent.publication_key != envelope.request.publication_key)
                or (
                    admission is not None
                    and (
                        admission.admitted_at != envelope.admitted_at
                        or admission.erasure_fenced_at is not None
                        or admission.erasure_version is not None
                    )
                )
            ):
                raise ValueError("retained cleanup anchor differs from its original columns")
            markers = await self.session.scalar(
                select(M9EventModel.event_id)
                .where(
                    M9EventModel.user_id == self.user_id,
                    M9EventModel.project_name == self.project_name,
                    M9EventModel.aggregate_id == record.attempt.attempt_id,
                    M9EventModel.event_kind.in_(("MANUAL_ADMISSION_FENCED", "MANUAL_RECOVERY_ADMISSION_FENCED")),
                )
                .limit(1)
            )
            if markers is not None or record.attempt.attempt_id in await self._verified_recovery_fences():
                raise ValueError("lost cleanup anchor cannot reset an existing fence")
            leases = await self._recovery_lease_rows(record.attempt.attempt_id)
            _RecoveryClosureMember(
                record=record,
                admission=envelope,
                admission_present=admission is not None,
                intent_present=intent is not None,
                leases=tuple(lease for _, lease in leases),
            )
            return envelope
        except (ValueError, TypeError):
            raise OpportunityError(_MISSING) from None

    async def get_envelope(self, attempt_id: str) -> AdmissionEnvelope | None:
        row = await self._row(attempt_id)
        if row is None:
            return None
        record = await self._record(row)
        await self.lock_commands((record.command.context,))
        row = await self._row(attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        return await self._envelope(await self._record(row))

    async def _save_envelope(
        self,
        envelope: AdmissionEnvelope,
        *,
        expected_version: int,
        missing_admission: bool = False,
        missing_intent: bool = False,
        fenced_at: datetime | None = None,
    ) -> None:
        body = envelope.model_dump(mode="json")
        for kind in (M9ManualAdmissionModel, M9ManualPublicationIntentModel):
            values = {
                "body_json": body,
                "metadata_digest": envelope.metadata_digest,
                "phase": envelope.phase,
                "version": envelope.version,
            }
            if kind is M9ManualAdmissionModel:
                values["admitted_at"] = envelope.admitted_at
            if (kind is M9ManualAdmissionModel and missing_admission) or (
                kind is M9ManualPublicationIntentModel and missing_intent
            ):
                if envelope.phase != AdmissionPhase.CLEANUP_PENDING or fenced_at is None:
                    raise OpportunityError(_MISSING)
                values.update(
                    user_id=self.user_id, project_name=self.project_name, attempt_id=envelope.request.attempt_id
                )
                if kind is M9ManualAdmissionModel:
                    values.update(erasure_fenced_at=fenced_at, erasure_version=1)
                else:
                    values["publication_key"] = envelope.request.publication_key
                self.session.add(kind(**values))
                continue
            result = await self.session.execute(
                update(kind)
                .where(
                    kind.user_id == self.user_id,
                    kind.project_name == self.project_name,
                    kind.attempt_id == envelope.request.attempt_id,
                    kind.version == expected_version,
                )
                .values(**values)
                .returning(kind.attempt_id)
                .execution_options(synchronize_session=False)
            )
            if result.scalar_one_or_none() is None:
                raise OpportunityError(_STALE)
        await _flush(self.session)

    async def reserve(self, request: AdmissionRequest, *, expected_attempt_version: int) -> AdmissionEnvelope:
        request = AdmissionRequest.model_validate(request.model_dump())
        existing = await self.get_envelope(request.attempt_id)
        if existing is not None:
            if existing.request != request:
                raise OpportunityError(_CONFLICT)
            return existing
        row, record = await self._guard(request.attempt_id, operational=True, reservation=request)
        await self._reject_closed_original_upload(request)
        attempt = record.attempt
        if attempt.attempt_version != expected_attempt_version or attempt.state != AttemptStateV2.RUNNING:
            raise OpportunityError(_STALE)
        if (
            request.context != record.command.context
            or request.descriptor != record.descriptor
            or (
                request.attempt_version,
                request.request_digest,
                request.query_id,
                request.query_revision,
                request.query_digest,
            )
            != (
                attempt.attempt_version,
                attempt.request_digest,
                attempt.query_id,
                attempt.query_revision,
                attempt.query_digest,
            )
        ):
            raise OpportunityError(_CONFLICT)
        query = await self.queries.get_exact(attempt.query_id, attempt.query_revision)
        if query is None:
            raise OpportunityError(_MISSING)
        grant = await self.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
        if grant is None or any(r not in grant.data_rules for r in request.data_rules):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        body = {
            "schema_version": "m9.manual-admission.v1",
            "request": request,
            "phase": AdmissionPhase.RESERVED,
            "version": 1,
            "claim_ref": None,
            "objects": (),
            "admitted_at": None,
            "deadlines": None,
            "dispatch_claim": None,
        }
        envelope = AdmissionEnvelope.model_validate({**body, "metadata_digest": admission_metadata_digest(body)})
        await self._save_attempt(row, record.model_copy(update={"request": request}))
        for kind in (M9ManualAdmissionModel, M9ManualPublicationIntentModel):
            values = {
                "user_id": self.user_id,
                "project_name": self.project_name,
                "attempt_id": attempt.attempt_id,
                "phase": envelope.phase,
                "version": 1,
                "body_json": envelope.model_dump(mode="json"),
                "metadata_digest": envelope.metadata_digest,
            }
            if kind is M9ManualPublicationIntentModel:
                values["publication_key"] = request.publication_key
            self.session.add(kind(**values))
        await _flush(self.session)
        return envelope

    async def attach(self, publication: PublishedAdmission, *, expected_envelope_version: int) -> AdmissionEnvelope:
        publication = PublishedAdmission.model_validate(publication.model_dump())
        existing = await self.get_envelope(publication.request.attempt_id)
        if existing is None:
            raise OpportunityError(_MISSING)
        if existing.request != publication.request:
            raise OpportunityError(_CONFLICT)
        if existing.phase != AdmissionPhase.RESERVED:
            if (existing.claim_ref, existing.objects) != (publication.claim_ref, publication.objects):
                raise OpportunityError(_CONFLICT)
            return existing
        _, record = await self._guard(
            publication.request.attempt_id,
            operational=True,
            claim=(publication.claim_ref, publication.upload_version),
            object_refs=(
                publication.publication_key,
                *(r for o in publication.objects for r in (o.payload_ref, o.integrity_ref, o.attestation_ref)),
            ),
        )
        envelope = await self._envelope(record, lock=True)
        if (
            envelope is None
            or envelope.version != expected_envelope_version
            or record.attempt.state != AttemptStateV2.RUNNING
        ):
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
        proposed_refs = {
            publication.publication_key,
            *(r for o in publication.objects for r in (o.payload_ref, o.integrity_ref, o.attestation_ref)),
        }
        await self._reject_fenced_refs(proposed_refs)
        prior_intents = (
            await self.session.scalars(
                select(M9ManualPublicationIntentModel)
                .where(
                    M9ManualPublicationIntentModel.user_id == self.user_id,
                    M9ManualPublicationIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        for prior in prior_intents:
            try:
                value = AdmissionEnvelope.model_validate(prior.body_json)
            except ValueError:
                raise OpportunityError(_MISSING) from None
            if value.phase in (AdmissionPhase.CLEANUP_PENDING, AdmissionPhase.ERASED) and proposed_refs.intersection(
                self._admission_refs(value)
            ):
                raise OpportunityError(_CONFLICT)
        if record.attempt.started_at is None or now < record.attempt.started_at:
            raise OpportunityError(_MISSING)
        query = await self.queries.get_exact(record.attempt.query_id, record.attempt.query_revision)
        grant = (
            None
            if query is None
            else await self.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
        )
        if grant is None:
            raise OpportunityError(_MISSING)
        deadlines = effective_admission_deadlines(grant, publication.objects, admitted_at=now)
        body = {
            **envelope.model_dump(),
            "phase": AdmissionPhase.READY,
            "version": envelope.version + 1,
            "admitted_at": now,
            "claim_ref": publication.claim_ref,
            "objects": publication.objects,
            "deadlines": deadlines,
        }
        ready = AdmissionEnvelope.model_validate({**body, "metadata_digest": admission_metadata_digest(body)})
        require_admission_access(ready, now=now, operational=True)
        shared = (
            await self.session.scalars(
                select(M9ManualUploadLeaseModel)
                .where(
                    M9ManualUploadLeaseModel.user_id == self.user_id,
                    M9ManualUploadLeaseModel.project_name == self.project_name,
                    M9ManualUploadLeaseModel.claim_ref == publication.claim_ref,
                    M9ManualUploadLeaseModel.upload_version == publication.upload_version,
                )
                .execution_options(populate_existing=True)
                .with_for_update()
            )
        ).all()
        for lease in shared:
            value = _upload_lease(lease)
            if (
                value.state != "ACTIVE"
                or lease.state != value.state
                or (value.request.opaque_upload_id, value.request.data_rules, value.request.original_clocks)
                != (
                    publication.request.opaque_upload_id,
                    publication.request.data_rules,
                    publication.request.original_clocks,
                )
            ):
                raise OpportunityError(_CONFLICT)
        lease = _UploadLeaseRecord(
            request=publication.request, claim_ref=publication.claim_ref, version=1, state="ACTIVE", closure_id=None
        )
        self.session.add(
            M9ManualUploadLeaseModel(
                user_id=self.user_id,
                project_name=self.project_name,
                claim_ref=publication.claim_ref,
                upload_version=publication.upload_version,
                attempt_id=record.attempt.attempt_id,
                source_kind=record.descriptor.source_kind,
                source_contract_version=record.descriptor.source_contract_version,
                state="ACTIVE",
                version=1,
                closure_id=None,
                body_json=_pack(lease),
                metadata_digest=_record_digest(lease),
            )
        )
        await self._save_envelope(ready, expected_version=envelope.version)
        return ready

    def _validate_checkpoint_binding(self, checkpoint: PageCheckpoint, admission: AdmissionEnvelope) -> None:
        if (
            admission.phase != AdmissionPhase.READY
            or admission.deadlines is None
            or admission.dispatch_claim is None
            or admission.admitted_at is None
        ):
            raise OpportunityError(_MISSING)
        page = checkpoint.page
        deadlines = {c.data_class: c for c in admission.deadlines.classes}
        try:
            expected_clocks = tuple(
                EvidenceDataClassClock(
                    data_class=name,
                    captured_at=admission.admitted_at,
                    refresh_due_at=deadlines[name].refresh_due_at,
                    retention_due_at=deadlines[name].retention_due_at,
                )
                for name in page.data_classes
            )
            if page.captured_at != admission.admitted_at or page.data_class_clocks != expected_clocks:
                raise ValueError("checkpoint must preserve original admission clocks")
            if page.payload_ref is not None:
                objects = [
                    o
                    for o in admission.objects
                    if (o.payload_ref, o.integrity_ref, o.evidence_kind)
                    == (page.payload_ref, page.payload_integrity_ref, "raw-page")
                ]
                if len(objects) != 1 or (objects[0].data_classes, objects[0].retained_material_digest) != (
                    page.data_classes,
                    page.retained_source_payload_digest,
                ):
                    raise ValueError("checkpoint raw object differs from original publication")
            elif checkpoint.native_fields or page.raw_media_type is not None:
                raise ValueError("missing page cannot carry native material")
            identities = set()
            material_refs = set()
            for field in checkpoint.native_fields:
                objects = [
                    o
                    for o in admission.objects
                    if (o.payload_ref, o.integrity_ref) == (field.material_ref, field.material_integrity_ref)
                ]
                key = (
                    field.source_identity_ref,
                    field.native_field_name,
                    field.native_field_definition,
                    field.native_field_version,
                    field.data_class,
                    field.unit,
                    field.window_start,
                    field.window_end,
                    field.normalization_version,
                )
                missing = field.missing_reason is not None
                if (
                    key in identities
                    or field.material_ref in material_refs
                    or field.source_identity_ref not in checkpoint.source_identity_refs
                    or field.data_class not in page.data_classes
                    or len(objects) != 1
                    or not objects[0].evidence_kind.startswith("native-field-")
                    or objects[0].data_classes != (field.data_class,)
                    or (field.value_ref, field.value_integrity_ref)
                    != ((None, None) if missing else (field.material_ref, field.material_integrity_ref))
                    or field.retained_normalized_value_digest
                    != (None if missing else objects[0].retained_material_digest)
                ):
                    raise ValueError("checkpoint native object differs from original publication")
                identities.add(key)
                material_refs.add(field.material_ref)
        except (KeyError, ValueError, TypeError):
            raise OpportunityError(_MISSING) from None

    def _validate_checkpoint_chain(self, checkpoints: tuple[PageCheckpoint, ...], query: SourceQuery) -> None:
        previous = None
        refs = set()
        for index, item in enumerate(checkpoints, start=1):
            if (
                item.page.ordinal != index
                or item.page.request_cursor_digest != (previous.page.response_cursor_digest if previous else None)
                or (previous is not None and previous.terminal_page)
                or (item.page.payload_ref is not None and item.page.payload_ref in refs)
                or (
                    item.page.response_cursor_digest is not None
                    and item.page.response_cursor_digest in {c.page.request_cursor_digest for c in checkpoints}
                )
            ):
                raise OpportunityError(_MISSING)
            if item.page.payload_ref is not None:
                refs.add(item.page.payload_ref)
            previous = item
        if (
            len(checkpoints) > query.max_pages
            or sum(c.page.record_count for c in checkpoints) > query.max_records
            or sum(c.page.raw_size_bytes for c in checkpoints) > 41_943_040
            or sum(c.quota_units_observed or 0 for c in checkpoints) > query.max_quota_units
        ):
            raise OpportunityError(StopCode.M9_OPERATIONAL_ENVELOPE_EXCEEDED)

    async def list_checkpoints(self, attempt_id: str) -> tuple[PageCheckpoint, ...]:
        attempt = await self.get_attempt(attempt_id)
        if attempt is None:
            return ()
        row = await self._row(attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        record = await self._record(row)
        return await self._checkpoints(record)

    async def _checkpoints(self, record: _AttemptRecord, *, cleanup_only: bool = False) -> tuple[PageCheckpoint, ...]:
        attempt = record.attempt
        attempt_id = attempt.attempt_id
        envelope = await self._cleanup_envelope(record) if cleanup_only else await self._envelope(record)
        rows = (
            await self.session.scalars(
                select(M9SnapshotPageModel)
                .where(
                    M9SnapshotPageModel.user_id == self.user_id,
                    M9SnapshotPageModel.project_name == self.project_name,
                    M9SnapshotPageModel.attempt_id == attempt_id,
                )
                .order_by(M9SnapshotPageModel.ordinal)
                .execution_options(populate_existing=True)
            )
        ).all()
        checkpoints = []
        for page_row in rows:
            stored = _unpack(_CheckpointRecord, page_row.checkpoint_json)
            original, checkpoint = stored.admission, stored.checkpoint
            if (
                envelope is None
                or any(
                    getattr(original, name) != getattr(envelope, name)
                    for name in ("request", "claim_ref", "objects", "admitted_at", "deadlines", "dispatch_claim")
                )
                or (page_row.user_id, page_row.project_name, page_row.attempt_id, page_row.ordinal, page_row.body_json)
                != (
                    self.user_id,
                    self.project_name,
                    attempt_id,
                    checkpoint.page.ordinal,
                    checkpoint.page.model_dump(mode="json"),
                )
            ):
                raise OpportunityError(_MISSING)
            self._validate_checkpoint_binding(checkpoint, original)
            checkpoints.append(checkpoint)
        query = await self.queries.get_exact(attempt.query_id, attempt.query_revision)
        if query is None:
            raise OpportunityError(_MISSING)
        result = tuple(checkpoints)
        self._validate_checkpoint_chain(result, query)
        return result

    async def append_checkpoint(
        self, attempt_id: str, checkpoint: PageCheckpoint, *, expected_attempt_version: int
    ) -> PageCheckpoint:
        try:
            checkpoint = PageCheckpoint.model_validate(checkpoint.model_dump())
        except ValueError:
            raise OpportunityError(_MISSING) from None
        existing = await self.list_checkpoints(attempt_id)
        ordinal = checkpoint.page.ordinal
        if ordinal <= len(existing):
            if existing[ordinal - 1] != checkpoint:
                raise OpportunityError(_CONFLICT)
            return existing[ordinal - 1]
        _, record = await self._guard(attempt_id, operational=True)
        if record.attempt.attempt_version != expected_attempt_version or record.attempt.state not in (
            AttemptStateV2.RUNNING,
            AttemptStateV2.OUTCOME_UNKNOWN,
            AttemptStateV2.NEEDS_OPERATOR,
        ):
            raise OpportunityError(_STALE)
        envelope = await self._envelope(record, lock=True)
        if envelope is None:
            raise OpportunityError(_MISSING)
        now = await self.profiles.database_time()
        require_admission_access(envelope, now=now, operational=True)
        if checkpoint.page.captured_at > now:
            raise OpportunityError(_STALE)
        self._validate_checkpoint_binding(checkpoint, envelope)
        if record.attempt.state != AttemptStateV2.RUNNING and (
            checkpoint.provider_observed_at is not None
            or checkpoint.page.provider_request_id is not None
            or checkpoint.quota_units_observed is not None
        ):
            raise OpportunityError(_MISSING)
        query = await self.queries.get_exact(record.command.query_id, record.command.query_revision)
        if query is None:
            raise OpportunityError(_MISSING)
        self._validate_checkpoint_chain((*existing, checkpoint), query)
        stored = _CheckpointRecord(admission=envelope, checkpoint=checkpoint)
        self.session.add(
            M9SnapshotPageModel(
                user_id=self.user_id,
                project_name=self.project_name,
                attempt_id=attempt_id,
                ordinal=ordinal,
                body_json=checkpoint.page.model_dump(mode="json"),
                checkpoint_json=_pack(stored),
            )
        )
        await _flush(self.session)
        return checkpoint

    async def _validate_snapshot_binding(
        self,
        stored: _SnapshotRecord,
        record: _AttemptRecord,
        envelope: AdmissionEnvelope,
        *,
        cleanup_only: bool = False,
    ) -> None:
        snapshot, provenance, original = stored.snapshot, stored.provenance, stored.admission
        attempt = record.attempt
        query = await self.queries.get_exact(attempt.query_id, attempt.query_revision)
        if (
            original.phase != AdmissionPhase.READY
            or original.admitted_at is None
            or original.dispatch_claim is None
            or original.version > envelope.version
            or any(
                getattr(original, name) != getattr(envelope, name)
                for name in ("request", "claim_ref", "objects", "admitted_at", "deadlines", "dispatch_claim")
            )
            or digest_source_snapshot(snapshot) != snapshot.snapshot_digest
            or digest_snapshot_provenance_v2(provenance) != stored.provenance_digest
            or (snapshot.user_id, snapshot.project_name, snapshot.attempt_id)
            != (self.user_id, self.project_name, attempt.attempt_id)
            or (
                provenance.snapshot_id,
                provenance.snapshot_digest,
                provenance.attempt_id,
                provenance.admission_metadata_digest,
                provenance.admitted_at,
            )
            != (
                snapshot.snapshot_id,
                snapshot.snapshot_digest,
                attempt.attempt_id,
                original.metadata_digest,
                original.admitted_at,
            )
            or not original.dispatch_claim.attempt_version <= provenance.attempt_version <= attempt.attempt_version
            or snapshot.capture_completed_at != original.admitted_at
            or snapshot.capture_started_at != attempt.started_at
            or snapshot.adapter_version != attempt.adapter_version
            or snapshot.revision != 1
            or snapshot.parent_revision is not None
            or not original.admitted_at <= snapshot.created_at <= stored.stored_at
            or any(page.captured_at != original.admitted_at for page in snapshot.pages)
            or query is None
        ):
            raise OpportunityError(_MISSING)
        if (
            snapshot.query_id,
            snapshot.query_revision,
            snapshot.query_digest,
            snapshot.source_kind,
            snapshot.source_contract_version,
            snapshot.requested_record_limit,
            snapshot.capability_grant_digest,
            snapshot.capability_evaluation_digest,
        ) != (
            query.query_id,
            query.revision,
            query.query_digest,
            query.source_kind,
            query.source_contract_version,
            query.max_records,
            query.capability_grant_digest,
            query.capability_evaluation_digest,
        ):
            raise OpportunityError(_MISSING)
        grant = await self.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
        evaluation = await self.capabilities.get_evaluation(query.capability_evaluation_id)
        if (
            grant is None
            or evaluation is None
            or (
                grant.grant_digest,
                evaluation.evaluation_digest,
                evaluation.grant_id,
                evaluation.grant_version,
                evaluation.grant_digest,
            )
            != (
                query.capability_grant_digest,
                query.capability_evaluation_digest,
                grant.grant_id,
                grant.grant_version,
                grant.grant_digest,
            )
        ):
            raise OpportunityError(_MISSING)
        checkpoints = await self._checkpoints(record, cleanup_only=cleanup_only)
        identities = tuple(sorted({ref for c in checkpoints for ref in c.source_identity_refs}))
        if snapshot.pages != tuple(c.page for c in checkpoints) or snapshot.source_identity_refs != identities:
            raise OpportunityError(_MISSING)
        complete = snapshot.coverage_state == CoverageState.COMPLETE_WITHIN_DECLARED_BOUNDS
        if complete and (
            not checkpoints or not checkpoints[-1].terminal_page or any(c.page.payload_ref is None for c in checkpoints)
        ):
            raise OpportunityError(_MISSING)
        if provenance.origin == SnapshotOriginV2.LOCAL_ADMISSION_RECONSTRUCTION:
            if (
                snapshot.provider_observed_at is not None
                or not checkpoints
                or any(c.page.payload_ref is None for c in checkpoints)
            ):
                raise OpportunityError(_MISSING)
        elif (
            provenance.response_recorded_at is None
            or provenance.response_recorded_at > snapshot.created_at
            or snapshot.provider_observed_at
            != max((c.provider_observed_at for c in checkpoints if c.provider_observed_at is not None), default=None)
        ):
            raise OpportunityError(_MISSING)

    async def _snapshot_record(
        self, row: M9SourceSnapshotModel, *, record: _AttemptRecord | None = None, cleanup_only: bool = False
    ) -> _SnapshotRecord:
        if record is None:
            attempt = await self.get_attempt(row.attempt_id)
            if attempt is None:
                raise OpportunityError(_MISSING)
            attempt_row = await self._row(attempt.attempt_id)
            if attempt_row is None:
                raise OpportunityError(_MISSING)
            record = await self._record(attempt_row)
        stored = _unpack(_SnapshotRecord, row.body_json)
        snapshot = stored.snapshot
        if any(
            getattr(row, name) != getattr(snapshot, name)
            for name in (
                "user_id",
                "project_name",
                "snapshot_id",
                "revision",
                "parent_revision",
                "attempt_id",
                "query_id",
                "query_revision",
                "snapshot_digest",
            )
        ):
            raise OpportunityError(_MISSING)
        envelope = await self._cleanup_envelope(record) if cleanup_only else await self._envelope(record)
        if envelope is None:
            raise OpportunityError(_MISSING)
        await self._validate_snapshot_binding(stored, record, envelope, cleanup_only=cleanup_only)
        events = (
            await self.session.scalars(
                select(M9EventModel).where(
                    M9EventModel.user_id == self.user_id,
                    M9EventModel.project_name == self.project_name,
                    M9EventModel.aggregate_id == snapshot.snapshot_id,
                    M9EventModel.aggregate_revision == 1,
                    M9EventModel.event_kind == "MANUAL_SNAPSHOT_STORED",
                )
            )
        ).all()
        if len(events) != 1 or (events[0].payload_digest, events[0].committed_at) != (
            _record_digest(stored),
            stored.stored_at,
        ):
            raise OpportunityError(_MISSING)
        return stored

    async def get_snapshot(
        self, snapshot_id: str, revision: int = 1
    ) -> tuple[SourceSnapshot, SnapshotProvenanceV2] | None:
        row = await self.session.get(
            M9SourceSnapshotModel, (self.user_id, self.project_name, snapshot_id, revision), populate_existing=True
        )
        if row is None:
            return None
        stored = await self._snapshot_record(row)
        return stored.snapshot, stored.provenance

    async def get_query(self, query_id: str, revision: int | None) -> SourceQuery | None:
        if revision is None:
            revision = await self.queries.current_revision(query_id)
            if revision is None:
                return None
        return await self.queries.get_exact(query_id, revision)

    async def list_capability_grants(self, *, after_id: str | None, limit: int) -> tuple[SourceCapabilityGrant, ...]:
        return await self.capabilities.list_latest(after_id=after_id, limit=limit)

    async def list_snapshot_ids(self, query_id: str, *, after_id: str | None, limit: int) -> tuple[str, ...]:
        statement = (
            select(M9SourceSnapshotModel.snapshot_id)
            .join(
                M9AcquisitionAttemptModel,
                (M9AcquisitionAttemptModel.user_id == M9SourceSnapshotModel.user_id)
                & (M9AcquisitionAttemptModel.project_name == M9SourceSnapshotModel.project_name)
                & (M9AcquisitionAttemptModel.attempt_id == M9SourceSnapshotModel.attempt_id),
            )
            .where(
                M9SourceSnapshotModel.user_id == self.user_id,
                M9SourceSnapshotModel.project_name == self.project_name,
                M9SourceSnapshotModel.query_id == query_id,
                M9SourceSnapshotModel.revision == 1,
                M9AcquisitionAttemptModel.protocol_version == "m9.acquisition.v2",
            )
            .order_by(M9SourceSnapshotModel.snapshot_id)
            .limit(limit)
        )
        if after_id is not None:
            statement = statement.where(M9SourceSnapshotModel.snapshot_id > after_id)
        return tuple(await self.session.scalars(statement))

    async def require_snapshot_read(
        self, attempt_id: str, *, expected_envelope_version: int, operational: bool
    ) -> None:
        _, record = await self._guard(attempt_id, operational=operational)
        envelope = await self._envelope(record, lock=True)
        if envelope is None or envelope.version != expected_envelope_version:
            raise OpportunityError(_STALE)
        require_admission_access(envelope, now=await self.profiles.database_time(), operational=operational)
        if await self._material_unavailable(record):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        query = await self.queries.get_exact(record.command.query_id, record.command.query_revision)
        if query is None:
            raise OpportunityError(_MISSING)
        if not operational:
            await self._require_capability(record, query)

    async def _snapshot_row_for_attempt(self, attempt_id: str) -> M9SourceSnapshotModel | None:
        return (
            await self.session.scalars(
                select(M9SourceSnapshotModel)
                .where(
                    M9SourceSnapshotModel.user_id == self.user_id,
                    M9SourceSnapshotModel.project_name == self.project_name,
                    M9SourceSnapshotModel.attempt_id == attempt_id,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()

    async def get_snapshot_for_attempt(self, attempt_id: str) -> tuple[SourceSnapshot, SnapshotProvenanceV2] | None:
        if await self.get_attempt(attempt_id) is None:
            return None
        row = await self._snapshot_row_for_attempt(attempt_id)
        if row is None:
            return None
        stored = await self._snapshot_record(row)
        return stored.snapshot, stored.provenance

    async def append_snapshot(
        self, snapshot: SourceSnapshot, provenance: SnapshotProvenanceV2, *, expected_attempt_version: int
    ) -> None:
        try:
            snapshot = SourceSnapshot.model_validate(snapshot.model_dump())
            provenance = SnapshotProvenanceV2.model_validate(provenance.model_dump())
        except ValueError:
            raise OpportunityError(_MISSING) from None
        if (snapshot.user_id, snapshot.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(_MISSING)
        if await self.get_attempt(snapshot.attempt_id) is None:
            raise OpportunityError(_MISSING)
        existing = await self._snapshot_row_for_attempt(snapshot.attempt_id)
        if existing is not None:
            stored = await self._snapshot_record(existing)
            if (stored.snapshot, stored.provenance) != (snapshot, provenance):
                raise OpportunityError(_CONFLICT)
            return
        collision = await self.session.get(
            M9SourceSnapshotModel, (self.user_id, self.project_name, snapshot.snapshot_id, snapshot.revision)
        )
        if collision is not None:
            raise OpportunityError(_CONFLICT)
        _, record = await self._guard(snapshot.attempt_id, operational=True)
        if (
            record.attempt.attempt_version != expected_attempt_version
            or provenance.attempt_version != expected_attempt_version
        ):
            raise OpportunityError(_STALE)
        if record.attempt.state not in (
            AttemptStateV2.RUNNING,
            AttemptStateV2.OUTCOME_UNKNOWN,
            AttemptStateV2.NEEDS_OPERATOR,
        ):
            raise OpportunityError(_STALE)
        if (
            provenance.origin == SnapshotOriginV2.SOURCE_RESPONSE_VERIFIED
            and record.attempt.state != AttemptStateV2.RUNNING
        ):
            raise OpportunityError(_MISSING)
        envelope = await self._envelope(record, lock=True)
        if envelope is None:
            raise OpportunityError(_MISSING)
        now = await self.profiles.database_time()
        require_admission_access(envelope, now=now, operational=True)
        stored = _SnapshotRecord(
            admission=envelope,
            snapshot=snapshot,
            provenance=provenance,
            provenance_digest=digest_snapshot_provenance_v2(provenance),
            stored_at=now,
        )
        await self._validate_snapshot_binding(stored, record, envelope)
        self.session.add(
            M9SourceSnapshotModel(
                **{
                    name: getattr(snapshot, name)
                    for name in (
                        "user_id",
                        "project_name",
                        "snapshot_id",
                        "revision",
                        "parent_revision",
                        "attempt_id",
                        "query_id",
                        "query_revision",
                        "snapshot_digest",
                    )
                },
                body_json=_pack(stored),
            )
        )
        self.session.add(
            M9EventModel(
                user_id=self.user_id,
                project_name=self.project_name,
                event_kind="MANUAL_SNAPSHOT_STORED",
                aggregate_id=snapshot.snapshot_id,
                aggregate_revision=1,
                payload_digest=_record_digest(stored),
                committed_at=now,
            )
        )
        await _flush(self.session)

    async def _guard_dependencies(
        self,
        records: dict[str, _AttemptRecord],
        *,
        operational_attempt_id: str | None,
        cleanup_only: bool = False,
        additional_object_refs: Sequence[str] = (),
    ) -> None:
        """Prelock every rank across the dependency set before validating subjects."""
        await self.lock_commands(tuple(record.command.context for record in records.values()))
        self.session.info["m9_manual_command_plan"]["lower"] = True
        await self.session.execute(text("LOCK TABLE adaptation_heads IN SHARE MODE"))
        queries = {}
        identities = set()
        for attempt_id, record in sorted(records.items()):
            query = await self.queries.get_exact(record.command.query_id, record.command.query_revision)
            if query is None:
                raise OpportunityError(_MISSING)
            queries[attempt_id] = query
            identities.add(("grant-head", query.capability_grant_id))
            identities.add(("grant", query.capability_grant_id, str(query.capability_grant_version)))
            identities.add(("evaluation", query.capability_evaluation_id))
        # Match CapabilityEvidenceRepository.consume's existing advisory identities.
        for identity in sorted(identities, key=lambda item: (item[1], item[0], item[2:])):
            guard = digest_canonical(
                {
                    "domain": "m9.capability-admission-lock.v1",
                    "user_id": self.user_id,
                    "project_name": self.project_name,
                    "identity": identity,
                }
            )
            first, second = struct.unpack(">ii", bytes.fromhex(guard.removeprefix("sha256:"))[:8])
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(:first,:second)"), {"first": first, "second": second}
            )
        for profile_id in sorted({q.cohort_profile_id for q in queries.values()}):
            await self.profiles.get_head_for_update(
                user_id=self.user_id, project_name=self.project_name, profile_id=profile_id
            )
        for query_id in sorted({q.query_id for q in queries.values()}):
            await self.queries.get_head(query_id)
        for attempt_id, record in sorted(records.items()):
            await self._subject(record, operational=attempt_id == operational_attempt_id)
        await self._original_upload_guards(tuple(r.request for r in records.values() if r.request is not None))
        claims = set()
        object_refs = set(additional_object_refs)
        for record in records.values():
            envelope = await self._cleanup_envelope(record) if cleanup_only else await self._envelope(record)
            if envelope is not None and envelope.claim_ref is not None:
                claims.add((envelope.claim_ref, envelope.request.upload_version))
            if envelope is not None:
                object_refs.update(self._admission_refs(envelope))
        for identity in sorted(claims):
            await self._upload_guard(*identity)
        await self._object_guards(tuple(object_refs))
        for attempt_id, expected in sorted(records.items()):
            row = await self._row(attempt_id, lock=True)
            if row is None or await self._record(row, cleanup_only=cleanup_only) != expected:
                raise OpportunityError(_STALE)
        for record in records.values():
            if cleanup_only:
                await self._cleanup_envelope(record)
            else:
                await self._envelope(record, lock=True)

    async def _observation_rows(self, observation_id: str) -> tuple[M9SourceObservationModel, ...]:
        return tuple(
            (
                await self.session.scalars(
                    select(M9SourceObservationModel)
                    .where(
                        M9SourceObservationModel.user_id == self.user_id,
                        M9SourceObservationModel.project_name == self.project_name,
                        M9SourceObservationModel.observation_id == observation_id,
                    )
                    .order_by(M9SourceObservationModel.revision)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def _observation_head(self, observation_id: str, *, lock: bool = False) -> M9ObservationHeadModel | None:
        statement = (
            select(M9ObservationHeadModel)
            .where(
                M9ObservationHeadModel.user_id == self.user_id,
                M9ObservationHeadModel.project_name == self.project_name,
                M9ObservationHeadModel.observation_id == observation_id,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def _observation_plan(
        self, observation_id: str, *, snapshot_id: str | None = None
    ) -> tuple[tuple[M9SourceObservationModel, ...], dict[str, _AttemptRecord]]:
        rows = await self._observation_rows(observation_id)
        initial = tuple((r.revision, r.snapshot_id, r.observation_digest) for r in rows)
        snapshot_ids = {r.snapshot_id for r in rows}
        if snapshot_id is not None:
            snapshot_ids.add(snapshot_id)
        records = {}
        dependencies = {}
        for identity in sorted(snapshot_ids):
            snapshot_row = await self.session.get(
                M9SourceSnapshotModel, (self.user_id, self.project_name, identity, 1), populate_existing=True
            )
            if snapshot_row is None:
                raise OpportunityError(_MISSING)
            row = await self._row(snapshot_row.attempt_id)
            if row is None:
                raise OpportunityError(_MISSING)
            record = await self._record(row)
            records[row.attempt_id] = record
            dependencies[identity] = row.attempt_id
        await self.lock_commands(tuple(record.command.context for record in records.values()))
        for identity, attempt_id in dependencies.items():
            snapshot_row = await self.session.get(
                M9SourceSnapshotModel, (self.user_id, self.project_name, identity, 1), populate_existing=True
            )
            if snapshot_row is None or snapshot_row.attempt_id != attempt_id:
                raise OpportunityError(_STALE)
        rows = await self._observation_rows(observation_id)
        if tuple((r.revision, r.snapshot_id, r.observation_digest) for r in rows) != initial:
            raise OpportunityError(_STALE)
        for attempt_id in records:
            row = await self._row(attempt_id)
            if row is None:
                raise OpportunityError(_MISSING)
            records[attempt_id] = await self._record(row)
        return rows, records

    async def _validate_observation(self, stored: _ObservationRecord) -> None:
        observation = stored.observation
        pair = await self.get_snapshot(observation.snapshot_id)
        if pair is None:
            raise OpportunityError(_MISSING)
        snapshot, provenance = pair
        attempt = await self.get_attempt(snapshot.attempt_id)
        if (
            attempt is None
            or digest_source_observation(observation) != observation.observation_digest
            or (observation.user_id, observation.project_name) != (self.user_id, self.project_name)
            or (observation.snapshot_digest, observation.source_kind)
            != (snapshot.snapshot_digest, snapshot.source_kind)
            or not 1 <= observation.page_ordinal <= len(snapshot.pages)
            or stored.snapshot_provenance_digest != digest_snapshot_provenance_v2(provenance)
            or not provenance.attempt_version <= stored.attempt_version <= attempt.attempt_version
            or not snapshot.created_at <= stored.stored_at
        ):
            raise OpportunityError(_MISSING)
        checkpoints = await self.list_checkpoints(snapshot.attempt_id)
        checkpoint = checkpoints[observation.page_ordinal - 1]
        page = checkpoint.page
        qualifiers = (
            "source_identity_ref",
            "native_field_name",
            "native_field_definition",
            "native_field_version",
            "data_class",
            "unit",
            "window_start",
            "window_end",
            "missing_reason",
            "normalization_version",
            "value_ref",
            "value_integrity_ref",
            "retained_normalized_value_digest",
        )
        fields = [
            f
            for f in checkpoint.native_fields
            if all(getattr(f, key) == getattr(observation, key) for key in qualifiers)
        ]
        if (
            len(fields) != 1
            or observation.source_identity_ref not in checkpoint.source_identity_refs
            or observation.data_class not in page.data_classes
            or (
                observation.payload_integrity_ref,
                observation.retained_source_payload_digest,
                observation.observed_at,
            )
            != (page.payload_integrity_ref, page.retained_source_payload_digest, page.captured_at)
        ):
            raise OpportunityError(_MISSING)
        query = await self.queries.get_exact(snapshot.query_id, snapshot.query_revision)
        if query is None:
            raise OpportunityError(_MISSING)
        grant = await self.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
        rule = (
            None
            if grant is None
            else next((r for r in grant.data_rules if r.data_class == observation.data_class), None)
        )
        if rule is None or (
            observation.retained_normalized_value_digest is not None and not rule.digest_proof_may_be_retained
        ):
            raise OpportunityError(_MISSING)

    @staticmethod
    def _require_observation_parent(
        observation: NormalizedSourceObservation, prior: NormalizedSourceObservation | None
    ) -> None:
        if (observation.revision, observation.parent_revision) != (
            (1, None) if prior is None else (prior.revision + 1, prior.revision)
        ):
            raise OpportunityError(_STALE)
        if prior is not None and any(
            getattr(prior, name) != getattr(observation, name)
            for name in (
                "source_kind",
                "source_identity_ref",
                "native_field_name",
                "native_field_definition",
                "native_field_version",
                "data_class",
                "unit",
                "window_start",
                "window_end",
            )
        ):
            raise OpportunityError(StopCode.M9_NORMALIZATION_LOSSY)

    async def _observation_history(
        self, rows: tuple[M9SourceObservationModel, ...], *, observation_id: str
    ) -> tuple[NormalizedSourceObservation, ...]:
        values = []
        for row in rows:
            stored = _unpack(_ObservationRecord, row.body_json)
            value = stored.observation
            if any(
                getattr(row, name) != getattr(value, name)
                for name in (
                    "user_id",
                    "project_name",
                    "observation_id",
                    "revision",
                    "parent_revision",
                    "snapshot_id",
                    "snapshot_digest",
                    "source_identity_ref",
                    "observation_digest",
                )
            ):
                raise OpportunityError(_MISSING)
            await self._validate_observation(stored)
            self._require_observation_parent(value, values[-1] if values else None)
            events = (
                await self.session.scalars(
                    select(M9EventModel).where(
                        M9EventModel.user_id == self.user_id,
                        M9EventModel.project_name == self.project_name,
                        M9EventModel.aggregate_id == value.observation_id,
                        M9EventModel.aggregate_revision == value.revision,
                        M9EventModel.event_kind == "MANUAL_OBSERVATION_STORED",
                    )
                )
            ).all()
            if len(events) != 1 or (events[0].payload_digest, events[0].committed_at) != (
                _record_digest(stored),
                stored.stored_at,
            ):
                raise OpportunityError(_MISSING)
            values.append(value)
        head = await self._observation_head(observation_id)
        if (head is None) != (not values) or (
            head is not None and (head.current_revision, head.head_version) != (len(values), len(values))
        ):
            raise OpportunityError(_MISSING)
        return tuple(values)

    async def get_observation(self, observation_id: str, revision: int) -> NormalizedSourceObservation | None:
        rows, _ = await self._observation_plan(observation_id)
        values = await self._observation_history(rows, observation_id=observation_id)
        return next((value for value in values if value.revision == revision), None)

    async def get_current_observation(self, observation_id: str) -> NormalizedSourceObservation | None:
        rows, _ = await self._observation_plan(observation_id)
        values = await self._observation_history(rows, observation_id=observation_id)
        return values[-1] if values else None

    async def append_observation(
        self, observation: NormalizedSourceObservation, *, expected_attempt_version: int
    ) -> None:
        try:
            observation = NormalizedSourceObservation.model_validate(observation.model_dump())
        except ValueError:
            raise OpportunityError(_MISSING) from None
        if (observation.user_id, observation.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(_MISSING)
        rows, records = await self._observation_plan(observation.observation_id, snapshot_id=observation.snapshot_id)
        values = await self._observation_history(rows, observation_id=observation.observation_id)
        existing = next((v for v in values if v.revision == observation.revision), None)
        if existing is not None:
            if existing != observation:
                raise OpportunityError(_CONFLICT)
            return
        self._require_observation_parent(observation, values[-1] if values else None)
        pair = await self.get_snapshot(observation.snapshot_id)
        if pair is None:
            raise OpportunityError(_MISSING)
        snapshot, provenance = pair
        await self._guard_dependencies(records, operational_attempt_id=snapshot.attempt_id)
        record = records[snapshot.attempt_id]
        if record.attempt.attempt_version != expected_attempt_version or record.attempt.state not in (
            AttemptStateV2.RUNNING,
            AttemptStateV2.OUTCOME_UNKNOWN,
            AttemptStateV2.NEEDS_OPERATOR,
        ):
            raise OpportunityError(_STALE)
        envelope = await self._envelope(record, lock=True)
        if envelope is None:
            raise OpportunityError(_MISSING)
        now = await self.profiles.database_time()
        require_admission_access(envelope, now=now, operational=True)
        stored = _ObservationRecord(
            observation=observation,
            snapshot_provenance_digest=digest_snapshot_provenance_v2(provenance),
            attempt_version=expected_attempt_version,
            stored_at=now,
        )
        await self._validate_observation(stored)
        # A guard also serializes an absent head across different first-attempt owners.
        guard = digest_canonical(
            {
                "domain": "m9.manual-observation-lock.v1",
                "user_id": self.user_id,
                "project_name": self.project_name,
                "observation_id": observation.observation_id,
            }
        )
        first, second = struct.unpack(">ii", bytes.fromhex(guard.removeprefix("sha256:"))[:8])
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:first,:second)"), {"first": first, "second": second}
        )
        head = await self._observation_head(observation.observation_id, lock=True)
        if (None if head is None else (head.current_revision, head.head_version)) != (
            None if not values else (values[-1].revision, values[-1].revision)
        ):
            raise OpportunityError(_STALE)
        self.session.add(
            M9SourceObservationModel(
                **{
                    name: getattr(observation, name)
                    for name in (
                        "user_id",
                        "project_name",
                        "observation_id",
                        "revision",
                        "parent_revision",
                        "snapshot_id",
                        "snapshot_digest",
                        "source_identity_ref",
                        "observation_digest",
                    )
                },
                body_json=_pack(stored),
            )
        )
        self.session.add(
            M9EventModel(
                user_id=self.user_id,
                project_name=self.project_name,
                event_kind="MANUAL_OBSERVATION_STORED",
                aggregate_id=observation.observation_id,
                aggregate_revision=observation.revision,
                payload_digest=_record_digest(stored),
                committed_at=now,
            )
        )
        await _flush(self.session)
        if head is None:
            self.session.add(
                M9ObservationHeadModel(
                    user_id=self.user_id,
                    project_name=self.project_name,
                    observation_id=observation.observation_id,
                    current_revision=1,
                    head_version=1,
                )
            )
        else:
            head.current_revision = head.head_version = observation.revision
        await _flush(self.session)

    @staticmethod
    def _admission_refs(envelope: AdmissionEnvelope) -> tuple[str, ...]:
        refs = tuple(r for o in envelope.objects for r in (o.payload_ref, o.integrity_ref, o.attestation_ref))
        if envelope.request.publication_key in refs:
            raise OpportunityError(_MISSING)
        return tuple(sorted((envelope.request.publication_key, *refs)))

    async def _object_guards(self, refs: Sequence[str]) -> None:
        for ref in sorted(set(refs)):
            digest = digest_canonical(
                {
                    "domain": "m9.manual-object-lock.v1",
                    "user_id": self.user_id,
                    "project_name": self.project_name,
                    "ref": ref,
                }
            )
            first, second = struct.unpack(">ii", bytes.fromhex(digest.removeprefix("sha256:"))[:8])
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(:first,:second)"), {"first": first, "second": second}
            )

    async def _reject_fenced_refs(self, refs: set[str]) -> None:
        await self._reject_recovery_fenced_refs(refs)
        rows = (
            await self.session.scalars(
                select(M9ManualClosureIntentModel)
                .where(
                    M9ManualClosureIntentModel.user_id == self.user_id,
                    M9ManualClosureIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        markers = (
            await self.session.scalars(
                select(M9EventModel).where(
                    M9EventModel.user_id == self.user_id,
                    M9EventModel.project_name == self.project_name,
                    M9EventModel.event_kind == "MANUAL_ADMISSION_FENCED",
                )
            )
        ).all()
        expected = {}
        blocked = False
        for row in rows:
            if self._is_recovery_closure(row):
                await self._recovery_closure_value(row)
                continue
            stored = await self._closure_value(row)
            blocked |= bool(refs.intersection(stored.intent.object_refs))
            for member in stored.members:
                key = member.record.attempt.attempt_id
                if key in expected:
                    raise OpportunityError(_MISSING)
                expected[key] = (
                    member.admission.version + 1,
                    self._fence_digest(stored, member),
                    stored.fence.fenced_at,
                )
        seen = set()
        for marker in markers:
            if marker.aggregate_id in seen or expected.get(marker.aggregate_id) != (
                marker.aggregate_revision,
                marker.payload_digest,
                marker.committed_at,
            ):
                raise OpportunityError(_MISSING)
            seen.add(marker.aggregate_id)
        if seen != set(expected):
            raise OpportunityError(_MISSING)
        if blocked:
            raise OpportunityError(_CONFLICT)

    @staticmethod
    def _is_recovery_closure(row: M9ManualClosureIntentModel) -> bool:
        try:
            schema = row.body_json["metadata"]["schema_version"]
        except (TypeError, KeyError):
            raise OpportunityError(_MISSING) from None
        if schema not in ("m9.manual-closure.v1", "m9.manual-recovery-closure.v1"):
            raise OpportunityError(_MISSING)
        return schema == "m9.manual-recovery-closure.v1"

    async def _recovery_closure_value(self, row: M9ManualClosureIntentModel) -> _RecoveryClosureRecord:
        stored = _unpack(_RecoveryClosureRecord, row.body_json, digest=row.metadata_digest)
        intent = stored.intent
        if (intent.user_id, intent.project_name) != (self.user_id, self.project_name) or any(
            getattr(row, key) != getattr(intent, key)
            for key in (
                "user_id",
                "project_name",
                "closure_id",
                "attempt_id",
                "attempt_version",
                "envelope_version",
                "phase",
                "version",
                "fenced_at",
            )
        ):
            raise OpportunityError(_MISSING)
        await self._require_event(
            aggregate_id=intent.closure_id,
            version=intent.version,
            kind="MANUAL_RECOVERY_CLOSURE_STATE",
            digest=_record_digest(stored),
            at=stored.finished_at or stored.authorized_at or stored.reads_drained_at or intent.fenced_at,
        )
        return stored

    async def _store_recovery_closure(
        self, stored: _RecoveryClosureRecord, row: M9ManualClosureIntentModel | None = None
    ) -> None:
        values = {
            key: getattr(stored.intent, key)
            for key in (
                "user_id",
                "project_name",
                "closure_id",
                "attempt_id",
                "attempt_version",
                "envelope_version",
                "phase",
                "version",
                "fenced_at",
            )
        }
        values.update(body_json=_pack(stored), metadata_digest=_record_digest(stored))
        if row is None:
            self.session.add(M9ManualClosureIntentModel(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self._add_event(
            aggregate_id=stored.intent.closure_id,
            version=stored.intent.version,
            kind="MANUAL_RECOVERY_CLOSURE_STATE",
            digest=_record_digest(stored),
            at=stored.finished_at or stored.authorized_at or stored.reads_drained_at or stored.fence.fenced_at,
        )
        await _flush(self.session)

    @staticmethod
    def _recovery_fence_digest(stored: _RecoveryClosureRecord, member: _RecoveryClosureMember) -> str:
        return digest_canonical({"domain": "m9.manual-recovery-fence.v1", "fence": stored.fence, "member": member})

    async def _verified_recovery_fences(self) -> dict[str, tuple[_RecoveryClosureRecord, _RecoveryClosureMember]]:
        rows = (
            await self.session.scalars(
                select(M9ManualClosureIntentModel)
                .where(
                    M9ManualClosureIntentModel.user_id == self.user_id,
                    M9ManualClosureIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        expected = {}
        for row in rows:
            if not self._is_recovery_closure(row):
                await self._closure_value(row)
                continue
            stored = await self._recovery_closure_value(row)
            for member in stored.members:
                attempt_id = member.record.attempt.attempt_id
                if attempt_id in expected:
                    raise OpportunityError(_MISSING)
                expected[attempt_id] = (stored, member)
        markers = (
            await self.session.scalars(
                select(M9EventModel).where(
                    M9EventModel.user_id == self.user_id,
                    M9EventModel.project_name == self.project_name,
                    M9EventModel.event_kind == "MANUAL_RECOVERY_ADMISSION_FENCED",
                )
            )
        ).all()
        seen = set()
        for marker in markers:
            value = expected.get(marker.aggregate_id)
            if value is None or marker.aggregate_id in seen:
                raise OpportunityError(_MISSING)
            stored, member = value
            if (marker.aggregate_revision, marker.payload_digest, marker.committed_at) != (
                _recovery_envelope(member, erased=False).version,
                self._recovery_fence_digest(stored, member),
                stored.fence.fenced_at,
            ):
                raise OpportunityError(_MISSING)
            seen.add(marker.aggregate_id)
        if seen != set(expected):
            raise OpportunityError(_MISSING)
        return expected

    async def _recovery_lease_rows(
        self, attempt_id: str
    ) -> tuple[tuple[M9ManualUploadLeaseModel, _UploadLeaseRecord], ...]:
        rows = (
            await self.session.scalars(
                select(M9ManualUploadLeaseModel)
                .where(
                    M9ManualUploadLeaseModel.user_id == self.user_id,
                    M9ManualUploadLeaseModel.project_name == self.project_name,
                    M9ManualUploadLeaseModel.attempt_id == attempt_id,
                )
                .order_by(M9ManualUploadLeaseModel.claim_ref)
                .execution_options(populate_existing=True)
            )
        ).all()
        return tuple((row, _upload_lease(row)) for row in rows)

    async def _recovery_witness(
        self, envelope: AdmissionEnvelope, row: M9ManualAdmissionModel
    ) -> _RecoveryClosureRecord | None:
        value = (await self._verified_recovery_fences()).get(row.attempt_id)
        if value is None:
            return None
        stored, member = value
        old_marker = await self.session.scalar(
            select(M9EventModel.event_id)
            .where(
                M9EventModel.user_id == self.user_id,
                M9EventModel.project_name == self.project_name,
                M9EventModel.aggregate_id == row.attempt_id,
                M9EventModel.event_kind == "MANUAL_ADMISSION_FENCED",
            )
            .limit(1)
        )
        erased = stored.intent.phase == "ERASED"
        if (
            old_marker is not None
            or envelope != _recovery_envelope(member, erased=erased)
            or (row.erasure_fenced_at, row.erasure_version) != (stored.fence.fenced_at, 1)
        ):
            raise OpportunityError(_MISSING)
        leases = await self._recovery_lease_rows(row.attempt_id)
        expected = tuple(
            lease.model_copy(
                update={
                    "state": "SPENT" if erased else "CLOSING",
                    "version": 3 if erased else 2,
                    "closure_id": stored.fence.closure_id,
                }
            )
            for lease in member.leases
        )
        if tuple(lease for _, lease in leases) != expected:
            raise OpportunityError(_MISSING)
        return stored

    async def _reject_recovery_fenced_refs(self, refs: set[str]) -> None:
        for stored, _ in (await self._verified_recovery_fences()).values():
            if refs.intersection(stored.intent.object_refs):
                raise OpportunityError(_CONFLICT)

    async def get_cleanup_state(self, attempt_id: str) -> ManualCleanupState | None:
        rows = (
            await self.session.scalars(
                select(M9ManualClosureIntentModel)
                .where(
                    M9ManualClosureIntentModel.user_id == self.user_id,
                    M9ManualClosureIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        found = None
        for row in rows:
            if self._is_recovery_closure(row):
                stored = await self._recovery_closure_value(row)
                if any(member.record.attempt.attempt_id == attempt_id for member in stored.members):
                    if found is not None:
                        raise OpportunityError(_MISSING)
                    found = row.closure_id
            else:
                old = await self._closure_value(row)
                if any(member.record.attempt.attempt_id == attempt_id for member in old.members):
                    raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
        await self._verified_recovery_fences()
        if found is None:
            return None
        _, current = await self._locked_recovery_closure(found, mutation=False)
        return current.state()

    async def plan_recovery_closure(self, attempt_id: str) -> ManualRecoveryClosurePlan:
        current = await self._closure_members(attempt_id, cleanup_only=True)
        members = []
        for member in current:
            leases = await self._recovery_lease_rows(member.record.attempt.attempt_id)
            members.append(
                _RecoveryClosureMember(
                    record=member.record,
                    admission=member.admission,
                    admission_present=await self.session.get(
                        M9ManualAdmissionModel,
                        (self.user_id, self.project_name, member.record.attempt.attempt_id),
                        populate_existing=True,
                    )
                    is not None,
                    intent_present=await self.session.get(
                        M9ManualPublicationIntentModel,
                        (self.user_id, self.project_name, member.admission.request.publication_key),
                        populate_existing=True,
                    )
                    is not None,
                    leases=tuple(lease for _, lease in leases),
                )
            )
        transaction = self.session.sync_session.get_transaction()
        if transaction is None:
            raise OpportunityError(_MISSING)
        return ManualRecoveryClosurePlan(attempt_id, tuple(members), transaction)

    async def begin_recovery_closure(self, attempt_id: str, *, dependency_plan: object) -> ManualCleanupState:
        existing = await self.get_cleanup_state(attempt_id)
        if existing is not None:
            return existing
        if not isinstance(dependency_plan, ManualRecoveryClosurePlan) or dependency_plan.attempt_id != attempt_id:
            raise OpportunityError(_MISSING)
        planning = dependency_plan.planning_transaction
        if (
            not isinstance(planning, SessionTransaction)
            or planning.is_active
            or planning is self.session.sync_session.get_transaction()
        ):
            raise OpportunityError(_STALE)
        records = {member.record.attempt.attempt_id: member.record for member in dependency_plan.members}
        await self._guard_dependencies(records, operational_attempt_id=None, cleanup_only=True)
        existing = await self.get_cleanup_state(attempt_id)
        if existing is not None:
            return existing
        current_plan = await self.plan_recovery_closure(attempt_id)
        if current_plan.members != dependency_plan.members:
            raise OpportunityError(_STALE)
        members = current_plan.members
        root = next(member for member in members if member.record.attempt.attempt_id == attempt_id)
        now = await self.profiles.database_time()
        for member in members:
            if member is root:
                continue
            deadline = (
                member.admission.deadlines.retention_due_at
                if member.admission is not None and member.admission.deadlines is not None
                else None
            )
            if deadline is None:
                clocks = _recovery_request(member).original_clocks
                bounds = [clock.retention_due_at for clock in clocks if clock.retention_due_at is not None]
                deadline = min(bounds) if bounds else None
            if deadline is None or now < deadline:
                raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
        reads = await self._closure_reads(members, lock=True)
        intent = AdmissionClosureIntent(
            closure_id=uuid7(),
            user_id=self.user_id,
            project_name=self.project_name,
            attempt_id=attempt_id,
            attempt_version=root.record.attempt.attempt_version,
            envelope_version=_recovery_envelope(root, erased=False).version,
            phase="CLEANUP_PENDING",
            version=1,
            object_refs=_recovery_refs(members, None),
            fenced_at=now,
        )
        stored = _RecoveryClosureRecord(fence=intent, intent=intent, members=members, reads=reads)
        for member in members:
            if member.admission is None:
                raise OpportunityError(_MISSING)
            await self._phase_member(
                _ClosureMember(record=member.record, admission=member.admission),
                phase=AdmissionPhase.CLEANUP_PENDING,
                closure_id=intent.closure_id,
                now=now,
                missing_admission=not member.admission_present,
                missing_intent=not member.intent_present,
            )
            self._add_event(
                aggregate_id=member.record.attempt.attempt_id,
                version=_recovery_envelope(member, erased=False).version,
                kind="MANUAL_RECOVERY_ADMISSION_FENCED",
                digest=self._recovery_fence_digest(stored, member),
                at=now,
            )
        await self._store_recovery_closure(stored)
        return stored.state()

    async def _locked_recovery_closure(
        self, closure_id: str, *, mutation: bool, additional_refs: Sequence[str] = ()
    ) -> tuple[M9ManualClosureIntentModel, _RecoveryClosureRecord]:
        row = await self._closure_row(closure_id)
        if row is None or not self._is_recovery_closure(row):
            raise OpportunityError(_MISSING)
        initial = await self._recovery_closure_value(row)
        refs = tuple(sorted(set(initial.intent.object_refs).union(additional_refs)))
        records = await self._closure_records_after_fence(initial.members, initial.fence.fenced_at)
        await self.lock_commands(tuple(record.command.context for record in records.values()))
        if mutation:
            await self._guard_dependencies(records, operational_attempt_id=None, additional_object_refs=refs)
        row = await self._closure_row(closure_id, lock=mutation)
        if row is None:
            raise OpportunityError(_MISSING)
        stored = await self._recovery_closure_value(row)
        if (
            stored.fence != initial.fence
            or stored.members != initial.members
            or stored.reads != initial.reads
            or stored.intent.version < initial.intent.version
        ):
            raise OpportunityError(_STALE)
        current = await self._closure_members(stored.fence.attempt_id, additional_refs=refs)
        if tuple(member.record.attempt.attempt_id for member in current) != tuple(records):
            raise OpportunityError(_STALE)
        return row, stored

    async def _recovery_drained_reads(self, stored: _RecoveryClosureRecord, *, now: datetime) -> None:
        reads = await self._closure_reads(stored.members, lock=True)
        if len(reads) != len(stored.reads) or any(
            (current.permit, current.attempt_version) != (original.permit, original.attempt_version)
            for current, original in zip(reads, stored.reads, strict=True)
        ):
            raise OpportunityError(_MISSING)
        if any(read.released_at is None and now < read.permit.expires_at for read in reads):
            raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)

    async def drain_recovery_closure(self, closure_id: str, *, expected_closure_version: int) -> ManualCleanupState:
        row, stored = await self._locked_recovery_closure(closure_id, mutation=True)
        if stored.intent.version >= 2:
            return stored.state()
        if stored.intent.version != expected_closure_version:
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
        await self._recovery_drained_reads(stored, now=now)
        updated = _RecoveryClosureRecord.model_validate(
            {**stored.model_dump(), "intent": stored.intent.model_copy(update={"version": 2}), "reads_drained_at": now}
        )
        await self._store_recovery_closure(updated, row)
        return updated.state()

    async def authorize_recovery_deletion(
        self, closure_id: str, *, proof: CustodianSpendReceipt, public_key: bytes, expected_closure_version: int
    ) -> ManualCleanupState:
        proof = CustodianSpendReceipt.model_validate(proof.model_dump())
        discovered = {
            ref
            for publication in proof.metadata.publications
            if publication.header is not None
            for obj in publication.header.metadata.objects
            for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)
        } | {publication.request.publication_key for publication in proof.metadata.publications}
        row, stored = await self._locked_recovery_closure(
            closure_id, mutation=True, additional_refs=tuple(sorted(discovered))
        )
        root = next(member for member in stored.members if member.record.attempt.attempt_id == stored.fence.attempt_id)
        verify_custodian_spent(
            canonical_json_bytes(proof),
            public_key=public_key,
            expected_request=_recovery_request(root),
            closure_id=closure_id,
        )
        if stored.proof is not None:
            if stored.proof != proof or stored.public_key != public_key.hex():
                raise OpportunityError(_CONFLICT)
            return stored.state()
        now = await self.profiles.database_time()
        if (
            stored.intent.version != expected_closure_version
            or stored.intent.version != 2
            or proof.metadata.deleted_at > now
        ):
            raise OpportunityError(_STALE)
        await self._recovery_drained_reads(stored, now=now)
        updated = _RecoveryClosureRecord.model_validate(
            {
                **stored.model_dump(),
                "proof": proof,
                "public_key": public_key.hex(),
                "authorized_at": now,
                "intent": stored.intent.model_copy(
                    update={"version": 3, "object_refs": _recovery_refs(stored.members, proof)}
                ),
            }
        )
        await self._store_recovery_closure(updated, row)
        return updated.state()

    async def finish_recovery_closure(
        self, receipt: AdmissionDeletionReceipt, *, expected_closure_version: int
    ) -> ManualCleanupState:
        row, stored = await self._locked_recovery_closure(receipt.closure.closure_id, mutation=True)
        receipt = AdmissionDeletionReceipt.model_validate(receipt.model_dump())
        if stored.receipt is not None:
            if stored.receipt != receipt:
                raise OpportunityError(_CONFLICT)
            return stored.state()
        now = await self.profiles.database_time()
        if (
            stored.intent.version != expected_closure_version
            or stored.intent.version != 3
            or receipt.closure != stored.intent
            or receipt.deleted_at > now
        ):
            raise OpportunityError(_STALE)
        await self._recovery_drained_reads(stored, now=now)
        for member in stored.members:
            if member.admission is None:
                raise OpportunityError(_MISSING)
            await self._phase_member(
                _ClosureMember(record=member.record, admission=member.admission),
                phase=AdmissionPhase.ERASED,
                closure_id=stored.fence.closure_id,
                now=now,
            )
        updated = _RecoveryClosureRecord.model_validate(
            {
                **stored.model_dump(),
                "receipt": receipt,
                "finished_at": now,
                "intent": stored.intent.model_copy(update={"version": 4, "phase": "ERASED"}),
            }
        )
        await self._store_recovery_closure(updated, row)
        return updated.state()

    async def _closure_members(
        self, attempt_id: str, *, cleanup_only: bool = False, additional_refs: Sequence[str] = ()
    ) -> tuple[_ClosureMember, ...]:
        rows = (
            await self.session.scalars(
                select(M9ManualPublicationIntentModel)
                .where(
                    M9ManualPublicationIntentModel.user_id == self.user_id,
                    M9ManualPublicationIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        envelopes = {}
        for row in rows:
            try:
                envelope = AdmissionEnvelope.model_validate(row.body_json)
            except ValueError:
                raise OpportunityError(_MISSING) from None
            if (row.attempt_id, row.publication_key, row.phase, row.version, row.metadata_digest) != (
                envelope.request.attempt_id,
                envelope.request.publication_key,
                envelope.phase,
                envelope.version,
                envelope.metadata_digest,
            ) or (envelope.request.context.user_id, envelope.request.context.project_name) != (
                self.user_id,
                self.project_name,
            ):
                raise OpportunityError(_MISSING)
            envelopes[row.attempt_id] = envelope
        if cleanup_only:
            attempts = (
                await self.session.scalars(
                    select(M9AcquisitionAttemptModel)
                    .where(
                        M9AcquisitionAttemptModel.user_id == self.user_id,
                        M9AcquisitionAttemptModel.project_name == self.project_name,
                        M9AcquisitionAttemptModel.protocol_version == "m9.acquisition.v2",
                    )
                    .execution_options(populate_existing=True)
                )
            ).all()
            for attempt_row in attempts:
                record = await self._record(attempt_row, cleanup_only=True)
                if record.request is not None:
                    envelope = await self._cleanup_envelope(record)
                    if envelope is None:
                        raise OpportunityError(_MISSING)
                    envelopes[attempt_row.attempt_id] = envelope
        if attempt_id not in envelopes:
            raise OpportunityError(_MISSING)
        selected = {attempt_id}
        while True:
            refs = set(additional_refs) | {r for key in selected for r in self._admission_refs(envelopes[key])}
            uploads = {self._original_upload_identity(envelopes[key].request) for key in selected}
            claims = {
                (envelopes[key].claim_ref, envelopes[key].request.upload_version)
                for key in selected
                if envelopes[key].claim_ref is not None
            }
            expanded = selected | {
                key
                for key, value in envelopes.items()
                if (
                    refs.intersection(self._admission_refs(value))
                    or (value.claim_ref is not None and (value.claim_ref, value.request.upload_version) in claims)
                    or self._original_upload_identity(value.request) in uploads
                )
            }
            if expanded == selected:
                break
            selected = expanded
        members = []
        for key in sorted(selected):
            row = await self._row(key)
            if row is None:
                raise OpportunityError(_MISSING)
            record = await self._record(row, cleanup_only=cleanup_only)
            envelope = await self._cleanup_envelope(record) if cleanup_only else await self._envelope(record)
            if envelope is None or envelope != envelopes[key]:
                raise OpportunityError(_STALE)
            members.append(_ClosureMember(record=record, admission=envelope))
        return tuple(members)

    async def plan_closure(self, attempt_id: str) -> ManualClosurePlan:
        members = await self._closure_members(attempt_id)
        transaction = self.session.sync_session.get_transaction()
        if transaction is None:
            raise OpportunityError(_MISSING)
        return ManualClosurePlan(attempt_id, members, transaction)

    async def _closure_row(self, closure_id: str, *, lock: bool = False) -> M9ManualClosureIntentModel | None:
        statement = (
            select(M9ManualClosureIntentModel)
            .where(
                M9ManualClosureIntentModel.user_id == self.user_id,
                M9ManualClosureIntentModel.project_name == self.project_name,
                M9ManualClosureIntentModel.closure_id == closure_id,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        return (await self.session.scalars(statement)).one_or_none()

    async def _require_event(self, *, aggregate_id: str, version: int, kind: str, digest: str, at: datetime) -> None:
        events = (
            await self.session.scalars(
                select(M9EventModel).where(
                    M9EventModel.user_id == self.user_id,
                    M9EventModel.project_name == self.project_name,
                    M9EventModel.aggregate_id == aggregate_id,
                    M9EventModel.aggregate_revision == version,
                    M9EventModel.event_kind == kind,
                )
            )
        ).all()
        if len(events) != 1 or (events[0].payload_digest, events[0].committed_at) != (digest, at):
            raise OpportunityError(_MISSING)

    def _add_event(self, *, aggregate_id: str, version: int, kind: str, digest: str, at: datetime) -> None:
        self.session.add(
            M9EventModel(
                user_id=self.user_id,
                project_name=self.project_name,
                aggregate_id=aggregate_id,
                aggregate_revision=version,
                event_kind=kind,
                payload_digest=digest,
                committed_at=at,
            )
        )

    async def _closure_value(self, row: M9ManualClosureIntentModel) -> _ClosureRecord:
        stored = _unpack(_ClosureRecord, row.body_json, digest=row.metadata_digest)
        intent = stored.intent
        if any(
            getattr(row, key) != getattr(intent, key)
            for key in (
                "user_id",
                "project_name",
                "closure_id",
                "attempt_id",
                "attempt_version",
                "envelope_version",
                "phase",
                "version",
                "fenced_at",
            )
        ) or (intent.user_id, intent.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(_MISSING)
        keys = tuple(m.record.attempt.attempt_id for m in stored.members)
        root = next((m for m in stored.members if m.record.attempt.attempt_id == intent.attempt_id), None)
        refs = tuple(sorted({r for m in stored.members for r in self._admission_refs(m.admission)}))
        if (
            not keys
            or keys != tuple(sorted(set(keys)))
            or root is None
            or intent.attempt_version != root.record.attempt.attempt_version
            or intent.envelope_version != root.admission.version + 1
            or intent.object_refs != refs
            or any(m.admission.phase != AdmissionPhase.READY for m in stored.members)
        ):
            raise OpportunityError(_MISSING)
        at = stored.finished_at or stored.authorized_at or intent.fenced_at
        await self._require_event(
            aggregate_id=intent.closure_id,
            version=intent.version,
            kind="MANUAL_CLOSURE_STATE",
            digest=_record_digest(stored),
            at=at,
        )
        return stored

    def _fence_digest(self, stored: _ClosureRecord, member: _ClosureMember) -> str:
        return digest_canonical({"domain": "m9.manual-fence.v1", "fence": stored.fence, "member": member})

    async def _closure_witness(self, envelope: AdmissionEnvelope, row: M9ManualAdmissionModel) -> _ClosureRecord | None:
        markers = (
            await self.session.scalars(
                select(M9EventModel).where(
                    M9EventModel.user_id == self.user_id,
                    M9EventModel.project_name == self.project_name,
                    M9EventModel.aggregate_id == row.attempt_id,
                    M9EventModel.event_kind == "MANUAL_ADMISSION_FENCED",
                )
            )
        ).all()
        if not markers:
            if row.erasure_fenced_at is not None or envelope.phase in (
                AdmissionPhase.CLEANUP_PENDING,
                AdmissionPhase.ERASED,
            ):
                raise OpportunityError(_MISSING)
            return None
        if len(markers) != 1:
            raise OpportunityError(_MISSING)
        closures = (
            await self.session.scalars(
                select(M9ManualClosureIntentModel)
                .where(
                    M9ManualClosureIntentModel.user_id == self.user_id,
                    M9ManualClosureIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        matches = []
        for closure_row in closures:
            if self._is_recovery_closure(closure_row):
                await self._recovery_closure_value(closure_row)
                continue
            stored = await self._closure_value(closure_row)
            for member in stored.members:
                if member.record.attempt.attempt_id != row.attempt_id:
                    continue
                marker = markers[0]
                erased = stored.intent.phase == "ERASED"
                if (
                    (marker.aggregate_revision, marker.payload_digest, marker.committed_at)
                    != (member.admission.version + 1, self._fence_digest(stored, member), stored.fence.fenced_at)
                    or (row.erasure_fenced_at, row.erasure_version) != (stored.fence.fenced_at, 1)
                    or (envelope.phase, envelope.version)
                    != (
                        AdmissionPhase.ERASED if erased else AdmissionPhase.CLEANUP_PENDING,
                        member.admission.version + (2 if erased else 1),
                    )
                    or envelope.model_dump(exclude={"phase", "version", "metadata_digest"})
                    != member.admission.model_dump(exclude={"phase", "version", "metadata_digest"})
                ):
                    raise OpportunityError(_MISSING)
                matches.append(stored)
        if len(matches) != 1:
            raise OpportunityError(_MISSING)
        return matches[0]

    async def _store_closure(self, stored: _ClosureRecord, row: M9ManualClosureIntentModel | None = None) -> None:
        values = {
            key: getattr(stored.intent, key)
            for key in (
                "user_id",
                "project_name",
                "closure_id",
                "attempt_id",
                "attempt_version",
                "envelope_version",
                "phase",
                "version",
                "fenced_at",
            )
        }
        values.update(body_json=_pack(stored), metadata_digest=_record_digest(stored))
        if row is None:
            self.session.add(M9ManualClosureIntentModel(**values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self._add_event(
            aggregate_id=stored.intent.closure_id,
            version=stored.intent.version,
            kind="MANUAL_CLOSURE_STATE",
            digest=_record_digest(stored),
            at=stored.finished_at or stored.authorized_at or stored.intent.fenced_at,
        )
        await _flush(self.session)

    async def _verified_read(self, row: M9ManualReadLeaseModel) -> _ReadLeaseRecord:
        lease = _read_lease(row)
        issued = lease.model_copy(update={"released_at": None})
        await self._require_event(
            aggregate_id=lease.permit.lease_id,
            version=1,
            kind="MANUAL_READ_ISSUED",
            digest=_record_digest(issued),
            at=lease.permit.issued_at,
        )
        if lease.released_at is not None:
            await self._require_event(
                aggregate_id=lease.permit.lease_id,
                version=2,
                kind="MANUAL_READ_RELEASED",
                digest=_record_digest(lease),
                at=lease.released_at,
            )
        return lease

    async def _closure_reads(
        self, members: Sequence[_ClosureMember | _RecoveryClosureMember], *, lock: bool
    ) -> tuple[_ReadLeaseRecord, ...]:
        orphan = await self.session.scalar(
            select(M9EventModel.event_id)
            .outerjoin(
                M9ManualReadLeaseModel,
                (
                    (M9ManualReadLeaseModel.user_id == M9EventModel.user_id)
                    & (M9ManualReadLeaseModel.project_name == M9EventModel.project_name)
                    & (M9ManualReadLeaseModel.lease_id == M9EventModel.aggregate_id)
                ),
            )
            .where(
                M9EventModel.user_id == self.user_id,
                M9EventModel.project_name == self.project_name,
                M9EventModel.event_kind == "MANUAL_READ_ISSUED",
                M9ManualReadLeaseModel.lease_id.is_(None),
            )
            .limit(1)
        )
        if orphan is not None:
            raise OpportunityError(_MISSING)
        statement = (
            select(M9ManualReadLeaseModel)
            .where(
                M9ManualReadLeaseModel.user_id == self.user_id,
                M9ManualReadLeaseModel.project_name == self.project_name,
                M9ManualReadLeaseModel.attempt_id.in_([m.record.attempt.attempt_id for m in members]),
            )
            .order_by(M9ManualReadLeaseModel.lease_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        rows = (await self.session.scalars(statement)).all()
        return tuple([await self._verified_read(row) for row in rows])

    async def begin_closure(
        self, attempt_id: str, *, expected_envelope_version: int, dependency_plan: ManualClosurePlan | None = None
    ) -> AdmissionClosureIntent:
        existing = (
            await self.session.scalars(
                select(M9ManualClosureIntentModel)
                .where(
                    M9ManualClosureIntentModel.user_id == self.user_id,
                    M9ManualClosureIntentModel.project_name == self.project_name,
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        for row in existing:
            if self._is_recovery_closure(row):
                recovery = await self._recovery_closure_value(row)
                if any(member.record.attempt.attempt_id == attempt_id for member in recovery.members):
                    raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
                continue
            stored = await self._closure_value(row)
            if any(m.record.attempt.attempt_id == attempt_id for m in stored.members):
                return await self.get_closure(stored.intent.closure_id)
        if not isinstance(dependency_plan, ManualClosurePlan) or dependency_plan.attempt_id != attempt_id:
            raise OpportunityError(_MISSING)
        planning = dependency_plan.planning_transaction
        if (
            not isinstance(planning, SessionTransaction)
            or planning.is_active
            or planning.session.get_transaction() is planning
            or planning is self.session.sync_session.get_transaction()
        ):
            raise OpportunityError(_STALE)
        records = {m.record.attempt.attempt_id: m.record for m in dependency_plan.members}
        await self._guard_dependencies(records, operational_attempt_id=None)
        current = await self._closure_members(attempt_id)
        if current != dependency_plan.members:
            raise OpportunityError(_STALE)
        root = next(m for m in current if m.record.attempt.attempt_id == attempt_id)
        if root.admission.version != expected_envelope_version:
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
        for member in current:
            if member.admission.phase != AdmissionPhase.READY:
                raise OpportunityError(_MISSING)
            if member is not root:
                deadline = None if member.admission.deadlines is None else member.admission.deadlines.retention_due_at
                if deadline is None or now < deadline:
                    raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
        reads = await self._closure_reads(current, lock=True)
        intent = AdmissionClosureIntent(
            closure_id=uuid7(),
            user_id=self.user_id,
            project_name=self.project_name,
            attempt_id=attempt_id,
            attempt_version=root.record.attempt.attempt_version,
            envelope_version=expected_envelope_version + 1,
            phase="CLEANUP_PENDING",
            version=1,
            object_refs=tuple(sorted({r for m in current for r in self._admission_refs(m.admission)})),
            fenced_at=now,
        )
        stored = _ClosureRecord(fence=intent, intent=intent, members=current, reads=reads)
        for member in current:
            await self._phase_member(
                member, phase=AdmissionPhase.CLEANUP_PENDING, closure_id=intent.closure_id, now=now
            )
            self._add_event(
                aggregate_id=member.record.attempt.attempt_id,
                version=member.admission.version + 1,
                kind="MANUAL_ADMISSION_FENCED",
                digest=self._fence_digest(stored, member),
                at=now,
            )
        await self._store_closure(stored)
        return intent

    async def _phase_member(
        self,
        member: _ClosureMember,
        *,
        phase: AdmissionPhase,
        closure_id: str,
        now: datetime,
        missing_admission: bool = False,
        missing_intent: bool = False,
    ) -> None:
        original = member.admission
        pending = phase == AdmissionPhase.CLEANUP_PENDING
        version = original.version + (1 if pending else 2)
        body = {**original.model_dump(), "phase": phase, "version": version}
        envelope = AdmissionEnvelope.model_validate({**body, "metadata_digest": admission_metadata_digest(body)})
        if original.claim_ref is not None:
            row = await self.session.get(
                M9ManualUploadLeaseModel,
                (
                    self.user_id,
                    self.project_name,
                    original.claim_ref,
                    original.request.upload_version,
                    original.request.attempt_id,
                ),
                populate_existing=True,
            )
            if row is None:
                raise OpportunityError(_MISSING)
            lease = _upload_lease(row)
            if (lease.state, lease.version, lease.closure_id) != (
                ("ACTIVE", 1, None) if pending else ("CLOSING", 2, closure_id)
            ):
                raise OpportunityError(_STALE)
            updated = lease.model_copy(
                update={
                    "state": "CLOSING" if pending else "SPENT",
                    "version": 2 if pending else 3,
                    "closure_id": closure_id,
                }
            )
            row.state, row.version, row.closure_id = updated.state, updated.version, closure_id
            row.body_json, row.metadata_digest = _pack(updated), _record_digest(updated)
        if pending:
            await self.session.execute(
                update(M9ManualAdmissionModel)
                .where(
                    M9ManualAdmissionModel.user_id == self.user_id,
                    M9ManualAdmissionModel.project_name == self.project_name,
                    M9ManualAdmissionModel.attempt_id == original.request.attempt_id,
                )
                .values(erasure_fenced_at=now, erasure_version=1)
            )
        await self._save_envelope(
            envelope,
            expected_version=original.version if pending else original.version + 1,
            missing_admission=missing_admission,
            missing_intent=missing_intent,
            fenced_at=now if pending else None,
        )

    async def _closure_records_after_fence(
        self, members: Sequence[_ClosureMember | _RecoveryClosureMember], fenced_at: datetime
    ) -> dict[str, _AttemptRecord]:
        records = {}
        for member in members:
            attempt_row = await self._row(member.record.attempt.attempt_id)
            if attempt_row is None:
                raise OpportunityError(_MISSING)
            current = await self._record(attempt_row)
            original = member.record
            history = tuple(sorted(current.transitions, key=lambda e: e.to_version))
            original_history = tuple(sorted(original.transitions, key=lambda e: e.to_version))
            added = history[len(original_history) :]
            if (
                current.command != original.command
                or current.descriptor != original.descriptor
                or current.request != original.request
                or current.attempt.attempt_version < original.attempt.attempt_version
                or history[: len(original_history)] != original_history
                or any(
                    getattr(current.attempt, key) != getattr(original.attempt, key)
                    for key in (
                        "user_id",
                        "project_name",
                        "actor_id",
                        "command_id",
                        "request_digest",
                        "query_id",
                        "query_revision",
                        "query_digest",
                        "adapter_version",
                        "started_at",
                        "provider_request_id",
                        "quota_disposition",
                        "quota_units_observed",
                        "page_cursor_digest",
                    )
                )
                or (
                    current.attempt.attempt_version == original.attempt.attempt_version
                    and current.attempt != original.attempt
                )
                or (
                    current.attempt.attempt_version > original.attempt.attempt_version
                    and (
                        not added
                        or (added[0].from_version, added[0].from_state)
                        != (original.attempt.attempt_version, original.attempt.state)
                        or added[0].at < fenced_at
                    )
                )
            ):
                raise OpportunityError(_MISSING)
            records[current.attempt.attempt_id] = current
        return records

    async def _locked_closure(
        self, closure_id: str, *, mutation: bool
    ) -> tuple[M9ManualClosureIntentModel, _ClosureRecord]:
        row = await self._closure_row(closure_id)
        if row is None or self._is_recovery_closure(row):
            raise OpportunityError(_MISSING)
        initial = await self._closure_value(row)
        records = await self._closure_records_after_fence(initial.members, initial.fence.fenced_at)
        await self.lock_commands(tuple(r.command.context for r in records.values()))
        if mutation:
            await self._guard_dependencies(records, operational_attempt_id=None)
        row = await self._closure_row(closure_id, lock=mutation)
        if row is None:
            raise OpportunityError(_MISSING)
        stored = await self._closure_value(row)
        if (
            stored.fence != initial.fence
            or stored.members != initial.members
            or stored.reads != initial.reads
            or stored.intent.version < initial.intent.version
        ):
            raise OpportunityError(_STALE)
        current_members = await self._closure_members(stored.intent.attempt_id)
        if tuple(m.record.attempt.attempt_id for m in current_members) != tuple(records):
            raise OpportunityError(_STALE)
        for member in current_members:
            await self._envelope(member.record)
        return row, stored

    async def get_closure(self, closure_id: str) -> AdmissionClosureIntent:
        row = await self._closure_row(closure_id)
        if row is not None and self._is_recovery_closure(row):
            _, recovery = await self._locked_recovery_closure(closure_id, mutation=False)
            return recovery.intent
        _, stored = await self._locked_closure(closure_id, mutation=False)
        return stored.intent

    async def authorize_deletion(self, closure_id: str, *, expected_closure_version: int) -> AdmissionClosureIntent:
        row, stored = await self._locked_closure(closure_id, mutation=True)
        if stored.authorized_at is not None:
            return stored.intent
        if stored.intent.version != expected_closure_version:
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
        reads = await self._closure_reads(stored.members, lock=True)
        if len(reads) != len(stored.reads) or any(
            (a.permit, a.attempt_version) != (b.permit, b.attempt_version)
            for a, b in zip(reads, stored.reads, strict=True)
        ):
            raise OpportunityError(_MISSING)
        if any(r.released_at is None and now < r.permit.expires_at for r in reads):
            raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
        updated = stored.model_copy(
            update={"intent": stored.intent.model_copy(update={"version": 2}), "authorized_at": now}
        )
        await self._store_closure(updated, row)
        return updated.intent

    async def finish_closure(
        self, receipt: AdmissionDeletionReceipt, *, expected_closure_version: int
    ) -> AdmissionClosureIntent:
        try:
            receipt = AdmissionDeletionReceipt.model_validate(receipt.model_dump())
        except ValueError:
            raise OpportunityError(_MISSING) from None
        row, stored = await self._locked_closure(receipt.closure.closure_id, mutation=True)
        if stored.receipt is not None:
            if stored.receipt != receipt:
                raise OpportunityError(_CONFLICT)
            return stored.intent
        now = await self.profiles.database_time()
        if (
            stored.authorized_at is None
            or receipt.closure != stored.intent
            or (
                stored.intent.version != expected_closure_version
                or receipt.deleted_at < stored.authorized_at
                or receipt.deleted_at > now
            )
        ):
            raise OpportunityError(_STALE)
        reads = await self._closure_reads(stored.members, lock=True)
        if len(reads) != len(stored.reads) or any(
            (a.permit, a.attempt_version) != (b.permit, b.attempt_version)
            for a, b in zip(reads, stored.reads, strict=True)
        ):
            raise OpportunityError(_MISSING)
        if any(r.released_at is None and now < r.permit.expires_at for r in reads):
            raise OpportunityError(StopCode.M9_INVALIDATION_INCOMPLETE)
        objects = [o for m in stored.members for o in m.admission.objects]
        if len({p.payload_ref for p in receipt.retained_proofs}) != len(receipt.retained_proofs):
            raise OpportunityError(_MISSING)
        for proof in receipt.retained_proofs:
            if proof not in objects or proof.retained_material_digest is None:
                raise OpportunityError(_MISSING)
            refs = {proof.payload_ref, proof.integrity_ref, proof.attestation_ref}
            while True:
                aliases = [o for o in objects if refs.intersection((o.payload_ref, o.integrity_ref, o.attestation_ref))]
                expanded = refs | {r for o in aliases for r in (o.payload_ref, o.integrity_ref, o.attestation_ref)}
                if expanded == refs:
                    break
                refs = expanded
            if any(not r.digest_proof_may_be_retained for o in aliases for r in o.data_rules):
                raise OpportunityError(_MISSING)
        for member in stored.members:
            await self._phase_member(member, phase=AdmissionPhase.ERASED, closure_id=stored.intent.closure_id, now=now)
        updated = stored.model_copy(
            update={
                "intent": stored.intent.model_copy(update={"phase": "ERASED", "version": 3}),
                "receipt": receipt,
                "finished_at": now,
            }
        )
        await self._store_closure(updated, row)
        return updated.intent

    async def claim_dispatch(
        self, attempt_id: str, *, expected_attempt_version: int, expected_envelope_version: int
    ) -> DispatchClaim:
        row, record = await self._guard(attempt_id, operational=True)
        envelope = await self._envelope(record, lock=True)
        if (
            envelope is None
            or envelope.version != expected_envelope_version
            or record.attempt.attempt_version != expected_attempt_version
        ):
            raise OpportunityError(_STALE)
        if envelope.dispatch_claim is not None or record.attempt.state != AttemptStateV2.RUNNING:
            raise OpportunityError(StopCode.M9_ACQUISITION_OUTCOME_UNKNOWN)
        now = await self.profiles.database_time()
        require_admission_access(envelope, now=now, operational=True)
        claim = DispatchClaim(
            claim_id=uuid7(),
            context=record.command.context,
            request_digest=record.attempt.request_digest,
            attempt_id=attempt_id,
            attempt_version=expected_attempt_version + 1,
            envelope_version=envelope.version + 1,
            claimed_at=now,
        )
        body = {**envelope.model_dump(), "version": claim.envelope_version, "dispatch_claim": claim}
        updated = AdmissionEnvelope.model_validate({**body, "metadata_digest": admission_metadata_digest(body)})
        attempt = AcquisitionAttemptV2.model_validate(
            {
                **record.attempt.model_dump(),
                "attempt_version": claim.attempt_version,
                "quota_disposition": "POSSIBLY_CONSUMED",
            }
        )
        await self._save_attempt(row, record.model_copy(update={"attempt": attempt}), transitioned_at=now)
        await self._save_envelope(updated, expected_version=envelope.version)
        return claim

    @staticmethod
    def _material_loss_digest(envelope: AdmissionEnvelope, version: int) -> str:
        return digest_canonical(
            {
                "domain": "m9.manual-material-unavailable.v1",
                "envelope_version": version,
                "original": envelope.model_dump(exclude={"phase", "version", "metadata_digest"}),
            }
        )

    async def _material_unavailable(self, record: _AttemptRecord) -> bool:
        markers = (
            await self.session.scalars(
                select(M9EventModel).where(
                    M9EventModel.user_id == self.user_id,
                    M9EventModel.project_name == self.project_name,
                    M9EventModel.aggregate_id == record.attempt.attempt_id,
                    M9EventModel.event_kind == "MANUAL_MATERIAL_UNAVAILABLE",
                )
            )
        ).all()
        if not markers:
            return False
        envelope = await self._envelope(record)
        now = await self.profiles.database_time()
        if envelope is None or envelope.admitted_at is None or len(markers) != 1:
            raise OpportunityError(_MISSING)
        marker = markers[0]
        if (
            not 1 <= marker.aggregate_revision <= envelope.version
            or marker.payload_digest != self._material_loss_digest(envelope, marker.aggregate_revision)
            or not envelope.admitted_at <= marker.committed_at <= now
        ):
            raise OpportunityError(_MISSING)
        return True

    async def mark_material_unavailable(self, attempt_id: str, *, expected_envelope_version: int) -> None:
        _, record = await self._guard(attempt_id, operational=False)
        envelope = await self._envelope(record, lock=True)
        if envelope is None or envelope.phase != AdmissionPhase.READY or envelope.version != expected_envelope_version:
            raise OpportunityError(_STALE)
        if await self._material_unavailable(record):
            return
        self._add_event(
            aggregate_id=attempt_id,
            version=envelope.version,
            kind="MANUAL_MATERIAL_UNAVAILABLE",
            digest=self._material_loss_digest(envelope, envelope.version),
            at=await self.profiles.database_time(),
        )
        await _flush(self.session)

    async def begin_read(
        self, attempt_id: str, *, expected_envelope_version: int, operational: bool
    ) -> AdmissionReadPermit:
        _, record = await self._guard(attempt_id, operational=operational)
        envelope = await self._envelope(record, lock=True)
        if envelope is None or envelope.version != expected_envelope_version or envelope.deadlines is None:
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
        require_admission_access(envelope, now=now, operational=operational)
        if await self._material_unavailable(record):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        limits = [envelope.deadlines.retention_due_at]
        if operational:
            limits.append(envelope.deadlines.refresh_due_at)
        deadline = min((d for d in limits if d is not None), default=None)
        expires_at = min(now + timedelta(seconds=30), deadline) if deadline is not None else now + timedelta(seconds=30)
        permit = AdmissionReadPermit(
            lease_id=uuid7(),
            user_id=self.user_id,
            project_name=self.project_name,
            attempt_id=attempt_id,
            envelope_version=envelope.version,
            operational=operational,
            issued_at=now,
            expires_at=expires_at,
            access_deadline=deadline,
        )
        lease = _ReadLeaseRecord(permit=permit, attempt_version=record.attempt.attempt_version, released_at=None)
        self.session.add(
            M9ManualReadLeaseModel(
                **{
                    name: getattr(permit, name)
                    for name in (
                        "user_id",
                        "project_name",
                        "lease_id",
                        "attempt_id",
                        "envelope_version",
                        "operational",
                        "issued_at",
                        "expires_at",
                    )
                },
                attempt_version=record.attempt.attempt_version,
                released_at=None,
                body_json=_pack(lease),
                metadata_digest=_record_digest(lease),
            )
        )
        self._add_event(
            aggregate_id=permit.lease_id,
            version=1,
            kind="MANUAL_READ_ISSUED",
            digest=_record_digest(lease),
            at=permit.issued_at,
        )
        await _flush(self.session)
        return permit

    async def release_read(self, lease_id: str) -> None:
        row = await self.session.get(
            M9ManualReadLeaseModel, (self.user_id, self.project_name, lease_id), populate_existing=True
        )
        if row is None:
            return
        initial = _read_lease(row)
        await self._guard(initial.permit.attempt_id, operational=False)
        row = (
            await self.session.scalars(
                select(M9ManualReadLeaseModel)
                .where(
                    M9ManualReadLeaseModel.user_id == self.user_id,
                    M9ManualReadLeaseModel.project_name == self.project_name,
                    M9ManualReadLeaseModel.lease_id == lease_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).one()
        lease = await self._verified_read(row)
        if lease.released_at is not None:
            return
        released_at = await self.profiles.database_time()
        lease = lease.model_copy(update={"released_at": released_at})
        row.released_at = lease.released_at
        row.body_json = _pack(lease)
        row.metadata_digest = _record_digest(lease)
        self._add_event(
            aggregate_id=lease_id,
            version=2,
            kind="MANUAL_READ_RELEASED",
            digest=_record_digest(lease),
            at=released_at,
        )
        await _flush(self.session)

    def _event_digest(self, record: _AttemptRecord, event: _Transition) -> str:
        body: dict[str, Any] = {
            "domain": "m9.manual-attempt-transition.v1",
            "context": record.command.context,
            "request_digest": record.attempt.request_digest,
            "attempt_id": record.attempt.attempt_id,
            "transition": event,
        }
        if event.to_state in (AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED, AttemptStateV2.EXPIRED_UNRECOVERABLE):
            body.update(terminal_attempt=record.attempt, terminal_receipt=record.receipt)
        return digest_canonical(body)

    def _event_kind(self, event: _Transition) -> str:
        return (
            "MANUAL_ATTEMPT_EXPIRED"
            if event.to_state == AttemptStateV2.EXPIRED_UNRECOVERABLE
            else "MANUAL_ATTEMPT_" + event.to_state.value
        )

    async def _verify_history(self, record: _AttemptRecord) -> None:
        events = sorted(record.transitions, key=lambda e: e.to_version)
        if not events:
            if record.attempt.state in (
                AttemptStateV2.OUTCOME_UNKNOWN,
                AttemptStateV2.NEEDS_OPERATOR,
                AttemptStateV2.EXPIRED_UNRECOVERABLE,
                AttemptStateV2.SUCCEEDED,
                AttemptStateV2.FAILED,
            ):
                raise OpportunityError(_MISSING)
            return
        if (
            len({e.to_version for e in events}) != len(events)
            or any(
                (a.to_version, a.to_state) != (b.from_version, b.from_state) or a.at > b.at for a, b in pairwise(events)
            )
            or (events[-1].to_version, events[-1].to_state, events[-1].at)
            != (record.attempt.attempt_version, record.attempt.state, record.changed_at)
        ):
            raise OpportunityError(_MISSING)
        for event in events:
            rows = (
                await self.session.scalars(
                    select(M9EventModel).where(
                        M9EventModel.user_id == self.user_id,
                        M9EventModel.project_name == self.project_name,
                        M9EventModel.aggregate_id == record.attempt.attempt_id,
                        M9EventModel.aggregate_revision == event.to_version,
                        M9EventModel.event_kind == self._event_kind(event),
                    )
                )
            ).all()
            if len(rows) != 1 or (rows[0].payload_digest, rows[0].committed_at) != (
                self._event_digest(record, event),
                event.at,
            ):
                raise OpportunityError(_MISSING)

    async def _receipt_snapshots(
        self, record: _AttemptRecord, *, cleanup_only: bool = False
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        await self._checkpoints(record, cleanup_only=cleanup_only)
        row = await self._snapshot_row_for_attempt(record.attempt.attempt_id)
        if row is None:
            return (), (), ()
        stored = await self._snapshot_record(row, record=record, cleanup_only=cleanup_only)
        return (
            (stored.snapshot.snapshot_id,),
            (stored.snapshot.snapshot_digest,),
            (stored.provenance_digest,),
        )

    async def _verify_terminal_receipt(self, record: _AttemptRecord, *, cleanup_only: bool = False) -> None:
        receipt, attempt = record.receipt, record.attempt
        snapshots = await self._receipt_snapshots(record, cleanup_only=cleanup_only)
        if attempt.state in (AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED):
            await self._known_response_snapshot(record, state=attempt.state, cleanup_only=cleanup_only)
        if (
            receipt is None
            or (receipt.snapshot_ids, receipt.snapshot_digests, receipt.snapshot_provenance_digests) != snapshots
            or digest_acquisition_result_v2(receipt) != receipt.result_digest
            or (
                receipt.command_id,
                receipt.request_digest,
                receipt.attempt_id,
                receipt.attempt_version,
                receipt.state,
                receipt.outcome_reason,
                receipt.closure,
                receipt.quota_disposition,
                receipt.quota_units_observed,
                receipt.committed_at,
            )
            != (
                attempt.command_id,
                attempt.request_digest,
                attempt.attempt_id,
                attempt.attempt_version,
                attempt.state,
                attempt.outcome_reason,
                attempt.closure,
                attempt.quota_disposition,
                attempt.quota_units_observed,
                attempt.completed_at,
            )
        ):
            raise OpportunityError(_MISSING)
        row = (
            await self.session.scalars(
                select(M9CommandReceiptModel)
                .where(
                    M9CommandReceiptModel.user_id == self.user_id,
                    M9CommandReceiptModel.actor_id == attempt.actor_id,
                    M9CommandReceiptModel.operation == "acquire",
                    M9CommandReceiptModel.command_id == attempt.command_id,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None or (
            row.project_name,
            row.request_digest,
            row.result_kind,
            row.result_ref,
            row.result_digest,
            row.committed_at,
        ) != (
            self.project_name,
            attempt.request_digest,
            "ACQUISITION_V2",
            f"{attempt.attempt_id}:{attempt.attempt_version}",
            receipt.result_digest,
            receipt.committed_at,
        ):
            raise OpportunityError(_MISSING)

    def _transition_record(
        self, record: _AttemptRecord, attempt: AcquisitionAttemptV2, *, now: datetime, resolver_id: str
    ) -> tuple[_AttemptRecord, _Transition]:
        event = _Transition(
            from_state=record.attempt.state,
            to_state=attempt.state,
            from_version=record.attempt.attempt_version,
            to_version=attempt.attempt_version,
            at=now,
            resolver_id=resolver_id,
        )
        return record.model_copy(
            update={"attempt": attempt, "changed_at": now, "transitions": (*record.transitions, event)}
        ), event

    async def _stage_transition(self, record: _AttemptRecord, event: _Transition) -> None:
        self.session.add(
            M9EventModel(
                user_id=self.user_id,
                project_name=self.project_name,
                event_kind=self._event_kind(event),
                aggregate_id=record.attempt.attempt_id,
                aggregate_revision=event.to_version,
                payload_digest=self._event_digest(record, event),
                committed_at=event.at,
            )
        )
        await _flush(self.session)

    async def _mark_uncertainty(
        self, attempt_id: str, *, expected_attempt_version: int, state: AttemptStateV2
    ) -> AcquisitionAttemptV2:
        row, record = await self._guard(attempt_id, operational=False)
        envelope = await self._envelope(record, lock=True)
        if record.attempt.attempt_version != expected_attempt_version:
            raise OpportunityError(_STALE)
        if envelope is None or envelope.dispatch_claim is None:
            raise OpportunityError(_MISSING)
        now = await self.profiles.database_time()
        attempt = AcquisitionAttemptV2.model_validate(
            {
                **record.attempt.model_dump(),
                "attempt_version": expected_attempt_version + 1,
                "state": state,
                "outcome_reason": AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
            }
        )
        try:
            updated, event = self._transition_record(record, attempt, now=now, resolver_id="manual-acquisition-host")
        except ValueError:
            raise OpportunityError(_STALE) from None
        await self._save_attempt(row, updated, transitioned_at=now)
        await self._stage_transition(updated, event)
        return attempt

    async def mark_outcome_unknown(self, attempt_id: str, *, expected_attempt_version: int) -> AcquisitionAttemptV2:
        return await self._mark_uncertainty(
            attempt_id, expected_attempt_version=expected_attempt_version, state=AttemptStateV2.OUTCOME_UNKNOWN
        )

    async def mark_needs_operator(self, attempt_id: str, *, expected_attempt_version: int) -> AcquisitionAttemptV2:
        return await self._mark_uncertainty(
            attempt_id, expected_attempt_version=expected_attempt_version, state=AttemptStateV2.NEEDS_OPERATOR
        )

    async def get_receipt(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2 | None:
        attempt = await self.get_for_command(command)
        if attempt is None:
            return None
        row = await self._row(attempt.attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        return (await self._record(row)).receipt

    async def get_current_receipt(self, command: AcquireSourceQueryV2) -> AcquisitionReceiptV2 | None:
        """Project the retained transition without changing clocks or outcome authority."""
        attempt = await self.get_for_command(command)
        if attempt is None:
            return None
        row = await self._row(attempt.attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        record = await self._record(row)
        if record.receipt is not None:
            return record.receipt
        ids, digests, provenance = await self._receipt_snapshots(record)
        committed_at = record.changed_at
        snapshot_row = await self._snapshot_row_for_attempt(attempt.attempt_id)
        if snapshot_row is not None:
            stored = await self._snapshot_record(snapshot_row, record=record)
            committed_at = max(committed_at, stored.stored_at)
        receipt = AcquisitionReceiptV2(
            protocol_version="m9.acquisition.v2",
            command_id=attempt.command_id,
            request_digest=attempt.request_digest,
            attempt_id=attempt.attempt_id,
            attempt_version=attempt.attempt_version,
            state=attempt.state,
            outcome_reason=attempt.outcome_reason,
            snapshot_ids=ids,
            snapshot_digests=digests,
            snapshot_provenance_digests=provenance,
            closure=attempt.closure,
            quota_disposition=attempt.quota_disposition,
            quota_units_observed=attempt.quota_units_observed,
            result_digest="sha256:" + "0" * 64,
            committed_at=committed_at,
        )
        return receipt.model_copy(update={"result_digest": digest_acquisition_result_v2(receipt)})

    async def _known_response_snapshot(
        self, record: _AttemptRecord, *, state: AttemptStateV2, cleanup_only: bool = False
    ) -> _SnapshotRecord:
        row = await self._snapshot_row_for_attempt(record.attempt.attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        stored = await self._snapshot_record(row, record=record, cleanup_only=cleanup_only)
        complete = stored.snapshot.coverage_state == CoverageState.COMPLETE_WITHIN_DECLARED_BOUNDS
        if stored.provenance.origin != SnapshotOriginV2.SOURCE_RESPONSE_VERIFIED or complete != (
            state == AttemptStateV2.SUCCEEDED
        ):
            raise OpportunityError(_MISSING)
        return stored

    async def finish_acquisition(
        self,
        attempt_id: str,
        *,
        expected_attempt_version: int,
        state: AttemptStateV2,
        reason: AttemptOutcomeReason,
        resolver_id: str,
    ) -> AcquisitionReceiptV2:
        if state not in (AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED):
            raise OpportunityError(_MISSING)
        if await self.get_attempt(attempt_id) is None:
            raise OpportunityError(_MISSING)
        row = await self._row(attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        initial = await self._record(row)
        if initial.receipt is not None:
            return initial.receipt
        row, record = await self._guard(attempt_id, operational=True)
        if record.attempt.attempt_version != expected_attempt_version:
            raise OpportunityError(_STALE)
        if record.attempt.state in (AttemptStateV2.OUTCOME_UNKNOWN, AttemptStateV2.NEEDS_OPERATOR):
            raise OpportunityError(StopCode.M9_ACQUISITION_OUTCOME_UNKNOWN)
        if record.attempt.state != AttemptStateV2.RUNNING:
            raise OpportunityError(_STALE)
        envelope = await self._envelope(record, lock=True)
        if envelope is None:
            raise OpportunityError(_MISSING)
        now = await self.profiles.database_time()
        require_admission_access(envelope, now=now, operational=True)
        stored = await self._known_response_snapshot(record, state=state)
        checkpoints = await self._checkpoints(record)
        observed = bool(checkpoints) and all(c.quota_units_observed is not None for c in checkpoints)
        try:
            attempt = AcquisitionAttemptV2.model_validate(
                {
                    **record.attempt.model_dump(),
                    "attempt_version": expected_attempt_version + 1,
                    "state": state,
                    "outcome_reason": reason,
                    "completed_at": now,
                    "provider_request_id": next(
                        (
                            c.page.provider_request_id
                            for c in reversed(checkpoints)
                            if c.page.provider_request_id is not None
                        ),
                        record.attempt.provider_request_id,
                    ),
                    "quota_disposition": QuotaDispositionV2.OBSERVED if observed else record.attempt.quota_disposition,
                    "quota_units_observed": sum(c.quota_units_observed or 0 for c in checkpoints)
                    if observed
                    else record.attempt.quota_units_observed,
                }
            )
            updated, event = self._transition_record(record, attempt, now=now, resolver_id=resolver_id)
            receipt = AcquisitionReceiptV2(
                protocol_version="m9.acquisition.v2",
                command_id=attempt.command_id,
                request_digest=attempt.request_digest,
                attempt_id=attempt_id,
                attempt_version=attempt.attempt_version,
                state=attempt.state,
                outcome_reason=attempt.outcome_reason,
                snapshot_ids=(stored.snapshot.snapshot_id,),
                snapshot_digests=(stored.snapshot.snapshot_digest,),
                snapshot_provenance_digests=(stored.provenance_digest,),
                closure=None,
                quota_disposition=attempt.quota_disposition,
                quota_units_observed=attempt.quota_units_observed,
                result_digest="sha256:" + "0" * 64,
                committed_at=now,
            )
        except ValueError:
            raise OpportunityError(_MISSING) from None
        receipt = receipt.model_copy(update={"result_digest": digest_acquisition_result_v2(receipt)})
        updated = updated.model_copy(update={"receipt": receipt})
        await self._save_attempt(row, updated, transitioned_at=now)
        self.session.add(
            M9CommandReceiptModel(
                user_id=self.user_id,
                project_name=self.project_name,
                actor_id=attempt.actor_id,
                operation="acquire",
                command_id=attempt.command_id,
                request_digest=attempt.request_digest,
                result_kind="ACQUISITION_V2",
                result_ref=f"{attempt_id}:{attempt.attempt_version}",
                result_digest=receipt.result_digest,
                committed_at=now,
            )
        )
        await self._stage_transition(updated, event)
        return receipt

    async def close_expired(
        self, attempt_id: str, *, expected_attempt_version: int, resolver_id: str
    ) -> AcquisitionReceiptV2:
        initial = await self.get_attempt(attempt_id)
        if initial is None:
            raise OpportunityError(_MISSING)
        row = await self._row(attempt_id)
        if row is None:
            raise OpportunityError(_MISSING)
        initial_record = await self._record(row)
        if initial_record.receipt is not None:
            return initial_record.receipt
        row, record = await self._guard(attempt_id, operational=False)
        if record.attempt.attempt_version != expected_attempt_version or record.attempt.state not in (
            AttemptStateV2.RUNNING,
            AttemptStateV2.OUTCOME_UNKNOWN,
            AttemptStateV2.NEEDS_OPERATOR,
        ):
            raise OpportunityError(_STALE)
        envelope = await self._envelope(record, lock=True)
        if envelope is None or envelope.deadlines is None:
            raise OpportunityError(_MISSING)
        if envelope.dispatch_claim is None and (
            record.attempt.state != AttemptStateV2.RUNNING
            or record.attempt.attempt_version != envelope.request.attempt_version
            or envelope.version != 2
            or record.attempt.quota_disposition != QuotaDispositionV2.UNKNOWN
            or record.attempt.quota_units_observed is not None
            or record.transitions
        ):
            raise OpportunityError(_MISSING)
        now = await self.profiles.database_time()
        retention, refresh = envelope.deadlines.retention_due_at, envelope.deadlines.refresh_due_at
        if retention is not None and now >= retention:
            disposition, deadline = ExpiryDispositionV2.ADMISSION_RETENTION_EXPIRED, retention
        elif refresh is not None and now >= refresh:
            disposition, deadline = ExpiryDispositionV2.OPERATIONAL_EVIDENCE_STALE, refresh
        else:
            raise OpportunityError(_STALE)
        snapshot_ids, snapshot_digests, provenance_digests = await self._receipt_snapshots(record)
        events = []
        if record.attempt.state == AttemptStateV2.RUNNING:
            unknown = AcquisitionAttemptV2.model_validate(
                {
                    **record.attempt.model_dump(),
                    "attempt_version": record.attempt.attempt_version + 1,
                    "state": AttemptStateV2.OUTCOME_UNKNOWN,
                    "outcome_reason": AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
                }
            )
            record, event = self._transition_record(record, unknown, now=now, resolver_id=resolver_id)
            events.append(event)
        try:
            closure = ExpiryClosureV2(
                disposition=disposition,
                original_deadline=deadline,
                closed_at=now,
                resolver_id=resolver_id,
                resolver_version="m9.manual-policy-expiry.v1",
                expected_prior_version=record.attempt.attempt_version,
            )
            expired = AcquisitionAttemptV2.model_validate(
                {
                    **record.attempt.model_dump(),
                    "state": AttemptStateV2.EXPIRED_UNRECOVERABLE,
                    "attempt_version": record.attempt.attempt_version + 1,
                    "completed_at": now,
                    "closure": closure,
                }
            )
            record, event = self._transition_record(record, expired, now=now, resolver_id=resolver_id)
        except ValueError:
            raise OpportunityError(_MISSING) from None
        events.append(event)
        receipt = AcquisitionReceiptV2(
            protocol_version="m9.acquisition.v2",
            command_id=expired.command_id,
            request_digest=expired.request_digest,
            attempt_id=attempt_id,
            attempt_version=expired.attempt_version,
            state=expired.state,
            outcome_reason=expired.outcome_reason,
            snapshot_ids=snapshot_ids,
            snapshot_digests=snapshot_digests,
            snapshot_provenance_digests=provenance_digests,
            closure=closure,
            quota_disposition=expired.quota_disposition,
            quota_units_observed=expired.quota_units_observed,
            result_digest="sha256:" + "0" * 64,
            committed_at=now,
        )
        receipt = receipt.model_copy(update={"result_digest": digest_acquisition_result_v2(receipt)})
        record = record.model_copy(update={"receipt": receipt})
        await self._save_attempt(row, record, transitioned_at=now)
        self.session.add(
            M9CommandReceiptModel(
                user_id=self.user_id,
                project_name=self.project_name,
                actor_id=expired.actor_id,
                operation="acquire",
                command_id=expired.command_id,
                request_digest=expired.request_digest,
                result_kind="ACQUISITION_V2",
                result_ref=f"{attempt_id}:{expired.attempt_version}",
                result_digest=receipt.result_digest,
                committed_at=now,
            )
        )
        for transition in events:
            await self._stage_transition(record, transition)
        return receipt


class ManualAdmissionTransaction:
    """One SQL session; the host supplies current project-policy authority."""

    def __init__(self, session: AsyncSession, *, user_id: str, project_name: str) -> None:
        self.session, self.user_id, self.project_name = session, user_id, project_name
        self.manual = ManualAdmissionRepository(
            session, user_id=user_id, project_name=project_name, policy_identity=self.creative_policy_identity
        )
        self.profiles = self.manual.profiles
        self.capabilities = self.manual.capabilities
        self.queries = self.manual.queries

    async def creative_policy_identity(self) -> tuple[str, str, str]:
        raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
