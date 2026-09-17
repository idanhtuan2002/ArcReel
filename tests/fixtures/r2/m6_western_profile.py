"""Fixture screenplays for the M6 Western-generic evaluator (plan Task 9).

Plain builder functions only — no fixtures, no service wiring, no database. Every id
and hash is fixed, so two calls produce equal values.
"""

from __future__ import annotations

from r2.adaptation.hashing import compute_adaptation_hash
from r2.contracts.adaptation import ArtifactVersionRef, ScreenplayArtifactV2, ScreenplayScene
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, CreativeApprovalStatus

_BRANCH_REF = ArtifactVersionRef(artifact_id="branch-1", version=1, content_hash="sha256:" + "a1" * 32)
_MAP_REF = ArtifactVersionRef(artifact_id="map-1", version=1, content_hash="sha256:" + "b2" * 32)


def _scene(
    *,
    scene_id: str,
    dramatic_text: str,
    source_mapping_refs: list[str] | None = None,
    character_refs: list[str] | None = None,
) -> ScreenplayScene:
    return ScreenplayScene(
        scene_id=scene_id,
        purpose="advance the plot",
        duration_target=30.0,
        location_ref=None,
        character_refs=character_refs or ["char-1"],
        source_mapping_refs=source_mapping_refs or ["entry-1"],
        dramatic_text=dramatic_text,
    )


def _screenplay(*, scenes: list[ScreenplayScene], source_mapping_refs: list[str] | None = None) -> ScreenplayArtifactV2:
    draft = ScreenplayArtifactV2(
        screenplay_id="screenplay-1",
        schema_version="r2-screenplay-artifact-v2",
        version=1,
        adaptation_branch_ref=_BRANCH_REF,
        content_basis=ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="v1", refs=["src-1"]),
        scenes=scenes,
        characters=["char-1"],
        source_mapping_refs=source_mapping_refs or ["entry-1"],
        approval_status=CreativeApprovalStatus.DRAFT,
        locked_for_direction=False,
        content_hash="pending",
        adaptation_map_ref=_MAP_REF,
        profile_analysis_refs=[],
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


def golden_western_screenplay() -> ScreenplayArtifactV2:
    """Passes every WESTERN_* structural rule with no findings."""
    return _screenplay(
        scenes=[
            _scene(
                scene_id="scene-1",
                dramatic_text="INT. DINER - NIGHT\nMARA stares at the empty booth. Rain streaks the window.",
            ),
            _scene(
                scene_id="scene-2",
                dramatic_text="EXT. HIGHWAY - DAWN\nMARA walks the shoulder, thumb out, headlights approaching.",
            ),
        ]
    )


def screenplay_with_bad_scene_heading() -> ScreenplayArtifactV2:
    return _screenplay(
        scenes=[
            _scene(scene_id="scene-1", dramatic_text="MARA sits alone.\nShe says nothing."),
        ]
    )


def screenplay_with_unseparated_action() -> ScreenplayArtifactV2:
    return _screenplay(
        scenes=[
            _scene(scene_id="scene-1", dramatic_text="INT. DINER - NIGHT"),
        ]
    )


def screenplay_with_interiority_leak() -> ScreenplayArtifactV2:
    return _screenplay(
        scenes=[
            _scene(scene_id="scene-1", dramatic_text="INT. DINER - NIGHT\nMara thinks that she should leave."),
        ]
    )


def screenplay_with_orphan_reference() -> ScreenplayArtifactV2:
    return _screenplay(
        scenes=[
            _scene(
                scene_id="scene-1",
                dramatic_text="INT. DINER - NIGHT\nMara waits.",
                source_mapping_refs=["entry-1", "entry-orphan"],
            ),
        ],
        source_mapping_refs=["entry-1"],
    )


def screenplay_with_duplicate_scene_id() -> ScreenplayArtifactV2:
    scene = _scene(scene_id="scene-1", dramatic_text="INT. DINER - NIGHT\nMara waits.")
    return _screenplay(scenes=[scene, scene.model_copy(update={"purpose": "a second beat"})])


def slow_burn_screenplay() -> ScreenplayArtifactV2:
    """A deliberately unresolved, slow-burn excerpt — must never trip a block on
    rubric grounds; only advisory observations are ever emitted for rubric concepts."""
    return _screenplay(
        scenes=[
            _scene(
                scene_id="scene-1", dramatic_text="INT. DINER - NIGHT\nMara waits. Nothing happens. She waits more."
            ),
            _scene(scene_id="scene-2", dramatic_text="INT. DINER - NIGHT\nStill nothing. The coffee goes cold."),
        ]
    )
