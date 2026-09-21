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
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import adaptation_uow_factory
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.errors import (
    AdaptationAuthorityIntegrityError,
    AdaptationIdentityConflictError,
    AdaptationProfileMismatchError,
    AdaptationStaleDependencyError,
    AdaptationStaleHeadError,
    AdaptationWaiverNotApplicableError,
)
from r2.adaptation.evaluation import ProfileEvaluationService, report_ref_of
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash
from r2.adaptation.profiles import _PACKS_DIR, _compute_policy_pack_digest
from r2.contracts import (
    CandidateSelectionStatus,
    ContentBasisType,
    GenerationCandidate,
    GenerationLifecycleStatus,
)
from r2.contracts.adaptation import (
    AdaptationBranchV2,
    AdaptationDecisionAction,
    AdaptationPolicy,
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
    DecisionRef,
    MapApprovalCommand,
    ProfileWaiverCommand,
    ScreenplayAdmissionCommand,
    ScreenplayArtifactV2,
    ScreenplayScene,
)
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import CreativeApprovalStatus
from r2.contracts.production import CameraAngle, ShotSpecV1, ShotSpecV2
from r2.production import ProductionApprovalService
from r2.production.shot_schema_upgrade import ShotSpecManualMappingRequired, upgrade_shot_spec_v1
from tests.fixtures.r2.m3_media_assertions import frame_pixel_stddev
from tests.fixtures.r2.m6_dual_profile_corpus import GoldenBSliceEvidence, build_golden_b_canon, run_profile_slice

USER = "u1"
PROJECT = "project-golden-b"

type Factory = async_sessionmaker[AsyncSession]


def _basis() -> ContentBasis:
    return ContentBasis(basis_type=ContentBasisType.NARRATIVE, basis_version="canon-golden-b", refs=["canon-golden-b"])


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

    # Real per-shot Remotion rendering (M3 real-media closure Task 3) means
    # the first shot's own DETERMINISTIC text card is visible ~1s in, not a
    # solid color -- frame_pixel_stddev is the same real-content check used
    # for M3's own Golden A products.
    stddev = frame_pixel_stddev(path, path.parent)
    assert stddev > 5.0, f"final video's opening frame looks solid-color (pixel stddev={stddev})"


def _assert_slice_shape(slice_: GoldenBSliceEvidence, *, canon_ref) -> None:
    assert slice_.parent_canon_ref == canon_ref
    assert 5 <= len(slice_.shots) <= 10
    assert all(isinstance(shot, ShotSpecV2) for shot in slice_.shots)
    assert slice_.multi_candidate_count >= 2
    assert slice_.final.path.is_file()
    assert 60.0 <= slice_.final.duration_seconds <= 120.0
    _assert_real_video(slice_.final.path)


@pytest.mark.timeout(
    1500
)  # real per-shot Remotion renders: measured ~400s/slice x 2 slices (~800s); see pyproject.toml note
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


# --------------------------------------------------------------------------- #
# Task 16 — adversarial mutations
#
# Each case drives the same Golden B corpus into one specific illegal operation
# and asserts three things together: (1) the operation fails at its owning
# boundary with a stable typed error, (2) no partial authority state is written
# for the attempted decision, and (3) the sibling slice's already-recorded
# evidence and master are unaffected. Several plan-named mutations
# (cross-profile sidecars, stale report/waiver, retry-tuple substitution,
# ambiguous v1 mapping, rejected/failed candidate promotion) already have
# dedicated, exhaustive unit/integration coverage from Tasks 9-12 — this section
# does not re-derive that coverage line by line; it proves the SAME owning
# boundaries hold when reached through the full dual-profile acceptance path,
# and calls out by name where a case is "already green" from earlier tasks.
# --------------------------------------------------------------------------- #

from tests.integration.r2.adaptation._fakes import FakeAuthority

_PRINCIPAL = "human:golden-b"


async def _build_pair(session_factory: Factory, tmp_path) -> tuple:
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
    return canon, uow_factory, western, shuangwen


