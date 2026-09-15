"""Unit coverage for the M6 immutable profile-pack registry (plan Task 8).

Exact profile/version/digest lookup, manifest tamper, duplicate rule ID, invalid
disposition/applicability, cross-profile rule, and the forbidden runtime latest/hot
reload surface. ``verify_manifest_bytes`` is exercised directly against constructed
manifests for the structural-failure cases; ``ProfilePackRegistry.resolve`` is
exercised against the two real, packaged manifests for the exact-lookup cases.
"""

from __future__ import annotations

import copy
import json

import pytest

from r2.adaptation.errors import (
    AdaptationNotFoundError,
    AdaptationPolicyDigestMismatchError,
    AdaptationPolicyPackIntegrityError,
)
from r2.adaptation.profiles import (
    _PACKS_DIR,
    ProfilePack,
    ProfilePackRegistry,
    _compute_policy_pack_digest,
    verify_manifest_bytes,
)
from r2.contracts.adaptation import AdaptationProfileId, AdaptationProfileRef


def _minimal_manifest(
    *, profile_id: str = "WESTERN_GENERIC", profile_version: str = "v1", rule_applicability: str = "ALWAYS"
) -> dict:
    return {
        "profile_id": profile_id,
        "profile_version": profile_version,
        "evaluator_version": "test-evaluator-v1",
        "source_identity": "test manifest",
        "rules": [
            {
                "rule_id": "R1",
                "rule_version": "v1",
                "disposition": "INTEGRITY_BLOCK",
                "applicability": rule_applicability,
                "description": "test rule",
            }
        ],
    }


def _real_bytes(filename: str) -> bytes:
    return (_PACKS_DIR / filename).read_bytes()


def _real_digest(filename: str) -> str:
    raw = json.loads(_real_bytes(filename))
    return _compute_policy_pack_digest(raw)


# --- exact lookup ------------------------------------------------------------------


def test_registry_resolves_the_real_western_generic_pack() -> None:
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v1",
        policy_pack_digest=_real_digest("western_generic_v1.json"),
    )
    pack = ProfilePackRegistry().resolve(ref)
    assert isinstance(pack, ProfilePack)
    assert pack.evaluator_version == "r2-m6-western-evaluator-v1"
    assert any(rule.rule_id == "WESTERN_SCENE_HEADING_STRUCTURE" for rule in pack.rules)
    assert any(rule.applicability.value == "ALWAYS" for rule in pack.rules)


def test_registry_resolves_the_real_shuangwen_pack() -> None:
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
        profile_version="v1",
        policy_pack_digest=_real_digest("cn_short_drama_shuangwen_v1.json"),
    )
    pack = ProfilePackRegistry().resolve(ref)
    assert pack.evaluator_version == "r2-m6-shuangwen-evaluator-v1"
    assert any(rule.rule_id == "SHUANGWEN_TYPE_VOCABULARY" for rule in pack.rules)


def test_registry_resolve_is_deterministic() -> None:
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v1",
        policy_pack_digest=_real_digest("western_generic_v1.json"),
    )
    registry = ProfilePackRegistry()
    first = registry.resolve(ref)
    second = registry.resolve(ref)
    assert first.rules == second.rules
    assert first.canonical_bytes == second.canonical_bytes


def test_registry_rejects_an_unknown_profile_version() -> None:
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v2",
        policy_pack_digest=_real_digest("western_generic_v1.json"),
    )
    with pytest.raises(AdaptationNotFoundError):
        ProfilePackRegistry().resolve(ref)


# --- manifest tamper (digest mismatch) ----------------------------------------------


def test_registry_rejects_a_wrong_digest() -> None:
    ref = AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC, profile_version="v1", policy_pack_digest="sha256:" + "00" * 32
    )
    with pytest.raises(AdaptationPolicyDigestMismatchError):
        ProfilePackRegistry().resolve(ref)


def test_verify_manifest_bytes_rejects_tampered_content_under_the_original_digest() -> None:
    original_digest = _real_digest("western_generic_v1.json")
    tampered = json.loads(_real_bytes("western_generic_v1.json"))
    tampered["rules"][0]["description"] = "tampered"
    with pytest.raises(AdaptationPolicyDigestMismatchError):
        verify_manifest_bytes(json.dumps(tampered).encode("utf-8"), original_digest)


