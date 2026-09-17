"""Integration coverage for ``AcceptedNarrativeAdapter`` (Task 25, spec §8.4): the
concrete exact reader M5C supplies behind M5B's ``AcceptedNarrativeReader`` protocol.

Driven through the real repository/UoW against the same database the acceptance suite
uses (see ``conftest.py``), never a fake authority/repository — the currentness guard
under test is the real ``RevisionAcceptanceHead`` projection.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.contracts.narrative_context import ContextDescriptorBasis, compute_source_content_hash
from r2.contracts.narrative_lifecycle import NarrativeWorkScope
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.accepted_narrative_adapter import AcceptedNarrativeAdapter
from tests.factories import make_narrative_work_scope, make_revision_acceptance_command
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER
from tests.integration.r2.narrative_lifecycle.test_evidence_service import _candidate, _revision

USER = "u1"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def _scope(*, user_id: str = USER, project_name: str = PROJECT) -> NarrativeWorkScope:
    return make_narrative_work_scope(user_id=user_id, project_name=project_name)


@pytest.fixture
def adapter(session_factory: Factory) -> AcceptedNarrativeAdapter:
    return AcceptedNarrativeAdapter(narrative_lifecycle_uow_factory(session_factory))


async def _seed_revision(session_factory: Factory, *, revision_id: str, scope: NarrativeWorkScope) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate(candidate_id=f"cand-{revision_id}", scope=scope))
        await uow.repository.insert_revision(
            _revision(revision_id=revision_id, candidate_id=f"cand-{revision_id}", scope=scope)
        )
        await uow.commit()


async def test_get_exact_returns_the_accepted_revision_prose_and_authority_descriptor(
    session_factory: Factory, adapter: AcceptedNarrativeAdapter, acceptance_service: NarrativeAcceptanceService
) -> None:
    scope = _scope()
    await _seed_revision(session_factory, revision_id="rev-1", scope=scope)
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="dec-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )

    record = await adapter.get_exact(accepted_narrative_ref="dec-1", project_name=PROJECT, user_id=USER)

    assert record is not None
    assert record.accepted_narrative_ref == "dec-1"
    seeded = _revision(revision_id="rev-1", candidate_id="cand-rev-1", scope=scope)
    assert record.content == seeded.normalized_content
    descriptor = record.descriptor
    assert descriptor.authority_class == "ACCEPTED_NARRATIVE"
    assert descriptor.visibility_policy == "AUTHOR_ONLY"
    assert descriptor.user_id == USER
    assert descriptor.project_name == PROJECT
    # Trap check: content_hash must be recomputed via compute_source_content_hash, not
    # copied verbatim from NarrativeRevision.content_hash — the two hash domains share a
    # normalization but use different prefixes ("nsc:" vs "pch:"), and M5B's compiler
    # recomputes compute_source_content_hash(prose) to compare byte-for-byte.
    assert descriptor.content_hash == compute_source_content_hash(seeded.normalized_content)
    assert descriptor.content_hash != seeded.content_hash
    assert descriptor.canon_basis == ContextDescriptorBasis(
        branch_id=scope.canon_branch_id, canon_version_id=seeded.base_canon_version_id
    )
    assert descriptor.plan_basis == ContextDescriptorBasis(plan_id=scope.plan_id, plan_version=seeded.plan_version)


async def test_adapter_returns_not_found_for_a_superseded_acceptance(
    session_factory: Factory, adapter: AcceptedNarrativeAdapter, acceptance_service: NarrativeAcceptanceService
) -> None:
    scope = _scope()
    await _seed_revision(session_factory, revision_id="rev-1", scope=scope)
    d1 = await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="d-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )
    await _seed_revision(session_factory, revision_id="rev-2", scope=scope)
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

    assert await adapter.get_exact(accepted_narrative_ref=d1.decision_id, project_name=PROJECT, user_id=USER) is None


async def test_adapter_returns_not_found_for_an_unresolved_reference(
    adapter: AcceptedNarrativeAdapter,
) -> None:
    assert (
        await adapter.get_exact(accepted_narrative_ref="d-does-not-exist", project_name=PROJECT, user_id=USER) is None
    )


@pytest.mark.parametrize("bogus_ref", ["pch:0123456789abcdef", "rev-1", "revheads:branch-1/plan-1/scene-1"])
async def test_adapter_rejects_a_prose_hash_or_head_id_reference(
    adapter: AcceptedNarrativeAdapter, bogus_ref: str
) -> None:
    """``accepted_narrative_ref`` is a revision-acceptance decision ID, never a revision
    ID, prose hash, or mutable head ID; none of those resolve through the decision
    registry, so they collapse to the same not-found result as any other bad reference."""
    assert await adapter.get_exact(accepted_narrative_ref=bogus_ref, project_name=PROJECT, user_id=USER) is None


async def test_adapter_returns_not_found_for_a_cross_scope_reference(
    session_factory: Factory, adapter: AcceptedNarrativeAdapter, acceptance_service: NarrativeAcceptanceService
) -> None:
    scope = _scope()
    await _seed_revision(session_factory, revision_id="rev-1", scope=scope)
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(decision_id="dec-1", work_scope=scope, action="ACCEPT"),
        authenticated_principal=SHOWRUNNER,
    )

    other_project = await adapter.get_exact(
        accepted_narrative_ref="dec-1", project_name="another-project", user_id=USER
    )
    other_user = await adapter.get_exact(accepted_narrative_ref="dec-1", project_name=PROJECT, user_id="another-user")

    assert other_project is None
    assert other_user is None


async def test_adapter_returns_not_found_when_the_accepted_revision_never_resolves(
    adapter: AcceptedNarrativeAdapter, acceptance_service: NarrativeAcceptanceService
) -> None:
    """A dangling/corrupt reference: the decision resolves and is currently effective,
    but the revision it names was never recorded as evidence."""
    scope = _scope()
    await acceptance_service.decide_revision(
        make_revision_acceptance_command(
            decision_id="dec-1", work_scope=scope, action="ACCEPT", selected_revision_id="rev-ghost"
        ),
        authenticated_principal=SHOWRUNNER,
    )

    assert await adapter.get_exact(accepted_narrative_ref="dec-1", project_name=PROJECT, user_id=USER) is None
