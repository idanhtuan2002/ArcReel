"""``TakeDirectorAdapter`` — the M6 ``TAKE``-family ``DirectorAdapter`` (plan Task 13).

Pure and provider-neutral: its only input is an ``AdmittedScreenplayRef``, its only
dependency is the read-only ``ApprovedScreenplayReader`` (Task 12), and its only output
is a raw ``scenes``/``shots`` bundle of ``SceneSpec``/``ShotSpecV2`` — mirroring how
``OpenMontageDirectorAdapter``'s M3 backend returns a raw direction result rather than a
pre-built ``DirectorSuccess``. ``DirectorValidator.normalize`` (not this adapter) stamps
the routing/attempted-director identity and runs the shared contract/semantic checks
(no shots, an orphan shot referencing an unknown scene, and so on); this adapter has no
access to the ``RoutingDecision`` and never fabricates one. Provider identity, jobs,
candidates, retries, budgets and master approval never appear here — those stay
downstream of the Director boundary, exactly like every other adapter.

Shot breakdown is deliberately minimal: exactly one canonical ``ShotSpecV2`` per scene,
always the pinned Take vocabulary's neutral default (``MEDIUM``/``EYE_LEVEL``/
``STATIC``). This adapter has no creative shot-blocking intelligence — that is out of
scope for M6 — so it never fabricates a value outside the closed
``ShotSize``/``CameraAngle``/``CameraMovement`` enums and never varies shot count by
scene content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from r2.adaptation.errors import AdaptationError
from r2.contracts import DirectorKind, ProductionMethod, SceneSpec
from r2.contracts.adaptation import (
    AdmittedScreenplayRef,
    ArtifactVersionRef,
    DecisionRef,
    ScreenplayArtifactV2,
    ScreenplayScene,
)
from r2.contracts.production import CameraAngle, CameraMovement, ShotSize, ShotSpecV2
from r2.production_intelligence.director import DirectorRouteUnavailable

_SCENE_SPEC_SCHEMA_VERSION = "r2-take-scene-spec-v1"
_SHOT_SPEC_SCHEMA_VERSION = "r2-shot-spec-v2"
_TAKE_ALLOWED_METHODS = [ProductionMethod.GENERATED_VIDEO]
TAKE_DERIVATION_VERSION = "r2-take-director-v1"


@runtime_checkable
class ApprovedScreenplayReaderPort(Protocol):
    """The one method ``TakeDirectorAdapter`` needs from Task 12's
    ``ApprovedScreenplayReader`` — a structural port so this module stays testable and
    provider/persistence-neutral without importing the concrete DB-backed reader."""

    async def get_exact_admitted(
        self,
        *,
        user_id: str,
        project_name: str,
        screenplay_ref: ArtifactVersionRef,
        admission_ref: DecisionRef,
    ) -> ScreenplayArtifactV2: ...


@dataclass(frozen=True)
class TakeDirectionResult:
    scenes: tuple[SceneSpec, ...]
    shots: tuple[ShotSpecV2, ...]


def _scene_spec(scene: ScreenplayScene, *, screenplay: ScreenplayArtifactV2) -> SceneSpec:
    return SceneSpec(
        id=scene.scene_id,
        schema_version=_SCENE_SPEC_SCHEMA_VERSION,
        version=1,
        source_artifact_ref=screenplay.screenplay_id,
        source_unit_refs=list(scene.source_mapping_refs),
        content_basis=screenplay.content_basis,
        purpose=scene.purpose,
        duration_target=scene.duration_target,
        temporal_context=None,
        location_ref=scene.location_ref,
        entity_refs=list(scene.character_refs),
        required_beats=[],
        continuity_requirements=[],
        allowed_methods=list(_TAKE_ALLOWED_METHODS),
        approval_status=screenplay.approval_status,
    )


def _shot_spec(scene: ScreenplayScene, *, screenplay: ScreenplayArtifactV2) -> ShotSpecV2:
    return ShotSpecV2(
        id=f"{scene.scene_id}-TAKE-1",
        schema_version=_SHOT_SPEC_SCHEMA_VERSION,
        version=1,
        scene_id=scene.scene_id,
        content_basis=screenplay.content_basis,
        purpose=scene.purpose,
        target_duration=scene.duration_target,
        framing=ShotSize.MEDIUM.value,
        camera=CameraMovement.STATIC.value,
        shot_size=ShotSize.MEDIUM,
        camera_angle=CameraAngle.EYE_LEVEL,
        camera_movement=CameraMovement.STATIC,
        entity_refs=list(scene.character_refs),
        audio_intent=None,
        required_continuity=[],
        required_reference_roles=[],
        allowed_methods=list(_TAKE_ALLOWED_METHODS),
        quality_tier=0,
        approval_status=screenplay.approval_status,
    )


class TakeDirectorAdapter:
    """Scoped to one exact ``(user_id, project_name)`` at construction — the shared
    ``DirectorAdapter.direct(artifact)`` signature carries no tenant scope of its own,
    so whoever wires a Director run for a given user/project builds a fresh adapter
    instance for it, exactly as every other adaptation service takes its scope at the
    call site rather than smuggling it through a generic artifact type."""

    director_kind: DirectorKind = DirectorKind.TAKE

    def __init__(self, reader: ApprovedScreenplayReaderPort, *, user_id: str, project_name: str) -> None:
        self._reader = reader
        self._user_id = user_id
        self._project_name = project_name

    async def direct(self, artifact: object) -> object:
        if not isinstance(artifact, AdmittedScreenplayRef):
            raise DirectorRouteUnavailable(
                f"TakeDirectorAdapter requires an AdmittedScreenplayRef, got {type(artifact).__name__}"
            )

        try:
            screenplay = await self._reader.get_exact_admitted(
                user_id=self._user_id,
                project_name=self._project_name,
                screenplay_ref=artifact.screenplay_ref,
                admission_ref=artifact.admission_ref,
            )
        except AdaptationError as exc:
            raise DirectorRouteUnavailable(
                f"admitted screenplay {artifact.screenplay_ref.artifact_id!r} does not resolve: {exc}"
            ) from exc

        scenes = tuple(_scene_spec(scene, screenplay=screenplay) for scene in screenplay.scenes)
        shots = tuple(_shot_spec(scene, screenplay=screenplay) for scene in screenplay.scenes)
        return TakeDirectionResult(scenes=scenes, shots=shots)


__all__ = ["TAKE_DERIVATION_VERSION", "ApprovedScreenplayReaderPort", "TakeDirectionResult", "TakeDirectorAdapter"]
