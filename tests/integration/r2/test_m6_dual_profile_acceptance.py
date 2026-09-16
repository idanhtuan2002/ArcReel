"""M6 acceptance — one shared Canon, two independently reviewable dual-profile
60-120s slices (plan Task 15).

Drives every public M6 service end to end for both ``WESTERN_GENERIC`` and
``CN_SHORT_DRAMA_SHUANGWEN`` from the same pinned ``CanonFixture``: branch, map,
map approval, screenplay proposal, profile evaluation, screenplay admission, TAKE
direction, readiness, local production (multi-candidate for the first shot),
explicit master approval, and final FFmpeg assembly. Asserts the two slices are
fully isolated (branch heads, reports, admissions, candidates, masters) while
sharing the exact same Canon parent identity. Does not assert cultural
representativeness of the Shuangwen content (plan Task 15's own scope note).
"""

from __future__ import annotations

import json
import subprocess

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from r2.adaptation.profiles import _PACKS_DIR, _compute_policy_pack_digest
from r2.contracts.adaptation import AdaptationProfileId, AdaptationProfileRef
from r2.contracts.production import ShotSpecV2
from tests.fixtures.r2.m6_dual_profile_corpus import GoldenBSliceEvidence, build_golden_b_canon, run_profile_slice

USER = "u1"
PROJECT = "project-golden-b"

type Factory = async_sessionmaker[AsyncSession]


def _western_ref() -> AdaptationProfileRef:
    raw = json.loads((_PACKS_DIR / "western_generic_v1.json").read_bytes())
    return AdaptationProfileRef(
        profile_id=AdaptationProfileId.WESTERN_GENERIC,
        profile_version="v1",
        policy_pack_digest=_compute_policy_pack_digest(raw),
    )


def _shuangwen_ref() -> AdaptationProfileRef:
    raw = json.loads((_PACKS_DIR / "cn_short_drama_shuangwen_v1.json").read_bytes())
    return AdaptationProfileRef(
        profile_id=AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN,
        profile_version="v1",
        policy_pack_digest=_compute_policy_pack_digest(raw),
    )


def _assert_real_video(path) -> None:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "video"


def _assert_slice_shape(slice_: GoldenBSliceEvidence, *, canon_ref) -> None:
    assert slice_.parent_canon_ref == canon_ref
    assert 5 <= len(slice_.shots) <= 10
    assert all(isinstance(shot, ShotSpecV2) for shot in slice_.shots)
    assert slice_.multi_candidate_count >= 2
    assert slice_.final.path.is_file()
    assert 60.0 <= slice_.final.duration_seconds <= 120.0
    _assert_real_video(slice_.final.path)


async def test_two_dual_profile_slices_share_one_canon_parent_with_isolated_evidence(
    session_factory: Factory, tmp_path
) -> None:
    canon = build_golden_b_canon()
    uow_factory = adaptation_uow_factory(session_factory)

    western = await run_profile_slice(
        _western_ref(),
        canon=canon,
        uow_factory=uow_factory,
        user_id=USER,
        project_name=PROJECT,
        work_dir=tmp_path / "western",
    )
    shuangwen = await run_profile_slice(
        _shuangwen_ref(),
        canon=canon,
        uow_factory=uow_factory,
        user_id=USER,
        project_name=PROJECT,
        work_dir=tmp_path / "shuangwen",
    )

    _assert_slice_shape(western, canon_ref=canon.canon_ref)
    _assert_slice_shape(shuangwen, canon_ref=canon.canon_ref)

    # exact common parent identity
    assert western.parent_canon_ref == shuangwen.parent_canon_ref == canon.canon_ref

    # independent branch heads
    assert western.branch_id != shuangwen.branch_id

    # independent evidence: map approvals, reports, admissions never collide
    assert western.map_approval_ref != shuangwen.map_approval_ref
    assert western.report_digest != shuangwen.report_digest
    assert western.admission_ref != shuangwen.admission_ref
    assert western.admitted_screenplay_ref != shuangwen.admitted_screenplay_ref

    # independent masters: distinct final assets from distinct host scopes (separate
    # work_dir per slice) -- shot ids may repeat across profiles by design (same
    # scene_id scheme), so isolation is proven by scope, not by shot-id uniqueness.
    assert western.final.sha256 != shuangwen.final.sha256
    assert western.final.path != shuangwen.final.path


async def test_the_canon_fixture_carries_the_required_narrative_elements() -> None:
    canon = build_golden_b_canon()
    content = canon.content

    character_count = sum(1 for e in content.entities_by_id.values() if e.entity_type.value == "CHARACTER")
    location_count = sum(1 for e in content.entities_by_id.values() if e.entity_type.value == "LOCATION")
    assert character_count >= 2
    assert location_count >= 2  # a location change requires at least two locations

    location_facts = [f for f in content.facts_by_id.values() if f.predicate == "location"]
    assert len({str(f.value) for f in location_facts}) >= 2  # the location actually changes

    state_facts = [f for f in content.facts_by_id.values() if f.predicate == "state"]
    assert len({str(f.value) for f in state_facts}) >= 2  # the prop's state actually changes

    # secret/knowledge constraint: one character knows, another does not, same proposition
    states_by_subject = {
        ks.subject_entity_id: ks.epistemic_state.value for ks in content.knowledge_states_by_id.values()
    }
    assert "KNOWN" in states_by_subject.values()
    assert "UNKNOWN" in states_by_subject.values()
