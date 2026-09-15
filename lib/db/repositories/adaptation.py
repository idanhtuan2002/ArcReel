"""Scoped, transaction-bound adapter for the append-only M6 adaptation proposal
evidence (plan Task 5).

``AdaptationRepository`` exposes exact scoped reads and append-only writes only. It
never commits, rolls back, or constructs a session; the unit of work owns that. Every
read predicate carries ``(user_id, project_name)`` so an unknown id/version and a
cross-scope id/version return the same ``None``. A duplicate ``(id, version)`` — same
tenant or not — raises the raw ``sqlalchemy.exc.IntegrityError``; translating that into
a typed identity-conflict error (and deciding what counts as an "exact retry") is
Task 6's ``AdaptationEvidenceService`` job, not this repository's — this task only
proves the constraint exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.adaptation import (
    AdaptationBranchModel,
    AdaptationDecisionModel,
    AdaptationHeadModel,
    AdaptationMapEntryModel,
    AdaptationMapModel,
    AdaptationMapProfileAnalysisRefModel,
    AdaptationScreenplayModel,
    AdaptationScreenplayProfileAnalysisRefModel,
    AdaptationScreenplaySceneModel,
)
from lib.db.repositories.base import rowcount
from r2.adaptation.errors import AdaptationAuthorityIntegrityError
from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationBranchV2,
    AdaptationDecision,
    AdaptationHead,
    AdaptationMapV2,
    ArtifactVersionRef,
    MapApprovalDecision,
    ScreenplayArtifactV2,
)

_decision_adapter: TypeAdapter[AdaptationDecision] = TypeAdapter(AdaptationDecision)

# The family's "select a new effective candidate" action, keyed by the shared
# decision_kind/family string (the two are 1:1 by construction). Mirrors
# ``r2.adaptation.authority_kernel``'s own mapping; duplicated rather than imported so
# this persistence-layer module never depends on the domain authority module (only the
# reverse dependency is permitted) — the same controlled duplication this file's ORM
# ``CheckConstraint`` string tuples already use against the Pydantic contract enums.
_ACCEPTING_ACTION_BY_KIND = {
    "MAP_APPROVAL": "APPROVE",
    "PROFILE_WAIVER": "WAIVE",
    "SCREENPLAY_ADMISSION": "ADMIT",
}


def _stored_aware(value: datetime) -> datetime:
    """SQLite does not reliably round-trip ``tzinfo`` through ``DateTime(timezone=True)``;
    every stored timestamp here is UTC by construction, so a naive read is UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _branch_row(branch: AdaptationBranchV2, *, user_id: str, project_name: str) -> AdaptationBranchModel:
    return AdaptationBranchModel(
        branch_id=branch.branch_id,
        version=branch.version,
        user_id=user_id,
        project_name=project_name,
        parent_branch_id=branch.parent_branch_id,
        parent_canon_artifact_id=branch.parent_canon_version.artifact_id,
        parent_canon_version=branch.parent_canon_version.version,
        parent_canon_content_hash=branch.parent_canon_version.content_hash,
        medium=branch.medium,
        adaptation_policy=branch.adaptation_policy.value,
        overlay_version=branch.overlay_version,
        profile_id=branch.profile_ref.profile_id.value,
        profile_version=branch.profile_ref.profile_version,
        policy_pack_digest=branch.profile_ref.policy_pack_digest,
        created_at=branch.created_at,
        created_by=branch.created_by,
    )


def _branch_from_row(row: AdaptationBranchModel) -> AdaptationBranchV2:
    return AdaptationBranchV2.model_validate(
        {
            "branch_id": row.branch_id,
            "schema_version": "r2-adaptation-branch-v2",
            "version": row.version,
            "parent_branch_id": row.parent_branch_id,
            "parent_canon_version": {
                "artifact_id": row.parent_canon_artifact_id,
                "version": row.parent_canon_version,
                "content_hash": row.parent_canon_content_hash,
            },
            "medium": row.medium,
            "adaptation_policy": row.adaptation_policy,
            "overlay_version": row.overlay_version,
            "profile_ref": {
                "profile_id": row.profile_id,
                "profile_version": row.profile_version,
                "policy_pack_digest": row.policy_pack_digest,
            },
            "created_at": _stored_aware(row.created_at),
            "created_by": row.created_by,
        }
    )


