"""Verified immutable source-query evidence for the acquisition application."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from hashlib import sha256
from typing import Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts.opportunity import (
    AcquireSourceQuery,
    AcquisitionAttempt,
    AcquisitionReceipt,
    AttemptOutcomeReason,
    AttemptState,
    CapabilityEvaluationRequest,
    CommandContext,
    CoverageState,
    DeclareSourceQuery,
    EffectiveCapabilityEvaluation,
    ErasableEvidencePayload,
    M9ContractModel,
    MissingReason,
    NormalizedSourceObservation,
    OpportunityCohortProfile,
    OpportunityCohortProfileHead,
    PayloadRef,
    QueryReceipt,
    SnapshotPage,
    SourceCapabilityGrant,
    SourcePageRequest,
    SourcePageResult,
    SourceQuery,
    SourceQueryHead,
    SourceSnapshot,
)
from r2.opportunity.capabilities import page_clocks, require_clocks_current, retain_page_proof, validate_capability
from r2.opportunity.digests import (
    digest_command_request,
    digest_command_result,
    digest_source_observation,
    digest_source_query,
    digest_source_snapshot,
)
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.normalization import decode_manual_payload, normalize_manual_page
from r2.opportunity.ports import MarketSourcePort, SnapshotEvidenceStore, SourceCapabilityPort
from r2.opportunity.profiles import verified_profile


class NativeFieldMaterial(M9ContractModel):
    """Only erasable references and lossless field metadata cross the DB boundary."""

    source_identity_ref: str
    native_field_name: str
    native_field_definition: str
    native_field_version: str
    data_class: str
    unit: str | None
    window_start: AwareDatetime | None
    window_end: AwareDatetime | None
    missing_reason: MissingReason | None
    normalization_version: str
    material_ref: str
    material_integrity_ref: str
    value_ref: str | None
    value_integrity_ref: str | None
    retained_normalized_value_digest: str | None


class ManualPageMaterials(M9ContractModel):
    raw: PayloadRef
    fields: tuple[NativeFieldMaterial, ...]


async def materialize_manual_page(
    request: SourcePageRequest,
    page: SourcePageResult,
    grant: SourceCapabilityGrant,
    evidence: SnapshotEvidenceStore,
) -> ManualPageMaterials:
    """Store and verify manual native material outside the application transaction."""
    if (request.source_kind, request.source_contract_version, request.operation) != (
        "manual-import",
        "manual-import.v1",
        "import",
    ) or (request.user_id, request.project_name, request.capability_grant_digest) != (
        grant.user_id,
        grant.project_name,
        grant.grant_digest,
    ):
        raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
    page = SourcePageResult.model_validate(page.model_dump())
    drafts = normalize_manual_page(page)
    retain_raw = retain_page_proof(page, grant)
    rules = {rule.data_class: rule for rule in grant.data_rules}

    def identity(native: str) -> str:
        return canonical_json_bytes(
            {
                "source_kind": request.source_kind,
                "source_contract_version": request.source_contract_version,
                "native_id": native,
            }
        ).decode("utf-8")

    async def put(kind: str, raw: bytes, ids: tuple[str, ...], classes: tuple[str, ...], retain: bool) -> PayloadRef:
        stored = await evidence.put_if_absent(
            ErasableEvidencePayload(
                user_id=request.user_id,
                project_name=request.project_name,
                attempt_id=request.attempt_id,
                page_ordinal=request.page_ordinal,
                evidence_kind=kind,
                raw_payload=raw,
                raw_media_type="application/json",
                source_native_ids=ids,
                data_classes=classes,
                retain_digest_proof=retain,
            )
        )
        stored = PayloadRef.model_validate(stored.model_dump())
        if (
            await evidence.verify_and_read(stored.payload_ref, stored.payload_integrity_ref) != raw
            or stored.raw_size_bytes != len(raw)
            or stored.retained_content_digest != ("sha256:" + sha256(raw).hexdigest() if retain else None)
        ):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        return stored

    raw = await put(
        "raw-page", page.raw_payload, tuple(identity(n) for n in page.source_native_ids), page.data_classes, retain_raw
    )
    fields = []
    for ordinal, draft in enumerate(drafts, start=1):
        missing = draft["missing_reason"] is not None
        data_class = str(draft["data_class"])
        body = {
            "schema": "m9.manual-native-value.v1",
            "source_kind": request.source_kind,
            "source_contract_version": request.source_contract_version,
            **{
                key: value for key, value in draft.items() if key not in ("source_native_id", "value", "missing_reason")
            },
            **({"missing_reason": draft["missing_reason"]} if missing else {"value": draft["value"]}),
        }
        material = await put(
            f"native-field-{ordinal}",
            canonical_json_bytes(body),
            (identity(str(draft["source_native_id"])),),
            (data_class,),
            not missing and rules[data_class].digest_proof_may_be_retained,
        )
        if len(material.source_identity_refs) != 1 or material.source_identity_refs[0] not in raw.source_identity_refs:
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        fields.append(
            NativeFieldMaterial.model_validate(
                {
                    **{k: v for k, v in draft.items() if k not in ("source_native_id", "value")},
                    "source_identity_ref": material.source_identity_refs[0],
                    "material_ref": material.payload_ref,
                    "material_integrity_ref": material.payload_integrity_ref,
                    "value_ref": None if missing else material.payload_ref,
                    "value_integrity_ref": None if missing else material.payload_integrity_ref,
                    "retained_normalized_value_digest": None if missing else material.retained_content_digest,
                }
            )
        )
    return ManualPageMaterials(raw=raw, fields=tuple(fields))


def verified_query(query: SourceQuery) -> SourceQuery:
    try:
        value = SourceQuery.model_validate(query.model_dump())
        if value.query_digest != digest_source_query(value):
            raise ValueError("query integrity differs")
        return value
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None


class PageCheckpoint(M9ContractModel):
    """Internal restart metadata; cursor bytes and native values remain erasable."""

    page: SnapshotPage
    source_identity_refs: tuple[str, ...]
    quota_units_observed: int | None = Field(ge=0)
    next_cursor_ref: str | None
    next_cursor_integrity_ref: str | None
    terminal_page: bool
    provider_observed_at: AwareDatetime | None
    native_fields: tuple[NativeFieldMaterial, ...] = ()

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        if (self.next_cursor_ref is None) != (self.next_cursor_integrity_ref is None):
            raise ValueError("cursor refs must be paired")
        if self.terminal_page != (self.page.response_cursor_digest is None) or self.terminal_page != (
            self.next_cursor_ref is None
        ):
            raise ValueError("cursor metadata must match terminal coverage")
        if len(set(self.source_identity_refs)) != len(self.source_identity_refs):
            raise ValueError("source identities must be distinct")
        if len(self.source_identity_refs) > self.page.record_count or bool(self.source_identity_refs) != bool(
            self.page.record_count
        ):
            raise ValueError("source identity coverage differs from page records")
        if self.page.payload_ref is None and (not self.terminal_page or self.source_identity_refs):
            raise ValueError("missing page cannot carry resumable content")
        return self


def verified_query_receipt(receipt: QueryReceipt, context: CommandContext, request_digest: str) -> QueryReceipt:
    try:
        receipt = QueryReceipt.model_validate(receipt.model_dump())
        query = verified_query(receipt.query)
        if (
            (
                query.user_id,
                query.project_name,
                query.created_by,
                receipt.command_id,
                receipt.request_digest,
                receipt.head.query_id,
                receipt.head.current_revision,
            )
            != (
                context.user_id,
                context.project_name,
                context.actor_id,
                context.command_id,
                request_digest,
                query.query_id,
                query.revision,
            )
            or receipt.committed_at < query.created_at
            or receipt.head.head_version != query.revision
        ):
            raise ValueError("query receipt binding differs")
        if digest_command_result("declare_query", request_digest, receipt) != receipt.result_digest:
            raise ValueError("query receipt result differs")
        return receipt
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None


def verified_acquisition_receipt(
    receipt: AcquisitionReceipt, context: CommandContext, request_digest: str
) -> AcquisitionReceipt:
    try:
        receipt = AcquisitionReceipt.model_validate(receipt.model_dump())
        if (receipt.command_id, receipt.request_digest) != (context.command_id, request_digest) or (
            len(receipt.snapshot_ids) != len(receipt.snapshot_digests)
        ):
            raise ValueError("acquisition receipt binding differs")
        if digest_command_result("acquire", request_digest, receipt) != receipt.result_digest:
            raise ValueError("acquisition receipt result differs")
        return receipt
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None


class AcquisitionProfileReadPort(Protocol):
    async def lock_command_key(self, *, context: CommandContext, operation: str) -> None: ...
    async def database_time(self) -> datetime: ...
    async def get_exact(
        self, *, user_id: str, project_name: str, profile_id: str, revision: int
    ) -> OpportunityCohortProfile | None: ...
    async def get_head_for_update(
        self, *, user_id: str, project_name: str, profile_id: str
    ) -> OpportunityCohortProfileHead | None: ...


class AcquisitionQueryPort(Protocol):
    async def get_exact(self, query_id: str, revision: int) -> SourceQuery | None: ...
    async def get_head(self, query_id: str) -> SourceQueryHead | None: ...
    async def append(self, query: SourceQuery) -> None: ...
    async def stage_head(self, head: SourceQueryHead, *, expected_head_version: int | None) -> None: ...


class ConsumedCapabilityPort(Protocol):
    async def get_grant(self, grant_id: str, version: int) -> SourceCapabilityGrant | None: ...
    async def get_evaluation(self, evaluation_id: str) -> EffectiveCapabilityEvaluation | None: ...
    async def consume(
        self, grant: SourceCapabilityGrant, evaluation: EffectiveCapabilityEvaluation, *, actor_id: str
    ) -> None: ...


class AcquisitionReceiptPort(Protocol):
    async def get_query(self, *, context: CommandContext, request_digest: str) -> QueryReceipt | None: ...
    async def get_query_for_revision(self, query_id: str, revision: int) -> QueryReceipt | None: ...
    async def stage_query(self, *, context: CommandContext, receipt: QueryReceipt) -> None: ...
    async def get_acquisition(self, *, context: CommandContext, request_digest: str) -> AcquisitionReceipt | None: ...
    async def current_acquisition(
        self, *, context: CommandContext, request_digest: str
    ) -> AcquisitionReceipt | None: ...
    async def stage_acquisition(self, *, context: CommandContext, receipt: AcquisitionReceipt) -> None: ...


class AcquisitionAttemptPort(Protocol):
    async def get_exact(self, attempt_id: str) -> AcquisitionAttempt | None: ...
    async def prepare(self, attempt: AcquisitionAttempt) -> tuple[AcquisitionAttempt, bool]: ...
    async def transition(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        state: AttemptState,
        reason: AttemptOutcomeReason | None = None,
    ) -> AcquisitionAttempt: ...


class AcquisitionPagePort(Protocol):
    async def list_for_attempt(self, attempt_id: str) -> tuple[PageCheckpoint, ...]: ...
    async def append(
        self, attempt_id: str, checkpoint: PageCheckpoint, *, expected_attempt_version: int
    ) -> PageCheckpoint: ...


class AcquisitionSnapshotPort(Protocol):
    async def append(self, snapshot: SourceSnapshot) -> None: ...


class AcquisitionObservationPort(Protocol):
    async def append(self, observation: NormalizedSourceObservation, *, expected_head_version: int | None) -> None: ...


class AcquisitionTransactionPort(Protocol):
    @property
    def profiles(self) -> AcquisitionProfileReadPort: ...
    @property
    def queries(self) -> AcquisitionQueryPort: ...
    @property
    def capabilities(self) -> ConsumedCapabilityPort: ...
    @property
    def receipts(self) -> AcquisitionReceiptPort: ...
    @property
    def attempts(self) -> AcquisitionAttemptPort: ...
    @property
    def pages(self) -> AcquisitionPagePort: ...
    @property
    def snapshots(self) -> AcquisitionSnapshotPort: ...
    @property
    def observations(self) -> AcquisitionObservationPort: ...
    async def creative_policy_identity(self) -> tuple[str, str, str]: ...
    async def stage_query_event(self, *, query: SourceQuery, committed_at: datetime) -> None: ...
    async def stage_snapshot_event(self, *, snapshot: SourceSnapshot, committed_at: datetime) -> None: ...


class AcquisitionStorePort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[AcquisitionTransactionPort]: ...


class OpportunityAcquisitionService:
    def __init__(
        self,
        *,
        store: AcquisitionStorePort,
        capabilities: SourceCapabilityPort | None,
        source: MarketSourcePort | None,
        evidence: SnapshotEvidenceStore | None,
        new_id: Callable[[], str],
        user_id: str,
        project_name: str,
        actor_id: str,
    ) -> None:
        self.store, self.capabilities, self.source, self.evidence = store, capabilities, source, evidence
        self.user_id, self.project_name, self.actor_id = user_id, project_name, actor_id
        self._new_id = new_id

    def _scope(self, context: CommandContext) -> None:
        if (context.user_id, context.project_name, context.actor_id) != (
            self.user_id,
            self.project_name,
            self.actor_id,
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)

    async def _query_replay(self, context: CommandContext, request_digest: str) -> QueryReceipt | None:
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=context, operation="declare_query")
            replay = await tx.receipts.get_query(context=context, request_digest=request_digest)
            return None if replay is None else verified_query_receipt(replay, context, request_digest)

    async def _resolve(
        self, command: DeclareSourceQuery | SourceQuery
    ) -> tuple[SourceCapabilityGrant, EffectiveCapabilityEvaluation]:
        draft = command.draft if isinstance(command, DeclareSourceQuery) else command
        if (
            self.capabilities is None
            or self.source is None
            or self.evidence is None
            or (draft.source_kind, draft.source_contract_version, draft.operation)
            != ("manual-import", "manual-import.v1", "import")
        ):
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        if draft.credential_ref is not None:
            raise OpportunityError(StopCode.M9_CREDENTIAL_REFERENCE_INVALID)
        try:
            grant = await self.capabilities.resolve_grant(draft.capability_grant_id)
            grant = SourceCapabilityGrant.model_validate(grant.model_dump())
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
                draft.capability_grant_id,
                draft.capability_grant_version,
                draft.capability_grant_digest,
                draft.source_kind,
                draft.source_contract_version,
                draft.credential_ref,
            ):
                raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
            request = CapabilityEvaluationRequest(
                user_id=self.user_id,
                project_name=self.project_name,
                actor_id=self.actor_id,
                grant_id=grant.grant_id,
                grant_version=grant.grant_version,
                grant_digest=grant.grant_digest,
                source_kind=draft.source_kind,
                operation=draft.operation,
                purpose=draft.intent,
                account_binding_digest=grant.account_binding_digest,
            )
            evaluation = await self.capabilities.evaluate(request)
            evaluation = EffectiveCapabilityEvaluation.model_validate(evaluation.model_dump())
            if (evaluation.evaluation_id, evaluation.evaluation_digest) != (
                draft.capability_evaluation_id,
                draft.capability_evaluation_digest,
            ):
                raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
            return grant, evaluation
        except OpportunityError:
            raise
        except Exception:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE) from None

    def _manual_authority(
        self, command: DeclareSourceQuery | SourceQuery, grant: SourceCapabilityGrant
    ) -> CapabilityEvaluationRequest:
        draft = command.draft if isinstance(command, DeclareSourceQuery) else command
        if len(grant.conditions) != 1:
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        condition = grant.conditions[0].model_dump()
        classes = condition.get("data_classes")
        if (
            set(condition) != {"kind", "upload_ref", "origin_ref", "uploader_id", "data_classes"}
            or condition.get("kind") != "manual-upload-policy.v1"
            or condition.get("uploader_id") != self.actor_id
            or any(
                not isinstance(condition.get(key), str) or not condition[key].strip()
                for key in ("upload_ref", "origin_ref")
            )
            or not isinstance(classes, (list, tuple))
            or not all(isinstance(item, str) and item.strip() for item in classes)
            or len(classes) != len(set(classes))
            or set(classes) != {rule.data_class for rule in grant.data_rules}
            or draft.parameters.model_dump() != {"import_ref": condition.get("upload_ref")}
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        return CapabilityEvaluationRequest(
            user_id=self.user_id,
            project_name=self.project_name,
            actor_id=self.actor_id,
            grant_id=grant.grant_id,
            grant_version=grant.grant_version,
            grant_digest=grant.grant_digest,
            source_kind=draft.source_kind,
            operation=draft.operation,
            purpose=draft.intent,
            account_binding_digest=grant.account_binding_digest,
        )

    async def declare_query(self, command: DeclareSourceQuery) -> QueryReceipt:
        command = DeclareSourceQuery.model_validate(command.model_dump())
        context, draft = command.context, command.draft
        self._scope(context)
        request_digest = digest_command_request("declare_query", context, command)
        replay = await self._query_replay(context, request_digest)
        if replay is not None:
            return replay
        try:
            grant, evaluation = await self._resolve(command)
            capability_request = self._manual_authority(command, grant)
        except OpportunityError:
            replay = await self._query_replay(context, request_digest)
            if replay is not None:
                return replay
            raise
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=context, operation="declare_query")
            replay = await tx.receipts.get_query(context=context, request_digest=request_digest)
            if replay is not None:
                return verified_query_receipt(replay, context, request_digest)
            policy = await tx.creative_policy_identity()
            await tx.capabilities.consume(grant, evaluation, actor_id=self.actor_id)
            profile_head = await tx.profiles.get_head_for_update(
                user_id=self.user_id, project_name=self.project_name, profile_id=draft.cohort_profile_id
            )
            profile = await tx.profiles.get_exact(
                user_id=self.user_id,
                project_name=self.project_name,
                profile_id=draft.cohort_profile_id,
                revision=draft.cohort_profile_revision,
            )
            if profile is None or profile_head is None:
                raise OpportunityError(StopCode.M9_COHORT_LEAKAGE)
            profile = verified_profile(profile)
            payload = profile.payload
            if (
                profile.profile_id,
                profile.revision,
                profile.profile_digest,
                profile_head.current_revision,
                payload.cohort_id,
                payload.cohort_version,
            ) != (
                draft.cohort_profile_id,
                draft.cohort_profile_revision,
                draft.cohort_profile_digest,
                draft.cohort_profile_revision,
                draft.cohort_id,
                draft.cohort_version,
            ) or (
                payload.creative_profile_id,
                payload.creative_profile_version,
                payload.creative_policy_pack_digest,
            ) != policy:
                raise OpportunityError(StopCode.M9_COHORT_LEAKAGE)
            rules = tuple(rule for rule in payload.source_rules if rule.source_kind == draft.source_kind)
            if (
                len(rules) != 1
                or draft.intent not in rules[0].allowed_intents
                or ({rule.data_class for rule in grant.data_rules} - set(rules[0].allowed_data_classes))
            ):
                raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
            old = await tx.queries.get_head(command.query_id)
            if old is None:
                if command.parent_revision is not None or command.expected_head_version is not None:
                    raise OpportunityError(StopCode.M9_STALE_HEAD)
                revision, version = 1, 1
            else:
                if (command.parent_revision, command.expected_head_version) != (old.current_revision, old.head_version):
                    raise OpportunityError(StopCode.M9_STALE_HEAD)
                revision, version = old.current_revision + 1, old.head_version + 1
            now = await tx.profiles.database_time()
            validate_capability(grant, evaluation, capability_request, now=now)
            query = SourceQuery.model_validate(
                {
                    **draft.model_dump(),
                    "query_id": command.query_id,
                    "revision": revision,
                    "parent_revision": command.parent_revision,
                    "user_id": self.user_id,
                    "project_name": self.project_name,
                    "query_digest": "sha256:" + "0" * 64,
                    "created_by": self.actor_id,
                    "created_at": now,
                }
            )
            query = query.model_copy(update={"query_digest": digest_source_query(query)})
            head = SourceQueryHead(query_id=query.query_id, current_revision=revision, head_version=version)
            receipt = QueryReceipt(
                command_id=context.command_id,
                request_digest=request_digest,
                query=query,
                head=head,
                result_digest="sha256:" + "0" * 64,
                committed_at=now,
            )
            receipt = receipt.model_copy(
                update={"result_digest": digest_command_result("declare_query", request_digest, receipt)}
            )
            await tx.queries.append(query)
            await tx.queries.stage_head(head, expected_head_version=command.expected_head_version)
            await tx.stage_query_event(query=query, committed_at=now)
            await tx.receipts.stage_query(context=context, receipt=receipt)
            return receipt

    async def _acquisition_preflight(
        self, command: AcquireSourceQuery, request_digest: str
    ) -> tuple[AcquisitionReceipt | None, SourceQuery | None]:
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            replay = await tx.receipts.current_acquisition(context=command.context, request_digest=request_digest)
            if replay is not None:
                return verified_acquisition_receipt(replay, command.context, request_digest), None
            declaration = await tx.receipts.get_query_for_revision(command.query_id, command.query_revision)
            if declaration is None or declaration.query.query_digest != command.query_digest:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            return None, declaration.query

    async def _admit_acquisition(
        self,
        tx: AcquisitionTransactionPort,
        command: AcquireSourceQuery,
        query: SourceQuery,
        grant: SourceCapabilityGrant,
        evaluation: EffectiveCapabilityEvaluation,
    ) -> datetime:
        policy = await tx.creative_policy_identity()
        await tx.capabilities.consume(grant, evaluation, actor_id=self.actor_id)
        head = await tx.profiles.get_head_for_update(
            user_id=self.user_id,
            project_name=self.project_name,
            profile_id=query.cohort_profile_id,
        )
        profile = await tx.profiles.get_exact(
            user_id=self.user_id,
            project_name=self.project_name,
            profile_id=query.cohort_profile_id,
            revision=query.cohort_profile_revision,
        )
        if profile is None or head is None:
            raise OpportunityError(StopCode.M9_COHORT_LEAKAGE)
        profile = verified_profile(profile)
        payload = profile.payload
        if (
            profile.revision,
            profile.profile_digest,
            head.current_revision,
            payload.cohort_id,
            payload.cohort_version,
            payload.creative_profile_id,
            payload.creative_profile_version,
            payload.creative_policy_pack_digest,
        ) != (
            query.cohort_profile_revision,
            query.cohort_profile_digest,
            query.cohort_profile_revision,
            query.cohort_id,
            query.cohort_version,
            *policy,
        ):
            raise OpportunityError(StopCode.M9_COHORT_LEAKAGE)
        rules = tuple(r for r in payload.source_rules if r.source_kind == query.source_kind)
        if (
            len(rules) != 1
            or query.intent not in rules[0].allowed_intents
            or ({r.data_class for r in grant.data_rules} - set(rules[0].allowed_data_classes))
        ):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        query_head = await tx.queries.get_head(query.query_id)
        declaration = await tx.receipts.get_query_for_revision(query.query_id, query.revision)
        if declaration is None or declaration.query != query:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        if query_head is None or (query_head.current_revision, query_head.head_version) != (
            command.query_revision,
            command.expected_query_head_version,
        ):
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        now = await tx.profiles.database_time()
        validate_capability(grant, evaluation, self._manual_authority(query, grant), now=now)
        return now

    async def _current_acquisition(self, command: AcquireSourceQuery, request_digest: str) -> AcquisitionReceipt:
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            receipt = await tx.receipts.current_acquisition(context=command.context, request_digest=request_digest)
            if receipt is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            return verified_acquisition_receipt(receipt, command.context, request_digest)

    async def acquire(self, command: AcquireSourceQuery) -> AcquisitionReceipt:
        command = AcquireSourceQuery.model_validate(command.model_dump())
        self._scope(command.context)
        request_digest = digest_command_request("acquire", command.context, command)
        try:
            return await self._acquire_command(command)
        except OpportunityError:
            replay, _query = await self._acquisition_preflight(command, request_digest)
            if replay is not None:
                return replay
            raise
        except Exception:
            try:
                return await self._current_acquisition(command, request_digest)
            except Exception:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _acquire_command(self, command: AcquireSourceQuery) -> AcquisitionReceipt:
        command = AcquireSourceQuery.model_validate(command.model_dump())
        self._scope(command.context)
        request_digest = digest_command_request("acquire", command.context, command)
        replay, query = await self._acquisition_preflight(command, request_digest)
        if replay is not None:
            return replay
        if query is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        grant, evaluation = await self._resolve(query)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            replay = await tx.receipts.current_acquisition(context=command.context, request_digest=request_digest)
            if replay is not None:
                return verified_acquisition_receipt(replay, command.context, request_digest)
            await self._admit_acquisition(tx, command, query, grant, evaluation)
            attempt, created = await tx.attempts.prepare(
                AcquisitionAttempt(
                    attempt_id=self._new_id(),
                    attempt_version=1,
                    user_id=self.user_id,
                    project_name=self.project_name,
                    actor_id=self.actor_id,
                    command_id=command.context.command_id,
                    request_digest=request_digest,
                    query_id=query.query_id,
                    query_revision=query.revision,
                    query_digest=query.query_digest,
                    page_cursor_digest=None,
                    state=AttemptState.PLANNED,
                    adapter_version="manual-import.v1",
                    started_at=None,
                    completed_at=None,
                    provider_request_id=None,
                    outcome_reason=None,
                )
            )
            if not created:
                raise OpportunityError(StopCode.M9_STALE_HEAD)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            await self._admit_acquisition(tx, command, query, grant, evaluation)
            attempt = await tx.attempts.transition(
                attempt.attempt_id,
                expected_version=attempt.attempt_version,
                state=AttemptState.RUNNING,
            )
        try:
            return await self._capture_manual(command, request_digest, query, attempt, grant, evaluation)
        except OpportunityError as error:
            reason = (
                AttemptOutcomeReason.CAPABILITY_EXPIRED
                if error.code == StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE
                else AttemptOutcomeReason.POLICY_FORBIDDEN
            )
            return await self._fail_running(command, request_digest, query, attempt, reason)

    async def _fail_running(
        self,
        command: AcquireSourceQuery,
        request_digest: str,
        query: SourceQuery,
        attempt: AcquisitionAttempt,
        reason: AttemptOutcomeReason,
    ) -> AcquisitionReceipt:
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            replay = await tx.receipts.current_acquisition(context=command.context, request_digest=request_digest)
            if replay is not None and replay.state != AttemptState.RUNNING:
                return verified_acquisition_receipt(replay, command.context, request_digest)
            current = await tx.attempts.get_exact(attempt.attempt_id)
            if current is None or current.attempt_version != attempt.attempt_version or current.started_at is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            checkpoints = await tx.pages.list_for_attempt(attempt.attempt_id)
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
                source_identity_refs=tuple({ref for c in checkpoints for ref in c.source_identity_refs}),
                pages=tuple(c.page for c in checkpoints),
                coverage_state=CoverageState.PARTIAL,
                requested_record_limit=query.max_records,
                returned_record_count=sum(c.page.record_count for c in checkpoints),
                coverage_note=reason.value,
                provider_observed_at=checkpoints[-1].provider_observed_at if checkpoints else None,
                capture_started_at=current.started_at,
                capture_completed_at=now,
                adapter_version=attempt.adapter_version,
                capability_grant_digest=query.capability_grant_digest,
                capability_evaluation_digest=query.capability_evaluation_digest,
                snapshot_digest="sha256:" + "0" * 64,
                created_at=now,
            )
            snapshot = snapshot.model_copy(update={"snapshot_digest": digest_source_snapshot(snapshot)})
            await tx.snapshots.append(snapshot)
            return await self._finish_acquisition(tx, command, request_digest, attempt, snapshot, reason)

    async def _capture_manual(
        self,
        command: AcquireSourceQuery,
        request_digest: str,
        query: SourceQuery,
        attempt: AcquisitionAttempt,
        grant: SourceCapabilityGrant,
        evaluation: EffectiveCapabilityEvaluation,
    ) -> AcquisitionReceipt:
        source, evidence = self.source, self.evidence
        if source is None or evidence is None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        grant, evaluation = await self._resolve(query)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            await self._admit_acquisition(tx, command, query, grant, evaluation)
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
        try:
            page = await source.fetch_page(request)
            page = SourcePageResult.model_validate(page.model_dump())
        except OpportunityError as error:
            if error.code != StopCode.M9_ACQUISITION_OUTCOME_UNKNOWN:
                raise
            return await self._mark_outcome_unknown(command, request_digest, attempt)
        except Exception:
            return await self._mark_outcome_unknown(command, request_digest, attempt)
        if (
            not page.terminal_page
            or page.next_cursor is not None
            or page.returned_record_count > query.max_records
            or (page.quota_units_observed is not None and page.quota_units_observed > query.max_quota_units)
        ):
            raise OpportunityError(StopCode.M9_OPERATIONAL_ENVELOPE_EXCEEDED)
        if page.provider_request_id != query.parameters.model_dump().get("import_ref"):
            raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
        grant, evaluation = await self._resolve(query)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            await self._admit_acquisition(tx, command, query, grant, evaluation)
        materials = await materialize_manual_page(request, page, grant, evidence)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            now = await self._admit_acquisition(tx, command, query, grant, evaluation)
            checkpoint = PageCheckpoint(
                page=SnapshotPage(
                    ordinal=1,
                    request_cursor_digest=None,
                    response_cursor_digest=None,
                    provider_request_id=page.provider_request_id,
                    payload_ref=materials.raw.payload_ref,
                    payload_integrity_ref=materials.raw.payload_integrity_ref,
                    retained_source_payload_digest=materials.raw.retained_content_digest,
                    raw_media_type=page.raw_media_type,
                    raw_size_bytes=materials.raw.raw_size_bytes,
                    data_classes=page.data_classes,
                    data_class_clocks=page_clocks(page, grant, captured_at=now),
                    record_count=page.returned_record_count,
                    captured_at=now,
                    missing_reason=None,
                ),
                source_identity_refs=materials.raw.source_identity_refs,
                native_fields=materials.fields,
                quota_units_observed=page.quota_units_observed,
                next_cursor_ref=None,
                next_cursor_integrity_ref=None,
                terminal_page=True,
                provider_observed_at=page.provider_observed_at,
            )
            await tx.pages.append(attempt.attempt_id, checkpoint, expected_attempt_version=attempt.attempt_version)
        return await self._finalize_manual(command, request_digest, query, attempt, checkpoint)

    async def _mark_outcome_unknown(
        self,
        command: AcquireSourceQuery,
        request_digest: str,
        attempt: AcquisitionAttempt,
    ) -> AcquisitionReceipt:
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            await tx.attempts.transition(
                attempt.attempt_id,
                expected_version=attempt.attempt_version,
                state=AttemptState.OUTCOME_UNKNOWN,
                reason=AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
            )
        return await self._current_acquisition(command, request_digest)

    async def _finalize_manual(
        self,
        command: AcquireSourceQuery,
        request_digest: str,
        query: SourceQuery,
        attempt: AcquisitionAttempt,
        checkpoint: PageCheckpoint,
    ) -> AcquisitionReceipt:
        evidence = self.evidence
        if evidence is None or checkpoint.page.payload_ref is None or checkpoint.page.payload_integrity_ref is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        grant, evaluation = await self._resolve(query)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            now = await self._admit_acquisition(tx, command, query, grant, evaluation)
            require_clocks_current(checkpoint.page.data_class_clocks, now=now, operational=True)
        await evidence.verify_and_read(checkpoint.page.payload_ref, checkpoint.page.payload_integrity_ref)
        for field in checkpoint.native_fields:
            await evidence.verify_and_read(field.material_ref, field.material_integrity_ref)
        grant, evaluation = await self._resolve(query)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            now = await self._admit_acquisition(tx, command, query, grant, evaluation)
            current = await tx.receipts.current_acquisition(context=command.context, request_digest=request_digest)
            if current is not None and current.state != AttemptState.RUNNING:
                return verified_acquisition_receipt(current, command.context, request_digest)
            checkpoints = await tx.pages.list_for_attempt(attempt.attempt_id)
            if len(checkpoints) != 1 or checkpoints[0] != checkpoint or attempt.started_at is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            require_clocks_current(checkpoint.page.data_class_clocks, now=now, operational=True)
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
                coverage_note="complete-manual-upload",
                provider_observed_at=checkpoint.provider_observed_at,
                capture_started_at=attempt.started_at,
                capture_completed_at=now,
                adapter_version=attempt.adapter_version,
                capability_grant_digest=query.capability_grant_digest,
                capability_evaluation_digest=query.capability_evaluation_digest,
                snapshot_digest="sha256:" + "0" * 64,
                created_at=now,
            )
            snapshot = snapshot.model_copy(update={"snapshot_digest": digest_source_snapshot(snapshot)})
            await tx.snapshots.append(snapshot)
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
                        "observed_at": checkpoint.page.captured_at,
                    }
                )
                observation = observation.model_copy(
                    update={"observation_digest": digest_source_observation(observation)}
                )
                await tx.observations.append(observation, expected_head_version=None)
            return await self._finish_acquisition(
                tx,
                command,
                request_digest,
                attempt,
                snapshot,
                AttemptOutcomeReason.COMPLETED,
            )

    async def reconcile_manual_checkpoint(self, command: AcquireSourceQuery) -> AcquisitionReceipt:
        """Host recovery of a verified response; never start another source call."""
        command = AcquireSourceQuery.model_validate(command.model_dump())
        self._scope(command.context)
        request_digest = digest_command_request("acquire", command.context, command)
        async with self.store.transaction() as tx:
            await tx.profiles.lock_command_key(context=command.context, operation="acquire")
            current = await tx.receipts.current_acquisition(context=command.context, request_digest=request_digest)
            if current is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            if current.state != AttemptState.RUNNING:
                return verified_acquisition_receipt(current, command.context, request_digest)
            attempt = await tx.attempts.get_exact(current.attempt_id)
            declaration = await tx.receipts.get_query_for_revision(command.query_id, command.query_revision)
            checkpoints = await tx.pages.list_for_attempt(current.attempt_id)
            if not checkpoints:
                return current
            if attempt is None or declaration is None or len(checkpoints) != 1:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            query, checkpoint = declaration.query, checkpoints[0]
            if (
                query.query_digest != command.query_digest
                or query.source_kind != "manual-import"
                or query.source_contract_version != "manual-import.v1"
                or not checkpoint.terminal_page
                or checkpoint.page.provider_request_id != query.parameters.model_dump().get("import_ref")
            ):
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        try:
            grant, evaluation = await self._resolve(query)
            async with self.store.transaction() as tx:
                await tx.profiles.lock_command_key(context=command.context, operation="acquire")
                now = await self._admit_acquisition(tx, command, query, grant, evaluation)
                require_clocks_current(checkpoint.page.data_class_clocks, now=now, operational=True)
            evidence = self.evidence
            page = checkpoint.page
            if (
                evidence is None
                or page.payload_ref is None
                or page.payload_integrity_ref is None
                or page.raw_media_type is None
            ):
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            raw = await evidence.verify_and_read(page.payload_ref, page.payload_integrity_ref)
            _, drafts = decode_manual_payload(raw)
            response = SourcePageResult(
                provider_request_id=page.provider_request_id,
                next_cursor=None,
                raw_payload=raw,
                raw_media_type=page.raw_media_type,
                source_native_ids=tuple({str(d["source_native_id"]) for d in drafts}),
                data_classes=page.data_classes,
                returned_record_count=page.record_count,
                quota_units_observed=checkpoint.quota_units_observed,
                provider_observed_at=checkpoint.provider_observed_at,
                terminal_page=True,
            )
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
            materials = await materialize_manual_page(request, response, grant, evidence)
            if materials.fields != checkpoint.native_fields or materials.raw != PayloadRef(
                payload_ref=page.payload_ref,
                payload_integrity_ref=page.payload_integrity_ref,
                source_identity_refs=checkpoint.source_identity_refs,
                retained_content_digest=page.retained_source_payload_digest,
                raw_size_bytes=page.raw_size_bytes,
            ):
                raise OpportunityError(StopCode.M9_RAW_DIGEST_MISMATCH)
            return await self._finalize_manual(command, request_digest, query, attempt, checkpoint)
        except OpportunityError:
            return await self._fail_running(
                command, request_digest, query, attempt, AttemptOutcomeReason.POLICY_FORBIDDEN
            )
        except Exception:
            try:
                return await self._current_acquisition(command, request_digest)
            except Exception:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _finish_acquisition(
        self,
        tx: AcquisitionTransactionPort,
        command: AcquireSourceQuery,
        request_digest: str,
        attempt: AcquisitionAttempt,
        snapshot: SourceSnapshot,
        reason: AttemptOutcomeReason,
    ) -> AcquisitionReceipt:
        attempt = await tx.attempts.transition(
            attempt.attempt_id,
            expected_version=attempt.attempt_version,
            state=AttemptState.SUCCEEDED if reason == AttemptOutcomeReason.COMPLETED else AttemptState.FAILED,
            reason=reason,
        )
        if attempt.completed_at is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        receipt = AcquisitionReceipt(
            command_id=command.context.command_id,
            request_digest=request_digest,
            attempt_id=attempt.attempt_id,
            attempt_version=attempt.attempt_version,
            state=attempt.state,
            snapshot_ids=(snapshot.snapshot_id,),
            snapshot_digests=(snapshot.snapshot_digest,),
            result_digest="sha256:" + "0" * 64,
            committed_at=attempt.completed_at,
        )
        receipt = receipt.model_copy(
            update={"result_digest": digest_command_result("acquire", request_digest, receipt)}
        )
        await tx.stage_snapshot_event(snapshot=snapshot, committed_at=attempt.completed_at)
        await tx.receipts.stage_acquisition(context=command.context, receipt=receipt)
        return receipt
