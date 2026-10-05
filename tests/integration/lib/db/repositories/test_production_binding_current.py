"""Current binding reads require a complete locked head and latest verified version."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_binding import (
    ProductionBindingCommandModel,
    ProductionBindingHeadModel,
    ProductionBindingVersionModel,
)
from lib.db.repositories.production_binding import ProductionBindingIntegrityError, ProductionBindingRepository
from r2.contracts.preparation import ProductionBinding
from r2.contracts.production_binding_authority import BindingCreateResultV1, BindingEnvelopeV1
from r2.contracts.production_target import TargetVersionRef

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_location_binding_v1_vectors.json"
type Factory = async_sessionmaker[AsyncSession]


def _cases() -> dict[str, dict[str, Any]]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


def _refs() -> tuple[TargetVersionRef, TargetVersionRef]:
    envelope = _cases()["binding_envelope"]["body"]
    return (
        TargetVersionRef.model_validate(envelope["target_ref"]),
        TargetVersionRef.model_validate(envelope["scene_ref"]),
    )


async def _seed(session: AsyncSession) -> tuple[ProductionBindingHeadModel, ProductionBindingVersionModel]:
    cases = _cases()
    body = cases["binding_body"]["body"]
    envelope = cases["binding_envelope"]["body"]
    head = ProductionBindingHeadModel(
        user_id="u1", project_name="demo", binding_id=body["id"], current_version=None, current_envelope_digest=None
    )
    session.add(head)
    await session.flush()
    version = ProductionBindingVersionModel(
        user_id="u1",
        project_name="demo",
        binding_id=body["id"],
        binding_version=1,
        binding_body_json=body,
        binding_body_digest=cases["binding_body"]["digest"],
        envelope_json=envelope,
        envelope_digest=cases["binding_envelope"]["digest"],
        target_type="SHOT",
        target_id=envelope["target_ref"]["target_id"],
        target_registry_version=envelope["target_ref"]["registry_version"],
        target_version_digest=envelope["target_ref"]["version_digest"],
        scene_type="SCENE",
        scene_id=envelope["scene_ref"]["target_id"],
        scene_registry_version=envelope["scene_ref"]["registry_version"],
        scene_version_digest=envelope["scene_ref"]["version_digest"],
        receipt_a_id=body["asset_refs"][0],
        receipt_b_id=body["asset_refs"][1],
        created_at=datetime.now(UTC),
    )
    session.add(version)
    await session.flush()
    head.current_version = 1
    head.current_envelope_digest = cases["binding_envelope"]["digest"]
    await session.flush()
    return head, version


async def _fail_after_append(session: AsyncSession, body: ProductionBinding, envelope: BindingEnvelopeV1) -> None:
    async with session.begin():
        repo = ProductionBindingRepository(session)
        head = await repo.lock_binding_head(user_id="u1", project_name="demo", binding_id=body.id)
        await repo.append_first_version(head=head, body=body, envelope=envelope)
        raise RuntimeError("forced after append")


async def test_current_binding_read_is_scoped_and_rehashes_row(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vectors have no registered target and frame foreign-key rows")
        head, _ = await _seed(session)
        target, scene = _refs()
        repo = ProductionBindingRepository(session)
        verified = await repo.get_current_verified(
            user_id="u1",
            project_name="demo",
            binding_id=head.binding_id,
            expected_target_ref=target,
            expected_scene_ref=scene,
        )
        assert verified is not None
        assert verified.envelope_digest == head.current_envelope_digest
        assert (
            await repo.get_current_verified(
                user_id="u1",
                project_name="other",
                binding_id=head.binding_id,
                expected_target_ref=target,
                expected_scene_ref=scene,
            )
            is None
        )


@pytest.mark.parametrize("tamper", ["head_digest", "body", "latest", "genesis"])
async def test_current_binding_read_rejects_head_or_version_drift(session_factory: Factory, tamper: str) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vectors have no registered target and frame foreign-key rows")
        head, version = await _seed(session)
        if tamper == "head_digest":
            head.current_envelope_digest = "sha256:" + "f" * 64
        elif tamper == "body":
            version.binding_body_json = version.binding_body_json | {"semantic_ref": "location:changed"}
        elif tamper == "latest":
            session.add(
                ProductionBindingVersionModel(
                    **{
                        column.name: getattr(version, column.name)
                        for column in version.__table__.columns
                        if column.name != "binding_version"
                    },
                    binding_version=2,
                )
            )
        else:
            head.current_version = None
            head.current_envelope_digest = None
        await session.flush()
        target, scene = _refs()
        with pytest.raises(ProductionBindingIntegrityError, match=r"binding head integrity|binding version integrity"):
            await ProductionBindingRepository(session).get_current_verified(
                user_id="u1",
                project_name="demo",
                binding_id=head.binding_id,
                expected_target_ref=target,
                expected_scene_ref=scene,
            )


async def test_first_binding_append_and_head_cas_share_caller_transaction(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vectors have no registered target and frame foreign-key rows")
        cases = _cases()
        body = ProductionBinding.model_validate(cases["binding_body"]["body"])
        envelope = BindingEnvelopeV1.model_validate(cases["binding_envelope"]["body"])
        target, scene = _refs()
        repo = ProductionBindingRepository(session)
        head = await repo.lock_binding_head(user_id="u1", project_name="demo", binding_id=body.id)
        assert head.current_version is None
        version = await repo.append_first_version(head=head, body=body, envelope=envelope)
        await repo.advance_first_head(head=head, version=version, expected_target_ref=target, expected_scene_ref=scene)
        verified = await repo.get_current_verified(
            user_id="u1",
            project_name="demo",
            binding_id=body.id,
            expected_target_ref=target,
            expected_scene_ref=scene,
        )
        assert verified is not None
        with pytest.raises(ProductionBindingIntegrityError, match="already current"):
            await repo.lock_binding_head(user_id="u1", project_name="demo", binding_id=body.id)


async def test_failed_first_binding_append_rolls_back_head_and_version(session_factory: Factory) -> None:
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("synthetic vectors have no registered target and frame foreign-key rows")
        cases = _cases()
        body = ProductionBinding.model_validate(cases["binding_body"]["body"])
        envelope = BindingEnvelopeV1.model_validate(cases["binding_envelope"]["body"])
        with pytest.raises(RuntimeError, match="forced after append"):
            await _fail_after_append(session, body, envelope)
        assert await session.scalar(select(func.count()).select_from(ProductionBindingHeadModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductionBindingVersionModel)) == 0


@pytest.mark.parametrize("tamper", ["result_json", "result_digest", "command_digest"])
async def test_binding_command_receipt_rehashes_and_rejects_changed_input(
    session_factory: Factory, tamper: str
) -> None:
    cases = _cases()
    result = BindingCreateResultV1.model_validate(cases["binding_create_result"]["body"])
    async with session_factory() as session:
        repo = ProductionBindingRepository(session)
        assert (
            await repo.get_command_receipt(
                user_id="u1",
                project_name="demo",
                principal="user:u1",
                command_id="cmd-location-1",
                expected_command_digest=result.command_digest,
            )
            is None
        )
        recorded = await repo.record_command(
            user_id="u1",
            project_name="demo",
            principal="user:u1",
            command_id="cmd-location-1",
            result=result,
        )
        assert recorded.result_digest == cases["binding_create_result"]["digest"]
        exact = await repo.get_command_receipt(
            user_id="u1",
            project_name="demo",
            principal="user:u1",
            command_id="cmd-location-1",
            expected_command_digest=result.command_digest,
        )
        assert exact == recorded
        with pytest.raises(ProductionBindingIntegrityError, match="command ID has different input"):
            await repo.get_command_receipt(
                user_id="u1",
                project_name="demo",
                principal="user:u1",
                command_id="cmd-location-1",
                expected_command_digest="sha256:" + "f" * 64,
            )
        row = await session.get(ProductionBindingCommandModel, ("u1", "demo", "user:u1", "cmd-location-1"))
        assert row is not None
        if tamper == "result_json":
            row.result_json = row.result_json | {"binding_version": 2}
        elif tamper == "result_digest":
            row.result_digest = "sha256:" + "f" * 64
        else:
            row.command_digest = "sha256:" + "f" * 64
        await session.flush()
        with pytest.raises(ProductionBindingIntegrityError, match="receipt integrity"):
            await repo.get_command_receipt(
                user_id="u1",
                project_name="demo",
                principal="user:u1",
                command_id="cmd-location-1",
                expected_command_digest=result.command_digest,
            )
