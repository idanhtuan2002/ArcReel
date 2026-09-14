"""Integration coverage for ``NarrativeAcceptanceService.admit_canon_handoff`` (Task 28,
spec §11.2 admission transaction and §11.3 frozen currentness).

Reuses ``test_compilation_service``'s seeding helpers rather than redefining them: an
admissible handoff needs the whole M5C-3 chain (accepted revision -> reviewed change set
-> admitted compilation attempt -> SUCCEEDED result -> persisted compiled delta) before
an admission can even be attempted. Local fixtures are deliberately avoided for the
evidence service: ``evidence_service`` already exists in two sibling files, and a third
copy would be a shared-facility duplication.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork, narrative_lifecycle_uow_factory
from lib.db.repositories.narrative_lifecycle import NarrativeLifecycleRepository
from r2.contracts.narrative import CanonCommitApproval, CanonDelta
from r2.contracts.narrative_lifecycle import (
    CANON_APPROVAL_BINDING_FINGERPRINT_VERSION,
    ChangeSetReviewHead,
    NarrativeDecisionRetryAuthentication,
    NarrativeWorkScope,
    RevisionAcceptanceHead,
)
from r2.narrative_lifecycle.acceptance import (
    AdmittedNarrativeHandoff,
    CanonHandoffAdmissionCommand,
    NarrativeAcceptanceService,
)
from r2.narrative_lifecycle.errors import (
    NarrativeDecisionAuthorizationError,
    NarrativeDecisionIdentityConflictError,
    NarrativeEvidenceIntegrityError,
    NarrativeHandoffConflict,
)
from r2.narrative_lifecycle.evidence import NarrativeLifecycleEvidenceService
from r2.narrative_lifecycle.hashing import compute_canon_approval_binding_fingerprint
from tests.factories import (
    NARRATIVE_LIFECYCLE_NOW,
    make_canon_commit_approval,
    make_change_set_review_command,
    make_compilation_result,
    make_narrative_change_set,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER, FakeShowrunnerAuthorityPort
from tests.integration.r2.narrative_lifecycle.test_compilation_service import _canon_delta, _compilation_command
from tests.integration.r2.narrative_lifecycle.test_evidence_service import _attempt, _candidate, _result, _revision

USER = "u1"
PROJECT = "project-a"
ATTEMPT_ID = "rev-1:0"
RESULT_ID = "cres-1"

type Factory = async_sessionmaker[AsyncSession]

_DEADLOCK_TIMEOUT_S = 10.0


def _scope(*, user_id: str = USER, project_name: str = PROJECT) -> NarrativeWorkScope:
    return make_narrative_work_scope(user_id=user_id, project_name=project_name)


def _evidence(session_factory: Factory) -> NarrativeLifecycleEvidenceService:
    return NarrativeLifecycleEvidenceService(narrative_lifecycle_uow_factory(session_factory))


def _approval(**overrides: object) -> CanonCommitApproval:
    delta = _admissible_delta()
    defaults: dict[str, object] = {
        "approval_ref": "approval-1",
        "canon_delta_id": delta.canon_delta_id,
        "payload_hash": delta.payload_hash,
        "payload_hash_algorithm": delta.payload_hash_algorithm,
        "payload_hash_version": delta.payload_hash_version,
        "content_schema_version": delta.content_schema_version,
        "project_name": PROJECT,
        "user_id": USER,
        "approved_by": SHOWRUNNER,
        "approved_at": NARRATIVE_LIFECYCLE_NOW,
    }
    defaults.update(overrides)
    return make_canon_commit_approval(**defaults)


def _admissible_delta(**overrides: object) -> CanonDelta:
    """Exactly the payload the pure compiler seals for the single-change-set seed below:
    ``author_decision_refs`` is the accepted revision decision plus every review /
    resolution decision the attempt named, and ``source_change_set_refs`` is its exact
    selection."""
    defaults: dict[str, object] = {"author_decision_refs": ["d-1", "d-2"], "source_change_set_refs": ["cs-1"]}
    defaults.update(overrides)
    return _canon_delta(**defaults)


def _handoff_command(**overrides: object) -> CanonHandoffAdmissionCommand:
    defaults: dict[str, object] = {
        "admission_id": "adm-1",
        "work_scope": _scope(),
        "compilation_attempt_id": ATTEMPT_ID,
        "generation": 0,
        "compilation_result_id": RESULT_ID,
    }
    defaults.update(overrides)
    return CanonHandoffAdmissionCommand(**defaults)


async def _seed_admissible_handoff(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> CanonDelta:
    """d-1 accepts rev-1, d-2 accepts cs-1, ``rev-1:0`` is an admitted compilation
    attempt, and ``cres-1`` is its SUCCEEDED result with a persisted compiled delta."""
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt())
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-1",)), [make_narrative_change_set(change_set_id="cs-1")]
        )
        await uow.commit()

    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=_scope(), action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=_scope(),
            action="ACCEPT",
            change_set_lineage_id="lin-cs-1",
            selected_change_set_id="cs-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    evidence = _evidence(session_factory)
    await evidence.admit_compilation(_compilation_command())
    delta = _admissible_delta()
    await evidence.record_successful_compilation(
        make_compilation_result(
            result_id=RESULT_ID,
            attempt_id=ATTEMPT_ID,
            generation=0,
            outcome="SUCCEEDED",
            canon_delta_id=delta.canon_delta_id,
            canon_delta_payload_hash=delta.payload_hash,
        ),
        delta,
    )
    return delta


async def _supersede_the_review(acceptance_service: NarrativeAcceptanceService, session_factory: Factory) -> None:
    """cs-1b replaces cs-1 in lineage ``lin-cs-1`` under decision d-2b."""
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_extraction_attempt(_attempt(attempt_id="att-2"))
        await uow.repository.insert_successful_extraction(
            _result(result_id="res-2", attempt_id="att-2", outcome="SUCCEEDED", change_set_ids=("cs-1b",)),
            [
                make_narrative_change_set(
                    change_set_id="cs-1b", change_set_lineage_id="lin-cs-1", extraction_attempt_id="att-2"
                )
            ],
        )
        await uow.commit()
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2b",
            work_scope=_scope(),
            action="SUPERSEDE",
            change_set_lineage_id="lin-cs-1",
            selected_change_set_id="cs-1b",
            expected_latest_decision_id="d-2",
            expected_effective_decision_id="d-2",
        ),
        authenticated_principal=SHOWRUNNER,
    )


async def _supersede_the_revision(acceptance_service: NarrativeAcceptanceService, session_factory: Factory) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate(candidate_id="cand-2"))
        await uow.repository.insert_revision(_revision(revision_id="rev-2", candidate_id="cand-2"))
        await uow.commit()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-1b",
            work_scope=_scope(),
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )


# --- §11.3 frozen currentness --------------------------------------------------------


async def test_supersession_before_admission_blocks_receipt_creation(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    await _supersede_the_review(acceptance_service, session_factory)
    with pytest.raises(NarrativeHandoffConflict):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
        )
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        assert (
            await uow.repository.get_exact_handoff_admission(admission_id="adm-1", project_name=PROJECT, user_id=USER)
        ) is None


async def test_supersession_after_committed_admission_does_not_invalidate_the_receipt(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    admitted = await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    await _supersede_the_revision(acceptance_service, session_factory)
    again = await acceptance_service.admit_canon_handoff(
        _handoff_command(admission_id=admitted.admission_id),
        authenticated_principal=SHOWRUNNER,
        canon_commit_approval=_approval(),
    )
    assert again.admission_id == admitted.admission_id
    assert again.admission == admitted.admission
    assert admitted.revision_acceptance_decision_id == "d-1"


# --- §11.2 the admitted tuple --------------------------------------------------------


async def test_the_admitted_handoff_carries_the_persisted_delta_and_approval(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    delta = await _seed_admissible_handoff(acceptance_service, session_factory)
    approval = _approval()
    admitted = await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=approval
    )
    assert isinstance(admitted, AdmittedNarrativeHandoff)
    assert admitted.canon_delta == delta
    assert admitted.canon_commit_approval == approval
    assert admitted.admission.canon_delta_payload_hash == delta.payload_hash
    assert admitted.admission.canon_commit_approval_fingerprint == compute_canon_approval_binding_fingerprint(approval)
    assert admitted.admission.canon_commit_approval_fingerprint_algorithm == "sha256"
    assert admitted.admission.canon_commit_approval_fingerprint_version == CANON_APPROVAL_BINDING_FINGERPRINT_VERSION
    assert admitted.admission.actor_id == SHOWRUNNER
    assert admitted.admission.base_canon_version_id == "cv-1"
    assert admitted.admission.revision_acceptance_decision_id == "d-1"
    assert admitted.admission.review_decision_ids == ("d-2",)
    assert admitted.admission.conflict_resolution_decision_ids == ()


async def test_the_admission_records_every_head_it_locked_in_canonical_order(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    admitted = await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    families = [head.head_family for head in admitted.admission.observed_heads]
    assert families == ["REVISION_ACCEPTANCE", "CHANGE_SET_REVIEW"]
    assert [head.effective_decision_id for head in admitted.admission.observed_heads] == ["d-1", "d-2"]
    assert admitted.admission.observed_heads[1].logical_key == ("d-1", "lin-cs-1")


# --- exact retry vs identity conflict ------------------------------------------------


async def test_the_same_admission_id_with_another_result_tuple_is_an_identity_conflict(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    with pytest.raises(NarrativeDecisionIdentityConflictError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(compilation_result_id="cres-9"),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(),
        )


async def test_the_same_admission_id_with_another_approval_ref_fails(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    with pytest.raises(NarrativeDecisionIdentityConflictError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(approval_ref="approval-2"),
        )


async def test_the_same_admission_id_with_a_changed_approval_timestamp_fails(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    """One second of drift changes the approval-binding fingerprint, so the retry can no
    longer prove it names the exact existing M5A approval lineage."""
    await _seed_admissible_handoff(acceptance_service, session_factory)
    await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    drifted = _approval(approved_at=NARRATIVE_LIFECYCLE_NOW + timedelta(seconds=1))
    assert compute_canon_approval_binding_fingerprint(drifted) != compute_canon_approval_binding_fingerprint(
        _approval()
    )
    with pytest.raises(NarrativeDecisionIdentityConflictError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=drifted
        )


async def test_an_admission_id_already_owned_by_another_scope_is_an_identity_conflict(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    with pytest.raises(NarrativeDecisionIdentityConflictError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(work_scope=_scope(project_name="project-b")),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(project_name="project-b"),
        )


# --- approval / delta binding --------------------------------------------------------


async def test_an_approval_naming_another_delta_hash_blocks_admission(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(payload_hash="sha256:not-the-delta"),
        )


async def test_an_approval_naming_another_canon_delta_id_blocks_admission(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(canon_delta_id="delta-other"),
        )


async def test_an_approval_from_another_actor_than_the_admitting_showrunner_blocks_admission(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(approved_by="someone-else"),
        )


async def test_an_approval_issued_before_the_delta_existed_blocks_admission(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(approved_at=NARRATIVE_LIFECYCLE_NOW - timedelta(seconds=1)),
        )


async def test_an_approval_from_another_scope_blocks_admission(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(project_name="project-b"),
        )


# --- compilation evidence ------------------------------------------------------------


async def test_a_non_successful_compilation_result_cannot_be_admitted(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt())
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-1",)), [make_narrative_change_set(change_set_id="cs-1")]
        )
        await uow.commit()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=_scope(), action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=_scope(),
            action="ACCEPT",
            change_set_lineage_id="lin-cs-1",
            selected_change_set_id="cs-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    evidence = _evidence(session_factory)
    await evidence.admit_compilation(_compilation_command())
    await evidence.record_compilation_without_delta(
        make_compilation_result(result_id=RESULT_ID, attempt_id=ATTEMPT_ID, generation=0, outcome="ABSTAINED")
    )
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
        )


async def test_a_stale_result_id_for_this_attempt_generation_cannot_be_admitted(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(compilation_result_id="cres-stale"),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(),
        )


async def test_an_unknown_compilation_attempt_cannot_be_admitted(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(compilation_attempt_id="rev-9:0"),
            authenticated_principal=SHOWRUNNER,
            canon_commit_approval=_approval(),
        )


# --- authority -----------------------------------------------------------------------


async def test_a_principal_without_the_showrunner_grant_cannot_admit(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await acceptance_service.admit_canon_handoff(
            _handoff_command(), authenticated_principal="intruder", canon_commit_approval=_approval()
        )
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        assert (
            await uow.repository.get_exact_handoff_admission(admission_id="adm-1", project_name=PROJECT, user_id=USER)
        ) is None


# --- PostgreSQL concurrency ----------------------------------------------------------


class _HookBeforeReviewHeadLockRepository(NarrativeLifecycleRepository):
    """Runs one injected coroutine at the exact naked-read / head-lock boundary: every
    decision this admission names has already been read without a lock, and no head is
    held yet."""

    def __init__(self, session: AsyncSession, hook: Callable[[], Awaitable[None]]) -> None:
        super().__init__(session)
        self._hook: Callable[[], Awaitable[None]] | None = hook

    async def lock_existing_change_set_review_head(
        self, *, revision_acceptance_decision_id: str, change_set_lineage_id: str, user_id: str, project_name: str
    ) -> ChangeSetReviewHead | None:
        if self._hook is not None:
            hook, self._hook = self._hook, None
            await hook()
        return await super().lock_existing_change_set_review_head(
            revision_acceptance_decision_id=revision_acceptance_decision_id,
            change_set_lineage_id=change_set_lineage_id,
            user_id=user_id,
            project_name=project_name,
        )


class _HookBeforeReviewHeadLockUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    def __init__(self, session_factory: Factory, hook: Callable[[], Awaitable[None]]) -> None:
        super().__init__(session_factory)
        self._hook = hook

    async def __aenter__(self) -> _HookBeforeReviewHeadLockUnitOfWork:
        await super().__aenter__()
        self.repository = _HookBeforeReviewHeadLockRepository(self.session, self._hook)
        return self


async def test_a_supersession_concurrent_with_validation_cannot_land_invisibly(
    concurrent_session_factory: Factory, fake_showrunner: FakeShowrunnerAuthorityPort
) -> None:
    """A supersession committed on a second connection after the admission's unlocked
    decision reads, but before it takes any head lock, must still be observed: the
    locked read is the authority, never the naked one."""
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("this race needs two real connections and row-level locking (PostgreSQL only)")

    setup_service = NarrativeAcceptanceService(
        lambda: SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory), fake_showrunner
    )
    await _seed_admissible_handoff(setup_service, concurrent_session_factory)

    async def supersede_on_another_connection() -> None:
        await asyncio.wait_for(
            _supersede_the_review(setup_service, concurrent_session_factory), timeout=_DEADLOCK_TIMEOUT_S
        )

    racing_service = NarrativeAcceptanceService(
        lambda: _HookBeforeReviewHeadLockUnitOfWork(concurrent_session_factory, supersede_on_another_connection),
        fake_showrunner,
    )
    with pytest.raises(NarrativeHandoffConflict):
        await asyncio.wait_for(
            racing_service.admit_canon_handoff(
                _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
            ),
            timeout=_DEADLOCK_TIMEOUT_S,
        )
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory) as uow:
        # The hook really did commit on the other connection while the admission was
        # mid-validation — without this the test would pass vacuously.
        head = await uow.repository.get_change_set_review_head(
            revision_acceptance_decision_id="d-1",
            change_set_lineage_id="lin-cs-1",
            user_id=USER,
            project_name=PROJECT,
        )
        assert head is not None
        assert head.effective_decision_id == "d-2b"
        assert (
            await uow.repository.get_exact_handoff_admission(admission_id="adm-1", project_name=PROJECT, user_id=USER)
        ) is None


class _HookBeforeRevisionHeadLockRepository(NarrativeLifecycleRepository):
    """Fires one injected coroutine before the very first lock this admission takes, so
    the hook can run a whole competing transaction on another connection without
    contending for anything the hooked transaction already holds."""

    def __init__(self, session: AsyncSession, hook: Callable[[], Awaitable[None]]) -> None:
        super().__init__(session)
        self._hook: Callable[[], Awaitable[None]] | None = hook

    async def lock_existing_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None:
        if self._hook is not None:
            hook, self._hook = self._hook, None
            await hook()
        return await super().lock_existing_revision_head(work_scope)


class _HookBeforeRevisionHeadLockUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    def __init__(self, session_factory: Factory, hook: Callable[[], Awaitable[None]]) -> None:
        super().__init__(session_factory)
        self._hook = hook

    async def __aenter__(self) -> _HookBeforeRevisionHeadLockUnitOfWork:
        await super().__aenter__()
        self.repository = _HookBeforeRevisionHeadLockRepository(self.session, self._hook)
        return self


async def test_a_concurrent_duplicate_admission_replays_the_original_receipt(
    concurrent_session_factory: Factory, fake_showrunner: FakeShowrunnerAuthorityPort
) -> None:
    """Two transactions submitting the identical admission serialize on these locks. The
    loser's pre-lock retry lookup ran before the winner committed, so it must re-resolve
    the retry once it holds the locks and replay the winner's receipt — never fall through
    to a unique violation, which would contradict ``NarrativeHandoffAdmission``'s own
    "same ID with the exact same full tuple returns the original receipt" contract in
    exactly the response-lost-retry scenario section 11.3 calls out."""
    async with concurrent_session_factory() as probe:
        if probe.bind.dialect.name == "sqlite":
            pytest.skip("this race needs two real connections and row-level locking (PostgreSQL only)")

    setup_service = NarrativeAcceptanceService(
        lambda: SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory), fake_showrunner
    )
    await _seed_admissible_handoff(setup_service, concurrent_session_factory)
    winner: list[AdmittedNarrativeHandoff] = []

    async def admit_the_same_thing_on_another_connection() -> None:
        winner.append(
            await asyncio.wait_for(
                setup_service.admit_canon_handoff(
                    _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
                ),
                timeout=_DEADLOCK_TIMEOUT_S,
            )
        )

    racing_service = NarrativeAcceptanceService(
        lambda: _HookBeforeRevisionHeadLockUnitOfWork(
            concurrent_session_factory, admit_the_same_thing_on_another_connection
        ),
        fake_showrunner,
    )
    loser = await asyncio.wait_for(
        racing_service.admit_canon_handoff(
            _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
        ),
        timeout=_DEADLOCK_TIMEOUT_S,
    )
    assert len(winner) == 1
    assert loser.admission == winner[0].admission
    assert loser.canon_delta == winner[0].canon_delta
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(concurrent_session_factory) as uow:
        stored = await uow.repository.get_exact_handoff_admission(
            admission_id="adm-1", project_name=PROJECT, user_id=USER
        )
        assert stored == loser.admission


# --- the authority-port surface an admission is allowed to use -----------------------


class _NoRetryPathAuthorityPort(FakeShowrunnerAuthorityPort):
    """A production-shaped adapter: ``authenticate_exact_retry``'s stated precondition is
    that ``decision_id`` names an already-stored decision, so a conforming adapter
    resolves it against stored authority records and fails closed otherwise. An admission
    must never reach that method — ``admission_id`` is a different id space and, on an
    initial admission, names no record at all."""

    async def authenticate_exact_retry(
        self, authenticated_principal: str, decision_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeDecisionRetryAuthentication:
        raise NarrativeDecisionAuthorizationError(
            f"{decision_id!r} names no stored decision; the decision-retry path cannot serve it"
        )


async def test_the_admission_never_authenticates_through_the_decision_retry_path(
    session_factory: Factory,
) -> None:
    service = NarrativeAcceptanceService(narrative_lifecycle_uow_factory(session_factory), _NoRetryPathAuthorityPort())
    await _seed_admissible_handoff(service, session_factory)
    admitted = await service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    assert admitted.admission_id == "adm-1"
    assert admitted.admission.actor_id == SHOWRUNNER
    # The exact retry goes through the same capability method, not the decision one.
    again = await service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    assert again.admission == admitted.admission


async def test_an_admission_id_colliding_with_a_decision_id_is_not_resolved_as_that_decision(
    session_factory: Factory,
) -> None:
    """``admission_id`` and ``decision_id`` are separate id spaces with independent primary
    keys, so nothing stops a caller choosing an admission id that also names a real
    decision. The capability check must not resolve it as one."""
    service = NarrativeAcceptanceService(narrative_lifecycle_uow_factory(session_factory), _NoRetryPathAuthorityPort())
    await _seed_admissible_handoff(service, session_factory)
    admitted = await service.admit_canon_handoff(
        _handoff_command(admission_id="d-1"),  # also the revision-acceptance decision id
        authenticated_principal=SHOWRUNNER,
        canon_commit_approval=_approval(),
    )
    assert admitted.admission_id == "d-1"
    assert admitted.admission.revision_acceptance_decision_id == "d-1"
    assert admitted.admission.actor_id == SHOWRUNNER