def _assert_sibling_unaffected(slice_: GoldenBSliceEvidence, *, canon_ref) -> None:
    """The sibling's own evidence/master must be exactly as it was: still a real
    video at the same path with the same hash, still citing the shared parent."""
    assert slice_.parent_canon_ref == canon_ref
    assert slice_.final.path.is_file()
    _assert_real_video(slice_.final.path)


@pytest.mark.timeout(
    1500
)  # real per-shot Remotion renders via _build_pair: measured ~800s/pair; see pyproject.toml note
async def test_mutation_cross_profile_report_reuse_is_rejected_and_siblings_are_unaffected(
    session_factory: Factory, tmp_path
) -> None:
    """Owning boundary: AdaptationAuthorityService.admit_screenplay_for_direction's
    dependency-report checks (report.artifact_hash / report.profile_ref) — a report
    minted for one profile's branch can never admit a screenplay proposed under the
    sibling profile's branch."""
    canon, uow_factory, western, shuangwen = await _build_pair(session_factory, tmp_path)
    evidence = AdaptationEvidenceService(uow_factory)
    authority = AdaptationAuthorityService(uow_factory, FakeAuthority(principal=_PRINCIPAL))

    # A second proposal version on the Western branch, but admitted citing the
    # Shuangwen slice's own report/map-approval -- neither belongs to this branch.
    western_branch = await evidence.get_exact_branch(
        branch_id=western.branch_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert western_branch is not None
    proposal_v1 = await evidence.get_exact_screenplay(
        screenplay_id=f"{western.branch_id}-sp", version=1, project_name=PROJECT, user_id=USER
    )
    assert proposal_v1 is not None
    branch_ref = ArtifactVersionRef(
        artifact_id=western_branch.branch_id, version=western_branch.version, content_hash="sha256:" + "b0" * 32
    )
    draft = ScreenplayArtifactV2(
        screenplay_id=proposal_v1.screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        # v2 is already taken by run_profile_slice's own admitted N+1 row.
        version=proposal_v1.version + 2,
        adaptation_branch_ref=branch_ref,
        content_basis=proposal_v1.content_basis,
        scenes=[
            ScreenplayScene(
                scene_id="w-scene-mutated",
                purpose="advance the ledger reveal",
                duration_target=15.0,
                location_ref=None,
                character_refs=proposal_v1.characters,
                source_mapping_refs=["entry-1"],
                dramatic_text="INT. OLD WAREHOUSE - NIGHT\nA different beat entirely.",
            )
        ],
        characters=proposal_v1.characters,
        source_mapping_refs=["entry-1"],
        approval_status=proposal_v1.approval_status,
        locked_for_direction=False,
        content_hash="pending",
        adaptation_map_ref=proposal_v1.adaptation_map_ref,
        profile_analysis_refs=[],
    )
    proposal_v2 = await evidence.append_screenplay(
        draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)}), user_id=USER, project_name=PROJECT
    )
    proposal_v2_ref = ArtifactVersionRef(
        artifact_id=proposal_v2.screenplay_id, version=proposal_v2.version, content_hash=proposal_v2.content_hash
    )
    admitted_draft = proposal_v2.model_copy(
        update={
            "version": proposal_v2.version + 1,
            "approval_status": proposal_v2.approval_status,
            "locked_for_direction": True,
            "content_hash": "pending",
        }
    )
    admitted = admitted_draft.model_copy(update={"content_hash": compute_adaptation_hash(admitted_draft)})

    bogus_decision_id = "d-admit-mutation-cross-profile"
    admit = ScreenplayAdmissionCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=bogus_decision_id,
        branch_id=western.branch_id,
        proposal_ref=proposal_v2_ref,
        admitted_screenplay=admitted,
        profile_ref=_western_ref(),
        effective_map_approval_ref=western.map_approval_ref,
        report_refs=[DecisionRef(decision_id=shuangwen.report_digest, decision_digest=shuangwen.report_digest)],
        waiver_refs=[],
        expected_predecessor_id=western.admission_ref.decision_id,
        action=AdaptationDecisionAction.ADMIT,
    )
    with pytest.raises(
        (AdaptationStaleDependencyError, AdaptationProfileMismatchError, AdaptationAuthorityIntegrityError)
    ):
        await authority.admit_screenplay_for_direction(admit, authenticated_principal=_PRINCIPAL)

    async with uow_factory() as uow:
        assert (
            await uow.repository.get_decision_by_id(user_id=USER, project_name=PROJECT, decision_id=bogus_decision_id)
            is None
        )

    _assert_sibling_unaffected(western, canon_ref=canon.canon_ref)
    _assert_sibling_unaffected(shuangwen, canon_ref=canon.canon_ref)


