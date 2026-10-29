"""M10-C quality operator routes: profiles, probes, Human review, run sealing and dispositions.

Every mutation is prepare/submit: prepare builds the complete service request on the server and seals it; submit
accepts only that sealed request back and passes it to the accepted service unchanged, so a retry replays the
service receipt. Mutations need an interactive session (the embedded-agent token is refused); the routes are
unavailable when authentication is disabled.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

import r2.contracts.quality as q
from lib.api_errors import ApiError, ConflictError, NotFoundError, ServiceUnavailableError, UnprocessableError
from lib.artifact_manifest import ArtifactManifestError, ProjectArtifactManifestAdapter
from lib.db import async_session_factory
from lib.db.models.quality import QualityProfileHeadModel, QualityProfileRevisionModel
from lib.db.models.quality_dispositions import DispositionHeadModel
from lib.db.models.quality_probes import QualityProbeObservationModel
from lib.db.models.quality_runs import QualityHumanObservationModel, QualityRunModel
from lib.db.repositories.quality import QualityProfileRepository
from lib.db.repositories.quality_runs import QualityRunRepository
from lib.project_manager import get_project_manager
from r2.contracts.artifact_metadata import R2ArtifactMetadata
from r2.quality.digests import compute_digest
from r2.quality.errors import DispositionUnauthorizedError, M10Error, ProfilePublicationUnauthorizedError
from r2.quality.host_catalog import HOST_CATALOG, HOST_CATALOG_ID
from r2.quality.ports import ProbeRequest
from r2.quality.probes import DEFAULT_PROBE_CATALOG, ProbeCatalog
from r2.quality.runs import HumanObservationRequest, run_digest
from server.auth import CurrentUser, InteractiveUser, get_token_secret, is_auth_enabled, oauth2_scheme_optional
from server.services.governance_grants import CheckpointedShowrunnerGrantReader
from server.services.quality_dispositions import DispositionCustodian, DispositionService, quality_readiness
from server.services.quality_prepare import Action, seal, unseal
from server.services.quality_probe_runtime import ProbeHost, QualityProbeRuntime
from server.services.quality_probes import QualityProbeService
from server.services.quality_profile_custodian import InteractiveProfilePublicationCustodian
from server.services.quality_profiles import ProfilePublicationService
from server.services.quality_requests import (
    completion_request,
    disposition_request,
    probe_request,
    publication_request,
    review_request,
)
from server.services.quality_runs import HumanObservationService, QualityRunService, run_validity
from server.services.quality_subjects import resolve_assessed_subject
from server.services.quality_template import default_platform_constraints, quality_policy

router = APIRouter()

QUALITY_UNAVAILABLE = "m10_quality_unavailable"
QUALITY_REQUEST_INVALID = "m10_quality_request_invalid"
QUALITY_UNAUTHORIZED = "m10_quality_unauthorized"
CATALOG_ENV = "ARCREEL_QUALITY_PROBE_CATALOG"

Token = Annotated[str | None, Depends(oauth2_scheme_optional)]


@dataclass(frozen=True)
class QualityDeps:
    """Everything the routes need from the host; tests override the whole dependency."""

    sessions: Any
    project_root: Callable[[str], Path]
    grant_reader: Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]] | None
    read_directory: Path | None
    socket_directory: Path | None
    catalog: ProbeCatalog | None
    runtime: QualityProbeRuntime
    secret: str
    # Owner of the governance archive and attestor socket; root on an activated host (ADR-0103).
    custody_uid: int = 0
    custody_gid: int = 0


def quality_deps(request: Request) -> QualityDeps:
    read_dir = os.environ.get("ARCREEL_GOVERNANCE_READ_DIR")
    socket_dir = os.environ.get("ARCREEL_GOVERNANCE_ATTESTOR_DIR")
    granted: CheckpointedShowrunnerGrantReader | None = getattr(request.app.state, "governance_grants", None)
    reader: Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]] | None = None
    if granted is not None and read_dir and socket_dir:
        verified = granted

        async def activated() -> CheckpointedShowrunnerGrantReader:
            return verified

        reader = activated
    return QualityDeps(
        sessions=async_session_factory,
        project_root=lambda name: Path(get_project_manager().get_project_path(name)),
        grant_reader=reader,
        read_directory=None if not read_dir else Path(read_dir),
        socket_directory=None if not socket_dir else Path(socket_dir),
        catalog=HOST_CATALOG if os.environ.get(CATALOG_ENV) == HOST_CATALOG_ID else None,
        runtime=QualityProbeRuntime(
            ProbeHost(tools={"ffmpeg": Path("/usr/bin/ffmpeg"), "ffprobe": Path("/usr/bin/ffprobe")})
        ),
        secret=get_token_secret() if is_auth_enabled() else "",
    )


Deps = Annotated[QualityDeps, Depends(quality_deps)]


def _available(deps: QualityDeps) -> None:
    if not is_auth_enabled() or not deps.secret:
        raise ServiceUnavailableError(QUALITY_UNAVAILABLE)


def _reader(deps: QualityDeps) -> Callable[[], Awaitable[CheckpointedShowrunnerGrantReader]]:
    if deps.grant_reader is None:
        raise ServiceUnavailableError(QUALITY_UNAVAILABLE)
    return deps.grant_reader


def _custody(deps: QualityDeps) -> tuple[Path, Path]:
    if deps.read_directory is None or deps.socket_directory is None:
        raise ServiceUnavailableError(QUALITY_UNAVAILABLE)
    return deps.read_directory, deps.socket_directory


async def _run[T](operation: Callable[[], Awaitable[T]]) -> T:
    try:
        return await operation()
    except (ProfilePublicationUnauthorizedError, DispositionUnauthorizedError) as error:
        raise ApiError(QUALITY_UNAUTHORIZED, status_code=403) from error
    except M10Error as error:
        raise ConflictError(error.code) from error
    except ValueError as error:
        raise UnprocessableError(QUALITY_REQUEST_INVALID) from error


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SealedBody(StrictBody):
    request: dict[str, Any]
    seal: str = Field(min_length=1, max_length=128)


def _prepared(deps: QualityDeps, action: Action, user: Any, project: str, request: BaseModel) -> dict[str, Any]:
    token = seal(deps.secret, action, user_id=user.id, actor_id=user.sub, project_name=project, request=request)
    return {"action": action, "request": request.model_dump(mode="json"), "seal": token}


def _unsealed[M: BaseModel](
    deps: QualityDeps, action: Action, model: type[M], user: Any, project: str, body: SealedBody
) -> M:
    try:
        return unseal(
            deps.secret,
            action,
            model,
            user_id=user.id,
            actor_id=user.sub,
            project_name=project,
            request=body.request,
            token=body.seal,
        )
    except M10Error as error:
        raise UnprocessableError(QUALITY_REQUEST_INVALID) from error


async def _profile(deps: QualityDeps, user_id: str, project: str, profile_id: str, revision: int):
    async with deps.sessions() as session:
        profile = await QualityProfileRepository(session).get_revision(
            user_id=user_id, project_name=project, profile_id=profile_id, revision=revision
        )
    if profile is None:
        raise NotFoundError(QUALITY_REQUEST_INVALID)
    return profile


async def _subject(deps: QualityDeps, user_id: str, project: str, root: str) -> q.AssessedSubject:
    async with deps.sessions() as session:
        return await _run(
            lambda: resolve_assessed_subject(
                session, deps.project_root(project), user_id=user_id, project_name=project, root_artifact_key=root
            )
        )


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- reads


@router.get("/projects/{project_name}/quality/template")
async def profile_template(
    project_name: str,
    user: CurrentUser,
    deps: Deps,
    platform_profile_id: str,
    width: int,
    height: int,
    min_duration_ms: int,
    max_duration_ms: int,
    locales: str = "",
) -> dict[str, Any]:
    _available(deps)
    constraints = default_platform_constraints(
        platform_profile_id=platform_profile_id,
        width=width,
        height=height,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        required_locales=tuple(item for item in locales.split(",") if item),
    )
    policy = await _run(lambda: _policy(constraints))
    return {"policy": policy.model_dump(mode="json")}


async def _policy(constraints: dict[str, Any]) -> q.QualityPolicyV2:
    return quality_policy(constraints)


@router.get("/projects/{project_name}/quality/profiles")
async def list_profiles(project_name: str, user: CurrentUser, deps: Deps) -> dict[str, Any]:
    _available(deps)
    async with deps.sessions() as session:
        heads = (
            (
                await session.execute(
                    sa.select(QualityProfileHeadModel).filter_by(user_id=user.id, project_name=project_name)
                )
            )
            .scalars()
            .all()
        )
        profiles = []
        for head in sorted(heads, key=lambda row: row.profile_id):
            profile = await QualityProfileRepository(session).get_revision(
                user_id=user.id, project_name=project_name, profile_id=head.profile_id, revision=head.current_revision
            )
            if profile is not None:
                profiles.append(profile.model_dump(mode="json"))
    return {"profiles": profiles}


@router.get("/projects/{project_name}/quality/profiles/{profile_id}/revisions")
async def list_revisions(project_name: str, profile_id: str, user: CurrentUser, deps: Deps) -> dict[str, Any]:
    _available(deps)
    async with deps.sessions() as session:
        rows = (
            await session.execute(
                sa.select(QualityProfileRevisionModel.revision, QualityProfileRevisionModel.profile_digest)
                .filter_by(user_id=user.id, project_name=project_name, profile_id=profile_id)
                .order_by(QualityProfileRevisionModel.revision)
            )
        ).all()
    return {"revisions": [{"revision": row.revision, "profile_digest": row.profile_digest} for row in rows]}


@router.get("/projects/{project_name}/quality/masters")
async def list_masters(project_name: str, user: CurrentUser, deps: Deps) -> dict[str, Any]:
    """Approved masters in the manifest, each with whether its subject resolves now."""
    _available(deps)
    root = deps.project_root(project_name)
    try:
        entries = ProjectArtifactManifestAdapter(root).snapshot_entries()
    except (ArtifactManifestError, OSError, ValueError) as error:
        raise ServiceUnavailableError(QUALITY_UNAVAILABLE) from error
    masters = []
    for key, entry in sorted(entries.items(), key=lambda item: item[0].encode()):
        if entry.r2 is None:
            continue
        metadata = R2ArtifactMetadata.model_validate(entry.r2)
        approved = metadata.approved_master
        if approved is None or metadata.contract_ref.contract_type == "ShotSpec":
            continue
        resolvable = True
        async with deps.sessions() as session:
            try:
                await resolve_assessed_subject(
                    session, root, user_id=user.id, project_name=project_name, root_artifact_key=key.encode()
                )
            except M10Error:
                resolvable = False
        masters.append(
            {
                "artifact_key": key.encode(),
                "artifact_path": entry.artifact_path,
                "selected_candidate_id": approved.selected_candidate_id,
                "resolvable": resolvable,
            }
        )
    return {"masters": masters}


@router.get("/projects/{project_name}/quality/observations")
async def list_observations(
    project_name: str, profile_id: str, revision: int, root: str, user: CurrentUser, deps: Deps
) -> dict[str, Any]:
    """Technical and Human observations of the root's current subject under one profile revision."""
    _available(deps)
    subject = await _subject(deps, user.id, project_name, root)
    subject_digest = compute_digest("m10.assessed-subject.v1", subject)
    found: list[dict[str, Any]] = []
    async with deps.sessions() as session:
        repository = QualityRunRepository(session)
        technical_ids = (
            await session.execute(
                sa.select(QualityProbeObservationModel.observation_id).filter_by(
                    user_id=user.id, project_name=project_name
                )
            )
        ).scalars()
        for observation_id in technical_ids.all():
            stored = await _run(
                lambda oid=observation_id: repository.technical_observation(
                    user_id=user.id, project_name=project_name, observation_id=oid
                )
            )
            if stored is None:
                continue
            observation, request = stored
            if (request.profile.profile_id, request.profile.revision) != (profile_id, revision):
                continue
            if compute_digest("m10.assessed-subject.v1", request.subject) != subject_digest:
                continue
            found.append(_summary(observation))
        human_ids = (
            await session.execute(
                sa.select(QualityHumanObservationModel.observation_id).filter_by(
                    user_id=user.id, project_name=project_name, profile_id=profile_id, profile_revision=revision
                )
            )
        ).scalars()
        for observation_id in human_ids.all():
            stored = await _run(
                lambda oid=observation_id: repository.human_observation(
                    user_id=user.id, project_name=project_name, observation_id=oid
                )
            )
            if stored is not None and stored.observation.subject_digest == subject_digest:
                found.append(_summary(stored.observation))
    return {"subject_digest": subject_digest, "observations": found}


