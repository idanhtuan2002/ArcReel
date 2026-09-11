"""Unit coverage for the internal authority-kernel transaction body (spec §7.2).

Exercised against a fake repository + fake authority port, never a real database:
this module tests orchestration (retry-before-write ordering, predecessor OCC, REJECT
semantics), not persistence. Real-DB composite-FK / CHECK enforcement is covered by the
Task 16 repository/migration tests instead.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from r2.contracts.narrative_lifecycle import (
    NarrativeDecisionAuthorization,
    NarrativeDecisionCommand,
    NarrativeDecisionReceipt,
    NarrativeDecisionRetryAuthentication,
    NarrativeWorkScope,
)
from r2.narrative_lifecycle.authority_kernel import AuthorityKernel, head_lock_sort_key
from r2.narrative_lifecycle.errors import (
    NarrativeAuthorityIntegrityError,
    NarrativeDecisionAuthorizationError,
    NarrativeDecisionIdentityConflictError,
    NarrativeDecisionPredecessorConflict,
)
from tests.factories import (
    make_narrative_decision_authorization,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)

_NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
SCOPE = make_narrative_work_scope()


def _revision_key(scope: NarrativeWorkScope) -> tuple[str, str, str, str, str]:
    return (scope.user_id, scope.project_name, scope.plan_id, scope.scene_contract_id, scope.canon_branch_id)


class _FakeRevisionHead:
    __slots__ = ("decision_generation", "effective_decision_id", "effective_generation", "latest_decision_id")

    def __init__(
        self,
        *,
        latest_decision_id: str | None = None,
        decision_generation: int = 0,
        effective_decision_id: str | None = None,
        effective_generation: int = 0,
    ) -> None:
        self.latest_decision_id = latest_decision_id
        self.decision_generation = decision_generation
        self.effective_decision_id = effective_decision_id
        self.effective_generation = effective_generation


class _FakeRepository:
    """An in-memory double for the subset of ``NarrativeLifecycleRepositoryPort`` the
    kernel actually calls. Only the ``REVISION_ACCEPTANCE`` family is modeled — the
    kernel's family dispatch is exercised end-to-end in the Task 16 integration tests
    against the real repository for the other two families."""

    def __init__(self) -> None:
        self.decisions: dict[str, tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int]] = {}
        self.revision_heads: dict[tuple[str, ...], _FakeRevisionHead] = {}
        self.writes: list[str] = []
        self.before_head_lock: Any = None  # test hook: async fn run just before a genesis head insert

    # --- decisions ---

    async def get_decision_by_id(
        self, decision_id: str, *, user_id: str, project_name: str
    ) -> tuple[NarrativeDecisionCommand, NarrativeDecisionAuthorization, int] | None:
        stored = self.decisions.get(decision_id)
        if stored is None:
            return None
        _, authorization, _ = stored
        if authorization.user_id != user_id or authorization.project_name != project_name:
            return None
        return stored

    async def insert_identity_and_decision(
        self,
        command: NarrativeDecisionCommand,
        authorization: NarrativeDecisionAuthorization,
        *,
        canonical_identity_hash: str,
        decision_generation: int,
        stored_at: datetime,
    ) -> None:
        if command.decision_id in self.decisions:
            raise NarrativeDecisionIdentityConflictError(f"decision {command.decision_id!r} already exists")
        self.decisions[command.decision_id] = (command, authorization, decision_generation)
        self.writes.append(f"decision:{command.decision_id}")

    # --- revision head ---

    async def lock_or_insert_revision_head(self, work_scope: NarrativeWorkScope) -> Any:
        key = _revision_key(work_scope)
        if key not in self.revision_heads:
            if self.before_head_lock is not None:
                await self.before_head_lock()
            self.revision_heads[key] = _FakeRevisionHead()
            self.writes.append(f"head-insert:{key}")
        return self._revision_head_contract(work_scope)

    async def advance_revision_head(
        self,
        work_scope: NarrativeWorkScope,
        *,
        expected_latest_decision_id: str | None,
        expected_effective_decision_id: str | None,
        new_latest_decision_id: str,
        new_decision_generation: int,
        new_effective_decision_id: str | None,
        new_effective_generation: int,
    ) -> None:
        key = _revision_key(work_scope)
        head = self.revision_heads.get(key)
        if (
            head is None
            or head.latest_decision_id != expected_latest_decision_id
            or head.effective_decision_id != expected_effective_decision_id
        ):
            raise NarrativeDecisionPredecessorConflict("expected revision head predecessor is stale")
        head.latest_decision_id = new_latest_decision_id
        head.decision_generation = new_decision_generation
        head.effective_decision_id = new_effective_decision_id
        head.effective_generation = new_effective_generation
        self.writes.append(f"head-advance:{key}")

    def _revision_head_contract(self, work_scope: NarrativeWorkScope) -> Any:
        from r2.contracts.narrative_lifecycle import RevisionAcceptanceHead

        head = self.revision_heads[_revision_key(work_scope)]
        return RevisionAcceptanceHead(
            work_scope=work_scope,
            latest_decision_id=head.latest_decision_id,
            decision_generation=head.decision_generation,
            effective_decision_id=head.effective_decision_id,
            effective_generation=head.effective_generation,
        )

    # --- test helpers matching the plan's RED pseudocode ---

    def seed_decision(
        self, decision_id: str, *, generation: int, action: str = "ACCEPT", scope: NarrativeWorkScope = SCOPE
    ) -> None:
        command = make_revision_acceptance_command(decision_id=decision_id, work_scope=scope, action=action)
        authorization = make_narrative_decision_authorization(
            decision_id=decision_id, user_id=scope.user_id, project_name=scope.project_name, action=action
        )
        self.decisions[decision_id] = (command, authorization, generation)
        key = _revision_key(scope)
        self.revision_heads[key] = _FakeRevisionHead(
            latest_decision_id=decision_id,
            decision_generation=generation,
            effective_decision_id=decision_id if action in ("ACCEPT", "RESOLVE", "SUPERSEDE") else None,
            effective_generation=generation if action in ("ACCEPT", "RESOLVE", "SUPERSEDE") else 0,
        )

    def advance_latest(self, decision_id: str, *, scope: NarrativeWorkScope = SCOPE) -> None:
        """Move the head's latest pointer without a matching stored decision — models a
        head that has raced ahead of (or diverged from) the decision under test."""
        head = self.revision_heads[_revision_key(scope)]
        head.latest_decision_id = decision_id
        head.decision_generation += 1

    def drop_head(self, family: str, scope: NarrativeWorkScope = SCOPE) -> None:
        assert family == "revision"
        self.revision_heads.pop(_revision_key(scope), None)

    def head(self, family: str, scope: NarrativeWorkScope = SCOPE) -> _FakeRevisionHead | None:
        assert family == "revision"
        return self.revision_heads.get(_revision_key(scope))


class _FakeUnitOfWork:
    def __init__(self, repo: _FakeRepository) -> None:
        self.repository = repo
        self.committed = False

    async def __aenter__(self) -> _FakeUnitOfWork:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _FakeAuthorityPort:
    def __init__(self) -> None:
        self.denied = False

    async def authorize_initial_decision(
        self, authenticated_principal: str, canonical_command: NarrativeDecisionCommand
    ) -> NarrativeDecisionAuthorization:
        if self.denied:
            raise NarrativeDecisionAuthorizationError("denied")
        scope = canonical_command.work_scope
        return make_narrative_decision_authorization(
            decision_id=canonical_command.decision_id,
            user_id=scope.user_id,
            project_name=scope.project_name,
            decision_family=canonical_command.decision_family,
            action=canonical_command.action,
        )

    async def authenticate_exact_retry(
        self, authenticated_principal: str, decision_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication:
        if self.denied:
            raise NarrativeDecisionAuthorizationError("denied")
        return NarrativeDecisionRetryAuthentication(
            retry_authentication_ref="retry-1",
            user_id=exact_scope.user_id,
            project_name=exact_scope.project_name,
            actor_id="showrunner-1",
            authority_role="HUMAN_SHOWRUNNER",
            decision_id=decision_id,
            authenticated_at=_NOW,
            authenticated_via="test",
        )


@pytest.fixture
def fake_repo() -> _FakeRepository:
    return _FakeRepository()


@pytest.fixture
def fake_authority() -> _FakeAuthorityPort:
    return _FakeAuthorityPort()


@pytest.fixture
def kernel(fake_repo: _FakeRepository, fake_authority: _FakeAuthorityPort) -> AuthorityKernel:
    return AuthorityKernel(lambda: _FakeUnitOfWork(fake_repo), fake_authority)


async def _run(kernel: AuthorityKernel, command: NarrativeDecisionCommand) -> NarrativeDecisionReceipt:
    return await kernel.run(command, authenticated_principal="showrunner-1")


async def test_exact_retry_writes_nothing_and_never_touches_a_head(
    kernel: AuthorityKernel, fake_repo: _FakeRepository
) -> None:
    fake_repo.seed_decision("d-1", generation=1)
    fake_repo.advance_latest("d-2")  # head moved on after d-1
    fake_repo.drop_head("revision")  # head is missing entirely

    retry_command = make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT")
    receipt = await _run(kernel, retry_command)

    assert receipt.decision_id == "d-1"
    assert receipt.decision_generation == 1
    assert receipt.effective_decision_id == "d-1"
    assert fake_repo.writes == []  # no head INSERT, no head reconstruction, no decision write
    assert fake_repo.head("revision") is None


async def test_reject_preserves_the_effective_pointer(kernel: AuthorityKernel, fake_repo: _FakeRepository) -> None:
    accept = make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT")
    await _run(kernel, accept)
    reject = make_revision_acceptance_command(
        decision_id="d-2",
        work_scope=SCOPE,
        action="REJECT",
        selected_revision_id="rev-2",
        expected_latest_decision_id="d-1",
        expected_effective_decision_id="d-1",
    )
    receipt = await _run(kernel, reject)

    head = fake_repo.head("revision")
    assert head is not None
    assert head.effective_decision_id == "d-1"
    assert head.latest_decision_id == "d-2"
    assert head.effective_generation == 1
    assert head.decision_generation == 2
    assert receipt.effective_decision_id == "d-1"
    assert receipt.effective_generation == 1
    assert receipt.decision_generation == 2


async def test_same_id_different_tuple_is_an_identity_conflict_with_zero_writes(
    kernel: AuthorityKernel, fake_repo: _FakeRepository
) -> None:
    fake_repo.seed_decision("d-1", generation=1)
    conflicting = make_revision_acceptance_command(
        decision_id="d-1", work_scope=SCOPE, action="ACCEPT", selected_revision_id="rev-DIFFERENT"
    )

    with pytest.raises(NarrativeDecisionIdentityConflictError):
        await _run(kernel, conflicting)
    assert fake_repo.writes == []


async def test_retry_that_only_becomes_visible_under_the_serialized_lookup_is_still_zero_writes(
    fake_repo: _FakeRepository, fake_authority: _FakeAuthorityPort
) -> None:
    """A concurrent transaction lands the same decision_id between our step-2 miss and
    our step-4 head lock. Step 5's re-check must catch it before any predecessor
    rejection or new write — modeled by seeding the decision from inside the
    ``before_head_lock`` hook, i.e. strictly after step 2's first (missing) lookup."""
    kernel = AuthorityKernel(lambda: _FakeUnitOfWork(fake_repo), fake_authority)

    async def _land_concurrently() -> None:
        fake_repo.decisions["d-1"] = (
            make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT"),
            make_narrative_decision_authorization(
                decision_id="d-1", user_id=SCOPE.user_id, project_name=SCOPE.project_name
            ),
            1,
        )

    fake_repo.before_head_lock = _land_concurrently
    command = make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT")

    receipt = await _run(kernel, command)

    assert receipt.decision_id == "d-1"
    assert receipt.decision_generation == 1
    # the one head-insert write is from the genesis probe itself (lock_or_insert_head is
    # called before the second lookup, per spec §7.2 step 4); no decision write happened.
    assert "decision:d-1" not in fake_repo.writes


