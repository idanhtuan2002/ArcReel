"""Binding proof against the real R2 owners: contexts compiled before approval equal those after commit.

The genesis, plan and scene acceptances are recorded through the existing services; the authority port here
is the M5C test double, because this file proves the mapping and the context equality, not the grant.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import canon_authority_uow_factory
from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from r2.contracts import CanonCommitApproval, CreateCanonBranch, NarrativePlanApproval
from r2.contracts.narrative import CanonBranchType
from r2.narrative.canon_transaction import CanonTransactionService
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.evidence import NarrativeLifecycleEvidenceService
from r2.narrative_plan.service import NarrativePlanService
from server.story_authoring.narrative import (
    ProvisionalAcceptance,
    SceneBases,
    StoryBibleInput,
    StoryEntityInput,
    StoryIdentity,
    StoryOutlineInput,
    acceptance_command,
    binding,
    build_candidate,
    build_genesis_delta,
    build_plan_proposal,
    build_revision,
    committed_readers,
    compile_scene_context,
    genesis_canon_version_id,
    provisional_canon_view,
    provisional_plan,
    revision_decision_id,
    scene_contract,
    scene_refs,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER, FakeShowrunnerAuthorityPort

type Factory = async_sessionmaker[AsyncSession]

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
IDENTITY = StoryIdentity(user_id="default", project_name="story-test", run_id="run1")

BIBLE = StoryBibleInput(
    title="Căn nhà cũ",
    premise="Minh về làng bán nhà của cha.",
    characters=(
        StoryEntityInput(key="minh", name="Minh", description="Con trai cả, 32 tuổi, làm ở thành phố."),
        StoryEntityInput(key="lan", name="Lan", description="Em gái Minh, ở lại làng chăm mẹ."),
    ),
    locations=(StoryEntityInput(key="nha-cu", name="Căn nhà cũ", description="Nhà ba gian của cha."),),
    style_rules=("Ngôi thứ ba, giọng trầm.", "Không dùng từ Hán Việt khó."),
)

OUTLINE = StoryOutlineInput.model_validate(
    {
        "story_frame": "Ba chương: trở về, cuốn sổ, ra đi.",
        "chapters": [
            {
                "intent": "Minh trở về",
                "scenes": [
                    {
                        "purpose": "Minh mở cửa nhà cũ",
                        "pov": "minh",
                        "location": "nha-cu",
                        "participants": ["lan"],
                        "beats": ["mở cửa", "gặp Lan"],
                    },
                    {
                        "purpose": "Bữa cơm đầu tiên",
                        "pov": "lan",
                        "location": "nha-cu",
                        "participants": ["minh"],
                        "beats": ["im lặng"],
                    },
                ],
            },
            {
                "intent": "Cuốn sổ của cha",
                "scenes": [
                    {
                        "purpose": "Minh tìm thấy cuốn sổ",
                        "pov": "minh",
                        "location": "nha-cu",
                        "participants": [],
                        "beats": ["ngăn tủ"],
                    },
                ],
            },
        ],
    }
)

PROSE = (
    "Minh đẩy cánh cửa gỗ đã mục. Lan đứng sau lưng anh, không nói gì.",
    "Bữa cơm chỉ có tiếng đũa chạm bát. Lan gắp cho anh miếng cá kho.",
    "Trong ngăn tủ, dưới mấy tờ hóa đơn cũ, Minh thấy cuốn sổ bìa xanh của cha.",
)


def _services(factory: Factory):
    lifecycle = narrative_lifecycle_uow_factory(factory)
    authority = FakeShowrunnerAuthorityPort()
    return (
        NarrativeLifecycleEvidenceService(lifecycle),
        NarrativeAcceptanceService(lifecycle, authority),
    )


async def test_contexts_compiled_before_approval_equal_those_after_commit(concurrent_session_factory: Factory):
    factory = concurrent_session_factory
    delta = build_genesis_delta(IDENTITY, BIBLE, created_by="run1", created_at=NOW)
    canon_version = genesis_canon_version_id(delta)
    proposal = build_plan_proposal(IDENTITY, OUTLINE, canon_version_id=canon_version, created_by="run1", created_at=NOW)
    plan = provisional_plan(proposal, approval_ref="appr-plan", committed_by=SHOWRUNNER, committed_at=NOW)
    canon_view = provisional_canon_view(delta)
    scenes = scene_refs(OUTLINE)

    # Before approval: compile each scene against the provisional state, accepting earlier scenes in memory.
    from server.story_authoring.narrative import provisional_readers

    acceptances: list[ProvisionalAcceptance] = []
    provisional = []
    for scene, prose in zip(scenes, PROSE, strict=True):
        readers = provisional_readers(IDENTITY, BIBLE, canon_view=canon_view, plan=plan, acceptances=acceptances)
        contract = scene_contract(proposal, scene)
        pack = await compile_scene_context(
            readers,
            IDENTITY,
            scene,
            contract=contract,
            canon_version_id=canon_version,
            plan_version=1,
            recent_decision_ids=[a.decision_id for a in acceptances],
        )
        bases = SceneBases(canon_version, 1, contract.version, pack.context_pack_id)
        candidate = build_candidate(
            IDENTITY, scene, bases, prose, model="ornith-32k:9b", writer_version="w1", created_by="run1", created_at=NOW
        )
        revision = build_revision(candidate, created_by="run1", created_at=NOW)
        acceptances.append(
            ProvisionalAcceptance(revision=revision, decision_id=revision_decision_id(IDENTITY, scene, revision))
        )
        provisional.append((pack, candidate, revision))

    # The approval: genesis, plan, then each scene's evidence and acceptance, through the real owners.
    canon = CanonTransactionService(canon_authority_uow_factory(factory), version_id_factory=lambda: canon_version)
    await canon.create_branch(
        CreateCanonBranch(
            branch_id=IDENTITY.canon_branch_id,
            user_id=IDENTITY.user_id,
            project_name=IDENTITY.project_name,
            branch_type=CanonBranchType.MAIN,
            created_at=NOW,
            created_by=SHOWRUNNER,
        )
    )
    committed = await canon.commit(
        delta=delta,
        approval=CanonCommitApproval(
            approval_ref="appr-canon",
            canon_delta_id=delta.canon_delta_id,
            payload_hash=delta.payload_hash,
            payload_hash_algorithm="sha256",
            payload_hash_version="r2-canon-delta-v1",
            content_schema_version=delta.content_schema_version,
            project_name=IDENTITY.project_name,
            user_id=IDENTITY.user_id,
            approved_by=SHOWRUNNER,
            approved_at=NOW,
            status="APPROVED",
        ),
        project_name=IDENTITY.project_name,
        user_id=IDENTITY.user_id,
        now=NOW,
    )
    assert committed.version.canon_version_id == canon_version

    readers = committed_readers(IDENTITY, BIBLE, session_factory=factory)
    plan_service = NarrativePlanService(narrative_plan_uow_factory(factory), readers.compiler._canon_reader)
    await plan_service.commit_revision(
        proposal=proposal,
        approval=NarrativePlanApproval(
            approval_ref="appr-plan",
            plan_revision_id=proposal.plan_revision_id,
            plan_id=proposal.plan_id,
            expected_version=None,
            content_hash=proposal.content_hash,
            project_name=IDENTITY.project_name,
            user_id=IDENTITY.user_id,
            approved_by=SHOWRUNNER,
            approved_at=NOW,
        ),
        project_name=IDENTITY.project_name,
        user_id=IDENTITY.user_id,
        now=NOW,
    )

    evidence, acceptance = _services(factory)
    decided: list[str] = []
    for scene, (pack, candidate, revision) in zip(scenes, provisional, strict=True):
        real = await compile_scene_context(
            readers,
            IDENTITY,
            scene,
            contract=scene_contract(proposal, scene),
            canon_version_id=canon_version,
            plan_version=1,
            recent_decision_ids=decided,
        )
        assert binding(real) == binding(pack), scene.node_id
        assert sorted(segment.content for segment in real.recent_accepted_context) == sorted(
            earlier.normalized_content for _, _, earlier in provisional[: scene.global_index]
        )
        await evidence.record_draft_candidate(candidate)
        await evidence.record_revision(revision)
        decision_id = revision_decision_id(IDENTITY, scene, revision)
        receipt = await acceptance.decide_revision(
            acceptance_command(revision, decision_id=decision_id, actor_id=SHOWRUNNER),
            authenticated_principal=SHOWRUNNER,
        )
        assert receipt.effective_decision_id == decision_id
        decided.append(decision_id)
