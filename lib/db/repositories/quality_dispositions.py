"""Scoped disposition custody on PostgreSQL; callers own transactions and stage methods never commit."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import r2.contracts.quality as q
from lib.db.models.quality_dispositions import (
    DispositionAuthorizationModel,
    DispositionCommandModel,
    DispositionHeadModel,
    DispositionOutboxModel,
    QualityDispositionModel,
)
from r2.advanced_creative.digests import canonical_json_bytes
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    CommandReplayConflictError,
    DispositionUnauthorizedError,
    RequiredEvidenceMissingError,
    StaleHeadError,
)

MAX_JSON_BYTES = 1048576


@dataclass(frozen=True)
class DispositionKey:
    user_id: str
    project_name: str
    actor_id: str
    command_id: str


def disposition_digest(disposition: q.QualityDisposition) -> str:
    return compute_digest("m10.quality-disposition.v1", q.QualityDisposition.model_validate(disposition))


def _bounded(value: object) -> object:
    if len(canonical_json_bytes(value)) > MAX_JSON_BYTES:
        raise RequiredEvidenceMissingError()
    return value


def _lock_id(domain: str, parts: list[str]) -> int:
    scoped = canonical_json_bytes({"domain": domain, "parts": parts})
    return int.from_bytes(hashlib.sha256(scoped).digest()[:8], "big", signed=True)


class QualityDispositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _require_postgresql(self) -> None:
        if self.session.get_bind().dialect.name != "postgresql" or not self.session.in_transaction():
            raise RequiredEvidenceMissingError()

    async def _advisory(self, lock: int) -> None:
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(:lock)"), {"lock": lock})

    async def lock_command(self, key: DispositionKey) -> None:
        """Serialize one full command key; a hash collision only serializes, never merges identities."""
        self._require_postgresql()
        await self._advisory(_lock_id("m10.disposition-command.v1", [*key.__dict__.values()]))

    async def database_now(self) -> datetime:
        self._require_postgresql()
        value = await self.session.scalar(sa.select(sa.func.clock_timestamp()))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise DispositionUnauthorizedError()
        return value

    async def record_authorization(self, lease: q.DispositionAuthorizationLease, *, grant_sequence: int) -> None:
        self._require_postgresql()
        lease = q.DispositionAuthorizationLease.model_validate(lease)
        if type(grant_sequence) is not int or grant_sequence < 1:
            raise DispositionUnauthorizedError()
        self.session.add(
            DispositionAuthorizationModel(
                user_id=lease.user_id,
                project_name=lease.project_name,
                authorization_id=lease.authorization_id,
                actor_id=lease.actor_id,
                command_id=lease.command_id,
                request_digest=lease.request_digest,
                subject_digest=lease.subject_digest,
                grant_sequence=grant_sequence,
                issued_at=lease.issued_at,
                admit_not_after=lease.admit_not_after,
                lease_json=_bounded(lease.model_dump(mode="json")),
            )
        )
        await self.session.flush()

    async def load_authorization(
        self, *, user_id: str, project_name: str, authorization_id: str
    ) -> tuple[q.DispositionAuthorizationLease, int] | None:
        """The persisted lease and the grant sequence it was issued under, recomputed from the stored body."""
        row = await self.session.get(DispositionAuthorizationModel, (user_id, project_name, authorization_id))
        if row is None:
            return None
        try:
            lease = q.DispositionAuthorizationLease.model_validate(row.lease_json)
        except (ValueError, TypeError):
            raise DispositionUnauthorizedError() from None
        if (lease.authorization_id, lease.actor_id, lease.command_id, lease.request_digest, lease.subject_digest) != (
            row.authorization_id,
            row.actor_id,
            row.command_id,
            row.request_digest,
            row.subject_digest,
        ) or (lease.issued_at, lease.admit_not_after) != (row.issued_at, row.admit_not_after):
            raise DispositionUnauthorizedError()
        return (lease, row.grant_sequence)

    async def receipt(self, key: DispositionKey, request_digest: str) -> q.QualityDisposition | None:
        """Receipt-first replay of the exact key; a changed body conflicts and digest drift refuses."""
        row = await self.session.get(
            DispositionCommandModel, (key.user_id, key.project_name, key.actor_id, key.command_id)
        )
        if row is None:
            return None
        if row.request_digest != request_digest:
            raise CommandReplayConflictError()
        stored_row = await self.session.get(QualityDispositionModel, (key.user_id, key.project_name, row.result_ref))
        if stored_row is None or (stored_row.actor_id, stored_row.command_id) != (key.actor_id, key.command_id):
            raise RequiredEvidenceMissingError()
        stored = await self.disposition(
            user_id=key.user_id, project_name=key.project_name, disposition_id=row.result_ref
        )
        if stored is None or disposition_digest(stored) != row.result_digest:
            raise RequiredEvidenceMissingError()
        return stored

    async def disposition(self, *, user_id: str, project_name: str, disposition_id: str) -> q.QualityDisposition | None:
        row = await self.session.get(QualityDispositionModel, (user_id, project_name, disposition_id))
        if row is None:
            return None
        try:
            stored = q.QualityDisposition.model_validate(row.disposition_json)
        except (ValueError, TypeError):
            raise RequiredEvidenceMissingError() from None
        if (
            disposition_digest(stored) != row.disposition_digest
            or stored.disposition_id != disposition_id
            or (stored.decision.value, stored.quality_run_id, stored.subject_digest)
            != (
                row.decision,
                row.quality_run_id,
                row.subject_digest,
            )
        ):
            raise RequiredEvidenceMissingError()
        return stored

    async def lock_head(
        self, *, user_id: str, project_name: str, subject_digest: str, profile_id: str
    ) -> tuple[str | None, int]:
        """Serialize every issuer of one subject/profile head (absent heads included); returns (current, version)."""
        self._require_postgresql()
        await self._advisory(_lock_id("m10.disposition-head.v1", [user_id, project_name, subject_digest, profile_id]))
        head = (
            await self.session.execute(
                sa.select(DispositionHeadModel)
                .filter_by(
                    user_id=user_id, project_name=project_name, subject_digest=subject_digest, profile_id=profile_id
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        return (None, 0) if head is None else (head.current_disposition_id, head.version)

    async def append(
        self,
        key: DispositionKey,
        request_digest: str,
        disposition: q.QualityDisposition,
        *,
        authorization_id: str,
        expected_version: int,
    ) -> str:
        """Append disposition, receipt and outbox event and advance the head by CAS, all in one transaction."""
        self._require_postgresql()
        disposition = q.QualityDisposition.model_validate(disposition)
        digest = disposition_digest(disposition)
        head = (
            await self.session.execute(
                sa.select(DispositionHeadModel)
                .filter_by(
                    user_id=key.user_id,
                    project_name=key.project_name,
                    subject_digest=disposition.subject_digest,
                    profile_id=disposition.profile_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        version = 0 if head is None else head.version
        current = None if head is None else head.current_disposition_id
        if version != expected_version or current != disposition.supersedes_disposition_id:
            raise StaleHeadError()
        self.session.add(
            QualityDispositionModel(
                user_id=key.user_id,
                project_name=key.project_name,
                disposition_id=disposition.disposition_id,
                actor_id=key.actor_id,
                command_id=key.command_id,
                authorization_id=authorization_id,
                subject_digest=disposition.subject_digest,
                profile_id=disposition.profile_id,
                quality_run_id=disposition.quality_run_id,
                decision=disposition.decision.value,
                disposition_digest=digest,
                disposition_json=_bounded(disposition.model_dump(mode="json")),
                issued_at=disposition.issued_at,
                expires_at=disposition.expires_at,
            )
        )
        self.session.add(
            DispositionCommandModel(
                **key.__dict__,
                request_digest=request_digest,
                result_ref=disposition.disposition_id,
                result_digest=digest,
                receipt_json=_bounded(
                    {
                        "command": key.__dict__,
                        "request_digest": request_digest,
                        "result_ref": disposition.disposition_id,
                        "result_digest": digest,
                        "committed_at": disposition.issued_at.isoformat(),
                    }
                ),
                committed_at=disposition.issued_at,
            )
        )
        await self.session.flush()
        self.session.add(
            DispositionOutboxModel(
                user_id=key.user_id,
                project_name=key.project_name,
                disposition_id=disposition.disposition_id,
                event_json=_bounded(
                    {
                        "event": "QUALITY_DISPOSITION_ISSUED",
                        "disposition_id": disposition.disposition_id,
                        "disposition_digest": digest,
                        "decision": disposition.decision.value,
                        "quality_run_id": disposition.quality_run_id,
                        "subject_digest": disposition.subject_digest,
                        "supersedes_disposition_id": disposition.supersedes_disposition_id,
                    }
                ),
                admitted_at=disposition.issued_at,
            )
        )
        if head is None:
            self.session.add(
                DispositionHeadModel(
                    user_id=key.user_id,
                    project_name=key.project_name,
                    subject_digest=disposition.subject_digest,
                    profile_id=disposition.profile_id,
                    current_disposition_id=disposition.disposition_id,
                    current_digest=digest,
                    version=1,
                )
            )
        else:
            head.current_disposition_id = disposition.disposition_id
            head.current_digest = digest
            head.version += 1
        await self.session.flush()
        return digest

    async def head_disposition(
        self, *, user_id: str, project_name: str, subject_digest: str, profile_id: str
    ) -> q.QualityDisposition | None:
        row = await self.session.get(DispositionHeadModel, (user_id, project_name, subject_digest, profile_id))
        if row is None:
            return None
        stored = await self.disposition(
            user_id=user_id, project_name=project_name, disposition_id=row.current_disposition_id
        )
        if stored is None or disposition_digest(stored) != row.current_digest:
            raise RequiredEvidenceMissingError()
        return stored


__all__ = ["DispositionKey", "QualityDispositionRepository", "disposition_digest"]
