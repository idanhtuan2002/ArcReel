"""Receipt-first Human-custodied cohort profile publication and scoped reads."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from pydantic import ValidationError

from r2.contracts.opportunity import (
    CohortProfileReceipt,
    CommandContext,
    CustodianAuthorizationLease,
    OpportunityCohortProfile,
    OpportunityCohortProfileHead,
    OpportunityIdentityRead,
    OpportunityReadPage,
    ProfilePublicationSubject,
    PublishOpportunityCohortProfile,
)
from r2.opportunity.digests import (
    digest_cohort_profile,
    digest_cohort_profile_payload,
    digest_command_request,
    digest_command_result,
    digest_profile_publication_subject,
)
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.ports import OpportunityProfileCustodianPort

OPERATION = "publish_cohort_profile"
CUSTODIAN_POLICY_ID = "arcreel.showrunner-grant"
CUSTODIAN_POLICY_VERSION = "governance.showrunner_grant_event.v1"


class OpportunityProfileNotFoundError(LookupError):
    pass


def verified_profile(profile: OpportunityCohortProfile) -> OpportunityCohortProfile:
    try:
        result = OpportunityCohortProfile.model_validate(profile.model_dump(mode="python"))
        if (
            digest_cohort_profile_payload(result.payload) != result.payload_digest
            or digest_cohort_profile(result) != result.profile_digest
        ):
            raise ValueError("profile integrity mismatch")
    except (ValidationError, ValueError):
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
    return result


class ProfileTransactionPort(Protocol):
    async def lock_command_key(self, *, context: CommandContext, operation: str) -> None: ...
    async def database_time(self) -> datetime: ...
    async def creative_policy_identity(self, *, user_id: str, project_name: str) -> tuple[str, str, str]: ...
    async def get_command_receipt(
        self, *, context: CommandContext, operation: str, request_digest: str
    ) -> CohortProfileReceipt | None: ...
    async def get_exact(
        self, *, user_id: str, project_name: str, profile_id: str, revision: int
    ) -> OpportunityCohortProfile | None: ...
    async def get_head_for_update(
        self, *, user_id: str, project_name: str, profile_id: str
    ) -> OpportunityCohortProfileHead | None: ...
    async def list_heads(
        self, *, user_id: str, project_name: str, after_id: str | None, limit: int
    ) -> tuple[OpportunityCohortProfile, ...]: ...
    async def stage_profile(self, profile: OpportunityCohortProfile) -> None: ...
    async def stage_head(
        self, *, user_id: str, project_name: str, head: OpportunityCohortProfileHead, expected_head_version: int | None
    ) -> None: ...
    async def stage_event(self, *, profile: OpportunityCohortProfile, committed_at: datetime) -> None: ...
    async def stage_command_receipt(
        self, *, context: CommandContext, operation: str, receipt: CohortProfileReceipt
    ) -> None: ...


class ProfileStorePort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[ProfileTransactionPort]: ...
    async def get_command_receipt(
        self, *, context: CommandContext, operation: str, request_digest: str
    ) -> CohortProfileReceipt | None: ...


def verified_receipt(
    receipt: CohortProfileReceipt, context: CommandContext, request_digest: str
) -> CohortProfileReceipt:
    try:
        receipt = CohortProfileReceipt.model_validate(receipt.model_dump(mode="python"))
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
    profile = verified_profile(receipt.profile)
    if (profile.user_id, profile.project_name, profile.created_by, receipt.command_id, receipt.request_digest) != (
        context.user_id,
        context.project_name,
        context.actor_id,
        context.command_id,
        request_digest,
    ) or (receipt.head.profile_id, receipt.head.current_revision) != (profile.profile_id, profile.revision):
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
    if digest_command_result(OPERATION, request_digest, receipt) != receipt.result_digest:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
    return receipt


class OpportunityProfileService:
    def __init__(
        self,
        *,
        store: ProfileStorePort,
        custodian: OpportunityProfileCustodianPort,
        user_id: str,
        project_name: str,
        actor_id: str,
    ) -> None:
        self.store, self.custodian = store, custodian
        self.user_id, self.project_name, self.actor_id = user_id, project_name, actor_id

    async def publish_cohort_profile(self, command: PublishOpportunityCohortProfile) -> CohortProfileReceipt:
        command = PublishOpportunityCohortProfile.model_validate(command.model_dump(mode="python"))
        context = command.context
        if (context.user_id, context.project_name, context.actor_id) != (
            self.user_id,
            self.project_name,
            self.actor_id,
        ):
            raise OpportunityError(StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED)
        request_digest = digest_command_request(OPERATION, context, command)
        replay = await self.store.get_command_receipt(
            context=context, operation=OPERATION, request_digest=request_digest
        )
        if replay is not None:
            return verified_receipt(replay, context, request_digest)
        payload_digest = digest_cohort_profile_payload(command.payload)
        subject = ProfilePublicationSubject(
            user_id=context.user_id,
            project_name=context.project_name,
            actor_id=context.actor_id,
            profile_id=command.profile_id,
            parent_revision=command.parent_revision,
            payload_digest=payload_digest,
        )
        try:
            lease = await self.custodian.authorize_publication(context.command_id, subject)
        except OpportunityError:
            replay = await self.store.get_command_receipt(
                context=context, operation=OPERATION, request_digest=request_digest
            )
            if replay is not None:
                return verified_receipt(replay, context, request_digest)
            raise
        async with self.store.transaction() as repo:
            await repo.lock_command_key(context=context, operation=OPERATION)
            replay = await repo.get_command_receipt(context=context, operation=OPERATION, request_digest=request_digest)
            if replay is not None:
                return verified_receipt(replay, context, request_digest)
            now = await repo.database_time()
            try:
                lease = CustodianAuthorizationLease.model_validate(lease.model_dump(mode="python"))
            except (ValidationError, ValueError):
                raise OpportunityError(StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED) from None
            if (
                not lease.authorized
                or lease.command_id != context.command_id
                or lease.subject_digest != digest_profile_publication_subject(subject)
                or lease.custodian_policy_id != CUSTODIAN_POLICY_ID
                or lease.custodian_policy_version != CUSTODIAN_POLICY_VERSION
                or not lease.issued_at <= now <= lease.admit_not_after
            ):
                raise OpportunityError(StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED)
            policy = await repo.creative_policy_identity(user_id=context.user_id, project_name=context.project_name)
            payload = command.payload
            if (
                payload.creative_profile_id,
                payload.creative_profile_version,
                payload.creative_policy_pack_digest,
            ) != policy:
                raise OpportunityError(StopCode.M9_COHORT_LEAKAGE)
            old = await repo.get_head_for_update(
                user_id=context.user_id, project_name=context.project_name, profile_id=command.profile_id
            )
            if old is None:
                if command.parent_revision is not None or command.expected_head_version is not None:
                    raise OpportunityError(StopCode.M9_STALE_HEAD)
                revision, head_version = 1, 1
            else:
                if (command.parent_revision, command.expected_head_version) != (old.current_revision, old.head_version):
                    raise OpportunityError(StopCode.M9_STALE_HEAD)
                revision, head_version = old.current_revision + 1, old.head_version + 1
            shell = OpportunityCohortProfile.model_construct(
                profile_id=command.profile_id,
                revision=revision,
                parent_revision=command.parent_revision,
                user_id=context.user_id,
                project_name=context.project_name,
                payload=payload,
                payload_digest=payload_digest,
                profile_digest="sha256:" + "0" * 64,
                created_by=context.actor_id,
                custodian_authorization_id=lease.authorization_id,
                custodian_policy_id=lease.custodian_policy_id,
                custodian_policy_version=lease.custodian_policy_version,
                custodian_evidence_digest=lease.custodian_evidence_digest,
                custodian_admitted_at=now,
                created_at=now,
            )
            profile = OpportunityCohortProfile.model_validate(
                {**shell.model_dump(mode="python"), "profile_digest": digest_cohort_profile(shell)}
            )
            head = OpportunityCohortProfileHead(
                profile_id=command.profile_id, current_revision=revision, head_version=head_version
            )
            receipt = CohortProfileReceipt(
                command_id=context.command_id,
                request_digest=request_digest,
                profile=profile,
                head=head,
                result_digest="sha256:" + "0" * 64,
                committed_at=now,
            )
            receipt = receipt.model_copy(
                update={"result_digest": digest_command_result(OPERATION, request_digest, receipt)}
            )
            await repo.stage_profile(profile)
            await repo.stage_head(
                user_id=context.user_id,
                project_name=context.project_name,
                head=head,
                expected_head_version=command.expected_head_version,
            )
            await repo.stage_event(profile=profile, committed_at=now)
            await repo.stage_command_receipt(context=context, operation=OPERATION, receipt=receipt)
            return receipt

    def require_read_scope(self, user_id: str, project_name: str) -> None:
        if (user_id, project_name) != (self.user_id, self.project_name):
            raise OpportunityProfileNotFoundError

    async def get_cohort_profile(self, request: OpportunityIdentityRead) -> OpportunityCohortProfile:
        self.require_read_scope(request.user_id, request.project_name)
        async with self.store.transaction() as repo:
            revision = request.revision
            if revision is None:
                head = await repo.get_head_for_update(
                    user_id=request.user_id, project_name=request.project_name, profile_id=request.identity
                )
                if head is None or head.profile_id != request.identity:
                    raise OpportunityProfileNotFoundError
                revision = head.current_revision
            profile = await repo.get_exact(
                user_id=request.user_id,
                project_name=request.project_name,
                profile_id=request.identity,
                revision=revision,
            )
            if profile is None or (profile.user_id, profile.project_name, profile.profile_id, profile.revision) != (
                request.user_id,
                request.project_name,
                request.identity,
                revision,
            ):
                raise OpportunityProfileNotFoundError
            return verified_profile(profile)

    async def list_cohort_profiles(self, request: OpportunityReadPage) -> tuple[OpportunityCohortProfile, ...]:
        self.require_read_scope(request.user_id, request.project_name)
        async with self.store.transaction() as repo:
            profiles: Sequence[OpportunityCohortProfile] = await repo.list_heads(
                user_id=request.user_id,
                project_name=request.project_name,
                after_id=request.after_id,
                limit=request.limit,
            )
            if any(
                (profile.user_id, profile.project_name) != (request.user_id, request.project_name)
                for profile in profiles
            ):
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            return tuple(verified_profile(profile) for profile in profiles)
