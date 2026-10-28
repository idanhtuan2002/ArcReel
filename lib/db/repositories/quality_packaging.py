"""PostgreSQL custody of M10-B package-scoped packaging observations."""

from __future__ import annotations

import hashlib
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.quality_packaging import (
    PackagePreviewModel,
    PackageSelectionAuthorizationModel,
    PackageSelectionModel,
    PackagingHeadModel,
    PackagingObservationModel,
)
from lib.db.models.quality_probes import QualityProbeResultModel
from r2.advanced_creative.digests import canonical_json_bytes
from r2.contracts import packaging as p
from r2.contracts import quality as q
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.errors import (
    CommandReplayConflictError,
    DispositionUnauthorizedError,
    RequiredEvidenceMissingError,
    StaleHeadError,
)
from r2.quality.probes import ProbeExecutionResult, execution_result_digest


def packaging_observation_digest(observation: p.PackagingObservation) -> str:
    return compute_digest("m10.packaging-observation.v1", observation)


class PackagingObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _require_postgresql(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RequiredEvidenceMissingError()

    async def lock_command(self, request: p.PackageCheckRequest) -> None:
        """Serialize every writer of one full command key; a hash collision only serializes, never merges."""
        self._require_postgresql()
        command = request.command
        key = [command.user_id, command.project_name, command.actor_id, command.operation, command.command_id]
        scoped = canonical_json_bytes({"domain": "m10.package-check-command-lock.v1", "key": key})
        lock = int.from_bytes(hashlib.sha256(scoped).digest()[:8], "big", signed=True)
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    async def replay(self, request: p.PackageCheckRequest) -> p.PackagingObservation | None:
        """The observation this exact command recorded; another request under the same command id conflicts."""
        command = request.command
        row = (
            await self.session.execute(
                sa.select(PackagingObservationModel).filter_by(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    actor_id=command.actor_id,
                    command_id=command.command_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.request_digest != compute_digest("m10.package-check-request.v1", request):
            raise CommandReplayConflictError()
        return self._verified(row)

    async def get(self, *, user_id: str, project_name: str, observation_id: str) -> p.PackagingObservation | None:
        row = await self.session.get(PackagingObservationModel, (user_id, project_name, observation_id))
        return None if row is None else self._verified(row)

    async def get_with_run(
        self, *, user_id: str, project_name: str, observation_id: str
    ) -> tuple[p.PackagingObservation, str] | None:
        """A verified observation and the sealed run whose facts it was checked against."""
        row = await self.session.get(PackagingObservationModel, (user_id, project_name, observation_id))
        return None if row is None else (self._verified(row), row.quality_run_id)

    @staticmethod
    def _verified(row: PackagingObservationModel) -> p.PackagingObservation:
        try:
            observation = p.PackagingObservation.model_validate(row.observation_json)
            verify_caches(observation)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        subject = observation.packaging_subject
        if (
            packaging_observation_digest(observation) != row.observation_digest
            or observation.observation_id != row.observation_id
            or (subject.packaging_candidate_id, subject.packaging_candidate_revision)
            != (row.candidate_id, row.candidate_revision)
            or subject.packaging_candidate_digest != row.candidate_payload_digest
            or observation.constraint_snapshot_digest != row.constraint_snapshot_digest
            or observation.status.value != row.status
        ):
            raise RequiredEvidenceMissingError()
        return observation

    async def stage(
        self, request: p.PackageCheckRequest, observation: p.PackagingObservation, recorded_at: datetime
    ) -> None:
        """Flush one observation for the caller's transaction; never commits."""
        self._require_postgresql()
        subject = request.subject
        self.session.add(
            PackagingObservationModel(
                user_id=subject.user_id,
                project_name=subject.project_name,
                observation_id=observation.observation_id,
                actor_id=subject.actor_id,
                command_id=request.command.command_id,
                request_digest=compute_digest("m10.package-check-request.v1", request),
                candidate_id=subject.candidate_id,
                candidate_revision=subject.candidate_revision,
                candidate_payload_digest=subject.candidate_payload_digest,
                quality_run_id=subject.quality_run_id,
                constraint_snapshot_digest=observation.constraint_snapshot_digest,
                status=observation.status.value,
                observation_digest=packaging_observation_digest(observation),
                observation_json=observation.model_dump(mode="json"),
                recorded_at=recorded_at,
            )
        )
        await self.session.flush()

    async def probe_result(
        self, *, user_id: str, project_name: str, execution_id: str, expected_digest: str
    ) -> ProbeExecutionResult:
        """A stored probe result whose recomputed digest is exactly the one an observation names."""
        row = await self.session.get(QualityProbeResultModel, (user_id, project_name, execution_id))
        if row is None:
            raise RequiredEvidenceMissingError()
        try:
            result = ProbeExecutionResult.model_validate(row.result_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        digest = execution_result_digest(result)
        if digest != row.result_digest or digest != expected_digest:
            raise RequiredEvidenceMissingError()
        return result


def preview_digest(preview: p.PackagePreview) -> str:
    return compute_digest("m10.package-preview.v1", preview)


def selection_digest(selection: p.PackageSelection) -> str:
    return compute_digest("m10.package-selection.v1", selection)


def _lock_key(domain: str, key: list[str]) -> int:
    scoped = canonical_json_bytes({"domain": domain, "key": key})
    return int.from_bytes(hashlib.sha256(scoped).digest()[:8], "big", signed=True)


def _slot(slot: p.PackagingSlotKey) -> dict[str, str]:
    return {
        "user_id": slot.user_id,
        "project_name": slot.project_name,
        "source_artifact_key": slot.source_artifact_key,
        "cohort_id": slot.cohort_id,
        "product_surface": slot.product_surface,
    }


class PackageSelectionRepository:
    """Previews, selection leases, selections and the PACKAGING_SLOT head; nothing here commits."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _require_postgresql(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RequiredEvidenceMissingError()

    async def database_now(self) -> datetime:
        self._require_postgresql()
        value = await self.session.scalar(sa.select(sa.func.clock_timestamp()))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise RequiredEvidenceMissingError()
        return value

    async def lock_command(self, command: q.CommandEnvelope) -> None:
        """Serialize every writer of one full command key; a hash collision only serializes, never merges."""
        self._require_postgresql()
        key = [command.user_id, command.project_name, command.actor_id, command.operation, command.command_id]
        lock = _lock_key("m10.package-command-lock.v1", key)
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    async def lock_head(self, slot: p.PackagingSlotKey, *, for_update: bool) -> tuple[str | None, int]:
        """Serialize one PACKAGING_SLOT (absent heads included); returns (current selection, version)."""
        self._require_postgresql()
        values = _slot(slot)
        await self.session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:lock)"),
            {"lock": _lock_key("m10.packaging-head.v1", list(values.values()))},
        )
        statement = sa.select(PackagingHeadModel).filter_by(**values)
        statement = statement.with_for_update() if for_update else statement.with_for_update(read=True)
        head = (await self.session.execute(statement)).scalar_one_or_none()
        return (None, 0) if head is None else (head.current_selection_id, head.head_version)

    async def head_version(self, slot: p.PackagingSlotKey) -> int:
        head = await self.session.get(PackagingHeadModel, tuple(_slot(slot).values()))
        return 0 if head is None else head.head_version

    async def replay_preview(self, request: p.PackagePreviewRequest) -> p.PackagePreview | None:
        command = request.command
        row = (
            await self.session.execute(
                sa.select(PackagePreviewModel).filter_by(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    actor_id=command.actor_id,
                    command_id=command.command_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.request_digest != compute_digest("m10.package-preview-request.v1", request):
            raise CommandReplayConflictError()
        return self._preview(row)

    @staticmethod
    def _preview(row: PackagePreviewModel) -> p.PackagePreview:
        try:
            preview = p.PackagePreview.model_validate(row.preview_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        if preview_digest(preview) != row.preview_digest or preview.preview_id != row.preview_id:
            raise RequiredEvidenceMissingError()
        return preview

    async def stage_preview(self, request: p.PackagePreviewRequest, preview: p.PackagePreview) -> None:
        self._require_postgresql()
        command = request.command
        self.session.add(
            PackagePreviewModel(
                user_id=command.user_id,
                project_name=command.project_name,
                preview_id=preview.preview_id,
                actor_id=command.actor_id,
                command_id=command.command_id,
                request_digest=compute_digest("m10.package-preview-request.v1", request),
                source_artifact_key=preview.slot.source_artifact_key,
                cohort_id=preview.slot.cohort_id,
                product_surface=preview.slot.product_surface,
                packaging_observation_id=preview.packaging_observation_id,
                preview_digest=preview_digest(preview),
                preview_json=preview.model_dump(mode="json"),
                expires_at=preview.expires_at,
                created_at=preview.created_at,
            )
        )
        await self.session.flush()

    async def preview(
        self, *, user_id: str, project_name: str, preview_id: str, for_update: bool = False
    ) -> p.PackagePreview | None:
        statement = sa.select(PackagePreviewModel).filter_by(
            user_id=user_id, project_name=project_name, preview_id=preview_id
        )
        if for_update:
            statement = statement.with_for_update()
        row = (await self.session.execute(statement)).scalar_one_or_none()
        return None if row is None else self._preview(row)

    async def record_authorization(
        self, lease: p.PackagingSelectionAuthorizationLease, *, grant_sequence: int, recorded_at: datetime
    ) -> None:
        self._require_postgresql()
        if type(grant_sequence) is not int or grant_sequence < 1:
            raise DispositionUnauthorizedError()
        self.session.add(
            PackageSelectionAuthorizationModel(
                user_id=lease.user_id,
                project_name=lease.project_name,
                authorization_id=lease.authorization_id,
                lease_json=lease.model_dump(mode="json"),
                grant_sequence=grant_sequence,
                recorded_at=recorded_at,
            )
        )
        await self.session.flush()

    async def load_authorization(
        self, *, user_id: str, project_name: str, authorization_id: str
    ) -> tuple[p.PackagingSelectionAuthorizationLease, int] | None:
        row = await self.session.get(PackageSelectionAuthorizationModel, (user_id, project_name, authorization_id))
        if row is None:
            return None
        try:
            lease = p.PackagingSelectionAuthorizationLease.model_validate(row.lease_json)
        except (ValueError, TypeError):
            raise DispositionUnauthorizedError() from None
        if lease.authorization_id != row.authorization_id:
            raise DispositionUnauthorizedError()
        return lease, row.grant_sequence

    async def replay_selection(self, request: p.PackageSelectionRequest) -> p.PackageSelection | None:
        command = request.command
        row = (
            await self.session.execute(
                sa.select(PackageSelectionModel).filter_by(
                    user_id=command.user_id,
                    project_name=command.project_name,
                    actor_id=command.actor_id,
                    command_id=command.command_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.request_digest != compute_digest("m10.package-selection-request.v1", request):
            raise CommandReplayConflictError()
        return self._selection(row)

    @staticmethod
    def _selection(row: PackageSelectionModel) -> p.PackageSelection:
        try:
            selection = p.PackageSelection.model_validate(row.selection_json)
            verify_caches(selection)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        if selection_digest(selection) != row.selection_digest or selection.selection_id != row.selection_id:
            raise RequiredEvidenceMissingError()
        return selection

    async def selection(self, *, user_id: str, project_name: str, selection_id: str) -> p.PackageSelection | None:
        row = await self.session.get(PackageSelectionModel, (user_id, project_name, selection_id))
        return None if row is None else self._selection(row)

    async def append_selection(self, request: p.PackageSelectionRequest, selection: p.PackageSelection) -> None:
        """Append the selection and advance the slot head by CAS; the caller holds the head lock."""
        self._require_postgresql()
        slot = selection.preview.slot
        values = _slot(slot)
        head = await self.session.get(PackagingHeadModel, tuple(values.values()))
        version = 0 if head is None else head.head_version
        if version != selection.head_version - 1:
            raise StaleHeadError()
        command = request.command
        self.session.add(
            PackageSelectionModel(
                user_id=command.user_id,
                project_name=command.project_name,
                selection_id=selection.selection_id,
                actor_id=command.actor_id,
                command_id=command.command_id,
                request_digest=compute_digest("m10.package-selection-request.v1", request),
                preview_id=selection.preview.preview_id,
                authorization_id=selection.custodian_authorization_id,
                source_artifact_key=slot.source_artifact_key,
                cohort_id=slot.cohort_id,
                product_surface=slot.product_surface,
                head_version=selection.head_version,
                selection_digest=selection_digest(selection),
                selection_json=selection.model_dump(mode="json"),
                selected_at=selection.selected_at,
            )
        )
        await self.session.flush()
        if head is None:
            self.session.add(
                PackagingHeadModel(
                    **values,
                    current_selection_id=selection.selection_id,
                    head_version=selection.head_version,
                    updated_at=selection.selected_at,
                )
            )
        else:
            advanced = await self.session.execute(
                sa.update(PackagingHeadModel)
                .filter_by(**values, head_version=version)
                .values(
                    current_selection_id=selection.selection_id,
                    head_version=selection.head_version,
                    updated_at=selection.selected_at,
                )
            )
            if getattr(advanced, "rowcount", 0) != 1:
                raise StaleHeadError()
        await self.session.flush()


__all__ = [
    "PackageSelectionRepository",
    "PackagingObservationRepository",
    "packaging_observation_digest",
    "preview_digest",
    "selection_digest",
]
