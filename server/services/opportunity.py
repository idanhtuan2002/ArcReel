"""Host composition: scoped PostgreSQL profiles and read-only accepted M8 lineage."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.adaptation import AdaptationRepository
from lib.db.repositories.opportunity import OpportunityProfileRepository, OpportunityUnitOfWork
from lib.db.repositories.opportunity_acquisition import AcquisitionTransaction, OpportunityAcquisitionUnitOfWork
from r2.advanced_creative.errors import LineageAmbiguousError
from r2.advanced_creative.exploration import uuid7
from r2.advanced_creative.lineage import project_profile
from r2.opportunity.acquisition import OpportunityAcquisitionService
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.ports import MarketSourcePort, SnapshotEvidenceStore, SourceCapabilityPort
from r2.opportunity.profiles import OpportunityProfileService
from server.auth import CurrentUserInfo
from server.services.governance_grants import CurrentShowrunnerGrantReader
from server.services.m9_custodian import M9ProfileCustodian

if TYPE_CHECKING:
    from r2.opportunity.acquisition_v2 import ManualCleanupPort, ManualUploadMetadata, OpportunityAcquisitionServiceV2
    from r2.opportunity.manual_admission import ManualBindingDescriptor, ManualBindingRegistry


class HostProfileTransaction(OpportunityProfileRepository):
    async def creative_policy_identity(self, *, user_id: str, project_name: str) -> tuple[str, str, str]:
        # The table lock covers new head keys as well as transitions of existing heads.
        # Accepted adaptation writers always INSERT before taking a per-head row lock.
        await self.session.execute(text("LOCK TABLE adaptation_heads IN SHARE MODE"))
        admissions = await AdaptationRepository(self.session).list_effective_screenplay_admissions(
            user_id=user_id, project_name=project_name
        )
        try:
            return project_profile(admissions)
        except LineageAmbiguousError:
            raise OpportunityError(StopCode.M9_COHORT_LEAKAGE) from None


class HostProfileUnitOfWork(OpportunityUnitOfWork):
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[HostProfileTransaction]:
        async with super().transaction() as repo:
            yield HostProfileTransaction(repo.session, guard_key=self.guard_key)


def build_profile_service(
    sessions: async_sessionmaker[AsyncSession],
    *,
    grants: CurrentShowrunnerGrantReader | None,
    current_user: CurrentUserInfo,
    project_name: str,
) -> OpportunityProfileService:
    custodian = M9ProfileCustodian(
        sessions, grants=grants, user_id=current_user.id, project_name=project_name, actor_id=current_user.sub
    )
    return OpportunityProfileService(
        store=HostProfileUnitOfWork(sessions),
        custodian=custodian,
        user_id=current_user.id,
        project_name=project_name,
        actor_id=current_user.sub,
    )


class HostAcquisitionTransaction(AcquisitionTransaction):
    async def creative_policy_identity(self) -> tuple[str, str, str]:
        return await HostProfileTransaction(self.session).creative_policy_identity(
            user_id=self.user_id, project_name=self.project_name
        )


class HostAcquisitionUnitOfWork(OpportunityAcquisitionUnitOfWork):
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[HostAcquisitionTransaction]:
        async with super().transaction() as tx:
            yield HostAcquisitionTransaction(
                tx.session, user_id=self.user_id, project_name=self.project_name, guard_key=self.guard_key
            )


def build_acquisition_service(
    sessions: async_sessionmaker[AsyncSession],
    *,
    current_user: CurrentUserInfo,
    project_name: str,
    capabilities: SourceCapabilityPort | None = None,
    source: MarketSourcePort | None = None,
    evidence: SnapshotEvidenceStore | None = None,
) -> OpportunityAcquisitionService:
    return OpportunityAcquisitionService(
        store=HostAcquisitionUnitOfWork(sessions, user_id=current_user.id, project_name=project_name),
        capabilities=capabilities,
        source=source,
        evidence=evidence,
        new_id=uuid7,
        user_id=current_user.id,
        project_name=project_name,
        actor_id=current_user.sub,
    )


def build_acquisition_service_for_protocol(
    sessions: async_sessionmaker[AsyncSession],
    *,
    protocol_version: str,
    current_user: CurrentUserInfo,
    project_name: str,
    capabilities: SourceCapabilityPort | None = None,
    source: MarketSourcePort | None = None,
    evidence: SnapshotEvidenceStore | None = None,
    registry: ManualBindingRegistry | None = None,
    descriptor: ManualBindingDescriptor | None = None,
    upload: ManualUploadMetadata | None = None,
    cleanup: ManualCleanupPort | None = None,
) -> OpportunityAcquisitionService | OpportunityAcquisitionServiceV2:
    if protocol_version == "m9.acquisition.v1":
        if registry is not None or descriptor is not None or upload is not None or cleanup is not None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        return build_acquisition_service(
            sessions,
            current_user=current_user,
            project_name=project_name,
            capabilities=capabilities,
            source=source,
            evidence=evidence,
        )
    if protocol_version == "m9.acquisition.v2":
        from server.services.opportunity_acquisition_v2 import build_acquisition_service_v2

        if source is not None or evidence is not None:
            raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
        return build_acquisition_service_v2(
            sessions,
            current_user=current_user,
            project_name=project_name,
            capabilities=capabilities,
            registry=registry,
            descriptor=descriptor,
            upload=upload,
            cleanup=cleanup,
        )
    raise OpportunityError(StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE)
