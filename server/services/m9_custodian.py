"""Host-owned durable Human publication leases over the activated Showrunner reader."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantEventModel
from lib.db.models.host_custodian import HostCustodianLeaseModel
from lib.db.repositories.opportunity import OpportunityProfileRepository
from r2.advanced_creative.exploration import uuid7
from r2.contracts.opportunity import CommandContext, CustodianAuthorizationLease, ProfilePublicationSubject
from r2.governance.grant_signature import verify_grant_event
from r2.governance.grant_transition import GrantScopeV1
from r2.opportunity.digests import digest_profile_publication_subject
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.profiles import CUSTODIAN_POLICY_ID, CUSTODIAN_POLICY_VERSION, OPERATION
from server.services.governance_grants import CurrentShowrunnerGrantReader, ShowrunnerGrantUnavailableError


def _denied() -> OpportunityError:
    return OpportunityError(StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED)


class M9ProfileCustodian:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        grants: CurrentShowrunnerGrantReader | None,
        user_id: str,
        project_name: str,
        actor_id: str,
        clock: Callable[[], datetime] | None = None,
        id_source: Callable[[], str] = uuid7,
    ) -> None:
        self.sessions, self.grants = sessions, grants
        self.user_id, self.project_name, self.actor_id = user_id, project_name, actor_id
        self.clock, self.id_source = clock, id_source

    async def now(self, repo: OpportunityProfileRepository) -> datetime:
        value = self.clock() if self.clock is not None else await repo.database_time()
        if value.tzinfo is None:
            raise _denied()
        return value.astimezone(UTC)

    async def verify_retained_grant(self, session: AsyncSession, lease: CustodianAuthorizationLease) -> None:
        # A bounded lease keeps its original authorization after later revocation.
        # Its retained ISSUE proof is verified without issuing or renewing any grant.
        if self.grants is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        row = (
            await session.execute(
                select(ShowrunnerGrantEventModel)
                .where(
                    ShowrunnerGrantEventModel.user_id == self.user_id,
                    ShowrunnerGrantEventModel.project_name == self.project_name,
                    ShowrunnerGrantEventModel.principal == self.actor_id,
                    ShowrunnerGrantEventModel.event_digest == lease.custodian_evidence_digest,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise _denied()
        try:
            event = verify_grant_event(row.raw_event, key_id=self.grants.key_id, public_key=self.grants.public_key)
            body = event.body
            expected = (
                body.user_id,
                body.project_name,
                body.principal,
                body.sequence,
                body.event_type,
                body.issued_at,
                body.signer_key_id,
                event.event_digest,
            )
            actual = (
                row.user_id,
                row.project_name,
                row.principal,
                row.sequence,
                row.event_type,
                row.issued_at,
                row.signer_key_id,
                row.event_digest,
            )
            if (
                expected != actual
                or body.event_type != "ISSUE"
                or body.role != "HUMAN_SHOWRUNNER"
                or body.not_before is None
                or body.expires_at is None
            ):
                raise ValueError("retained grant proof mismatch")
            if not (
                row.imported_at <= lease.issued_at
                and datetime.fromisoformat(body.not_before) <= lease.issued_at < datetime.fromisoformat(body.expires_at)
            ):
                raise ValueError("retained grant was not active when the lease was issued")
            if lease.admit_not_after > datetime.fromisoformat(body.expires_at):
                raise ValueError("lease exceeds grant expiry")
        except ValueError:
            raise _denied() from None

    async def authorize_publication(
        self, command_id: str, subject: ProfilePublicationSubject
    ) -> CustodianAuthorizationLease:
        if (subject.user_id, subject.project_name, subject.actor_id) != (
            self.user_id,
            self.project_name,
            self.actor_id,
        ):
            raise _denied()
        if self.grants is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        context = CommandContext(
            command_id=command_id, user_id=self.user_id, project_name=self.project_name, actor_id=self.actor_id
        )
        subject_digest = digest_profile_publication_subject(subject)
        async with self.sessions() as session, session.begin():
            repo = OpportunityProfileRepository(session)
            await repo.lock_command_key(context=context, operation=OPERATION)
            row = (
                await session.execute(
                    select(HostCustodianLeaseModel)
                    .where(
                        HostCustodianLeaseModel.user_id == self.user_id,
                        HostCustodianLeaseModel.project_name == self.project_name,
                        HostCustodianLeaseModel.actor_id == self.actor_id,
                        HostCustodianLeaseModel.operation == OPERATION,
                        HostCustodianLeaseModel.command_id == command_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if row is not None:
                try:
                    lease = CustodianAuthorizationLease(
                        authorization_id=row.authorization_id,
                        command_id=row.command_id,
                        authorized=True,
                        subject_digest=row.subject_digest,
                        custodian_policy_id=row.policy_id,
                        custodian_policy_version=row.policy_version,
                        custodian_evidence_digest=row.grant_event_digest,
                        issued_at=row.issued_at,
                        admit_not_after=row.admit_not_after,
                    )
                except ValidationError:
                    raise _denied() from None
                now = await self.now(repo)
                if (
                    lease.subject_digest != subject_digest
                    or lease.custodian_policy_id != CUSTODIAN_POLICY_ID
                    or lease.custodian_policy_version != CUSTODIAN_POLICY_VERSION
                    or not lease.issued_at <= now <= lease.admit_not_after
                ):
                    raise _denied()
                await self.verify_retained_grant(session, lease)
                return lease
            try:
                event = await self.grants.require_current_locked(
                    session, scope=GrantScopeV1(self.user_id, self.project_name, self.actor_id)
                )
            except ShowrunnerGrantUnavailableError:
                raise _denied() from None
            now = await self.now(repo)
            if event.body.role != "HUMAN_SHOWRUNNER" or event.body.expires_at is None or event.body.not_before is None:
                raise _denied()
            deadline = min(now + timedelta(seconds=30), datetime.fromisoformat(event.body.expires_at))
            if now < datetime.fromisoformat(event.body.not_before) or deadline <= now:
                raise _denied()
            lease = CustodianAuthorizationLease(
                authorization_id=self.id_source(),
                command_id=command_id,
                authorized=True,
                subject_digest=subject_digest,
                custodian_policy_id=CUSTODIAN_POLICY_ID,
                custodian_policy_version=CUSTODIAN_POLICY_VERSION,
                custodian_evidence_digest=event.event_digest,
                issued_at=now,
                admit_not_after=deadline,
            )
            session.add(
                HostCustodianLeaseModel(
                    authorization_id=lease.authorization_id,
                    user_id=self.user_id,
                    project_name=self.project_name,
                    actor_id=self.actor_id,
                    operation=OPERATION,
                    command_id=command_id,
                    subject_digest=subject_digest,
                    policy_id=lease.custodian_policy_id,
                    policy_version=lease.custodian_policy_version,
                    grant_event_digest=lease.custodian_evidence_digest,
                    issued_at=lease.issued_at,
                    admit_not_after=lease.admit_not_after,
                )
            )
            await session.flush()
            return lease
