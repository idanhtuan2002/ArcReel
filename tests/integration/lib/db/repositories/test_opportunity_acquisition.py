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


def planned_attempt(query, *, command_id="019a0000-0000-7000-8000-000000000041"):
    from r2.contracts.opportunity import AcquisitionAttempt

    return AcquisitionAttempt(
        attempt_id="019a0000-0000-7000-8000-000000000042",
        attempt_version=1,
        user_id=query.user_id,
        project_name=query.project_name,
        actor_id="human-a",
        command_id=command_id,
        request_digest="sha256:" + "a" * 64,
        query_id=query.query_id,
        query_revision=query.revision,
        query_digest=query.query_digest,
        page_cursor_digest=None,
        state="PLANNED",
        adapter_version="manual-import.v1",
        started_at=None,
        completed_at=None,
        provider_request_id=None,
        outcome_reason=None,
    )


async def prepare_attempt(factory):
    query = await stage_query(factory)
    attempt = planned_attempt(query)
    async with unit_of_work(factory).transaction() as tx:
        stored, created = await tx.attempts.prepare(attempt)
        assert created
        assert stored == attempt
    return attempt


async def test_attempt_replay_preserves_identity_and_rejects_changed_request_or_project(session_factory):
    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        stored, created = await tx.attempts.prepare(attempt)
        assert not created
        assert stored == attempt
    for changed in (
        attempt.model_copy(update={"request_digest": "sha256:" + "b" * 64}),
        attempt.model_copy(update={"project_name": "foreign"}),
    ):
        with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
            async with unit_of_work(session_factory, changed.project_name).transaction() as tx:
                await tx.attempts.prepare(changed)
    async with unit_of_work(session_factory, "foreign").transaction() as tx:
        assert await tx.attempts.get_exact(attempt.attempt_id) is None


async def test_attempt_running_replay_never_returns_a_new_dispatch_permission(session_factory):
    from r2.contracts.opportunity import AttemptState

    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        running = await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        assert running.started_at is not None
        assert running.completed_at is None
    async with unit_of_work(session_factory).transaction() as tx:
        replay, created = await tx.attempts.prepare(attempt)
        assert not created
        assert replay == running
        assert replay.attempt_version == 2
    with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)


@pytest.mark.parametrize("state", ["SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN"])
async def test_attempt_transition_stamps_database_time_and_preserves_terminal_or_uncertain_state(
    session_factory, state
):
    from r2.contracts.opportunity import AttemptOutcomeReason, AttemptState

    attempt = await prepare_attempt(session_factory)
    reason = {"SUCCEEDED": "COMPLETED", "FAILED": "PROVIDER_REJECTED", "OUTCOME_UNKNOWN": "RESPONSE_OUTCOME_UNKNOWN"}[
        state
    ]
    async with unit_of_work(session_factory).transaction() as tx:
        await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
    async with unit_of_work(session_factory).transaction() as tx:
        before = await tx.profiles.database_time()
        result = await tx.attempts.transition(
            attempt.attempt_id, expected_version=2, state=AttemptState(state), reason=AttemptOutcomeReason(reason)
        )
        after = await tx.profiles.database_time()
        assert result.attempt_version == 3
        assert result.started_at is not None
        if state == "OUTCOME_UNKNOWN":
            assert result.completed_at is None
        else:
            assert before <= result.completed_at <= after
    with pytest.raises(OpportunityError):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.transition(attempt.attempt_id, expected_version=3, state=AttemptState.RUNNING)
    async with unit_of_work(session_factory).transaction() as tx:
        replay, created = await tx.attempts.prepare(attempt)
        assert not created
        assert replay == result


