"""Scoped immutable profile persistence; only the unit of work owns a transaction."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import and_, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.opportunity import M9CohortProfileModel, M9CommandReceiptModel, M9EventModel, M9ProfileHeadModel
from r2.contracts.opportunity import (
    CohortProfileReceipt,
    CommandContext,
    OpportunityCohortProfile,
    OpportunityCohortProfileHead,
)
from r2.opportunity.digests import (
    command_guard_key,
    digest_cohort_profile,
    digest_cohort_profile_payload,
    digest_command_result,
)
from r2.opportunity.errors import OpportunityError, StopCode

type GuardKey = Callable[[str, CommandContext], tuple[int, int]]


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


def _profile(row: M9CohortProfileModel) -> OpportunityCohortProfile:
    try:
        body = {name: getattr(row, name) for name in OpportunityCohortProfile.model_fields if name != "payload"}
        result = OpportunityCohortProfile.model_validate({**body, "payload": row.payload_json})
    except (ValidationError, ValueError):
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
    return verified_profile(result)


class OpportunityProfileRepository:
    def __init__(self, session: AsyncSession, *, guard_key: GuardKey = command_guard_key) -> None:
        self.session = session
        self.guard_key = guard_key

    async def lock_command_key(self, *, context: CommandContext, operation: str) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        first, second = self.guard_key(operation, context)
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:first, :second)"), {"first": first, "second": second}
        )

    async def database_time(self) -> datetime:
        value = await self.session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        return value.astimezone(UTC)

    async def get_exact(
        self, *, user_id: str, project_name: str, profile_id: str, revision: int
    ) -> OpportunityCohortProfile | None:
        statement = (
            select(M9CohortProfileModel)
            .where(
                M9CohortProfileModel.user_id == user_id,
                M9CohortProfileModel.project_name == project_name,
                M9CohortProfileModel.profile_id == profile_id,
                M9CohortProfileModel.revision == revision,
            )
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(statement)).scalar_one_or_none()
        return None if row is None else _profile(row)

    async def get_head_for_update(
        self, *, user_id: str, project_name: str, profile_id: str
    ) -> OpportunityCohortProfileHead | None:
        statement = (
            select(M9ProfileHeadModel)
            .where(
                M9ProfileHeadModel.user_id == user_id,
                M9ProfileHeadModel.project_name == project_name,
                M9ProfileHeadModel.profile_id == profile_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        return OpportunityCohortProfileHead(
            profile_id=row.profile_id, current_revision=row.current_revision, head_version=row.head_version
        )

    async def list_heads(
        self, *, user_id: str, project_name: str, after_id: str | None, limit: int
    ) -> tuple[OpportunityCohortProfile, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("profile page limit must be between one and one hundred")
        statement = (
            select(M9CohortProfileModel)
            .join(
                M9ProfileHeadModel,
                and_(
                    M9ProfileHeadModel.user_id == M9CohortProfileModel.user_id,
                    M9ProfileHeadModel.project_name == M9CohortProfileModel.project_name,
                    M9ProfileHeadModel.profile_id == M9CohortProfileModel.profile_id,
                    M9ProfileHeadModel.current_revision == M9CohortProfileModel.revision,
                ),
            )
            .where(M9CohortProfileModel.user_id == user_id, M9CohortProfileModel.project_name == project_name)
        )
        if after_id is not None:
            statement = statement.where(M9CohortProfileModel.profile_id > after_id)
        rows = (
            (
                await self.session.execute(
                    statement.order_by(M9CohortProfileModel.profile_id)
                    .limit(limit)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        return tuple(_profile(row) for row in rows)

    async def get_command_receipt(
        self, *, context: CommandContext, operation: str, request_digest: str
    ) -> CohortProfileReceipt | None:
        statement = (
            select(M9CommandReceiptModel)
            .where(
                M9CommandReceiptModel.user_id == context.user_id,
                M9CommandReceiptModel.actor_id == context.actor_id,
                M9CommandReceiptModel.operation == operation,
                M9CommandReceiptModel.command_id == context.command_id,
            )
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        if row.project_name != context.project_name or row.request_digest != request_digest:
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        if row.result_kind != "COHORT_PROFILE":
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        try:
            identity, revision, version = row.result_ref.split(":")
            profile = await self.get_exact(
                user_id=context.user_id, project_name=context.project_name, profile_id=identity, revision=int(revision)
            )
            if profile is None:
                raise ValueError("receipt profile is unavailable")
            receipt = CohortProfileReceipt(
                command_id=row.command_id,
                request_digest=row.request_digest,
                profile=profile,
                head=OpportunityCohortProfileHead(
                    profile_id=identity, current_revision=int(revision), head_version=int(version)
                ),
                result_digest=row.result_digest,
                committed_at=row.committed_at,
            )
            if digest_command_result(operation, request_digest, receipt) != row.result_digest:
                raise ValueError("receipt result integrity mismatch")
        except (ValidationError, ValueError):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
        return receipt

    async def stage_profile(self, profile: OpportunityCohortProfile) -> None:
        profile = verified_profile(profile)
        values = profile.model_dump(mode="python", exclude={"payload"})
        self.session.add(M9CohortProfileModel(**values, payload_json=profile.payload.model_dump(mode="json")))
        await self.flush()

    async def stage_head(
        self, *, user_id: str, project_name: str, head: OpportunityCohortProfileHead, expected_head_version: int | None
    ) -> None:
        if expected_head_version is None:
            if head.current_revision != 1 or head.head_version != 1:
                raise OpportunityError(StopCode.M9_STALE_HEAD)
            self.session.add(
                M9ProfileHeadModel(
                    user_id=user_id,
                    project_name=project_name,
                    profile_id=head.profile_id,
                    current_revision=1,
                    head_version=1,
                )
            )
            await self.flush()
            return
        if head.head_version != expected_head_version + 1:
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        result = await self.session.execute(
            update(M9ProfileHeadModel)
            .where(
                M9ProfileHeadModel.user_id == user_id,
                M9ProfileHeadModel.project_name == project_name,
                M9ProfileHeadModel.profile_id == head.profile_id,
                M9ProfileHeadModel.head_version == expected_head_version,
                M9ProfileHeadModel.current_revision == head.current_revision - 1,
            )
            .values(current_revision=head.current_revision, head_version=head.head_version)
            .returning(M9ProfileHeadModel.profile_id)
        )
        if result.scalar_one_or_none() is None:
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        await self.flush()

    async def stage_command_receipt(
        self, *, context: CommandContext, operation: str, receipt: CohortProfileReceipt
    ) -> None:
        if (receipt.profile.user_id, receipt.profile.project_name, receipt.command_id) != (
            context.user_id,
            context.project_name,
            context.command_id,
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        if digest_command_result(operation, receipt.request_digest, receipt) != receipt.result_digest:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        if (receipt.head.profile_id, receipt.head.current_revision) != (
            receipt.profile.profile_id,
            receipt.profile.revision,
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        self.session.add(
            M9CommandReceiptModel(
                user_id=context.user_id,
                project_name=context.project_name,
                actor_id=context.actor_id,
                operation=operation,
                command_id=context.command_id,
                request_digest=receipt.request_digest,
                result_kind="COHORT_PROFILE",
                result_ref=f"{receipt.head.profile_id}:{receipt.head.current_revision}:{receipt.head.head_version}",
                result_digest=receipt.result_digest,
                committed_at=receipt.committed_at,
            )
        )
        await self.flush()

    async def stage_event(self, *, profile: OpportunityCohortProfile, committed_at: datetime) -> None:
        self.session.add(
            M9EventModel(
                user_id=profile.user_id,
                project_name=profile.project_name,
                event_kind="COHORT_PROFILE_PUBLISHED",
                aggregate_id=profile.profile_id,
                aggregate_revision=profile.revision,
                payload_digest=profile.profile_digest,
                committed_at=committed_at,
            )
        )
        await self.flush()

    async def flush(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError as error:
            code = (
                StopCode.M9_STALE_HEAD
                if getattr(error.orig, "sqlstate", None) == "23505"
                else StopCode.M9_REQUIRED_EVIDENCE_MISSING
            )
            raise OpportunityError(code) from None


class OpportunityUnitOfWork:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, guard_key: GuardKey = command_guard_key
    ) -> None:
        self.session_factory = session_factory
        self.guard_key = guard_key

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[OpportunityProfileRepository]:
        async with self.session_factory() as session:
            if session.get_bind().dialect.name != "postgresql":
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            async with session.begin():
                yield OpportunityProfileRepository(session, guard_key=self.guard_key)

    async def get_command_receipt(
        self, *, context: CommandContext, operation: str, request_digest: str
    ) -> CohortProfileReceipt | None:
        async with self.session_factory() as session:
            return await OpportunityProfileRepository(session, guard_key=self.guard_key).get_command_receipt(
                context=context, operation=operation, request_digest=request_digest
            )
