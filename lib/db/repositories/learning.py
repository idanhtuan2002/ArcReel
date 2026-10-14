"""Persistence for M8-D learning observations (plan 2026-10-14 D1).

The repository writes inside the caller's transaction and never updates or deletes a row. Admissions
in one scope are serialized (a PostgreSQL advisory lock; SQLite has a single writer). Order: an exact
command replay returns its stored result first; then an identical observation id or identity replays;
then a correction must name the current tip of its identity. Every successful command, a replay
included, reserves its command id. Database uniqueness backs every rule.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.learning import LearningObservationCommandModel, LearningObservationModel
from r2.advanced_creative.errors import CommandConflictError, ObservationConflictError, ObservationNotFoundError
from r2.contracts.advanced_creative import LearningObservation
from r2.learning.observations import (
    ObservationIdentity,
    ObservationInvalidError,
    current_as_of,
    identity_of,
    ingest_command_digest,
    observation_digest,
    validate_correction,
    validate_observation,
)

Clock = Callable[[], datetime]
_TICK = timedelta(microseconds=1)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _observation(row: LearningObservationModel) -> LearningObservation:
    return LearningObservation.model_validate(row.observation_json)


def _identity_filter(identity: ObservationIdentity) -> tuple[ColumnElement[bool], ...]:
    model = LearningObservationModel
    return (
        model.source_family == identity.source_family,
        model.source_record_id == identity.source_record_id,
        model.metric_name == identity.metric_name,
        model.metric_definition_version == identity.metric_definition_version,
        model.window_starts_at == _utc(identity.window_starts_at),
        model.window_ends_at == _utc(identity.window_ends_at),
        model.window_timezone_name == identity.window_timezone_name,
        model.window_aggregation == identity.window_aggregation,
    )


class LearningObservationRepository:
    """``ObservationRepository`` over ``m8_learning_observations``."""

    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self.session = session
        self._clock = clock or (lambda: datetime.now(UTC))

    async def _lock_scope(self, *, user_id: str, project_name: str) -> None:
        """Serialize every admission in one scope (PostgreSQL); SQLite already has one writer."""
        if self.session.get_bind().dialect.name != "postgresql":
            return
        key = f"m8-learning-scope:{user_id}:{project_name}"
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    async def _row(self, *, user_id: str, project_name: str, observation_id: str) -> LearningObservationModel | None:
        return await self.session.get(LearningObservationModel, (user_id, project_name, observation_id))

    async def _original(
        self, *, user_id: str, project_name: str, identity: ObservationIdentity
    ) -> LearningObservationModel | None:
        model = LearningObservationModel
        return await self.session.scalar(
            select(model).where(
                model.user_id == user_id,
                model.project_name == project_name,
                model.correction_of.is_(None),
                *_identity_filter(identity),
            )
        )

    async def _successor(self, *, user_id: str, project_name: str, observation_id: str) -> str | None:
        model = LearningObservationModel
        return await self.session.scalar(
            select(model.observation_id).where(
                model.user_id == user_id, model.project_name == project_name, model.correction_of == observation_id
            )
        )

    async def _watermark(self, *, user_id: str, project_name: str) -> datetime | None:
        model = LearningObservationModel
        latest = await self.session.scalar(
            select(func.max(model.ingested_at)).where(model.user_id == user_id, model.project_name == project_name)
        )
        return None if latest is None else _utc(latest)

    async def _existing(
        self, *, user_id: str, project_name: str, observation: LearningObservation
    ) -> LearningObservationModel | None:
        """The stored observation this one replays, ``None`` when it is new, or a conflict."""
        digest = observation_digest(observation)
        same_id = await self._row(user_id=user_id, project_name=project_name, observation_id=observation.observation_id)
        if same_id is not None:
            if same_id.observation_digest != digest:
                raise ObservationConflictError("observation id holds different content")
            return same_id
        if observation.correction_of is None:
            original = await self._original(
                user_id=user_id, project_name=project_name, identity=identity_of(observation)
            )
            if original is not None:
                if original.observation_digest != digest:
                    raise ObservationConflictError("identity already observed; send a correction")
                return original
            return None
        predecessor = await self._row(
            user_id=user_id, project_name=project_name, observation_id=observation.correction_of
        )
        if predecessor is None:
            raise ObservationNotFoundError("correction names an unknown observation")
        validate_correction(observation, _observation(predecessor))
        if await self._successor(user_id=user_id, project_name=project_name, observation_id=predecessor.observation_id):
            raise ObservationConflictError("correction must name the current tip")
        return None

    async def ingest(
        self, *, user_id: str, project_name: str, observation: LearningObservation, command_id: str
    ) -> LearningObservation:
        if not command_id:
            raise ValueError("command_id is required")
        validate_observation(observation, project_name=project_name)
        command_digest = ingest_command_digest(user_id=user_id, project_name=project_name, observation=observation)
        await self._lock_scope(user_id=user_id, project_name=project_name)

        command = await self.session.get(LearningObservationCommandModel, (user_id, project_name, command_id))
        if command is not None:
            if command.command_digest != command_digest:
                raise CommandConflictError("command id reused with different content")
            stored_row = await self._row(
                user_id=user_id, project_name=project_name, observation_id=command.observation_id
            )
            assert stored_row is not None  # restrict-keyed, never deleted
            return _observation(stored_row)

        now = _utc(self._clock())
        existing = await self._existing(user_id=user_id, project_name=project_name, observation=observation)
        if existing is not None:
            result = _observation(existing)
        else:
            # Admission time strictly increases within a scope, even when the clock steps back.
            watermark = await self._watermark(user_id=user_id, project_name=project_name)
            ingested_at = now if watermark is None or now > watermark else watermark + _TICK
            result = observation.model_copy(update={"ingested_at": ingested_at})
            window = result.window
            self.session.add(
                LearningObservationModel(
                    user_id=user_id,
                    project_name=project_name,
                    observation_id=result.observation_id,
                    source_family=result.source_family,
                    source_record_id=result.source_record_id,
                    metric_name=result.metric_name,
                    metric_definition_version=result.metric_definition_version,
                    window_starts_at=_utc(window.starts_at),
                    window_ends_at=_utc(window.ends_at),
                    window_timezone_name=window.timezone_name,
                    window_aggregation=window.aggregation,
                    has_value=result.metric_value is not None,
                    missing_reason=result.missing_reason,
                    correction_of=result.correction_of,
                    observation_json=result.model_dump(mode="json"),
                    observation_digest=observation_digest(result),
                    observed_at=_utc(result.observed_at),
                    ingested_at=ingested_at,
                )
            )
            await self.session.flush()
        self.session.add(
            LearningObservationCommandModel(
                user_id=user_id,
                project_name=project_name,
                command_id=command_id,
                command_digest=command_digest,
                observation_id=result.observation_id,
                created_at=now,
            )
        )
        await self.session.flush()
        return result

    async def get(self, *, user_id: str, project_name: str, observation_id: str) -> LearningObservation | None:
        row = await self._row(user_id=user_id, project_name=project_name, observation_id=observation_id)
        return None if row is None else _observation(row)

    async def chain(self, *, user_id: str, project_name: str, observation_id: str) -> tuple[LearningObservation, ...]:
        """The identity's records from its original to its tip; empty for an unknown or foreign id."""
        row = await self._row(user_id=user_id, project_name=project_name, observation_id=observation_id)
        if row is None:
            return ()
        model = LearningObservationModel
        rows = (
            await self.session.scalars(
                select(model).where(
                    model.user_id == user_id,
                    model.project_name == project_name,
                    *_identity_filter(identity_of(_observation(row))),
                )
            )
        ).all()
        successor = {r.correction_of: r for r in rows if r.correction_of is not None}
        node = next((r for r in rows if r.correction_of is None), None)
        ordered: list[LearningObservation] = []
        while node is not None:
            ordered.append(_observation(node))
            node = successor.get(node.observation_id)
        return tuple(ordered)

    async def watermark(self, *, user_id: str, project_name: str) -> datetime | None:
        """The latest admission time in the scope; every later admission is stamped after it."""
        return await self._watermark(user_id=user_id, project_name=project_name)

    async def list_as_of(
        self, *, user_id: str, project_name: str, cutoff: datetime, source_family: str | None = None
    ) -> tuple[LearningObservation, ...]:
        """Each identity's current record as of ``cutoff`` (see ``current_as_of``).

        The cutoff must not pass the scope watermark. Admission times only increase past the
        watermark, so a result read at an admissible cutoff never changes; a later cutoff could still
        gain records and is refused.
        """
        cutoff = _utc(cutoff)
        watermark = await self._watermark(user_id=user_id, project_name=project_name)
        if watermark is None or cutoff > watermark:
            raise ObservationInvalidError("cutoff is after the latest admission; pin it at the watermark")
        model = LearningObservationModel
        query = select(model).where(
            model.user_id == user_id, model.project_name == project_name, model.ingested_at <= cutoff
        )
        if source_family is not None:
            query = query.where(model.source_family == source_family)
        rows = (await self.session.scalars(query)).all()
        return current_as_of((_observation(row) for row in rows), cutoff)


__all__ = ["LearningObservationRepository"]
