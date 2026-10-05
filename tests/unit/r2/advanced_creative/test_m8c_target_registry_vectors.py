"""Proposed Take-derived target registry canonical vectors."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from r2.contracts import canonical_json_bytes
from r2.contracts.adaptation import AdmittedScreenplayRef, ArtifactVersionRef, DecisionRef, ScreenplayArtifactV2
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.production_intelligence.take_director import TakeDirectionResult, TakeDirectorAdapter
from r2.target_registry.digests import (
    registration_command_digest,
    registration_result_digest,
    target_body_digest,
    target_version_digest,
)

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_target_registry_vectors.json"


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


class _ExactReader:
    def __init__(self, screenplay: ScreenplayArtifactV2, admitted: AdmittedScreenplayRef) -> None:
        self.screenplay = screenplay
        self.admitted = admitted

    async def get_exact_admitted(
        self,
        *,
        user_id: str,
        project_name: str,
        screenplay_ref: ArtifactVersionRef,
        admission_ref: DecisionRef,
    ) -> ScreenplayArtifactV2:
        assert (user_id, project_name) == ("u1", "project-a")
        assert (screenplay_ref, admission_ref) == (self.admitted.screenplay_ref, self.admitted.admission_ref)
        return self.screenplay


def test_target_registry_vectors_have_fixed_preparation_bytes_and_digests() -> None:
    cases = _cases()
    assert set(cases) == {
        "scene_body_v1",
        "shot_body_v1",
        "scene_version_v1",
        "shot_version_v1",
        "scene_body_v2",
        "shot_body_v2",
        "scene_version_v2",
        "shot_version_v2",
        "registration_command_v1",
        "registration_result_v1",
        "registration_command_v2",
        "registration_result_v2",
    }
    for name, case in cases.items():
        envelope = {"domain": case["domain"], "canonical_version": "1", "body": case["body"]}
        expected = case["canonical"].encode("utf-8")
        assert canonical_json_bytes(envelope) == expected, name
        assert "sha256:" + hashlib.sha256(expected).hexdigest() == case["digest"], name
        assert "object_ref" not in case["canonical"], name


def test_target_registry_versions_bind_real_take_bodies_and_admissions() -> None:
    cases = _cases()
    for suffix in ("v1", "v2"):
        scene_body = cases[f"scene_body_{suffix}"]["body"]
        shot_body = cases[f"shot_body_{suffix}"]["body"]
        assert SceneSpec.model_validate(scene_body["target"]).model_dump(mode="json") == scene_body["target"]
        assert ShotSpecV2.model_validate(shot_body["target"]).model_dump(mode="json") == shot_body["target"]
        assert shot_body["target"]["scene_id"] == scene_body["target"]["id"]
        scene_version = cases[f"scene_version_{suffix}"]["body"]
        shot_version = cases[f"shot_version_{suffix}"]["body"]
        assert scene_version["target_body_digest"] == cases[f"scene_body_{suffix}"]["digest"]
        assert shot_version["target_body_digest"] == cases[f"shot_body_{suffix}"]["digest"]
        assert scene_version["admitted_screenplay_ref"] == shot_version["admitted_screenplay_ref"]
        assert shot_version["scene_dependency"] == {
            "target_type": "SCENE",
            "target_id": scene_version["target_id"],
            "registry_version": scene_version["registry_version"],
            "target_version_digest": cases[f"scene_version_{suffix}"]["digest"],
        }
    assert cases["scene_body_v1"]["body"]["target"]["version"] == 1
    assert cases["scene_body_v2"]["body"]["target"]["version"] == 1
    assert cases["scene_version_v1"]["body"]["registry_version"] == 1
    assert cases["scene_version_v2"]["body"]["registry_version"] == 2
    assert cases["scene_body_v1"]["digest"] != cases["scene_body_v2"]["digest"]
    assert cases["shot_body_v1"]["digest"] != cases["shot_body_v2"]["digest"]
    assert (
        cases["scene_version_v1"]["body"]["admitted_screenplay_ref"]
        != cases["scene_version_v2"]["body"]["admitted_screenplay_ref"]
    )
    assert cases["scene_body_v2"]["body"]["target"]["duration_target"] == 1e-7
    assert '"duration_target":1e-07' in cases["scene_body_v2"]["canonical"]


def test_target_registry_body_vectors_match_take_derivation() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = _cases()
    for suffix in ("v1", "v2"):
        screenplay = ScreenplayArtifactV2.model_validate(payload["screenplays"][suffix])
        admitted = AdmittedScreenplayRef.model_validate(
            cases[f"scene_version_{suffix}"]["body"]["admitted_screenplay_ref"]
        )
        assert admitted.screenplay_ref.content_hash == screenplay.content_hash
        result = asyncio.run(
            TakeDirectorAdapter(_ExactReader(screenplay, admitted), user_id="u1", project_name="project-a").direct(
                admitted
            )
        )
        assert isinstance(result, TakeDirectionResult)
        assert [scene.model_dump(mode="json") for scene in result.scenes] == [
            cases[f"scene_body_{suffix}"]["body"]["target"]
        ]
        assert [shot.model_dump(mode="json") for shot in result.shots] == [
            cases[f"shot_body_{suffix}"]["body"]["target"]
        ]


def test_registration_receipt_vectors_bind_full_admission_and_ordered_target_versions() -> None:
    cases = _cases()
    for suffix in ("v1", "v2"):
        command = cases[f"registration_command_{suffix}"]
        result = cases[f"registration_result_{suffix}"]
        scene = cases[f"scene_version_{suffix}"]
        shot = cases[f"shot_version_{suffix}"]
        assert command["body"]["admitted_screenplay_ref"] == scene["body"]["admitted_screenplay_ref"]
        assert result["body"]["command_digest"] == command["digest"]
        assert result["body"]["scene_targets"] == [
            {
                "target_type": "SCENE",
                "target_id": scene["body"]["target_id"],
                "registry_version": scene["body"]["registry_version"],
                "version_digest": scene["digest"],
            }
        ]
        assert result["body"]["shot_targets"] == [
            {
                "target_type": "SHOT",
                "target_id": shot["body"]["target_id"],
                "registry_version": shot["body"]["registry_version"],
                "version_digest": shot["digest"],
            }
        ]
    assert cases["registration_command_v1"]["digest"] != cases["registration_command_v2"]["digest"]
    assert cases["registration_result_v1"]["digest"] != cases["registration_result_v2"]["digest"]


def test_registry_digest_helpers_match_fixed_target_and_receipt_vectors() -> None:
    cases = _cases()
    for suffix in ("v1", "v2"):
        scene_body = cases[f"scene_body_{suffix}"]
        shot_body = cases[f"shot_body_{suffix}"]
        assert (
            target_body_digest("SCENE", SceneSpec.model_validate(scene_body["body"]["target"])) == scene_body["digest"]
        )
        assert target_body_digest("SHOT", ShotSpecV2.model_validate(shot_body["body"]["target"])) == shot_body["digest"]
        for kind in ("scene", "shot"):
            version = cases[f"{kind}_version_{suffix}"]
            assert target_version_digest(version["body"]) == version["digest"]
        command = cases[f"registration_command_{suffix}"]
        result = cases[f"registration_result_{suffix}"]
        assert registration_command_digest(command["body"]) == command["digest"]
        assert registration_result_digest(result["body"]) == result["digest"]


def test_registry_digest_helpers_reject_mismatched_type_dependency_and_order() -> None:
    cases = _cases()
    scene = SceneSpec.model_validate(cases["scene_body_v1"]["body"]["target"])
    with pytest.raises(ValueError, match="target type does not match"):
        target_body_digest("SHOT", scene)
    with pytest.raises(ValueError, match="not a valid ProductionBindingTarget"):
        target_body_digest("FORMAT", scene)

    shot_version = cases["shot_version_v1"]["body"]
    with pytest.raises(ValueError, match="only a SHOT target version"):
        target_version_digest(shot_version | {"scene_dependency": None})

    result = cases["registration_result_v1"]["body"]
    with pytest.raises(ValueError, match="typed, unique and sorted"):
        registration_result_digest(result | {"scene_targets": result["scene_targets"] * 2})