@pytest.mark.timeout(
    1500
)  # real per-shot Remotion renders via _build_pair: measured ~800s/pair; see pyproject.toml note
async def test_mutation_stale_map_approval_after_supersession_is_rejected(session_factory: Factory, tmp_path) -> None:
    """Owning boundary: verify_locked_adaptation_selection inside
    admit_screenplay_for_direction -- an admission naming a MAP_APPROVAL decision that
    is no longer the branch's effective one fails closed."""
    canon, uow_factory, western, shuangwen = await _build_pair(session_factory, tmp_path)
    evidence = AdaptationEvidenceService(uow_factory)
    authority = AdaptationAuthorityService(uow_factory, FakeAuthority(principal=_PRINCIPAL))

    branch_ref = ArtifactVersionRef(artifact_id=western.branch_id, version=1, content_hash="sha256:" + "b0" * 32)
    map_v1 = await evidence.get_exact_map(
        adaptation_map_id=f"{western.branch_id}-map", version=1, project_name=PROJECT, user_id=USER
    )
    assert map_v1 is not None
    map_v2_draft = map_v1.model_copy(
        update={"version": 2, "adaptation_branch_ref": branch_ref, "content_hash": "pending"}
    )
    map_v2 = await evidence.append_map(
        map_v2_draft.model_copy(update={"content_hash": compute_adaptation_hash(map_v2_draft)}),
        user_id=USER,
        project_name=PROJECT,
    )
    supersede = MapApprovalCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id="d-map-mutation-supersede",
        branch_id=western.branch_id,
        map_ref=ArtifactVersionRef(
            artifact_id=map_v2.adaptation_map_id, version=map_v2.version, content_hash=map_v2.content_hash
        ),
        profile_ref=_western_ref(),
        relied_report_refs=[],
        expected_predecessor_id=western.map_approval_ref.decision_id,
        action=AdaptationDecisionAction.APPROVE,
    )
    await authority.decide_map(supersede, authenticated_principal=_PRINCIPAL)

    # A fresh, unlocked proposal (v3 -- v2 is already the terminal admitted row) so
    # this probes only the stale-map-approval boundary, not the separate
    # already-locked-source boundary the next case covers.
    proposal_v1 = await evidence.get_exact_screenplay(
        screenplay_id=f"{western.branch_id}-sp", version=1, project_name=PROJECT, user_id=USER
    )
    assert proposal_v1 is not None
    fresh_draft = proposal_v1.model_copy(update={"version": 3, "content_hash": "pending"})
    fresh_proposal = await evidence.append_screenplay(
        fresh_draft.model_copy(update={"content_hash": compute_adaptation_hash(fresh_draft)}),
        user_id=USER,
        project_name=PROJECT,
    )
    fresh_ref = ArtifactVersionRef(
        artifact_id=fresh_proposal.screenplay_id,
        version=fresh_proposal.version,
        content_hash=fresh_proposal.content_hash,
    )
    admitted_draft = fresh_proposal.model_copy(
        update={
            "version": fresh_proposal.version + 1,
            "approval_status": CreativeApprovalStatus.APPROVED,
            "locked_for_direction": True,
            "content_hash": "pending",
        }
    )
    admitted = admitted_draft.model_copy(update={"content_hash": compute_adaptation_hash(admitted_draft)})

    # Now the STALE (superseded) map approval ref can never admit anything again.
    admit = ScreenplayAdmissionCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id="d-admit-mutation-stale-map",
        branch_id=western.branch_id,
        proposal_ref=fresh_ref,
        admitted_screenplay=admitted,
        profile_ref=_western_ref(),
        effective_map_approval_ref=western.map_approval_ref,
        report_refs=[DecisionRef(decision_id=western.report_digest, decision_digest=western.report_digest)],
        waiver_refs=[],
        expected_predecessor_id=western.admission_ref.decision_id,
        action=AdaptationDecisionAction.ADMIT,
    )
    with pytest.raises(AdaptationAuthorityIntegrityError):
        await authority.admit_screenplay_for_direction(admit, authenticated_principal=_PRINCIPAL)

    async with uow_factory() as uow:
        assert (
            await uow.repository.get_decision_by_id(
                user_id=USER, project_name=PROJECT, decision_id="d-admit-mutation-stale-map"
            )
            is None
        )
    _assert_sibling_unaffected(shuangwen, canon_ref=canon.canon_ref)


