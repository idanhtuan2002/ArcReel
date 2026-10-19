"""Verified immutable source-query evidence for the acquisition application."""

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from r2.contracts.opportunity import (
    AcquisitionReceipt,
    CapabilityEvaluationRequest,
    CommandContext,
    DeclareSourceQuery,
    EffectiveCapabilityEvaluation,
    M9ContractModel,
    OpportunityCohortProfile,
    OpportunityCohortProfileHead,
    QueryReceipt,
    SnapshotPage,
    SourceCapabilityGrant,
    SourceQuery,
    SourceQueryHead,
)
from r2.opportunity.capabilities import validate_capability
from r2.opportunity.digests import digest_command_request, digest_command_result, digest_source_query
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.ports import MarketSourcePort, SnapshotEvidenceStore, SourceCapabilityPort
from r2.opportunity.profiles import verified_profile


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


class AcquisitionTransactionPort(Protocol):
    @property
    def profiles(self) -> AcquisitionProfileReadPort: ...
    @property
    def queries(self) -> AcquisitionQueryPort: ...
    @property
    def capabilities(self) -> ConsumedCapabilityPort: ...
    @property
    def receipts(self) -> AcquisitionReceiptPort: ...
    async def creative_policy_identity(self) -> tuple[str, str, str]: ...
    async def stage_query_event(self, *, query: SourceQuery, committed_at: datetime) -> None: ...


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
        user_id: str,
        project_name: str,
        actor_id: str,
    ) -> None:
        self.store, self.capabilities, self.source, self.evidence = store, capabilities, source, evidence
        self.user_id, self.project_name, self.actor_id = user_id, project_name, actor_id

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
        self, command: DeclareSourceQuery
    ) -> tuple[SourceCapabilityGrant, EffectiveCapabilityEvaluation]:
        draft = command.draft
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
        self, command: DeclareSourceQuery, grant: SourceCapabilityGrant
    ) -> CapabilityEvaluationRequest:
        draft = command.draft
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