def _map_row(map_: AdaptationMapV2, *, user_id: str, project_name: str) -> AdaptationMapModel:
    return AdaptationMapModel(
        adaptation_map_id=map_.adaptation_map_id,
        version=map_.version,
        user_id=user_id,
        project_name=project_name,
        adaptation_branch_ref_id=map_.adaptation_branch_ref.artifact_id,
        adaptation_branch_ref_version=map_.adaptation_branch_ref.version,
        adaptation_branch_ref_hash=map_.adaptation_branch_ref.content_hash,
        content_hash=map_.content_hash,
    )


def _map_entry_rows(map_: AdaptationMapV2, *, user_id: str, project_name: str) -> list[AdaptationMapEntryModel]:
    return [
        AdaptationMapEntryModel(
            adaptation_map_id=map_.adaptation_map_id,
            adaptation_map_version=map_.version,
            entry_id=entry.entry_id,
            user_id=user_id,
            project_name=project_name,
            position=position,
            source_refs_json=list(entry.source_refs),
            target_refs_json=list(entry.target_refs),
            operation=entry.operation.value,
            rationale=entry.rationale,
            fidelity_risk=entry.fidelity_risk,
            approval_status=entry.approval_status.value,
        )
        for position, entry in enumerate(map_.entries)
    ]


def _map_profile_analysis_ref_rows(
    map_: AdaptationMapV2, *, user_id: str, project_name: str
) -> list[AdaptationMapProfileAnalysisRefModel]:
    return [
        AdaptationMapProfileAnalysisRefModel(
            adaptation_map_id=map_.adaptation_map_id,
            adaptation_map_version=map_.version,
            position=position,
            user_id=user_id,
            project_name=project_name,
            ref_artifact_id=ref.artifact_id,
            ref_version=ref.version,
            ref_content_hash=ref.content_hash,
        )
        for position, ref in enumerate(map_.profile_analysis_refs)
    ]


def _map_from_rows(
    row: AdaptationMapModel,
    entry_rows: list[AdaptationMapEntryModel],
    ref_rows: list[AdaptationMapProfileAnalysisRefModel],
) -> AdaptationMapV2:
    return AdaptationMapV2.model_validate(
        {
            "adaptation_map_id": row.adaptation_map_id,
            "schema_version": "r2-adaptation-map-v2",
            "version": row.version,
            "adaptation_branch_ref": {
                "artifact_id": row.adaptation_branch_ref_id,
                "version": row.adaptation_branch_ref_version,
                "content_hash": row.adaptation_branch_ref_hash,
            },
            "entries": [
                {
                    "entry_id": entry.entry_id,
                    "source_refs": entry.source_refs_json,
                    "target_refs": entry.target_refs_json,
                    "operation": entry.operation,
                    "rationale": entry.rationale,
                    "fidelity_risk": entry.fidelity_risk,
                    "approval_status": entry.approval_status,
                }
                for entry in sorted(entry_rows, key=lambda item: item.position)
            ],
            "profile_analysis_refs": [
                {"artifact_id": ref.ref_artifact_id, "version": ref.ref_version, "content_hash": ref.ref_content_hash}
                for ref in sorted(ref_rows, key=lambda item: item.position)
            ],
            "content_hash": row.content_hash,
        }
    )


def _screenplay_row(screenplay: ScreenplayArtifactV2, *, user_id: str, project_name: str) -> AdaptationScreenplayModel:
    return AdaptationScreenplayModel(
        screenplay_id=screenplay.screenplay_id,
        version=screenplay.version,
        user_id=user_id,
        project_name=project_name,
        adaptation_branch_ref_id=screenplay.adaptation_branch_ref.artifact_id,
        adaptation_branch_ref_version=screenplay.adaptation_branch_ref.version,
        adaptation_branch_ref_hash=screenplay.adaptation_branch_ref.content_hash,
        content_basis_json=screenplay.content_basis.model_dump(mode="json"),
        characters_json=list(screenplay.characters),
        source_mapping_refs_json=list(screenplay.source_mapping_refs),
        approval_status=screenplay.approval_status.value,
        locked_for_direction=screenplay.locked_for_direction,
        content_hash=screenplay.content_hash,
        adaptation_map_ref_id=screenplay.adaptation_map_ref.artifact_id,
        adaptation_map_ref_version=screenplay.adaptation_map_ref.version,
        adaptation_map_ref_hash=screenplay.adaptation_map_ref.content_hash,
    )


