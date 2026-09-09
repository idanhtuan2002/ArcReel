"""Deterministic semantic identities for SceneContract and NarrativePlan content.

Scene semantic hashing excludes ``version``, the hash fields, and commit metadata but
covers every executable field. Plan content hashing covers scene IDs / versions /
semantic hashes, the ordered hierarchy, the story frame, and the exact Canon basis.
"""

from __future__ import annotations

import hashlib

from r2.contracts import canonical_json_bytes, ensure_json_value
from r2.contracts.narrative_plan import NarrativePlanContent, SceneContract

_SCENE_HASH_EXCLUDED = {"version", "semantic_hash", "semantic_hash_algorithm", "semantic_hash_version"}
SCENE_SEMANTIC_HASH_SCHEMA = "r2-scene-contract-content-v1"
PLAN_CONTENT_HASH_SCHEMA = "r2-narrative-plan-content-v1"


def _sha256_ref(prefix: str, payload: object) -> str:
    return prefix + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()


def compute_scene_semantic_hash(scene: SceneContract) -> str:
    body = scene.model_dump(mode="json", exclude=set(_SCENE_HASH_EXCLUDED))
    return _sha256_ref("sh:", {"schema": SCENE_SEMANTIC_HASH_SCHEMA, "body": body})


def compute_plan_content_hash(content: NarrativePlanContent) -> str:
    scene_identities = [
        {
            "scene_contract_id": scene.scene_contract_id,
            "version": scene.version,
            "semantic_hash": scene.semantic_hash,
        }
        for scene in content.scene_contracts
    ]
    payload = {
        "schema": PLAN_CONTENT_HASH_SCHEMA,
        "schema_version": content.schema_version,
        "parent_version": content.parent_version,
        "canon_basis": content.canon_basis.model_dump(mode="json"),
        "story_frame": content.story_frame,
        "volume_plans": [node.model_dump(mode="json") for node in content.volume_plans],
        "episode_plans": [node.model_dump(mode="json") for node in content.episode_plans],
        "arc_plans": [node.model_dump(mode="json") for node in content.arc_plans],
        "chapter_plans": [node.model_dump(mode="json") for node in content.chapter_plans],
        "scene_identities": scene_identities,
    }
    return _sha256_ref("np:", payload)