async def test_unknown_attempt_requires_qualified_resolution_before_becoming_terminal(session_factory):
    from r2.contracts.opportunity import AttemptOutcomeReason, AttemptState

    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        await tx.attempts.transition(
            attempt.attempt_id,
            expected_version=2,
            state=AttemptState.OUTCOME_UNKNOWN,
            reason=AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
        )
    with pytest.raises(OpportunityError, match="M9_ACQUISITION_OUTCOME_UNKNOWN"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.transition(
                attempt.attempt_id,
                expected_version=3,
                state=AttemptState.SUCCEEDED,
                reason=AttemptOutcomeReason.COMPLETED,
            )
    async with unit_of_work(session_factory).transaction() as tx:
        current = await tx.attempts.get_exact(attempt.attempt_id)
        assert current.state == AttemptState.OUTCOME_UNKNOWN
        assert current.attempt_version == 3


@pytest.mark.parametrize("fault", ["column", "body", "malformed", "query_binding"])
async def test_attempt_reader_revalidates_persisted_state_and_query_binding(session_factory, fault):
    from lib.db.models.opportunity_acquisition import M9AcquisitionAttemptModel

    attempt = await prepare_attempt(session_factory)
    values = (
        {"state": "RUNNING"}
        if fault == "column"
        else {
            "body_json": {
                **attempt.model_dump(mode="json"),
                {"body": "actor_id", "malformed": "attempt_id", "query_binding": "query_digest"}[fault]: {
                    "body": "foreign",
                    "malformed": "bad",
                    "query_binding": "sha256:" + "b" * 64,
                }[fault],
            }
        }
    )
    async with session_factory() as session, session.begin():
        await session.execute(update(M9AcquisitionAttemptModel).values(**values))
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.get_exact(attempt.attempt_id)


async def test_attempt_prepare_and_transition_are_rolled_back_with_application_transaction(session_factory):
    from r2.contracts.opportunity import AttemptState

    query = await stage_query(session_factory)
    attempt = planned_attempt(query)

    async def interrupted():
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.prepare(attempt)
            await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
            raise RuntimeError("injected")

    with pytest.raises(RuntimeError, match="injected"):
        await interrupted()
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.attempts.get_exact(attempt.attempt_id) is None


@pytest.mark.parametrize("reason", ["COMPLETED", "RESPONSE_OUTCOME_UNKNOWN", "OPERATOR_RESOLVED", None])
async def test_known_failure_cannot_claim_completion_or_unqualified_reconciliation(session_factory, reason):
    from r2.contracts.opportunity import AttemptOutcomeReason, AttemptState

    attempt = await prepare_attempt(session_factory)
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.transition(
                attempt.attempt_id,
                expected_version=1,
                state=AttemptState.FAILED,
                reason=None if reason is None else AttemptOutcomeReason(reason),
            )
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.attempts.get_exact(attempt.attempt_id) == attempt


async def test_unknown_can_escalate_to_operator_but_cannot_resolve_without_host_proof(session_factory):
    from r2.contracts.opportunity import AttemptOutcomeReason, AttemptState

    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        await tx.attempts.transition(
            attempt.attempt_id,
            expected_version=2,
            state=AttemptState.OUTCOME_UNKNOWN,
            reason=AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
        )
        operator = await tx.attempts.transition(
            attempt.attempt_id,
            expected_version=3,
            state=AttemptState.NEEDS_OPERATOR,
            reason=AttemptOutcomeReason.RESPONSE_OUTCOME_UNKNOWN,
        )
        assert operator.completed_at is None
    with pytest.raises(OpportunityError, match="M9_ACQUISITION_OUTCOME_UNKNOWN"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.transition(
                attempt.attempt_id,
                expected_version=4,
                state=AttemptState.FAILED,
                reason=AttemptOutcomeReason.OPERATOR_RESOLVED,
            )
    async with unit_of_work(session_factory).transaction() as tx:
        replay, created = await tx.attempts.prepare(attempt)
        assert replay == operator
        assert not created


async def checkpoint_fixture(tx):
    from r2.contracts.opportunity import SnapshotPage
    from tests.unit.r2.opportunity.test_capabilities import _page

    module = importlib.import_module("r2.opportunity.acquisition")
    assert hasattr(module, "PageCheckpoint"), "B3 typed page checkpoint is missing"
    grant, _, _ = _authority()
    captured_at = await tx.profiles.database_time()
    clocks = importlib.import_module("r2.opportunity.capabilities").page_clocks(
        _page(("manual-public-metadata",)), grant, captured_at=captured_at
    )
    page = SnapshotPage(
        ordinal=1,
        request_cursor_digest=None,
        response_cursor_digest=None,
        provider_request_id=None,
        payload_ref="payload:opaque",
        payload_integrity_ref="integrity:opaque",
        retained_source_payload_digest=None,
        raw_media_type="application/json",
        raw_size_bytes=2,
        data_classes=("manual-public-metadata",),
        data_class_clocks=clocks,
        record_count=1,
        captured_at=captured_at,
        missing_reason=None,
    )
    return module.PageCheckpoint(
        page=page,
        source_identity_refs=("identity:opaque",),
        quota_units_observed=0,
        next_cursor_ref=None,
        next_cursor_integrity_ref=None,
        terminal_page=True,
        provider_observed_at=None,
    )


async def test_page_checkpoint_reopen_is_exact_and_replay_cannot_renew_capture_clocks(session_factory):
    from datetime import timedelta

    from r2.contracts.opportunity import AttemptState

    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        checkpoint = await checkpoint_fixture(tx)
        assert await tx.pages.append(attempt.attempt_id, checkpoint, expected_attempt_version=2) == checkpoint
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.pages.list_for_attempt(attempt.attempt_id) == (checkpoint,)
        assert await tx.pages.append(attempt.attempt_id, checkpoint, expected_attempt_version=2) == checkpoint
    renewed = checkpoint.model_copy(
        update={
            "page": checkpoint.page.model_copy(
                update={
                    "captured_at": checkpoint.page.captured_at + timedelta(seconds=1),
                    "data_class_clocks": tuple(
                        c.model_copy(
                            update={
                                "captured_at": c.captured_at + timedelta(seconds=1),
                                "refresh_due_at": c.refresh_due_at + timedelta(seconds=1),
                                "retention_due_at": c.retention_due_at + timedelta(seconds=1),
                            }
                        )
                        for c in checkpoint.page.data_class_clocks
                    ),
                }
            )
        }
    )
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.pages.append(attempt.attempt_id, renewed, expected_attempt_version=2)
    async with unit_of_work(session_factory, "foreign").transaction() as tx:
        assert await tx.pages.list_for_attempt(attempt.attempt_id) == ()


@pytest.mark.parametrize("fault", ["page", "checkpoint", "malformed"])
async def test_page_checkpoint_reader_refuses_mutated_metadata(session_factory, fault):
    from lib.db.models.opportunity_acquisition import M9SnapshotPageModel
    from r2.contracts.opportunity import AttemptState

    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        checkpoint = await checkpoint_fixture(tx)
        await tx.pages.append(attempt.attempt_id, checkpoint, expected_attempt_version=2)
    if fault == "page":
        values = {"body_json": {**checkpoint.page.model_dump(mode="json"), "record_count": 2}}
    elif fault == "checkpoint":
        values = {"checkpoint_json": {**checkpoint.model_dump(mode="json"), "source_identity_refs": ["identity:other"]}}
    else:
        values = {"checkpoint_json": {"unknown": True}}
    async with session_factory() as session, session.begin():
        await session.execute(update(M9SnapshotPageModel).values(**values))
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.pages.list_for_attempt(attempt.attempt_id)


@pytest.mark.parametrize("fault", ["planned", "stale_version", "future", "page_bound", "initial_cursor", "clock_rule"])
async def test_page_admission_requires_running_attempt_version_database_anchor_and_bounds(session_factory, fault):
    from datetime import timedelta

    from r2.contracts.opportunity import AttemptState

    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        if fault != "planned":
            await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        checkpoint = await checkpoint_fixture(tx)
    page = checkpoint.page
    if fault == "future":
        page = page.model_copy(update={"captured_at": page.captured_at + timedelta(days=1)})
    elif fault == "page_bound":
        page = page.model_copy(update={"ordinal": 2})
    elif fault == "initial_cursor":
        page = page.model_copy(update={"request_cursor_digest": "sha256:" + "b" * 64})
    elif fault == "clock_rule":
        page = page.model_copy(
            update={
                "data_class_clocks": tuple(
                    clock.model_copy(update={"retention_due_at": clock.retention_due_at + timedelta(seconds=1)})
                    for clock in page.data_class_clocks
                )
            }
        )
    checkpoint = checkpoint.model_copy(update={"page": page})
    with pytest.raises(OpportunityError):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.pages.append(
                attempt.attempt_id, checkpoint, expected_attempt_version=17 if fault == "stale_version" else 2
            )
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.pages.list_for_attempt(attempt.attempt_id) == ()


async def stage_checkpoint(factory):
    from r2.contracts.opportunity import AttemptState

    attempt = await prepare_attempt(factory)
    async with unit_of_work(factory).transaction() as tx:
        running = await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        checkpoint = await checkpoint_fixture(tx)
        await tx.pages.append(attempt.attempt_id, checkpoint, expected_attempt_version=2)
    return running, checkpoint


async def snapshot_fixture(tx, attempt):
    from r2.contracts.opportunity import SourceSnapshot
    from r2.opportunity.digests import digest_source_snapshot

    query = await tx.queries.get_exact(attempt.query_id, attempt.query_revision)
    checkpoints = await tx.pages.list_for_attempt(attempt.attempt_id)
    now = await tx.profiles.database_time()
    snapshot = SourceSnapshot(
        snapshot_id="019a0000-0000-7000-8000-000000000051",
        revision=1,
        parent_revision=None,
        user_id=query.user_id,
        project_name=query.project_name,
        query_id=query.query_id,
        query_revision=query.revision,
        query_digest=query.query_digest,
        attempt_id=attempt.attempt_id,
        source_kind=query.source_kind,
        source_contract_version=query.source_contract_version,
        source_identity_refs=tuple(ref for item in checkpoints for ref in item.source_identity_refs),
        pages=tuple(item.page for item in checkpoints),
        coverage_state="COMPLETE_WITHIN_DECLARED_BOUNDS",
        requested_record_limit=query.max_records,
        returned_record_count=sum(item.page.record_count for item in checkpoints),
        coverage_note="Synthetic declared bounds.",
        provider_observed_at=None,
        capture_started_at=attempt.started_at,
        capture_completed_at=now,
        adapter_version=attempt.adapter_version,
        capability_grant_digest=query.capability_grant_digest,
        capability_evaluation_digest=query.capability_evaluation_digest,
        snapshot_digest="sha256:" + "0" * 64,
        created_at=now,
    )
    return snapshot.model_copy(update={"snapshot_digest": digest_source_snapshot(snapshot)})


def observation_fixture(snapshot):
    from r2.contracts.opportunity import NormalizedSourceObservation
    from r2.opportunity.digests import digest_source_observation

    page = snapshot.pages[0]
    observation = NormalizedSourceObservation(
        observation_id="019a0000-0000-7000-8000-000000000052",
        revision=1,
        parent_revision=None,
        user_id=snapshot.user_id,
        project_name=snapshot.project_name,
        snapshot_id=snapshot.snapshot_id,
        snapshot_digest=snapshot.snapshot_digest,
        page_ordinal=1,
        source_kind=snapshot.source_kind,
        source_identity_ref=snapshot.source_identity_refs[0],
        native_field_name="views",
        native_field_definition="Synthetic view count within the declared window.",
        native_field_version="synthetic-count.v1",
        data_class="manual-public-metadata",
        value_ref="value:opaque",
        value_integrity_ref="integrity:value",
        retained_normalized_value_digest=None,
        unit="count",
        window_start=None,
        window_end=None,
        missing_reason=None,
        payload_integrity_ref=page.payload_integrity_ref,
        retained_source_payload_digest=page.retained_source_payload_digest,
        normalization_version="manual-import.v1",
        observation_digest="sha256:" + "0" * 64,
        observed_at=page.captured_at,
    )
    return observation.model_copy(update={"observation_digest": digest_source_observation(observation)})


async def stage_snapshot(factory):
    attempt, _ = await stage_checkpoint(factory)
    async with unit_of_work(factory).transaction() as tx:
        snapshot = await snapshot_fixture(tx, attempt)
        await tx.snapshots.append(snapshot)
        observation = observation_fixture(snapshot)
        await tx.observations.append(observation, expected_head_version=None)
    return snapshot, observation


async def test_snapshot_and_observation_round_trip_verify_scoped_immutable_page_lineage(session_factory):
    snapshot, observation = await stage_snapshot(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.snapshots.get_exact(snapshot.snapshot_id, 1) == snapshot
        assert await tx.snapshots.get_for_attempt(snapshot.attempt_id) == snapshot
        assert await tx.observations.get_exact(observation.observation_id, 1) == observation
        assert await tx.observations.get_current(observation.observation_id) == observation
    async with unit_of_work(session_factory, "foreign").transaction() as tx:
        assert await tx.snapshots.get_exact(snapshot.snapshot_id, 1) is None
        assert await tx.observations.get_current(observation.observation_id) is None


@pytest.mark.parametrize("fault", ["digest", "query", "page", "identity", "adapter", "capability"])
async def test_snapshot_admission_refuses_unbound_metadata_even_with_recomputed_digest(session_factory, fault):
    from r2.opportunity.digests import digest_source_snapshot

    attempt, _ = await stage_checkpoint(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        snapshot = await snapshot_fixture(tx, attempt)
    changes = {
        "digest": {"snapshot_digest": "sha256:" + "b" * 64},
        "query": {"query_digest": "sha256:" + "b" * 64},
        "page": {"pages": (snapshot.pages[0].model_copy(update={"payload_integrity_ref": "integrity:other"}),)},
        "identity": {"source_identity_refs": ("identity:foreign",)},
        "adapter": {"adapter_version": "other.v1"},
        "capability": {"capability_evaluation_digest": "sha256:" + "b" * 64},
    }
    snapshot = snapshot.model_copy(update=changes[fault])
    if fault != "digest":
        snapshot = snapshot.model_copy(update={"snapshot_digest": digest_source_snapshot(snapshot)})
    with pytest.raises(OpportunityError):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.snapshots.append(snapshot)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.snapshots.get_for_attempt(attempt.attempt_id) is None


@pytest.mark.parametrize("fault", ["digest", "identity", "page", "payload", "class"])
async def test_observation_admission_requires_exact_snapshot_page_and_value_lineage(session_factory, fault):
    from r2.opportunity.digests import digest_source_observation

    attempt, _ = await stage_checkpoint(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        snapshot = await snapshot_fixture(tx, attempt)
        await tx.snapshots.append(snapshot)
    observation = observation_fixture(snapshot)
    changes = {
        "digest": {"observation_digest": "sha256:" + "b" * 64},
        "identity": {"source_identity_ref": "identity:foreign"},
        "page": {"page_ordinal": 2},
        "payload": {"payload_integrity_ref": "integrity:foreign"},
        "class": {"data_class": "manual-excerpt"},
    }
    observation = observation.model_copy(update=changes[fault])
    if fault != "digest":
        observation = observation.model_copy(update={"observation_digest": digest_source_observation(observation)})
    with pytest.raises(OpportunityError):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.observations.append(observation, expected_head_version=None)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.observations.get_current(observation.observation_id) is None


@pytest.mark.parametrize("aggregate", ["snapshot", "observation"])
async def test_snapshot_and_observation_readers_recompute_stored_bodies(session_factory, aggregate):
    from lib.db.models.opportunity_acquisition import M9SourceObservationModel, M9SourceSnapshotModel

    snapshot, observation = await stage_snapshot(session_factory)
    model, original = (
        (M9SourceSnapshotModel, snapshot) if aggregate == "snapshot" else (M9SourceObservationModel, observation)
    )
    field = "coverage_note" if aggregate == "snapshot" else "native_field_definition"
    async with session_factory() as session, session.begin():
        await session.execute(update(model).values(body_json={**original.model_dump(mode="json"), field: "mutated"}))

    async def read_mutated():
        async with unit_of_work(session_factory).transaction() as tx:
            if aggregate == "snapshot":
                await tx.snapshots.get_exact(snapshot.snapshot_id, 1)
            else:
                await tx.observations.get_current(observation.observation_id)

    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        await read_mutated()


async def test_observation_correction_appends_and_cas_failure_rolls_back_new_revision(session_factory):
    from r2.opportunity.digests import digest_source_observation

    _, observation = await stage_snapshot(session_factory)
    corrected = observation.model_copy(update={"revision": 2, "parent_revision": 1, "value_ref": "value:correction"})
    corrected = corrected.model_copy(update={"observation_digest": digest_source_observation(corrected)})
    async with unit_of_work(session_factory).transaction() as tx:
        await tx.observations.append(corrected, expected_head_version=1)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.observations.get_current(observation.observation_id) == corrected
        assert await tx.observations.get_exact(observation.observation_id, 1) == observation
    divergent = corrected.model_copy(update={"revision": 3, "parent_revision": 2, "value_ref": "value:divergent"})
    divergent = divergent.model_copy(update={"observation_digest": digest_source_observation(divergent)})
    with pytest.raises(OpportunityError, match="M9_STALE_HEAD"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.observations.append(divergent, expected_head_version=1)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.observations.get_exact(observation.observation_id, 3) is None
        assert await tx.observations.get_current(observation.observation_id) == corrected


async def test_complete_snapshot_requires_a_proven_terminal_page(session_factory):
    from r2.contracts.opportunity import AttemptState

    attempt = await prepare_attempt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        running = await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
        snapshot = await snapshot_fixture(tx, running)
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.snapshots.append(snapshot)


async def test_snapshot_reader_revalidates_original_consumed_capability_evaluation(session_factory):
    from lib.db.models.opportunity_acquisition import M9CapabilityEvaluationModel

    snapshot, _ = await stage_snapshot(session_factory)
    async with session_factory() as session, session.begin():
        await session.execute(update(M9CapabilityEvaluationModel).values(evaluation_digest="sha256:" + "b" * 64))
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.snapshots.get_exact(snapshot.snapshot_id, 1)


def query_receipt(query, now):
    from r2.contracts.opportunity import QueryReceipt
    from r2.opportunity.digests import digest_command_result

    receipt = QueryReceipt(
        command_id="019a0000-0000-7000-8000-000000000071",
        request_digest="sha256:" + "a" * 64,
        query=query,
        head=SourceQueryHead(query_id=query.query_id, current_revision=1, head_version=1),
        result_digest="sha256:" + "0" * 64,
        committed_at=now,
    )
    return receipt.model_copy(
        update={"result_digest": digest_command_result("declare_query", receipt.request_digest, receipt)}
    )


def receipt_context(receipt, project="show-a"):
    from r2.contracts.opportunity import CommandContext

    return CommandContext(command_id=receipt.command_id, user_id="u1", project_name=project, actor_id="human-a")


async def test_typed_query_receipt_reconstructs_verified_immutable_revision_without_renewing_time(session_factory):
    query = await stage_query(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        receipt = query_receipt(query, await tx.profiles.database_time())
        await tx.receipts.stage_query(context=receipt_context(receipt), receipt=receipt)
    async with unit_of_work(session_factory).transaction() as tx:
        replay = await tx.receipts.get_query(context=receipt_context(receipt), request_digest=receipt.request_digest)
        assert replay == receipt
    for project, digest in (("foreign", receipt.request_digest), ("show-a", "sha256:" + "b" * 64)):
        with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
            async with unit_of_work(session_factory, project).transaction() as tx:
                await tx.receipts.get_query(context=receipt_context(receipt, project), request_digest=digest)


@pytest.mark.parametrize("fault", ["ref", "digest", "kind", "time"])
async def test_query_receipt_reconstruction_refuses_malformed_or_substituted_evidence(session_factory, fault):
    from datetime import timedelta

    from lib.db.models.opportunity import M9CommandReceiptModel

    query = await stage_query(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        receipt = query_receipt(query, await tx.profiles.database_time())
        await tx.receipts.stage_query(context=receipt_context(receipt), receipt=receipt)
    values = {
        "ref": {"result_ref": "missing:1:1"},
        "digest": {"result_digest": "sha256:" + "b" * 64},
        "kind": {"result_kind": "COHORT_PROFILE"},
        "time": {"committed_at": receipt.committed_at + timedelta(seconds=1)},
    }[fault]
    async with session_factory() as session, session.begin():
        await session.execute(update(M9CommandReceiptModel).values(**values))
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.receipts.get_query(context=receipt_context(receipt), request_digest=receipt.request_digest)


async def final_acquisition_receipt(factory):
    from r2.contracts.opportunity import AcquisitionReceipt, AttemptOutcomeReason, AttemptState
    from r2.opportunity.digests import digest_command_result

    snapshot, _ = await stage_snapshot(factory)
    async with unit_of_work(factory).transaction() as tx:
        attempt = await tx.attempts.transition(
            snapshot.attempt_id,
            expected_version=2,
            state=AttemptState.SUCCEEDED,
            reason=AttemptOutcomeReason.COMPLETED,
        )
        receipt = AcquisitionReceipt(
            command_id=attempt.command_id,
            request_digest=attempt.request_digest,
            attempt_id=attempt.attempt_id,
            attempt_version=attempt.attempt_version,
            state=attempt.state,
            snapshot_ids=(snapshot.snapshot_id,),
            snapshot_digests=(snapshot.snapshot_digest,),
            result_digest="sha256:" + "0" * 64,
            committed_at=await tx.profiles.database_time(),
        )
        receipt = receipt.model_copy(
            update={"result_digest": digest_command_result("acquire", receipt.request_digest, receipt)}
        )
        await tx.receipts.stage_acquisition(context=receipt_context(receipt), receipt=receipt)
    return receipt


async def test_acquisition_receipt_reconstructs_terminal_attempt_and_its_exact_snapshot(session_factory):
    receipt = await final_acquisition_receipt(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        assert (
            await tx.receipts.get_acquisition(context=receipt_context(receipt), request_digest=receipt.request_digest)
            == receipt
        )
    with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
        async with unit_of_work(session_factory, "foreign").transaction() as tx:
            await tx.receipts.get_acquisition(
                context=receipt_context(receipt, "foreign"), request_digest=receipt.request_digest
            )


async def test_acquisition_receipt_fails_when_bound_snapshot_evidence_has_changed(session_factory):
    from lib.db.models.opportunity_acquisition import M9SourceSnapshotModel

    receipt = await final_acquisition_receipt(session_factory)
    async with session_factory() as session, session.begin():
        row = await session.scalar(select(M9SourceSnapshotModel))
        await session.execute(
            update(M9SourceSnapshotModel).values(body_json={**row.body_json, "snapshot_digest": "sha256:" + "b" * 64})
        )
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.receipts.get_acquisition(context=receipt_context(receipt), request_digest=receipt.request_digest)


@pytest.mark.parametrize("fault", ["actor", "time"])
async def test_query_declaration_lookup_verifies_receipt_bound_metadata_outside_semantic_digest(session_factory, fault):
    from datetime import timedelta

    query = await stage_query(session_factory)
    async with unit_of_work(session_factory).transaction() as tx:
        receipt = query_receipt(query, await tx.profiles.database_time())
        await tx.receipts.stage_query(context=receipt_context(receipt), receipt=receipt)
        assert await tx.receipts.get_query_for_revision(query.query_id, query.revision) == receipt
    mutated = query.model_copy(
        update={"created_by": "foreign"}
        if fault == "actor"
        else {
            "created_at": query.created_at + timedelta(seconds=1),
        }
    )
    assert digest_source_query(mutated) == query.query_digest
    async with session_factory() as session, session.begin():
        await session.execute(update(M9SourceQueryModel).values(body_json=mutated.model_dump(mode="json")))
    with pytest.raises(OpportunityError, match="M9_REQUIRED_EVIDENCE_MISSING"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.receipts.get_query_for_revision(query.query_id, query.revision)


async def test_attempt_command_preflight_returns_retained_state_before_any_new_query_admission(session_factory):
    from r2.contracts.opportunity import AttemptState

    attempt = await prepare_attempt(session_factory)
    context = receipt_context(attempt)
    async with unit_of_work(session_factory).transaction() as tx:
        running = await tx.attempts.transition(attempt.attempt_id, expected_version=1, state=AttemptState.RUNNING)
    async with unit_of_work(session_factory).transaction() as tx:
        assert await tx.attempts.get_for_command(context=context, request_digest=attempt.request_digest) == running
        current = await tx.receipts.current_acquisition(context=context, request_digest=attempt.request_digest)
        assert current.attempt_id == running.attempt_id
        assert current.attempt_version == 2
        assert current.state == AttemptState.RUNNING
        assert current.committed_at == running.started_at
    with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
        async with unit_of_work(session_factory).transaction() as tx:
            await tx.attempts.get_for_command(context=context, request_digest="sha256:" + "b" * 64)
