"""M10-B package preview and Human selection into `PACKAGING_SLOT`.

A preview binds the exact candidate revision, packaging observation, current READY disposition, chosen variants
and waivers; it grants nothing. Selection is a Human act under a DB-time custodian lease and writes only the M10
packaging head. Every writer takes the design's global order: command guard, sorted masters, profile head, run
head, disposition head, preview, packaging head, grant heads. Nothing here writes Production Authority.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import r2.contracts.quality as q
from lib.db.models.quality_dispositions import DispositionHeadModel
from lib.db.models.quality_runs import QualityRunHeadModel
from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_dispositions import disposition_digest
from lib.db.repositories.quality_packaging import (
    PackageSelectionRepository,
    PackagingObservationRepository,
    preview_digest,
)
from lib.db.repositories.quality_runs import QualityRunRepository
from r2.advanced_creative.digests import canonical_json_bytes
from r2.advanced_creative.exploration import uuid7
from r2.contracts import packaging as p
from r2.contracts.advanced_creative import ExplorationKind, PackagingCandidate
from r2.governance.grant_transition import GrantScopeV1
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    DispositionStaleError,
    DispositionUnauthorizedError,
    ProfileStaleError,
    RequiredEvidenceMissingError,
    StaleHeadError,
    SubjectStaleError,
    WaiverForbiddenError,
)
from r2.quality.runs import run_digest
from server.auth import get_current_interactive_user
from server.services.governance_grants import CheckpointedShowrunnerGrantReader, ShowrunnerGrantUnavailableError
from server.services.governance_startup import GovernanceStartupUnavailable, verify_governance_activated_startup
from server.services.quality_dispositions import readiness_in
from server.services.quality_packaging import require_packaging_lineage
from server.services.quality_runs import human_principals, lock_grant_heads, lock_profile_head, lock_subject_masters

SELECTION_POLICY_ID = "m10.package-selection.interactive-human.v1"
SELECTION_POLICY_VERSION = "1"
PREVIEW_SECONDS = 600
_LEASE_SECONDS = 30

type Sessions = async_sessionmaker[AsyncSession]
type GrantReaderFactory = Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]


def _chosen_variants(candidate: PackagingCandidate, selected: tuple[str, ...]) -> None:
    """Exactly one known alternative per variant group; variant ids must be unambiguous across groups."""
    owners: dict[str, str] = {}
    for group in candidate.variant_groups:
        for variant in group.variants:
            if variant.variant_id in owners:
                raise RequiredEvidenceMissingError()
            owners[variant.variant_id] = group.group_id
    groups = [owners.get(variant_id) for variant_id in selected]
    if None in groups or sorted(groups) != sorted(group.group_id for group in candidate.variant_groups):  # pyright: ignore[reportArgumentType]
        raise RequiredEvidenceMissingError()


def _waivers(observation: p.PackagingObservation, policy: q.QualityPolicyV2, waivers: tuple[p.PackageWaiver, ...]):
    """A FAIL is selectable only when every BLOCKING finding is waivable and waived with a reason; nothing else."""
    blocking = {f.finding_id: f.rule_id for f in observation.findings if f.severity == "BLOCKING"}
    requested = {w.finding_id: w.rule_id for w in waivers}
    if observation.status is q.ObservationStatus.PASS:
        if requested:
            raise WaiverForbiddenError()
        return
    if observation.status is not q.ObservationStatus.FAIL or requested != blocking:
        raise WaiverForbiddenError()
    if not set(blocking.values()) <= set(policy.packaging_waiverable_rule_ids):
        raise WaiverForbiddenError()


@dataclass(frozen=True)
class PackageEvidence:
    candidate: PackagingCandidate
    observation: p.PackagingObservation
    run: q.QualityRun
    profile: q.QualityProfileRevision


async def resolve_package_evidence(
    session: AsyncSession,
    *,
    user_id: str,
    project_name: str,
    slot: p.PackagingSlotKey,
    candidate_id: str,
    candidate_revision: int,
    candidate_payload_digest: str,
    observation_id: str,
    selected_variant_ids: tuple[str, ...],
    waivers: tuple[p.PackageWaiver, ...],
) -> PackageEvidence:
    """Re-derive and verify every package input from immutable evidence; shared by preview and selection.

    The exact PACKAGING revision (payload, closures, lineage), a PACKAGING head, the packaging observation and the
    sealed run it was checked against, the published V2 profile and its constraint snapshot, the slot identity,
    one chosen alternative per group and exact waivers of waivable blocking findings.
    """
    m8 = ExplorationRepository(session)
    revision = await m8.get_exact(
        user_id=user_id, project_name=project_name, candidate_id=candidate_id, revision=candidate_revision
    )
    head = await m8.get_head(user_id=user_id, project_name=project_name, candidate_id=candidate_id)
    current = (
        None
        if head is None
        else await m8.get_exact(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id, revision=head.current_revision
        )
    )
    if (
        revision is None
        or current is None
        or current.kind is not ExplorationKind.PACKAGING
        or revision.payload_digest != candidate_payload_digest
    ):
        raise SubjectStaleError()
    found = await PackagingObservationRepository(session).get_with_run(
        user_id=user_id, project_name=project_name, observation_id=observation_id
    )
    if found is None:
        raise RequiredEvidenceMissingError()
    observation, run_id = found
    bound = observation.packaging_subject
    if (bound.packaging_candidate_id, bound.packaging_candidate_revision, bound.packaging_candidate_digest) != (
        candidate_id,
        candidate_revision,
        candidate_payload_digest,
    ):
        raise SubjectStaleError()
    run = await QualityRunRepository(session).run(user_id=user_id, project_name=project_name, run_id=run_id)
    if run is None:
        raise RequiredEvidenceMissingError()
    profile = await QualityProfileRepository(session).get_revision(
        user_id=user_id, project_name=project_name, profile_id=run.profile_id, revision=run.profile_revision
    )
    if profile is None or profile.profile_digest != run.profile_digest:
        raise ProfileStaleError()
    if not isinstance(profile.policy, q.QualityPolicyV2):
        raise ProfileStaleError()
    candidate = require_packaging_lineage(revision, run, profile, project_name)
    snapshot = compute_digest("m10.platform-constraints.v1", profile.policy.platform_constraints)
    if (
        (slot.user_id, slot.project_name, slot.source_artifact_key, slot.cohort_id, slot.product_surface)
        != (
            user_id,
            project_name,
            run.subject.master_binding.root.artifact_key,
            profile.cohort_id,
            profile.product_surface,
        )
        or bound.base_subject_digest != run.subject_digest
        or observation.constraint_snapshot_digest != snapshot
        or candidate.constraint_snapshot_digest != snapshot
    ):
        raise SubjectStaleError()
    _chosen_variants(candidate, selected_variant_ids)
    _waivers(observation, profile.policy, waivers)
    return PackageEvidence(candidate, observation, run, profile)


class PackagePreviewService:
    def __init__(self, *, sessions: Sessions, grant_reader: GrantReaderFactory, project_root: Path) -> None:
        self._sessions = sessions
        self._grant_reader = grant_reader
        self._project_root = project_root

    async def preview(self, request: p.PackagePreviewRequest) -> p.PackagePreview:
        if request.command.request_digest != compute_digest("m10.package-preview-request.v1", request):
            raise RequiredEvidenceMissingError()
        async with self._sessions() as session, session.begin():
            repository = PackageSelectionRepository(session)
            await repository.lock_command(request.command)
            replayed = await repository.replay_preview(request)
        if replayed is not None:
            return replayed
        reader = await self._grant_reader()
        subject = request.subject
        user_id, project_name = subject.user_id, subject.project_name
        async with self._sessions() as session, session.begin():
            repository = PackageSelectionRepository(session)
            await repository.lock_command(request.command)
            replayed = await repository.replay_preview(request)
            if replayed is not None:
                return replayed
            evidence = await resolve_package_evidence(
                session,
                user_id=user_id,
                project_name=project_name,
                slot=subject.slot,
                candidate_id=subject.candidate_id,
                candidate_revision=subject.candidate_revision,
                candidate_payload_digest=subject.candidate_payload_digest,
                observation_id=subject.packaging_observation_id,
                selected_variant_ids=subject.selected_variant_ids,
                waivers=subject.waivers,
            )
            candidate, observation, run = evidence.candidate, evidence.observation, evidence.run
            run_id, slot = run.run_id, subject.slot
            readiness, disposition, ready_run = await readiness_in(
                session,
                reader,
                project_root=self._project_root,
                user_id=user_id,
                project_name=project_name,
                subject_digest=run.subject_digest,
                profile_id=run.profile_id,
            )
            if readiness.state != "READY" or disposition is None or ready_run is None or ready_run.run_id != run_id:
                raise DispositionStaleError()
            now = await repository.database_now()
            preview = p.PackagePreview(
                preview_id=uuid7(),
                slot=slot,
                candidate_id=subject.candidate_id,
                candidate_revision=subject.candidate_revision,
                candidate_payload_digest=subject.candidate_payload_digest,
                approved_master_id=candidate.approved_master_id,
                approved_master_digest=candidate.approved_master_digest,
                quality_run_id=run.run_id,
                quality_run_digest=run_digest(run),
                disposition_id=disposition.disposition_id,
                disposition_digest=disposition_digest(disposition),
                profile_id=run.profile_id,
                profile_revision=run.profile_revision,
                profile_digest=run.profile_digest,
                packaging_observation_id=observation.observation_id,
                packaging_observation_digest=compute_digest("m10.packaging-observation.v1", observation),
                selected_variant_ids=subject.selected_variant_ids,
                waivers=subject.waivers,
                expected_head_version=await repository.head_version(slot),
                created_at=now,
                expires_at=min(now + timedelta(seconds=PREVIEW_SECONDS), disposition.expires_at),
            )
            await repository.stage_preview(request, preview)
        return preview


class PackageSelectionCustodian:
    """A request-bound authenticated wrapper; it is not itself an authorization."""

    def __init__(
        self,
        request: p.PackageSelectionRequest,
        sessions: Sessions,
        *,
        interactive_token: str | None,
        read_directory: Path,
        socket_directory: Path,
        expected_uid: int,
        expected_gid: int,
    ) -> None:
        self._request = p.PackageSelectionRequest.model_validate(request)
        self._binding = canonical_json_bytes(self._request)
        self._sessions = sessions
        self._token = interactive_token
        self._read_directory = read_directory
        self._socket_directory = socket_directory
        self._expected_uid = expected_uid
        self._expected_gid = expected_gid
        self._reader: CheckpointedShowrunnerGrantReader | None = None

    async def require_actor(self, request: p.PackageSelectionRequest) -> None:
        normalized = p.PackageSelectionRequest.model_validate(request)
        if canonical_json_bytes(normalized) != self._binding:
            raise DispositionUnauthorizedError()
        try:
            user = await get_current_interactive_user(self._token)
        except HTTPException:
            raise DispositionUnauthorizedError() from None
        if (user.id, user.sub) != (normalized.command.user_id, normalized.command.actor_id):
            raise DispositionUnauthorizedError()

    @property
    def reader(self) -> CheckpointedShowrunnerGrantReader:
        if self._reader is None:
            raise DispositionUnauthorizedError()
        return self._reader

    async def authorize_selection(self, request: p.PackageSelectionRequest) -> p.PackagingSelectionAuthorizationLease:
        """Activate governance, read the current HUMAN_SHOWRUNNER grant and persist a DB-time lease of ≤30 s."""
        await self.require_actor(request)
        try:
            reader = await verify_governance_activated_startup(
                self._read_directory,
                self._socket_directory,
                session_factory=self._sessions,
                expected_uid=self._expected_uid,
                expected_gid=self._expected_gid,
            )
        except GovernanceStartupUnavailable:
            raise DispositionUnauthorizedError() from None
        if type(reader) is not CheckpointedShowrunnerGrantReader:
            raise DispositionUnauthorizedError()
        self._reader = reader
        command = request.command
        async with self._sessions() as session, session.begin():
            repository = PackageSelectionRepository(session)
            try:
                grant = await reader.require_current_locked(
                    session, scope=GrantScopeV1(command.user_id, command.project_name, command.actor_id)
                )
            except ShowrunnerGrantUnavailableError:
                raise DispositionUnauthorizedError() from None
            await self.require_actor(request)
            issued_at = await repository.database_now()
            deadline = issued_at + timedelta(seconds=_LEASE_SECONDS)
            if grant.body.expires_at is not None:
                deadline = min(deadline, datetime.fromisoformat(grant.body.expires_at))
            if deadline <= issued_at:
                raise DispositionUnauthorizedError()
            lease = p.PackagingSelectionAuthorizationLease(
                authorization_id=uuid7(),
                action="PACKAGING_SELECTION",
                user_id=command.user_id,
                project_name=command.project_name,
                actor_id=command.actor_id,
                command_id=command.command_id,
                request_digest=command.request_digest,
                subject_digest=request.subject.preview_digest,
                policy_id=SELECTION_POLICY_ID,
                policy_version=SELECTION_POLICY_VERSION,
                evidence_digest=grant.event_digest,
                issued_at=issued_at,
                admit_not_after=deadline,
            )
            await repository.record_authorization(lease, grant_sequence=grant.body.sequence, recorded_at=issued_at)
        return lease

    async def admit(
        self,
        session: AsyncSession,
        request: p.PackageSelectionRequest,
        lease: p.PackagingSelectionAuthorizationLease,
    ) -> datetime:
        """Under the write transaction: the stored lease, the same current grant and the window on DB time."""
        await self.require_actor(request)
        lease = p.PackagingSelectionAuthorizationLease.model_validate(lease)
        command = request.command
        repository = PackageSelectionRepository(session)
        stored = await repository.load_authorization(
            user_id=command.user_id, project_name=command.project_name, authorization_id=lease.authorization_id
        )
        if (
            stored is None
            or stored[0] != lease
            or (lease.policy_id, lease.policy_version) != (SELECTION_POLICY_ID, SELECTION_POLICY_VERSION)
            or (lease.command_id, lease.request_digest, lease.subject_digest)
            != (command.command_id, command.request_digest, request.subject.preview_digest)
        ):
            raise DispositionUnauthorizedError()
        try:
            grant = await self.reader.require_current_locked(
                session, scope=GrantScopeV1(command.user_id, command.project_name, command.actor_id)
            )
        except ShowrunnerGrantUnavailableError:
            raise DispositionUnauthorizedError() from None
        if (grant.body.sequence, grant.event_digest) != (stored[1], lease.evidence_digest):
            raise DispositionUnauthorizedError()
        now = await repository.database_now()
        if not lease.issued_at <= now <= lease.admit_not_after:
            raise DispositionUnauthorizedError()
        return now


class PackageSelectionService:
    """Records one Human package selection; nothing in the request is trusted beyond its bound identity."""

    def __init__(self, *, sessions: Sessions, custodian: PackageSelectionCustodian, project_root: Path) -> None:
        self._sessions = sessions
        self._custodian = custodian
        self._project_root = project_root

    async def select(
        self, request: p.PackageSelectionRequest, lease: p.PackagingSelectionAuthorizationLease
    ) -> p.PackageSelection:
        if request.command.request_digest != compute_digest("m10.package-selection-request.v1", request):
            raise RequiredEvidenceMissingError()
        await self._custodian.require_actor(request)
        subject = request.subject
        user_id, project_name = subject.user_id, subject.project_name
        async with self._sessions() as session, session.begin():
            repository = PackageSelectionRepository(session)
            await repository.lock_command(request.command)
            replayed = await repository.replay_selection(request)
            if replayed is not None:
                return replayed
            preview = await repository.preview(
                user_id=user_id, project_name=project_name, preview_id=subject.preview_id
            )
            if preview is None or preview_digest(preview) != subject.preview_digest:
                raise SubjectStaleError()
            runs = QualityRunRepository(session)
            run = await runs.run(user_id=user_id, project_name=project_name, run_id=preview.quality_run_id)
            if run is None or run_digest(run) != preview.quality_run_digest:
                raise DispositionStaleError()
            # Global order: masters, profile head, run head, disposition head, preview, packaging head, grants.
            await lock_subject_masters(session, run.subject)
            await lock_profile_head(session, user_id=user_id, project_name=project_name, profile_id=run.profile_id)
            head_run = (
                await session.execute(
                    select(QualityRunHeadModel.current_run_id)
                    .filter_by(
                        user_id=user_id,
                        project_name=project_name,
                        subject_digest=run.subject_digest,
                        profile_id=run.profile_id,
                    )
                    .with_for_update(read=True)
                )
            ).scalar_one_or_none()
            head_disposition = (
                await session.execute(
                    select(DispositionHeadModel.current_disposition_id)
                    .filter_by(
                        user_id=user_id,
                        project_name=project_name,
                        subject_digest=run.subject_digest,
                        profile_id=run.profile_id,
                    )
                    .with_for_update(read=True)
                )
            ).scalar_one_or_none()
            if head_run != preview.quality_run_id or head_disposition != preview.disposition_id:
                raise DispositionStaleError()
            locked = await repository.preview(
                user_id=user_id, project_name=project_name, preview_id=subject.preview_id, for_update=True
            )
            if locked != preview:
                raise SubjectStaleError()
            _, version = await repository.lock_head(preview.slot, for_update=True)
            if version != preview.expected_head_version or version != subject.expected_head_version:
                raise StaleHeadError()
            evidence = await resolve_package_evidence(
                session,
                user_id=user_id,
                project_name=project_name,
                slot=preview.slot,
                candidate_id=preview.candidate_id,
                candidate_revision=preview.candidate_revision,
                candidate_payload_digest=preview.candidate_payload_digest,
                observation_id=preview.packaging_observation_id,
                selected_variant_ids=preview.selected_variant_ids,
                waivers=preview.waivers,
            )
            if (
                evidence.run.run_id != preview.quality_run_id
                or compute_digest("m10.packaging-observation.v1", evidence.observation)
                != preview.packaging_observation_digest
            ):
                raise SubjectStaleError()
            # One sorted grant-head set (selector and every Human assessor), as the A6 issuer takes it.
            await lock_grant_heads(
                session,
                user_id=user_id,
                project_name=project_name,
                principals={request.command.actor_id}
                | await human_principals(
                    session, user_id=user_id, project_name=project_name, observation_ids=list(run.observation_refs)
                ),
            )
            readiness, disposition, ready_run = await readiness_in(
                session,
                self._custodian.reader,
                project_root=self._project_root,
                user_id=user_id,
                project_name=project_name,
                subject_digest=run.subject_digest,
                profile_id=run.profile_id,
            )
            if (
                readiness.state != "READY"
                or disposition is None
                or ready_run is None
                or (disposition.disposition_id, disposition_digest(disposition), ready_run.run_id)
                != (preview.disposition_id, preview.disposition_digest, preview.quality_run_id)
            ):
                raise DispositionStaleError()
            now = await self._custodian.admit(session, request, lease)
            if now >= preview.expires_at:
                raise DispositionStaleError()
            selection = p.PackageSelection(
                selection_id=uuid7(),
                command_id=request.command.command_id,
                request_digest=request.command.request_digest,
                preview=preview,
                preview_digest=subject.preview_digest,
                head_version=version + 1,
                selector_id=request.command.actor_id,
                custodian_authorization_id=lease.authorization_id,
                custodian_policy_id=lease.policy_id,
                custodian_policy_version=lease.policy_version,
                custodian_evidence_digest=lease.evidence_digest,
                selected_at=now,
            )
            await repository.append_selection(request, selection)
        return selection


__all__ = [
    "PREVIEW_SECONDS",
    "SELECTION_POLICY_ID",
    "SELECTION_POLICY_VERSION",
    "PackageEvidence",
    "PackagePreviewService",
    "PackageSelectionCustodian",
    "PackageSelectionService",
    "resolve_package_evidence",
]
