"""Canon schema v2 across the real transaction, resolver, and integrity paths."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lib.db.canon_uow import canon_authority_uow_factory, canon_projection_uow_factory
from r2.contracts import (
    AddEntityOperation,
    AddEventOperation,
    AddFactOperation,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    Entity,
    EntityType,
    EpistemicProposition,
    EpistemicState,
    Event,
    Fact,
    UpdateKnowledgeOperation,
    compute_epistemic_proposition_ref,
)
from r2.narrative.canon_resolver import CanonResolver
from r2.narrative.canon_transaction import CanonTransactionService
from r2.narrative.errors import CanonValidationError
from r2.narrative.hashing import seal_canon_delta
from r2.narrative.integrity import CanonIntegrityChecker, CanonIntegrityReport
from tests.integration.r2.narrative._canon_authority import (
    NOW,
    PROJECT,
    USER,
    Factory,
    delete_projection,
    main_branch_command,
    make_approval,
)

T_EARLY = datetime(2026, 1, 1, tzinfo=UTC)
T_MID = datetime(2026, 6, 1, tzinfo=UTC)
RING_REF = compute_epistemic_proposition_ref(subject_ref="obj-ring", predicate="owner", object_or_value="char-b")


def _entity(entity_id: str, kind: EntityType = EntityType.CHARACTER) -> Entity:
    return Entity(entity_id=entity_id, entity_type=kind, canonical_name=entity_id.title(), aliases=[])


def _seal_v(delta_id: str, base: str | None, schema: str, operations: list[CanonOperation]) -> CanonDelta:
    return seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id=delta_id,
            target_branch_id="main",
            base_canon_version_id=base,
            operations=operations,
            source_change_set_refs=["s-1"],
            author_decision_refs=["a-1"],
            validation_report_refs=[],
            content_schema_version=schema,
            created_at=NOW,
            created_by="showrunner",
        )
    )


def _v1_genesis_delta() -> CanonDelta:
    return _seal_v(
        "delta-v1",
        None,
        "r2-canon-schema-v1",
        [
            AddEntityOperation(operation_id="op-a", target_id="char-a", entity=_entity("char-a")),
            AddEntityOperation(operation_id="op-b", target_id="char-b", entity=_entity("char-b")),
            AddEntityOperation(
                operation_id="op-ring", target_id="obj-ring", entity=_entity("obj-ring", EntityType.OBJECT)
            ),
            AddEventOperation(
                operation_id="op-seen",
                target_id="ev-seen",
                event=Event(event_id="ev-seen", event_type="SIGHT", participant_refs=["char-a"]),
            ),
            AddFactOperation(
                operation_id="op-fact",
                target_id="fact-owner",
                fact=Fact(
                    fact_id="fact-owner",
                    subject_ref="obj-ring",
                    predicate="owner",
                    value="char-b",
                    effective_from=T_EARLY,
                ),
            ),
        ],
    )


def _v2_knowledge_delta(base_version_id: str) -> CanonDelta:
    proposition = EpistemicProposition(
        proposition_ref=RING_REF, subject_ref="obj-ring", predicate="owner", object_or_value="char-b"
    )
    return _seal_v(
        "delta-v2",
        base_version_id,
        "r2-canon-schema-v2",
        [
            UpdateKnowledgeOperation(
                operation_id="op-k-1",
                target_id="k-1",
                subject_entity_id="char-a",
                proposition=proposition,
                epistemic_state=EpistemicState.KNOWN,
                effective_from=T_MID,
                evidence_event_refs=["ev-seen"],
            )
        ],
    )


def _v1_downgrade_delta(base_version_id: str) -> CanonDelta:
    return _seal_v(
        "delta-v1-downgrade",
        base_version_id,
        "r2-canon-schema-v1",
        [AddEntityOperation(operation_id="op-c", target_id="char-c", entity=_entity("char-c"))],
    )


def _service(factory: Factory, version_ids: list[str]) -> CanonTransactionService:
    return CanonTransactionService(canon_authority_uow_factory(factory), version_id_factory=iter(version_ids).__next__)


async def _commit_v1_then_v2(factory: Factory) -> tuple[str, str]:
    svc = _service(factory, ["v1", "v2"])
    await svc.create_branch(main_branch_command())
    v1_delta = _v1_genesis_delta()
    await svc.commit(
        delta=v1_delta,
        approval=make_approval(v1_delta, approval_ref="ap-v1"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    v2_delta = _v2_knowledge_delta("v1")
    v2_result = await svc.commit(
        delta=v2_delta,
        approval=make_approval(v2_delta, approval_ref="ap-v2"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    return "v1", v2_result.version.content_hash


async def _resolve(factory: Factory, version_id: str):
    async with canon_projection_uow_factory(factory)() as uow:
        return await CanonResolver(uow.repository).resolve(
            branch_id="main", version_id=version_id, project_name=PROJECT, user_id=USER
        )


async def _run_checker(factory: Factory) -> CanonIntegrityReport:
    async with canon_projection_uow_factory(factory)() as uow:
        return await CanonIntegrityChecker(uow.repository).check_scope(project_name=PROJECT, user_id=USER)


async def test_v1_genesis_then_v2_knowledge_delta_commits_and_records_the_target_selector(
    session_factory: Factory,
) -> None:
    svc = _service(session_factory, ["v1", "v2"])
    await svc.create_branch(main_branch_command())
    v1_delta = _v1_genesis_delta()
    v1_result = await svc.commit(
        delta=v1_delta,
        approval=make_approval(v1_delta, approval_ref="ap-v1"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    assert v1_result.version.content_schema_version == "r2-canon-schema-v1"

    v2_delta = _v2_knowledge_delta("v1")
    v2_result = await svc.commit(
        delta=v2_delta,
        approval=make_approval(v2_delta, approval_ref="ap-v2"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    assert v2_result.version.content_schema_version == "r2-canon-schema-v2"
    assert v2_result.version.parent_version_id == "v1"


async def test_projection_loss_rebuilds_the_mixed_v1_v2_lineage(session_factory: Factory) -> None:
    _, v2_hash = await _commit_v1_then_v2(session_factory)
    await delete_projection(session_factory, "v2")
    rebuilt = await _resolve(session_factory, "v2")
    assert rebuilt.content_schema_version == "r2-canon-schema-v2"
    assert rebuilt.content_hash == v2_hash
    assert rebuilt.content.knowledge_states_by_id["k-1"].epistemic_state is EpistemicState.KNOWN
    assert RING_REF in rebuilt.content.epistemic_propositions_by_ref


async def test_v1_content_hash_of_the_v1_version_is_unchanged_by_v2(session_factory: Factory) -> None:
    await _commit_v1_then_v2(session_factory)
    v1_view = await _resolve(session_factory, "v1")
    assert v1_view.content_schema_version == "r2-canon-schema-v1"
    assert v1_view.content.knowledge_states_by_id == {}


async def test_a_v2_to_v1_downgrade_delta_is_rejected(session_factory: Factory) -> None:
    await _commit_v1_then_v2(session_factory)
    svc = _service(session_factory, ["v3"])
    downgrade = _v1_downgrade_delta("v2")
    with pytest.raises(CanonValidationError):
        await svc.commit(
            delta=downgrade,
            approval=make_approval(downgrade, approval_ref="ap-v3"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )


async def test_integrity_checker_accepts_a_mixed_v1_v2_branch(session_factory: Factory) -> None:
    await _commit_v1_then_v2(session_factory)
    report = await _run_checker(session_factory)
    assert report.ok is True
    assert report.findings == ()