def _screenplay_scene_rows(
    screenplay: ScreenplayArtifactV2, *, user_id: str, project_name: str
) -> list[AdaptationScreenplaySceneModel]:
    return [
        AdaptationScreenplaySceneModel(
            screenplay_id=screenplay.screenplay_id,
            screenplay_version=screenplay.version,
            scene_id=scene.scene_id,
            user_id=user_id,
            project_name=project_name,
            position=position,
            purpose=scene.purpose,
            duration_target=scene.duration_target,
            location_ref=scene.location_ref,
            character_refs_json=list(scene.character_refs),
            source_mapping_refs_json=list(scene.source_mapping_refs),
            dramatic_text=scene.dramatic_text,
        )
        for position, scene in enumerate(screenplay.scenes)
    ]


def _screenplay_profile_analysis_ref_rows(
    screenplay: ScreenplayArtifactV2, *, user_id: str, project_name: str
) -> list[AdaptationScreenplayProfileAnalysisRefModel]:
    return [
        AdaptationScreenplayProfileAnalysisRefModel(
            screenplay_id=screenplay.screenplay_id,
            screenplay_version=screenplay.version,
            position=position,
            user_id=user_id,
            project_name=project_name,
            ref_artifact_id=ref.artifact_id,
            ref_version=ref.version,
            ref_content_hash=ref.content_hash,
        )
        for position, ref in enumerate(screenplay.profile_analysis_refs)
    ]


def _screenplay_from_rows(
    row: AdaptationScreenplayModel,
    scene_rows: list[AdaptationScreenplaySceneModel],
    ref_rows: list[AdaptationScreenplayProfileAnalysisRefModel],
) -> ScreenplayArtifactV2:
    return ScreenplayArtifactV2.model_validate(
        {
            "screenplay_id": row.screenplay_id,
            "schema_version": "r2-screenplay-artifact-v2",
            "version": row.version,
            "adaptation_branch_ref": {
                "artifact_id": row.adaptation_branch_ref_id,
                "version": row.adaptation_branch_ref_version,
                "content_hash": row.adaptation_branch_ref_hash,
            },
            "content_basis": row.content_basis_json,
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "purpose": scene.purpose,
                    "duration_target": scene.duration_target,
                    "location_ref": scene.location_ref,
                    "character_refs": scene.character_refs_json,
                    "source_mapping_refs": scene.source_mapping_refs_json,
                    "dramatic_text": scene.dramatic_text,
                }
                for scene in sorted(scene_rows, key=lambda item: item.position)
            ],
            "characters": row.characters_json,
            "source_mapping_refs": row.source_mapping_refs_json,
            "approval_status": row.approval_status,
            "locked_for_direction": row.locked_for_direction,
            "content_hash": row.content_hash,
            "adaptation_map_ref": {
                "artifact_id": row.adaptation_map_ref_id,
                "version": row.adaptation_map_ref_version,
                "content_hash": row.adaptation_map_ref_hash,
            },
            "profile_analysis_refs": [
                {"artifact_id": ref.ref_artifact_id, "version": ref.ref_version, "content_hash": ref.ref_content_hash}
                for ref in sorted(ref_rows, key=lambda item: item.position)
            ],
        }
    )


def _head_key_of(decision: AdaptationDecision) -> str:
    if isinstance(decision, MapApprovalDecision):
        return decision.command.branch_id
    raise NotImplementedError(
        "adaptation repository: PROFILE_WAIVER/SCREENPLAY_ADMISSION head_key derivation is added by Task 11/12, "
        "once their decisions are persisted for the first time"
    )


def _artifact_ref_from_columns(
    artifact_id: str | None, version: int | None, content_hash: str | None
) -> ArtifactVersionRef | None:
    if artifact_id is None:
        return None
    assert version is not None
    assert content_hash is not None
    return ArtifactVersionRef(artifact_id=artifact_id, version=version, content_hash=content_hash)