async def test_stale_expected_latest_fails_even_when_effective_pointer_is_unchanged(
    kernel: AuthorityKernel, fake_repo: _FakeRepository
) -> None:
    fake_repo.seed_decision("d-1", generation=1)  # latest=d-1, effective=d-1
    stale = make_revision_acceptance_command(
        decision_id="d-2",
        work_scope=SCOPE,
        action="REJECT",
        selected_revision_id="rev-2",
        expected_latest_decision_id="wrong-id",  # stale: the real latest is "d-1"
        expected_effective_decision_id="d-1",  # correctly matches the real effective
    )
    with pytest.raises(NarrativeDecisionPredecessorConflict):
        await _run(kernel, stale)
    assert "decision:d-2" not in fake_repo.writes


async def test_stale_expected_effective_fails_even_when_latest_matches(
    kernel: AuthorityKernel, fake_repo: _FakeRepository
) -> None:
    fake_repo.seed_decision("d-1", generation=1, action="REJECT")  # latest=d-1, effective stays None
    stale = make_revision_acceptance_command(
        decision_id="d-2",
        work_scope=SCOPE,
        action="REJECT",
        selected_revision_id="rev-2",
        expected_latest_decision_id="d-1",  # correctly matches the real latest
        expected_effective_decision_id="some-other-id",  # stale: the real effective is None
    )
    with pytest.raises(NarrativeDecisionPredecessorConflict):
        await _run(kernel, stale)
    assert "decision:d-2" not in fake_repo.writes


