"""Projection unit-of-work lifecycle for CanonResolutionService."""

from __future__ import annotations

import inspect

import pytest

from lib.db.canon_uow import canon_projection_uow_factory
from r2.narrative.canon_resolution import CanonResolutionService
from r2.narrative.errors import CanonIntegrityError
from tests.integration.r2.narrative._canon_authority import (
    PROJECT,
    USER,
    Factory,
    commit_version,
    delete_projection,
    main_branch,
    projection_row_count,
    seed_main_genesis,
    tamper_delta_operations,
)


async def resolve(factory: Factory, *, branch_id: str, version_id: str | None = None):
    service = CanonResolutionService(canon_projection_uow_factory(factory))
    return await service.resolve(branch_id=branch_id, version_id=version_id, project_name=PROJECT, user_id=USER)


async def test_rebuilt_projection_is_durable_after_the_service_call(session_factory: Factory) -> None:
    await seed_main_genesis(session_factory)
    await delete_projection(session_factory, "main-v1")
    assert await projection_row_count(session_factory, "main-v1") == 0

    view = await resolve(session_factory, branch_id="main")

    assert await projection_row_count(session_factory, "main-v1") == 1
    async with canon_projection_uow_factory(session_factory)() as uow:
        stored = await uow.repository.load_projection(canon_version_id="main-v1", project_name=PROJECT, user_id=USER)
    assert stored is not None
    assert stored.content_hash == view.content_hash


async def test_service_call_rolls_back_every_rebuild_when_replay_fails(session_factory: Factory) -> None:
    _, main_content = await seed_main_genesis(session_factory, entity_id="parent-entity")
    await commit_version(
        session_factory,
        branch=main_branch(),
        base_content=main_content,
        base_version_id="main-v1",
        add_entity_id="second-entity",
        version_id="main-v2",
        version_number=2,
        parent_version_id="main-v1",
        delta_id="delta-main-2",
        approval_ref="approval-main-2",
    )
    await delete_projection(session_factory, "main-v1")
    await delete_projection(session_factory, "main-v2")
    await tamper_delta_operations(session_factory, "delta-main-2")

    with pytest.raises(CanonIntegrityError):
        await resolve(session_factory, branch_id="main")

    assert await projection_row_count(session_factory, "main-v1") == 0
    assert await projection_row_count(session_factory, "main-v2") == 0


def test_service_constructor_takes_only_a_projection_uow_factory() -> None:
    parameters = list(inspect.signature(CanonResolutionService.__init__).parameters)
    assert parameters == ["self", "projection_uow_factory", "clock"]