def test_verify_manifest_bytes_rejects_malformed_json() -> None:
    with pytest.raises(AdaptationPolicyPackIntegrityError):
        verify_manifest_bytes(b"{not json", "sha256:" + "00" * 32)


# --- structural validation: duplicate rule id / invalid disposition/applicability ----


def test_verify_manifest_bytes_rejects_a_duplicate_rule_id() -> None:
    manifest = _minimal_manifest()
    manifest["rules"].append(dict(manifest["rules"][0]))
    digest = _compute_policy_pack_digest(manifest)
    with pytest.raises(AdaptationPolicyPackIntegrityError, match="reuses rule id"):
        verify_manifest_bytes(json.dumps(manifest).encode("utf-8"), digest)


def test_verify_manifest_bytes_rejects_an_invalid_disposition() -> None:
    manifest = _minimal_manifest()
    manifest["rules"][0]["disposition"] = "NOT_A_REAL_DISPOSITION"
    digest = _compute_policy_pack_digest(manifest)
    with pytest.raises(AdaptationPolicyPackIntegrityError):
        verify_manifest_bytes(json.dumps(manifest).encode("utf-8"), digest)


def test_verify_manifest_bytes_rejects_an_invalid_applicability() -> None:
    manifest = _minimal_manifest(rule_applicability="NOT_A_REAL_APPLICABILITY")
    digest = _compute_policy_pack_digest(manifest)
    with pytest.raises(AdaptationPolicyPackIntegrityError):
        verify_manifest_bytes(json.dumps(manifest).encode("utf-8"), digest)


def test_verify_manifest_bytes_rejects_a_cross_profile_rule() -> None:
    manifest = _minimal_manifest(profile_id="WESTERN_GENERIC", rule_applicability="CN_SHORT_DRAMA_SHUANGWEN")
    digest = _compute_policy_pack_digest(manifest)
    with pytest.raises(AdaptationPolicyPackIntegrityError, match="neither ALWAYS nor"):
        verify_manifest_bytes(json.dumps(manifest).encode("utf-8"), digest)


def test_verify_manifest_bytes_accepts_a_rule_scoped_to_its_own_profile() -> None:
    manifest = _minimal_manifest(profile_id="CN_SHORT_DRAMA_SHUANGWEN", rule_applicability="CN_SHORT_DRAMA_SHUANGWEN")
    digest = _compute_policy_pack_digest(manifest)
    pack = verify_manifest_bytes(json.dumps(manifest).encode("utf-8"), digest)
    assert pack.rules[0].applicability.value == "CN_SHORT_DRAMA_SHUANGWEN"


def test_the_two_real_packs_carry_no_duplicate_or_cross_profile_rule() -> None:
    for filename, profile_id in (
        ("western_generic_v1.json", "WESTERN_GENERIC"),
        ("cn_short_drama_shuangwen_v1.json", "CN_SHORT_DRAMA_SHUANGWEN"),
    ):
        raw = json.loads(_real_bytes(filename))
        digest = _compute_policy_pack_digest(raw)
        pack = verify_manifest_bytes(_real_bytes(filename), digest)
        assert len({rule.rule_id for rule in pack.rules}) == len(pack.rules)
        for rule in pack.rules:
            assert rule.applicability.value in ("ALWAYS", profile_id)


def test_manifest_immutability_ignores_a_mutated_copy() -> None:
    """Sanity: mutating a deep copy of a real manifest never affects the packaged
    file or a freshly resolved pack's own content."""
    raw = copy.deepcopy(json.loads(_real_bytes("western_generic_v1.json")))
    raw["rules"][0]["description"] = "mutated copy only"
    fresh = json.loads(_real_bytes("western_generic_v1.json"))
    assert fresh["rules"][0]["description"] != "mutated copy only"


# --- forbidden runtime latest / hot reload / executable rule DSL --------------------


def test_registry_exposes_no_latest_or_reload_method() -> None:
    public_methods = {name for name in dir(ProfilePackRegistry) if not name.startswith("_")}
    assert public_methods == {"resolve"}