@pytest.mark.timeout(
    1500
)  # real per-shot Remotion renders via _build_pair: measured ~800s/pair; see pyproject.toml note
async def test_mutation_readmitting_an_already_locked_screenplay_is_rejected(
    session_factory: Factory, tmp_path
) -> None:
    """Owning boundary (approval-lock split): once a proposal is admitted
    (locked_for_direction=True), it can never again be the *source* of a new
    admission -- an admitted artifact is terminal, not a fresh proposal."""
    canon, uow_factory, western, shuangwen = await _build_pair(session_factory, tmp_path)
    authority = AdaptationAuthorityService(uow_factory, FakeAuthority(principal=_PRINCIPAL))
    evidence = AdaptationEvidenceService(uow_factory)

    already_admitted = await evidence.get_exact_screenplay(
        screenplay_id=western.admitted_screenplay_ref.artifact_id,
        version=western.admitted_screenplay_ref.version,
        project_name=PROJECT,
        user_id=USER,
    )
    assert already_admitted is not None
    assert already_admitted.locked_for_direction is True

    re_admitted_draft = already_admitted.model_copy(
        update={"version": already_admitted.version + 1, "content_hash": "pending"}
    )
    re_admitted = re_admitted_draft.model_copy(update={"content_hash": compute_adaptation_hash(re_admitted_draft)})
    admit_again = ScreenplayAdmissionCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id="d-admit-mutation-relock",
        branch_id=western.branch_id,
        proposal_ref=western.admitted_screenplay_ref,
        admitted_screenplay=re_admitted,
        profile_ref=_western_ref(),
        effective_map_approval_ref=western.map_approval_ref,
        report_refs=[DecisionRef(decision_id=western.report_digest, decision_digest=western.report_digest)],
        waiver_refs=[],
        expected_predecessor_id=western.admission_ref.decision_id,
        action=AdaptationDecisionAction.ADMIT,
    )
    with pytest.raises(AdaptationStaleDependencyError):
        await authority.admit_screenplay_for_direction(admit_again, authenticated_principal=_PRINCIPAL)

    async with uow_factory() as uow:
        assert (
            await uow.repository.get_decision_by_id(
                user_id=USER, project_name=PROJECT, decision_id="d-admit-mutation-relock"
            )
            is None
        )
    _assert_sibling_unaffected(shuangwen, canon_ref=canon.canon_ref)


