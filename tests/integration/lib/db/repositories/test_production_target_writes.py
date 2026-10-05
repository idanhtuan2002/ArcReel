"""Target registry writes and receipts share the caller's transaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_target import (
    ProductionTargetCommandModel,
    ProductionTargetHeadModel,
    ProductionTargetVersionModel,
)
from lib.db.repositories.production_target import (
    ProductionTargetCommandConflictError,
    ProductionTargetIntegrityError,
    ProductionTargetRepository,
)
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_target import TargetRegistrationResultBody, TargetVersionBody
from r2.target_registry.digests import registration_result_digest

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_target_registry_vectors.json"
type Factory = async_sessionmaker[AsyncSession]


def _cases() -> dict[str, dict]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


def _result() -> TargetRegistrationResultBody:
    return TargetRegistrationResultBody.model_validate(_cases()["registration_result_v1"]["body"])


@pytest.mark.parametrize("tamper", ["result_json", "result_digest", "command_digest"])
async def test_receipt_round_trip_scope_conflict_and_corruption(session_factory: Factory, tamper: str) -> None:
    result = _result()
    async with session_factory() as session:
        repo = ProductionTargetRepository(session)
        assert (
            await repo.get_command_receipt(
                user_id="u1",
                project_name="project-a",
                principal="operator",
                command_id="cmd-1",
                expected_command_digest=result.command_digest,
            )
            is None
        )
        await repo.record_command(
            user_id="u1", project_name="project-a", principal="operator", command_id="cmd-1", result=result
        )
        receipt = await repo.get_command_receipt(
            user_id="u1",
            project_name="project-a",
            principal="operator",
            command_id="cmd-1",
            expected_command_digest=result.command_digest,
        )
        assert receipt is not None
        assert receipt.result_digest == registration_result_digest(result)
        assert receipt.scene_targets == result.scene_targets
        assert (
            await repo.get_command_receipt(
                user_id="u1",
                project_name="other",
                principal="operator",
                command_id="cmd-1",
                expected_command_digest=result.command_digest,
            )
            is None
        )
        with pytest.raises(ProductionTargetCommandConflictError):
            await repo.get_command_receipt(
                user_id="u1",
                project_name="project-a",
                principal="operator",
                command_id="cmd-1",
                expected_command_digest="sha256:" + "f" * 64,
            )
        changed = {
            "result_json": {"result_json": result.model_dump(mode="json") | {"scene_targets": []}},
            "result_digest": {"result_digest": "sha256:" + "f" * 64},
            "command_digest": {"command_digest": "sha256:" + "f" * 64},
        }[tamper]
        await session.execute(
            update(ProductionTargetCommandModel)
            .where(ProductionTargetCommandModel.command_id == "cmd-1")
            .values(**changed)
        )
        with pytest.raises(ProductionTargetIntegrityError):
            await repo.get_command_receipt(
                user_id="u1",
                project_name="project-a",
                principal="operator",
                command_id="cmd-1",
                expected_command_digest=result.command_digest,
            )


async def test_scene_then_shot_write_and_rollback(session_factory: Factory) -> None:
    cases = _cases()
    admission = AdmittedScreenplayRef.model_validate(cases["scene_version_v1"]["body"]["admitted_screenplay_ref"])
    async with session_factory() as session:
        repo = ProductionTargetRepository(session)
        for kind in ("scene", "shot"):
            body = TargetVersionBody.model_validate(cases[f"{kind}_version_v1"]["body"])
            target = (SceneSpec if kind == "scene" else ShotSpecV2).model_validate(
                cases[f"{kind}_body_v1"]["body"]["target"]
            )
            head = await repo.lock_target_head(
                user_id="u1", project_name="project-a", target_type=body.target_type, target_id=body.target_id
            )
            assert head.current_version is None
            ref = await repo.append_version(head=head, body=body, target=target)
            await repo.advance_head(head=head, expected_version=None, expected_digest=None, new_ref=ref)
            verified = await repo.get_current_verified(
                user_id="u1",
                project_name="project-a",
                target_type=body.target_type,
                target_id=body.target_id,
                expected_admission=admission,
            )
            assert verified is not None
            assert verified.ref == ref
        assert await session.scalar(select(func.count()).select_from(ProductionTargetHeadModel)) == 2
        await repo.record_command(
            user_id="u1", project_name="project-a", principal="operator", command_id="cmd-1", result=_result()
        )
        assert await session.scalar(select(func.count()).select_from(ProductionTargetCommandModel)) == 1
        await session.rollback()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProductionTargetHeadModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 0
        assert await session.scalar(select(func.count()).select_from(ProductionTargetCommandModel)) == 0


async def test_head_advance_rejects_wrong_predecessor(session_factory: Factory) -> None:
    async with session_factory() as session:
        head = await ProductionTargetRepository(session).lock_target_head(
            user_id="u1", project_name="project-a", target_type="SCENE", target_id="scene-1"
        )
        with pytest.raises(ProductionTargetIntegrityError):
            await ProductionTargetRepository(session).advance_head(
                head=head,
                expected_version=1,
                expected_digest="sha256:" + "f" * 64,
                new_ref=_result().scene_targets[0],
            )


async def test_next_admission_advances_registry_versions_and_preserves_history(session_factory: Factory) -> None:
    cases = _cases()
    async with session_factory() as session:
        repo = ProductionTargetRepository(session)
        for generation in (1, 2):
            admitted = AdmittedScreenplayRef.model_validate(
                cases[f"scene_version_v{generation}"]["body"]["admitted_screenplay_ref"]
            )
            for kind in ("scene", "shot"):
                body = TargetVersionBody.model_validate(cases[f"{kind}_version_v{generation}"]["body"])
                target = (SceneSpec if kind == "scene" else ShotSpecV2).model_validate(
                    cases[f"{kind}_body_v{generation}"]["body"]["target"]
                )
                head = await repo.lock_target_head(
                    user_id="u1", project_name="project-a", target_type=body.target_type, target_id=body.target_id
                )
                previous_version, previous_digest = head.current_version, head.current_version_digest
                ref = await repo.append_version(head=head, body=body, target=target)
                await repo.advance_head(
                    head=head, expected_version=previous_version, expected_digest=previous_digest, new_ref=ref
                )
                current = await repo.get_current_verified(
                    user_id="u1",
                    project_name="project-a",
                    target_type=body.target_type,
                    target_id=body.target_id,
                    expected_admission=admitted,
                )
                assert current is not None
                assert current.ref.registry_version == generation
                assert current.ref.version_digest == cases[f"{kind}_version_v{generation}"]["digest"]
                assert current.target.version == 1
        assert await session.scalar(select(func.count()).select_from(ProductionTargetVersionModel)) == 4