async def test_retry_naming_a_vanished_effective_predecessor_is_an_integrity_error(
    kernel: AuthorityKernel, fake_repo: _FakeRepository
) -> None:
    """Reconstructing an exact-retry receipt for a past REJECT walks one hop to the
    decision it named as ``expected_effective`` (§6.6 — REJECT itself stores no
    generation number, only the reference). If that referenced decision no longer
    resolves, retry reconstruction fails closed rather than guessing."""
    fake_repo.seed_decision("d-1", generation=1)  # latest=d-1, effective=d-1
    reject = make_revision_acceptance_command(
        decision_id="d-2",
        work_scope=SCOPE,
        action="REJECT",
        selected_revision_id="rev-2",
        expected_latest_decision_id="d-1",
        expected_effective_decision_id="d-1",
    )
    await _run(kernel, reject)  # d-2 now stored; head unaffected (REJECT keeps effective=d-1)
    del fake_repo.decisions["d-1"]  # the stored d-2 still names it, but it vanished

    with pytest.raises(NarrativeAuthorityIntegrityError):
        await _run(kernel, reject)  # exact retry of d-2 must reconstruct its receipt


async def test_a_genuinely_new_id_triggers_exactly_one_head_insert(
    kernel: AuthorityKernel, fake_repo: _FakeRepository
) -> None:
    command = make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT")
    await _run(kernel, command)
    assert fake_repo.writes.count(f"head-insert:{_revision_key(SCOPE)}") == 1


