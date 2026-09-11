"""PostgreSQL-only concurrency coverage for the M5C-2 authority kernel (Task 21,
freezing the checkpoint).

Two genuinely independent connections race the same head, synchronized with
``asyncio.Barrier`` so both reach the serialization point before either proceeds — never
``time.sleep``, never implicit ordering. Skipped on SQLite: the StaticPool test engine
shares one connection and SQLite has no real row-level locking, so there is nothing to
race against.

The barrier is injected via a test-only ``SqlAlchemyNarrativeLifecycleUnitOfWork``
subclass that swaps in a ``NarrativeLifecycleRepository`` subclass awaiting the barrier
immediately before the one repository call that actually serializes the race — the same
"subclass the concrete unit of work" pattern Task 13's ``_FaultOnCommitUnitOfWork``
already established, not a new production seam.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork
from lib.db.repositories.narrative_lifecycle import NarrativeLifecycleRepository
from r2.contracts.narrative_lifecycle import (
    ChangeSetReviewHead,
    ConflictResolutionCommand,
    NarrativeWorkScope,
    RevisionAcceptanceHead,
)
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.authority_kernel import AuthorityKernel
from tests.factories import (
    make_change_set_review_command,
    make_narrative_change_set,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER, FakeShowrunnerAuthorityPort
from tests.integration.r2.narrative_lifecycle.test_evidence_service import _attempt, _candidate, _result, _revision

type Factory = async_sessionmaker[AsyncSession]

_DEADLOCK_TIMEOUT_S = 10.0


def _scope() -> NarrativeWorkScope:
    return make_narrative_work_scope()


async def _skip_unless_postgres(session_factory: Factory) -> None:
    async with session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("concurrency races need real row-level locking (PostgreSQL only)")


def _outcome_type(value: object) -> str:
    return type(value).__name__


async def _run_capturing(coro: Coroutine[Any, Any, object]) -> object:
    try:
        return await coro
    except Exception as exc:
        return exc


class _BarrierBeforeRevisionHeadLockRepository(NarrativeLifecycleRepository):
    def __init__(self, session: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def lock_or_insert_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead:
        await self._barrier.wait()
        return await super().lock_or_insert_revision_head(work_scope)


class _BarrierBeforeRevisionHeadLockUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    def __init__(self, session_factory: Factory, barrier: asyncio.Barrier) -> None:
        super().__init__(session_factory)
        self._barrier = barrier

    async def __aenter__(self) -> _BarrierBeforeRevisionHeadLockUnitOfWork:
        await super().__aenter__()
        self.repository = _BarrierBeforeRevisionHeadLockRepository(self.session, self._barrier)
        return self


class _BarrierBeforeChangeSetReviewHeadLockRepository(NarrativeLifecycleRepository):
    def __init__(self, session: AsyncSession, barrier: asyncio.Barrier) -> None:
        super().__init__(session)
        self._barrier = barrier

    async def lock_or_insert_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead:
        await self._barrier.wait()
        return await super().lock_or_insert_change_set_review_head(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            change_set_lineage_id=change_set_lineage_id,
            user_id=user_id,
            project_name=project_name,
        )


class _BarrierBeforeChangeSetReviewHeadLockUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    def __init__(self, session_factory: Factory, barrier: asyncio.Barrier) -> None:
        super().__init__(session_factory)
        self._barrier = barrier

    async def __aenter__(self) -> _BarrierBeforeChangeSetReviewHeadLockUnitOfWork:
        await super().__aenter__()
        self.repository = _BarrierBeforeChangeSetReviewHeadLockRepository(self.session, self._barrier)
        return self


class _FaultBeforeCommitUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    """Flushes every write normally, then fails the commit — nothing reaches the DB."""

    async def commit(self) -> None:
        raise RuntimeError("injected fault before commit")


async def test_two_concurrent_genesis_revision_decisions_yield_one_receipt_and_one_conflict(
    concurrent_session_factory: Factory,
) -> None:
    await _skip_unless_postgres(concurrent_session_factory)
    barrier = asyncio.Barrier(2)
    kernel = AuthorityKernel(
        lambda: _BarrierBeforeRevisionHeadLockUnitOfWork(concurrent_session_factory, barrier),
        FakeShowrunnerAuthorityPort(),
    )
    scope = _scope()

    async def run(decision_id: str) -> object:
        command = make_revision_acceptance_command(decision_id=decision_id, work_scope=scope, action="ACCEPT")
        return await kernel.run(command, authenticated_principal=SHOWRUNNER)

    a, b = await asyncio.wait_for(
        asyncio.gather(_run_capturing(run("d-a")), _run_capturing(run("d-b"))), timeout=_DEADLOCK_TIMEOUT_S
    )
    outcomes = sorted(_outcome_type(x) for x in (a, b))
    assert outcomes == ["NarrativeDecisionPredecessorConflict", "NarrativeDecisionReceipt"]


async def test_two_concurrent_genesis_change_set_review_decisions_yield_one_receipt_and_one_conflict(
    concurrent_session_factory: Factory,
) -> None:
    await _skip_unless_postgres(concurrent_session_factory)
    scope = _scope()
    fake_showrunner = FakeShowrunnerAuthorityPort()
    setup_service = NarrativeAcceptanceService(
        lambda: SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory), fake_showrunner
    )
    await setup_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )

    barrier = asyncio.Barrier(2)
    kernel = AuthorityKernel(
        lambda: _BarrierBeforeChangeSetReviewHeadLockUnitOfWork(concurrent_session_factory, barrier), fake_showrunner
    )

    async def run(decision_id: str) -> object:
        command = make_change_set_review_command(decision_id=decision_id, work_scope=scope, action="ACCEPT")
        return await kernel.run(command, authenticated_principal=SHOWRUNNER)

    a, b = await asyncio.wait_for(
        asyncio.gather(_run_capturing(run("d-2")), _run_capturing(run("d-3"))), timeout=_DEADLOCK_TIMEOUT_S
    )
    outcomes = sorted(_outcome_type(x) for x in (a, b))
    assert outcomes == ["NarrativeDecisionPredecessorConflict", "NarrativeDecisionReceipt"]


async def test_two_concurrent_conflict_lineage_geneses_on_one_subject_do_not_deadlock_in_reverse_order(
    concurrent_session_factory: Factory,
) -> None:
    """Both commands name the same two competing change sets, listed in opposite order,
    and race for the same revision head first (§7.2's conflict-genesis order locks the
    revision before any change-set-review head) — so they cannot interleave their
    change-set-review locks at all; whichever wins the revision head runs its whole
    genesis to completion before the other even starts locking, and §7.3's canonical
    sort (independent of the caller's own listing order) is exercised without a second
    party ever contending for it concurrently. The loser then meets an already-committed
    lineage for the same canonical subject. Barrier lands before the revision-head lock
    — both sides can reach it unconditionally — never deeper, or a barrier a blocked
    party can never reach becomes a deadlock the test manufactures itself, not the
    production code. asyncio.wait_for turns a genuine hang into a failure, not a wait.
    """
    await _skip_unless_postgres(concurrent_session_factory)
    scope = _scope()
    fake_showrunner = FakeShowrunnerAuthorityPort()
    setup_service = NarrativeAcceptanceService(
        lambda: SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory), fake_showrunner
    )
    await setup_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory) as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt())
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-a", "cs-b")),
            [make_narrative_change_set(change_set_id="cs-a"), make_narrative_change_set(change_set_id="cs-b")],
        )
        await uow.commit()
    await setup_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-cs-a",
            selected_change_set_id="cs-a",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await setup_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-3",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-cs-b",
            selected_change_set_id="cs-b",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    barrier = asyncio.Barrier(2)
    racing_service = NarrativeAcceptanceService(
        lambda: _BarrierBeforeRevisionHeadLockUnitOfWork(concurrent_session_factory, barrier), fake_showrunner
    )

    def _genesis(decision_id: str, lineage_id: str, *, reverse: bool) -> ConflictResolutionCommand:
        pair = (("cs-a", "d-2"), ("cs-b", "d-3"))
        if reverse:
            pair = pair[::-1]
        return ConflictResolutionCommand(
            decision_id=decision_id,
            action="RESOLVE",
            work_scope=scope,
            revision_acceptance_decision_id="d-1",
            conflict_resolution_lineage_id=lineage_id,
            competing_change_set_ids=(pair[0][0], pair[1][0]),
            competing_review_decision_ids=(pair[0][1], pair[1][1]),
            chosen_resolution="keep cs-a",
            expected_latest_decision_id=None,
            expected_effective_decision_id=None,
            base_canon_version_id="cv-1",
            plan_version=2,
            scene_contract_version=1,
            context_pack_id="ctx-1",
            actor_id=SHOWRUNNER,
        )

    async def run(decision_id: str, lineage_id: str, *, reverse: bool) -> object:
        return await racing_service.resolve_change_set_conflict(
            _genesis(decision_id, lineage_id, reverse=reverse), authenticated_principal=SHOWRUNNER
        )

    a, b = await asyncio.wait_for(
        asyncio.gather(
            _run_capturing(run("d-4", "L-1", reverse=False)), _run_capturing(run("d-5", "L-2", reverse=True))
        ),
        timeout=_DEADLOCK_TIMEOUT_S,
    )
    outcomes = sorted(_outcome_type(x) for x in (a, b))
    assert outcomes == ["NarrativeConflictLineageConflict", "NarrativeDecisionReceipt"]


async def test_a_fault_before_commit_leaves_no_partial_authority_writes(concurrent_session_factory: Factory) -> None:
    await _skip_unless_postgres(concurrent_session_factory)
    scope = _scope()
    faulting_kernel = AuthorityKernel(
        lambda: _FaultBeforeCommitUnitOfWork(concurrent_session_factory), FakeShowrunnerAuthorityPort()
    )
    command = make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT")
    with pytest.raises(RuntimeError, match="injected fault"):
        await faulting_kernel.run(command, authenticated_principal=SHOWRUNNER)

    async with SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory) as uow:
        assert (
            await uow.repository.get_decision_by_id("d-1", user_id=scope.user_id, project_name=scope.project_name)
        ) is None
        assert (await uow.repository.get_revision_head(scope)) is None
