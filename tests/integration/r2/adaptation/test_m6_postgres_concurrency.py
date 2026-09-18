"""M6 cross-family PostgreSQL concurrency (plan Task 16).

Real-PostgreSQL barrier races the Task 7/12 per-family concurrency suites
(``test_adaptation_concurrency.py``, ``test_screenplay_admission.py``'s own race
test) do not exercise: two *different* profile branches admitting concurrently
never contend (distinct head keys, deterministic per-key lock order), and two
concurrent admissions of the *same* screenplay -- each of which internally locks
its own admission head and then the branch's MAP_APPROVAL head inside one
transaction -- resolve to exactly one winner with no deadlock and no partial
write. Skipped on SQLite: the StaticPool test engine shares one connection and
SQLite has no real row-level locking, so there is nothing to race against.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.adaptation_uow import SqlAlchemyAdaptationUnitOfWork, adaptation_uow_factory
from lib.db.repositories.adaptation import AdaptationRepository
from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.evaluation import ProfileEvaluationService, report_ref_of
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash
from r2.adaptation.profiles import _PACKS_DIR, _compute_policy_pack_digest
from r2.adaptation.shuangwen_profile import ShuangwenSourceScope
from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationBranchV2,
    AdaptationDecisionAction,
    AdaptationMapEntry,
    AdaptationMapV2,
    AdaptationOperation,
    AdaptationPolicy,
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
    FindingDisposition,
    MapApprovalCommand,
    ScreenplayAdmissionCommand,
    ScreenplayArtifactV2,
    ScreenplayScene,
)
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, CreativeApprovalStatus
from tests.integration.r2.adaptation._fakes import FakeAuthority

USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]

_PRINCIPAL = "human:anhtuan"
_DEADLOCK_TIMEOUT_S = 10.0


async def _skip_unless_postgres(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")


_PACK_FILENAMES = {
    AdaptationProfileId.WESTERN_GENERIC: "western_generic_v1.json",
    AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN: "cn_short_drama_shuangwen_v1.json",
}


def _profile_ref(profile_id: AdaptationProfileId) -> AdaptationProfileRef:
    raw = json.loads((_PACKS_DIR / _PACK_FILENAMES[profile_id]).read_bytes())
    return AdaptationProfileRef(
        profile_id=profile_id, profile_version="v1", policy_pack_digest=_compute_policy_pack_digest(raw)
    )


def _branch(*, branch_id: str, profile_ref: AdaptationProfileRef) -> AdaptationBranchV2:
    return AdaptationBranchV2(
        branch_id=branch_id,
        schema_version="r2-adaptation-branch-v2",
        version=1,
        parent_branch_id=None,
        parent_canon_version=ArtifactVersionRef(artifact_id="canon-1", version=1, content_hash="sha256:" + "a1" * 32),
        medium="SHORT_FORM_VIDEO",
        adaptation_policy=AdaptationPolicy.FAITHFUL,
        overlay_version=1,
        profile_ref=profile_ref,
        created_at=datetime.now(UTC),
        created_by=_PRINCIPAL,
    )


def _map(*, adaptation_map_id: str, branch_ref: ArtifactVersionRef) -> AdaptationMapV2:
    entry = AdaptationMapEntry(
        entry_id="entry-1",
        source_refs=["src-1"],
        target_refs=["tgt-1"],
        operation=AdaptationOperation.PRESERVE,
        rationale="keep the scene",
        fidelity_risk="low",
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    draft = AdaptationMapV2(
        adaptation_map_id=adaptation_map_id,
        schema_version="r2-adaptation-map-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        entries=[entry],
        profile_analysis_refs=[],
        content_hash="pending",
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


def _screenplay(
    *, screenplay_id: str, branch_ref: ArtifactVersionRef, map_ref: ArtifactVersionRef, dramatic_text: str
) -> ScreenplayArtifactV2:
    scene = ScreenplayScene(
        scene_id="scene-1",
        purpose="advance the plot",
        duration_target=30.0,
        location_ref=None,
        character_refs=["char-1"],
        source_mapping_refs=["entry-1"],
        dramatic_text=dramatic_text,
    )
    draft = ScreenplayArtifactV2(
        screenplay_id=screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        content_basis=ContentBasis(basis_type=ContentBasisType.ADAPTATION, basis_version="v1", refs=["src-1"]),
        scenes=[scene],
        characters=["char-1"],
        source_mapping_refs=["entry-1"],
        approval_status=CreativeApprovalStatus.DRAFT,
        locked_for_direction=False,
        content_hash="pending",
        adaptation_map_ref=map_ref,
        profile_analysis_refs=[],
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


def _screenplay_ref(screenplay: ScreenplayArtifactV2) -> ArtifactVersionRef:
    return ArtifactVersionRef(
        artifact_id=screenplay.screenplay_id, version=screenplay.version, content_hash=screenplay.content_hash
    )


def _admitted_from(proposal: ScreenplayArtifactV2) -> ScreenplayArtifactV2:
    draft = proposal.model_copy(
        update={
            "version": proposal.version + 1,
            "approval_status": CreativeApprovalStatus.APPROVED,
            "locked_for_direction": True,
            "content_hash": "pending",
        }
    )
    return draft.model_copy(update={"content_hash": compute_adaptation_hash(draft)})


async def _seed_admissible_proposal(
    session_factory: Factory,
    *,
    branch_id: str,
    map_id: str,
    screenplay_id: str,
    profile_ref: AdaptationProfileRef,
    source_scope: ShuangwenSourceScope | None = None,
):
    """Branch -> approved map -> screenplay proposal -> admissible (no unwaived
    blocking finding) evaluation report, entirely on one (non-racing) connection,
    ahead of the barrier-guarded race. ``source_scope`` is required for
    ``CN_SHORT_DRAMA_SHUANGWEN`` (mirrors ``evaluation.evaluate``'s own per-profile
    signature) and always yields exactly one ``NOT_APPLICABLE`` finding for a
    plain, un-tagged screenplay -- admissible, not zero-finding."""
    uow_factory = adaptation_uow_factory(session_factory)
    evidence = AdaptationEvidenceService(uow_factory)
    authority = AdaptationAuthorityService(uow_factory, FakeAuthority())
    evaluation = ProfileEvaluationService(uow_factory)

    branch = await evidence.create_branch(
        _branch(branch_id=branch_id, profile_ref=profile_ref), user_id=USER, project_name=PROJECT
    )
    branch_ref = ArtifactVersionRef(
        artifact_id=branch.branch_id, version=branch.version, content_hash="sha256:" + "b0" * 32
    )
    map_ = await evidence.append_map(
        _map(adaptation_map_id=map_id, branch_ref=branch_ref), user_id=USER, project_name=PROJECT
    )
    map_ref = ArtifactVersionRef(
        artifact_id=map_.adaptation_map_id, version=map_.version, content_hash=map_.content_hash
    )

    map_approve = MapApprovalCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=f"d-map-{map_id}",
        branch_id=branch_id,
        map_ref=map_ref,
        profile_ref=profile_ref,
        relied_report_refs=[],
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.APPROVE,
    )
    map_receipt = await authority.decide_map(map_approve, authenticated_principal=_PRINCIPAL)

    proposal = await evidence.append_screenplay(
        _screenplay(
            screenplay_id=screenplay_id,
            branch_ref=branch_ref,
            map_ref=map_ref,
            dramatic_text="INT. ROOM - DAY\nSomething happens.",
        ),
        user_id=USER,
        project_name=PROJECT,
    )
    report = await evaluation.evaluate(
        artifact_ref=_screenplay_ref(proposal),
        profile_ref=profile_ref,
        user_id=USER,
        project_name=PROJECT,
        source_scope=source_scope,
    )
    assert not any(
        finding.disposition in (FindingDisposition.INTEGRITY_BLOCK, FindingDisposition.PROFILE_BLOCK)
        for finding in report.findings
    )
    return branch, map_receipt, proposal, report


def _admit_command(
    *,
    decision_id: str,
    branch_id: str,
    proposal: ScreenplayArtifactV2,
    profile_ref: AdaptationProfileRef,
    map_approval_ref,
    report_ref,
) -> ScreenplayAdmissionCommand:
    return ScreenplayAdmissionCommand(
        user_id=USER,
        project_name=PROJECT,
        decision_id=decision_id,
        branch_id=branch_id,
        proposal_ref=_screenplay_ref(proposal),
        admitted_screenplay=_admitted_from(proposal),
        profile_ref=profile_ref,
        effective_map_approval_ref=map_approval_ref,
        report_refs=[report_ref],
        waiver_refs=[],
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.ADMIT,
    )


class _BarrierBeforeHeadLockRepository(AdaptationRepository):
    """Barriers only the ``SCREENPLAY_ADMISSION`` ``prepare_or_lock_head`` call --
    each admission command's *own* first lock point -- mirroring
    ``test_screenplay_admission.py``'s own same-shaped race harness. Barriering the
    second, ``MAP_APPROVAL`` lock too would deadlock the harness itself: once real
    Postgres row-level locking serializes the two racers at the first (shared) head,
    the loser never reaches the second barrier point until the winner's transaction
    completes, but the winner cannot complete without a second party at that barrier."""

    def __init__(self, session: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def prepare_or_lock_head(
        self, *, user_id: str, project_name: str, family: AdaptationAuthorityFamily, head_key: str
    ):
        if family == AdaptationAuthorityFamily.SCREENPLAY_ADMISSION:
            await self._barrier.wait()
        return await super().prepare_or_lock_head(
            user_id=user_id, project_name=project_name, family=family, head_key=head_key
        )


class _BarrierBeforeHeadLockUnitOfWork(SqlAlchemyAdaptationUnitOfWork):
    def __init__(self, session_factory: Factory, barrier: asyncio.Barrier) -> None:
        super().__init__(session_factory)
        self._barrier = barrier

    async def __aenter__(self) -> _BarrierBeforeHeadLockUnitOfWork:
        await super().__aenter__()
        self.repository = _BarrierBeforeHeadLockRepository(self.session, self._barrier)
        return self


async def _run_capturing(coro):
    try:
        return await coro
    except Exception as exc:
        return exc


async def test_two_different_profile_branches_admit_concurrently_without_contention(
    concurrent_session_factory: Factory,
) -> None:
    """Different-profile genesis: WESTERN_GENERIC and CN_SHORT_DRAMA_SHUANGWEN branches
    never share a head key, so racing their admissions to the same barrier point must
    let both proceed -- one never blocks on the other's lock."""
    await _skip_unless_postgres(concurrent_session_factory)

    western_profile = _profile_ref(AdaptationProfileId.WESTERN_GENERIC)
    shuangwen_profile = _profile_ref(AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN)
    _, western_map_receipt, western_proposal, western_report = await _seed_admissible_proposal(
        concurrent_session_factory,
        branch_id="branch-race-w",
        map_id="map-race-w",
        screenplay_id="sp-race-w",
        profile_ref=western_profile,
    )
    _, shuangwen_map_receipt, shuangwen_proposal, shuangwen_report = await _seed_admissible_proposal(
        concurrent_session_factory,
        branch_id="branch-race-s",
        map_id="map-race-s",
        screenplay_id="sp-race-s",
        profile_ref=shuangwen_profile,
        source_scope=ShuangwenSourceScope(chapter_start=9, chapter_end=9, source_refs=["src-1"]),
    )

    barrier = asyncio.Barrier(2)

    def uow_factory():
        return _BarrierBeforeHeadLockUnitOfWork(concurrent_session_factory, barrier)

    western_authority = AdaptationAuthorityService(uow_factory, FakeAuthority())
    shuangwen_authority = AdaptationAuthorityService(uow_factory, FakeAuthority())

    async def admit_western():
        command = _admit_command(
            decision_id="d-admit-race-w",
            branch_id="branch-race-w",
            proposal=western_proposal,
            profile_ref=western_profile,
            map_approval_ref=western_map_receipt.decision_ref,
            report_ref=report_ref_of(western_report),
        )
        return await western_authority.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)

    async def admit_shuangwen():
        command = _admit_command(
            decision_id="d-admit-race-s",
            branch_id="branch-race-s",
            proposal=shuangwen_proposal,
            profile_ref=shuangwen_profile,
            map_approval_ref=shuangwen_map_receipt.decision_ref,
            report_ref=report_ref_of(shuangwen_report),
        )
        return await shuangwen_authority.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)

    a, b = await asyncio.wait_for(
        asyncio.gather(_run_capturing(admit_western()), _run_capturing(admit_shuangwen())), timeout=_DEADLOCK_TIMEOUT_S
    )
    outcomes = sorted(type(x).__name__ for x in (a, b))
    assert outcomes == ["AdaptationDecisionReceipt", "AdaptationDecisionReceipt"]