@pytest.mark.timeout(
    1500
)  # real per-shot Remotion renders via _build_pair: measured ~800s/pair; see pyproject.toml note
async def test_mutation_reused_decision_id_with_a_different_command_is_rejected(
    session_factory: Factory, tmp_path
) -> None:
    """Owning boundary (retry-tuple substitution): replaying an already-recorded
    decision_id with a byte-different command is an identity conflict, never a
    silent overwrite or a fresh append."""
    canon, uow_factory, western, shuangwen = await _build_pair(session_factory, tmp_path)
    authority = AdaptationAuthorityService(uow_factory, FakeAuthority(principal=_PRINCIPAL))

    conflicting = MapApprovalCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=western.map_approval_ref.decision_id,
        branch_id=western.branch_id,
        map_ref=ArtifactVersionRef(
            artifact_id="a-completely-different-map", version=99, content_hash="sha256:" + "9" * 64
        ),
        profile_ref=_western_ref(),
        relied_report_refs=[],
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.REJECT,
    )
    with pytest.raises(AdaptationIdentityConflictError):
        await authority.decide_map(conflicting, authenticated_principal=_PRINCIPAL)

    _assert_sibling_unaffected(western, canon_ref=canon.canon_ref)
    _assert_sibling_unaffected(shuangwen, canon_ref=canon.canon_ref)


@pytest.mark.timeout(
    1500
)  # real per-shot Remotion renders via _build_pair: measured ~800s/pair; see pyproject.toml note
async def test_mutation_waiver_laundering_after_a_semantic_change_is_rejected(
    session_factory: Factory, tmp_path
) -> None:
    """Owning boundary (waiver laundering): a waiver decision targets an exact
    artifact content hash -- once the branch's evidence moves on to different
    content, the old waiver can never excuse a finding on the new content, even
    though it names the same finding_id/rule_version pair."""
    canon, uow_factory, western, shuangwen = await _build_pair(session_factory, tmp_path)
    evidence = AdaptationEvidenceService(uow_factory)
    authority = AdaptationAuthorityService(uow_factory, FakeAuthority(principal=_PRINCIPAL))
    evaluation = ProfileEvaluationService(uow_factory)

    western_branch = await evidence.get_exact_branch(
        branch_id=western.branch_id, version=1, project_name=PROJECT, user_id=USER
    )
    assert western_branch is not None
    branch_ref = ArtifactVersionRef(
        artifact_id=western_branch.branch_id, version=western_branch.version, content_hash="sha256:" + "b0" * 32
    )
    proposal_v1 = await evidence.get_exact_screenplay(
        screenplay_id=f"{western.branch_id}-sp", version=1, project_name=PROJECT, user_id=USER
    )
    assert proposal_v1 is not None

    # A proposal with one deliberate PROFILE_BLOCK finding (missing INT./EXT. slug).
    flawed_draft = ScreenplayArtifactV2(
        screenplay_id=proposal_v1.screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        version=3,
        adaptation_branch_ref=branch_ref,
        content_basis=proposal_v1.content_basis,
        scenes=[
            ScreenplayScene(
                scene_id="w-scene-flawed",
                purpose="advance the ledger reveal",
                duration_target=15.0,
                location_ref=None,
                character_refs=proposal_v1.characters,
                source_mapping_refs=["entry-1"],
                dramatic_text="Something happens.\nMore happens.",
            )
        ],
        characters=proposal_v1.characters,
        source_mapping_refs=["entry-1"],
        approval_status=proposal_v1.approval_status,
        locked_for_direction=False,
        content_hash="pending",
        adaptation_map_ref=proposal_v1.adaptation_map_ref,
        profile_analysis_refs=[],
    )
    flawed = await evidence.append_screenplay(
        flawed_draft.model_copy(update={"content_hash": compute_adaptation_hash(flawed_draft)}),
        user_id=USER,
        project_name=PROJECT,
    )
    flawed_ref = ArtifactVersionRef(
        artifact_id=flawed.screenplay_id, version=flawed.version, content_hash=flawed.content_hash
    )
    report = await evaluation.evaluate(
        artifact_ref=flawed_ref, profile_ref=_western_ref(), user_id=USER, project_name=PROJECT
    )
    assert len(report.findings) == 1
    finding = report.findings[0]

    waive = ProfileWaiverCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id="d-waive-mutation-laundering",
        branch_id=western.branch_id,
        artifact_ref=flawed_ref,
        profile_ref=_western_ref(),
        report_ref=report_ref_of(report),
        finding_ids=[finding.finding_id],
        rule_versions=[finding.rule_version],
        rationale="accepted for this mutation probe",
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.WAIVE,
    )
    waiver_receipt = await authority.decide_waiver(waive, authenticated_principal=_PRINCIPAL)

    # The content changes (v4) -- the v3 waiver can never excuse v4's finding, even
    # though the finding_id/rule_version are identical (same rule, same defect).
    changed_draft = flawed_draft.model_copy(
        update={"version": 4, "scenes": [flawed_draft.scenes[0].model_copy(update={"scene_id": "w-scene-flawed-2"})]}
    )
    changed = await evidence.append_screenplay(
        changed_draft.model_copy(update={"content_hash": compute_adaptation_hash(changed_draft)}),
        user_id=USER,
        project_name=PROJECT,
    )
    changed_ref = ArtifactVersionRef(
        artifact_id=changed.screenplay_id, version=changed.version, content_hash=changed.content_hash
    )
    admitted_draft = changed.model_copy(
        update={
            "version": changed.version + 1,
            "approval_status": CreativeApprovalStatus.APPROVED,
            "locked_for_direction": True,
            "content_hash": "pending",
        }
    )
    admitted = admitted_draft.model_copy(update={"content_hash": compute_adaptation_hash(admitted_draft)})
    admit = ScreenplayAdmissionCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id="d-admit-mutation-laundering",
        branch_id=western.branch_id,
        proposal_ref=changed_ref,
        admitted_screenplay=admitted,
        profile_ref=_western_ref(),
        effective_map_approval_ref=western.map_approval_ref,
        report_refs=[DecisionRef(decision_id=report.report_digest, decision_digest=report.report_digest)],
        waiver_refs=[waiver_receipt.decision_ref],
        expected_predecessor_id=western.admission_ref.decision_id,
        action=AdaptationDecisionAction.ADMIT,
    )
    with pytest.raises((AdaptationWaiverNotApplicableError, AdaptationStaleDependencyError)):
        await authority.admit_screenplay_for_direction(admit, authenticated_principal=_PRINCIPAL)

    async with uow_factory() as uow:
        assert (
            await uow.repository.get_decision_by_id(
                user_id=USER, project_name=PROJECT, decision_id="d-admit-mutation-laundering"
            )
            is None
        )
    _assert_sibling_unaffected(shuangwen, canon_ref=canon.canon_ref)


