from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.adaptation.schema_upgrade import validate_adaptation_transition
from r2.contracts.adaptation import (
    AdaptationBranchV2,
    AdaptationPolicy,
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
CANON_REF = ArtifactVersionRef(artifact_id="canon-1", version=1, content_hash="sha256:" + "a" * 64)
WESTERN_PROFILE_REF = AdaptationProfileRef(
    profile_id=AdaptationProfileId.WESTERN_GENERIC, profile_version="1", policy_pack_digest="sha256:" + "b" * 64
)
SHUANGWEN_PROFILE_REF = AdaptationProfileRef(
    profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
    profile_version="1",
    policy_pack_digest="sha256:" + "c" * 64,
)


def _branch(**overrides: object) -> AdaptationBranchV2:
    defaults: dict[str, object] = {
        "branch_id": "branch-1",
        "schema_version": "r2-adaptation-branch-v2",
        "version": 1,
        "parent_branch_id": None,
        "parent_canon_version": CANON_REF,
        "medium": "short-drama",
        "adaptation_policy": AdaptationPolicy.FAITHFUL,
        "overlay_version": 1,
        "profile_ref": WESTERN_PROFILE_REF,
        "created_at": NOW,
        "created_by": "showrunner-1",
    }
    defaults.update(overrides)
    return AdaptationBranchV2(**defaults)


# --- legal genesis -----------------------------------------------------------------------


def test_genesis_at_version_one_is_legal() -> None:
    assert validate_adaptation_transition(None, _branch(version=1)) is None


def test_genesis_above_version_one_is_illegal() -> None:
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(None, _branch(version=2))


# --- legal sequential transition ----------------------------------------------------------


def test_version_advancing_by_exactly_one_is_legal() -> None:
    previous = _branch(version=1)
    assert validate_adaptation_transition(previous, _branch(version=2)) is None


def test_version_advancing_by_more_than_one_is_illegal() -> None:
    previous = _branch(version=1)
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(previous, _branch(version=3))


def test_repeating_the_same_version_is_illegal() -> None:
    previous = _branch(version=1)
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(previous, _branch(version=1))


# --- no v2-to-v1 (or any) downgrade --------------------------------------------------------


def test_a_lower_version_after_a_higher_one_is_a_downgrade_and_illegal() -> None:
    previous = _branch(version=5)
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(previous, _branch(version=4))


# --- no same-ID genesis tuple substitution -------------------------------------------------


def test_a_second_differing_genesis_under_the_same_branch_id_is_rejected() -> None:
    # A real genesis for branch-1 already exists (version 1); a second "genesis" attempt
    # with a different tuple under the same branch_id is just a non-sequential version 1
    # resubmission, which the version-advance rule already rejects.
    previous = _branch(version=1, medium="feature-film")
    differing_genesis = _branch(version=1, medium="short-drama")
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(previous, differing_genesis)


# --- profile change requires a new branch --------------------------------------------------


def test_changing_profile_mid_lineage_is_illegal() -> None:
    previous = _branch(version=1, profile_ref=WESTERN_PROFILE_REF)
    with pytest.raises(ValueError, match="ADAPTATION_PROFILE_MISMATCH"):
        validate_adaptation_transition(previous, _branch(version=2, profile_ref=SHUANGWEN_PROFILE_REF))


def test_a_new_branch_id_may_freely_choose_its_own_profile() -> None:
    # Not a "transition" of branch-1 at all — a different branch_id is always genesis.
    result = validate_adaptation_transition(
        None, _branch(branch_id="branch-2", version=1, profile_ref=SHUANGWEN_PROFILE_REF)
    )
    assert result is None


# --- root binding is fixed at genesis --------------------------------------------------------


def test_changing_parent_branch_id_mid_lineage_is_illegal() -> None:
    previous = _branch(version=1, parent_branch_id=None)
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(previous, _branch(version=2, parent_branch_id="some-other-branch"))


def test_changing_parent_canon_version_mid_lineage_is_illegal() -> None:
    previous = _branch(version=1)
    other_canon_ref = ArtifactVersionRef(artifact_id="canon-2", version=1, content_hash="sha256:" + "d" * 64)
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(previous, _branch(version=2, parent_canon_version=other_canon_ref))


def test_mismatched_branch_id_is_rejected_outright() -> None:
    previous = _branch(branch_id="branch-1", version=1)
    with pytest.raises(ValueError, match="ADAPTATION_STALE_HEAD"):
        validate_adaptation_transition(previous, _branch(branch_id="branch-2", version=2))
