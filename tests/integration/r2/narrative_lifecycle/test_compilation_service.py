"""Integration coverage for compilation admission and atomic compiled-delta recording
(Task 24, spec §10.1 currentness/overlap/basis rules and §5.5 contract shapes).

Mirrors ``test_evidence_service.py``'s extraction-admission coverage at compilation's
higher fan-out (three decision families instead of one) and reuses its attempt/candidate/
revision/result seeding helpers rather than redefining them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork, narrative_lifecycle_uow_factory
from r2.contracts.narrative import AddFactOperation, CanonDelta, CanonDeltaPayload, Fact
from r2.contracts.narrative_lifecycle import CompilationAttempt, CompilationSelectedChangeSet, NarrativeWorkScope
from r2.narrative.hashing import seal_canon_delta
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeConflictCoverageError,
    NarrativeDecisionApplicabilityError,
    NarrativeEvidenceIntegrityError,
)
from r2.narrative_lifecycle.evidence import CompilationAdmissionCommand, NarrativeLifecycleEvidenceService
from tests.factories import (
    NARRATIVE_LIFECYCLE_NOW,
    make_change_set_review_command,
    make_compilation_attempt,
    make_compilation_result,
    make_conflict_resolution_command,
    make_narrative_change_set,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER
from tests.integration.r2.narrative_lifecycle.test_evidence_service import _attempt, _candidate, _result, _revision

USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def _scope() -> NarrativeWorkScope:
    return make_narrative_work_scope(user_id=USER, project_name=PROJECT)


@pytest.fixture
def evidence_service(session_factory: Factory) -> NarrativeLifecycleEvidenceService:
    return NarrativeLifecycleEvidenceService(narrative_lifecycle_uow_factory(session_factory))


class InjectedFault(RuntimeError):
    pass


class _FaultOnCommitUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    """Flushes normally, then fails the commit — the transaction never reaches the DB."""

    async def commit(self) -> None:
        raise InjectedFault("injected fault before commit")


@pytest.fixture
def fault_on_commit_service(session_factory: Factory) -> NarrativeLifecycleEvidenceService:
    return NarrativeLifecycleEvidenceService(lambda: _FaultOnCommitUnitOfWork(session_factory))


def _canon_delta(**overrides: object) -> CanonDelta:
    defaults: dict[str, object] = {
        "canon_delta_id": "delta-1",
        "target_branch_id": "branch-1",
        "base_canon_version_id": "cv-1",
        "operations": [
            AddFactOperation(
                operation_id="op-1",
                target_id="fact-1",
                fact=Fact(
                    fact_id="fact-1",
                    subject_ref="hero",
                    predicate="mood",
                    value="calm",
                    effective_from=NARRATIVE_LIFECYCLE_NOW,
                ),
            )
        ],
        "source_change_set_refs": ["cs-1"],
        "author_decision_refs": ["d-1"],
        "validation_report_refs": [],
        "created_at": NARRATIVE_LIFECYCLE_NOW,
        "created_by": SHOWRUNNER,
    }
    defaults.update(overrides)
    return seal_canon_delta(CanonDeltaPayload(**defaults))


def _compilation_command(
    *,
    generation: int = 0,
    revision_id: str = "rev-1",
    revision_acceptance_decision_id: str = "d-1",
    selected: tuple[tuple[str, str], ...] = (("cs-1", "d-2"),),
    conflict_resolution_decision_ids: tuple[str, ...] = (),
) -> CompilationAdmissionCommand:
    return CompilationAdmissionCommand(
        work_scope=_scope(),
        revision_id=revision_id,
        generation=generation,
        revision_acceptance_decision_id=revision_acceptance_decision_id,
        selected_change_sets=tuple(
            CompilationSelectedChangeSet(change_set_id=cs, review_decision_id=rd) for cs, rd in selected
        ),
        conflict_resolution_decision_ids=conflict_resolution_decision_ids,
        creative_policy_ref="policy-1",
        creative_policy_version="1",
        compiler_version="compiler-1",
        requested_canon_delta_id="delta-1",
        delta_created_at=NARRATIVE_LIFECYCLE_NOW,
        delta_created_by=SHOWRUNNER,
        authenticated_principal=SHOWRUNNER,
    )


async def _set_fk_triggers(session: AsyncSession, table: str, *, enabled: bool) -> None:
    """Toggle Postgres's referential-integrity triggers on ``table``.

    ``test_compilation_admission_fails_when_a_selected_change_set_basis_mismatches`` needs
    to seed a change set whose ``base_canon_version_id`` disagrees with its own
    ``source_revision_id``'s revision — the exact state
    ``fk_narrative_change_sets_revision_basis`` exists to forbid, so that the service's own
    mutual-basis check (not the DB) is what's under test. SQLite already runs these suites
    with ``foreign_keys=OFF`` (see ``tests/conftest.py``); this is a no-op there.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    state = "ENABLE" if enabled else "DISABLE"
    await session.execute(text(f'ALTER TABLE "{table}" {state} TRIGGER ALL'))


