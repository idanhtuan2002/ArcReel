"""Integration coverage for the scoped Narrative-lifecycle evidence adapter and UoW."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from lib.db.repositories.narrative_lifecycle import NarrativeLifecycleRepository
from r2.contracts.narrative_lifecycle import (
    CanonMutationEffectKey,
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeItem,
    NarrativeChangeSet,
    NarrativeRevision,
    NarrativeWorkScope,
    SourceSpan,
)
from r2.contracts.provenance import Provenance
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeEvidenceIdentityConflictError,
    NarrativeEvidenceIntegrityError,
)

NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)
USER = "u1"
OTHER_USER = "conformance"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def _scope(*, user_id: str = USER) -> NarrativeWorkScope:
    return NarrativeWorkScope(
        user_id=user_id,
        project_name=PROJECT,
        plan_id="plan-1",
        scene_contract_id="scene-1",
        canon_branch_id="branch-1",
    )


def _prov() -> Provenance:
    return Provenance(created_by="AGENT", created_at=NOW)


def _candidate(*, candidate_id: str = "cand-1", user_id: str = USER) -> DraftCandidate:
    return DraftCandidate(
        candidate_id=candidate_id,
        work_scope=_scope(user_id=user_id),
        base_canon_version_id="cv-1",
        plan_version=2,
        scene_contract_version=1,
        context_pack_id="ctx-1",
        normalized_content="prose",
        content_hash="pch:abc",
        writer_kind="AGENT",
        writer_version="w-1",
        provenance=_prov(),
        created_at=NOW,
        created_by="who",
        semantic_fingerprint="esf:1",
    )


def _revision(*, revision_id: str = "rev-1", candidate_id: str = "cand-1", user_id: str = USER) -> NarrativeRevision:
    return NarrativeRevision(
        revision_id=revision_id,
        work_scope=_scope(user_id=user_id),
        base_candidate_id=candidate_id,
        predecessor_revision_id=None,
        base_canon_version_id="cv-1",
        plan_version=2,
        scene_contract_version=1,
        context_pack_id="ctx-1",
        normalized_content="prose",
        content_hash="pch:abc",
        review_refs=["r-1"],
        provenance=_prov(),
        created_at=NOW,
        created_by="who",
        semantic_fingerprint="esf:2",
    )


def _attempt(*, attempt_id: str = "att-1", generation: int = 0, revision_id: str = "rev-1") -> ExtractionAttempt:
    return ExtractionAttempt(
        attempt_id=attempt_id,
        generation=generation,
        work_scope=_scope(),
        revision_id=revision_id,
        revision_acceptance_decision_id="dec-1",
        observed_revision_effective_generation=0,
        base_canon_version_id="cv-1",
        plan_version=2,
        scene_contract_version=1,
        context_pack_id="ctx-1",
        extractor_kind="LOCAL",
        extractor_version="x-1",
        policy_ref="pol",
        policy_version="1",
        admitted_at=NOW,
        admitted_by="who",
        input_fingerprint="if-1",
    )


def _result(
    *,
    result_id: str = "res-1",
    attempt_id: str = "att-1",
    generation: int = 0,
    outcome: str = "ABSTAINED",
    change_set_ids: tuple[str, ...] = (),
) -> ExtractionResult:
    return ExtractionResult(
        result_id=result_id,
        attempt_id=attempt_id,
        generation=generation,
        outcome=outcome,
        change_set_ids=change_set_ids,
        diagnostics=(),
        provider_receipt=None,
        completed_at=NOW,
        output_fingerprint="of-1",
    )


def _change_set(*, change_set_id: str, attempt_id: str = "att-1", generation: int = 0) -> NarrativeChangeSet:
    key = CanonMutationEffectKey(
        canon_subject_kind="FACT", subject_ref="hero", effect_descriptor="trust", canon_operation_count=1
    )
    span = SourceSpan(start=0, end=4)
    return NarrativeChangeSet(
        change_set_id=change_set_id,
        change_set_lineage_id=f"lin-{change_set_id}",
        source_revision_id="rev-1",
        extraction_attempt_id=attempt_id,
        extraction_generation=generation,
        base_canon_version_id="cv-1",
        source_spans=(span,),
        semantic_effect_keys=(key,),
        changes=(NarrativeChangeItem(change_id="ch-1", evidence_span=span, effect_keys=(key,), summary="s"),),
        confidence=0.7,
        extractor_version="x-1",
        policy_ref="pol",
        policy_version="1",
        created_at=NOW,
        output_fingerprint="of-cs",
    )


async def _seed_attempt(session_factory: Factory, *, generation: int = 0) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt(generation=generation))
        await uow.commit()


async def test_scoped_reads_collapse_unknown_and_cross_scope(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        assert await repo.get_exact_draft_candidate(candidate_id="cand-1", project_name=PROJECT, user_id=USER)
        assert await repo.get_exact_draft_candidate(candidate_id="ghost", project_name=PROJECT, user_id=USER) is None
        assert (
            await repo.get_exact_draft_candidate(candidate_id="cand-1", project_name=PROJECT, user_id=OTHER_USER)
        ) is None
        assert await repo.get_exact_revision(revision_id="rev-1", project_name="other", user_id=USER) is None
        assert await repo.get_exact_extraction_attempt(attempt_id="att-1", project_name=PROJECT, user_id=USER)


async def test_result_is_uniquely_bound_to_one_attempt_generation(session_factory: Factory) -> None:
    await _seed_attempt(session_factory, generation=0)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_non_successful_extraction(
            _result(result_id="res-1", generation=0, outcome="FAILED")
        )
        await uow.commit()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeAttemptGenerationConflict):
            await uow.repository.insert_non_successful_extraction(
                _result(result_id="res-2", generation=0, outcome="ABSTAINED")
            )


async def test_successful_bundle_stores_ordered_membership(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_successful_extraction(
            _result(outcome="SUCCEEDED", change_set_ids=("cs-2", "cs-1")),
            (_change_set(change_set_id="cs-2"), _change_set(change_set_id="cs-1")),
        )
        await uow.commit()
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        loaded = await repo.get_exact_extraction_result(
            attempt_id="att-1", generation=0, project_name=PROJECT, user_id=USER
        )
        assert loaded is not None
        assert tuple(loaded.change_set_ids) == ("cs-2", "cs-1")  # association order, not sorted
        assert await repo.get_exact_change_set(change_set_id="cs-1", project_name=PROJECT, user_id=USER) is not None


async def test_successful_bundle_with_mismatched_ids_writes_nothing(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeEvidenceIntegrityError):
            await uow.repository.insert_successful_extraction(
                _result(outcome="SUCCEEDED", change_set_ids=("cs-1", "cs-9")),
                (_change_set(change_set_id="cs-1"),),
            )
        await uow.commit()
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        assert (
            await repo.get_exact_extraction_result(attempt_id="att-1", generation=0, project_name=PROJECT, user_id=USER)
        ) is None
        assert await repo.get_exact_change_set(change_set_id="cs-1", project_name=PROJECT, user_id=USER) is None


async def test_non_success_result_rejects_declared_change_sets(session_factory: Factory) -> None:
    await _seed_attempt(session_factory)
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeEvidenceIntegrityError):
            await uow.repository.insert_non_successful_extraction(
                _result(outcome="SUCCEEDED", change_set_ids=("cs-1",))
            )


async def test_duplicate_candidate_id_fails_closed(session_factory: Factory) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate(candidate_id="cand-1"))
        await uow.commit()
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        with pytest.raises(NarrativeEvidenceIdentityConflictError):
            await uow.repository.insert_draft_candidate(_candidate(candidate_id="cand-1"))


async def test_uow_rollback_leaves_no_partial_evidence(session_factory: Factory) -> None:
    async with narrative_lifecycle_uow_factory(session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        # exit without commit -> rollback
    async with session_factory() as session:
        repo = NarrativeLifecycleRepository(session)
        assert await repo.get_exact_draft_candidate(candidate_id="cand-1", project_name=PROJECT, user_id=USER) is None
