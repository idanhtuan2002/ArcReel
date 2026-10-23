"""Application-owned V2 SQL transactions reuse the existing scoped host policy."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.opportunity_manual_admission import ManualAdmissionTransaction
from r2.advanced_creative.exploration import uuid7
from r2.opportunity.acquisition_v2 import ManualCleanupPort, ManualUploadMetadata, OpportunityAcquisitionServiceV2
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import ManualBindingDescriptor, ManualBindingRegistry
from r2.opportunity.ports import SourceCapabilityPort
from server.auth import CurrentUserInfo
from server.services.opportunity import HostAcquisitionTransaction


class HostManualAdmissionTransaction(ManualAdmissionTransaction):
    async def creative_policy_identity(self) -> tuple[str, str, str]:
        return await HostAcquisitionTransaction(
            self.session, user_id=self.user_id, project_name=self.project_name
        ).creative_policy_identity()


class HostManualAdmissionUnitOfWork:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, user_id: str, project_name: str) -> None:
        self.sessions, self.user_id, self.project_name = sessions, user_id, project_name

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[HostManualAdmissionTransaction]:
        async with self.sessions() as session, session.begin():
            if session.get_bind().dialect.name != "postgresql":
                raise OpportunityError(StopCode.M9_REQUIRED_EVIDENCE_MISSING)
            yield HostManualAdmissionTransaction(session, user_id=self.user_id, project_name=self.project_name)


def build_acquisition_service_v2(
    sessions: async_sessionmaker[AsyncSession],
    *,
    current_user: CurrentUserInfo,
    project_name: str,
    registry: ManualBindingRegistry | None = None,
    descriptor: ManualBindingDescriptor | None = None,
    upload: ManualUploadMetadata | None = None,
    capabilities: SourceCapabilityPort | None = None,
    cleanup: ManualCleanupPort | None = None,
) -> OpportunityAcquisitionServiceV2:
    return OpportunityAcquisitionServiceV2(
        store=HostManualAdmissionUnitOfWork(sessions, user_id=current_user.id, project_name=project_name),
        registry=registry,
        descriptor=descriptor,
        upload=upload,
        capabilities=capabilities,
        cleanup=cleanup,
        new_id=uuid7,
        user_id=current_user.id,
        project_name=project_name,
        actor_id=current_user.sub,
    )
