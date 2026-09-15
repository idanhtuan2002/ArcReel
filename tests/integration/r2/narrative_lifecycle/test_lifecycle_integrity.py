"""Integration coverage for ``NarrativeLifecycleIntegrityChecker`` (Task 20, partial —
rebuild only; Task 30 completes it with the read-side currentness wiring).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.contracts.narrative_lifecycle import (
    CompilationSelectedChangeSet,
    DraftCandidate,
    NarrativeRevision,
    NarrativeWorkScope,
    ThreadPayoffEffectKey,
)
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.compiler import COMPILER_POLICY_VERSION, COMPILER_VERSION, CompilerPolicy, ExactCanonBase
from r2.narrative_lifecycle.errors import (
    NarrativeAuthorityIntegrityError,
    NarrativeEvidenceIntegrityError,
    NarrativeEvidenceNotFoundError,
)
from r2.narrative_lifecycle.evidence import CompilationAdmissionCommand
from r2.narrative_lifecycle.hashing import compute_evidence_semantic_fingerprint, compute_prose_content_hash
from r2.narrative_lifecycle.integrity import NarrativeLifecycleIntegrityChecker
from tests.factories import (
    make_change_set_review_command,
    make_draft_candidate,
    make_narrative_change_set,
    make_narrative_revision,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER
from tests.integration.r2.narrative_lifecycle.test_handoff_admission import (
    PROJECT,
    USER,
    _approval,
    _evidence,
    _handoff_command,
    _seed_admissible_handoff,
)
from tests.integration.r2.narrative_lifecycle.test_handoff_admission import _scope as _handoff_scope

type Factory = async_sessionmaker[AsyncSession]


def _scope() -> NarrativeWorkScope:
    return make_narrative_work_scope()


async def _set_fk_triggers(session: AsyncSession, table: str, *, enabled: bool) -> None:
    """Toggle Postgres's referential-integrity triggers on ``table``.

    A few tests below corrupt state a live system's own FKs would never allow (a decision
    vanishing from under a head, a change set deleted while still referenced) specifically
    to prove the integrity checker catches it independently of the DB. SQLite already runs
    these suites with ``foreign_keys=OFF`` (see ``tests/conftest.py``); on Postgres the FK
    itself would block the corrupting statement before the checker ever saw it, so it must
    be suspended around that one statement — a no-op on SQLite.
    """
    if session.get_bind().dialect.name != "postgresql":
        return
    state = "ENABLE" if enabled else "DISABLE"
    await session.execute(text(f'ALTER TABLE "{table}" {state} TRIGGER ALL'))


@pytest.fixture
def integrity_checker(session_factory: Factory) -> NarrativeLifecycleIntegrityChecker:
    return NarrativeLifecycleIntegrityChecker(narrative_lifecycle_uow_factory(session_factory))


def _real_candidate(**overrides: object) -> DraftCandidate:
    draft = make_draft_candidate(semantic_fingerprint="pending", **overrides)
    content_hash = compute_prose_content_hash(draft.normalized_content)
    draft = draft.model_copy(update={"content_hash": content_hash})
    return draft.model_copy(update={"semantic_fingerprint": compute_evidence_semantic_fingerprint(draft)})


def _real_revision(**overrides: object) -> NarrativeRevision:
    revision = make_narrative_revision(semantic_fingerprint="pending", **overrides)
    content_hash = compute_prose_content_hash(revision.normalized_content)
    revision = revision.model_copy(update={"content_hash": content_hash})
    return revision.model_copy(update={"semantic_fingerprint": compute_evidence_semantic_fingerprint(revision)})


async def test_rebuild_matches_the_stored_head_after_accept_supersede_reject(
    acceptance_service: NarrativeAcceptanceService, integrity_checker: NarrativeLifecycleIntegrityChecker
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-3",
            work_scope=scope,
            action="REJECT",
            selected_revision_id="rev-3",
            expected_latest_decision_id="d-2",
            expected_effective_decision_id="d-2",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    verified = await integrity_checker.verify_revision_head(scope)
    assert verified.latest_decision_id == "d-3"
    assert verified.decision_generation == 3
    assert verified.effective_decision_id == "d-2"
    assert verified.effective_generation == 2

    stored = await acceptance_service.get_current_revision_selection(scope)
    assert stored == verified


async def test_reject_does_not_advance_effective_generation_on_rebuild(
    acceptance_service: NarrativeAcceptanceService, integrity_checker: NarrativeLifecycleIntegrityChecker
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="REJECT",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    rebuilt = await integrity_checker.rebuild_revision_head(scope)
    assert rebuilt.effective_generation == 1
    assert rebuilt.decision_generation == 2
    assert rebuilt.effective_decision_id == "d-1"
    assert rebuilt.latest_decision_id == "d-2"


async def test_rebuild_on_an_untouched_scope_is_the_null_head(
    integrity_checker: NarrativeLifecycleIntegrityChecker,
) -> None:
    rebuilt = await integrity_checker.rebuild_revision_head(_scope())
    assert rebuilt.latest_decision_id is None
    assert rebuilt.decision_generation == 0
    assert rebuilt.effective_decision_id is None
    assert rebuilt.effective_generation == 0
    # verify_revision_head must not treat "nothing ever happened" as corruption
    verified = await integrity_checker.verify_revision_head(_scope())
    assert verified == rebuilt


async def test_verify_revision_head_raises_when_the_stored_head_disagrees(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )

    # Corrupt the mutable head directly -- the authoritative decision chain still says
    # decision_generation=1, but the stored projection now (wrongly) claims 2.
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE revision_acceptance_heads SET decision_generation = 2 "
                "WHERE user_id = :user_id AND project_name = :project_name"
            ),
            {"user_id": scope.user_id, "project_name": scope.project_name},
        )
        await session.commit()

    with pytest.raises(NarrativeAuthorityIntegrityError):
        await integrity_checker.verify_revision_head(scope)


async def test_change_set_review_and_conflict_resolution_heads_also_rebuild(
    acceptance_service: NarrativeAcceptanceService, integrity_checker: NarrativeLifecycleIntegrityChecker
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(decision_id="d-2", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )

    verified = await integrity_checker.verify_change_set_review_head(
        revision_acceptance_decision_id="d-1",
        change_set_lineage_id="lin-cs-1",
        user_id=scope.user_id,
        project_name=scope.project_name,
    )
    assert verified.latest_decision_id == "d-2"
    assert verified.effective_decision_id == "d-2"

    empty_conflict = await integrity_checker.rebuild_conflict_resolution_head(
        revision_acceptance_decision_id="d-1", conflict_resolution_lineage_id="lin-ghost"
    )
    assert empty_conflict.latest_decision_id is None


# --- Task 30: decision-chain walks (acyclic / scope-consistent / predecessor-consistent) --


async def test_verify_revision_decision_chain_matches_the_plain_rebuild(
    acceptance_service: NarrativeAcceptanceService, integrity_checker: NarrativeLifecycleIntegrityChecker
) -> None:
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=scope,
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    verified = await integrity_checker.verify_revision_decision_chain(scope)
    assert verified.latest_decision_id == "d-2"
    assert verified.effective_decision_id == "d-2"
    assert verified.effective_generation == 2


# --- Task 30: historical conflict-resolution validity -------------------------------------


async def _seed_two_reviewed_change_sets(
    acceptance_service: NarrativeAcceptanceService, session_factory: Factory, *, scope: NarrativeWorkScope
) -> None:
    from tests.factories import make_extraction_attempt, make_extraction_result

    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_real_candidate(work_scope=scope))
        await uow.repository.insert_revision(_real_revision(work_scope=scope))
        await uow.repository.insert_extraction_attempt(make_extraction_attempt(work_scope=scope, revision_id="rev-1"))
        await uow.repository.insert_successful_extraction(
            make_extraction_result(
                attempt_id="att-1", generation=0, outcome="SUCCEEDED", change_set_ids=("cs-a", "cs-b")
            ),
            [
                make_narrative_change_set(change_set_id="cs-a", change_set_lineage_id="lin-a"),
                make_narrative_change_set(change_set_id="cs-b", change_set_lineage_id="lin-b"),
            ],
        )
        await uow.commit()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-a",
            selected_change_set_id="cs-a",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-3",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-b",
            selected_change_set_id="cs-b",
        ),
        authenticated_principal=SHOWRUNNER,
    )


async def test_verify_conflict_resolution_historical_validity_passes_for_an_intact_chain(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    scope = _scope()
    await _seed_two_reviewed_change_sets(acceptance_service, session_factory, scope=scope)
    await acceptance_service.resolve_change_set_conflict(
        make_conflict_resolution_command_for(scope),
        authenticated_principal=SHOWRUNNER,
    )
    result = await integrity_checker.verify_conflict_resolution_historical_validity(
        "res-1", user_id=scope.user_id, project_name=scope.project_name
    )
    assert result is None  # nothing to report -- the historical chain is intact


async def test_verify_conflict_resolution_historical_validity_raises_when_a_named_change_set_vanishes(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    scope = _scope()
    await _seed_two_reviewed_change_sets(acceptance_service, session_factory, scope=scope)
    await acceptance_service.resolve_change_set_conflict(
        make_conflict_resolution_command_for(scope),
        authenticated_principal=SHOWRUNNER,
    )
    async with session_factory() as session:
        await session.execute(text("DELETE FROM narrative_extraction_result_change_sets WHERE change_set_id = 'cs-a'"))
        await _set_fk_triggers(session, "narrative_change_sets", enabled=False)
        await session.execute(text("DELETE FROM narrative_change_sets WHERE change_set_id = 'cs-a'"))
        await _set_fk_triggers(session, "narrative_change_sets", enabled=True)
        await session.commit()

    with pytest.raises(NarrativeEvidenceIntegrityError):
        await integrity_checker.verify_conflict_resolution_historical_validity(
            "res-1", user_id=scope.user_id, project_name=scope.project_name
        )


def make_conflict_resolution_command_for(scope: NarrativeWorkScope):
    from tests.factories import make_conflict_resolution_command

    return make_conflict_resolution_command(
        decision_id="res-1",
        work_scope=scope,
        action="RESOLVE",
        conflict_resolution_lineage_id="lin-conflict",
        competing_change_set_ids=("cs-a", "cs-b"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution="r2-m5c-conflict-resolution-instruction-v1:KEEP:cs-a",
    )


# --- Task 30: head-pointer referential integrity -------------------------------------------


async def test_verify_revision_head_references_raises_when_the_head_points_to_a_deleted_decision(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    scope = _scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_real_candidate(work_scope=scope))
        await uow.repository.insert_revision(_real_revision(work_scope=scope))
        await uow.commit()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await integrity_checker.verify_revision_head_references(scope)  # intact: no raise

    async with session_factory() as session:
        await _set_fk_triggers(session, "revision_acceptance_heads", enabled=False)
        await session.execute(
            text(
                "UPDATE revision_acceptance_heads SET latest_decision_id = 'ghost-decision', "
                "effective_decision_id = 'ghost-decision' "
                "WHERE user_id = :user_id AND project_name = :project_name"
            ),
            {"user_id": scope.user_id, "project_name": scope.project_name},
        )
        await _set_fk_triggers(session, "revision_acceptance_heads", enabled=True)
        await session.commit()

    with pytest.raises(NarrativeAuthorityIntegrityError):
        await integrity_checker.verify_revision_head_references(scope)


# --- Task 30: evidence content-hash / fingerprint recomputation ----------------------------


async def test_verify_draft_candidate_evidence_passes_for_a_real_hash_and_fails_on_tamper(
    integrity_checker: NarrativeLifecycleIntegrityChecker, session_factory: Factory
) -> None:
    scope = _scope()
    candidate = _real_candidate(work_scope=scope)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(candidate)
        await uow.commit()

    verified = await integrity_checker.verify_draft_candidate_evidence(
        candidate_id=candidate.candidate_id, user_id=scope.user_id, project_name=scope.project_name
    )
    assert verified.candidate_id == candidate.candidate_id

    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE narrative_draft_candidates SET normalized_content = 'tampered prose' WHERE candidate_id = :id"
            ),
            {"id": candidate.candidate_id},
        )
        await session.commit()

    with pytest.raises(NarrativeEvidenceIntegrityError):
        await integrity_checker.verify_draft_candidate_evidence(
            candidate_id=candidate.candidate_id, user_id=scope.user_id, project_name=scope.project_name
        )


async def test_verify_revision_evidence_not_found_for_an_unknown_id(
    integrity_checker: NarrativeLifecycleIntegrityChecker,
) -> None:
    with pytest.raises(NarrativeEvidenceNotFoundError):
        await integrity_checker.verify_revision_evidence(revision_id="ghost", user_id="u1", project_name="p1")


# --- Task 30: compilation result / compiled-delta cardinality ------------------------------


async def test_verify_compilation_result_evidence_passes_for_an_admitted_succeeded_result(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    verified = await integrity_checker.verify_compilation_result_evidence(
        attempt_id="rev-1:0", generation=0, user_id=USER, project_name=PROJECT
    )
    assert verified.attempt_id == "rev-1:0"


async def test_verify_compilation_result_evidence_raises_when_the_compiled_delta_hash_is_tampered(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE narrative_compiled_canon_deltas SET canon_delta_payload_hash = 'sha256:tampered' "
                "WHERE compilation_attempt_id = 'rev-1:0'"
            )
        )
        await session.commit()

    with pytest.raises(NarrativeEvidenceIntegrityError):
        await integrity_checker.verify_compilation_result_evidence(
            attempt_id="rev-1:0", generation=0, user_id=USER, project_name=PROJECT
        )


async def test_verify_compilation_recompute_reproduces_a_no_canon_mutation_outcome(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    """An outcome-only (THREAD_PAYOFF-only) selection needs no policy rule at all --
    the cheapest real end-to-end recompute fixture. Uses ``test_handoff_admission``'s
    fixed ``(USER, PROJECT)`` scope because ``_compilation_command`` hardcodes it."""
    scope = _handoff_scope()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_real_candidate(work_scope=scope))
        await uow.repository.insert_revision(_real_revision(work_scope=scope))
        await uow.repository.insert_extraction_attempt(make_extraction_attempt_for(scope))
        outcome_key = ThreadPayoffEffectKey(thread_ref="thread-1", payoff_ref="payoff-1")
        change_set = make_narrative_change_set(
            change_set_id="cs-outcome",
            change_set_lineage_id="lin-outcome",
            key=outcome_key,
        )
        await uow.repository.insert_successful_extraction(
            make_extraction_result_for(scope, change_set_ids=("cs-outcome",)), [change_set]
        )
        await uow.commit()

    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(
            decision_id="d-2",
            work_scope=scope,
            action="ACCEPT",
            change_set_lineage_id="lin-outcome",
            selected_change_set_id="cs-outcome",
        ),
        authenticated_principal=SHOWRUNNER,
    )

    evidence = _evidence(session_factory)
    from tests.factories import make_compilation_result

    attempt = await evidence.admit_compilation(
        CompilationAdmissionCommand(
            work_scope=scope,
            revision_id="rev-1",
            generation=0,
            revision_acceptance_decision_id="d-1",
            selected_change_sets=(CompilationSelectedChangeSet(change_set_id="cs-outcome", review_decision_id="d-2"),),
            creative_policy_ref="policy-1",
            creative_policy_version=COMPILER_POLICY_VERSION,
            compiler_version=COMPILER_VERSION,
            requested_canon_delta_id="delta-outcome",
            delta_created_at=datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
            delta_created_by=SHOWRUNNER,
            authenticated_principal=SHOWRUNNER,
        )
    )
    await evidence.record_compilation_without_delta(
        make_compilation_result(
            result_id="res-outcome", attempt_id=attempt.attempt_id, generation=0, outcome="NO_CANON_MUTATION"
        )
    )

    exact_canon_base = ExactCanonBase(
        canon_branch_id=scope.canon_branch_id, base_canon_version_id="cv-1", content_schema_version="r2-canon-schema-v1"
    )
    empty_policy = CompilerPolicy(
        policy_ref="policy-1",
        policy_version="r2-m5c-canon-delta-compiler-policy-v1",
        collision_policy="SAME_SUBJECT",
        mutation_rules=(),
        replacement_rules=(),
    )
    recomputed = await integrity_checker.verify_compilation_recompute(
        attempt_id=attempt.attempt_id,
        generation=0,
        user_id=scope.user_id,
        project_name=scope.project_name,
        exact_canon_base=exact_canon_base,
        compiler_policy=empty_policy,
    )
    assert recomputed.outcome == "NO_CANON_MUTATION"


def make_extraction_attempt_for(scope: NarrativeWorkScope):
    from tests.factories import make_extraction_attempt

    return make_extraction_attempt(work_scope=scope, revision_id="rev-1")


def make_extraction_result_for(scope: NarrativeWorkScope, *, change_set_ids: tuple[str, ...]):
    from tests.factories import make_extraction_result

    return make_extraction_result(attempt_id="att-1", generation=0, outcome="SUCCEEDED", change_set_ids=change_set_ids)


# --- Task 30: handoff-admission binding ----------------------------------------------------


async def test_verify_handoff_admission_evidence_passes_for_an_intact_admission(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    admitted = await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    verified = await integrity_checker.verify_handoff_admission_evidence(
        admission_id=admitted.admission_id, user_id=USER, project_name=PROJECT
    )
    assert verified.admission_id == admitted.admission_id


async def test_verify_handoff_admission_evidence_raises_when_the_approval_fingerprint_is_tampered(
    acceptance_service: NarrativeAcceptanceService,
    integrity_checker: NarrativeLifecycleIntegrityChecker,
    session_factory: Factory,
) -> None:
    await _seed_admissible_handoff(acceptance_service, session_factory)
    admitted = await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "UPDATE narrative_handoff_admissions SET canon_commit_approval_fingerprint = 'cab:tampered' "
                "WHERE admission_id = :id"
            ),
            {"id": admitted.admission_id},
        )
        await session.commit()

    with pytest.raises(NarrativeEvidenceIntegrityError):
        await integrity_checker.verify_handoff_admission_evidence(
            admission_id=admitted.admission_id, user_id=USER, project_name=PROJECT
        )