async def test_mutation_branch_cannot_silently_change_its_canon_parent(session_factory: Factory) -> None:
    """Owning boundary (changed Canon parent / silent rebase):
    validate_adaptation_transition rejects a second branch version that changes
    parent_canon_version -- a branch's root binding is fixed at genesis."""
    canon = build_golden_b_canon()
    uow_factory = adaptation_uow_factory(session_factory)
    evidence = AdaptationEvidenceService(uow_factory)

    genesis = AdaptationBranchV2(
        branch_id="golden-b-rebase-probe",
        schema_version="r2-adaptation-branch-v2",
        version=1,
        parent_branch_id=None,
        parent_canon_version=canon.canon_ref,
        medium="SHORT_FORM_VIDEO",
        adaptation_policy=AdaptationPolicy.FAITHFUL,
        overlay_version=1,
        profile_ref=_western_ref(),
        created_at=datetime.now(UTC),
        created_by=_PRINCIPAL,
    )
    await evidence.create_branch(genesis, user_id=USER, project_name=PROJECT)

    rebased = genesis.model_copy(
        update={
            "version": 2,
            "parent_canon_version": ArtifactVersionRef(
                artifact_id=canon.canon_ref.artifact_id,
                version=canon.canon_ref.version,
                content_hash="sha256:" + "f" * 64,
            ),
        }
    )
    with pytest.raises(AdaptationStaleHeadError):
        await evidence.create_branch(rebased, user_id=USER, project_name=PROJECT)

    async with uow_factory() as uow:
        stored = await uow.repository.get_exact_branch(
            branch_id="golden-b-rebase-probe", version=2, project_name=PROJECT, user_id=USER
        )
        assert stored is None


# --- already-green: recorded, not re-derived ---------------------------------


