"""Typed scoped acquisition aggregates share one application-owned transaction."""

from __future__ import annotations

import struct
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.opportunity_acquisition import (
    M9CapabilityEvaluationModel,
    M9ConsumedCapabilityGrantModel,
    M9SourceQueryHeadModel,
    M9SourceQueryModel,
)
from lib.db.repositories.opportunity import GuardKey, OpportunityProfileRepository
from r2.advanced_creative.digests import digest_canonical
from r2.contracts.opportunity import EffectiveCapabilityEvaluation, SourceCapabilityGrant, SourceQuery, SourceQueryHead
from r2.opportunity.acquisition import verified_query
from r2.opportunity.digests import command_guard_key, digest_capability_evaluation, digest_capability_grant
from r2.opportunity.errors import OpportunityError, StopCode


async def _flush(session: AsyncSession) -> None:
    try:
        await session.flush()
    except SQLAlchemyError as error:
        code = (
            StopCode.M9_STALE_HEAD
            if isinstance(error, IntegrityError) and getattr(error.orig, "sqlstate", None) == "23505"
            else StopCode.M9_REQUIRED_EVIDENCE_MISSING
        )
        raise OpportunityError(code) from None


def _grant(row: M9ConsumedCapabilityGrantModel) -> SourceCapabilityGrant:
    try:
        value = SourceCapabilityGrant.model_validate(row.body_json)
        if digest_capability_grant(value) != value.grant_digest or any(
            getattr(row, name) != getattr(value, name)
            for name in ("user_id", "project_name", "grant_id", "grant_version", "grant_digest")
        ):
            raise ValueError("consumed grant integrity differs")
        return value
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None


def _evaluation(row: M9CapabilityEvaluationModel) -> EffectiveCapabilityEvaluation:
    try:
        value = EffectiveCapabilityEvaluation.model_validate(row.body_json)
        if digest_capability_evaluation(value, actor_id=row.actor_id) != value.evaluation_digest or any(
            getattr(row, name) != getattr(value, name)
            for name in ("user_id", "project_name", "evaluation_id", "grant_id", "grant_version", "evaluation_digest")
        ):
            raise ValueError("capability evaluation integrity differs")
        return value
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None


def _query(row: M9SourceQueryModel) -> SourceQuery:
    try:
        query = verified_query(SourceQuery.model_validate(row.body_json))
    except ValueError:
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
    if any(
        getattr(row, name) != getattr(query, name)
        for name in (
            "user_id",
            "project_name",
            "query_id",
            "revision",
            "parent_revision",
            "query_digest",
            "cohort_profile_id",
            "cohort_profile_revision",
            "capability_grant_id",
            "capability_grant_version",
            "capability_evaluation_id",
        )
    ):
        raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
    return query


class CapabilityEvidenceRepository:
    def __init__(self, session: AsyncSession, *, user_id: str, project_name: str) -> None:
        self.session, self.user_id, self.project_name = session, user_id, project_name

    async def get_grant(self, grant_id: str, version: int) -> SourceCapabilityGrant | None:
        row = await self.session.get(
            M9ConsumedCapabilityGrantModel, (self.user_id, self.project_name, grant_id, version), populate_existing=True
        )
        return None if row is None else _grant(row)

    async def get_evaluation(self, evaluation_id: str) -> EffectiveCapabilityEvaluation | None:
        row = await self.session.get(
            M9CapabilityEvaluationModel, (self.user_id, self.project_name, evaluation_id), populate_existing=True
        )
        return None if row is None else _evaluation(row)

    async def consume(
        self, grant: SourceCapabilityGrant, evaluation: EffectiveCapabilityEvaluation, *, actor_id: str
    ) -> None:
        if (grant.user_id, grant.project_name) != (self.user_id, self.project_name) or (
            evaluation.user_id,
            evaluation.project_name,
        ) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        if (
            digest_capability_grant(grant) != grant.grant_digest
            or digest_capability_evaluation(evaluation, actor_id=actor_id) != evaluation.evaluation_digest
            or (evaluation.grant_id, evaluation.grant_version, evaluation.grant_digest)
            != (grant.grant_id, grant.grant_version, grant.grant_digest)
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        if self.session.get_bind().dialect.name != "postgresql":
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        # Advisory guards cover absent immutable rows before INSERT; actual rows
        # and complete envelopes remain authority even when guard hashes collide.
        for identity in (("grant", grant.grant_id, str(grant.grant_version)), ("evaluation", evaluation.evaluation_id)):
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
        stored = await self.get_grant(grant.grant_id, grant.grant_version)
        if stored is None:
            self.session.add(
                M9ConsumedCapabilityGrantModel(
                    user_id=self.user_id,
                    project_name=self.project_name,
                    grant_id=grant.grant_id,
                    grant_version=grant.grant_version,
                    grant_digest=grant.grant_digest,
                    body_json=grant.model_dump(mode="json"),
                )
            )
            await _flush(self.session)
        elif stored != grant:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        existing = await self.get_evaluation(evaluation.evaluation_id)
        if existing is None:
            self.session.add(
                M9CapabilityEvaluationModel(
                    user_id=self.user_id,
                    project_name=self.project_name,
                    evaluation_id=evaluation.evaluation_id,
                    actor_id=actor_id,
                    grant_id=grant.grant_id,
                    grant_version=grant.grant_version,
                    evaluation_digest=evaluation.evaluation_digest,
                    body_json=evaluation.model_dump(mode="json"),
                )
            )
            await _flush(self.session)
        elif existing != evaluation:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)


