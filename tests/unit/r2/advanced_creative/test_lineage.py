"""Server-resolved M8 lineage: version 1 (ADR-0098) and version 2 (ADR-0105)."""

from __future__ import annotations

import hashlib

import pytest

from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.errors import LineageAmbiguousError, LineageEpisodeOutOfScopeError
from r2.advanced_creative.lineage import host_policy_digest, project_profile, resolve_episode_lineage
from r2.contracts.adaptation import (
    AdaptationProfileId,
    AdaptationProfileRef,
    AdmittedScreenplayRef,
    ArtifactVersionRef,
    DecisionRef,
)


def test_the_content_basis_binds_the_episode_and_its_script_bytes() -> None:
    lineage = resolve_episode_lineage("demo", 2, b'{"a":1}')

    assert lineage.content_basis_digest == digest_canonical(
        {
            "basis_kind": "host_episode_script",
            "episode": 2,
            "script_digest": "sha256:" + hashlib.sha256(b'{"a":1}').hexdigest(),
        }
    )
    assert resolve_episode_lineage("demo", 3, b'{"a":1}').content_basis_digest != lineage.content_basis_digest
    assert resolve_episode_lineage("demo", 2, b'{"a":2}').content_basis_digest != lineage.content_basis_digest


def test_every_episode_binds_the_host_profile_and_no_master() -> None:
    lineage = resolve_episode_lineage("demo", 1, b"")

    assert lineage.project_name == "demo"
    assert (lineage.creative_profile_id, lineage.creative_profile_version) == ("arcreel.host", "1")
    assert lineage.policy_digest == digest_canonical(
        {"profile_id": "arcreel.host", "profile_version": "1", "rules": []}
    )
    assert lineage.approved_master_id is None
    assert lineage.approved_master_digest is None


def _pack(profile: str) -> str:
    return "sha256:" + hashlib.sha256(profile.encode()).hexdigest()


def _admission(profile: str = "WESTERN_GENERIC", decision: str = "adm-1") -> AdmittedScreenplayRef:
    return AdmittedScreenplayRef(
        screenplay_ref=ArtifactVersionRef(artifact_id="sp-1", version=2, content_hash="hash-sp-1"),
        admission_ref=DecisionRef(decision_id=decision, decision_digest=f"digest-{decision}"),
        profile_ref=AdaptationProfileRef(
            profile_id=AdaptationProfileId(profile), profile_version="7", policy_pack_digest=_pack(profile)
        ),
    )


def test_no_admission_keeps_resolution_v1_bytes() -> None:
    assert resolve_episode_lineage("demo", 2, b"x", admissions=()) == resolve_episode_lineage("demo", 2, b"x")


def test_one_admission_binds_its_profile_and_the_admission_into_the_basis() -> None:
    admission = _admission("CN_SHORT_DRAMA_SHUANGWEN")

    lineage = resolve_episode_lineage("demo", 1, b'{"a":1}', admissions=(admission,))

    assert (lineage.creative_profile_id, lineage.creative_profile_version) == ("CN_SHORT_DRAMA_SHUANGWEN", "7")
    assert lineage.policy_digest == _pack("CN_SHORT_DRAMA_SHUANGWEN")
    assert lineage.content_basis_digest == digest_canonical(
        {
            "basis_kind": "admitted_screenplay_episode_script",
            "episode": 1,
            "script_digest": "sha256:" + hashlib.sha256(b'{"a":1}').hexdigest(),
            "admission_decision_id": "adm-1",
            "admission_decision_digest": "digest-adm-1",
            "screenplay_id": "sp-1",
            "screenplay_version": 2,
            "screenplay_content_hash": "hash-sp-1",
        }
    )
    assert lineage.approved_master_id is None
    assert lineage.approved_master_digest is None
    other = resolve_episode_lineage("demo", 1, b'{"a":1}', admissions=(_admission(decision="adm-2"),))
    assert other.content_basis_digest != lineage.content_basis_digest


def test_an_admitted_project_has_only_episode_one() -> None:
    with pytest.raises(LineageEpisodeOutOfScopeError) as caught:
        resolve_episode_lineage("demo", 2, b"x", admissions=(_admission(),))
    assert caught.value.code == "M8_LINEAGE_EPISODE_OUT_OF_SCOPE"


def test_two_admissions_are_ambiguous_and_never_pick_one() -> None:
    admissions = (_admission("WESTERN_GENERIC", "a"), _admission("CN_SHORT_DRAMA_SHUANGWEN", "b"))

    with pytest.raises(LineageAmbiguousError) as caught:
        resolve_episode_lineage("demo", 1, b"x", admissions=admissions)
    assert caught.value.code == "M8_LINEAGE_AMBIGUOUS"
    with pytest.raises(LineageAmbiguousError):
        project_profile(admissions)


def test_the_project_profile_is_the_host_profile_without_an_admission() -> None:
    assert project_profile(()) == ("arcreel.host", "1", host_policy_digest())
    assert project_profile((_admission(),)) == ("WESTERN_GENERIC", "7", _pack("WESTERN_GENERIC"))
