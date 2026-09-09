"""Genesis, append, exact retry, stale head, approval, and Canon-basis behaviour."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from r2.contracts import (
    CanonBasis,
    CanonContent,
    NarrativePlanApproval,
    NarrativePlanContent,
    NarrativePlanContentV2,
    NarrativePlanRevisionProposal,
    SceneContractV2,
    SceneTemporalWindow,
    SceneThreadConstraint,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.errors import NarrativePlanSchemaVersionError
from r2.narrative.hashing import compute_canon_content_hash
from r2.narrative_plan.errors import (
    NarrativePlanApprovalError,
    NarrativePlanNotFoundError,
    NarrativePlanValidationError,
    NarrativePlanVersionConflict,
)
from r2.narrative_plan.hashing import (
    compute_plan_content_hash,
    compute_plan_content_hash_v2,
    compute_scene_semantic_hash_v2,
)
from r2.narrative_plan.service import NarrativePlanService

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)
USER = "u1"
OTHER_USER = "conformance"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


class FakeCanonReader:
    def __init__(self, views: dict[str, ResolvedCanonView]) -> None:
        self._views = views
        self.requested: list[str] = []

    async def get_exact(
        self, *, branch_id: str, canon_version_id: str, project_name: str, user_id: str
    ) -> ResolvedCanonView | None:
        _ = (branch_id, project_name, user_id)
        self.requested.append(canon_version_id)
        return self._views.get(canon_version_id)


def _canon_view(version_id: str = "canon-v1") -> ResolvedCanonView:
    content = CanonContent(entities_by_id={}, facts_by_id={}, events_by_id={})
    return ResolvedCanonView(
        canon_version_id=version_id,
        branch_id="main",
        content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


def _content(
    *, canon_version_id: str = "canon-v1", frame: str = "frame", parent_version: int | None = None
) -> NarrativePlanContent:
    return NarrativePlanContent(
        parent_version=parent_version,
        canon_basis=CanonBasis(branch_id="main", canon_version_id=canon_version_id),
        story_frame=frame,
    )


def _proposal(
    *, plan_id: str = "plan-1", expected_version: int | None = None, revision: str = "rev-1", frame: str = "frame"
) -> NarrativePlanRevisionProposal:
    content = _content(frame=frame, parent_version=expected_version)
    return NarrativePlanRevisionProposal(
        plan_revision_id=revision,
        plan_id=plan_id,
        expected_version=expected_version,
        proposed_content=content,
        content_hash=compute_plan_content_hash(content),
        created_at=NOW,
        created_by="lead",
    )


def _approval(
    proposal: NarrativePlanRevisionProposal, *, approval_ref: str = "ap-1", user_id: str = USER
) -> NarrativePlanApproval:
    return NarrativePlanApproval(
        approval_ref=approval_ref,
        plan_revision_id=proposal.plan_revision_id,
        plan_id=proposal.plan_id,
        expected_version=proposal.expected_version,
        content_hash=proposal.content_hash,
        project_name=PROJECT,
        user_id=user_id,
        approved_by="approver",
        approved_at=NOW,
    )


def _service(factory: Factory, reader: FakeCanonReader | None = None) -> tuple[NarrativePlanService, FakeCanonReader]:
    reader = reader or FakeCanonReader({"canon-v1": _canon_view()})
    return NarrativePlanService(narrative_plan_uow_factory(factory), reader), reader


async def test_genesis_then_append_through_the_only_write_path(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    genesis = _proposal(expected_version=None, revision="rev-1")
    result = await service.commit_revision(
        proposal=genesis, approval=_approval(genesis, approval_ref="ap-1"), project_name=PROJECT, user_id=USER, now=NOW
    )
    assert result.plan.version == 1

    append = _proposal(expected_version=1, revision="rev-2", frame="frame-2")
    appended = await service.commit_revision(
        proposal=append, approval=_approval(append, approval_ref="ap-2"), project_name=PROJECT, user_id=USER, now=NOW
    )
    assert appended.plan.version == 2
    assert (
        await service.get_version(plan_id="plan-1", version=2, project_name=PROJECT, user_id=USER)
    ).content.story_frame == "frame-2"


async def test_exact_retry_returns_the_original_and_writes_nothing(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    genesis = _proposal(revision="rev-1")
    first = await service.commit_revision(
        proposal=genesis, approval=_approval(genesis), project_name=PROJECT, user_id=USER, now=NOW
    )
    retry = await service.commit_revision(
        proposal=genesis,
        approval=_approval(genesis),
        project_name=PROJECT,
        user_id=USER,
        now=datetime(2027, 1, 1, tzinfo=UTC),
    )
    assert retry.plan.version == first.plan.version
    assert retry.plan.committed_at == first.plan.committed_at


async def test_genesis_for_an_existing_plan_is_a_version_conflict(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    genesis = _proposal(revision="rev-1")
    await service.commit_revision(
        proposal=genesis, approval=_approval(genesis), project_name=PROJECT, user_id=USER, now=NOW
    )
    second_genesis = _proposal(revision="rev-2", frame="other")
    with pytest.raises(NarrativePlanVersionConflict):
        await service.commit_revision(
            proposal=second_genesis,
            approval=_approval(second_genesis, approval_ref="ap-2"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )


async def test_append_for_a_missing_plan_is_not_found(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    append = _proposal(expected_version=1, revision="rev-1")
    with pytest.raises(NarrativePlanNotFoundError):
        await service.commit_revision(
            proposal=append, approval=_approval(append), project_name=PROJECT, user_id=USER, now=NOW
        )


async def test_stale_expected_head_is_rejected_with_zero_writes(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    genesis = _proposal(revision="rev-1")
    await service.commit_revision(
        proposal=genesis, approval=_approval(genesis), project_name=PROJECT, user_id=USER, now=NOW
    )
    stale = _proposal(expected_version=5, revision="rev-2")
    with pytest.raises(NarrativePlanVersionConflict):
        await service.commit_revision(
            proposal=stale, approval=_approval(stale, approval_ref="ap-2"), project_name=PROJECT, user_id=USER, now=NOW
        )
    assert (await service.get_version(plan_id="plan-1", version=1, project_name=PROJECT, user_id=USER)).version == 1


async def test_approval_receipt_must_match_the_proposal_and_scope(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    genesis = _proposal(revision="rev-1")
    wrong_scope = _approval(genesis, user_id=OTHER_USER)
    with pytest.raises(NarrativePlanApprovalError):
        await service.commit_revision(
            proposal=genesis, approval=wrong_scope, project_name=PROJECT, user_id=USER, now=NOW
        )


async def test_reusing_an_approval_ref_for_another_revision_is_rejected(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    genesis = _proposal(revision="rev-1")
    await service.commit_revision(
        proposal=genesis,
        approval=_approval(genesis, approval_ref="ap-shared"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    append = _proposal(expected_version=1, revision="rev-2", frame="frame-2")
    with pytest.raises(NarrativePlanApprovalError):
        await service.commit_revision(
            proposal=append,
            approval=_approval(append, approval_ref="ap-shared"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )


async def test_commit_validates_only_the_exact_canon_basis(session_factory: Factory) -> None:
    reader = FakeCanonReader({"canon-v1": _canon_view()})  # canon-missing absent
    service, _ = _service(session_factory, reader)
    genesis = _proposal(revision="rev-1", frame="frame")
    genesis = genesis.model_copy(
        update={
            "proposed_content": _content(canon_version_id="canon-missing"),
        }
    )
    genesis = genesis.model_copy(update={"content_hash": compute_plan_content_hash(genesis.proposed_content)})
    with pytest.raises(NarrativePlanValidationError):
        await service.commit_revision(
            proposal=genesis, approval=_approval(genesis), project_name=PROJECT, user_id=USER, now=NOW
        )
    assert reader.requested == ["canon-missing"]


# --- v2 NarrativePlan commit path (Task 5 service wiring) -----------------------

_WIN = SceneTemporalWindow(
    effective_from=datetime(2026, 3, 1, 10, tzinfo=UTC), effective_until=datetime(2026, 3, 1, 12, tzinfo=UTC)
)


def _thread(
    constraint_id: str, thread_ref: str, state: str = "OPEN", payoff: str | None = None
) -> SceneThreadConstraint:
    return SceneThreadConstraint(
        constraint_id=constraint_id, thread_ref=thread_ref, required_state=state, payoff_ref=payoff
    )


def _v2_scene(scene_id: str, sequence_index: int, **overrides: object) -> SceneContractV2:
    draft = SceneContractV2(
        scene_contract_id=scene_id,
        version=1,
        semantic_hash="sh:placeholder",
        semantic_hash_version="r2-scene-contract-content-v2",
        sequence_index=sequence_index,
        purpose="p",
        pov=None,
        location_ref=None,
        temporal_window=_WIN,
        **overrides,
    )
    return draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash_v2(draft)})


def _content_v2(*, scenes: list[SceneContractV2], parent_version: int | None = None) -> NarrativePlanContentV2:
    return NarrativePlanContentV2(
        parent_version=parent_version,
        canon_basis=CanonBasis(branch_id="main", canon_version_id="canon-v1"),
        story_frame="frame",
        scene_contracts=scenes,
    )


def _proposal_v2(
    content: NarrativePlanContentV2, *, expected_version: int | None = None, revision: str = "rev-1"
) -> NarrativePlanRevisionProposal:
    return NarrativePlanRevisionProposal(
        plan_revision_id=revision,
        plan_id="plan-1",
        expected_version=expected_version,
        proposed_content=content,
        content_hash=compute_plan_content_hash_v2(content),
        created_at=NOW,
        created_by="lead",
    )


async def test_v2_plan_commits_and_runs_the_thread_lifecycle_pass(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    content = _content_v2(
        scenes=[
            _v2_scene("sc-open", 0, active_threads=["t1"], exit_state_targets=[_thread("e0", "t1")]),
            _v2_scene(
                "sc-resolve",
                1,
                active_threads=["t1"],
                promise_payoff_refs=["p1"],
                exit_state_targets=[_thread("r1", "t1", "RESOLVED", "p1")],
            ),
        ]
    )
    proposal = _proposal_v2(content)
    result = await service.commit_revision(
        proposal=proposal, approval=_approval(proposal), project_name=PROJECT, user_id=USER, now=NOW
    )
    assert result.plan.version == 1
    assert result.plan.content_hash_version == "r2-narrative-plan-content-v2"
    stored = await service.get_version(plan_id="plan-1", version=1, project_name=PROJECT, user_id=USER)
    assert stored.content.schema_version == "r2-narrative-plan-v2"


async def test_v2_plan_with_a_broken_thread_lineage_is_rejected_with_zero_writes(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    content = _content_v2(
        scenes=[
            _v2_scene(
                "sc-bad",
                0,
                promise_payoff_refs=["p1"],
                exit_state_targets=[_thread("r", "ghost", "RESOLVED", "p1")],
            )
        ]
    )
    proposal = _proposal_v2(content)
    with pytest.raises(NarrativePlanValidationError) as exc:
        await service.commit_revision(
            proposal=proposal, approval=_approval(proposal), project_name=PROJECT, user_id=USER, now=NOW
        )
    assert "SCENE_THREAD_LIFECYCLE_RESOLUTION_WITHOUT_THREAD" in str(exc.value)
    with pytest.raises(NarrativePlanNotFoundError):
        await service.get_version(plan_id="plan-1", version=1, project_name=PROJECT, user_id=USER)


async def test_a_v2_plan_lineage_cannot_downgrade_to_v1(session_factory: Factory) -> None:
    service, _ = _service(session_factory)
    v2_genesis = _proposal_v2(_content_v2(scenes=[_v2_scene("sc-1", 0, omniscient_authoring_allowed_by_scene=True)]))
    await service.commit_revision(
        proposal=v2_genesis, approval=_approval(v2_genesis), project_name=PROJECT, user_id=USER, now=NOW
    )
    v1_append = _proposal(expected_version=1, revision="rev-2", frame="frame-2")
    with pytest.raises(NarrativePlanSchemaVersionError):
        await service.commit_revision(
            proposal=v1_append,
            approval=_approval(v1_append, approval_ref="ap-2"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )
