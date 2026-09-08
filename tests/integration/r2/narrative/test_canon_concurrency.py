"""All-or-nothing fault injection, PostgreSQL-authoritative concurrency, and restart proof."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from lib.db.base import Base
from lib.db.canon_uow import canon_authority_uow_factory, canon_projection_uow_factory
from lib.db.models import register_models
from r2.contracts import CanonCommitResult
from r2.narrative.canon_resolution import CanonResolutionService
from r2.narrative.canon_transaction import CanonCommitStage, CanonTransactionService
from r2.narrative.errors import (
    CanonApprovalError,
    CanonBaseVersionConflict,
    CanonIdentityConflictError,
)
from tests.integration.r2.narrative._canon_authority import (
    NOW,
    PROJECT,
    USER,
    Factory,
    authority_snapshot,
    local_version_count,
    main_branch_command,
    make_approval,
    make_entity_delta,
    narrative_branch_command,
    seed_genesis_via_service,
    total_delta_count,
)


class InjectedCommitFailure(RuntimeError):
    pass


def transaction_service(
    factory: Factory,
    *,
    version_id: str,
    fault_hook: Callable[[CanonCommitStage], None] | None = None,
) -> CanonTransactionService:
    if fault_hook is None:
        return CanonTransactionService(
            canon_authority_uow_factory(factory), version_id_factory=iter([version_id]).__next__
        )
    return CanonTransactionService(
        canon_authority_uow_factory(factory),
        version_id_factory=iter([version_id]).__next__,
        fault_hook=fault_hook,
    )


async def commit_second_delta(service: CanonTransactionService, base_version_id: str) -> CanonCommitResult:
    delta = make_entity_delta("delta-2", "main", base_version_id, "villain")
    return await service.commit(
        delta=delta,
        approval=make_approval(delta, approval_ref="approval-2"),
        project_name=PROJECT,
        user_id=USER,
        now=NOW,
    )


@pytest.mark.parametrize("stage", list(CanonCommitStage))
async def test_fault_at_each_commit_boundary_preserves_prior_authority(
    session_factory: Factory, stage: CanonCommitStage
) -> None:
    base = await seed_genesis_via_service(session_factory)
    before = await authority_snapshot(session_factory)

    def fail_at(observed: CanonCommitStage) -> None:
        if observed is stage:
            raise InjectedCommitFailure(stage.value)

    service = transaction_service(session_factory, version_id="v2", fault_hook=fail_at)
    with pytest.raises(InjectedCommitFailure):
        await commit_second_delta(service, base)

    assert await authority_snapshot(session_factory) == before


async def test_same_base_concurrent_commits_have_exactly_one_winner(
    concurrent_session_factory: Factory,
) -> None:
    base = await seed_genesis_via_service(concurrent_session_factory)
    start = asyncio.Event()

    async def attempt(tag: str) -> object:
        await start.wait()
        service = transaction_service(concurrent_session_factory, version_id=f"v-{tag}")
        delta = make_entity_delta(f"delta-{tag}", "main", base, f"entity-{tag}")
        try:
            return await service.commit(
                delta=delta,
                approval=make_approval(delta, approval_ref=f"approval-{tag}"),
                project_name=PROJECT,
                user_id=USER,
                now=NOW,
            )
        except CanonBaseVersionConflict as exc:
            return exc

    tasks = [asyncio.create_task(attempt("a")), asyncio.create_task(attempt("b"))]
    start.set()
    outcomes = await asyncio.gather(*tasks)
    assert sorted(type(item).__name__ for item in outcomes) == [
        "CanonBaseVersionConflict",
        "CanonCommitResult",
    ]
    assert await local_version_count(concurrent_session_factory, "main") == 2


async def test_different_branches_commit_independently(concurrent_session_factory: Factory) -> None:
    base = await seed_genesis_via_service(concurrent_session_factory)
    bootstrap = CanonTransactionService(canon_authority_uow_factory(concurrent_session_factory))
    await bootstrap.create_branch(
        narrative_branch_command(branch_id="story", parent_branch_id="main", parent_version_id=base)
    )
    start = asyncio.Event()

    async def commit_on(branch_id: str, tag: str) -> object:
        await start.wait()
        service = transaction_service(concurrent_session_factory, version_id=f"v-{tag}")
        delta = make_entity_delta(f"delta-{tag}", branch_id, base, f"entity-{tag}")
        return await service.commit(
            delta=delta,
            approval=make_approval(delta, approval_ref=f"approval-{tag}"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )

    tasks = [
        asyncio.create_task(commit_on("main", "a")),
        asyncio.create_task(commit_on("story", "b")),
    ]
    start.set()
    outcomes = await asyncio.gather(*tasks)
    assert all(isinstance(item, CanonCommitResult) for item in outcomes)


async def test_racing_two_main_branch_creations_yields_one_conflict(
    concurrent_session_factory: Factory,
) -> None:
    start = asyncio.Event()

    async def create(branch_id: str) -> object:
        await start.wait()
        service = CanonTransactionService(canon_authority_uow_factory(concurrent_session_factory))
        try:
            return await service.create_branch(main_branch_command(branch_id=branch_id))
        except CanonIdentityConflictError as exc:
            return exc

    tasks = [asyncio.create_task(create("main-a")), asyncio.create_task(create("main-b"))]
    start.set()
    outcomes = await asyncio.gather(*tasks)
    assert sorted(type(item).__name__ for item in outcomes) == [
        "CanonBranchSnapshot",
        "CanonIdentityConflictError",
    ]


async def test_racing_the_same_approval_ref_on_different_branches(
    concurrent_session_factory: Factory,
) -> None:
    base = await seed_genesis_via_service(concurrent_session_factory)
    bootstrap = CanonTransactionService(canon_authority_uow_factory(concurrent_session_factory))
    await bootstrap.create_branch(
        narrative_branch_command(branch_id="story", parent_branch_id="main", parent_version_id=base)
    )
    start = asyncio.Event()

    async def commit_on(branch_id: str, tag: str) -> object:
        await start.wait()
        service = transaction_service(concurrent_session_factory, version_id=f"v-{tag}")
        delta = make_entity_delta(f"delta-{tag}", branch_id, base, f"entity-{tag}")
        try:
            return await service.commit(
                delta=delta,
                approval=make_approval(delta, approval_ref="shared-approval"),
                project_name=PROJECT,
                user_id=USER,
                now=NOW,
            )
        except CanonApprovalError as exc:
            return exc

    tasks = [
        asyncio.create_task(commit_on("main", "a")),
        asyncio.create_task(commit_on("story", "b")),
    ]
    start.set()
    outcomes = await asyncio.gather(*tasks)
    assert sorted(type(item).__name__ for item in outcomes) == [
        "CanonApprovalError",
        "CanonCommitResult",
    ]
    assert await total_delta_count(concurrent_session_factory) == 2


async def test_committed_head_survives_a_fresh_resolution_session(session_factory: Factory) -> None:
    base = await seed_genesis_via_service(session_factory)
    view = await CanonResolutionService(canon_projection_uow_factory(session_factory)).resolve(
        branch_id="main", version_id=None, project_name=PROJECT, user_id=USER
    )
    assert view.canon_version_id == base


@asynccontextmanager
async def _reopenable_engine(db_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=pool.NullPool)
    register_models()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.sqlite_only
async def test_committed_head_survives_an_engine_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "canon-restart.db"
    async with _reopenable_engine(db_path) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        service = CanonTransactionService(
            canon_authority_uow_factory(factory), version_id_factory=iter(["v1"]).__next__
        )
        await service.create_branch(main_branch_command())
        delta = make_entity_delta("delta-1", "main", None, "hero")
        result = await service.commit(
            delta=delta,
            approval=make_approval(delta, approval_ref="approval-1"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )
        committed_hash = result.version.content_hash

    async with _reopenable_engine(db_path) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        view = await CanonResolutionService(canon_projection_uow_factory(factory)).resolve(
            branch_id="main", version_id=None, project_name=PROJECT, user_id=USER
        )
    assert view.canon_version_id == "v1"
    assert view.content_hash == committed_hash
