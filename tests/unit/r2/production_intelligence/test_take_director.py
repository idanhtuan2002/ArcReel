"""Unit coverage for ``TakeDirectorAdapter`` (plan Task 13).

Exact approved/locked screenplay input, deterministic normalized SceneSpec/ShotSpecV2
output, no orphan/duplicate shots, only pinned Take vocabulary, stale admission
references, provider-field leakage, and no automatic cross-route fallback through the
real ``DirectorExecutionService``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.adaptation.errors import AdaptationNotFoundError
from r2.contracts import ContentBasis, ContentBasisType, DirectorFailure, DirectorKind, DirectorSuccess
from r2.contracts.adaptation import (
    AdaptationProfileId,
    AdaptationProfileRef,
    AdmittedScreenplayRef,
    ArtifactVersionRef,
    DecisionRef,
    ScreenplayArtifactV2,
    ScreenplayScene,
)
from r2.contracts.enums import CreativeApprovalStatus
from r2.contracts.production import CameraAngle, CameraMovement, ShotSize, ShotSpecV2
from r2.production_intelligence.director import (
    DirectorExecutionService,
    DirectorRouteUnavailable,
    DirectorRoutingPolicy,
    DirectorValidator,
)
from r2.production_intelligence.take_director import TakeDirectionResult, TakeDirectorAdapter

FORBIDDEN_PROVIDER_FIELDS = {"provider", "model", "endpoint", "payload", "provider_job_id"}
_CLOCK = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
USER = "u1"
PROJECT = "project-a"


def _profile_ref() -> AdaptationProfileRef:
    return AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC, profile_version="v1", policy_pack_digest="sha256:" + "a1" * 32
    )


def _scene(scene_id: str, *, dramatic_text: str = "INT. ROOM - DAY\nSomething happens.") -> ScreenplayScene:
    return ScreenplayScene(
        scene_id=scene_id,
        purpose="advance the plot",
        duration_target=30.0,
        location_ref=None,
        character_refs=["char-1"],
        source_mapping_refs=["entry-1"],
        dramatic_text=dramatic_text,
    )


def _screenplay(
    *, screenplay_id: str = "sp-1", version: int = 2, scenes: list[ScreenplayScene]
) -> ScreenplayArtifactV2:
    return ScreenplayArtifactV2(
        screenplay_id=screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        version=version,
        adaptation_branch_ref=ArtifactVersionRef(artifact_id="branch-1", version=1, content_hash="sha256:" + "b0" * 32),
        content_basis=ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="v1", refs=["src-1"]),
        scenes=scenes,
        characters=["char-1"],
        source_mapping_refs=["entry-1"],
        approval_status=CreativeApprovalStatus.APPROVED,
        locked_for_direction=True,
        content_hash="sha256:" + "c9" * 32,
        adaptation_map_ref=ArtifactVersionRef(artifact_id="map-1", version=1, content_hash="sha256:" + "d3" * 32),
        profile_analysis_refs=[],
    )


def _admitted_ref(screenplay: ScreenplayArtifactV2) -> AdmittedScreenplayRef:
    return AdmittedScreenplayRef(
        screenplay_ref=ArtifactVersionRef(
            artifact_id=screenplay.screenplay_id, version=screenplay.version, content_hash=screenplay.content_hash
        ),
        admission_ref=DecisionRef(decision_id="d-admit-1", decision_digest="sha256:" + "e7" * 32),
        profile_ref=_profile_ref(),
    )


class _FakeReader:
    def __init__(self, screenplay: ScreenplayArtifactV2 | None = None, *, error: Exception | None = None) -> None:
        self._screenplay = screenplay
        self._error = error
        self.calls: list[dict[str, object]] = []

    async def get_exact_admitted(self, *, user_id, project_name, screenplay_ref, admission_ref):
        self.calls.append(
            {
                "user_id": user_id,
                "project_name": project_name,
                "screenplay_ref": screenplay_ref,
                "admission_ref": admission_ref,
            }
        )
        if self._error is not None:
            raise self._error
        assert self._screenplay is not None
        return self._screenplay


# --- exact input / deterministic output -------------------------------------------------


async def test_direct_resolves_through_the_reader_with_exact_refs() -> None:
    screenplay = _screenplay(scenes=[_scene("scene-1"), _scene("scene-2")])
    admitted = _admitted_ref(screenplay)
    reader = _FakeReader(screenplay)
    adapter = TakeDirectorAdapter(reader, user_id=USER, project_name=PROJECT)

    result = await adapter.direct(admitted)

    assert isinstance(result, TakeDirectionResult)
    assert reader.calls == [
        {
            "user_id": USER,
            "project_name": PROJECT,
            "screenplay_ref": admitted.screenplay_ref,
            "admission_ref": admitted.admission_ref,
        }
    ]


async def test_direct_produces_one_scene_spec_and_one_shot_spec_per_scene() -> None:
    screenplay = _screenplay(scenes=[_scene("scene-1"), _scene("scene-2"), _scene("scene-3")])
    reader = _FakeReader(screenplay)
    adapter = TakeDirectorAdapter(reader, user_id=USER, project_name=PROJECT)

    result = await adapter.direct(_admitted_ref(screenplay))

    assert isinstance(result, TakeDirectionResult)
    assert len(result.scenes) == 3
    assert len(result.shots) == 3
    assert {scene.id for scene in result.scenes} == {"scene-1", "scene-2", "scene-3"}
    assert all(isinstance(shot, ShotSpecV2) for shot in result.shots)


async def test_direct_is_deterministic_for_identical_input() -> None:
    screenplay = _screenplay(scenes=[_scene("scene-1"), _scene("scene-2")])
    adapter_a = TakeDirectorAdapter(_FakeReader(screenplay), user_id=USER, project_name=PROJECT)
    adapter_b = TakeDirectorAdapter(_FakeReader(screenplay), user_id=USER, project_name=PROJECT)

    result_a = await adapter_a.direct(_admitted_ref(screenplay))
    result_b = await adapter_b.direct(_admitted_ref(screenplay))

    assert result_a == result_b


# --- no orphan / duplicate shots; only pinned vocabulary --------------------------------


async def test_no_shot_is_orphaned_or_duplicated() -> None:
    screenplay = _screenplay(scenes=[_scene("scene-1"), _scene("scene-2"), _scene("scene-3")])
    adapter = TakeDirectorAdapter(_FakeReader(screenplay), user_id=USER, project_name=PROJECT)

    result = await adapter.direct(_admitted_ref(screenplay))
    assert isinstance(result, TakeDirectionResult)

    scene_ids = {scene.id for scene in result.scenes}
    shot_ids = [shot.id for shot in result.shots]
    assert len(shot_ids) == len(set(shot_ids))  # no duplicates
    assert all(shot.scene_id in scene_ids for shot in result.shots)  # no orphans


async def test_every_shot_uses_only_the_pinned_take_vocabulary() -> None:
    screenplay = _screenplay(scenes=[_scene("scene-1")])
    adapter = TakeDirectorAdapter(_FakeReader(screenplay), user_id=USER, project_name=PROJECT)

    result = await adapter.direct(_admitted_ref(screenplay))
    assert isinstance(result, TakeDirectionResult)

    for shot in result.shots:
        assert shot.shot_size in set(ShotSize)
        assert shot.camera_angle in set(CameraAngle)
        assert shot.camera_movement in set(CameraMovement)


# --- stale admission reference -----------------------------------------------------------


async def test_direct_translates_a_stale_admission_into_route_unavailable() -> None:
    reader = _FakeReader(error=AdaptationNotFoundError("screenplay admission record does not resolve"))
    screenplay = _screenplay(scenes=[_scene("scene-1")])
    adapter = TakeDirectorAdapter(reader, user_id=USER, project_name=PROJECT)

    with pytest.raises(DirectorRouteUnavailable):
        await adapter.direct(_admitted_ref(screenplay))


async def test_direct_rejects_a_non_admitted_screenplay_ref_artifact() -> None:
    adapter = TakeDirectorAdapter(_FakeReader(), user_id=USER, project_name=PROJECT)
    with pytest.raises(DirectorRouteUnavailable):
        await adapter.direct(object())


# --- no provider-field leakage ------------------------------------------------------------


async def test_output_carries_no_provider_fields() -> None:
    screenplay = _screenplay(scenes=[_scene("scene-1")])
    adapter = TakeDirectorAdapter(_FakeReader(screenplay), user_id=USER, project_name=PROJECT)

    result = await adapter.direct(_admitted_ref(screenplay))
    assert isinstance(result, TakeDirectionResult)

    for scene in result.scenes:
        assert set(scene.model_dump(mode="json")).isdisjoint(FORBIDDEN_PROVIDER_FIELDS)
    for shot in result.shots:
        assert set(shot.model_dump(mode="json")).isdisjoint(FORBIDDEN_PROVIDER_FIELDS)


# --- end-to-end through the real DirectorExecutionService: no cross-route fallback -------


def _narrative_basis() -> ContentBasis:
    return ContentBasis(basis_type=ContentBasisType.NARRATIVE, basis_version="canon-v1", refs=["event:1"])


async def test_take_succeeds_end_to_end_through_director_execution_service() -> None:
    screenplay = _screenplay(scenes=[_scene("scene-1"), _scene("scene-2")])
    admitted = _admitted_ref(screenplay)
    adapter = TakeDirectorAdapter(_FakeReader(screenplay), user_id=USER, project_name=PROJECT)

    routing = DirectorRoutingPolicy(clock=lambda: _CLOCK).decide(
        input_profile_ref="profile:drama", content_basis=_narrative_basis()
    )
    service = DirectorExecutionService(validator=DirectorValidator(clock=lambda: _CLOCK), clock=lambda: _CLOCK)
    result = await service.execute(routing=routing, adapters={DirectorKind.TAKE: adapter}, artifact=admitted)

    assert isinstance(result, DirectorSuccess)
    assert result.actual_director is DirectorKind.TAKE
    assert len(result.shots) == 2
    assert isinstance(result.shots[0], ShotSpecV2)
    assert result.routing_decision_ref == routing.routing_decision_id


async def test_take_route_unavailable_does_not_automatically_cross_route_to_openmontage() -> None:
    routing = DirectorRoutingPolicy(clock=lambda: _CLOCK).decide(
        input_profile_ref="profile:drama", content_basis=_narrative_basis()
    )
    failing_take = TakeDirectorAdapter(
        _FakeReader(error=AdaptationNotFoundError("gone")), user_id=USER, project_name=PROJECT
    )

    class _OpenMontageSpy:
        director_kind = DirectorKind.OPENMONTAGE
        calls = 0

        async def direct(self, artifact: object) -> object:
            type(self).calls += 1
            raise AssertionError("OPENMONTAGE must never be called for a TAKE route")

    service = DirectorExecutionService(validator=DirectorValidator(clock=lambda: _CLOCK), clock=lambda: _CLOCK)
    result = await service.execute(
        routing=routing,
        adapters={DirectorKind.TAKE: failing_take, DirectorKind.OPENMONTAGE: _OpenMontageSpy()},
        artifact=_admitted_ref(_screenplay(scenes=[_scene("scene-1")])),
    )

    assert isinstance(result, DirectorFailure)
    assert _OpenMontageSpy.calls == 0
