"""Scoped registry reads rehash stored target bodies and exact Scene dependencies."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.production_target import ProductionTargetHeadModel, ProductionTargetVersionModel
from lib.db.repositories.production_target import ProductionTargetIntegrityError, ProductionTargetRepository
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.enums import ProductionBindingTarget
from r2.contracts.production import ShotSpecV2
from r2.target_registry.digests import target_body_digest, target_version_digest

FIXTURE = Path(__file__).resolve().parents[4] / "fixtures/r2/m8c_target_registry_vectors.json"
type Factory = async_sessionmaker[AsyncSession]


def _cases() -> dict[str, dict]:
    return {case["name"]: case for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]}


async def _seed_bundle(session: AsyncSession) -> tuple[AdmittedScreenplayRef, dict[str, dict]]:
    cases = _cases()
    admitted = AdmittedScreenplayRef.model_validate(cases["scene_version_v1"]["body"]["admitted_screenplay_ref"])
    for kind in ("scene", "shot"):
        version_case = cases[f"{kind}_version_v1"]
        body = version_case["body"]
        head = ProductionTargetHeadModel(
            user_id=body["user_id"],
            project_name=body["project_name"],
            target_type=body["target_type"],
            target_id=body["target_id"],
            current_version=None,
            current_version_digest=None,
        )
        session.add(head)
        await session.flush()
        dependency = body["scene_dependency"]
        session.add(
            ProductionTargetVersionModel(
                user_id=body["user_id"],
                project_name=body["project_name"],
                target_type=body["target_type"],
                target_id=body["target_id"],
                registry_version=body["registry_version"],
                target_body_json=cases[f"{kind}_body_v1"]["body"]["target"],
                target_body_digest=body["target_body_digest"],
                admitted_screenplay_ref_json=body["admitted_screenplay_ref"],
                take_derivation_version=body["take_derivation_version"],
                version_digest=version_case["digest"],
                scene_target_type=None if dependency is None else dependency["target_type"],
                scene_target_id=None if dependency is None else dependency["target_id"],
                scene_registry_version=None if dependency is None else dependency["registry_version"],
                scene_version_digest=None if dependency is None else dependency["target_version_digest"],
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()
        head.current_version = body["registry_version"]
        head.current_version_digest = version_case["digest"]
        await session.flush()
    return admitted, cases


async def test_target_registry_current_read_is_scoped_and_rehashed(session_factory: Factory) -> None:
    async with session_factory() as session:
        admitted, cases = await _seed_bundle(session)
        repo = ProductionTargetRepository(session)
        for kind in ("scene", "shot"):
            body = cases[f"{kind}_version_v1"]["body"]
            verified = await repo.get_current_verified(
                user_id="u1",
                project_name="project-a",
                target_type=body["target_type"],
                target_id=body["target_id"],
                expected_admission=admitted,
            )
            assert verified is not None
            assert verified.ref.version_digest == cases[f"{kind}_version_v1"]["digest"]
            assert verified.admitted_screenplay_ref == admitted
            assert (
                await repo.get_current_verified(
                    user_id="u1",
                    project_name="foreign",
                    target_type=body["target_type"],
                    target_id=body["target_id"],
                    expected_admission=admitted,
                )
                is None
            )


@pytest.mark.parametrize("tamper", ["body", "body_digest", "version_digest", "head_digest", "scene_link", "admission"])
async def test_target_registry_current_read_rejects_corrupt_rows(session_factory: Factory, tamper: str) -> None:
    async with session_factory() as session:
        admitted, cases = await _seed_bundle(session)
        shot_body = cases["shot_version_v1"]["body"]
        head = await session.get(ProductionTargetHeadModel, ("u1", "project-a", "SHOT", shot_body["target_id"]))
        version = await session.get(
            ProductionTargetVersionModel, ("u1", "project-a", "SHOT", shot_body["target_id"], 1)
        )
        assert head is not None
        assert version is not None
        if tamper == "body":
            version.target_body_json = version.target_body_json | {"purpose": "altered"}
        elif tamper == "body_digest":
            version.target_body_digest = "sha256:" + "f" * 64
        elif tamper == "version_digest":
            version.version_digest = "sha256:" + "f" * 64
        elif tamper == "head_digest":
            head.current_version_digest = "sha256:" + "f" * 64
        elif tamper == "scene_link":
            version.scene_version_digest = "sha256:" + "f" * 64
        else:
            version.admitted_screenplay_ref_json = version.admitted_screenplay_ref_json | {
                "screenplay_ref": version.admitted_screenplay_ref_json["screenplay_ref"]
                | {"content_hash": "sha256:" + "f" * 64}
            }
        await session.flush()
        with pytest.raises(ProductionTargetIntegrityError, match="integrity"):
            await ProductionTargetRepository(session).get_current_verified(
                user_id="u1",
                project_name="project-a",
                target_type="SHOT",
                target_id=shot_body["target_id"],
                expected_admission=admitted,
            )


async def test_shot_read_rejects_changed_hint_after_identity_map_refresh(
    session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with session_factory() as session:
        admitted, cases = await _seed_bundle(session)
        repo = ProductionTargetRepository(session)
        shot_case = cases["shot_version_v1"]
        shot_body = shot_case["body"]
        changed_target = ShotSpecV2.model_validate(cases["shot_body_v1"]["body"]["target"]).model_copy(
            update={"purpose": "changed after the hint"}
        )
        changed_body_digest = target_body_digest("SHOT", changed_target)
        changed_version_digest = target_version_digest(shot_body | {"target_body_digest": changed_body_digest})
        original_head = repo._head
        changed = False

        async def change_after_hint(
            *, user_id: str, project_name: str, target_type: ProductionBindingTarget, target_id: str, lock: bool
        ) -> ProductionTargetHeadModel | None:
            nonlocal changed
            if lock and target_type == ProductionBindingTarget.SCENE and not changed:
                changed = True
                await session.execute(
                    update(ProductionTargetVersionModel)
                    .where(
                        ProductionTargetVersionModel.user_id == "u1",
                        ProductionTargetVersionModel.project_name == "project-a",
                        ProductionTargetVersionModel.target_type == "SHOT",
                        ProductionTargetVersionModel.target_id == shot_body["target_id"],
                        ProductionTargetVersionModel.registry_version == 1,
                    )
                    .values(
                        target_body_json=changed_target.model_dump(mode="json"),
                        target_body_digest=changed_body_digest,
                        version_digest=changed_version_digest,
                    )
                    .execution_options(synchronize_session=False)
                )
                await session.execute(
                    update(ProductionTargetHeadModel)
                    .where(
                        ProductionTargetHeadModel.user_id == "u1",
                        ProductionTargetHeadModel.project_name == "project-a",
                        ProductionTargetHeadModel.target_type == "SHOT",
                        ProductionTargetHeadModel.target_id == shot_body["target_id"],
                    )
                    .values(current_version_digest=changed_version_digest)
                    .execution_options(synchronize_session=False)
                )
            return await original_head(
                user_id=user_id,
                project_name=project_name,
                target_type=target_type,
                target_id=target_id,
                lock=lock,
            )

        monkeypatch.setattr(repo, "_head", change_after_hint)
        with pytest.raises(ProductionTargetIntegrityError, match="changed after its untrusted scene hint"):
            await repo.get_current_verified(
                user_id="u1",
                project_name="project-a",
                target_type="SHOT",
                target_id=shot_body["target_id"],
                expected_admission=admitted,
            )
        assert changed


async def test_target_head_must_name_latest_stored_version(session_factory: Factory) -> None:
    async with session_factory() as session:
        admitted, cases = await _seed_bundle(session)
        body = cases["scene_version_v2"]["body"]
        session.add(
            ProductionTargetVersionModel(
                user_id=body["user_id"],
                project_name=body["project_name"],
                target_type=body["target_type"],
                target_id=body["target_id"],
                registry_version=body["registry_version"],
                target_body_json=cases["scene_body_v2"]["body"]["target"],
                target_body_digest=body["target_body_digest"],
                admitted_screenplay_ref_json=body["admitted_screenplay_ref"],
                take_derivation_version=body["take_derivation_version"],
                version_digest=cases["scene_version_v2"]["digest"],
                scene_target_type=None,
                scene_target_id=None,
                scene_registry_version=None,
                scene_version_digest=None,
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()
        with pytest.raises(ProductionTargetIntegrityError, match="not latest"):
            await ProductionTargetRepository(session).get_current_verified(
                user_id="u1",
                project_name="project-a",
                target_type="SCENE",
                target_id=body["target_id"],
                expected_admission=admitted,
            )