async def _seed_one_reviewed_change_set(
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
    *,
    change_set_overrides: dict | None = None,
) -> None:
    """d-1 accepts rev-1; cs-1 is extracted from it; d-2 accepts cs-1 under lin-cs-1 —
    the minimal precondition for a single-change-set compilation admission."""
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt())
        if change_set_overrides:
            # Only the deliberate-mismatch caller needs the FK suspended (see
            # _set_fk_triggers) — every other caller's change set genuinely satisfies
            # fk_narrative_change_sets_revision_basis and should stay covered by it.
            await _set_fk_triggers(uow.repository.session, "narrative_change_sets", enabled=False)
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-1",)),
            [make_narrative_change_set(change_set_id="cs-1", **(change_set_overrides or {}))],
        )
        if change_set_overrides:
            await _set_fk_triggers(uow.repository.session, "narrative_change_sets", enabled=True)
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


async def _seed_two_overlapping_reviewed_change_sets(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory
) -> None:
    """d-1 accepts rev-1; cs-a / cs-b (same default span+effect key, so they overlap
    under ``SAME_SUBJECT``) are extracted from it; d-2 / d-3 each accept one, under their
    own lineage — the precondition for the overlap-admission tests."""
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt())
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-a", "cs-b")),
            [
                make_narrative_change_set(change_set_id="cs-a"),
                make_narrative_change_set(change_set_id="cs-b"),
            ],
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
            change_set_lineage_id="lin-cs-a",
            selected_change_set_id="cs-a",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-3",
            work_scope=_scope(),
            action="ACCEPT",
            change_set_lineage_id="lin-cs-b",
            selected_change_set_id="cs-b",
        ),
        authenticated_principal=SHOWRUNNER,
    )


@pytest.fixture
def seed_compilation_attempt(
    session_factory: Factory, acceptance_service: NarrativeAcceptanceService
) -> Callable[..., Awaitable[CompilationAttempt]]:
    """Seeds a ``CompilationAttempt`` row alongside the revision-acceptance and
    change-set-review decisions its default fields (``revision_acceptance_decision_id``,
    ``selected_change_sets``, ``observed_effective_heads``) actually reference — Postgres
    enforces those as real FKs (``fk_narrative_compilation_attempts_revision_acceptance``
    and friends), unlike SQLite's ``foreign_keys=OFF``."""

    async def _seed(*, generation: int = 0) -> CompilationAttempt:
        attempt = make_compilation_attempt(generation=generation, work_scope=_scope())
        await _seed_one_reviewed_change_set(acceptance_service, session_factory)
        async with narrative_lifecycle_uow_factory(session_factory)() as uow:
            await uow.repository.insert_compilation_attempt(attempt)
            await uow.commit()
        return attempt

    return _seed