def _summary(observation: q.TechnicalObservation | q.NarrativeObservation) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "observation_type": observation.observation_type,
        "requirement_id": observation.requirement_id,
        "slot_id": observation.slot_id,
        "status": observation.status,
        "observed_at": observation.observed_at.isoformat(),
        "findings": [finding.model_dump(mode="json") for finding in observation.findings],
    }


@router.get("/projects/{project_name}/quality/runs")
async def list_runs(project_name: str, root: str, user: CurrentUser, deps: Deps) -> dict[str, Any]:
    """Every sealed run of the root across subjects and profiles, with validity, readiness and disposition head."""
    _available(deps)
    reader = _reader(deps)
    project_root = deps.project_root(project_name)
    async with deps.sessions() as session:
        rows = (
            (await session.execute(sa.select(QualityRunModel).filter_by(user_id=user.id, project_name=project_name)))
            .scalars()
            .all()
        )
        runs = []
        for row in sorted(rows, key=lambda item: item.sealed_at, reverse=True):
            run = await QualityRunRepository(session).run(user_id=user.id, project_name=project_name, run_id=row.run_id)
            if run is None or run.subject.master_binding.root.artifact_key != root:
                continue
            head = await session.get(DispositionHeadModel, (user.id, project_name, run.subject_digest, run.profile_id))
            runs.append(
                {
                    "run": run.model_dump(mode="json"),
                    "run_digest": run_digest(run),
                    "disposition_version": 0 if head is None else head.version,
                    "current_disposition_id": None if head is None else head.current_disposition_id,
                }
            )
    for item in runs:
        run = item["run"]
        validity = await _run(
            lambda rid=run["run_id"]: run_validity(
                deps.sessions,
                reader,
                project_root=project_root,
                user_id=user.id,
                project_name=project_name,
                run_id=rid,
            )
        )
        readiness = await _run(
            lambda r=run: quality_readiness(
                deps.sessions,
                reader,
                project_root=project_root,
                user_id=user.id,
                project_name=project_name,
                subject_digest=r["subject_digest"],
                profile_id=r["profile_id"],
            )
        )
        item["validity"] = {"state": validity.state, "reasons": list(validity.reasons)}
        item["readiness"] = {"state": readiness.state, "reasons": list(readiness.reasons)}
    return {"runs": runs}


