"""Shared Canon authority seeding helpers for the M5A narrative integration tests.

Seeds branch / accepted-delta / version rows directly through the authority
adapter (Task 8's ``CanonTransactionService`` is not available to Task 7) and
provides small raw-SQL corruptors for the recovery tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import canon_authority_uow_factory
from lib.db.models.canon import (
    CanonBranchModel,
    CanonDeltaModel,
    CanonResolvedProjectionModel,
    CanonVersionModel,
)
from r2.contracts import (
    AcceptedCanonDeltaSnapshot,
    AddEntityOperation,
    AddEventOperation,
    CanonBranchSnapshot,
    CanonBranchType,
    CanonCommitApproval,
    CanonContent,
    CanonDelta,
    CanonDeltaPayload,
    CanonOperation,
    CanonVersionSnapshot,
    CreateCanonBranch,
    Entity,
    EntityType,
    Event,
    UpdateEntityOperation,
)
from r2.narrative.canon_state import apply_canon_delta, empty_canon_content
from r2.narrative.canon_transaction import CanonTransactionService
from r2.narrative.hashing import compute_canon_content_hash, seal_canon_delta

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
USER = "user-a"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def main_branch(*, branch_id: str = "main") -> CanonBranchSnapshot:
    return CanonBranchSnapshot(
        branch_id=branch_id,
        user_id=USER,
        project_name=PROJECT,
        branch_type=CanonBranchType.MAIN,
        parent_branch_id=None,
        parent_version_id=None,
        head_version_id=None,
        created_at=NOW,
        created_by="showrunner",
    )


def narrative_branch(
    *, branch_id: str = "story", parent_branch_id: str = "main", parent_version_id: str
) -> CanonBranchSnapshot:
    return CanonBranchSnapshot(
        branch_id=branch_id,
        user_id=USER,
        project_name=PROJECT,
        branch_type=CanonBranchType.NARRATIVE_BRANCH,
        parent_branch_id=parent_branch_id,
        parent_version_id=parent_version_id,
        head_version_id=None,
        created_at=NOW,
        created_by="showrunner",
    )


async def commit_version(
    factory: Factory,
    *,
    branch: CanonBranchSnapshot,
    base_content: CanonContent,
    base_version_id: str | None,
    add_entity_id: str,
    version_id: str,
    version_number: int,
    parent_version_id: str | None,
    delta_id: str,
    approval_ref: str,
    insert_branch: bool = False,
) -> CanonContent:
    operation = AddEntityOperation(
        operation_id=f"op-{add_entity_id}",
        target_id=add_entity_id,
        entity=Entity(
            entity_id=add_entity_id,
            entity_type=EntityType.CHARACTER,
            canonical_name=add_entity_id.replace("-", " ").title(),
            aliases=[],
        ),
    )
    delta = seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id=delta_id,
            target_branch_id=branch.branch_id,
            base_canon_version_id=base_version_id,
            operations=[operation],
            source_change_set_refs=["s-1"],
            author_decision_refs=["a-1"],
            validation_report_refs=[],
            created_at=NOW,
            created_by="showrunner",
        )
    )
    candidate = apply_canon_delta(base_content, delta)
    approval = CanonCommitApproval(
        approval_ref=approval_ref,
        canon_delta_id=delta_id,
        payload_hash=delta.payload_hash,
        payload_hash_algorithm="sha256",
        payload_hash_version="r2-canon-delta-v1",
        content_schema_version="r2-canon-schema-v1",
        project_name=branch.project_name,
        user_id=branch.user_id,
        approved_by="approver",
        approved_at=NOW,
        status="APPROVED",
    )
    accepted = AcceptedCanonDeltaSnapshot(delta=delta, approval=approval, committed_version_id=version_id)
    version = CanonVersionSnapshot(
        canon_version_id=version_id,
        branch_id=branch.branch_id,
        version_number=version_number,
        parent_version_id=parent_version_id,
        committed_delta_id=delta_id,
        committed_at=NOW,
        committed_by="showrunner",
        content_hash=compute_canon_content_hash(candidate),
        content_hash_algorithm="sha256",
        content_hash_version="r2-canon-content-v1",
        content_schema_version="r2-canon-schema-v1",
    )
    expected_head = None if version_number == 1 else parent_version_id
    async with canon_authority_uow_factory(factory)() as uow:
        if insert_branch:
            await uow.repository.insert_branch(branch)
        await uow.repository.insert_delta(accepted)
        await uow.repository.insert_version(version)
        await uow.repository.advance_head(
            branch_id=branch.branch_id,
            expected_head_id=expected_head,
            version_id=version_id,
            project_name=branch.project_name,
            user_id=branch.user_id,
        )
        await uow.commit()
    return candidate


async def seed_main_genesis(
    factory: Factory,
    *,
    entity_id: str = "hero",
    version_id: str = "main-v1",
    delta_id: str = "delta-main-1",
    approval_ref: str = "approval-main-1",
) -> tuple[CanonBranchSnapshot, CanonContent]:
    branch = main_branch()
    content = await commit_version(
        factory,
        branch=branch,
        base_content=empty_canon_content(),
        base_version_id=None,
        add_entity_id=entity_id,
        version_id=version_id,
        version_number=1,
        parent_version_id=None,
        delta_id=delta_id,
        approval_ref=approval_ref,
        insert_branch=True,
    )
    return branch, content


async def seed_pinned_child(factory: Factory) -> dict[str, object]:
    _, main_content = await seed_main_genesis(factory, entity_id="parent-entity", version_id="main-v1")
    child = narrative_branch(parent_version_id="main-v1")
    child_content = await commit_version(
        factory,
        branch=child,
        base_content=main_content,
        base_version_id="main-v1",
        add_entity_id="child-entity",
        version_id="child-v1",
        version_number=1,
        parent_version_id=None,
        delta_id="delta-child-1",
        approval_ref="approval-child-1",
        insert_branch=True,
    )
    return {
        "child_branch_id": child.branch_id,
        "child_version_id": "child-v1",
        "child_content": child_content,
        "child_content_hash": compute_canon_content_hash(child_content),
        "main_version_id": "main-v1",
    }


async def advance_main_to_v2(factory: Factory) -> CanonContent:
    _, main_content = await seed_main_genesis(factory, entity_id="parent-entity", version_id="main-v1")
    return await commit_version(
        factory,
        branch=main_branch(),
        base_content=main_content,
        base_version_id="main-v1",
        add_entity_id="main-extra",
        version_id="main-v2",
        version_number=2,
        parent_version_id="main-v1",
        delta_id="delta-main-2",
        approval_ref="approval-main-2",
    )


def _entity(entity_id: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        entity_type=EntityType.CHARACTER,
        canonical_name=entity_id.replace("-", " ").title(),
        aliases=[],
    )


def _seal(delta_id: str, branch_id: str, base_version_id: str | None, operation: CanonOperation) -> CanonDelta:
    return seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id=delta_id,
            target_branch_id=branch_id,
            base_canon_version_id=base_version_id,
            operations=[operation],
            source_change_set_refs=["s-1"],
            author_decision_refs=["a-1"],
            validation_report_refs=[],
            created_at=NOW,
            created_by="showrunner",
        )
    )


def make_entity_delta(delta_id: str, branch_id: str, base_version_id: str | None, entity_id: str) -> CanonDelta:
    operation = AddEntityOperation(operation_id=f"op-{entity_id}", target_id=entity_id, entity=_entity(entity_id))
    return _seal(delta_id, branch_id, base_version_id, operation)


def make_update_noop_delta(delta_id: str, branch_id: str, base_version_id: str | None, entity_id: str) -> CanonDelta:
    operation = UpdateEntityOperation(
        operation_id=f"op-update-{entity_id}", target_id=entity_id, entity=_entity(entity_id)
    )
    return _seal(delta_id, branch_id, base_version_id, operation)


def make_event_delta(
    delta_id: str, branch_id: str, base_version_id: str | None, *, event_id: str, participant: str
) -> CanonDelta:
    operation = AddEventOperation(
        operation_id=f"op-{event_id}",
        target_id=event_id,
        event=Event(event_id=event_id, event_type="ARRIVAL", participant_refs=[participant]),
    )
    return _seal(delta_id, branch_id, base_version_id, operation)


def make_approval(
    delta: CanonDelta,
    *,
    approval_ref: str,
    approved_by: str = "approver",
    approved_at: datetime = NOW,
) -> CanonCommitApproval:
    return CanonCommitApproval(
        approval_ref=approval_ref,
        canon_delta_id=delta.canon_delta_id,
        payload_hash=delta.payload_hash,
        payload_hash_algorithm=delta.payload_hash_algorithm,
        payload_hash_version=delta.payload_hash_version,
        content_schema_version=delta.content_schema_version,
        project_name=PROJECT,
        user_id=USER,
        approved_by=approved_by,
        approved_at=approved_at,
        status="APPROVED",
    )


def main_branch_command(branch_id: str = "main") -> CreateCanonBranch:
    return CreateCanonBranch(
        branch_id=branch_id,
        user_id=USER,
        project_name=PROJECT,
        branch_type=CanonBranchType.MAIN,
        created_at=NOW,
        created_by="showrunner",
    )


def narrative_branch_command(*, branch_id: str, parent_branch_id: str, parent_version_id: str) -> CreateCanonBranch:
    return CreateCanonBranch(
        branch_id=branch_id,
        user_id=USER,
        project_name=PROJECT,
        branch_type=CanonBranchType.NARRATIVE_BRANCH,
        parent_branch_id=parent_branch_id,
        parent_version_id=parent_version_id,
        created_at=NOW,
        created_by="showrunner",
    )


async def seed_genesis_via_service(factory: Factory, *, version_id: str = "v1") -> str:
    service = CanonTransactionService(
        canon_authority_uow_factory(factory), version_id_factory=iter([version_id]).__next__
    )
    await service.create_branch(main_branch_command())
    delta = make_entity_delta("delta-genesis", "main", None, "hero")
    await service.commit(
        delta=delta,
        approval=make_approval(delta, approval_ref="approval-genesis"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )
    return version_id


async def local_version_count(factory: Factory, branch_id: str) -> int:
    async with factory() as session:
        result = await session.execute(
            select(func.count()).select_from(CanonVersionModel).where(CanonVersionModel.branch_id == branch_id)
        )
        return int(result.scalar_one())


async def total_delta_count(factory: Factory) -> int:
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(CanonDeltaModel))
        return int(result.scalar_one())


async def authority_snapshot(factory: Factory) -> dict[str, object]:
    async with factory() as session:
        deltas = (
            (await session.execute(select(CanonDeltaModel.canon_delta_id).order_by(CanonDeltaModel.canon_delta_id)))
            .scalars()
            .all()
        )
        versions = (
            (
                await session.execute(
                    select(CanonVersionModel.canon_version_id).order_by(CanonVersionModel.canon_version_id)
                )
            )
            .scalars()
            .all()
        )
        heads = (
            await session.execute(
                select(CanonBranchModel.branch_id, CanonBranchModel.head_version_id).order_by(
                    CanonBranchModel.branch_id
                )
            )
        ).all()
        projections = (
            (
                await session.execute(
                    select(CanonResolvedProjectionModel.canon_version_id).order_by(
                        CanonResolvedProjectionModel.canon_version_id
                    )
                )
            )
            .scalars()
            .all()
        )
    return {
        "deltas": list(deltas),
        "versions": list(versions),
        "heads": [tuple(row) for row in heads],
        "projections": list(projections),
    }


async def authority_counts(factory: Factory) -> dict[str, int]:
    async with factory() as session:
        deltas = (await session.execute(select(func.count()).select_from(CanonDeltaModel))).scalar_one()
        versions = (await session.execute(select(func.count()).select_from(CanonVersionModel))).scalar_one()
        projections = (
            await session.execute(select(func.count()).select_from(CanonResolvedProjectionModel))
        ).scalar_one()
    return {"deltas": int(deltas), "versions": int(versions), "projections": int(projections)}


async def delete_projection(factory: Factory, version_id: str) -> None:
    async with factory() as session:
        await session.execute(
            delete(CanonResolvedProjectionModel).where(CanonResolvedProjectionModel.canon_version_id == version_id)
        )
        await session.commit()


async def corrupt_projection_hash(factory: Factory, version_id: str) -> None:
    async with factory() as session:
        await session.execute(
            update(CanonResolvedProjectionModel)
            .where(CanonResolvedProjectionModel.canon_version_id == version_id)
            .values(content_hash="tampered-projection-hash")
        )
        await session.commit()


async def corrupt_version_hash_version(factory: Factory, version_id: str) -> None:
    async with factory() as session:
        await session.execute(
            update(CanonVersionModel)
            .where(CanonVersionModel.canon_version_id == version_id)
            .values(content_hash_version="r2-canon-content-v2")
        )
        await session.commit()


async def tamper_delta_operations(factory: Factory, delta_id: str) -> None:
    async with factory() as session:
        await session.execute(
            update(CanonDeltaModel)
            .where(CanonDeltaModel.canon_delta_id == delta_id)
            .values(
                operations_json=[
                    {
                        "kind": "ADD_ENTITY",
                        "operation_id": "op-tampered",
                        "target_id": "tampered",
                        "entity": {
                            "entity_id": "tampered",
                            "entity_type": "CHARACTER",
                            "canonical_name": "Tampered",
                            "aliases": [],
                        },
                    }
                ]
            )
        )
        await session.commit()


async def break_version_parent(factory: Factory, version_id: str) -> None:
    async with factory() as session:
        await session.execute(
            update(CanonVersionModel)
            .where(CanonVersionModel.canon_version_id == version_id)
            .values(parent_version_id="ghost-parent")
        )
        await session.commit()


async def projection_row_count(factory: Factory, version_id: str) -> int:
    async with factory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(CanonResolvedProjectionModel)
            .where(CanonResolvedProjectionModel.canon_version_id == version_id)
        )
        return int(result.scalar_one())


async def branch_head(factory: Factory, branch_id: str) -> str | None:
    async with factory() as session:
        result = await session.execute(
            select(CanonBranchModel.head_version_id).where(CanonBranchModel.branch_id == branch_id)
        )
        return result.scalar_one_or_none()
