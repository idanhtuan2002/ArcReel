from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from r2.contracts import SceneSpec, ScriptArtifact, ShotSpec


@dataclass(frozen=True)
class GoldenADirectionResult:
    scenes: tuple[SceneSpec, ...]
    shots: tuple[ShotSpec, ...]


class GoldenAOpenMontageBackend(Protocol):
    def direct(self, script: ScriptArtifact) -> GoldenADirectionResult: ...


class FixtureOpenMontageBackend:
    def direct(self, script: ScriptArtifact) -> GoldenADirectionResult:
        if script.id != "SCRIPT-GOLDEN-A":
            raise ValueError("Fixture backend only accepts Golden A")
        scenes_data = [
            {
                "id": "SC01",
                "schema_version": "1",
                "version": 1,
                "source_artifact_ref": "SCRIPT-GOLDEN-A",
                "source_unit_refs": ["SEC-01"],
                "content_basis": {
                    "basis_type": "FACTUAL",
                    "basis_version": "golden-a-v1",
                    "refs": ["research:RP-GOLDEN-A", "claim:CLAIM-001"],
                },
                "purpose": "Explain SEC-01",
                "duration_target": 22.0,
                "temporal_context": None,
                "location_ref": None,
                "entity_refs": [],
                "required_beats": ["beat:SEC-01"],
                "continuity_requirements": [],
                "allowed_methods": ["REUSE"],
                "approval_status": "APPROVED",
            },
            {
                "id": "SC02",
                "schema_version": "1",
                "version": 1,
                "source_artifact_ref": "SCRIPT-GOLDEN-A",
                "source_unit_refs": ["SEC-02"],
                "content_basis": {
                    "basis_type": "FACTUAL",
                    "basis_version": "golden-a-v1",
                    "refs": ["research:RP-GOLDEN-A", "claim:CLAIM-002"],
                },
                "purpose": "Explain SEC-02",
                "duration_target": 25.0,
                "temporal_context": None,
                "location_ref": None,
                "entity_refs": [],
                "required_beats": ["beat:SEC-02"],
                "continuity_requirements": [],
                "allowed_methods": ["DETERMINISTIC"],
                "approval_status": "APPROVED",
            },
            {
                "id": "SC03",
                "schema_version": "1",
                "version": 1,
                "source_artifact_ref": "SCRIPT-GOLDEN-A",
                "source_unit_refs": ["SEC-03"],
                "content_basis": {
                    "basis_type": "FACTUAL",
                    "basis_version": "golden-a-v1",
                    "refs": ["research:RP-GOLDEN-A", "claim:CLAIM-003"],
                },
                "purpose": "Explain SEC-03",
                "duration_target": 25.0,
                "temporal_context": None,
                "location_ref": None,
                "entity_refs": [],
                "required_beats": ["beat:SEC-03"],
                "continuity_requirements": [],
                "allowed_methods": ["DETERMINISTIC"],
                "approval_status": "APPROVED",
            },
        ]
        shots_data = [
            {
                "id": "SH01",
                "schema_version": "1",
                "version": 1,
                "scene_id": "SC01",
                "content_basis": {
                    "basis_type": "FACTUAL",
                    "basis_version": "golden-a-v1",
                    "refs": ["research:RP-GOLDEN-A"],
                },
                "purpose": "Visualize SH01",
                "target_duration": 22.0,
                "framing": "graphic",
                "camera": "static",
                "entity_refs": [],
                "audio_intent": "narration",
                "required_continuity": [],
                "required_reference_roles": [],
                "allowed_methods": ["REUSE"],
                "quality_tier": 1,
                "approval_status": "APPROVED",
            },
            {
                "id": "SH02",
                "schema_version": "1",
                "version": 1,
                "scene_id": "SC02",
                "content_basis": {
                    "basis_type": "FACTUAL",
                    "basis_version": "golden-a-v1",
                    "refs": ["research:RP-GOLDEN-A"],
                },
                "purpose": "Visualize SH02",
                "target_duration": 12.0,
                "framing": "graphic",
                "camera": "static",
                "entity_refs": [],
                "audio_intent": "narration",
                "required_continuity": [],
                "required_reference_roles": [],
                "allowed_methods": ["DETERMINISTIC"],
                "quality_tier": 1,
                "approval_status": "APPROVED",
            },
            {
                "id": "SH03",
                "schema_version": "1",
                "version": 1,
                "scene_id": "SC02",
                "content_basis": {
                    "basis_type": "FACTUAL",
                    "basis_version": "golden-a-v1",
                    "refs": ["research:RP-GOLDEN-A"],
                },
                "purpose": "Visualize SH03",
                "target_duration": 13.0,
                "framing": "graphic",
                "camera": "static",
                "entity_refs": [],
                "audio_intent": "narration",
                "required_continuity": [],
                "required_reference_roles": [],
                "allowed_methods": ["DETERMINISTIC"],
                "quality_tier": 1,
                "approval_status": "APPROVED",
            },
            {
                "id": "SH04",
                "schema_version": "1",
                "version": 1,
                "scene_id": "SC03",
                "content_basis": {
                    "basis_type": "FACTUAL",
                    "basis_version": "golden-a-v1",
                    "refs": ["research:RP-GOLDEN-A"],
                },
                "purpose": "Visualize SH04",
                "target_duration": 25.0,
                "framing": "graphic",
                "camera": "static",
                "entity_refs": [],
                "audio_intent": "narration",
                "required_continuity": [],
                "required_reference_roles": [],
                "allowed_methods": ["DETERMINISTIC"],
                "quality_tier": 1,
                "approval_status": "APPROVED",
            },
        ]
        return GoldenADirectionResult(
            tuple(SceneSpec.model_validate(x) for x in scenes_data),
            tuple(ShotSpec.model_validate(x) for x in shots_data),
        )


class GoldenAOpenMontageAdapter:
    def __init__(self, backend: GoldenAOpenMontageBackend) -> None:
        self._backend = backend

    def direct(self, script: ScriptArtifact) -> GoldenADirectionResult:
        result = self._backend.direct(script)
        if not result.scenes or not result.shots:
            raise ValueError("director produced empty direction")
        return result