# ---------------------------------------------------------------- publish


class PublishIntent(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    profile_id: str | None = None
    expected_profile_revision: int = Field(ge=0)
    cohort_id: str = Field(min_length=1, max_length=255)
    product_surface: str = Field(min_length=1, max_length=255)
    policy: dict[str, Any]
    supersession_effect: Literal["HISTORICAL_ONLY", "REEVALUATE_CURRENT"] = "HISTORICAL_ONLY"


@router.post("/projects/{project_name}/quality/profiles/prepare")
async def prepare_publication(
    project_name: str, body: PublishIntent, user: InteractiveUser, deps: Deps
) -> dict[str, Any]:
    _available(deps)

    async def build() -> q.ProfilePublicationAuthorizationRequest:
        return publication_request(
            user_id=user.id,
            actor_id=user.sub,
            project_name=project_name,
            command_id=body.command_id,
            profile_id=body.profile_id,
            expected_revision=body.expected_profile_revision,
            cohort_id=body.cohort_id,
            product_surface=body.product_surface,
            policy=q.QualityPolicyV2.model_validate(body.policy),
            supersession_effect=q.SupersessionEffect(body.supersession_effect),
            now=_now(),
        )

    return _prepared(deps, "publish_profile", user, project_name, await _run(build))


@router.post("/projects/{project_name}/quality/profiles")
async def publish_profile(
    project_name: str, body: SealedBody, user: InteractiveUser, token: Token, deps: Deps
) -> dict[str, Any]:
    _available(deps)
    request = _unsealed(deps, "publish_profile", q.ProfilePublicationAuthorizationRequest, user, project_name, body)
    read_directory, socket_directory = _custody(deps)

    async def operation() -> q.QualityProfileRevision:
        custodian = await InteractiveProfilePublicationCustodian.for_request(
            request,
            deps.sessions,
            interactive_token=token,
            read_directory=read_directory,
            socket_directory=socket_directory,
            expected_uid=deps.custody_uid,
            expected_gid=deps.custody_gid,
        )
        return await ProfilePublicationService(deps.sessions, custodian=custodian).publish(request)

    return {"profile": (await _run(operation)).model_dump(mode="json")}


# ---------------------------------------------------------------- probes


class ProbeIntent(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    profile_id: str
    revision: int = Field(ge=1)
    root_artifact_key: str
    requirement_id: Literal["technical-container", "technical-decode"]


@router.post("/projects/{project_name}/quality/probes/prepare")
async def prepare_probe(project_name: str, body: ProbeIntent, user: InteractiveUser, deps: Deps) -> dict[str, Any]:
    _available(deps)
    if deps.catalog is None:
        raise ServiceUnavailableError(QUALITY_UNAVAILABLE)
    profile = await _profile(deps, user.id, project_name, body.profile_id, body.revision)
    subject = await _subject(deps, user.id, project_name, body.root_artifact_key)

    async def build() -> ProbeRequest:
        return probe_request(
            user_id=user.id,
            actor_id=user.sub,
            project_name=project_name,
            execution_ref=body.command_id,
            subject=subject,
            profile=profile,
            requirement_id=body.requirement_id,
        )

    return _prepared(deps, "probe", user, project_name, await _run(build))


@router.post("/projects/{project_name}/quality/probes")
async def run_probe(
    project_name: str, body: SealedBody, user: InteractiveUser, token: Token, deps: Deps
) -> dict[str, Any]:
    _available(deps)
    request = _unsealed(deps, "probe", ProbeRequest, user, project_name, body)

    async def operation() -> q.TechnicalObservation:
        service = await QualityProbeService.for_request(
            request,
            deps.sessions,
            interactive_token=token,
            project_root=deps.project_root(project_name),
            catalog=deps.catalog or DEFAULT_PROBE_CATALOG,
            runtime=deps.runtime,
        )
        return await service.observe(request)

    return {"observation": _summary(await _run(operation))}


# ---------------------------------------------------------------- review


class FindingRow(StrictBody):
    rule_id: str
    severity: Literal["BLOCKING", "ADVISORY"]
    locator: str = Field(max_length=32)


class ReviewIntent(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    profile_id: str
    revision: int = Field(ge=1)
    root_artifact_key: str
    status: Literal["PASS", "FAIL"]
    criteria_verdicts: dict[str, Literal["PASS", "FAIL"]]
    findings: list[FindingRow] = Field(default_factory=list, max_length=32)
    notes: str = Field(default="", max_length=20000)


@router.post("/projects/{project_name}/quality/reviews/prepare")
async def prepare_review(project_name: str, body: ReviewIntent, user: InteractiveUser, deps: Deps) -> dict[str, Any]:
    _available(deps)
    profile = await _profile(deps, user.id, project_name, body.profile_id, body.revision)
    subject = await _subject(deps, user.id, project_name, body.root_artifact_key)

    async def build() -> HumanObservationRequest:
        return review_request(
            user_id=user.id,
            actor_id=user.sub,
            project_name=project_name,
            command_id=body.command_id,
            subject=subject,
            profile=profile,
            status=body.status,
            criteria_verdicts=body.criteria_verdicts,
            findings=[row.model_dump() for row in body.findings],
            notes=body.notes,
        )

    return _prepared(deps, "review", user, project_name, await _run(build))


@router.post("/projects/{project_name}/quality/reviews")
async def record_review(
    project_name: str, body: SealedBody, user: InteractiveUser, token: Token, deps: Deps
) -> dict[str, Any]:
    _available(deps)
    request = _unsealed(deps, "review", HumanObservationRequest, user, project_name, body)
    reader = _reader(deps)

    async def operation() -> q.NarrativeObservation:
        service = await HumanObservationService.for_request(
            request,
            deps.sessions,
            interactive_token=token,
            grant_reader=reader,
            project_root=deps.project_root(project_name),
        )
        return await service.record(request)

    return {"observation": _summary(await _run(operation))}


# ---------------------------------------------------------------- runs


class SealIntent(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    profile_id: str
    revision: int = Field(ge=1)
    root_artifact_key: str
    observation_ids: list[str] = Field(min_length=1, max_length=16)


@router.post("/projects/{project_name}/quality/runs/prepare")
async def prepare_seal(project_name: str, body: SealIntent, user: InteractiveUser, deps: Deps) -> dict[str, Any]:
    _available(deps)
    profile = await _profile(deps, user.id, project_name, body.profile_id, body.revision)
    subject = await _subject(deps, user.id, project_name, body.root_artifact_key)
    observations: list[q.TechnicalObservation | q.NarrativeObservation] = []
    async with deps.sessions() as session:
        repository = QualityRunRepository(session)
        for observation_id in body.observation_ids:
            technical = await _run(
                lambda oid=observation_id: repository.technical_observation(
                    user_id=user.id, project_name=project_name, observation_id=oid
                )
            )
            if technical is not None:
                observations.append(technical[0])
                continue
            human = await _run(
                lambda oid=observation_id: repository.human_observation(
                    user_id=user.id, project_name=project_name, observation_id=oid
                )
            )
            if human is None:
                raise NotFoundError(QUALITY_REQUEST_INVALID)
            observations.append(human.observation)

    async def build() -> q.CompleteRunCommand:
        return completion_request(
            user_id=user.id,
            actor_id=user.sub,
            project_name=project_name,
            command_id=body.command_id,
            subject=subject,
            profile=profile,
            observations=observations,
        )

    return _prepared(deps, "seal_run", user, project_name, await _run(build))


@router.post("/projects/{project_name}/quality/runs")
async def seal_run(
    project_name: str, body: SealedBody, user: InteractiveUser, token: Token, deps: Deps
) -> dict[str, Any]:
    _available(deps)
    request = _unsealed(deps, "seal_run", q.CompleteRunCommand, user, project_name, body)
    reader = _reader(deps)

    async def operation() -> q.QualityRun:
        service = await QualityRunService.for_request(
            request,
            deps.sessions,
            interactive_token=token,
            grant_reader=reader,
            project_root=deps.project_root(project_name),
        )
        return await service.complete(request)

    run = await _run(operation)
    return {"run": run.model_dump(mode="json"), "run_digest": run_digest(run)}


# ---------------------------------------------------------------- dispositions


class DisposeIntent(StrictBody):
    command_id: str = Field(min_length=1, max_length=255)
    run_id: str
    decision: Literal["PASS", "REWORK", "WAIVE"]
    reason: str = Field(min_length=1, max_length=2000)
    waiver_bindings: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    expected_disposition_version: int = Field(ge=0)
    requested_ttl_seconds: int = Field(gt=0, le=604800)


@router.post("/projects/{project_name}/quality/dispositions/prepare")
async def prepare_disposition(
    project_name: str, body: DisposeIntent, user: InteractiveUser, deps: Deps
) -> dict[str, Any]:
    _available(deps)
    async with deps.sessions() as session:
        run = await QualityRunRepository(session).run(user_id=user.id, project_name=project_name, run_id=body.run_id)
    if run is None:
        raise NotFoundError(QUALITY_REQUEST_INVALID)
    profile = await _profile(deps, user.id, project_name, run.profile_id, run.profile_revision)

    async def build() -> q.DispositionAuthorizationRequest:
        return disposition_request(
            user_id=user.id,
            actor_id=user.sub,
            project_name=project_name,
            command_id=body.command_id,
            run=run,
            run_digest=run_digest(run),
            policy=profile.policy,
            decision=body.decision,
            reason=body.reason,
            waiver_bindings=body.waiver_bindings,
            expected_version=body.expected_disposition_version,
            requested_ttl_seconds=body.requested_ttl_seconds,
            now=_now(),
        )

    return _prepared(deps, "dispose", user, project_name, await _run(build))


@router.post("/projects/{project_name}/quality/dispositions")
async def issue_disposition(
    project_name: str, body: SealedBody, user: InteractiveUser, token: Token, deps: Deps
) -> dict[str, Any]:
    _available(deps)
    request = _unsealed(deps, "dispose", q.DispositionAuthorizationRequest, user, project_name, body)
    read_directory, socket_directory = _custody(deps)

    async def operation() -> q.QualityDisposition:
        custodian = await DispositionCustodian.for_request(
            request,
            deps.sessions,
            interactive_token=token,
            read_directory=read_directory,
            socket_directory=socket_directory,
            expected_uid=deps.custody_uid,
            expected_gid=deps.custody_gid,
        )
        return await DispositionService(
            deps.sessions, custodian=custodian, project_root=deps.project_root(project_name)
        ).issue(request)

    return {"disposition": (await _run(operation)).model_dump(mode="json")}


__all__ = ["QualityDeps", "quality_deps", "router"]
