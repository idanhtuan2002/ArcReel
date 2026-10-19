"""Typed scoped acquisition aggregates share one application-owned transaction."""

from __future__ import annotations

import struct
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.opportunity import M9CommandReceiptModel, M9EventModel
from lib.db.models.opportunity_acquisition import (
    M9AcquisitionAttemptModel,
    M9CapabilityEvaluationModel,
    M9ConsumedCapabilityGrantModel,
    M9ObservationHeadModel,
    M9SnapshotPageModel,
    M9SourceObservationModel,
    M9SourceQueryHeadModel,
    M9SourceQueryModel,
    M9SourceSnapshotModel,
)
from lib.db.repositories.opportunity import GuardKey, OpportunityProfileRepository
from r2.advanced_creative.digests import digest_canonical
from r2.contracts.opportunity import (
    AcquisitionAttempt,
    AcquisitionReceipt,
    AttemptOutcomeReason,
    AttemptState,
    CommandContext,
    CoverageState,
    EffectiveCapabilityEvaluation,
    NormalizedSourceObservation,
    QueryReceipt,
    SourceCapabilityGrant,
    SourceQuery,
    SourceQueryHead,
    SourceSnapshot,
)
from r2.opportunity.acquisition import (
    PageCheckpoint,
    verified_acquisition_receipt,
    verified_query,
    verified_query_receipt,
)
from r2.opportunity.capabilities import page_clocks, retain_page_proof
from r2.opportunity.digests import (
    command_guard_key,
    digest_capability_evaluation,
    digest_capability_grant,
    digest_command_result,
    digest_source_observation,
    digest_source_snapshot,
)
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
        identities = (("grant", grant.grant_id, str(grant.grant_version)), ("evaluation", evaluation.evaluation_id))
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


