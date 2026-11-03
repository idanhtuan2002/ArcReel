"""MODEL observations of qualified reviewer routes: append-only and replay-exact.

A replay of a recorded observation keeps the first recording's ``observed_at``; any other difference conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

import r2.contracts.quality as q
from lib.db.models.production_run import ModelObservationModel
from r2.quality.digests import compute_digest

DOMAIN = "m10.narrative-observation.v1"


@dataclass(frozen=True)
class StoredModelObservation:
    observation: q.NarrativeObservation
    digest: str
    run_id: str
    profile_id: str
    profile_revision: int
    profile_digest: str
    qualification_digest: str


class ModelObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        user_id: str,
        project_name: str,
        run_id: str,
        profile: q.QualityProfileRevision,
        observation: q.NarrativeObservation,
    ) -> q.NarrativeObservation:
        """The observation as stored: the new one, or the first recording when this one replays it."""
        observation = q.NarrativeObservation.model_validate(observation)
        prior = await self.session.get(ModelObservationModel, (user_id, project_name, observation.observation_id))
        if prior is not None:
            stored = q.NarrativeObservation.model_validate_json(prior.observation_json)
            replay = observation.model_copy(update={"observed_at": stored.observed_at})
            if compute_digest(DOMAIN, replay) != prior.observation_digest:
                raise ValueError("MODEL_OBSERVATION_REPLAY_CONFLICT")
            return stored
        digest = compute_digest(DOMAIN, observation)
        self.session.add(
            ModelObservationModel(
                user_id=user_id,
                project_name=project_name,
                observation_id=observation.observation_id,
                run_id=run_id,
                profile_id=profile.profile_id,
                profile_revision=profile.revision,
                profile_digest=profile.profile_digest,
                qualification_digest=observation.assessor_qualification_digest,
                observation_digest=digest,
                observation_json=observation.model_dump_json(),
                created_at=datetime.now(UTC),
            )
        )
        await self.session.flush()
        return observation

    async def get(self, *, user_id: str, project_name: str, observation_id: str) -> StoredModelObservation | None:
        row = await self.session.get(ModelObservationModel, (user_id, project_name, observation_id))
        if row is None:
            return None
        observation = q.NarrativeObservation.model_validate_json(row.observation_json)
        if compute_digest(DOMAIN, observation) != row.observation_digest:
            return None
        return StoredModelObservation(
            observation=observation,
            digest=row.observation_digest,
            run_id=row.run_id,
            profile_id=row.profile_id,
            profile_revision=row.profile_revision,
            profile_digest=row.profile_digest,
            qualification_digest=row.qualification_digest,
        )


__all__ = ["ModelObservationRepository", "StoredModelObservation"]
