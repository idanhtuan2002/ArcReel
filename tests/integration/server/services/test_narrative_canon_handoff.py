"""Integration coverage for the authenticated M5A handoff facade (Task 29, spec §11.4).

Seeds Canon genesis directly through ``CanonTransactionService`` and the admissible
Narrative handoff chain through Task 28's own seeding helper
(``tests.integration.r2.narrative_lifecycle.test_handoff_admission``) rather than
redefining either: this file's job is only the reload-and-call-M5A seam, not the
decision/compilation/admission chain those suites already cover.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import canon_authority_uow_factory
from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.contracts import (
    AddEntityOperation,
    CanonBranchType,
    CanonCommitApproval,
    CanonCommitResult,
    CanonDelta,
    CanonDeltaPayload,
    CreateCanonBranch,
    Entity,
    EntityType,
)
from r2.narrative.canon_transaction import CanonTransactionService, new_version_id
from r2.narrative.errors import CanonBaseVersionConflict
from r2.narrative.hashing import seal_canon_delta
from r2.narrative_lifecycle.acceptance import AdmittedNarrativeHandoff, NarrativeAcceptanceService
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError, NarrativeEvidenceNotFoundError
from server.services.narrative_canon_handoff import NarrativeCanonHandoffFacade
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER, FakeShowrunnerAuthorityPort
from tests.integration.r2.narrative_lifecycle.test_handoff_admission import (
    PROJECT,
    USER,
    _approval,
    _handoff_command,
    _seed_admissible_handoff,
)

type Factory = async_sessionmaker[AsyncSession]

NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)


def _branch_command() -> CreateCanonBranch:
    return CreateCanonBranch(
        branch_id="branch-1",
        user_id=USER,
        project_name=PROJECT,
        branch_type=CanonBranchType.MAIN,
        created_at=NOW,
        created_by="showrunner",
    )


def _entity_delta(*, delta_id: str, entity_id: str, base_canon_version_id: str | None) -> CanonDelta:
    return seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id=delta_id,
            target_branch_id="branch-1",
            base_canon_version_id=base_canon_version_id,
            operations=[
                AddEntityOperation(
                    operation_id=f"op-{entity_id}",
                    target_id=entity_id,
                    entity=Entity(
                        entity_id=entity_id,
                        entity_type=EntityType.CHARACTER,
                        canonical_name=entity_id.replace("-", " ").title(),
                        aliases=[],
                    ),
                )
            ],
            source_change_set_refs=[],
            author_decision_refs=["genesis"],
            validation_report_refs=[],
            created_at=NOW,
            created_by="showrunner",
        )
    )


def _approval_for(delta: CanonDelta, *, approval_ref: str) -> CanonCommitApproval:
    return CanonCommitApproval(
        approval_ref=approval_ref,
        canon_delta_id=delta.canon_delta_id,
        payload_hash=delta.payload_hash,
        payload_hash_algorithm=delta.payload_hash_algorithm,
        payload_hash_version=delta.payload_hash_version,
        content_schema_version=delta.content_schema_version,
        project_name=PROJECT,
        user_id=USER,
        approved_by="approver",
        approved_at=NOW,
        status="APPROVED",
    )


def _seeded_then_random_version_ids() -> Callable[[], str]:
    """``cv-1`` for the one Canon genesis this suite's admissible delta names as its
    exact base; every commit after that mints its own id, same as production."""
    seeded = iter(["cv-1"])

    def _next() -> str:
        for value in seeded:
            return value
        return new_version_id()

    return _next


@pytest.fixture
def canon(session_factory: Factory) -> CanonTransactionService:
    return CanonTransactionService(
        canon_authority_uow_factory(session_factory), version_id_factory=_seeded_then_random_version_ids()
    )


@pytest.fixture
def facade(session_factory: Factory, canon: CanonTransactionService) -> NarrativeCanonHandoffFacade:
    return NarrativeCanonHandoffFacade(
        narrative_lifecycle_uow_factory(session_factory), canon, FakeShowrunnerAuthorityPort()
    )


@pytest.fixture
async def admitted_handoff(session_factory: Factory, canon: CanonTransactionService) -> AdmittedNarrativeHandoff:
    """A real admission, produced the only way one can be: through
    ``NarrativeAcceptanceService.admit_canon_handoff``, against a Canon branch whose
    genesis version is exactly the base the admissible delta names."""
    await canon.create_branch(_branch_command())
    genesis = _entity_delta(delta_id="delta-genesis", entity_id="hero", base_canon_version_id=None)
    await canon.commit(
        delta=genesis,
        approval=_approval_for(genesis, approval_ref="approval-genesis"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    acceptance_service = NarrativeAcceptanceService(
        narrative_lifecycle_uow_factory(session_factory), FakeShowrunnerAuthorityPort()
    )
    await _seed_admissible_handoff(acceptance_service, session_factory)
    return await acceptance_service.admit_canon_handoff(
        _handoff_command(), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
    )


async def test_facade_reloads_the_durable_delta_and_approval_after_restart(
    facade: NarrativeCanonHandoffFacade, admitted_handoff: AdmittedNarrativeHandoff
) -> None:
    """A fresh facade call — nothing but the admission id, standing in for a call made
    after a process restart — reloads the exact persisted delta and approval and lands
    them on Canon through the existing M5A commit path."""
    result = await facade.commit_from_admission(
        admission_id=admitted_handoff.admission_id,
        scope=admitted_handoff.admission.work_scope,
        authenticated_principal=SHOWRUNNER,
        now=NOW,
    )
    assert isinstance(result, CanonCommitResult)
    assert result.version.committed_delta_id == admitted_handoff.canon_delta.canon_delta_id
    assert result.accepted_delta.approval == admitted_handoff.canon_commit_approval


async def test_canon_head_movement_after_admission_is_rejected_by_existing_m5a_occ(
    facade: NarrativeCanonHandoffFacade, admitted_handoff: AdmittedNarrativeHandoff, canon: CanonTransactionService
) -> None:
    unrelated = _entity_delta(delta_id="delta-unrelated", entity_id="villain", base_canon_version_id="cv-1")
    await canon.commit(
        delta=unrelated,
        approval=_approval_for(unrelated, approval_ref="approval-unrelated"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )  # advances the branch head away from the admission's exact base
    with pytest.raises(CanonBaseVersionConflict):
        await facade.commit_from_admission(
            admission_id=admitted_handoff.admission_id,
            scope=admitted_handoff.admission.work_scope,
            authenticated_principal=SHOWRUNNER,
            now=NOW,
        )


async def test_a_retry_after_a_lost_response_replays_the_exact_persisted_commit(
    facade: NarrativeCanonHandoffFacade, admitted_handoff: AdmittedNarrativeHandoff
) -> None:
    """A caller that never saw the first response — a dropped reply, or a crash between
    the M5A commit and recording success — retries with the same admission id,
    authenticated principal, and exact scope. M5A's own exact-retry governs the
    outcome: the same version is returned, not a second one."""
    first = await facade.commit_from_admission(
        admission_id=admitted_handoff.admission_id,
        scope=admitted_handoff.admission.work_scope,
        authenticated_principal=SHOWRUNNER,
        now=NOW,
    )
    second = await facade.commit_from_admission(
        admission_id=admitted_handoff.admission_id,
        scope=admitted_handoff.admission.work_scope,
        authenticated_principal=SHOWRUNNER,
        now=NOW,
    )
    assert second == first


async def test_an_unadmitted_id_does_not_resolve(facade: NarrativeCanonHandoffFacade) -> None:
    with pytest.raises(NarrativeEvidenceNotFoundError):
        await facade.commit_from_admission(
            admission_id="adm-never-admitted",
            scope=_handoff_command().work_scope,
            authenticated_principal=SHOWRUNNER,
            now=NOW,
        )


async def test_facade_denies_a_principal_without_showrunner_capability(
    facade: NarrativeCanonHandoffFacade, admitted_handoff: AdmittedNarrativeHandoff
) -> None:
    with pytest.raises(NarrativeDecisionAuthorizationError, match="lacks Human Showrunner capability"):
        await facade.commit_from_admission(
            admission_id=admitted_handoff.admission_id,
            scope=admitted_handoff.admission.work_scope,
            authenticated_principal="human:not-showrunner",
            now=NOW,
        )


async def test_facade_does_not_resolve_an_admission_through_another_scope(
    facade: NarrativeCanonHandoffFacade, admitted_handoff: AdmittedNarrativeHandoff
) -> None:
    wrong_scope = admitted_handoff.admission.work_scope.model_copy(update={"user_id": "another-user"})

    with pytest.raises(NarrativeEvidenceNotFoundError):
        await facade.commit_from_admission(
            admission_id=admitted_handoff.admission_id,
            scope=wrong_scope,
            authenticated_principal=SHOWRUNNER,
            now=NOW,
        )
