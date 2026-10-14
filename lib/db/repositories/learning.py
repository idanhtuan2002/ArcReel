"""Persistence for M8-D learning observations (plan 2026-10-14 D1).

The repository writes inside the caller's transaction and never updates or deletes a row. Admission
order: an exact command replay returns its stored result first; then an identical observation id or
identity replays; then a correction must name the current tip of its identity, which is locked for the
rest of the transaction. Database uniqueness settles any race the locks do not cover.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.learning import LearningObservationModel
from r2.advanced_creative.errors import CommandConflictError, ObservationConflictError, ObservationNotFoundError
from r2.contracts.advanced_creative import LearningObservation
from r2.learning.observations import (
    ObservationIdentity,
    current_as_of,
    identity_of,
    ingest_command_digest,
    observation_digest,
    validate_correction,
    validate_observation,
)

Clock = Callable[[], datetime]


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

    async def _lock_command(self, *, user_id: str, project_name: str, command_id: str) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            return
        key = f"m8-learning-command:{user_id}:{project_name}:{command_id}"
        await self.session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    async def _row(self, *, user_id: str, project_name: str, observation_id: str) -> LearningObservationModel | None:
        return await self.session.get(LearningObservationModel, (user_id, project_name, observation_id))

    async def _by_command(self, *, user_id: str, project_name: str, command_id: str) -> LearningObservationModel | None:
        model = LearningObservationModel
        return await self.session.scalar(
            select(model).where(
                model.user_id == user_id, model.project_name == project_name, model.command_id == command_id
            )
        )

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

    async def _replay(
        self, *, user_id: str, project_name: str, observation: LearningObservation, command_id: str, command_digest: str
    ) -> LearningObservation | None:
        """The stored result this request replays, ``None`` for a new admission, or a conflict."""
        by_command = await self._by_command(user_id=user_id, project_name=project_name, command_id=command_id)
        if by_command is not None:
            if by_command.command_digest != command_digest:
                raise CommandConflictError("command id reused with different content")
            return _observation(by_command)
        digest = observation_digest(observation)
        same_id = await self._row(user_id=user_id, project_name=project_name, observation_id=observation.observation_id)
        if same_id is not None:
            if same_id.observation_digest != digest:
                raise ObservationConflictError("observation id holds different content")
            return _observation(same_id)
        if observation.correction_of is None:
            original = await self._original(
                user_id=user_id, project_name=project_name, identity=identity_of(observation)
            )
            if original is not None:
                if original.observation_digest != digest:
                    raise ObservationConflictError("identity already observed; send a correction")
                return _observation(original)
        return None

    async def ingest(
        self, *, user_id: str, project_name: str, observation: LearningObservation, command_id: str
    ) -> LearningObservation:
        if not command_id:
            raise ValueError("command_id is required")
        validate_observation(observation, project_name=project_name)
        command_digest = ingest_command_digest(user_id=user_id, project_name=project_name, observation=observation)
        await self._lock_command(user_id=user_id, project_name=project_name, command_id=command_id)
        replayed = await self._replay(
            user_id=user_id,
            project_name=project_name,
            observation=observation,
            command_id=command_id,
            command_digest=command_digest,
        )
        if replayed is not None:
            return replayed

        ingested_at = _utc(self._clock())
        if observation.correction_of is not None:
            predecessor_row = await self.session.scalar(
                select(LearningObservationModel)
                .where(
                    LearningObservationModel.user_id == user_id,
                    LearningObservationModel.project_name == project_name,
                    LearningObservationModel.observation_id == observation.correction_of,
                )
                .with_for_update()
            )
            if predecessor_row is None:
                raise ObservationNotFoundError("correction names an unknown observation")
            validate_correction(observation, _observation(predecessor_row))
            if await self._successor(
                user_id=user_id, project_name=project_name, observation_id=predecessor_row.observation_id
            ):
                raise ObservationConflictError("correction must name the current tip")
            ingested_at = max(ingested_at, _utc(predecessor_row.ingested_at))

        stored = observation.model_copy(update={"ingested_at": ingested_at})
        window = stored.window
        row = LearningObservationModel(
            user_id=user_id,
            project_name=project_name,
            observation_id=stored.observation_id,
            source_family=stored.source_family,
            source_record_id=stored.source_record_id,
            metric_name=stored.metric_name,
            metric_definition_version=stored.metric_definition_version,
            window_starts_at=_utc(window.starts_at),
            window_ends_at=_utc(window.ends_at),
            window_timezone_name=window.timezone_name,
            window_aggregation=window.aggregation,
            has_value=stored.metric_value is not None,
            missing_reason=stored.missing_reason,
            correction_of=stored.correction_of,
            observation_json=stored.model_dump(mode="json"),
            observation_digest=observation_digest(stored),
            command_id=command_id,
            command_digest=command_digest,
            observed_at=_utc(stored.observed_at),
            ingested_at=ingested_at,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
        except IntegrityError:
            # A concurrent writer won the identity, successor or command slot; re-resolve against it.
            replayed = await self._replay(
                user_id=user_id,
                project_name=project_name,
                observation=observation,
                command_id=command_id,
                command_digest=command_digest,
            )
            if replayed is not None:
                return replayed
            raise ObservationConflictError("observation lost a concurrent admission") from None
        return stored

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

    async def list_as_of(
        self, *, user_id: str, project_name: str, cutoff: datetime, source_family: str | None = None
    ) -> tuple[LearningObservation, ...]:
        """Each identity's current record as of ``cutoff`` (see ``current_as_of``)."""
        model = LearningObservationModel
        query = select(model).where(
            model.user_id == user_id, model.project_name == project_name, model.ingested_at <= _utc(cutoff)
        )
        if source_family is not None:
            query = query.where(model.source_family == source_family)
        rows = (await self.session.scalars(query)).all()
        return current_as_of((_observation(row) for row in rows), _utc(cutoff))


__all__ = ["LearningObservationRepository"]
