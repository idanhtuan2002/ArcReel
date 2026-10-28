"""M10-B packaging API: candidate revisions, checks, previews, Human selection, export and download.

The user comes from the session and the project from the path; every command envelope is built here from the
authenticated principal, never accepted from the client. Selection and export need an interactive session
(a Human showrunner custodian lease for selection). Downloads use a short-lived token scoped to one export and
revalidate that the export is still the slot's current, ready selection.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from lib.api_errors import ApiError, ConflictError, NotFoundError, ServiceUnavailableError, UnprocessableError
from lib.db import async_session_factory
from lib.db.base import DEFAULT_USER_ID
from lib.project_manager import get_project_manager
from r2.advanced_creative.errors import ExplorationNotFoundError, M8Error
from r2.contracts import packaging as p
from r2.contracts import quality as q
from r2.quality.digests import compute_digest
from r2.quality.errors import (
    CommandReplayConflictError,
    DispositionUnauthorizedError,
    M10Error,
    StaleHeadError,
)
from server.auth import (
    CurrentUser,
    InteractiveUser,
    get_current_interactive_user,
    get_token_secret,
    is_auth_enabled,
    oauth2_scheme_optional,
)
from server.services.governance_grants import CheckpointedShowrunnerGrantReader
from server.services.governance_startup import verify_governance_activated_startup
from server.services.package_export import Download, PackageExportService
from server.services.packaging_candidates import PackagingDraft, append_packaging_revision
from server.services.quality_package_selection import (
    PackagePreviewService,
    PackageSelectionCustodian,
    PackageSelectionService,
)
from server.services.quality_packaging import PackagingCheckService

router = APIRouter()
#: Registered without the Bearer dependency: the scoped export token in the query authenticates the download.
download_router = APIRouter()

PACKAGING_REQUEST_INVALID = "m10_packaging_request_invalid"
PACKAGING_UNAVAILABLE = "m10_packaging_unavailable"
EXPORT_TOKEN_PURPOSE = "m10-export"
EXPORT_TOKEN_SECONDS = 300

Token = Annotated[str | None, Depends(oauth2_scheme_optional)]


@dataclass(frozen=True)
class PackagingDeps:
    """Everything the routes need from the host; tests override the whole dependency."""

    sessions: Any
    project_root: Callable[[str], Path]
    grant_reader: Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]] | None
    read_directory: Path | None
    socket_directory: Path | None


def packaging_deps() -> PackagingDeps:
    read_dir = os.environ.get("ARCREEL_GOVERNANCE_READ_DIR")
    socket_dir = os.environ.get("ARCREEL_GOVERNANCE_ATTESTOR_DIR")
    reader: Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]] | None = None
    if read_dir and socket_dir:
        read_path, socket_path = Path(read_dir), Path(socket_dir)

        async def activated() -> CheckpointedShowrunnerGrantReader:
            return await verify_governance_activated_startup(
                read_path, socket_path, session_factory=async_session_factory
            )

        reader = activated
    return PackagingDeps(
        sessions=async_session_factory,
        project_root=lambda name: Path(get_project_manager().get_project_path(name)),
        grant_reader=reader,
        read_directory=None if not read_dir else Path(read_dir),
        socket_directory=None if not socket_dir else Path(socket_dir),
    )


Deps = Annotated[PackagingDeps, Depends(packaging_deps)]


def _api_error(error: Exception) -> ApiError:
    if isinstance(error, ExplorationNotFoundError):
        return NotFoundError(error.code)
    if isinstance(error, M8Error):
        return ConflictError(error.code)
    if isinstance(error, DispositionUnauthorizedError):
        return ApiError(error.code, status_code=403)
    if isinstance(error, (CommandReplayConflictError, StaleHeadError)):
        return ConflictError(error.code)
    if isinstance(error, M10Error):
        return ConflictError(error.code)
    return UnprocessableError(PACKAGING_REQUEST_INVALID)


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except (M10Error, M8Error, ValueError) as error:
        raise _api_error(error) from error


def _reader(deps: PackagingDeps) -> Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]:
    if deps.grant_reader is None:
        raise ServiceUnavailableError(PACKAGING_UNAVAILABLE)
    return deps.grant_reader


def _command(user_id: str, project: str, actor_id: str, operation: str, command_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "project_name": project,
        "actor_id": actor_id,
        "operation": operation,
        "command_id": command_id,
        "request_digest": "sha256:" + "0" * 64,
    }


def _sealed[M: q.M10ContractModel](model: type[M], domain: str, body: dict[str, Any]) -> M:
    """Build a request with its server-computed request digest; a malformed body is a 422."""
    try:
        body["command"]["request_digest"] = compute_digest(domain, body)
        return model.model_validate(body)
    except ValueError as error:
        raise UnprocessableError(PACKAGING_REQUEST_INVALID) from error


async def _author_kind(token: str | None) -> str:
    try:
        await get_current_interactive_user(token)
    except HTTPException:
        return "AGENT"
    return "HUMAN"


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RevisionBody(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    quality_run_id: str
    candidate_id: str | None = None
    expected_head_version: int | None = None
    draft: PackagingDraft


class CheckBody(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    candidate_id: str
    candidate_revision: int
    candidate_payload_digest: str
    quality_run_id: str
    quality_run_digest: str


class PreviewBody(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    source_artifact_key: str
    cohort_id: str
    product_surface: str
    candidate_id: str
    candidate_revision: int
    candidate_payload_digest: str
    packaging_observation_id: str
    selected_variant_ids: list[str]
    waivers: list[dict[str, str]]


class SelectionBody(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    preview_id: str
    preview_digest: str
    expected_head_version: int


class ExportBody(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    source_artifact_key: str
    cohort_id: str
    product_surface: str
    selection_id: str
    selection_digest: str


@router.post("/projects/{project_name}/packaging/revisions")
async def append_revision(
    project_name: str, body: RevisionBody, user: CurrentUser, token: Token, deps: Deps
) -> dict[str, Any]:
    author = await _author_kind(token)

    async def operation() -> dict[str, Any]:
        revision, head = await append_packaging_revision(
            deps.sessions,
            user_id=user.id,
            project_name=project_name,
            actor_id=user.sub,
            author_kind=author,  # pyright: ignore[reportArgumentType]
            run_id=body.quality_run_id,
            candidate_id=body.candidate_id,
            expected_head_version=body.expected_head_version,
            command_id=body.command_id,
            draft=body.draft,
            clock=lambda: datetime.now(UTC),
        )
        return {"revision": revision.model_dump(mode="json"), "head": head.model_dump(mode="json")}

    return await _run(operation)


@router.post("/projects/{project_name}/packaging/checks")
async def check_package(project_name: str, body: CheckBody, user: CurrentUser, deps: Deps) -> dict[str, Any]:
    request = _sealed(
        p.PackageCheckRequest,
        "m10.package-check-request.v1",
        {
            "command": _command(user.id, project_name, user.sub, "CHECK_PACKAGE", body.command_id),
            "subject": {"user_id": user.id, "project_name": project_name, "actor_id": user.sub}
            | body.model_dump(exclude={"command_id"}),
        },
    )
    service = PackagingCheckService(
        sessions=deps.sessions, project_root=deps.project_root(project_name), clock=lambda: datetime.now(UTC)
    )
    observation = await _run(lambda: service.check(request))
    return observation.model_dump(mode="json")


def _slot(user_id: str, project: str, body: PreviewBody | ExportBody) -> dict[str, str]:
    return {
        "user_id": user_id,
        "project_name": project,
        "source_artifact_key": body.source_artifact_key,
        "cohort_id": body.cohort_id,
        "product_surface": body.product_surface,
    }


@router.post("/projects/{project_name}/packaging/previews")
async def preview_package(project_name: str, body: PreviewBody, user: CurrentUser, deps: Deps) -> dict[str, Any]:
    subject = body.model_dump(exclude={"command_id", "source_artifact_key", "cohort_id", "product_surface"})
    request = _sealed(
        p.PackagePreviewRequest,
        "m10.package-preview-request.v1",
        {
            "command": _command(user.id, project_name, user.sub, "PREVIEW_PACKAGE", body.command_id),
            "subject": {
                "user_id": user.id,
                "project_name": project_name,
                "actor_id": user.sub,
                "slot": _slot(user.id, project_name, body),
            }
            | subject,
        },
    )
    service = PackagePreviewService(
        sessions=deps.sessions, grant_reader=_reader(deps), project_root=deps.project_root(project_name)
    )
    preview = await _run(lambda: service.preview(request))
    return {
        "preview": preview.model_dump(mode="json"),
        "preview_digest": compute_digest("m10.package-preview.v1", preview),
    }


@router.post("/projects/{project_name}/packaging/selections")
async def select_package(
    project_name: str, body: SelectionBody, user: InteractiveUser, token: Token, deps: Deps
) -> dict[str, Any]:
    if deps.read_directory is None or deps.socket_directory is None:
        raise ServiceUnavailableError(PACKAGING_UNAVAILABLE)
    request = _sealed(
        p.PackageSelectionRequest,
        "m10.package-selection-request.v1",
        {
            "command": _command(user.id, project_name, user.sub, "SELECT_PACKAGE", body.command_id),
            "subject": {"user_id": user.id, "project_name": project_name, "actor_id": user.sub}
            | body.model_dump(exclude={"command_id"}),
        },
    )
    custodian = PackageSelectionCustodian(
        request,
        deps.sessions,
        interactive_token=token,
        read_directory=deps.read_directory,
        socket_directory=deps.socket_directory,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    service = PackageSelectionService(
        sessions=deps.sessions, custodian=custodian, project_root=deps.project_root(project_name)
    )

    async def operation() -> p.PackageSelection:
        lease = await custodian.authorize_selection(request)
        return await service.select(request, lease)

    selection = await _run(operation)
    return selection.model_dump(mode="json") | {
        "selection_digest": compute_digest("m10.package-selection.v1", selection)
    }


def _export_request(user_id: str, actor: str, project: str, body: ExportBody) -> p.ExportRequest:
    return _sealed(
        p.ExportRequest,
        "m10.export-request.v1",
        {
            "command": _command(user_id, project, actor, "EXPORT_PACKAGE", body.command_id),
            "subject": {
                "user_id": user_id,
                "project_name": project,
                "actor_id": actor,
                "slot": _slot(user_id, project, body),
                "selection_id": body.selection_id,
                "selection_digest": body.selection_digest,
            },
        },
    )


@router.post("/projects/{project_name}/packaging/exports")
async def export_package(
    project_name: str, body: ExportBody, user: InteractiveUser, token: Token, deps: Deps
) -> dict[str, Any]:
    request = _export_request(user.id, user.sub, project_name, body)
    service = PackageExportService(
        sessions=deps.sessions,
        grant_reader=_reader(deps),
        project_root=deps.project_root(project_name),
        interactive_token=token,
    )
    receipt = await _run(lambda: service.export(request))
    return receipt.model_dump(mode="json") | {
        "download_token": create_export_token(user.sub, project_name, receipt.archive_digest)
    }


def create_export_token(subject: str, project_name: str, archive_digest: str) -> str:
    now = time.time()
    payload = {
        "sub": subject,
        "project": project_name,
        "purpose": EXPORT_TOKEN_PURPOSE,
        "archive": archive_digest,
        "iat": now,
        "exp": now + EXPORT_TOKEN_SECONDS,
    }
    return jwt.encode(payload, get_token_secret(), algorithm="HS256")


def _verify_export_token(token: str, project_name: str, archive_digest: str) -> str:
    """The token's subject when it is a current, well-formed m10-export token for exactly this archive."""
    if not is_auth_enabled():
        return "anonymous"
    try:
        payload = jwt.decode(
            token, get_token_secret(), algorithms=["HS256"], options={"require": ["exp", "iat", "sub"]}
        )
    except jwt.InvalidTokenError as error:
        raise ApiError("download_expired", status_code=401) from error
    issued, expires, subject = payload.get("iat"), payload.get("exp"), payload.get("sub")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(issued, (int, float))
        or not isinstance(expires, (int, float))
        or not 0 < expires - issued <= EXPORT_TOKEN_SECONDS
    ):
        raise ApiError("download_expired", status_code=401)
    if (payload.get("purpose"), payload.get("project"), payload.get("archive")) != (
        EXPORT_TOKEN_PURPOSE,
        project_name,
        archive_digest,
    ):
        raise ApiError("download_token_mismatch", status_code=403)
    return subject


