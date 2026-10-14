"""Local FFmpeg rendering of one format projection plan (M8-E E2).

The source must be the exact master bytes the plan binds (its digest equals the plan's
``source_master_digest``). The render execution id is the deterministic identity of source, plan,
argv, FFmpeg version and adapter, so a succeeded execution only replays and the output is stored
content-addressed under the project's ``formats`` directory. The subprocess runs outside any database
transaction with a timeout, inside an M7 attempt whose lease outlives that timeout. An attempt that was
accepted but whose success was never recorded (the process died in between) is completed when the
same command is sent again, from the output its job id names.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatRenderModel
from lib.db.repositories.formats import FormatRepository
from lib.db.repositories.host_hardening import ExecutionAttemptFencingError, ExecutionAttemptRepository
from lib.video_backends.execution_adapter import accepted_submit_receipt
from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.errors import (
    FormatConflictError,
    FormatMediaMissingError,
    FormatNotFoundError,
    FormatRenderIncompleteError,
    M8Error,
)
from r2.advanced_creative.format_render import execution_identity, materialize, render_argv
from r2.advanced_creative.formats import FormatInvalidError, validate_plan
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ExecutionAttemptState,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.host_submit import AttemptSubmitter
from r2.host_hardening.paid_routes import current_release_mode
from r2.host_hardening.route_inventory import (
    FORMAT_RENDER_SUBMIT_FAMILIES,
    HOST_FORMAT_ADAPTER_VERSION,
    require_submit_route,
)
from server.services.execution_attempts import capability_resolver

Clock = Callable[[], datetime]


class FormatRenderFailedError(M8Error):
    """FFmpeg did not produce the projection."""

    code = "m8_format_render_failed"


@dataclass(frozen=True)
class SourceFacts:
    width: int
    height: int
    has_audio: bool


@dataclass(frozen=True)
class RenderResult:
    execution_id: str
    artifact_digest: str
    artifact_path: Path
    replayed: bool


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _copy_hashing(source: Path, destination: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as reader, destination.open("xb") as writer:
        for chunk in iter(lambda: reader.read(1 << 20), b""):
            digest.update(chunk)
            writer.write(chunk)
    return "sha256:" + digest.hexdigest()


@contextlib.asynccontextmanager
async def verified_snapshot(path: Path, expected_digest: str, directory: Path) -> AsyncGenerator[Path]:
    """A private copy of ``path`` whose bytes were hashed as they were copied and equal ``expected_digest``.

    Every later read uses the copy, so a file replaced or rewritten after the check is never measured,
    served or registered under the recorded digest. The copy is removed when the context exits.
    """
    await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)
    snapshot = directory / f".snapshot-{uuid.uuid4().hex}{path.suffix}"
    try:
        try:
            digest = await asyncio.to_thread(_copy_hashing, path, snapshot)
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as error:
            raise FormatMediaMissingError("a media file is missing") from error
        if digest != expected_digest:
            raise FormatConflictError("a media file changed since it was recorded")
        yield snapshot
    finally:
        snapshot.unlink(missing_ok=True)


def snapshot_dir(project_dir: Path) -> Path:
    return project_dir / "formats" / ".snapshots"


def _redacted(output: bytes, secrets_: tuple[str, ...]) -> str:
    """The last diagnostic lines with every local path replaced; at most 400 characters."""
    text = output.decode("utf-8", "replace")
    for value in sorted(secrets_, key=len, reverse=True):
        text = text.replace(value, "<path>")
    return text[-400:]


async def run_process(argv: list[str]) -> tuple[int, bytes]:
    """Run to completion; cancellation (including an enclosing ``asyncio.timeout``) kills the process."""
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await process.communicate()
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    return process.returncode if process.returncode is not None else -1, stdout + stderr


async def probe_source(path: Path, *, ffprobe: str = "ffprobe") -> SourceFacts:
    async with asyncio.timeout(60):
        code, output = await run_process([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)])
    if code != 0:
        raise FormatRenderFailedError("the source could not be probed")
    streams = json.loads(output.decode("utf-8", "replace") or "{}").get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise FormatRenderFailedError("the source has no video stream")
    return SourceFacts(
        width=int(video["width"]),
        height=int(video["height"]),
        has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
    )


async def ffmpeg_version(ffmpeg: str = "ffmpeg") -> str:
    async with asyncio.timeout(30):
        code, output = await run_process([ffmpeg, "-version"])
    if code != 0:
        raise FormatRenderFailedError("ffmpeg is not available")
    return output.decode("utf-8", "replace").splitlines()[0].strip()


FORMAT_REQUEST_SCHEMA = "r2.m8.format.render.v1"
RENDER_TIMEOUT_SECONDS = 1800
# The M7 lease of a render attempt outlives the bounded FFmpeg run, so the recovery scanner never
# reclaims an attempt whose process may still be running.
RENDER_LEASE_SECONDS = RENDER_TIMEOUT_SECONDS + 300
_FAMILY = FORMAT_RENDER_SUBMIT_FAMILIES[0]


def render_task_id(user_id: str, project_name: str, command_id: str) -> str:
    scope = digest_canonical({"user_id": user_id, "project_name": project_name, "command_id": command_id})
    return "m8e-format:" + scope.removeprefix("sha256:")


def render_route(ffmpeg_version_line: str) -> ProviderRouteSnapshot:
    return ProviderRouteSnapshot(
        provider_id=_FAMILY.key.provider_id,
        provider_account_ref="local",
        provider_model_id="ffmpeg",
        backend_model_id=ffmpeg_version_line,
        endpoint_id=_FAMILY.key.endpoint_id,
        submitted_base_url="local://ffmpeg",
        adapter_version=HOST_FORMAT_ADAPTER_VERSION,
        capability_profile_ref=_FAMILY.capability_profile_ref,
    )


class FormatRenderService:
    """Render one plan through one bounded M7 attempt and record its evidence on success.

    A render command is an M7 task with a single attempt: re-sending the same command replays it
    (M7 checks the request is identical), and a failed, cancelled or unknown attempt is retried with
    a new command. The submit function runs FFmpeg on a private snapshot of the exact master bytes
    and stores the output content-addressed; M7 records the outcome, including unknown ones.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        submitter_for: Callable[[AsyncSession, str, str], AttemptSubmitter],
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        timeout: float = RENDER_TIMEOUT_SECONDS,
        clock: Clock | None = None,
    ) -> None:
        self._sessions = sessions
        self._submitter_for = submitter_for
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(UTC))

    async def render(
        self, *, user_id: str, project_name: str, project_dir: Path, plan_id: str, source: Path, command_id: str
    ) -> RenderResult:
        if not command_id:
            raise FormatInvalidError("a render names its command id")
        async with self._sessions() as session:
            plan = await FormatRepository(session).get_plan(user_id=user_id, project_name=project_name, plan_id=plan_id)
            recorded = await session.scalar(
                select(FormatRenderModel).where(
                    FormatRenderModel.user_id == user_id,
                    FormatRenderModel.project_name == project_name,
                    FormatRenderModel.command_id == command_id,
                )
            )
        if plan is None:
            raise FormatNotFoundError("unknown format plan")
        validate_plan(plan)
        if recorded is not None:
            if recorded.plan_id != plan_id:
                raise FormatConflictError("this render command already rendered another plan")
            path = project_dir / recorded.artifact_ref
            try:
                on_disk = await asyncio.to_thread(file_digest, path)
            except (FileNotFoundError, IsADirectoryError) as error:
                raise FormatMediaMissingError("the recorded output is missing; render with a new command") from error
            if on_disk != recorded.artifact_digest:
                raise FormatConflictError("the recorded output changed; render with a new command")
            return RenderResult(recorded.execution_id, recorded.artifact_digest, path, replayed=True)

        require_submit_route(
            _FAMILY.key.provider_id,
            _FAMILY.key.endpoint_id,
            HOST_FORMAT_ADAPTER_VERSION,
            release_mode=current_release_mode(),
            now=self._clock(),
        )
        store = project_dir / "formats"
        store.mkdir(parents=True, exist_ok=True)
        # Render from a private snapshot whose bytes were hashed as they were copied, so a source
        # replaced after the check can never be rendered under the master's identity.
        snapshot = store / f".source-{uuid.uuid4().hex}.mp4"
        try:
            try:
                source_digest = await asyncio.to_thread(_copy_hashing, source, snapshot)
            except FileNotFoundError as error:
                raise FormatMediaMissingError("the source master file is missing") from error
            if source_digest != plan.source_master_digest:
                raise FormatConflictError("the source bytes are not the master the plan binds")
            facts = await probe_source(snapshot, ffprobe=self._ffprobe)
            argv = render_argv(plan, source_width=facts.width, source_height=facts.height, has_audio=facts.has_audio)
            version = await ffmpeg_version(self._ffmpeg)
            task_id = render_task_id(user_id, project_name, command_id)
            request = ProviderRequest(
                id=f"{task_id}:render",
                host_task_ref=task_id,
                provider=_FAMILY.key.provider_id,
                model="ffmpeg",
                endpoint=_FAMILY.key.endpoint_id,
                payload={
                    "schema": FORMAT_REQUEST_SCHEMA,
                    "plan_id": plan_id,
                    "plan_digest": plan.plan_digest,
                    "source_digest": source_digest,
                    "argv": list(argv),
                    "ffmpeg_version": version,
                    "identity": execution_identity(
                        plan, source_digest=source_digest, argv=argv, ffmpeg_version=version
                    ),
                },
                adapter_version=HOST_FORMAT_ADAPTER_VERSION,
            )
            redact = (str(source), str(snapshot), str(project_dir))

            async def submit(attempt: AttemptSnapshot):
                digest = await self._run_ffmpeg(argv=argv, snapshot=snapshot, store=store, redact=redact)
                # Job ids are unique per scope; identical bytes from two executions stay distinct.
                return accepted_submit_receipt(digest, provider_job_id=f"{attempt.execution_id}:{digest}")

            try:
                async with self._sessions() as session:
                    result = await self._submitter_for(session, user_id, project_name).submit(
                        task_id=task_id, api_call_id=None, route=render_route(version), request=request, submit=submit
                    )
            except ExecutionAttemptFencingError as error:
                # Another writer (a cancel, or recovery after a lost lease) moved the attempt first.
                raise FormatRenderFailedError("the render attempt was moved by another writer") from error
            if result.snapshot.state is ExecutionAttemptState.SUCCEEDED:
                # The success evidence was committed by an earlier call of this command.
                return await self._recorded(user_id, project_name, project_dir, result.execution_id, command_id)
            if result.snapshot.state is not ExecutionAttemptState.ACCEPTED:
                raise FormatRenderFailedError(
                    f"render {result.execution_id} ended {result.snapshot.state.value} without an output"
                )
            digest = result.value if result.value is not None else self._accepted_digest(result.snapshot, store)
            artifact_ref = f"formats/{digest.removeprefix('sha256:')}.mp4"
            try:
                await self._record_success(
                    user_id=user_id,
                    project_name=project_name,
                    accepted=result.snapshot,
                    command_id=command_id,
                    plan_id=plan_id,
                    source_digest=source_digest,
                    argv=argv,
                    version=version,
                    digest=digest,
                    artifact_ref=artifact_ref,
                )
            except M8Error:
                raise
            except Exception as error:
                # A concurrent call of this command may have committed the same evidence first.
                async with self._sessions() as session:
                    winner = await session.get(FormatRenderModel, (user_id, project_name, result.execution_id))
                if winner is None or winner.artifact_digest != digest:
                    raise FormatRenderIncompleteError("the render's success could not be recorded") from error
            return RenderResult(result.execution_id, digest, project_dir / artifact_ref, replayed=result.value is None)
        finally:
            snapshot.unlink(missing_ok=True)

    async def _recorded(
        self, user_id: str, project_name: str, project_dir: Path, execution_id: str, command_id: str
    ) -> RenderResult:
        async with self._sessions() as session:
            row = await session.get(FormatRenderModel, (user_id, project_name, execution_id))
        if row is None or row.command_id != command_id:
            raise FormatRenderFailedError(f"render {execution_id} succeeded without its recorded evidence")
        return RenderResult(execution_id, row.artifact_digest, project_dir / row.artifact_ref, replayed=True)

    @staticmethod
    def _accepted_digest(accepted: AttemptSnapshot, store: Path) -> str:
        """The output of an attempt accepted by an earlier, interrupted call, read back from its job id.

        The job id is ``<execution id>:<digest>``; the content-addressed file must still hold exactly
        those bytes, otherwise the output is lost and the command cannot complete.
        """
        prefix = f"{accepted.execution_id}:"
        job_id = accepted.provider_job_id or ""
        digest = job_id.removeprefix(prefix)
        if not job_id.startswith(prefix) or not digest.startswith("sha256:"):
            raise FormatRenderFailedError(f"render {accepted.execution_id} was accepted without a known output")
        path = store / f"{digest.removeprefix('sha256:')}.mp4"
        try:
            on_disk = file_digest(path)
        except FileNotFoundError as error:
            raise FormatMediaMissingError("the accepted output is missing; render with a new command") from error
        if on_disk != digest:
            raise FormatConflictError("the accepted output changed; render with a new command")
        return digest

    async def _record_success(
        self,
        *,
        user_id: str,
        project_name: str,
        accepted: AttemptSnapshot,
        command_id: str,
        plan_id: str,
        source_digest: str,
        argv: tuple[str, ...],
        version: str,
        digest: str,
        artifact_ref: str,
    ) -> None:
        execution_id = accepted.execution_id
        async with self._sessions() as session, session.begin():
            repository = ExecutionAttemptRepository(session, capability_resolver=capability_resolver())
            succeeded = await repository.apply_provider_observation(
                user_id=user_id,
                project_name=project_name,
                execution_id=execution_id,
                expected_version=accepted.state_version,
                observation=ProviderObservation(
                    observation_id=f"{execution_id}:succeeded",
                    kind=ProviderObservationKind.SUCCEEDED,
                    observed_at=self._clock(),
                    provider_job_id=f"{execution_id}:{digest}",
                    evidence_digest=digest,
                ),
            )
            if succeeded.state is not ExecutionAttemptState.SUCCEEDED:
                raise FormatRenderFailedError("the render attempt could not reach SUCCEEDED")
            session.add(
                FormatRenderModel(
                    user_id=user_id,
                    project_name=project_name,
                    execution_id=execution_id,
                    command_id=command_id,
                    plan_id=plan_id,
                    source_digest=source_digest,
                    argv_json=list(argv),
                    ffmpeg_version=version,
                    artifact_digest=digest,
                    artifact_ref=artifact_ref,
                    created_at=self._clock(),
                )
            )

    async def _run_ffmpeg(self, *, argv: tuple[str, ...], snapshot: Path, store: Path, redact: tuple[str, ...]) -> str:
        """Run FFmpeg into a unique temporary file and publish it content-addressed; returns its digest."""
        temporary = store / f".render-{uuid.uuid4().hex}.partial.mp4"
        try:
            command = materialize(argv, source=str(snapshot), output=str(temporary))
            command[0] = self._ffmpeg
            async with asyncio.timeout(self._timeout):
                code, output = await run_process(command)
            if code != 0:
                raise FormatRenderFailedError(f"ffmpeg exit {code}: {_redacted(output, redact)}")
            digest = await asyncio.to_thread(file_digest, temporary)
            final = store / f"{digest.removeprefix('sha256:')}.mp4"
            # Content-addressed: an existing file must hold exactly these bytes, or it is replaced.
            if not final.exists() or await asyncio.to_thread(file_digest, final) != digest:
                os.replace(temporary, final)
            return digest
        finally:
            temporary.unlink(missing_ok=True)

    async def execution(self, *, user_id: str, project_name: str, execution_id: str) -> FormatRenderModel | None:
        async with self._sessions() as session:
            return await session.get(FormatRenderModel, (user_id, project_name, execution_id))


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


__all__ = [
    "FORMAT_REQUEST_SCHEMA",
    "RENDER_LEASE_SECONDS",
    "RENDER_TIMEOUT_SECONDS",
    "FormatRenderFailedError",
    "FormatRenderService",
    "RenderResult",
    "SourceFacts",
    "ffmpeg_available",
    "ffmpeg_version",
    "file_digest",
    "probe_source",
    "render_route",
    "render_task_id",
    "run_process",
    "snapshot_dir",
    "verified_snapshot",
]
