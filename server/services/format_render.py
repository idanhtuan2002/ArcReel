"""Local FFmpeg rendering of one format projection plan (M8-E E2).

The source must be the exact master bytes the plan binds (its digest equals the plan's
``source_master_digest``). The render execution id is the deterministic identity of source, plan,
argv, FFmpeg version and adapter, so a succeeded execution only replays and the output is stored
content-addressed under the project's ``formats`` directory. The subprocess runs outside any database
transaction with a timeout; cancellation or failure is recorded and the execution may run again.
A RUNNING execution older than ``stale_after`` is treated as abandoned (the process crashed).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatRenderModel
from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError, M8Error
from r2.advanced_creative.format_render import execution_identity, materialize, render_argv
from r2.advanced_creative.formats import validate_plan

Clock = Callable[[], datetime]


class FormatRenderBusyError(M8Error):
    """The same render execution is already running."""

    code = "m8_format_render_busy"


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


async def _run(argv: list[str]) -> tuple[int, bytes]:
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
        code, output = await _run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)])
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
        code, output = await _run([ffmpeg, "-version"])
    if code != 0:
        raise FormatRenderFailedError("ffmpeg is not available")
    return output.decode("utf-8", "replace").splitlines()[0].strip()


class FormatRenderService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        timeout: float = 1800,
        stale_after: timedelta = timedelta(hours=2),
        clock: Clock | None = None,
    ) -> None:
        self._sessions = sessions
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._timeout = timeout
        self._stale_after = stale_after
        self._clock = clock or (lambda: datetime.now(UTC))

    async def render(
        self, *, user_id: str, project_name: str, project_dir: Path, plan_id: str, source: Path
    ) -> RenderResult:
        async with self._sessions() as session:
            plan = await FormatRepository(session).get_plan(user_id=user_id, project_name=project_name, plan_id=plan_id)
        if plan is None:
            raise FormatNotFoundError("unknown format plan")
        validate_plan(plan)
        source_digest = await asyncio.to_thread(file_digest, source)
        if source_digest != plan.source_master_digest:
            raise FormatConflictError("the source bytes are not the master the plan binds")
        facts = await probe_source(source, ffprobe=self._ffprobe)
        argv = render_argv(plan, source_width=facts.width, source_height=facts.height, has_audio=facts.has_audio)
        version = await ffmpeg_version(self._ffmpeg)
        execution_id = execution_identity(plan, source_digest=source_digest, argv=argv, ffmpeg_version=version)
        store = project_dir / "formats"

        replay = await self._begin(
            user_id=user_id,
            project_name=project_name,
            plan_id=plan_id,
            execution_id=execution_id,
            source_digest=source_digest,
            argv=list(argv),
            version=version,
            store=store,
        )
        if replay is not None:
            return replay

        store.mkdir(parents=True, exist_ok=True)
        temporary = store / f".{execution_id}.{os.getpid()}.partial.mp4"
        try:
            command = materialize(argv, source=str(source), output=str(temporary))
            command[0] = self._ffmpeg
            async with asyncio.timeout(self._timeout):
                code, output = await _run(command)
            if code != 0:
                tail = output.decode("utf-8", "replace")[-800:]
                await self._finish(
                    user_id, project_name, execution_id, state="FAILED", error=f"ffmpeg exit {code}: {tail}"
                )
                raise FormatRenderFailedError(f"ffmpeg exited {code}")
            digest = await asyncio.to_thread(file_digest, temporary)
            final = store / f"{digest.removeprefix('sha256:')}.mp4"
            if final.exists():
                temporary.unlink()
            else:
                os.replace(temporary, final)
            await self._finish(
                user_id,
                project_name,
                execution_id,
                state="SUCCEEDED",
                artifact_digest=digest,
                artifact_ref=f"formats/{final.name}",
            )
            return RenderResult(execution_id=execution_id, artifact_digest=digest, artifact_path=final, replayed=False)
        except (asyncio.CancelledError, TimeoutError) as exc:
            state = "CANCELLED" if isinstance(exc, asyncio.CancelledError) else "FAILED"
            await asyncio.shield(
                self._finish(
                    user_id,
                    project_name,
                    execution_id,
                    state=state,
                    error="cancelled" if state == "CANCELLED" else "timed out",
                )
            )
            raise
        finally:
            if temporary.exists():
                temporary.unlink()

    async def _begin(
        self,
        *,
        user_id: str,
        project_name: str,
        plan_id: str,
        execution_id: str,
        source_digest: str,
        argv: list[str],
        version: str,
        store: Path,
    ) -> RenderResult | None:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            row = await session.get(FormatRenderModel, (user_id, project_name, execution_id), with_for_update=True)
            if row is not None and row.state == "SUCCEEDED":
                digest, ref = row.artifact_digest, row.artifact_ref
                path = None if ref is None else store.parent / ref
                if digest and path and path.exists() and await asyncio.to_thread(file_digest, path) == digest:
                    return RenderResult(execution_id, digest, path, replayed=True)
                # The stored output is gone or changed; the deterministic render may run again.
                row.state, row.artifact_digest, row.artifact_ref = "RUNNING", None, None
                row.attempt += 1
                row.started_at, row.finished_at, row.error = now, None, None
                return None
            if row is not None and row.state == "RUNNING":
                started = row.started_at if row.started_at.tzinfo else row.started_at.replace(tzinfo=UTC)
                if now - started < self._stale_after:
                    raise FormatRenderBusyError("this render is already running")
            if row is None:
                session.add(
                    FormatRenderModel(
                        user_id=user_id,
                        project_name=project_name,
                        execution_id=execution_id,
                        plan_id=plan_id,
                        source_digest=source_digest,
                        argv_json=argv,
                        ffmpeg_version=version,
                        state="RUNNING",
                        attempt=1,
                        started_at=now,
                    )
                )
            else:
                row.state, row.error, row.finished_at = "RUNNING", None, None
                row.attempt += 1
                row.started_at = now
        return None

    async def _finish(
        self,
        user_id: str,
        project_name: str,
        execution_id: str,
        *,
        state: str,
        error: str | None = None,
        artifact_digest: str | None = None,
        artifact_ref: str | None = None,
    ) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.get(FormatRenderModel, (user_id, project_name, execution_id), with_for_update=True)
            if row is None or row.state != "RUNNING":
                return
            row.state, row.error = state, error
            row.artifact_digest, row.artifact_ref = artifact_digest, artifact_ref
            row.finished_at = self._clock()

    async def execution(self, *, user_id: str, project_name: str, execution_id: str) -> FormatRenderModel | None:
        async with self._sessions() as session:
            return await session.get(FormatRenderModel, (user_id, project_name, execution_id))


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


__all__ = [
    "FormatRenderBusyError",
    "FormatRenderFailedError",
    "FormatRenderService",
    "RenderResult",
    "SourceFacts",
    "ffmpeg_available",
    "ffmpeg_version",
    "file_digest",
    "probe_source",
]