class AcquisitionAttemptRepository:
    """Command guards serialize absent attempts; locked rows fence state changes."""

    def __init__(
        self, session: AsyncSession, *, user_id: str, project_name: str, guard_key: GuardKey = command_guard_key
    ) -> None:
        self.session, self.user_id, self.project_name = session, user_id, project_name
        self.profiles = OpportunityProfileRepository(session, guard_key=guard_key)
        self.queries = SourceQueryRepository(session, user_id=user_id, project_name=project_name)

    async def _verified(self, row: M9AcquisitionAttemptModel) -> AcquisitionAttempt:
        try:
            value = AcquisitionAttempt.model_validate(row.body_json)
            if row.operation != "acquire" or any(
                getattr(row, name) != getattr(value, name)
                for name in (
                    "user_id",
                    "project_name",
                    "attempt_id",
                    "actor_id",
                    "command_id",
                    "request_digest",
                    "query_id",
                    "query_revision",
                    "attempt_version",
                    "state",
                )
            ):
                raise ValueError("attempt columns differ")
            if value.state == AttemptState.PLANNED:
                valid = value.started_at is None and value.completed_at is None and value.outcome_reason is None
            else:
                terminal = value.state in (AttemptState.SUCCEEDED, AttemptState.FAILED)
                valid = (value.completed_at is not None) == terminal
                if value.state != AttemptState.FAILED and value.started_at is None:
                    valid = False
                if terminal and value.completed_at != row.transitioned_at:
                    valid = False
                if value.state == AttemptState.RUNNING and (
                    value.started_at != row.transitioned_at or value.outcome_reason is not None
                ):
                    valid = False
                if value.state == AttemptState.SUCCEEDED and value.outcome_reason != AttemptOutcomeReason.COMPLETED:
                    valid = False
                if value.state == AttemptState.FAILED and value.outcome_reason in (
                    None,
                    AttemptOutcomeReason.COMPLETED,
                ):
                    valid = False
                if value.state in (AttemptState.OUTCOME_UNKNOWN, AttemptState.NEEDS_OPERATOR) and (
                    value.outcome_reason != AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN
                ):
                    valid = False
            if not valid or (value.started_at is not None and value.started_at > row.transitioned_at):
                raise ValueError("attempt state evidence differs")
            query = await self.queries.get_exact(value.query_id, value.query_revision)
            if query is None or query.query_digest != value.query_digest:
                raise ValueError("attempt query evidence differs")
            return value
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _row(self, attempt_id: str) -> M9AcquisitionAttemptModel | None:
        return (
            await self.session.execute(
                select(M9AcquisitionAttemptModel)
                .where(
                    M9AcquisitionAttemptModel.user_id == self.user_id,
                    M9AcquisitionAttemptModel.project_name == self.project_name,
                    M9AcquisitionAttemptModel.attempt_id == attempt_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def get_exact(self, attempt_id: str) -> AcquisitionAttempt | None:
        row = await self._row(attempt_id)
        return None if row is None else await self._verified(row)

    async def get_for_command(self, *, context: CommandContext, request_digest: str) -> AcquisitionAttempt | None:
        if (context.user_id, context.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        await self.profiles.lock_command_key(context=context, operation="acquire")
        row = (
            await self.session.execute(
                select(M9AcquisitionAttemptModel)
                .where(
                    M9AcquisitionAttemptModel.user_id == self.user_id,
                    M9AcquisitionAttemptModel.actor_id == context.actor_id,
                    M9AcquisitionAttemptModel.operation == "acquire",
                    M9AcquisitionAttemptModel.command_id == context.command_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.project_name != self.project_name or row.request_digest != request_digest:
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        return await self._verified(row)

    async def prepare(self, attempt: AcquisitionAttempt) -> tuple[AcquisitionAttempt, bool]:
        try:
            attempt = AcquisitionAttempt.model_validate(attempt.model_dump())
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
        if (attempt.user_id, attempt.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)
        context = CommandContext(
            command_id=attempt.command_id,
            user_id=self.user_id,
            project_name=self.project_name,
            actor_id=attempt.actor_id,
        )
        await self.profiles.lock_command_key(context=context, operation="acquire")
        row = (
            await self.session.execute(
                select(M9AcquisitionAttemptModel)
                .where(
                    M9AcquisitionAttemptModel.user_id == self.user_id,
                    M9AcquisitionAttemptModel.actor_id == attempt.actor_id,
                    M9AcquisitionAttemptModel.operation == "acquire",
                    M9AcquisitionAttemptModel.command_id == attempt.command_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is not None:
            if row.project_name != self.project_name or row.request_digest != attempt.request_digest:
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            stored = await self._verified(row)
            if (stored.query_id, stored.query_revision, stored.query_digest, stored.adapter_version) != (
                attempt.query_id,
                attempt.query_revision,
                attempt.query_digest,
                attempt.adapter_version,
            ):
                raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
            return stored, False
        if (
            attempt.state != AttemptState.PLANNED
            or attempt.attempt_version != 1
            or any(
                item is not None
                for item in (
                    attempt.started_at,
                    attempt.completed_at,
                    attempt.provider_request_id,
                    attempt.outcome_reason,
                    attempt.page_cursor_digest,
                )
            )
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        query = await self.queries.get_exact(attempt.query_id, attempt.query_revision)
        if query is None or query.query_digest != attempt.query_digest:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        self.session.add(
            M9AcquisitionAttemptModel(
                **{
                    name: getattr(attempt, name)
                    for name in (
                        "user_id",
                        "project_name",
                        "attempt_id",
                        "actor_id",
                        "command_id",
                        "request_digest",
                        "query_id",
                        "query_revision",
                        "attempt_version",
                        "state",
                    )
                },
                operation="acquire",
                transitioned_at=await self.profiles.database_time(),
                body_json=attempt.model_dump(mode="json"),
            )
        )
        await _flush(self.session)
        return attempt, True

    async def transition(
        self,
        attempt_id: str,
        *,
        expected_version: int,
        state: AttemptState,
        reason: AttemptOutcomeReason | None = None,
    ) -> AcquisitionAttempt:
        row = await self._row(attempt_id)
        if row is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        current = await self._verified(row)
        if current.attempt_version != expected_version:
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        if current.state in (AttemptState.OUTCOME_UNKNOWN, AttemptState.NEEDS_OPERATOR) and state in (
            AttemptState.SUCCEEDED,
            AttemptState.FAILED,
        ):
            # Recovery requires a qualified host receipt or provider reconciliation.
            raise OpportunityError(StopCode.M9_ACQUISITION_OUTCOME_UNKNOWN)
        allowed = {
            AttemptState.PLANNED: (AttemptState.RUNNING, AttemptState.FAILED),
            AttemptState.RUNNING: (AttemptState.SUCCEEDED, AttemptState.FAILED, AttemptState.OUTCOME_UNKNOWN),
            AttemptState.OUTCOME_UNKNOWN: (AttemptState.NEEDS_OPERATOR,),
        }
        if state not in allowed.get(current.state, ()):
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        if (
            (state == AttemptState.RUNNING and reason is not None)
            or (state == AttemptState.SUCCEEDED and reason != AttemptOutcomeReason.COMPLETED)
            or (
                state == AttemptState.FAILED
                and reason
                in (
                    None,
                    AttemptOutcomeReason.COMPLETED,
                    AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
                    AttemptOutcomeReason.OPERATOR_RESOLVED,
                )
            )
            or (
                state in (AttemptState.OUTCOME_UNKNOWN, AttemptState.NEEDS_OPERATOR)
                and reason != AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN
            )
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        now = await self.profiles.database_time()
        result = AcquisitionAttempt.model_validate(
            {
                **current.model_dump(),
                "attempt_version": expected_version + 1,
                "state": state,
                "outcome_reason": reason,
                "started_at": now if state == AttemptState.RUNNING else current.started_at,
                "completed_at": now if state in (AttemptState.SUCCEEDED, AttemptState.FAILED) else None,
            }
        )
        row.attempt_version, row.state, row.transitioned_at = result.attempt_version, result.state, now
        row.body_json = result.model_dump(mode="json")
        await _flush(self.session)
        return result


class SnapshotPageRepository:
    def __init__(self, session: AsyncSession, *, attempts: AcquisitionAttemptRepository) -> None:
        self.session, self.attempts = session, attempts
        self.user_id, self.project_name = attempts.user_id, attempts.project_name
        self.capabilities = CapabilityEvidenceRepository(session, user_id=self.user_id, project_name=self.project_name)

    async def _verified(self, row: M9SnapshotPageModel, attempt: AcquisitionAttempt) -> PageCheckpoint:
        try:
            raw = row.checkpoint_json
            if set(raw) != {"metadata", "metadata_digest"}:
                raise ValueError("checkpoint envelope differs")
            checkpoint = PageCheckpoint.model_validate(raw["metadata"])
            if (
                digest_canonical(checkpoint.model_dump()) != raw["metadata_digest"]
                or checkpoint.page.model_dump(mode="json") != row.body_json
                or checkpoint.page.ordinal != row.ordinal
                or (row.user_id, row.project_name, row.attempt_id)
                != (self.user_id, self.project_name, attempt.attempt_id)
            ):
                raise ValueError("checkpoint integrity differs")
            query = await self.attempts.queries.get_exact(attempt.query_id, attempt.query_revision)
            if query is None:
                raise ValueError("checkpoint query is absent")
            grant = await self.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
            page = checkpoint.page
            if (
                grant is None
                or grant.grant_digest != query.capability_grant_digest
                or page.data_class_clocks != page_clocks(page, grant, captured_at=page.captured_at)
                or (page.retained_source_payload_digest is not None and not retain_page_proof(page, grant))
                or attempt.started_at is None
                or page.captured_at < attempt.started_at
            ):
                raise ValueError("checkpoint policy clocks differ")
            return checkpoint
        except (ValueError, TypeError, KeyError):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def list_for_attempt(self, attempt_id: str) -> tuple[PageCheckpoint, ...]:
        attempt = await self.attempts.get_exact(attempt_id)
        if attempt is None:
            return ()
        rows = (
            (
                await self.session.execute(
                    select(M9SnapshotPageModel)
                    .where(
                        M9SnapshotPageModel.user_id == self.user_id,
                        M9SnapshotPageModel.project_name == self.project_name,
                        M9SnapshotPageModel.attempt_id == attempt_id,
                    )
                    .order_by(M9SnapshotPageModel.ordinal)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        result = tuple([await self._verified(row, attempt) for row in rows])
        for index, item in enumerate(result):
            previous = result[index - 1] if index else None
            if (
                item.page.ordinal != index + 1
                or item.page.request_cursor_digest != (previous.page.response_cursor_digest if previous else None)
                or (previous is not None and previous.terminal_page)
            ):
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        return result

    async def append(
        self, attempt_id: str, checkpoint: PageCheckpoint, *, expected_attempt_version: int
    ) -> PageCheckpoint:
        try:
            checkpoint = PageCheckpoint.model_validate(checkpoint.model_dump())
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None
        attempt = await self.attempts.get_exact(attempt_id)
        if attempt is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        pages = await self.list_for_attempt(attempt_id)
        ordinal = checkpoint.page.ordinal
        if ordinal <= len(pages):
            if pages[ordinal - 1] != checkpoint:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            return pages[ordinal - 1]
        if attempt.attempt_version != expected_attempt_version or attempt.state != AttemptState.RUNNING:
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        query = await self.attempts.queries.get_exact(attempt.query_id, attempt.query_revision)
        now = await self.attempts.profiles.database_time()
        previous = pages[-1] if pages else None
        if (
            query is None
            or ordinal != len(pages) + 1
            or ordinal > query.max_pages
            or checkpoint.page.captured_at > now
            or (
                previous is not None
                and (previous.terminal_page or checkpoint.page.captured_at < previous.page.captured_at)
            )
            or checkpoint.page.request_cursor_digest != (previous.page.response_cursor_digest if previous else None)
            or (
                checkpoint.page.response_cursor_digest is not None
                and checkpoint.page.response_cursor_digest
                in {item.page.request_cursor_digest for item in (*pages, checkpoint)}
            )
            or sum(item.page.record_count for item in (*pages, checkpoint)) > query.max_records
            or sum(item.page.raw_size_bytes for item in (*pages, checkpoint)) > 41_943_040
            or sum(item.quota_units_observed or 0 for item in (*pages, checkpoint)) > query.max_quota_units
        ):
            raise OpportunityError(StopCode.M9_OPERATIONAL_ENVELOPE_EXCEEDED)
        row = M9SnapshotPageModel(
            user_id=self.user_id,
            project_name=self.project_name,
            attempt_id=attempt_id,
            ordinal=ordinal,
            body_json=checkpoint.page.model_dump(mode="json"),
            checkpoint_json={
                "metadata": checkpoint.model_dump(mode="json"),
                "metadata_digest": digest_canonical(checkpoint.model_dump()),
            },
        )
        await self._verified(row, attempt)
        self.session.add(row)
        await _flush(self.session)
        return checkpoint


class SourceSnapshotRepository:
    def __init__(
        self, session: AsyncSession, *, attempts: AcquisitionAttemptRepository, pages: SnapshotPageRepository
    ) -> None:
        self.session, self.attempts, self.pages = session, attempts, pages
        self.user_id, self.project_name = attempts.user_id, attempts.project_name

    async def _validate(self, snapshot: SourceSnapshot) -> SourceSnapshot:
        try:
            snapshot = SourceSnapshot.model_validate(snapshot.model_dump())
            if digest_source_snapshot(snapshot) != snapshot.snapshot_digest:
                raise ValueError("snapshot integrity differs")
            if (snapshot.user_id, snapshot.project_name) != (self.user_id, self.project_name):
                raise ValueError("snapshot scope differs")
            attempt = await self.attempts.get_exact(snapshot.attempt_id)
            if attempt is None:
                raise ValueError("snapshot attempt is absent")
            query = await self.attempts.queries.get_exact(attempt.query_id, attempt.query_revision)
            if query is None or (
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
                raise ValueError("snapshot query authority differs")
            grant = await self.pages.capabilities.get_grant(query.capability_grant_id, query.capability_grant_version)
            evaluation = await self.pages.capabilities.get_evaluation(query.capability_evaluation_id)
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
                raise ValueError("snapshot capability evidence differs")
            checkpoints = await self.pages.list_for_attempt(snapshot.attempt_id)
            if snapshot.coverage_state == CoverageState.COMPLETE_WITHIN_DECLARED_BOUNDS and (
                not checkpoints
                or not checkpoints[-1].terminal_page
                or any(item.page.payload_ref is None for item in checkpoints)
            ):
                raise ValueError("complete coverage has no terminal source evidence")
            identities = tuple(sorted({ref for item in checkpoints for ref in item.source_identity_refs}))
            if (
                snapshot.pages != tuple(item.page for item in checkpoints)
                or snapshot.source_identity_refs != identities
                or snapshot.adapter_version != attempt.adapter_version
                or snapshot.capture_started_at != attempt.started_at
                or snapshot.created_at < snapshot.capture_completed_at
                or snapshot.revision != 1
                or snapshot.parent_revision is not None
            ):
                raise ValueError("snapshot page lineage differs")
            return snapshot
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _verified(self, row: M9SourceSnapshotModel) -> SourceSnapshot:
        try:
            snapshot = await self._validate(SourceSnapshot.model_validate(row.body_json))
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
                raise ValueError("snapshot columns differ")
            return snapshot
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def get_exact(self, snapshot_id: str, revision: int) -> SourceSnapshot | None:
        row = await self.session.get(
            M9SourceSnapshotModel, (self.user_id, self.project_name, snapshot_id, revision), populate_existing=True
        )
        return None if row is None else await self._verified(row)

    async def get_for_attempt(self, attempt_id: str) -> SourceSnapshot | None:
        row = (
            await self.session.execute(
                select(M9SourceSnapshotModel)
                .where(
                    M9SourceSnapshotModel.user_id == self.user_id,
                    M9SourceSnapshotModel.project_name == self.project_name,
                    M9SourceSnapshotModel.attempt_id == attempt_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return None if row is None else await self._verified(row)

    async def append(self, snapshot: SourceSnapshot) -> None:
        snapshot = await self._validate(snapshot)
        attempt = await self.attempts.get_exact(snapshot.attempt_id)
        now = await self.attempts.profiles.database_time()
        if attempt is None or attempt.state != AttemptState.RUNNING or snapshot.created_at > now:
            raise OpportunityError(StopCode.M9_STALE_HEAD)
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
                body_json=snapshot.model_dump(mode="json"),
            )
        )
        await _flush(self.session)


class SourceObservationRepository:
    def __init__(self, session: AsyncSession, *, snapshots: SourceSnapshotRepository) -> None:
        self.session, self.snapshots = session, snapshots
        self.user_id, self.project_name = snapshots.user_id, snapshots.project_name

    async def _validate(self, observation: NormalizedSourceObservation) -> NormalizedSourceObservation:
        try:
            observation = NormalizedSourceObservation.model_validate(observation.model_dump())
            if digest_source_observation(observation) != observation.observation_digest:
                raise ValueError("observation integrity differs")
            if (observation.user_id, observation.project_name) != (self.user_id, self.project_name):
                raise ValueError("observation scope differs")
            snapshot = await self.snapshots.get_exact(observation.snapshot_id, 1)
            if snapshot is None or (
                observation.snapshot_digest != snapshot.snapshot_digest
                or observation.source_kind != snapshot.source_kind
                or not 1 <= observation.page_ordinal <= len(snapshot.pages)
            ):
                raise ValueError("observation snapshot differs")
            checkpoints = await self.snapshots.pages.list_for_attempt(snapshot.attempt_id)
            checkpoint = checkpoints[observation.page_ordinal - 1]
            page = checkpoint.page
            if (
                observation.source_identity_ref not in checkpoint.source_identity_refs
                or observation.data_class not in page.data_classes
                or observation.payload_integrity_ref != page.payload_integrity_ref
                or observation.retained_source_payload_digest != page.retained_source_payload_digest
            ):
                raise ValueError("observation page lineage differs")
            query = await self.snapshots.attempts.queries.get_exact(snapshot.query_id, snapshot.query_revision)
            if query is None:
                raise ValueError("observation query absent")
            grant = await self.snapshots.pages.capabilities.get_grant(
                query.capability_grant_id, query.capability_grant_version
            )
            rule = (
                None
                if grant is None
                else next((r for r in grant.data_rules if r.data_class == observation.data_class), None)
            )
            if rule is None or (
                observation.retained_normalized_value_digest is not None and not rule.digest_proof_may_be_retained
            ):
                raise ValueError("observation proof policy differs")
            return observation
        except (ValueError, IndexError):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def _verified(self, row: M9SourceObservationModel) -> NormalizedSourceObservation:
        try:
            value = await self._validate(NormalizedSourceObservation.model_validate(row.body_json))
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
                raise ValueError("observation columns differ")
            return value
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def get_exact(self, observation_id: str, revision: int) -> NormalizedSourceObservation | None:
        row = await self.session.get(
            M9SourceObservationModel,
            (self.user_id, self.project_name, observation_id, revision),
            populate_existing=True,
        )
        return None if row is None else await self._verified(row)

    async def _head(self, observation_id: str, *, lock: bool = True) -> M9ObservationHeadModel | None:
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
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def get_current(self, observation_id: str) -> NormalizedSourceObservation | None:
        head = await self._head(observation_id, lock=False)
        if head is None:
            return None
        revision, version = head.current_revision, head.head_version
        # Verify/lock immutable attempt lineage before taking the observation head.
        value = await self.get_exact(observation_id, revision)
        head = await self._head(observation_id)
        if head is None or (head.current_revision, head.head_version) != (revision, version):
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        if value is None or version != revision:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        return value

    async def append(self, observation: NormalizedSourceObservation, *, expected_head_version: int | None) -> None:
        initial = await self._head(observation.observation_id, lock=False)
        initial_key = None if initial is None else (initial.current_revision, initial.head_version)
        snapshot_ids = {observation.snapshot_id}
        if initial is not None:
            prior_row = await self.session.get(
                M9SourceObservationModel,
                (self.user_id, self.project_name, observation.observation_id, initial.current_revision),
                populate_existing=True,
            )
            if prior_row is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            snapshot_ids.add(prior_row.snapshot_id)
        # A correction may span two snapshots/attempts; lock both in identity order
        # before validating either envelope or locking the mutable observation head.
        attempt_ids = (
            (
                await self.session.execute(
                    select(M9SourceSnapshotModel.attempt_id).where(
                        M9SourceSnapshotModel.user_id == self.user_id,
                        M9SourceSnapshotModel.project_name == self.project_name,
                        M9SourceSnapshotModel.snapshot_id.in_(sorted(snapshot_ids)),
                    )
                )
            )
            .scalars()
            .all()
        )
        await self.session.execute(
            select(M9AcquisitionAttemptModel)
            .where(
                M9AcquisitionAttemptModel.user_id == self.user_id,
                M9AcquisitionAttemptModel.project_name == self.project_name,
                M9AcquisitionAttemptModel.attempt_id.in_(sorted(set(attempt_ids))),
            )
            .order_by(M9AcquisitionAttemptModel.attempt_id)
            .with_for_update()
        )
        observation = await self._validate(observation)
        head = await self._head(observation.observation_id)
        current_key = None if head is None else (head.current_revision, head.head_version)
        if current_key != initial_key:
            raise OpportunityError(StopCode.M9_STALE_HEAD)
        if head is None:
            if (
                expected_head_version is not None
                or observation.revision != 1
                or observation.parent_revision is not None
            ):
                raise OpportunityError(StopCode.M9_STALE_HEAD)
        else:
            if (head.head_version, head.current_revision) != (expected_head_version, observation.parent_revision) or (
                observation.revision != head.current_revision + 1
            ):
                raise OpportunityError(StopCode.M9_STALE_HEAD)
            prior = await self.get_exact(observation.observation_id, head.current_revision)
            if prior is None or any(
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
                body_json=observation.model_dump(mode="json"),
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
            head.current_revision, head.head_version = observation.revision, head.head_version + 1
        await _flush(self.session)


class AcquisitionReceiptRepository:
    """Typed receipts reconstruct stored aggregates; caller-selected result models are absent."""

    def __init__(
        self, session: AsyncSession, *, attempts: AcquisitionAttemptRepository, snapshots: SourceSnapshotRepository
    ) -> None:
        self.session, self.attempts, self.snapshots = session, attempts, snapshots
        self.user_id, self.project_name = attempts.user_id, attempts.project_name

    def _scope(self, context: CommandContext) -> None:
        if (context.user_id, context.project_name) != (self.user_id, self.project_name):
            raise OpportunityError(StopCode.M9_SOURCE_POLICY_FORBIDDEN)

    async def _row(self, context: CommandContext, operation: str, request_digest: str) -> M9CommandReceiptModel | None:
        self._scope(context)
        row = (
            await self.session.execute(
                select(M9CommandReceiptModel)
                .where(
                    M9CommandReceiptModel.user_id == context.user_id,
                    M9CommandReceiptModel.actor_id == context.actor_id,
                    M9CommandReceiptModel.operation == operation,
                    M9CommandReceiptModel.command_id == context.command_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is not None and (row.project_name != context.project_name or row.request_digest != request_digest):
            raise OpportunityError(StopCode.M9_COMMAND_REPLAY_CONFLICT)
        return row

    async def get_query(self, *, context: CommandContext, request_digest: str) -> QueryReceipt | None:
        row = await self._row(context, "declare_query", request_digest)
        if row is None:
            return None
        try:
            if row.result_kind != "SOURCE_QUERY":
                raise ValueError("query receipt kind differs")
            identity, revision, version = row.result_ref.split(":")
            query = await self.attempts.queries.get_exact(identity, int(revision))
            if query is None:
                raise ValueError("query receipt evidence is absent")
            receipt = QueryReceipt(
                command_id=row.command_id,
                request_digest=row.request_digest,
                query=query,
                head=SourceQueryHead(query_id=identity, current_revision=int(revision), head_version=int(version)),
                result_digest=row.result_digest,
                committed_at=row.committed_at,
            )
            return verified_query_receipt(receipt, context, request_digest)
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def get_query_for_revision(self, query_id: str, revision: int) -> QueryReceipt | None:
        query = await self.attempts.queries.get_exact(query_id, revision)
        if query is None:
            return None
        rows = (
            (
                await self.session.execute(
                    select(M9CommandReceiptModel)
                    .where(
                        M9CommandReceiptModel.user_id == self.user_id,
                        M9CommandReceiptModel.project_name == self.project_name,
                        M9CommandReceiptModel.operation == "declare_query",
                        M9CommandReceiptModel.result_kind == "SOURCE_QUERY",
                        M9CommandReceiptModel.result_ref == f"{query_id}:{revision}:{revision}",
                    )
                    .limit(2)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != 1:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        row = rows[0]
        context = CommandContext(
            command_id=row.command_id, user_id=self.user_id, project_name=self.project_name, actor_id=row.actor_id
        )
        receipt = await self.get_query(context=context, request_digest=row.request_digest)
        if receipt is None or receipt.query != query:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        return receipt

    async def stage_query(self, *, context: CommandContext, receipt: QueryReceipt) -> None:
        self._scope(context)
        receipt = verified_query_receipt(receipt, context, receipt.request_digest)
        if await self.attempts.queries.get_exact(receipt.query.query_id, receipt.query.revision) != receipt.query:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        self.session.add(
            M9CommandReceiptModel(
                user_id=context.user_id,
                project_name=context.project_name,
                actor_id=context.actor_id,
                operation="declare_query",
                command_id=context.command_id,
                request_digest=receipt.request_digest,
                result_kind="SOURCE_QUERY",
                result_ref=f"{receipt.query.query_id}:{receipt.query.revision}:{receipt.head.head_version}",
                result_digest=receipt.result_digest,
                committed_at=receipt.committed_at,
            )
        )
        await _flush(self.session)

    async def _acquisition(
        self, *, context: CommandContext, request_digest: str, attempt: AcquisitionAttempt, committed_at: datetime
    ) -> AcquisitionReceipt:
        if (attempt.user_id, attempt.project_name, attempt.actor_id, attempt.command_id, attempt.request_digest) != (
            context.user_id,
            context.project_name,
            context.actor_id,
            context.command_id,
            request_digest,
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        snapshot = await self.snapshots.get_for_attempt(attempt.attempt_id)
        receipt = AcquisitionReceipt(
            command_id=context.command_id,
            request_digest=request_digest,
            attempt_id=attempt.attempt_id,
            attempt_version=attempt.attempt_version,
            state=attempt.state,
            snapshot_ids=() if snapshot is None else (snapshot.snapshot_id,),
            snapshot_digests=() if snapshot is None else (snapshot.snapshot_digest,),
            result_digest="sha256:" + "0" * 64,
            committed_at=committed_at,
        )
        return receipt.model_copy(update={"result_digest": digest_command_result("acquire", request_digest, receipt)})

    async def current_acquisition(self, *, context: CommandContext, request_digest: str) -> AcquisitionReceipt | None:
        self._scope(context)
        attempt = await self.attempts.get_for_command(context=context, request_digest=request_digest)
        if attempt is None:
            return None
        if attempt.state in (AttemptState.SUCCEEDED, AttemptState.FAILED):
            # A terminal attempt is published atomically with its immutable receipt.
            receipt = await self.get_acquisition(context=context, request_digest=request_digest)
            if receipt is None:
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            return receipt
        row = await self.attempts._row(attempt.attempt_id)
        if row is None:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        return await self._acquisition(
            context=context, request_digest=request_digest, attempt=attempt, committed_at=row.transitioned_at
        )

    async def get_acquisition(self, *, context: CommandContext, request_digest: str) -> AcquisitionReceipt | None:
        row = await self._row(context, "acquire", request_digest)
        if row is None:
            return None
        try:
            if row.result_kind != "ACQUISITION":
                raise ValueError("acquisition receipt kind differs")
            identity, version = row.result_ref.split(":")
            attempt = await self.attempts.get_exact(identity)
            if (
                attempt is None
                or attempt.attempt_version != int(version)
                or attempt.state
                not in (
                    AttemptState.SUCCEEDED,
                    AttemptState.FAILED,
                )
            ):
                raise ValueError("acquisition receipt attempt differs")
            receipt = await self._acquisition(
                context=context, request_digest=request_digest, attempt=attempt, committed_at=row.committed_at
            )
            if not receipt.snapshot_ids or receipt.result_digest != row.result_digest:
                raise ValueError("acquisition receipt result differs")
            return verified_acquisition_receipt(receipt, context, request_digest)
        except ValueError:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING) from None

    async def stage_acquisition(self, *, context: CommandContext, receipt: AcquisitionReceipt) -> None:
        self._scope(context)
        receipt = verified_acquisition_receipt(receipt, context, receipt.request_digest)
        attempt = await self.attempts.get_exact(receipt.attempt_id)
        if (
            attempt is None
            or attempt.state not in (AttemptState.SUCCEEDED, AttemptState.FAILED)
            or not receipt.snapshot_ids
        ):
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        expected = await self._acquisition(
            context=context, request_digest=receipt.request_digest, attempt=attempt, committed_at=receipt.committed_at
        )
        if expected != receipt:
            raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
        self.session.add(
            M9CommandReceiptModel(
                user_id=context.user_id,
                project_name=context.project_name,
                actor_id=context.actor_id,
                operation="acquire",
                command_id=context.command_id,
                request_digest=receipt.request_digest,
                result_kind="ACQUISITION",
                result_ref=f"{receipt.attempt_id}:{receipt.attempt_version}",
                result_digest=receipt.result_digest,
                committed_at=receipt.committed_at,
            )
        )
        await _flush(self.session)


class AcquisitionTransaction:
    def __init__(
        self, session: AsyncSession, *, user_id: str, project_name: str, guard_key: GuardKey = command_guard_key
    ) -> None:
        self.session = session
        self.user_id, self.project_name = user_id, project_name
        self.profiles = OpportunityProfileRepository(session, guard_key=guard_key)
        self.capabilities = CapabilityEvidenceRepository(session, user_id=user_id, project_name=project_name)
        self.queries = SourceQueryRepository(session, user_id=user_id, project_name=project_name)
        self.attempts = AcquisitionAttemptRepository(
            session, user_id=user_id, project_name=project_name, guard_key=guard_key
        )
        self.pages = SnapshotPageRepository(session, attempts=self.attempts)
        self.snapshots = SourceSnapshotRepository(session, attempts=self.attempts, pages=self.pages)
        self.observations = SourceObservationRepository(session, snapshots=self.snapshots)
        self.receipts = AcquisitionReceiptRepository(session, attempts=self.attempts, snapshots=self.snapshots)

    async def stage_query_event(self, *, query: SourceQuery, committed_at: datetime) -> None:
        self.session.add(
            M9EventModel(
                user_id=self.user_id,
                project_name=self.project_name,
                event_kind="SOURCE_QUERY_DECLARED",
                aggregate_id=query.query_id,
                aggregate_revision=query.revision,
                payload_digest=query.query_digest,
                committed_at=committed_at,
            )
        )
        await _flush(self.session)


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
