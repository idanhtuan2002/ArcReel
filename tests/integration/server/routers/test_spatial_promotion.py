"""A typed spatial promotion turns one previewed constraint set into binding version N+1, atomically."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_binding import ProductionBindingVersionModel
from lib.db.models.spatial_pair import (
    SpatialConstraintSetModel,
    SpatialPreviewBindingModel,
    SpatialPromotionResultModel,
)
from lib.db.repositories.spatial_promotion import SpatialPromotionRepository
from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.errors import CommandConflictError, PromotionBindingStaleError
from r2.contracts.advanced_creative import PromotionAuthorization
from r2.contracts.spatial_promotion import SpatialPromotionPreviewV2, SpatialPromotionReceiptV2
from r2.production_binding.spatial_promotion import spatial_preview_v2_digest
from server.services.location_binding_snapshot import CurrentLocationBindingSnapshotReader
from server.services.spatial_promotion import SpatialPromotionService
from tests.integration.server.routers.spatial_approval_support import approved_location
from tests.integration.server.routers.test_gates_export import PROJECT, USER
from tests.integration.server.routers.test_spatial_promotion_preview import command, spatial_candidate

type Factory = async_sessionmaker[AsyncSession]


def _authorization(preview: SpatialPromotionPreviewV2, *, digest: str | None = None, command_id: str = "promote-1"):
    return PromotionAuthorization(
        command_id=command_id,
        project_name=PROJECT,
        preview_id=preview.base_preview.preview_id,
        preview_digest=digest or spatial_preview_v2_digest(preview.model_dump(mode="json")),
        actor_id=USER.id,
        actor_scope=USER.id,
        decision="APPROVE",
        authorized_at=datetime.now(UTC),
    )


async def _counts(factory: Factory) -> tuple[int, int, int]:
    async with factory() as session:
        return (
            await session.scalar(select(func.count()).select_from(ProductionBindingVersionModel)) or 0,
            await session.scalar(select(func.count()).select_from(SpatialConstraintSetModel)) or 0,
            await session.scalar(select(func.count()).select_from(SpatialPromotionResultModel)) or 0,
        )


async def _previewed(client, project_dir, factory, monkeypatch):
    approved = await approved_location(client, project_dir, factory, monkeypatch, shot_duration=5.0)
    ids = await spatial_candidate(factory, project_dir, approved)
    service = SpatialPromotionService(session_factory=factory, project_dir=project_dir, grants=approved.grants)
    preview = await service.create_preview(command(approved, ids))
    return approved, ids, service, preview


@pytest.mark.asyncio
async def test_promotion_appends_the_spatial_binding_version_and_replays(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved, ids, service, preview = await _previewed(gate_export_client, project_dir, session_factory, monkeypatch)

    authorization = _authorization(preview)
    receipt = await service.promote(
        user_id=USER.id, project_name=PROJECT, authorization=authorization, expected_candidate_head_version=1
    )

    assert receipt.result.binding_version == 2
    assert receipt.base_receipt.result_master_id is None
    assert await _counts(session_factory) == (2, 1, 1)
    snapshot = await CurrentLocationBindingSnapshotReader(
        session_factory=session_factory, project_dir=project_dir
    ).read_current(user_id=USER.id, project_name=PROJECT, target_id=approved.target_id)
    assert snapshot.body.ordered_bindings[0].version == 2
    assert snapshot.spatial_set == preview.binding.proposal

    again = await service.promote(
        user_id=USER.id, project_name=PROJECT, authorization=authorization, expected_candidate_head_version=1
    )
    assert again == receipt
    with pytest.raises(CommandConflictError):
        await service.promote(
            user_id=USER.id,
            project_name=PROJECT,
            authorization=authorization,
            expected_candidate_head_version=2,
        )
    with pytest.raises(PromotionBindingStaleError, match="pair approval"):
        await service.create_preview(command(approved, ids, expected_binding_version=2, command_id="preview-after"))
    assert await _counts(session_factory) == (2, 1, 1)


@pytest.mark.asyncio
async def test_an_authorization_naming_the_base_digest_is_refused(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved, _ids, service, preview = await _previewed(gate_export_client, project_dir, session_factory, monkeypatch)

    with pytest.raises(PromotionBindingStaleError):
        await service.promote(
            user_id=USER.id,
            project_name=PROJECT,
            authorization=_authorization(preview, digest=digest_canonical(preview.base_preview)),
            expected_candidate_head_version=1,
        )
    assert await _counts(session_factory) == (1, 0, 0)


@pytest.mark.asyncio
async def test_a_storage_failure_after_the_binding_write_rolls_back_every_row(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved, _ids, service, preview = await _previewed(gate_export_client, project_dir, session_factory, monkeypatch)

    class _FailingSidecars(SpatialPromotionRepository):
        async def stage_result(self, **_kwargs: object) -> SpatialPromotionReceiptV2:
            raise OSError("result sidecar storage unavailable")

    service = SpatialPromotionService(
        session_factory=session_factory,
        project_dir=project_dir,
        grants=_approved.grants,
        sidecars_for=_FailingSidecars,
    )
    with pytest.raises(OSError, match="sidecar storage"):
        await service.promote(
            user_id=USER.id,
            project_name=PROJECT,
            authorization=_authorization(preview),
            expected_candidate_head_version=1,
        )
    assert await _counts(session_factory) == (1, 0, 0)


@pytest.mark.asyncio
async def test_postgresql_refuses_a_binding_preview_or_receipt_without_its_sidecar(
    gate_export_client: AsyncClient, project_dir: Path, session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    if session_factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("deferred coupling triggers are PostgreSQL-only")
    _approved, _ids, service, preview = await _previewed(gate_export_client, project_dir, session_factory, monkeypatch)
    await service.promote(
        user_id=USER.id, project_name=PROJECT, authorization=_authorization(preview), expected_candidate_head_version=1
    )

    for model in (SpatialPromotionResultModel, SpatialPreviewBindingModel):
        async with session_factory() as session:
            await session.execute(delete(model))
            with pytest.raises(IntegrityError, match="spatial sidecars"):
                await session.commit()
    assert await _counts(session_factory) == (2, 1, 1)
