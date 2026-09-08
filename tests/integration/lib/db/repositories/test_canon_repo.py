"""Integration coverage for the scoped Canon persistence adapter and unit of work."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import canon_authority_uow_factory, canon_projection_uow_factory
from lib.db.repositories.canon_repo import CanonProjectionRepository, CanonRepository
from r2.contracts import (
    AcceptedCanonDeltaSnapshot,
    AddEntityOperation,
    CanonBranchSnapshot,
    CanonBranchType,
    CanonCommitApproval,
    CanonDeltaPayload,
    CanonVersionSnapshot,
    Entity,
    EntityType,
)
from r2.narrative.canon_state import ResolvedCanonView, empty_canon_content
from r2.narrative.errors import (
    CanonApprovalError,
    CanonIdentityConflictError,
    CanonIntegrityError,
    CanonNotFoundError,
)
from r2.narrative.hashing import compute_canon_content_hash, seal_canon_delta

NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
# Seeded on PostgreSQL by tests/conftest.py::_PG_TEST_USER_IDS (users.id FK).
USER = "u1"
OTHER_USER = "conformance"
PROJECT = "project-a"

type Factory = async_sessionmaker[AsyncSession]


def branch_snapshot(
    *,
    branch_id: str = "main",
    user_id: str = USER,
    project_name: str = PROJECT,
    branch_type: CanonBranchType = CanonBranchType.MAIN,
    head: str | None = None,
) -> CanonBranchSnapshot:
    return CanonBranchSnapshot(
        branch_id=branch_id,
        user_id=user_id,
        project_name=project_name,
        branch_type=branch_type,
        parent_branch_id=None,
        parent_version_id=None,
        head_version_id=head,
        created_at=NOW,
        created_by="showrunner",
    )


def accepted_delta(
    *,
    delta_id: str = "delta-1",
    approval_ref: str = "approval-1",
    branch_id: str = "main",
    version_id: str = "version-1",
    user_id: str = USER,
    project_name: str = PROJECT,
) -> AcceptedCanonDeltaSnapshot:
    delta = seal_canon_delta(
        CanonDeltaPayload(
            canon_delta_id=delta_id,
            target_branch_id=branch_id,
            base_canon_version_id=None,
            operations=[
                AddEntityOperation(
                    operation_id="op-1",
                    target_id="e-1",
                    entity=Entity(entity_id="e-1", entity_type=EntityType.CHARACTER, canonical_name="Ada", aliases=[]),
                )
            ],
            source_change_set_refs=["s-1"],
            author_decision_refs=["a-1"],
            validation_report_refs=[],
            created_at=NOW,
            created_by="showrunner",
        )
    )
    approval = CanonCommitApproval(
        approval_ref=approval_ref,
        canon_delta_id=delta_id,
        payload_hash=delta.payload_hash,
        payload_hash_algorithm="sha256",
        payload_hash_version="r2-canon-delta-v1",
        content_schema_version="r2-canon-schema-v1",
        project_name=project_name,
        user_id=user_id,
        approved_by="approver",
        approved_at=NOW,
        status="APPROVED",
    )
    return AcceptedCanonDeltaSnapshot(delta=delta, approval=approval, committed_version_id=version_id)


def version_snapshot(
    *,
    version_id: str = "version-1",
    branch_id: str = "main",
    number: int = 1,
    parent: str | None = None,
    delta_id: str = "delta-1",
) -> CanonVersionSnapshot:
    content = empty_canon_content()
    return CanonVersionSnapshot(
        canon_version_id=version_id,
        branch_id=branch_id,
        version_number=number,
        parent_version_id=parent,
        committed_delta_id=delta_id,
        committed_at=NOW,
        committed_by="showrunner",
        content_hash=compute_canon_content_hash(content),
        content_hash_algorithm="sha256",
        content_hash_version="r2-canon-content-v1",
        content_schema_version="r2-canon-schema-v1",
    )


def empty_view(version_id: str = "version-1") -> ResolvedCanonView:
    content = empty_canon_content()
    return ResolvedCanonView(
        canon_version_id=version_id,
        branch_id="main",
        content_hash=compute_canon_content_hash(content),
        content=content,
    )


async def seed_branch(
    factory: Factory,
    *,
    branch_id: str = "main",
    user_id: str = USER,
    project_name: str = PROJECT,
    branch_type: CanonBranchType = CanonBranchType.MAIN,
) -> None:
    async with canon_authority_uow_factory(factory)() as uow:
        await uow.repository.insert_branch(
            branch_snapshot(branch_id=branch_id, user_id=user_id, project_name=project_name, branch_type=branch_type)
        )
        await uow.commit()


async def seed_full_version(factory: Factory) -> None:
    async with canon_authority_uow_factory(factory)() as uow:
        await uow.repository.insert_branch(branch_snapshot())
        await uow.repository.insert_delta(accepted_delta())
        await uow.repository.insert_version(version_snapshot())
        await uow.repository.advance_head(
            branch_id="main", expected_head_id=None, version_id="version-1", project_name=PROJECT, user_id=USER
        )
        await uow.commit()


async def test_repository_never_commits_its_bound_session(session_factory: Factory) -> None:
    async with session_factory() as session:
        repo = CanonRepository(session)
        await repo.insert_branch(branch_snapshot())
        assert session.in_transaction()
        await session.rollback()
    async with session_factory() as session:
        assert await CanonRepository(session).get_branch(branch_id="main", project_name=PROJECT, user_id=USER) is None


async def test_cross_scope_ids_are_indistinguishable_from_unknown(session_factory: Factory) -> None:
    await seed_branch(session_factory, user_id=USER, project_name="p-a")
    async with session_factory() as session:
        repo = CanonRepository(session)
        assert await repo.get_branch(branch_id="main", project_name="p-b", user_id=OTHER_USER) is None
        assert await repo.get_branch(branch_id="missing", project_name="p-b", user_id=OTHER_USER) is None


async def test_authority_uow_persists_branch_delta_version_and_head(session_factory: Factory) -> None:
    await seed_full_version(session_factory)
    async with session_factory() as session:
        repo = CanonRepository(session)
        branch = await repo.get_branch(branch_id="main", project_name=PROJECT, user_id=USER)
        assert branch is not None
        assert branch.head_version_id == "version-1"
        version = await repo.get_version(canon_version_id="version-1", project_name=PROJECT, user_id=USER)
        assert version is not None
        assert version.version_number == 1
        delta = await repo.get_accepted_delta(canon_delta_id="delta-1", project_name=PROJECT, user_id=USER)
        assert delta is not None
        assert delta.committed_version_id == "version-1"
        by_ref = await repo.get_accepted_delta_by_approval_ref(
            approval_ref="approval-1", project_name=PROJECT, user_id=USER
        )
        assert by_ref is not None
        assert by_ref.delta.canon_delta_id == "delta-1"
        versions = await repo.list_branch_versions(branch_id="main", project_name=PROJECT, user_id=USER)
        assert [item.canon_version_id for item in versions] == ["version-1"]
        branches = await repo.list_scope_branches(project_name=PROJECT, user_id=USER)
        assert [item.branch_id for item in branches] == ["main"]


async def test_advance_head_rejects_a_stale_expected_head(session_factory: Factory) -> None:
    await seed_full_version(session_factory)
    async with canon_authority_uow_factory(session_factory)() as uow:
        with pytest.raises(CanonIntegrityError):
            await uow.repository.advance_head(
                branch_id="main",
                expected_head_id=None,
                version_id="version-2",
                project_name=PROJECT,
                user_id=USER,
            )


async def test_projection_upsert_then_load_round_trips(session_factory: Factory) -> None:
    await seed_full_version(session_factory)
    async with canon_authority_uow_factory(session_factory)() as uow:
        assert (
            await uow.repository.load_projection(canon_version_id="version-1", project_name=PROJECT, user_id=USER)
            is None
        )
        await uow.repository.upsert_projection(view=empty_view(), built_at=NOW, project_name=PROJECT, user_id=USER)
        await uow.commit()
    async with canon_projection_uow_factory(session_factory)() as uow:
        loaded = await uow.repository.load_projection(canon_version_id="version-1", project_name=PROJECT, user_id=USER)
        assert loaded is not None
        assert loaded.content_hash == empty_view().content_hash


async def test_projection_upsert_rejects_an_unknown_version(session_factory: Factory) -> None:
    await seed_branch(session_factory)
    async with canon_authority_uow_factory(session_factory)() as uow:
        with pytest.raises(CanonNotFoundError):
            await uow.repository.upsert_projection(
                view=empty_view("ghost"), built_at=NOW, project_name=PROJECT, user_id=USER
            )


async def _commit_delta(factory: Factory, accepted: AcceptedCanonDeltaSnapshot) -> None:
    async with canon_authority_uow_factory(factory)() as uow:
        await uow.repository.insert_delta(accepted)
        await uow.commit()


async def _commit_branch(factory: Factory, branch: CanonBranchSnapshot) -> None:
    async with canon_authority_uow_factory(factory)() as uow:
        await uow.repository.insert_branch(branch)
        await uow.commit()


async def test_duplicate_approval_ref_is_rejected_by_the_database_constraint(
    session_factory: Factory,
) -> None:
    await seed_full_version(session_factory)
    duplicate = accepted_delta(delta_id="delta-2", approval_ref="approval-1", version_id="version-1")
    with pytest.raises(CanonApprovalError):
        await _commit_delta(session_factory, duplicate)


async def test_second_main_branch_in_one_scope_is_rejected_by_the_partial_unique_index(
    session_factory: Factory,
) -> None:
    await seed_branch(session_factory, branch_id="main")
    second_main = branch_snapshot(branch_id="main-2", branch_type=CanonBranchType.MAIN)
    with pytest.raises(CanonIdentityConflictError):
        await _commit_branch(session_factory, second_main)


async def test_projection_uow_repository_has_no_authority_methods(session_factory: Factory) -> None:
    async with canon_projection_uow_factory(session_factory)() as uow:
        assert isinstance(uow.repository, CanonProjectionRepository)
        assert not isinstance(uow.repository, CanonRepository)
        for method in ("insert_delta", "insert_version", "advance_head", "lock_branch", "insert_branch"):
            assert not hasattr(uow.repository, method)


async def test_each_uow_call_creates_a_fresh_session(session_factory: Factory) -> None:
    factory = canon_authority_uow_factory(session_factory)
    async with factory() as first:
        first_session = first.session
    async with factory() as second:
        assert second.session is not first_session


async def _upsert_then_raise(factory: Factory) -> None:
    async with canon_projection_uow_factory(factory)() as uow:
        await uow.repository.upsert_projection(view=empty_view(), built_at=NOW, project_name=PROJECT, user_id=USER)
        raise RuntimeError("boom")


async def test_projection_uow_rolls_back_when_the_block_raises(session_factory: Factory) -> None:
    await seed_full_version(session_factory)
    with pytest.raises(RuntimeError):
        await _upsert_then_raise(session_factory)
    async with canon_projection_uow_factory(session_factory)() as uow:
        assert (
            await uow.repository.load_projection(canon_version_id="version-1", project_name=PROJECT, user_id=USER)
            is None
        )