class SourceQueryRepository:
    def __init__(self, session: AsyncSession, *, user_id: str, project_name: str) -> None:
        self.session, self.user_id, self.project_name = session, user_id, project_name

    async def get_exact(self, query_id: str, revision: int) -> SourceQuery | None:
        row = await self.session.get(
            M9SourceQueryModel, (self.user_id, self.project_name, query_id, revision), populate_existing=True
        )
        return None if row is None else _query(row)

    async def get_head(self, query_id: str) -> SourceQueryHead | None:
        row = (
            await self.session.execute(
                select(M9SourceQueryHeadModel)
                .where(
                    M9SourceQueryHeadModel.user_id == self.user_id,
                    M9SourceQueryHeadModel.project_name == self.project_name,
                    M9SourceQueryHeadModel.query_id == query_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return (
            None
            if row is None
            else SourceQueryHead(
                query_id=row.query_id, current_revision=row.current_revision, head_version=row.head_version
            )
        )

    async def append(self, query: SourceQuery) -> None:
        query = verified_query(query)
        if (query.user_id, query.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        self.session.add(
            M9SourceQueryModel(
                **{
                    name: getattr(query, name)
                    for name in (
                        "user_id",
                        "project_name",
                        "query_id",
                        "revision",
                        "parent_revision",
                        "query_digest",
                        "cohort_profile_id",
                        "cohort_profile_revision",
                        "capability_grant_id",
                        "capability_grant_version",
                        "capability_evaluation_id",
                    )
                },
                body_json=query.model_dump(mode="json"),
            )
        )
        await _flush(self.session)

    async def stage_head(self, head: SourceQueryHead, *, expected_head_version: int | None) -> None:
        if expected_head_version is None:
            if head.current_revision != 1 or head.head_version != 1:
                raise OpportunityError(StopCode.M9_STALE_HEAD)
            self.session.add(
                M9SourceQueryHeadModel(
                    user_id=self.user_id,
                    project_name=self.project_name,
                    query_id=head.query_id,
                    current_revision=1,
                    head_version=1,
                )
            )
        else:
            if head.head_version != expected_head_version + 1:
                raise OpportunityError(StopCode.M9_STALE_HEAD)
            result = await self.session.execute(
                update(M9SourceQueryHeadModel)
                .where(
                    M9SourceQueryHeadModel.user_id == self.user_id,
                    M9SourceQueryHeadModel.project_name == self.project_name,
                    M9SourceQueryHeadModel.query_id == head.query_id,
                    M9SourceQueryHeadModel.head_version == expected_head_version,
                    M9SourceQueryHeadModel.current_revision == head.current_revision - 1,
                )
                .values(current_revision=head.current_revision, head_version=head.head_version)
                .returning(M9SourceQueryHeadModel.query_id)
            )
            if result.scalar_one_or_none() is None:
                raise OpportunityError(StopCode.M9_STALE_HEAD)
        await _flush(self.session)


class AcquisitionTransaction:
    def __init__(
        self, session: AsyncSession, *, user_id: str, project_name: str, guard_key: GuardKey = command_guard_key
    ) -> None:
        self.session = session
        self.profiles = OpportunityProfileRepository(session, guard_key=guard_key)
        self.capabilities = CapabilityEvidenceRepository(session, user_id=user_id, project_name=project_name)
        self.queries = SourceQueryRepository(session, user_id=user_id, project_name=project_name)


class OpportunityAcquisitionUnitOfWork:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        user_id: str,
        project_name: str,
        guard_key: GuardKey = command_guard_key,
    ) -> None:
        self.sessions, self.user_id, self.project_name, self.guard_key = sessions, user_id, project_name, guard_key

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AcquisitionTransaction]:
        async with self.sessions() as session:
            if session.get_bind().dialect.name != "postgresql":
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            async with session.begin():
                yield AcquisitionTransaction(
                    session, user_id=self.user_id, project_name=self.project_name, guard_key=self.guard_key
                )
