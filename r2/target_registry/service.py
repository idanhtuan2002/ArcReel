"""Atomic registration of Take-derived Scene and Shot registry versions."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import ConfigDict
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.adaptation_uow import SqlAlchemyAdaptationUnitOfWork
from lib.db.models.production_target import ProductionTargetHeadModel
from lib.db.repositories.production_target import (
    ProductionTargetIntegrityError,
    ProductionTargetRepository,
    VerifiedTargetVersion,
)
from r2.adaptation.screenplay_reader import TransactionBoundApprovedScreenplayReader
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.common import NonEmptyStr, R2ContractModel
from r2.contracts.enums import CreativeApprovalStatus, ProductionBindingTarget
from r2.contracts.production import SceneSpec, ShotSpecV2
from r2.contracts.production_target import (
    SceneVersionDependency,
    TargetRegistrationCommandBody,
    TargetRegistrationResult,
    TargetRegistrationResultBody,
    TargetVersionBody,
    TargetVersionRef,
)
from r2.production_intelligence.take_director import TAKE_DERIVATION_VERSION, TakeDirectionResult, TakeDirectorAdapter
from r2.target_registry.digests import registration_command_digest, target_body_digest

SessionFactory = Callable[[], AsyncSession]


class RegisterTakeTargetsCommand(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: NonEmptyStr
    project_name: NonEmptyStr
    principal: NonEmptyStr
    command_id: NonEmptyStr
    admitted_screenplay_ref: AdmittedScreenplayRef


def _ordered_bundle(result: object) -> tuple[tuple[SceneSpec, ...], tuple[ShotSpecV2, ...]]:
    if not isinstance(result, TakeDirectionResult):
        raise ProductionTargetIntegrityError("Take did not return a typed target bundle")
    scenes = tuple(sorted(result.scenes, key=lambda scene: scene.id))
    shots = tuple(sorted(result.shots, key=lambda shot: shot.id))
    scene_ids = {scene.id for scene in scenes}
    if (
        not scenes
        or not shots
        or len(scene_ids) != len(scenes)
        or len({shot.id for shot in shots}) != len(shots)
        or any(scene.approval_status != CreativeApprovalStatus.APPROVED for scene in scenes)
        or any(
            shot.approval_status != CreativeApprovalStatus.APPROVED or shot.scene_id not in scene_ids for shot in shots
        )
    ):
        raise ProductionTargetIntegrityError("Take target bundle is empty, duplicated, unapproved or orphaned")
    return scenes, shots


class TakeTargetRegistrationService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def register(self, command: RegisterTakeTargetsCommand) -> TargetRegistrationResult:
        command_body = TargetRegistrationCommandBody(
            user_id=command.user_id,
            project_name=command.project_name,
            principal=command.principal,
            admitted_screenplay_ref=command.admitted_screenplay_ref,
            take_derivation_version=TAKE_DERIVATION_VERSION,
        )
        digest = registration_command_digest(command_body)
        try:
            return await self._register_once(command, digest, require_receipt=False)
        except IntegrityError as original:
            try:
                return await self._register_once(command, digest, require_receipt=True)
            except _MissingWinnerReceipt:
                raise original from None

    async def _register_once(
        self, command: RegisterTakeTargetsCommand, digest: str, *, require_receipt: bool
    ) -> TargetRegistrationResult:
        async with SqlAlchemyAdaptationUnitOfWork(self._session_factory) as uow:
            repo = ProductionTargetRepository(uow.session)
            receipt = await repo.get_command_receipt(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                command_id=command.command_id,
                expected_command_digest=digest,
            )
            if require_receipt and receipt is None:
                raise _MissingWinnerReceipt
            reader = TransactionBoundApprovedScreenplayReader(
                uow.repository, expected_admission=command.admitted_screenplay_ref
            )
            direction = await TakeDirectorAdapter(
                reader, user_id=command.user_id, project_name=command.project_name
            ).direct(command.admitted_screenplay_ref)
            scenes, shots = _ordered_bundle(direction)
            if receipt is not None:
                await self._verify_replay(repo, command, receipt, scenes, shots)
                await uow.commit()
                return receipt

            heads: dict[tuple[ProductionBindingTarget, str], ProductionTargetHeadModel] = {}
            for kind, targets in ((ProductionBindingTarget.SCENE, scenes), (ProductionBindingTarget.SHOT, shots)):
                for target in targets:
                    heads[(kind, target.id)] = await repo.lock_target_head(
                        user_id=command.user_id,
                        project_name=command.project_name,
                        target_type=kind,
                        target_id=target.id,
                    )

            previous: dict[tuple[ProductionBindingTarget, str], VerifiedTargetVersion | None] = {}
            for kind, targets in ((ProductionBindingTarget.SCENE, scenes), (ProductionBindingTarget.SHOT, shots)):
                for target in targets:
                    head = heads[(kind, target.id)]
                    previous[(kind, target.id)] = (
                        None
                        if head.current_version is None
                        else await repo.get_current_verified(
                            user_id=command.user_id,
                            project_name=command.project_name,
                            target_type=kind,
                            target_id=target.id,
                            expected_admission=None,
                        )
                    )

            scene_refs: dict[str, TargetVersionRef] = {}
            shot_refs: list[TargetVersionRef] = []
            for scene in scenes:
                key = (ProductionBindingTarget.SCENE, scene.id)
                scene_refs[scene.id] = await self._select_version(
                    repo, command, heads[key], previous[key], scene, ProductionBindingTarget.SCENE, None
                )
            for shot in shots:
                key = (ProductionBindingTarget.SHOT, shot.id)
                scene_ref = scene_refs[shot.scene_id]
                old_scene = previous[(ProductionBindingTarget.SCENE, shot.scene_id)]
                old_scene_ref = None if old_scene is None else old_scene.ref
                shot_refs.append(
                    await self._select_version(
                        repo,
                        command,
                        heads[key],
                        previous[key],
                        shot,
                        ProductionBindingTarget.SHOT,
                        scene_ref,
                        old_scene_ref=old_scene_ref,
                    )
                )
            result = await repo.record_command(
                user_id=command.user_id,
                project_name=command.project_name,
                principal=command.principal,
                command_id=command.command_id,
                result=TargetRegistrationResultBody(
                    command_digest=digest,
                    scene_targets=tuple(scene_refs[scene.id] for scene in scenes),
                    shot_targets=tuple(shot_refs),
                ),
            )
            await uow.commit()
            return result

    @staticmethod
    async def _select_version(
        repo: ProductionTargetRepository,
        command: RegisterTakeTargetsCommand,
        head: ProductionTargetHeadModel,
        previous: VerifiedTargetVersion | None,
        target: SceneSpec | ShotSpecV2,
        kind: ProductionBindingTarget,
        scene_ref: TargetVersionRef | None,
        *,
        old_scene_ref: TargetVersionRef | None = None,
    ) -> TargetVersionRef:
        if (
            previous is not None
            and previous.target == target
            and previous.admitted_screenplay_ref == command.admitted_screenplay_ref
            and previous.take_derivation_version == TAKE_DERIVATION_VERSION
            and (kind == ProductionBindingTarget.SCENE or old_scene_ref == scene_ref)
        ):
            return previous.ref
        dependency = (
            None
            if scene_ref is None
            else SceneVersionDependency(
                target_type="SCENE",
                target_id=scene_ref.target_id,
                registry_version=scene_ref.registry_version,
                target_version_digest=scene_ref.version_digest,
            )
        )
        body = TargetVersionBody(
            user_id=command.user_id,
            project_name=command.project_name,
            registry_version=(head.current_version or 0) + 1,
            admitted_screenplay_ref=command.admitted_screenplay_ref,
            take_derivation_version=TAKE_DERIVATION_VERSION,
            target_type=kind,
            target_id=target.id,
            target_body_digest=target_body_digest(kind, target),
            scene_dependency=dependency,
        )
        ref = await repo.append_version(head=head, body=body, target=target)
        await repo.advance_head(
            head=head,
            expected_version=head.current_version,
            expected_digest=head.current_version_digest,
            new_ref=ref,
        )
        return ref

    @staticmethod
    async def _verify_replay(
        repo: ProductionTargetRepository,
        command: RegisterTakeTargetsCommand,
        receipt: TargetRegistrationResult,
        scenes: tuple[SceneSpec, ...],
        shots: tuple[ShotSpecV2, ...],
    ) -> None:
        for kind, targets, refs in (
            (ProductionBindingTarget.SCENE, scenes, receipt.scene_targets),
            (ProductionBindingTarget.SHOT, shots, receipt.shot_targets),
        ):
            if tuple(target.id for target in targets) != tuple(ref.target_id for ref in refs):
                raise ProductionTargetIntegrityError("replay target IDs disagree with the current Take bundle")
            for target, ref in zip(targets, refs, strict=True):
                current = await repo.get_current_verified(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    target_type=kind,
                    target_id=target.id,
                    expected_admission=command.admitted_screenplay_ref,
                )
                if (
                    current is None
                    or current.ref != ref
                    or current.target != target
                    or current.take_derivation_version != TAKE_DERIVATION_VERSION
                ):
                    raise ProductionTargetIntegrityError("replay result no longer names current Take target heads")


class _MissingWinnerReceipt(Exception):
    pass


__all__ = ["RegisterTakeTargetsCommand", "TakeTargetRegistrationService"]