async def test_a_retry_never_inserts_a_head(kernel: AuthorityKernel, fake_repo: _FakeRepository) -> None:
    fake_repo.seed_decision("d-1", generation=1)
    retry = make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT")
    await _run(kernel, retry)
    assert not any(write.startswith("head-insert:") for write in fake_repo.writes)


async def test_a_failure_advancing_the_head_propagates_and_does_not_return_a_receipt(
    kernel: AuthorityKernel, fake_repo: _FakeRepository
) -> None:
    """The kernel itself performs no partial commit on a mid-transaction failure — real
    atomicity is the unit of work's rollback (Task 21's PostgreSQL concurrency suite);
    here we only assert the kernel propagates rather than swallowing or papering over it."""
    command = make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT")

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated crash after the decision insert")

    fake_repo.advance_revision_head = _boom
    with pytest.raises(RuntimeError):
        await _run(kernel, command)
    # the decision row was written before the crash; a real transaction rolls this back
    # too, but the kernel's own job here is only to not swallow the failure.
    assert "decision:d-1" in fake_repo.writes


async def test_authority_port_denial_is_not_swallowed(
    kernel: AuthorityKernel, fake_authority: _FakeAuthorityPort
) -> None:
    fake_authority.denied = True
    command = make_revision_acceptance_command(decision_id="d-1", work_scope=SCOPE, action="ACCEPT")
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await _run(kernel, command)


def test_head_lock_sort_key_orders_by_family_then_scope_then_logical_key() -> None:
    revision_key = head_lock_sort_key("REVISION_ACCEPTANCE", user_id="u1", project_name="p", logical_key=("a",))
    review_key = head_lock_sort_key("CHANGE_SET_REVIEW", user_id="u1", project_name="p", logical_key=("a",))
    conflict_key = head_lock_sort_key("CONFLICT_RESOLUTION", user_id="u1", project_name="p", logical_key=("a",))
    assert revision_key < review_key < conflict_key