# --- admission: currentness, matching, applicability, overlap, basis -----------------


async def test_admit_compilation_is_live_after_this_task(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_one_reviewed_change_set(acceptance_service, session_factory)
    attempt = await evidence_service.admit_compilation(_compilation_command())
    assert attempt.attempt_id == "rev-1:0"
    assert attempt.generation == 0
    assert attempt.base_canon_version_id == "cv-1"
    assert len(attempt.observed_effective_heads) == 2  # revision head + the one review head
    assert {head.decision_id for head in attempt.observed_effective_heads} == {"d-1", "d-2"}


async def test_admit_compilation_exact_retry_returns_the_original_attempt(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_one_reviewed_change_set(acceptance_service, session_factory)
    first = await evidence_service.admit_compilation(_compilation_command())
    again = await evidence_service.admit_compilation(_compilation_command())
    assert again == first


async def test_compilation_admission_fails_when_the_revision_acceptance_is_superseded(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_one_reviewed_change_set(acceptance_service, session_factory)
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
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await evidence_service.admit_compilation(_compilation_command())


async def test_compilation_admission_fails_when_a_named_review_is_superseded(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_one_reviewed_change_set(acceptance_service, session_factory)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_extraction_attempt(_attempt(attempt_id="att-2"))
        await uow.repository.insert_successful_extraction(
            _result(result_id="res-2", outcome="SUCCEEDED", change_set_ids=("cs-1b",), attempt_id="att-2"),
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
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await evidence_service.admit_compilation(_compilation_command(selected=(("cs-1", "d-2"),)))


async def test_compilation_admission_fails_when_the_review_does_not_select_the_named_change_set(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_one_reviewed_change_set(acceptance_service, session_factory)
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await evidence_service.admit_compilation(_compilation_command(selected=(("cs-other", "d-2"),)))


async def test_compilation_admission_fails_when_a_selected_change_set_basis_mismatches(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_one_reviewed_change_set(
        acceptance_service, session_factory, change_set_overrides={"base_canon_version_id": "cv-other"}
    )
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await evidence_service.admit_compilation(_compilation_command())


async def test_compilation_admission_fails_on_an_unresolved_overlap(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_two_overlapping_reviewed_change_sets(acceptance_service, session_factory)
    with pytest.raises(NarrativeConflictCoverageError):
        await evidence_service.admit_compilation(_compilation_command(selected=(("cs-a", "d-2"), ("cs-b", "d-3"))))


async def test_compilation_admission_succeeds_once_the_overlap_is_resolved(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_two_overlapping_reviewed_change_sets(acceptance_service, session_factory)
    await acceptance_service.resolve_change_set_conflict(
        make_conflict_resolution_command(
            decision_id="d-4",
            work_scope=_scope(),
            revision_acceptance_decision_id="d-1",
            conflict_resolution_lineage_id="lin-conflict-1",
            competing_change_set_ids=("cs-a", "cs-b"),
            competing_review_decision_ids=("d-2", "d-3"),
            chosen_resolution="keep cs-a",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    attempt = await evidence_service.admit_compilation(
        _compilation_command(selected=(("cs-a", "d-2"), ("cs-b", "d-3")), conflict_resolution_decision_ids=("d-4",))
    )
    assert {head.decision_id for head in attempt.observed_effective_heads} == {"d-1", "d-2", "d-3", "d-4"}


async def test_compilation_admission_fails_when_the_named_resolution_is_superseded(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    await _seed_two_overlapping_reviewed_change_sets(acceptance_service, session_factory)
    await acceptance_service.resolve_change_set_conflict(
        make_conflict_resolution_command(
            decision_id="d-4",
            work_scope=_scope(),
            revision_acceptance_decision_id="d-1",
            conflict_resolution_lineage_id="lin-conflict-1",
            competing_change_set_ids=("cs-a", "cs-b"),
            competing_review_decision_ids=("d-2", "d-3"),
            chosen_resolution="keep cs-a",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.resolve_change_set_conflict(
        make_conflict_resolution_command(
            decision_id="d-5",
            work_scope=_scope(),
            action="SUPERSEDE",
            revision_acceptance_decision_id="d-1",
            conflict_resolution_lineage_id="lin-conflict-1",
            competing_change_set_ids=("cs-a", "cs-b"),
            competing_review_decision_ids=("d-2", "d-3"),
            chosen_resolution="keep cs-b",
            expected_latest_decision_id="d-4",
            expected_effective_decision_id="d-4",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await evidence_service.admit_compilation(
            _compilation_command(selected=(("cs-a", "d-2"), ("cs-b", "d-3")), conflict_resolution_decision_ids=("d-4",))
        )


# --- atomic recording: SUCCEEDED bundle and outcome-only results ---------------------


async def test_successful_compilation_bundle_is_atomic_when_the_commit_faults(
    evidence_service: NarrativeLifecycleEvidenceService,
    fault_on_commit_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    delta = _canon_delta()
    result = make_compilation_result(
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        outcome="SUCCEEDED",
        canon_delta_id=delta.canon_delta_id,
        canon_delta_payload_hash=delta.payload_hash,
    )
    with pytest.raises(InjectedFault):
        await fault_on_commit_service.record_successful_compilation(result, delta)
    assert (
        await evidence_service.get_exact_compilation_result(
            attempt_id=attempt.attempt_id, generation=attempt.generation, project_name=PROJECT, user_id=USER
        )
    ) is None
    assert (
        await evidence_service.get_exact_compiled_delta(
            compilation_result_id=result.result_id, project_name=PROJECT, user_id=USER
        )
    ) is None

    # Reloading after a successful call returns the exact stored payload, not a
    # recomputed one.
    recorded = await evidence_service.record_successful_compilation(result, delta)
    assert recorded == result
    reloaded = await evidence_service.get_exact_compiled_delta(
        compilation_result_id=result.result_id, project_name=PROJECT, user_id=USER
    )
    assert reloaded is not None
    assert reloaded.canon_delta == delta


async def test_successful_compilation_bundle_exact_retry_writes_nothing_new(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    delta = _canon_delta()
    result = make_compilation_result(
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        outcome="SUCCEEDED",
        canon_delta_id=delta.canon_delta_id,
        canon_delta_payload_hash=delta.payload_hash,
    )
    first = await evidence_service.record_successful_compilation(result, delta)
    again = await evidence_service.record_successful_compilation(result, delta)
    assert again == first


async def test_mismatched_successful_compilation_retry_fails_with_no_write(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    delta = _canon_delta()
    result = make_compilation_result(
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        outcome="SUCCEEDED",
        canon_delta_id=delta.canon_delta_id,
        canon_delta_payload_hash=delta.payload_hash,
    )
    await evidence_service.record_successful_compilation(result, delta)
    other_delta = _canon_delta(canon_delta_id="delta-2", source_change_set_refs=["cs-2"])
    other_result = make_compilation_result(
        result_id="cres-9",
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        outcome="SUCCEEDED",
        canon_delta_id=other_delta.canon_delta_id,
        canon_delta_payload_hash=other_delta.payload_hash,
    )
    with pytest.raises(NarrativeAttemptGenerationConflict):
        await evidence_service.record_successful_compilation(other_result, other_delta)
    assert (
        await evidence_service.get_exact_compiled_delta(
            compilation_result_id="cres-9", project_name=PROJECT, user_id=USER
        )
    ) is None


async def test_record_successful_compilation_rejects_a_payload_hash_mismatch(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    delta = _canon_delta()
    result = make_compilation_result(
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        outcome="SUCCEEDED",
        canon_delta_id=delta.canon_delta_id,
        canon_delta_payload_hash="wrong-hash",
    )
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await evidence_service.record_successful_compilation(result, delta)
    assert (
        await evidence_service.get_exact_compilation_result(
            attempt_id=attempt.attempt_id, generation=attempt.generation, project_name=PROJECT, user_id=USER
        )
    ) is None


async def test_record_successful_compilation_rejects_a_non_succeeded_result(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    delta = _canon_delta()
    result = make_compilation_result(attempt_id=attempt.attempt_id, generation=attempt.generation, outcome="ABSTAINED")
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await evidence_service.record_successful_compilation(result, delta)


async def test_record_compilation_without_delta_rejects_a_succeeded_outcome(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    delta = _canon_delta()
    result = make_compilation_result(
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        outcome="SUCCEEDED",
        canon_delta_id=delta.canon_delta_id,
        canon_delta_payload_hash=delta.payload_hash,
    )
    with pytest.raises(NarrativeEvidenceIntegrityError):
        await evidence_service.record_compilation_without_delta(result)


@pytest.mark.parametrize("outcome", ["NO_CANON_MUTATION", "ABSTAINED", "CONFLICT", "FAILED"])
async def test_record_compilation_without_delta_accepts_every_non_succeeded_outcome(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
    outcome: str,
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    result = make_compilation_result(attempt_id=attempt.attempt_id, generation=attempt.generation, outcome=outcome)
    recorded = await evidence_service.record_compilation_without_delta(result)
    assert recorded == result


async def test_record_compilation_without_delta_exact_retry_returns_the_original(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    result = make_compilation_result(attempt_id=attempt.attempt_id, generation=attempt.generation, outcome="ABSTAINED")
    await evidence_service.record_compilation_without_delta(result)
    again = await evidence_service.record_compilation_without_delta(result)
    assert again == result


async def test_mismatched_compilation_without_delta_retry_fails_with_no_write(
    evidence_service: NarrativeLifecycleEvidenceService,
    seed_compilation_attempt: Callable[..., Awaitable[CompilationAttempt]],
) -> None:
    attempt = await seed_compilation_attempt(generation=0)
    await evidence_service.record_compilation_without_delta(
        make_compilation_result(attempt_id=attempt.attempt_id, generation=attempt.generation, outcome="ABSTAINED")
    )
    with pytest.raises(NarrativeAttemptGenerationConflict):
        await evidence_service.record_compilation_without_delta(
            make_compilation_result(
                result_id="cres-9", attempt_id=attempt.attempt_id, generation=attempt.generation, outcome="FAILED"
            )
        )


async def test_repeated_admission_and_recording_yields_one_identical_result(
    evidence_service: NarrativeLifecycleEvidenceService,
    acceptance_service: NarrativeAcceptanceService,
    session_factory: Factory,
) -> None:
    """A crash before result recording leaves a durable attempt with no result; the
    same exact generation may be recomputed and recorded idempotently — never as
    ``OUTCOME_UNKNOWN``, which does not exist for compilation."""
    await _seed_one_reviewed_change_set(acceptance_service, session_factory)
    attempt = await evidence_service.admit_compilation(_compilation_command())
    assert (
        await evidence_service.get_exact_compilation_result(
            attempt_id=attempt.attempt_id, generation=attempt.generation, project_name=PROJECT, user_id=USER
        )
    ) is None

    delta = _canon_delta()
    result = make_compilation_result(
        attempt_id=attempt.attempt_id,
        generation=attempt.generation,
        outcome="SUCCEEDED",
        canon_delta_id=delta.canon_delta_id,
        canon_delta_payload_hash=delta.payload_hash,
    )
    first = await evidence_service.record_successful_compilation(result, delta)
    second = await evidence_service.record_successful_compilation(result, delta)
    assert first == second
    reloaded = await evidence_service.get_exact_compiled_delta(
        compilation_result_id=result.result_id, project_name=PROJECT, user_id=USER
    )
    assert reloaded is not None
    assert reloaded.canon_delta == delta