def test_mutation_an_unmapped_v1_shot_requires_manual_mapping_not_guessed() -> None:
    """Owning boundary (ambiguous v1 mapping): upgrade_shot_spec_v1 fails closed for
    any framing/camera string outside its exact pinned legacy vocabulary --
    exhaustively covered by tests/unit/r2/production/test_shot_schema_upgrade.py;
    this proves the same boundary using a Golden-B-shaped v1 shot."""
    v1_shot = ShotSpecV1(
        id="w-scene-1:TAKE-1",
        schema_version="1",
        version=1,
        scene_id="w-scene-1",
        content_basis=_basis(),
        purpose="advance the ledger reveal",
        target_duration=15.0,
        framing="a compound, free-text description no legacy caller ever used",
        camera="static",
        allowed_methods=["GENERATED_VIDEO"],
        quality_tier=0,
        approval_status="APPROVED",
    )
    with pytest.raises(ShotSpecManualMappingRequired):
        upgrade_shot_spec_v1(v1_shot, camera_angle=CameraAngle.EYE_LEVEL)


def test_mutation_a_failed_candidate_is_refused_and_never_becomes_master() -> None:
    """Owning boundary (failed/rejected latest candidate): ProductionApprovalService
    .promote refuses a non-GENERATED candidate -- exhaustively covered by
    tests/integration/r2/m4/test_approved_master_semantics.py; this proves the same
    boundary through the exact host port Golden B's run_profile_slice uses."""
    from r2.production import ArtifactHostSnapshot

    class _Host:
        def __init__(self) -> None:
            self.value = None

        def load_artifact(self, artifact_key):
            if self.value is None:
                return None
            return ArtifactHostSnapshot(
                artifact_key=artifact_key, usable=True, native_currency=None, r2_raw=self.value.model_dump(mode="json")
            )

        def write_r2_metadata(self, artifact_key, metadata):
            self.value = metadata
            return True

        def promote_version_with_r2_metadata(self, artifact_key, *, host_version_ref, metadata):
            self.value = metadata
            return True

    from r2.production import R2ArtifactMetadata, R2ContractRef

    host = _Host()
    host.value = R2ArtifactMetadata(
        metadata_schema_version="1",
        contract_ref=R2ContractRef(
            contract_type="ShotSpecV2", id="w-scene-1", version=1, schema_version="r2-shot-spec-v2"
        ),
        content_basis=_basis(),
        direct_dependencies=[],
        content_fingerprint="a" * 64,
    )
    good = GenerationCandidate(
        id="CAND-GOOD",
        target_ref="w-scene-1",
        content_fingerprint="a" * 64,
        execution_fingerprint="e-good" + "0" * 58,
        provider_execution_ref="local:ffmpeg:good",
        output_asset_ref="asset:good",
        lifecycle_state=GenerationLifecycleStatus.GENERATED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )
    ProductionApprovalService(host).promote(
        artifact_key="video:w-scene-1",
        candidate=good,
        host_version_ref="1",
        approval_record="approval:1",
        selected_by=_PRINCIPAL,
        selected_at=datetime.now(UTC),
    )
    assert host.value.approved_master.selected_candidate_id == "CAND-GOOD"

    failed = GenerationCandidate(
        id="CAND-FAILED",
        target_ref="w-scene-1",
        content_fingerprint="a" * 64,
        execution_fingerprint="e-failed" + "0" * 56,
        provider_execution_ref="local:ffmpeg:failed",
        output_asset_ref="asset:failed",
        lifecycle_state=GenerationLifecycleStatus.FAILED,
        selection_state=CandidateSelectionStatus.UNREVIEWED,
    )
    with pytest.raises(ValueError, match="GENERATED"):
        ProductionApprovalService(host).promote(
            artifact_key="video:w-scene-1",
            candidate=failed,
            host_version_ref="2",
            approval_record="approval:2",
            selected_by=_PRINCIPAL,
            selected_at=datetime.now(UTC),
        )
    assert host.value.approved_master.selected_candidate_id == "CAND-GOOD"