def _head_from_row(row: AdaptationHeadModel) -> AdaptationHead:
    """Only ever called for ``row.generation >= 1`` (the caller translates
    ``generation == 0`` to the public ``None``), so ``latest_decision_id`` is always
    set — ``AdaptationHead.latest_decision_id`` is not itself optional."""
    assert row.latest_decision_id is not None
    return AdaptationHead(
        user_id=row.user_id,
        project_name=row.project_name,
        family=AdaptationAuthorityFamily(row.family),
        head_key=row.head_key,
        latest_decision_id=row.latest_decision_id,
        effective_decision_id=row.effective_decision_id,
        selected_artifact_ref=_artifact_ref_from_columns(
            row.selected_artifact_id, row.selected_artifact_version, row.selected_artifact_hash
        ),
        generation=row.generation,
    )


def _decision_from_row(row: AdaptationDecisionModel) -> AdaptationDecision:
    return _decision_adapter.validate_python(
        {
            "decision_kind": row.decision_kind,
            "command": row.command_json,
            "authorization": row.authorization_json,
            "sequence": row.sequence,
            "decision_digest": row.decision_digest,
            "created_at": _stored_aware(row.created_at),
        }
    )


def _new_effective_selection(
    decision: AdaptationDecision, *, current_effective_id: str | None, current_artifact: ArtifactVersionRef | None
) -> tuple[str | None, ArtifactVersionRef | None]:
    """The new ``(effective_decision_id, selected_artifact_ref)`` pair after appending
    ``decision``: an accepting action (``APPROVE``/``WAIVE``/``ADMIT``) always becomes
    its own effective selection; any other action (``REJECT``/``DENY_WAIVER``/
    ``REVOKE``) leaves the previous selection unchanged."""
    if decision.command.action.value != _ACCEPTING_ACTION_BY_KIND[decision.decision_kind]:
        return current_effective_id, current_artifact
    assert isinstance(decision, MapApprovalDecision)
    return decision.command.decision_id, decision.command.map_ref


class AdaptationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _scalar(self, stmt: Any) -> Any:
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # --- branches ----------------------------------------------------------------

    async def get_exact_branch(
        self, *, branch_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationBranchV2 | None:
        row = await self._scalar(
            select(AdaptationBranchModel).where(
                AdaptationBranchModel.branch_id == branch_id,
                AdaptationBranchModel.version == version,
                AdaptationBranchModel.project_name == project_name,
                AdaptationBranchModel.user_id == user_id,
            )
        )
        return _branch_from_row(row) if row is not None else None

    async def get_latest_branch_version(
        self, *, branch_id: str, project_name: str, user_id: str
    ) -> AdaptationBranchV2 | None:
        row = await self._scalar(
            select(AdaptationBranchModel)
            .where(
                AdaptationBranchModel.branch_id == branch_id,
                AdaptationBranchModel.project_name == project_name,
                AdaptationBranchModel.user_id == user_id,
            )
            .order_by(AdaptationBranchModel.version.desc())
            .limit(1)
        )
        return _branch_from_row(row) if row is not None else None

    async def insert_branch(self, branch: AdaptationBranchV2, *, user_id: str, project_name: str) -> None:
        self.session.add(_branch_row(branch, user_id=user_id, project_name=project_name))
        await self.session.flush()

    # --- maps ----------------------------------------------------------------------

    async def get_exact_map(
        self, *, adaptation_map_id: str, version: int, project_name: str, user_id: str
    ) -> AdaptationMapV2 | None:
        row = await self._scalar(
            select(AdaptationMapModel).where(
                AdaptationMapModel.adaptation_map_id == adaptation_map_id,
                AdaptationMapModel.version == version,
                AdaptationMapModel.project_name == project_name,
                AdaptationMapModel.user_id == user_id,
            )
        )
        if row is None:
            return None
        entry_rows = list(
            (
                await self.session.execute(
                    select(AdaptationMapEntryModel).where(
                        AdaptationMapEntryModel.adaptation_map_id == adaptation_map_id,
                        AdaptationMapEntryModel.adaptation_map_version == version,
                        AdaptationMapEntryModel.project_name == project_name,
                        AdaptationMapEntryModel.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        ref_rows = list(
            (
                await self.session.execute(
                    select(AdaptationMapProfileAnalysisRefModel).where(
                        AdaptationMapProfileAnalysisRefModel.adaptation_map_id == adaptation_map_id,
                        AdaptationMapProfileAnalysisRefModel.adaptation_map_version == version,
                        AdaptationMapProfileAnalysisRefModel.project_name == project_name,
                        AdaptationMapProfileAnalysisRefModel.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return _map_from_rows(row, entry_rows, ref_rows)

    async def insert_map(self, map_: AdaptationMapV2, *, user_id: str, project_name: str) -> None:
        self.session.add(_map_row(map_, user_id=user_id, project_name=project_name))
        await self.session.flush()
        for row in _map_entry_rows(map_, user_id=user_id, project_name=project_name):
            self.session.add(row)
        for row in _map_profile_analysis_ref_rows(map_, user_id=user_id, project_name=project_name):
            self.session.add(row)
        await self.session.flush()

    # --- screenplays -----------------------------------------------------------------

    async def get_exact_screenplay(
        self, *, screenplay_id: str, version: int, project_name: str, user_id: str
    ) -> ScreenplayArtifactV2 | None:
        row = await self._scalar(
            select(AdaptationScreenplayModel).where(
                AdaptationScreenplayModel.screenplay_id == screenplay_id,
                AdaptationScreenplayModel.version == version,
                AdaptationScreenplayModel.project_name == project_name,
                AdaptationScreenplayModel.user_id == user_id,
            )
        )
        if row is None:
            return None
        scene_rows = list(
            (
                await self.session.execute(
                    select(AdaptationScreenplaySceneModel).where(
                        AdaptationScreenplaySceneModel.screenplay_id == screenplay_id,
                        AdaptationScreenplaySceneModel.screenplay_version == version,
                        AdaptationScreenplaySceneModel.project_name == project_name,
                        AdaptationScreenplaySceneModel.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        ref_rows = list(
            (
                await self.session.execute(
                    select(AdaptationScreenplayProfileAnalysisRefModel).where(
                        AdaptationScreenplayProfileAnalysisRefModel.screenplay_id == screenplay_id,
                        AdaptationScreenplayProfileAnalysisRefModel.screenplay_version == version,
                        AdaptationScreenplayProfileAnalysisRefModel.project_name == project_name,
                        AdaptationScreenplayProfileAnalysisRefModel.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return _screenplay_from_rows(row, scene_rows, ref_rows)

    async def insert_screenplay(self, screenplay: ScreenplayArtifactV2, *, user_id: str, project_name: str) -> None:
        self.session.add(_screenplay_row(screenplay, user_id=user_id, project_name=project_name))
        await self.session.flush()
        for row in _screenplay_scene_rows(screenplay, user_id=user_id, project_name=project_name):
            self.session.add(row)
        for row in _screenplay_profile_analysis_ref_rows(screenplay, user_id=user_id, project_name=project_name):
            self.session.add(row)
        await self.session.flush()

    # --- authority: decisions and heads (plan Task 7) -------------------------------

    def _insert(self, table_class: type) -> Any:
        """Dialect-aware ``INSERT ... ON CONFLICT DO NOTHING`` builder, mirroring
        ``NarrativeLifecycleRepository``'s own helper of the same name."""
        return (
            pg_insert(table_class)
            if self.session.get_bind().dialect.name == "postgresql"
            else sqlite_insert(table_class)
        )

    async def get_decision_by_id(
        self, *, user_id: str, project_name: str, decision_id: str
    ) -> AdaptationDecision | None:
        row = await self._scalar(
            select(AdaptationDecisionModel).where(
                AdaptationDecisionModel.user_id == user_id,
                AdaptationDecisionModel.project_name == project_name,
                AdaptationDecisionModel.decision_id == decision_id,
            )
        )
        return _decision_from_row(row) if row is not None else None

    async def prepare_or_lock_head(
        self, *, user_id: str, project_name: str, family: AdaptationAuthorityFamily, head_key: str
    ) -> AdaptationHead | None:
        stmt = self._insert(AdaptationHeadModel).values(
            user_id=user_id,
            project_name=project_name,
            family=family.value,
            head_key=head_key,
            generation=0,
            latest_decision_id=None,
            effective_decision_id=None,
            selected_artifact_id=None,
            selected_artifact_version=None,
            selected_artifact_hash=None,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["user_id", "project_name", "family", "head_key"])
        await self.session.execute(stmt)
        row = await self._scalar(
            select(AdaptationHeadModel)
            .where(
                AdaptationHeadModel.user_id == user_id,
                AdaptationHeadModel.project_name == project_name,
                AdaptationHeadModel.family == family.value,
                AdaptationHeadModel.head_key == head_key,
            )
            .with_for_update()
        )
        if row is None:
            raise AdaptationAuthorityIntegrityError("adaptation head vanished immediately after insert")
        return None if row.generation == 0 else _head_from_row(row)

    async def list_decisions_for_locked_head(
        self, *, user_id: str, project_name: str, family: AdaptationAuthorityFamily, head_key: str
    ) -> Sequence[AdaptationDecision]:
        rows = (
            (
                await self.session.execute(
                    select(AdaptationDecisionModel)
                    .where(
                        AdaptationDecisionModel.user_id == user_id,
                        AdaptationDecisionModel.project_name == project_name,
                        AdaptationDecisionModel.family == family.value,
                        AdaptationDecisionModel.head_key == head_key,
                    )
                    .order_by(AdaptationDecisionModel.sequence)
                )
            )
            .scalars()
            .all()
        )
        return [_decision_from_row(row) for row in rows]

    async def append_decision_and_advance_head(self, decision: AdaptationDecision, *, expected_generation: int) -> None:
        command = decision.command
        family_value = decision.decision_kind
        head_key = _head_key_of(decision)

        self.session.add(
            AdaptationDecisionModel(
                user_id=command.user_id,
                project_name=command.project_name,
                decision_id=command.decision_id,
                family=family_value,
                head_key=head_key,
                sequence=decision.sequence,
                decision_kind=decision.decision_kind,
                command_json=command.model_dump(mode="json"),
                authorization_json=decision.authorization.model_dump(mode="json"),
                decision_digest=decision.decision_digest,
                created_at=decision.created_at,
            )
        )
        await self.session.flush()

        current = await self._scalar(
            select(AdaptationHeadModel).where(
                AdaptationHeadModel.user_id == command.user_id,
                AdaptationHeadModel.project_name == command.project_name,
                AdaptationHeadModel.family == family_value,
                AdaptationHeadModel.head_key == head_key,
            )
        )
        if current is None:
            raise AdaptationAuthorityIntegrityError(
                f"adaptation head for {family_value}/{head_key!r} does not exist; prepare_or_lock_head must "
                "run in this same transaction before appending its first decision"
            )
        current_artifact = _artifact_ref_from_columns(
            current.selected_artifact_id, current.selected_artifact_version, current.selected_artifact_hash
        )
        new_effective_id, new_artifact = _new_effective_selection(
            decision, current_effective_id=current.effective_decision_id, current_artifact=current_artifact
        )

        result = await self.session.execute(
            update(AdaptationHeadModel)
            .where(
                AdaptationHeadModel.user_id == command.user_id,
                AdaptationHeadModel.project_name == command.project_name,
                AdaptationHeadModel.family == family_value,
                AdaptationHeadModel.head_key == head_key,
                AdaptationHeadModel.generation == expected_generation,
            )
            .values(
                generation=expected_generation + 1,
                latest_decision_id=command.decision_id,
                effective_decision_id=new_effective_id,
                selected_artifact_id=new_artifact.artifact_id if new_artifact is not None else None,
                selected_artifact_version=new_artifact.version if new_artifact is not None else None,
                selected_artifact_hash=new_artifact.content_hash if new_artifact is not None else None,
            )
        )
        if rowcount(result) != 1:
            raise AdaptationAuthorityIntegrityError(
                f"adaptation head for {family_value}/{head_key!r} was not at the expected generation "
                f"{expected_generation} when its decision was appended"
            )
        await self.session.flush()
