"""Scoped capability/query persistence uses the real PostgreSQL unit of work."""

from __future__ import annotations

import importlib
import importlib.util

import pytest
from sqlalchemy import func, select, update

from lib.db.models.opportunity_acquisition import M9SourceQueryModel
from lib.db.repositories.opportunity import OpportunityUnitOfWork
from r2.contracts.opportunity import SourceQuery, SourceQueryHead
from r2.opportunity.digests import digest_source_query
from r2.opportunity.errors import OpportunityError
from tests.integration.lib.db.repositories.test_opportunity_profiles import make_profile
from tests.unit.r2.opportunity.test_capabilities import NOW, _authority

QUERY = "019a0000-0000-7000-8000-000000000031"


def unit_of_work(factory, project="show-a"):
    assert importlib.util.find_spec("lib.db.repositories.opportunity_acquisition") is not None, (
        "B3 typed query repositories are missing"
    )
    module = importlib.import_module("lib.db.repositories.opportunity_acquisition")
    return module.OpportunityAcquisitionUnitOfWork(factory, user_id="u1", project_name=project)


async def fixture_query(factory):
    profile = make_profile()
    async with OpportunityUnitOfWork(factory).transaction() as repo:
        await repo.stage_profile(profile)
    grant, evaluation, request = _authority()
    query = SourceQuery.model_validate(
        {
            "query_id": QUERY,
            "revision": 1,
            "parent_revision": None,
            "user_id": "u1",
            "project_name": "show-a",
            "source_kind": grant.source_kind,
            "source_contract_version": grant.source_contract_version,
            "operation": request.operation,
            "intent": request.purpose,
            "parameters": {"import_ref": "synthetic-host-upload"},
            "cohort_id": profile.payload.cohort_id,
            "cohort_version": profile.payload.cohort_version,
            "cohort_profile_id": profile.profile_id,
            "cohort_profile_revision": profile.revision,
            "cohort_profile_digest": profile.profile_digest,
            "capability_grant_id": grant.grant_id,
            "capability_grant_version": grant.grant_version,
            "capability_grant_digest": grant.grant_digest,
            "capability_evaluation_id": evaluation.evaluation_id,
            "capability_evaluation_digest": evaluation.evaluation_digest,
            "credential_ref": None,
            "max_pages": 1,
            "max_records": 2,
            "max_quota_units": 0,
            "query_digest": "sha256:" + "0" * 64,
            "created_by": "human-a",
            "created_at": NOW,
        }
    )
    return (grant, evaluation, query.model_copy(update={"query_digest": digest_source_query(query)}))


async def stage_query(factory):
    grant, evaluation, query = await fixture_query(factory)
    async with unit_of_work(factory).transaction() as tx:
        await tx.capabilities.consume(grant, evaluation, actor_id="human-a")
        await tx.queries.append(query)
        await tx.queries.stage_head(
            SourceQueryHead(query_id=QUERY, current_revision=1, head_version=1), expected_head_version=None
        )
    return query


async def test_query_and_capability_history_are_scoped_and_verified(session_factory):
    query = await stage_query(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.queries.get_exact(QUERY, 1) == query
        assert (await tx.queries.get_head(QUERY)).current_revision == 1
        assert (
            await tx.capabilities.get_grant(query.capability_grant_id, 1)
        ).grant_digest == query.capability_grant_digest
    async with unit_of_work(session_factory, "foreign").transaction() as tx:
        assert await tx.queries.get_exact(QUERY, 1) is None
        assert await tx.queries.get_exact("019a0000-0000-7000-8000-000000000032", 1) is None


async def test_failed_query_transaction_rolls_back_capability_and_query_rows(session_factory):
    grant, evaluation, query = await fixture_query(session_factory)

    async def interrupted():
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.capabilities.consume(grant, evaluation, actor_id="human-a")
            await tx.queries.append(query)
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        await interrupted()
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.queries.get_exact(QUERY, 1) is None
        assert await tx.capabilities.get_grant(grant.grant_id, 1) is None


async def test_query_head_cas_conflict_does_not_leave_an_orphan_revision(session_factory):
    original = await stage_query(session_factory)
    next_query = original.model_copy(update={"revision": 2, "parent_revision": 1})

    async def conflicting_append():
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.queries.append(next_query)
            await tx.queries.stage_head(
                SourceQueryHead(query_id=QUERY, current_revision=2, head_version=2), expected_head_version=17
            )

    with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
        await conflicting_append()
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.queries.get_exact(QUERY, 2) is None
        assert (await tx.queries.get_head(QUERY)).current_revision == 1


@pytest.mark.parametrize("fault", ["body", "column", "malformed"])
async def test_historical_query_integrity_recomputes_both_envelope_and_columns(session_factory, fault):
    query = await stage_query(session_factory)
    async with session_factory() as session, session.begin():
        if fault == "body":
            values = {"body_json": {**query.model_dump(mode="json"), "intent": "AUDIENCE"}}
        elif fault == "column":
            values = {"query_digest": "sha256:" + "b" * 64}
        else:
            values = {"body_json": {**query.model_dump(mode="json"), "query_id": "invalid-id"}}
        await session.execute(update(M9SourceQueryModel).where(M9SourceQueryModel.query_id == QUERY).values(**values))
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.queries.get_exact(QUERY, 1)


async def test_foreign_query_cannot_be_staged_through_another_project_unit_of_work(session_factory):
    _, _, query = await fixture_query(session_factory)
    with pytest.raises(OpportunityError):
        async with unit_of_work(session_factory, "foreign").transaction() as tx:
            await tx.queries.append(query)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(M9SourceQueryModel)) == 0
