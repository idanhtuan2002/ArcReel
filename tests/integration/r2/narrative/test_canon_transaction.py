"""Approval, idempotency, base conflict, and atomic commit for CanonTransactionService."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from lib.db.canon_uow import canon_authority_uow_factory
from r2.contracts import CanonBranchType, Entity, EntityType
from r2.narrative.canon_transaction import CanonCommitStage, CanonTransactionService
from r2.narrative.errors import (
    CanonApprovalError,
    CanonBaseVersionConflict,
    CanonIdentityConflictError,
    CanonNotFoundError,
    CanonValidationError,
)
from r2.narrative.hashing import verify_canon_delta_hash
from tests.integration.r2.narrative._canon_authority import (
    NOW,
    PROJECT,
    USER,
    Factory,
    authority_counts,
    branch_head,
    main_branch_command,
    make_add_then_retire_fact_delta,
    make_approval,
    make_entity_delta,
    make_event_delta,
    make_update_noop_delta,
    narrative_branch_command,
)

LATER = datetime(2026, 9, 8, 12, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 6, 1, tzinfo=UTC)


def service(
    factory: Factory,
    *,
    version_id_factory: Callable[[], str] | None = None,
) -> CanonTransactionService:
    if version_id_factory is None:
        return CanonTransactionService(canon_authority_uow_factory(factory))
    return CanonTransactionService(canon_authority_uow_factory(factory), version_id_factory=version_id_factory)


def counting_version_ids() -> tuple[Callable[[], str], list[str]]:
    issued: list[str] = []

    def _next() -> str:
        issued.append(f"version-{len(issued) + 1}")
        return issued[-1]

    return _next, issued


async def commit_genesis(svc: CanonTransactionService, *, now: datetime = NOW):
    delta = make_entity_delta("delta-1", "main", None, "hero")
    return await svc.commit(
        delta=delta,
        approval=make_approval(delta, approval_ref="approval-1"),
        project_name=PROJECT,
        user_id=USER,
        now=now,
    )


async def test_approved_main_genesis_advances_head_atomically(session_factory: Factory) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1"]).__next__)
    await svc.create_branch(main_branch_command())
    result = await commit_genesis(svc)
    assert result.version.canon_version_id == "version-1"
    assert result.version.parent_version_id is None
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}
    assert await branch_head(session_factory, "main") == "version-1"


async def test_exact_retry_precedes_base_conflict(session_factory: Factory) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1"]).__next__)
    await svc.create_branch(main_branch_command())
    first = await commit_genesis(svc)
    retried = await commit_genesis(svc, now=LATER)
    assert retried == first
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}


async def test_exact_retry_after_head_advance_does_not_call_the_version_factory(
    session_factory: Factory,
) -> None:
    next_id, issued = counting_version_ids()
    svc = service(session_factory, version_id_factory=next_id)
    await svc.create_branch(main_branch_command())
    first = await commit_genesis(svc)
    second_delta = make_entity_delta("delta-2", "main", "version-1", "villain")
    await svc.commit(
        delta=second_delta,
        approval=make_approval(second_delta, approval_ref="approval-2"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    issued_before_retry = list(issued)
    retried = await commit_genesis(svc, now=LATER)
    assert retried == first
    assert issued == issued_before_retry


async def test_changing_approved_by_under_the_same_approval_ref_is_a_conflict(
    session_factory: Factory,
) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1"]).__next__)
    await svc.create_branch(main_branch_command())
    delta = make_entity_delta("delta-1", "main", None, "hero")
    await svc.commit(
        delta=delta,
        approval=make_approval(delta, approval_ref="approval-1"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    tampered = make_approval(delta, approval_ref="approval-1", approved_by="someone-else")
    with pytest.raises(CanonIdentityConflictError):
        await svc.commit(delta=delta, approval=tampered, project_name=PROJECT, user_id=USER, now=NOW)


async def test_wrong_approval_payload_hash_writes_nothing(session_factory: Factory) -> None:
    svc = service(session_factory)
    await svc.create_branch(main_branch_command())
    delta = make_entity_delta("delta-1", "main", None, "hero")
    bad = make_approval(delta, approval_ref="approval-1").model_copy(update={"payload_hash": "0" * 64})
    with pytest.raises(CanonApprovalError):
        await svc.commit(delta=delta, approval=bad, project_name=PROJECT, user_id=USER, now=NOW)
    assert await authority_counts(session_factory) == {"deltas": 0, "versions": 0, "projections": 0}


async def test_mismatched_request_scope_writes_nothing(session_factory: Factory) -> None:
    svc = service(session_factory)
    await svc.create_branch(main_branch_command())
    delta = make_entity_delta("delta-1", "main", None, "hero")
    with pytest.raises(CanonApprovalError):
        await svc.commit(
            delta=delta,
            approval=make_approval(delta, approval_ref="approval-1"),
            project_name="other-project",
            user_id=USER,
            now=NOW,
        )
    assert await authority_counts(session_factory) == {"deltas": 0, "versions": 0, "projections": 0}


async def test_stale_base_is_rejected_and_leaves_prior_authority_intact(session_factory: Factory) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1"]).__next__)
    await svc.create_branch(main_branch_command())
    await commit_genesis(svc)
    stale = make_entity_delta("delta-2", "main", None, "villain")
    with pytest.raises(CanonBaseVersionConflict):
        await svc.commit(
            delta=stale,
            approval=make_approval(stale, approval_ref="approval-2"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}


async def test_semantic_no_op_is_rejected(session_factory: Factory) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1"]).__next__)
    await svc.create_branch(main_branch_command())
    await commit_genesis(svc)
    noop = make_update_noop_delta("delta-2", "main", "version-1", "hero")
    with pytest.raises(CanonValidationError):
        await svc.commit(
            delta=noop,
            approval=make_approval(noop, approval_ref="approval-2"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}


async def test_invalid_candidate_is_rejected_and_writes_nothing(session_factory: Factory) -> None:
    svc = service(session_factory)
    await svc.create_branch(main_branch_command())
    delta = make_event_delta("delta-1", "main", None, event_id="arrival", participant="ghost")
    with pytest.raises(CanonValidationError):
        await svc.commit(
            delta=delta,
            approval=make_approval(delta, approval_ref="approval-1"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )
    assert await authority_counts(session_factory) == {"deltas": 0, "versions": 0, "projections": 0}


async def test_add_then_retire_fact_in_one_delta_is_rejected_and_writes_nothing(
    session_factory: Factory,
) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1", "version-2"]).__next__)
    await svc.create_branch(main_branch_command())
    await commit_genesis(svc)  # adds entity "hero"
    # ADD_FACT(effective_from=T2) then RETIRE_FACT(effective_until=T1): the fact is absent
    # from the resolved base and its final interval is inverted.
    delta = make_add_then_retire_fact_delta(
        "delta-2", "main", "version-1", subject="hero", effective_from=T2, effective_until=T1
    )
    with pytest.raises(CanonValidationError):
        await svc.commit(
            delta=delta,
            approval=make_approval(delta, approval_ref="approval-2"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}


async def test_reusing_an_approval_ref_for_another_delta_is_rejected(session_factory: Factory) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1"]).__next__)
    await svc.create_branch(main_branch_command())
    await commit_genesis(svc)
    other = make_entity_delta("delta-2", "main", "version-1", "villain")
    reused = make_approval(other, approval_ref="approval-1")
    with pytest.raises(CanonApprovalError):
        await svc.commit(delta=other, approval=reused, project_name=PROJECT, user_id=USER, now=NOW)
    assert await authority_counts(session_factory) == {"deltas": 1, "versions": 1, "projections": 1}


async def test_create_branch_retry_returns_existing_and_conflicts_on_mismatch(
    session_factory: Factory,
) -> None:
    svc = service(session_factory)
    first = await svc.create_branch(main_branch_command())
    again = await svc.create_branch(main_branch_command())
    assert again == first
    with pytest.raises(CanonIdentityConflictError):
        await svc.create_branch(main_branch_command().model_copy(update={"created_by": "different"}))
    with pytest.raises(CanonIdentityConflictError):
        await svc.create_branch(main_branch_command().model_copy(update={"created_at": LATER}))


async def test_create_narrative_branch_pins_a_parent_version(session_factory: Factory) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1"]).__next__)
    await svc.create_branch(main_branch_command())
    await commit_genesis(svc)
    story = await svc.create_branch(
        narrative_branch_command(branch_id="story", parent_branch_id="main", parent_version_id="version-1")
    )
    assert story.branch_type is CanonBranchType.NARRATIVE_BRANCH
    assert story.parent_version_id == "version-1"
    with pytest.raises((CanonNotFoundError, CanonValidationError)):
        await svc.create_branch(
            narrative_branch_command(branch_id="story-2", parent_branch_id="main", parent_version_id="ghost")
        )


async def test_mutating_the_delta_during_the_commit_does_not_change_the_persisted_bytes(
    session_factory: Factory,
) -> None:
    original = make_entity_delta("delta-1", "main", None, "hero")
    approval = make_approval(original, approval_ref="approval-1")

    def mutate_at_lock(stage: CanonCommitStage) -> None:
        if stage is CanonCommitStage.BEFORE_DELTA_INSERT:
            original.operations[0].target_id = "tampered"
            original.operations[0].entity = Entity(
                entity_id="tampered", entity_type=EntityType.CHARACTER, canonical_name="Tampered", aliases=[]
            )

    svc = CanonTransactionService(
        canon_authority_uow_factory(session_factory),
        version_id_factory=iter(["version-1"]).__next__,
        fault_hook=mutate_at_lock,
    )
    await svc.create_branch(main_branch_command())
    await svc.commit(delta=original, approval=approval, project_name=PROJECT, user_id=USER, now=NOW)

    async with canon_authority_uow_factory(session_factory)() as uow:
        stored = await uow.repository.get_accepted_delta(canon_delta_id="delta-1", project_name=PROJECT, user_id=USER)
    assert stored is not None
    assert [operation.target_id for operation in stored.delta.operations] == ["hero"]
    verify_canon_delta_hash(stored.delta)


async def test_narrative_branch_first_commit_records_the_pinned_parent(session_factory: Factory) -> None:
    svc = service(session_factory, version_id_factory=iter(["version-1", "version-2"]).__next__)
    await svc.create_branch(main_branch_command())
    await commit_genesis(svc)
    await svc.create_branch(
        narrative_branch_command(branch_id="story", parent_branch_id="main", parent_version_id="version-1")
    )
    child = make_entity_delta("delta-story-1", "story", "version-1", "villain")
    result = await svc.commit(
        delta=child,
        approval=make_approval(child, approval_ref="approval-story-1"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    assert result.version.canon_version_id == "version-2"
    assert result.version.version_number == 1
    assert result.version.parent_version_id == "version-1"
