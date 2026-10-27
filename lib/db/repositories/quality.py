"""Scoped PostgreSQL publication storage; caller owns transactions and Human admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import exc
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

import r2.contracts.quality as q
from lib.db.models.quality import (
    ProfilePublicationAuthorizationModel,
    QualityCommandModel,
    QualityOutboxModel,
    QualityProfileHeadModel,
    QualityProfileRevisionModel,
)
from r2.advanced_creative.digests import canonical_json_bytes
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.errors import (
    CommandReplayConflictError,
    OperationalEnvelopeExceededError,
    ProfilePublicationUnauthorizedError,
    ProfileStaleError,
    RequiredEvidenceMissingError,
    SchemaChangeRequiredError,
    StaleHeadError,
)
from r2.quality.profiles import build_published_profile, publication_bindings, validate_publication_envelope


@dataclass(frozen=True)
class StoredPublicationAuthorization:
    """Validated persisted data; this object grants no authority."""

    request: q.ProfilePublicationAuthorizationRequest
    lease: q.ProfilePublicationAuthorizationLease
    grant_sequence: int


def _normalized(request: q.ProfilePublicationAuthorizationRequest) -> q.ProfilePublicationAuthorizationRequest:
    validate_publication_envelope(request)
    return q.ProfilePublicationAuthorizationRequest.model_validate(request)


def _lease(value: q.ProfilePublicationAuthorizationLease) -> q.ProfilePublicationAuthorizationLease:
    try:
        return q.ProfilePublicationAuthorizationLease.model_validate(value)
    except (TypeError, ValueError):
        raise ProfilePublicationUnauthorizedError() from None


def _key(command: q.CommandEnvelope) -> dict[str, str]:
    return {name: value for name, value in command.model_dump().items() if name != "request_digest"}


def _result_ref(profile: q.QualityProfileRevision) -> str:
    return f"{profile.profile_id}@{profile.revision}"


class QualityProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _postgresql(self, *, transaction: bool = False) -> None:
        if self.session.get_bind().dialect.name != "postgresql":
            raise SchemaChangeRequiredError()
        if transaction and not self.session.in_transaction():
            raise ProfilePublicationUnauthorizedError()

    async def _flush(self) -> None:
        try:
            await self.session.flush()
        except exc.SQLAlchemyError:
            raise RequiredEvidenceMissingError() from None

    async def get_revision(
        self, *, user_id: str, project_name: str, profile_id: str, revision: int
    ) -> q.QualityProfileRevision | None:
        if any(len(value.encode("utf-8")) > 255 for value in (user_id, project_name, profile_id)):
            raise OperationalEnvelopeExceededError()
        row = (
            await self.session.execute(
                sa.select(QualityProfileRevisionModel)
                .filter_by(user_id=user_id, project_name=project_name, profile_id=profile_id, revision=revision)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        try:
            profile = q.QualityProfileRevision.model_validate(row.body_json)
            verify_caches(profile)
            if (
                (profile.user_id, profile.project_name, profile.profile_id, profile.revision)
                != (row.user_id, row.project_name, row.profile_id, row.revision)
                or (profile.parent_revision, profile.publication_authorization_id)
                != (row.parent_revision, row.authorization_id)
                or (profile.cohort_id, profile.product_surface, profile.policy_digest, profile.profile_digest)
                != (row.cohort_id, row.product_surface, row.policy_digest, row.profile_digest)
                or (profile.created_by, profile.created_at, profile.publication_admitted_at)
                != (row.created_by, row.created_at, row.admitted_at)
            ):
                raise RequiredEvidenceMissingError()
            request_body = await self.session.scalar(
                sa.select(ProfilePublicationAuthorizationModel.request_json).filter_by(
                    user_id=row.user_id, project_name=row.project_name, authorization_id=row.authorization_id
                )
            )
            stored_request = q.ProfilePublicationAuthorizationRequest.model_validate(request_body)
            authorization = await self.load_authorization(stored_request, row.authorization_id)
            if authorization is None:
                raise RequiredEvidenceMissingError()
            expected = build_published_profile(
                stored_request,
                authorization.lease,
                profile.publication_admitted_at,
                policy_id=authorization.lease.policy_id,
                policy_version=authorization.lease.policy_version,
            )
            if canonical_json_bytes(expected) != canonical_json_bytes(profile):
                raise RequiredEvidenceMissingError()
            return profile
        except (TypeError, ValueError, ProfilePublicationUnauthorizedError):
            raise RequiredEvidenceMissingError() from None

    async def replay(self, request: q.ProfilePublicationAuthorizationRequest) -> q.QualityProfileRevision | None:
        request = _normalized(request)
        self._postgresql()
        row = (
            await self.session.execute(
                sa.select(QualityCommandModel)
                .filter_by(**_key(request.command))
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.request_digest != request.command.request_digest:
            raise CommandReplayConflictError()
        try:
            receipt = q.CommandReceipt.model_validate(row.receipt_json)
            if receipt.command != request.command or receipt.committed_at != row.committed_at:
                raise RequiredEvidenceMissingError()
            profile = await self.get_revision(
                user_id=row.user_id,
                project_name=row.project_name,
                profile_id=row.result_profile_id,
                revision=row.result_revision,
            )
            if profile is None or (receipt.result_ref, receipt.result_digest, row.result_digest) != (
                _result_ref(profile),
                profile.profile_digest,
                profile.profile_digest,
            ):
                raise RequiredEvidenceMissingError()
            authorization = await self.load_authorization(request, profile.publication_authorization_id)
            if authorization is None:
                raise RequiredEvidenceMissingError()
            expected = build_published_profile(
                request,
                authorization.lease,
                profile.publication_admitted_at,
                policy_id=authorization.lease.policy_id,
                policy_version=authorization.lease.policy_version,
            )
            if (
                canonical_json_bytes(expected) != canonical_json_bytes(profile)
                or row.committed_at != profile.publication_admitted_at
            ):
                raise RequiredEvidenceMissingError()
            return profile
        except (TypeError, ValueError):
            raise RequiredEvidenceMissingError() from None

    async def lock_command(self, command: q.CommandEnvelope) -> None:
        try:
            command = q.CommandEnvelope.model_validate(command)
            if command.operation != "PUBLISH_PROFILE":
                raise ProfilePublicationUnauthorizedError()
            if any(len(value.encode("utf-8")) > 255 for value in _key(command).values()):
                raise OperationalEnvelopeExceededError()
        except (TypeError, ValueError):
            raise ProfilePublicationUnauthorizedError() from None
        self._postgresql(transaction=True)
        key = compute_digest("m10.command-key-guard.v1", command)
        await self.session.execute(sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})

    async def lock_profile(self, request: q.ProfilePublicationAuthorizationRequest) -> q.QualityProfileRevision | None:
        request = _normalized(request)
        self._postgresql(transaction=True)
        draft = request.subject.profile_draft
        identity = {"user_id": draft.user_id, "project_name": draft.project_name, "profile_id": draft.profile_id}
        await self.session.execute(
            insert(QualityProfileHeadModel)
            .values(**identity, current_revision=None, current_digest=None)
            .on_conflict_do_nothing(index_elements=list(identity))
        )
        head = (
            await self.session.execute(
                sa.select(QualityProfileHeadModel)
                .filter_by(**identity)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        current = head.current_revision
        if (current or 0) != request.subject.expected_profile_revision:
            raise StaleHeadError()
        if current is None:
            if head.current_digest is not None:
                raise RequiredEvidenceMissingError()
            return None
        profile = await self.get_revision(**identity, revision=current)
        genesis = await self.get_revision(**identity, revision=1)
        if profile is None or genesis is None or profile.profile_digest != head.current_digest:
            raise RequiredEvidenceMissingError()
        if (draft.cohort_id, draft.product_surface) != (genesis.cohort_id, genesis.product_surface):
            raise ProfileStaleError()
        return profile

    async def record_authorization(
        self,
        request: q.ProfilePublicationAuthorizationRequest,
        lease: q.ProfilePublicationAuthorizationLease,
        *,
        grant_sequence: int,
    ) -> None:
        request = _normalized(request)
        lease = _lease(lease)
        self._postgresql(transaction=True)
        build_published_profile(
            request, lease, lease.issued_at, policy_id=lease.policy_id, policy_version=lease.policy_version
        )
        if type(grant_sequence) is not int or grant_sequence < 1:
            raise ProfilePublicationUnauthorizedError()
        self.session.add(
            ProfilePublicationAuthorizationModel(
                user_id=lease.user_id,
                project_name=lease.project_name,
                authorization_id=lease.authorization_id,
                action=lease.action,
                actor_id=lease.actor_id,
                command_id=lease.command_id,
                request_digest=lease.request_digest,
                subject_digest=lease.subject_digest,
                policy_id=lease.policy_id,
                policy_version=lease.policy_version,
                evidence_digest=lease.evidence_digest,
                grant_sequence=grant_sequence,
                issued_at=lease.issued_at,
                admit_not_after=lease.admit_not_after,
                request_json=request.model_dump(mode="json"),
                lease_json=lease.model_dump(mode="json"),
            )
        )
        await self._flush()

    async def load_authorization(
        self, request: q.ProfilePublicationAuthorizationRequest, authorization_id: str
    ) -> StoredPublicationAuthorization | None:
        request = _normalized(request)
        self._postgresql()
        if len(authorization_id.encode("utf-8")) > 255:
            raise OperationalEnvelopeExceededError()
        row = (
            await self.session.execute(
                sa.select(ProfilePublicationAuthorizationModel)
                .filter_by(
                    user_id=request.command.user_id,
                    project_name=request.command.project_name,
                    authorization_id=authorization_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        try:
            stored = _normalized(q.ProfilePublicationAuthorizationRequest.model_validate(row.request_json))
            lease = q.ProfilePublicationAuthorizationLease.model_validate(row.lease_json)
            build_published_profile(
                stored, lease, lease.issued_at, policy_id=lease.policy_id, policy_version=lease.policy_version
            )
            request_digest, subject_digest = publication_bindings(stored)
            if (
                canonical_json_bytes(stored) != canonical_json_bytes(request)
                or (
                    lease.user_id,
                    lease.project_name,
                    lease.authorization_id,
                    lease.actor_id,
                    lease.command_id,
                    lease.action,
                )
                != (row.user_id, row.project_name, row.authorization_id, row.actor_id, row.command_id, row.action)
                or (request_digest, subject_digest, lease.request_digest, lease.subject_digest)
                != (row.request_digest, row.subject_digest, row.request_digest, row.subject_digest)
                or (
                    lease.policy_id,
                    lease.policy_version,
                    lease.evidence_digest,
                    lease.issued_at,
                    lease.admit_not_after,
                )
                != (row.policy_id, row.policy_version, row.evidence_digest, row.issued_at, row.admit_not_after)
                or type(row.grant_sequence) is not int
                or row.grant_sequence < 1
            ):
                raise ProfilePublicationUnauthorizedError()
            return StoredPublicationAuthorization(stored, lease, row.grant_sequence)
        except (TypeError, ValueError):
            raise ProfilePublicationUnauthorizedError() from None

    async def stage_publication(
        self,
        request: q.ProfilePublicationAuthorizationRequest,
        lease: q.ProfilePublicationAuthorizationLease,
        revision: q.QualityProfileRevision,
        admitted_at: datetime,
    ) -> None:
        request = _normalized(request)
        self._postgresql(transaction=True)
        lease = _lease(lease)
        authorization = await self.load_authorization(request, lease.authorization_id)
        if authorization is None or authorization.lease != lease:
            raise ProfilePublicationUnauthorizedError()
        expected = build_published_profile(
            request, authorization.lease, admitted_at, policy_id=lease.policy_id, policy_version=lease.policy_version
        )
        try:
            verify_caches(revision)
            if canonical_json_bytes(expected) != canonical_json_bytes(revision):
                raise ProfilePublicationUnauthorizedError()
        except (TypeError, ValueError):
            raise ProfilePublicationUnauthorizedError() from None
        previous = await self.lock_profile(request)
        self.session.add(
            QualityProfileRevisionModel(
                user_id=revision.user_id,
                project_name=revision.project_name,
                profile_id=revision.profile_id,
                revision=revision.revision,
                parent_revision=revision.parent_revision,
                authorization_id=lease.authorization_id,
                cohort_id=revision.cohort_id,
                product_surface=revision.product_surface,
                policy_digest=revision.policy_digest,
                profile_digest=revision.profile_digest,
                created_by=revision.created_by,
                created_at=revision.created_at,
                admitted_at=admitted_at,
                body_json=revision.model_dump(mode="json"),
            )
        )
        await self._flush()
        condition = (
            QualityProfileHeadModel.current_revision.is_(None)
            if previous is None
            else QualityProfileHeadModel.current_revision == previous.revision
        )
        advanced = await self.session.execute(
            sa.update(QualityProfileHeadModel)
            .where(
                QualityProfileHeadModel.user_id == revision.user_id,
                QualityProfileHeadModel.project_name == revision.project_name,
                QualityProfileHeadModel.profile_id == revision.profile_id,
                condition,
            )
            .values(current_revision=revision.revision, current_digest=revision.profile_digest)
            .returning(QualityProfileHeadModel.current_revision)
        )
        if advanced.scalar_one_or_none() != revision.revision:
            raise StaleHeadError()
        receipt = q.CommandReceipt(
            command=request.command,
            result_ref=_result_ref(revision),
            result_digest=revision.profile_digest,
            committed_at=admitted_at,
        )
        self.session.add(
            QualityCommandModel(
                **_key(request.command),
                request_digest=request.command.request_digest,
                result_profile_id=revision.profile_id,
                result_revision=revision.revision,
                result_digest=revision.profile_digest,
                receipt_json=receipt.model_dump(mode="json"),
                committed_at=admitted_at,
            )
        )
        await self._flush()
        event = {
            "event_type": "PROFILE_PUBLISHED",
            **_key(request.command),
            "profile_id": revision.profile_id,
            "revision": revision.revision,
            "profile_digest": revision.profile_digest,
            "previous_revision": revision.parent_revision,
            "cohort_id": revision.cohort_id,
            "product_surface": revision.product_surface,
            "supersession_effect": revision.supersession_effect.value,
            "admitted_at": revision.model_dump(mode="json")["publication_admitted_at"],
        }
        self.session.add(
            QualityOutboxModel(
                **_key(request.command),
                profile_id=revision.profile_id,
                revision=revision.revision,
                profile_digest=revision.profile_digest,
                previous_revision=revision.parent_revision,
                cohort_id=revision.cohort_id,
                product_surface=revision.product_surface,
                supersession_effect=revision.supersession_effect.value,
                admitted_at=admitted_at,
                event_json=event,
            )
        )
        await self._flush()
