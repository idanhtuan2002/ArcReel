"""Authenticated, owner-scoped M9 source queries, V2 manual acquisitions and their immutable readers.

Owner, project and actor come only from the authenticated scope. Mutations are interactive-only; reads accept the
existing API-key principal. Acquisition requests name `protocol_version` explicitly and only the V2 protocol is
served; host ports (manual binding registry, upload metadata, capability resolver) come from the application host and
their absence refuses before any source or custody contact.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from lib.api_errors import ApiError, NotFoundError, UnprocessableError
from lib.db import async_session_factory
from r2.contracts.advanced_creative import M8ContractModel, Sha256Digest
from r2.contracts.opportunity import (
    CommandContext,
    DeclareSourceQuery,
    OpportunityIdentityRead,
    OpportunityReadPage,
    QueryReceipt,
    SnapshotReadPage,
    SourceCapabilityGrant,
    SourceQuery,
    SourceQueryDraft,
)
from r2.contracts.opportunity_acquisition_v2 import (
    AcquireSourceQueryV2,
    AcquisitionReceiptV2,
    SourceSnapshotViewV2,
)
from r2.opportunity.acquisition import OpportunityAcquisitionService
from r2.opportunity.acquisition_v2 import ManualUploadMetadata, OpportunityAcquisitionServiceV2
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.manual_admission import ManualBindingDescriptor, ManualBindingRegistry
from r2.opportunity.ports import SourceCapabilityPort
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.services.opportunity import build_acquisition_service
from server.services.opportunity_acquisition_v2 import build_acquisition_service_v2

router = APIRouter()
Interactive = Annotated[CurrentUserInfo, Depends(get_current_interactive_user)]
CurrentUser = Annotated[CurrentUserInfo, Depends(get_current_user)]
type QueryServiceFactory = Callable[[CurrentUserInfo, str], OpportunityAcquisitionService]
type AcquisitionServiceFactory = Callable[[CurrentUserInfo, str], OpportunityAcquisitionServiceV2]
_PREFIX = "/projects/{project_name}/m9/opportunity"


@dataclass(frozen=True)
class ManualAcquisitionHost:
    """Host-configured ports for the V2 manual protocol; an unconfigured host serves none of them."""

    capabilities: SourceCapabilityPort | None = None
    registry: ManualBindingRegistry | None = None
    descriptor: ManualBindingDescriptor | None = None
    upload: ManualUploadMetadata | None = None


def _host(request: Request) -> ManualAcquisitionHost:
    host = getattr(request.app.state, "m9_manual_acquisition_host", None)
    return host if isinstance(host, ManualAcquisitionHost) else ManualAcquisitionHost()


def query_service_factory(request: Request) -> QueryServiceFactory:
    host = _host(request)
    return lambda user, project: build_acquisition_service(
        async_session_factory, current_user=user, project_name=project, capabilities=host.capabilities
    )


def acquisition_service_factory(request: Request) -> AcquisitionServiceFactory:
    host = _host(request)
    return lambda user, project: build_acquisition_service_v2(
        async_session_factory,
        current_user=user,
        project_name=project,
        capabilities=host.capabilities,
        registry=host.registry,
        descriptor=host.descriptor,
        upload=host.upload,
    )


QueryFactory = Annotated[QueryServiceFactory, Depends(query_service_factory)]
AcquisitionFactory = Annotated[AcquisitionServiceFactory, Depends(acquisition_service_factory)]


class DeclareQueryRequest(M8ContractModel):
    command_id: str
    query_id: str
    parent_revision: int | None
    expected_head_version: int | None
    draft: SourceQueryDraft


class AcquireRequest(M8ContractModel):
    protocol_version: Literal["m9.acquisition.v2"]
    command_id: str
    query_id: str
    query_revision: int
    query_digest: Sha256Digest
    expected_query_head_version: int


_CONFLICT = {
    StopCode.M9_COMMAND_REPLAY_CONFLICT,
    StopCode.M9_STALE_HEAD,
    StopCode.M9_EVIDENCE_STALE,
    StopCode.M9_ACQUISITION_OUTCOME_UNKNOWN,
}
_FORBIDDEN = {StopCode.M9_SOURCE_POLICY_FORBIDDEN, StopCode.M9_CREDENTIAL_REFERENCE_INVALID}


def api_error(error: OpportunityError) -> ApiError:
    code = error.code
    if code is StopCode.M9_STALE_HEAD:
        status, key = 409, "m9_query_stale_head"
    elif code in _CONFLICT:
        status, key = 409, code.value.lower()
    elif code in _FORBIDDEN:
        status, key = 403, code.value.lower()
    elif code is StopCode.M9_EVIDENCE_RETENTION_EXPIRED:
        status, key = 410, "m9_evidence_retention_expired"
    elif code is StopCode.M9_SOURCE_CAPABILITY_UNAVAILABLE:
        status, key = 503, "m9_source_capability_unavailable"
    else:
        status, key = 503, "m9_acquisition_evidence_missing"
    return ApiError(key, status_code=status).with_diagnostic({"stop_code": code.value})


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except LookupError:
        raise NotFoundError("resource_not_found") from None
    except OpportunityError as error:
        raise api_error(error) from None
    except ValueError:
        raise UnprocessableError("m9_acquisition_invalid") from None


def _context(command_id: str, user: CurrentUserInfo, project_name: str) -> CommandContext:
    return CommandContext(command_id=command_id, user_id=user.id, project_name=project_name, actor_id=user.sub)


@router.post(_PREFIX + "/queries", response_model=QueryReceipt)
async def declare_query(
    project_name: str, body: DeclareQueryRequest, current_user: Interactive, factory: QueryFactory
) -> QueryReceipt:
    async def operation() -> QueryReceipt:
        command = DeclareSourceQuery(
            context=_context(body.command_id, current_user, project_name),
            query_id=body.query_id,
            parent_revision=body.parent_revision,
            expected_head_version=body.expected_head_version,
            draft=body.draft,
        )
        return await factory(current_user, project_name).declare_query(command)

    return await _run(operation)


@router.get(_PREFIX + "/queries/{query_id}", response_model=SourceQuery)
async def get_query(
    project_name: str,
    query_id: str,
    current_user: CurrentUser,
    factory: AcquisitionFactory,
    revision: Annotated[int | None, Query(ge=1)] = None,
) -> SourceQuery:
    async def operation() -> SourceQuery:
        request = OpportunityIdentityRead(
            user_id=current_user.id, project_name=project_name, identity=query_id, revision=revision
        )
        return await factory(current_user, project_name).get_query(request)

    return await _run(operation)


@router.post(_PREFIX + "/acquisitions", response_model=AcquisitionReceiptV2)
async def acquire(
    project_name: str, body: AcquireRequest, current_user: Interactive, factory: AcquisitionFactory
) -> AcquisitionReceiptV2:
    async def operation() -> AcquisitionReceiptV2:
        command = AcquireSourceQueryV2(
            protocol_version=body.protocol_version,
            context=_context(body.command_id, current_user, project_name),
            query_id=body.query_id,
            query_revision=body.query_revision,
            query_digest=body.query_digest,
            expected_query_head_version=body.expected_query_head_version,
        )
        return await factory(current_user, project_name).acquire(command)

    return await _run(operation)


@router.get(_PREFIX + "/capabilities", response_model=tuple[SourceCapabilityGrant, ...])
async def list_capabilities(
    project_name: str,
    current_user: CurrentUser,
    factory: AcquisitionFactory,
    after_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> tuple[SourceCapabilityGrant, ...]:
    async def operation() -> tuple[SourceCapabilityGrant, ...]:
        request = OpportunityReadPage(
            user_id=current_user.id, project_name=project_name, after_id=after_id, limit=limit
        )
        return await factory(current_user, project_name).list_capabilities(request)

    return await _run(operation)


@router.get(_PREFIX + "/snapshots", response_model=tuple[SourceSnapshotViewV2, ...])
async def list_snapshots(
    project_name: str,
    current_user: CurrentUser,
    factory: AcquisitionFactory,
    query_id: str,
    after_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> tuple[SourceSnapshotViewV2, ...]:
    async def operation() -> tuple[SourceSnapshotViewV2, ...]:
        request = SnapshotReadPage(
            user_id=current_user.id, project_name=project_name, query_id=query_id, after_id=after_id, limit=limit
        )
        return await factory(current_user, project_name).list_snapshots(request)

    return await _run(operation)


@router.get(_PREFIX + "/snapshots/{snapshot_id}", response_model=SourceSnapshotViewV2)
async def get_snapshot(
    project_name: str,
    snapshot_id: str,
    current_user: CurrentUser,
    factory: AcquisitionFactory,
    revision: Annotated[int | None, Query(ge=1)] = None,
) -> SourceSnapshotViewV2:
    async def operation() -> SourceSnapshotViewV2:
        request = OpportunityIdentityRead(
            user_id=current_user.id, project_name=project_name, identity=snapshot_id, revision=revision
        )
        return await factory(current_user, project_name).get_snapshot(request)

    return await _run(operation)
