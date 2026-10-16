"""Authenticated, owner-scoped M9 cohort profile commands and immutable reads."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from lib.api_errors import ApiError, NotFoundError, UnprocessableError
from lib.db import async_session_factory
from r2.contracts.advanced_creative import M8ContractModel
from r2.contracts.opportunity import (
    CohortProfileReceipt,
    CommandContext,
    OpportunityCohortProfile,
    OpportunityCohortProfilePayload,
    OpportunityIdentityRead,
    OpportunityReadPage,
    PublishOpportunityCohortProfile,
)
from r2.opportunity.errors import OpportunityError, StopCode
from r2.opportunity.profiles import OpportunityProfileNotFoundError, OpportunityProfileService
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.services.opportunity import build_profile_service

router = APIRouter()
type ProfileServiceFactory = Callable[[CurrentUserInfo, str], OpportunityProfileService]
Interactive = Annotated[CurrentUserInfo, Depends(get_current_interactive_user)]
CurrentUser = Annotated[CurrentUserInfo, Depends(get_current_user)]


class PublishCohortProfileRequest(M8ContractModel):
    command_id: str
    profile_id: str
    parent_revision: int | None
    expected_head_version: int | None
    payload: OpportunityCohortProfilePayload


def profile_service_factory(request: Request) -> ProfileServiceFactory:
    grants = getattr(request.app.state, "governance_grants", None)
    return lambda user, project: build_profile_service(
        async_session_factory, grants=grants, current_user=user, project_name=project
    )


Factory = Annotated[ProfileServiceFactory, Depends(profile_service_factory)]
_PREFIX = "/projects/{project_name}/m9/opportunity/cohort-profiles"


def _api_error(error: OpportunityError) -> ApiError:
    code = error.code
    status, key = 503, "m9_required_evidence_missing"
    if code is StopCode.M9_PROFILE_PUBLICATION_UNAUTHORIZED:
        status, key = 403, "m9_profile_publication_unauthorized"
    elif code in {StopCode.M9_COMMAND_REPLAY_CONFLICT, StopCode.M9_STALE_HEAD, StopCode.M9_COHORT_LEAKAGE}:
        status, key = 409, code.value.lower()
    return ApiError(key, status_code=status).with_diagnostic({"stop_code": code.value})


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except OpportunityProfileNotFoundError:
        raise NotFoundError("resource_not_found") from None
    except OpportunityError as error:
        raise _api_error(error) from None
    except ValueError:
        raise UnprocessableError("m9_profile_invalid") from None


@router.post(_PREFIX, response_model=CohortProfileReceipt)
async def publish_profile(
    project_name: str, body: PublishCohortProfileRequest, current_user: Interactive, factory: Factory
) -> CohortProfileReceipt:
    async def operation() -> CohortProfileReceipt:
        context = CommandContext(
            command_id=body.command_id, user_id=current_user.id, project_name=project_name, actor_id=current_user.sub
        )
        command = PublishOpportunityCohortProfile(
            context=context,
            profile_id=body.profile_id,
            parent_revision=body.parent_revision,
            expected_head_version=body.expected_head_version,
            payload=body.payload,
        )
        return await factory(current_user, project_name).publish_cohort_profile(command)

    return await _run(operation)


@router.get(_PREFIX, response_model=tuple[OpportunityCohortProfile, ...])
async def list_profiles(
    project_name: str,
    current_user: CurrentUser,
    factory: Factory,
    after_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> tuple[OpportunityCohortProfile, ...]:
    async def operation() -> tuple[OpportunityCohortProfile, ...]:
        request = OpportunityReadPage(
            user_id=current_user.id, project_name=project_name, after_id=after_id, limit=limit
        )
        return await factory(current_user, project_name).list_cohort_profiles(request)

    return await _run(operation)


@router.get(_PREFIX + "/{profile_id}", response_model=OpportunityCohortProfile)
async def get_profile(
    project_name: str,
    profile_id: str,
    current_user: CurrentUser,
    factory: Factory,
    revision: Annotated[int | None, Query(ge=1)] = None,
) -> OpportunityCohortProfile:
    async def operation() -> OpportunityCohortProfile:
        request = OpportunityIdentityRead(
            user_id=current_user.id, project_name=project_name, identity=profile_id, revision=revision
        )
        return await factory(current_user, project_name).get_cohort_profile(request)

    return await _run(operation)