class _ClosingStream(StreamingResponse):
    """Releases the download's snapshot and scratch however the response ends: done, failed or cancelled."""

    def __init__(self, download: Download, content: Any, **kwargs: Any) -> None:
        super().__init__(content, **kwargs)
        self._download = download

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await asyncio.to_thread(self._download.close)


@download_router.get("/projects/{project_name}/packaging/exports/{archive_hex}/archive")
async def download_export(project_name: str, archive_hex: str, token: str, deps: Deps) -> StreamingResponse:
    if len(archive_hex) != 64 or any(c not in "0123456789abcdef" for c in archive_hex):
        raise NotFoundError(PACKAGING_REQUEST_INVALID)
    digest = "sha256:" + archive_hex
    _verify_export_token(token, project_name, digest)
    service = PackageExportService(
        sessions=deps.sessions,
        grant_reader=_reader(deps),
        project_root=deps.project_root(project_name),
        interactive_token=None,
    )
    download = await _run(lambda: service.open_download(DEFAULT_USER_ID, project_name, digest))

    def chunks():
        with os.fdopen(os.dup(download.descriptor), "rb", buffering=0) as handle:
            while chunk := handle.read(1 << 20):
                yield chunk

    return _ClosingStream(
        download,
        chunks(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="package-{archive_hex[:12]}.zip"'},
    )


__all__ = ["PackagingDeps", "create_export_token", "download_router", "packaging_deps", "router"]
