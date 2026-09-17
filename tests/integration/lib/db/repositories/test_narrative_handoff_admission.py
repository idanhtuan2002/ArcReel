"""Integration coverage for the M5C-4 handoff-admission repository method (Task 27):
append-only identity-conflict semantics and lossless round-trip of the embedded M5A
``CanonCommitApproval`` payload. Mirrors ``test_compilation_repository.py``'s shape
(Task 22) one checkpoint up the M5A handoff chain.

The repository never itself resolves an exact retry into the original receipt — any
``admission_id`` reuse, identical tuple or not, fails closed here with
``NarrativeDecisionIdentityConflictError``. Resolving an exact retry before ever calling
this method is the service layer's job (Task 28), not this repository's.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork, narrative_lifecycle_uow_factory
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.errors import NarrativeDecisionIdentityConflictError
from r2.narrative_lifecycle.hashing import compute_canon_approval_binding_fingerprint
from tests.factories import (
    make_canon_commit_approval,
    make_change_set_review_command,
    make_compilation_attempt,
    make_compilation_result,
    make_compiled_canon_delta_evidence,
    make_draft_candidate,
    make_extraction_attempt,
    make_extraction_result,
    make_narrative_change_set,
    make_narrative_handoff_admission,
    make_narrative_revision,
    make_revision_acceptance_command,
)
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER, FakeShowrunnerAuthorityPort

type Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
def acceptance_service(session_factory: Factory) -> NarrativeAcceptanceService:
    return NarrativeAcceptanceService(narrative_lifecycle_uow_factory(session_factory), FakeShowrunnerAuthorityPort())


@pytest.fixture
async def seeded_admission_inputs(session_factory: Factory, acceptance_service: NarrativeAcceptanceService) -> None:
    """Seeds exactly the object graph ``make_narrative_handoff_admission``'s defaults
    name: an accepted revision (``d-1`` selects ``rev-1``), an accepted change-set review
    (``d-2`` selects ``cs-1`` under ``d-1``), and a SUCCEEDED compilation attempt/result
    (``cattempt-1``/generation 0 -> ``cres-1``)."""
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(make_draft_candidate())
        await uow.repository.insert_revision(make_narrative_revision())
        await uow.repository.insert_extraction_attempt(make_extraction_attempt())
        await uow.repository.insert_successful_extraction(
            make_extraction_result(outcome="SUCCEEDED", change_set_ids=("cs-1",)),
            (make_narrative_change_set(change_set_id="cs-1"),),
        )
        await uow.commit()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", action="ACCEPT"), authenticated_principal=SHOWRUNNER
    )
    await acceptance_service.review_change_set(
        make_change_set_review_command(decision_id="d-2", action="ACCEPT"), authenticated_principal=SHOWRUNNER
    )
    evidence = make_compiled_canon_delta_evidence()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_compilation_attempt(make_compilation_attempt())
        await uow.repository.insert_successful_compilation(
            make_compilation_result(
                outcome="SUCCEEDED",
                canon_delta_id=evidence.canon_delta.canon_delta_id,
                canon_delta_payload_hash=evidence.canon_delta_payload_hash,
            ),
            evidence,
        )
        await uow.commit()


def _admission(**overrides: object):
    approval = overrides.pop(
        "canon_commit_approval",
        make_canon_commit_approval(canon_delta_id="delta-1", payload_hash="sha256:deadbeef"),
    )
    return make_narrative_handoff_admission(canon_commit_approval=approval, **overrides)


async def test_a_handoff_admission_round_trips_exactly(session_factory: Factory, seeded_admission_inputs: None) -> None:
    admission = _admission()
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        await uow.repository.insert_handoff_admission(admission)
        await uow.commit()
    async with SqlAlchemyNarrativeLifecycleUnitOfWork(session_factory) as uow:
        loaded = await uow.repository.get_exact_handoff_admission(
            admission_id=admission.admission_id,
            project_name=admission.work_scope.project_name,
            user_id=admission.work_scope.user_id,
        )
    assert loaded == admission
    assert loaded is not None
    assert loaded.canon_commit_approval == admission.canon_commit_approval
    assert (
        compute_canon_approval_binding_fingerprint(loaded.canon_commit_approval)
        == admission.canon_commit_approval_fingerprint
    )


async def test_handoff_admission_is_readable_by_id_without_a_scope_handle(
    session_factory: Factory, seeded_admission_inputs: None
) -> None:
    admission = _admission()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_handoff_admission(admission)
        await uow.commit()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        loaded = await uow.repository.get_handoff_admission_by_id(admission_id=admission.admission_id)
    assert loaded == admission


async def test_same_admission_id_with_a_changed_approval_field_is_an_identity_conflict(
    session_factory: Factory, seeded_admission_inputs: None
) -> None:
    admission = _admission()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_handoff_admission(admission)
        await uow.commit()
    mutated_approval = admission.canon_commit_approval.model_copy(update={"approved_by": "someone-else"})
    conflicting = admission.model_copy(
        update={
            "canon_commit_approval": mutated_approval,
            "canon_commit_approval_fingerprint": compute_canon_approval_binding_fingerprint(mutated_approval),
        }
    )
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeDecisionIdentityConflictError):
            await uow.repository.insert_handoff_admission(conflicting)


async def test_duplicate_admission_id_with_the_identical_tuple_still_fails_closed_at_repo_level(
    session_factory: Factory, seeded_admission_inputs: None
) -> None:
    admission = _admission()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_handoff_admission(admission)
        await uow.commit()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeDecisionIdentityConflictError):
            await uow.repository.insert_handoff_admission(admission)


async def test_unknown_or_cross_scope_admission_id_reads_as_none(
    session_factory: Factory, seeded_admission_inputs: None
) -> None:
    admission = _admission()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_handoff_admission(admission)
        await uow.commit()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        assert (
            await uow.repository.get_exact_handoff_admission(
                admission_id="ghost",
                project_name=admission.work_scope.project_name,
                user_id=admission.work_scope.user_id,
            )
        ) is None
        assert (
            await uow.repository.get_exact_handoff_admission(
                admission_id=admission.admission_id, project_name="other-project", user_id=admission.work_scope.user_id
            )
        ) is None
        assert await uow.repository.get_handoff_admission_by_id(admission_id="ghost") is None