async def test_two_concurrent_admissions_of_the_same_screenplay_yield_one_winner_no_deadlock(
    concurrent_session_factory: Factory,
) -> None:
    """Same-head genesis race at the admission family: two different decision_ids
    racing to admit the SAME proposal -- deterministic per-command lock order (this
    command's own admission head, then the branch's MAP_APPROVAL head) must resolve to
    exactly one winner with no deadlock and no partial write."""
    await _skip_unless_postgres(concurrent_session_factory)

    profile_ref = _profile_ref(AdaptationProfileId.WESTERN_GENERIC)
    _, map_receipt, proposal, report = await _seed_admissible_proposal(
        concurrent_session_factory,
        branch_id="branch-race-same",
        map_id="map-race-same",
        screenplay_id="sp-race-same",
        profile_ref=profile_ref,
    )

    barrier = asyncio.Barrier(2)

    def uow_factory():
        return _BarrierBeforeHeadLockUnitOfWork(concurrent_session_factory, barrier)

    racing = AdaptationAuthorityService(uow_factory, FakeAuthority())

    async def run(decision_id: str):
        command = _admit_command(
            decision_id=decision_id,
            branch_id="branch-race-same",
            proposal=proposal,
            profile_ref=profile_ref,
            map_approval_ref=map_receipt.decision_ref,
            report_ref=report_ref_of(report),
        )
        return await racing.admit_screenplay_for_direction(command, authenticated_principal=_PRINCIPAL)

    a, b = await asyncio.wait_for(
        asyncio.gather(_run_capturing(run("d-admit-race-a")), _run_capturing(run("d-admit-race-b"))),
        timeout=_DEADLOCK_TIMEOUT_S,
    )
    outcomes = sorted(type(x).__name__ for x in (a, b))
    assert outcomes == ["AdaptationDecisionReceipt", "AdaptationStaleHeadError"]

    async with adaptation_uow_factory(concurrent_session_factory)() as uow:
        decisions = await uow.repository.list_decisions_for_locked_head(
            user_id=USER,
            project_name=PROJECT,
            family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
            head_key=proposal.screenplay_id,
        )
        assert len(decisions) == 1
