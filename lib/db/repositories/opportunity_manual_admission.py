"""Typed manual custody metadata under command, policy, upload and row guards."""

from __future__ import annotations

import struct
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.opportunity import M9CommandReceiptModel, M9EventModel
from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel, M9SnapshotPageModel, M9SourceSnapshotModel
from lib.db.models.opportunity_manual_admission import (
    M9ManualAdmissionModel,
    M9ManualPublicationIntentModel,
    M9ManualReadLeaseModel,
    M9ManualUploadLeaseModel,
)
from lib.db.repositories.opportunity import OpportunityProfileRepository
from lib.db.repositories.opportunity_acquisition import CapabilityEvidenceRepository, SourceQueryRepository
from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.exploration import uuid7
from r2.contracts.opportunity import (
    AttemptOutcomeReason,
    CapabilityEvaluationRequest,
    CommandContext,
    M9ContractModel,
    SourceQuery,
)
from r2.contracts.opportunity_acquisition_v2 import (
    AcquireSourceQueryV2,
    AcquisitionAttemptV2,
    AcquisitionReceiptV2,
    AttemptStateV2,
    ExpiryClosureV2,
    ExpiryDispositionV2,
    QuotaDispositionV2,
)
from r2.opportunity.acquisition_v2_digests import digest_acquisition_request_v2, digest_acquisition_result_v2
from r2.opportunity.capabilities import validate_capability
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import (
    AdmissionEnvelope,
    AdmissionPhase,
    AdmissionReadPermit,
    AdmissionRequest,
    DispatchClaim,
    ManualBindingDescriptor,
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
            AttemptStateV2.RUNNING: {AttemptStateV2.OUTCOME_UNKNOWN},
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

    async def _record(self, row: M9AcquisitionAttemptModel) -> _AttemptRecord:
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
        if attempt.state == AttemptStateV2.EXPIRED_UNRECOVERABLE:
            await self._verify_expiry_receipt(record)
        elif record.receipt is not None or attempt.state in (AttemptStateV2.SUCCEEDED, AttemptStateV2.FAILED):
            raise OpportunityError(_MISSING)
        return record

    async def _subject(self, record: _AttemptRecord, *, operational: bool) -> SourceQuery:
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

    async def _guard(
        self, attempt_id: str, *, operational: bool, claim: tuple[str, int] | None = None
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
        hint = await self._envelope(record)
        claims = set(() if claim is None else (claim,))
        if hint is not None and hint.claim_ref is not None:
            claims.add((hint.claim_ref, hint.request.upload_version))
        for identity in sorted(claims):
            await self._upload_guard(*identity)
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
        record = await self._record(row)
        if record.command != command:
            raise OpportunityError(_CONFLICT)
        return record.attempt

    async def get_attempt(self, attempt_id: str) -> AcquisitionAttemptV2 | None:
        row = await self._row(attempt_id)
        if row is None:
            return None
        record = await self._record(row)
        return await self.get_for_command(record.command)

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

    async def _save_envelope(self, envelope: AdmissionEnvelope, *, expected_version: int) -> None:
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
        row, record = await self._guard(request.attempt_id, operational=True)
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
            publication.request.attempt_id, operational=True, claim=(publication.claim_ref, publication.upload_version)
        )
        envelope = await self._envelope(record, lock=True)
        if (
            envelope is None
            or envelope.version != expected_envelope_version
            or record.attempt.state != AttemptStateV2.RUNNING
        ):
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
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

    async def begin_read(
        self, attempt_id: str, *, expected_envelope_version: int, operational: bool
    ) -> AdmissionReadPermit:
        _, record = await self._guard(attempt_id, operational=operational)
        envelope = await self._envelope(record, lock=True)
        if envelope is None or envelope.version != expected_envelope_version or envelope.deadlines is None:
            raise OpportunityError(_STALE)
        now = await self.profiles.database_time()
        require_admission_access(envelope, now=now, operational=operational)
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
        lease = _read_lease(row)
        if lease.released_at is not None:
            return
        lease = lease.model_copy(update={"released_at": await self.profiles.database_time()})
        row.released_at = lease.released_at
        row.body_json = _pack(lease)
        row.metadata_digest = _record_digest(lease)
        await _flush(self.session)

    def _event_digest(self, record: _AttemptRecord, event: _Transition) -> str:
        return digest_canonical(
            {
                "domain": "m9.manual-attempt-transition.v1",
                "context": record.command.context,
                "request_digest": record.attempt.request_digest,
                "attempt_id": record.attempt.attempt_id,
                "transition": event,
            }
        )

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

    async def _verify_expiry_receipt(self, record: _AttemptRecord) -> None:
        receipt, attempt = record.receipt, record.attempt
        if (
            receipt is None
            or receipt.snapshot_ids
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
        if envelope is None or envelope.deadlines is None or envelope.dispatch_claim is None:
            raise OpportunityError(_MISSING)
        now = await self.profiles.database_time()
        retention, refresh = envelope.deadlines.retention_due_at, envelope.deadlines.refresh_due_at
        if retention is not None and now >= retention:
            disposition, deadline = ExpiryDispositionV2.ADMISSION_RETENTION_EXPIRED, retention
        elif refresh is not None and now >= refresh:
            disposition, deadline = ExpiryDispositionV2.OPERATIONAL_EVIDENCE_STALE, refresh
        else:
            raise OpportunityError(_STALE)
        for kind, column in (
            (M9SourceSnapshotModel, M9SourceSnapshotModel.snapshot_id),
            (M9SnapshotPageModel, M9SnapshotPageModel.ordinal),
        ):
            if (
                await self.session.scalar(
                    select(column)
                    .where(
                        kind.user_id == self.user_id,
                        kind.project_name == self.project_name,
                        kind.attempt_id == attempt_id,
                    )
                    .limit(1)
                )
                is not None
            ):
                # Checkpoint-bearing expiry needs the qualified V2 provenance writer.
                raise OpportunityError(_MISSING)
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
            snapshot_ids=(),
            snapshot_digests=(),
            snapshot_provenance_digests=(),
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
