"""Replay, pinned ancestry, and projection recovery for the Canon resolver."""

from __future__ import annotations

import asyncio

import pytest

from lib.db.canon_uow import canon_projection_uow_factory
from r2.narrative.canon_resolution import CanonResolutionService
from r2.narrative.canon_resolver import CanonResolver
from r2.narrative.errors import CanonIntegrityError, CanonNotFoundError
from tests.integration.r2.narrative._canon_authority import (
    PROJECT,
    USER,
    Factory,
    commit_version,
    corrupt_projection_hash,
    corrupt_version_hash_version,
    delete_projection,
    main_branch,
    narrative_branch,
    projection_row_count,
    seed_main_genesis,
    seed_pinned_child,
    tamper_delta_operations,
)


async def resolve(factory: Factory, *, branch_id: str, version_id: str | None = None):
    service = CanonResolutionService(canon_projection_uow_factory(factory))
    return await service.resolve(branch_id=branch_id, version_id=version_id, project_name=PROJECT, user_id=USER)


async def add_main_v2(factory: Factory, main_content, *, entity_id: str = "main-extra"):
    return await commit_version(
        factory,
        branch=main_branch(),
        base_content=main_content,
        base_version_id="main-v1",
        add_entity_id=entity_id,
        version_id="main-v2",
        version_number=2,
        parent_version_id="main-v1",
        delta_id="delta-main-2",
        approval_ref="approval-main-2",
    )


async def add_pinned_child(factory: Factory, main_content):
    return await commit_version(
        factory,
        branch=narrative_branch(parent_version_id="main-v1"),
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


async def test_main_genesis_replays_from_the_accepted_delta(session_factory: Factory) -> None:
    _, content = await seed_main_genesis(session_factory)
    await delete_projection(session_factory, "main-v1")
    view = await resolve(session_factory, branch_id="main")
    assert set(view.content.entities_by_id) == set(content.entities_by_id)
    assert view.canon_version_id == "main-v1"


async def test_narrative_version_one_replays_from_pinned_parent(session_factory: Factory) -> None:
    fixture = await seed_pinned_child(session_factory)
    await delete_projection(session_factory, "child-v1")
    view = await resolve(session_factory, branch_id="story")
    assert set(view.content.entities_by_id) == {"parent-entity", "child-entity"}
    assert view.canon_version_id == fixture["child_version_id"]
    assert view.content_hash == fixture["child_content_hash"]


async def test_parent_advance_does_not_change_pinned_child(session_factory: Factory) -> None:
    _, main_content = await seed_main_genesis(session_factory, entity_id="parent-entity")
    await add_pinned_child(session_factory, main_content)
    before = await resolve(session_factory, branch_id="story")
    await add_main_v2(session_factory, main_content)
    after = await resolve(session_factory, branch_id="story")
    assert after.model_dump(mode="json") == before.model_dump(mode="json")


async def test_missing_projection_is_rebuilt_and_persisted(session_factory: Factory) -> None:
    await seed_main_genesis(session_factory)
    await delete_projection(session_factory, "main-v1")
    first = await resolve(session_factory, branch_id="main")
    assert await projection_row_count(session_factory, "main-v1") == 1
    second = await resolve(session_factory, branch_id="main")
    assert second.model_dump(mode="json") == first.model_dump(mode="json")


async def test_corrupt_projection_is_replaced_by_a_rebuild(session_factory: Factory) -> None:
    _, content = await seed_main_genesis(session_factory)
    await resolve(session_factory, branch_id="main")
    await corrupt_projection_hash(session_factory, "main-v1")
    view = await resolve(session_factory, branch_id="main")
    assert set(view.content.entities_by_id) == set(content.entities_by_id)
    assert view.content_hash != "tampered-projection-hash"


async def test_matching_stored_projection_is_accepted_without_replay(session_factory: Factory) -> None:
    _, content = await seed_main_genesis(session_factory)
    first = await resolve(session_factory, branch_id="main")
    await tamper_delta_operations(session_factory, "delta-main-1")
    second = await resolve(session_factory, branch_id="main")
    assert second.model_dump(mode="json") == first.model_dump(mode="json")
    assert set(second.content.entities_by_id) == set(content.entities_by_id)


async def test_corrupt_authoritative_delta_fails_closed(session_factory: Factory) -> None:
    await seed_main_genesis(session_factory)
    await delete_projection(session_factory, "main-v1")
    await tamper_delta_operations(session_factory, "delta-main-1")
    with pytest.raises(CanonIntegrityError):
        await resolve(session_factory, branch_id="main")


async def test_unsupported_historical_hash_version_fails_closed(session_factory: Factory) -> None:
    await seed_main_genesis(session_factory)
    await delete_projection(session_factory, "main-v1")
    await corrupt_version_hash_version(session_factory, "main-v1")
    with pytest.raises(CanonIntegrityError):
        await resolve(session_factory, branch_id="main")


async def test_rebuilt_child_never_absorbs_a_later_parent_head(session_factory: Factory) -> None:
    _, main_content = await seed_main_genesis(session_factory, entity_id="parent-entity")
    await add_pinned_child(session_factory, main_content)
    baseline = await resolve(session_factory, branch_id="story")
    await add_main_v2(session_factory, main_content, entity_id="post-pin-entity")
    await delete_projection(session_factory, "child-v1")
    rebuilt = await resolve(session_factory, branch_id="story")
    assert "post-pin-entity" not in rebuilt.content.entities_by_id
    assert rebuilt.content_hash == baseline.content_hash


async def test_direct_resolver_reports_unknown_branch(session_factory: Factory) -> None:
    async with canon_projection_uow_factory(session_factory)() as uow:
        with pytest.raises(CanonNotFoundError):
            await CanonResolver(uow.repository).resolve(
                branch_id="missing", version_id=None, project_name=PROJECT, user_id=USER
            )


async def test_two_missing_projection_rebuilders_converge(concurrent_session_factory: Factory) -> None:
    await seed_main_genesis(concurrent_session_factory)
    await delete_projection(concurrent_session_factory, "main-v1")
    start = asyncio.Event()

    async def worker():
        await start.wait()
        return await resolve(concurrent_session_factory, branch_id="main")

    task_a = asyncio.create_task(worker())
    task_b = asyncio.create_task(worker())
    start.set()
    results = await asyncio.gather(task_a, task_b)
    assert results[0].model_dump(mode="json") == results[1].model_dump(mode="json")
    assert await projection_row_count(concurrent_session_factory, "main-v1") == 1
