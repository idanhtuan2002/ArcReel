"""Lineage-bound learning observations: identity, digest, admission and the cutoff fold (spec §6, §9).

An observation's identity is its scope plus source family and record, metric name and definition
version, and the exact metric window. One identity has exactly one original and a linear chain of
corrections; a correction never rewrites its predecessor. The server stamps ``ingested_at``, so the
observation digest excludes it and an exact re-send replays.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from r2.advanced_creative.digests import digest_canonical, digest_command
from r2.contracts.advanced_creative import ExperimentDesign, LearningObservation

INGEST_OBSERVATION = "INGEST_OBSERVATION"
MAX_SIGNIFICANT_DIGITS = 28
_EXPERIMENTS = frozenset({ExperimentDesign.CONCURRENT_RANDOMIZED, ExperimentDesign.PLATFORM_MANAGED})
LEARNING_ACTOR_SCOPE = "learning"


class MissingReason(StrEnum):
    MISSING = "MISSING"
    PRIVATE = "PRIVATE"
    DELETED = "DELETED"
    NOT_YET_AVAILABLE = "NOT_YET_AVAILABLE"


class ObservationInvalidError(ValueError):
    """The observation cannot be admitted in this scope as sent."""


@dataclass(frozen=True, order=True)
class ObservationIdentity:
    """Window instants are UTC, so a fold-ambiguous local time compares by instant."""

    source_family: str
    source_record_id: str
    metric_name: str
    metric_definition_version: str
    window_starts_at: datetime
    window_ends_at: datetime
    window_timezone_name: str
    window_aggregation: str


def identity_of(observation: LearningObservation) -> ObservationIdentity:
    window = observation.window
    return ObservationIdentity(
        source_family=observation.source_family,
        source_record_id=observation.source_record_id,
        metric_name=observation.metric_name,
        metric_definition_version=observation.metric_definition_version,
        window_starts_at=window.starts_at.astimezone(UTC),
        window_ends_at=window.ends_at.astimezone(UTC),
        window_timezone_name=window.timezone_name,
        window_aggregation=window.aggregation,
    )


def _semantic(observation: LearningObservation) -> dict[str, object]:
    return observation.model_dump(mode="python", exclude={"ingested_at"})


def observation_digest(observation: LearningObservation) -> str:
    """The digest of everything the source and caller assert; ``ingested_at`` is server time."""
    return digest_canonical({"contract_version": "1", "observation": _semantic(observation)})


def ingest_command_digest(*, user_id: str, project_name: str, observation: LearningObservation) -> str:
    return digest_command(INGEST_OBSERVATION, user_id, project_name, LEARNING_ACTOR_SCOPE, _semantic(observation))


def validate_observation(observation: LearningObservation, *, project_name: str) -> None:
    """Scope, window and value/missing-reason admissibility, independent of stored state."""
    if observation.lineage.project_name != project_name:
        raise ObservationInvalidError("observation lineage names another project")
    if observation.window.starts_at >= observation.window.ends_at:
        raise ObservationInvalidError("metric window must have positive length")
    if observation.correction_of == observation.observation_id:
        raise ObservationInvalidError("an observation cannot correct itself")
    for field in ("observation_id", "source_family", "source_record_id", "metric_name", "metric_definition_version"):
        if not getattr(observation, field):
            raise ObservationInvalidError(f"{field} is required")
    if observation.exposure_ref is not None and not observation.exposure_ref.strip():
        raise ObservationInvalidError("exposure_ref is blank")
    if observation.experiment_design in _EXPERIMENTS and observation.exposure_ref is None:
        raise ObservationInvalidError("a randomized or platform-managed observation names its exposure surface")
    if observation.metric_value is None:
        if observation.missing_reason not in set(MissingReason):
            raise ObservationInvalidError("a missing value needs a closed missing_reason")
    elif observation.missing_reason is not None:
        raise ObservationInvalidError("a present value takes no missing_reason")
    elif len(observation.metric_value.as_tuple().digits) > MAX_SIGNIFICANT_DIGITS:
        # Canonical digests normalize decimals at this precision; more digits would collide.
        raise ObservationInvalidError("metric_value has more significant digits than a digest keeps")


def validate_correction(correction: LearningObservation, predecessor: LearningObservation) -> None:
    """A correction keeps its predecessor's identity and changes what the source asserts."""
    if identity_of(correction) != identity_of(predecessor):
        raise ObservationInvalidError("a correction keeps its predecessor's identity")
    if correction.correction_of != predecessor.observation_id:
        raise ObservationInvalidError("a correction names its predecessor")


def current_as_of(observations: Iterable[LearningObservation], cutoff: datetime) -> tuple[LearningObservation, ...]:
    """Each identity's latest chain record ingested at or before ``cutoff``, sorted by identity.

    A chain follows ``correction_of`` from the single original. A record ingested after the cutoff
    hides itself and every later correction, so evidence pinned to a cutoff never moves.
    """
    by_id: dict[str, LearningObservation] = {}
    successor: dict[str, str] = {}
    originals: list[LearningObservation] = []
    for observation in observations:
        if observation.observation_id in by_id:
            raise ObservationInvalidError("duplicate observation id")
        by_id[observation.observation_id] = observation
        if observation.correction_of is None:
            originals.append(observation)
        elif successor.setdefault(observation.correction_of, observation.observation_id) != observation.observation_id:
            raise ObservationInvalidError("an observation has two corrections")
    current: dict[ObservationIdentity, LearningObservation] = {}
    for original in originals:
        identity = identity_of(original)
        if identity in current:
            raise ObservationInvalidError("an identity has two originals")
        chosen: LearningObservation | None = None
        node: LearningObservation | None = original
        while node is not None and node.ingested_at <= cutoff:
            chosen = node
            next_id = successor.get(node.observation_id)
            node = None if next_id is None else by_id.get(next_id)
        if chosen is not None:
            current[identity] = chosen
    return tuple(current[key] for key in sorted(current))


__all__ = [
    "INGEST_OBSERVATION",
    "LEARNING_ACTOR_SCOPE",
    "MissingReason",
    "ObservationIdentity",
    "ObservationInvalidError",
    "current_as_of",
    "identity_of",
    "ingest_command_digest",
    "observation_digest",
    "validate_correction",
    "validate_observation",
]
