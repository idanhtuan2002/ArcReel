"""Technical validation of one rendered format projection (M8-E E3, spec §10).

Every check is measured on the rendered bytes: ffprobe facts for dimensions, ratio, codec, fps,
duration and audio; a full decode for errors; and the plan's overlay collision analysis. Expected
values come from the plan's profile and the source master. The report is deterministic for one
render execution and is appended through the format repository, which re-validates it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.formats import FormatRenderModel
from lib.db.repositories.formats import FormatRepository
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError
from r2.advanced_creative.formats import overlay_collisions, reduced_ratio
from r2.contracts.advanced_creative import CanonicalJsonObject, TechnicalValidationReport
from server.services.format_render import FormatRenderFailedError, file_digest, run_process


@dataclass(frozen=True)
class MediaFacts:
    width: int
    height: int
    codec: str
    fps: Fraction
    duration: Fraction
    audio: tuple[str, ...]


async def media_facts(path: Path, *, ffprobe: str = "ffprobe") -> MediaFacts:
    async with asyncio.timeout(120):
        code, output = await run_process(
            [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
        )
    if code != 0:
        raise FormatRenderFailedError("the media could not be probed")
    data = json.loads(output.decode("utf-8", "replace") or "{}")
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise FormatRenderFailedError("the media has no video stream")
    return MediaFacts(
        width=int(video["width"]),
        height=int(video["height"]),
        codec=str(video.get("codec_name", "")),
        fps=Fraction(str(video.get("r_frame_rate", "0/1"))),
        duration=Fraction(str(data.get("format", {}).get("duration", "0"))),
        audio=tuple(str(stream.get("codec_name", "")) for stream in streams if stream.get("codec_type") == "audio"),
    )


async def decode_errors(path: Path, *, ffmpeg: str = "ffmpeg") -> int:
    async with asyncio.timeout(1800):
        code, output = await run_process([ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"])
    lines = [line for line in output.decode("utf-8", "replace").splitlines() if line.strip()]
    return len(lines) + (0 if code == 0 else 1)


def _check(name: str, observed: object, expected: object, passed: bool | None = None) -> dict[str, object]:
    ok = observed == expected if passed is None else passed
    return {"name": name, "observed": observed, "expected": expected, "verdict": "PASS" if ok else "FAIL"}


def _seconds(value: Fraction) -> str:
    return f"{float(value):.3f}"


class FormatValidationService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"
    ) -> None:
        self._sessions = sessions
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    async def validate(
        self, *, user_id: str, project_name: str, project_dir: Path, execution_id: str, source: Path
    ) -> TechnicalValidationReport:
        async with self._sessions() as session:
            render = await session.get(FormatRenderModel, (user_id, project_name, execution_id))
            plan = (
                None
                if render is None
                else await FormatRepository(session).get_plan(
                    user_id=user_id, project_name=project_name, plan_id=render.plan_id
                )
            )
        if render is None or plan is None or render.state != "SUCCEEDED":
            raise FormatNotFoundError("no succeeded render with this execution id")
        assert render.artifact_ref is not None
        artifact = project_dir / render.artifact_ref
        if await asyncio.to_thread(file_digest, artifact) != render.artifact_digest:
            raise FormatConflictError("the rendered artifact changed since it was rendered")
        if await asyncio.to_thread(file_digest, source) != render.source_digest:
            raise FormatConflictError("the source is not the master this render used")

        profile = plan.output_profile
        observed = await media_facts(artifact, ffprobe=self._ffprobe)
        source_facts = await media_facts(source, ffprobe=self._ffprobe)
        expected_duration = source_facts.duration
        if profile.duration_limit_seconds is not None:
            expected_duration = min(expected_duration, Fraction(str(profile.duration_limit_seconds)))
        tolerance = 1 / profile.fps + Fraction(1, 20)
        expected_audio = ["aac"] if source_facts.audio else []
        collisions = list(overlay_collisions(plan))
        errors = await decode_errors(artifact, ffmpeg=self._ffmpeg)
        ratio = reduced_ratio(observed.width, observed.height)
        target_ratio = reduced_ratio(profile.width, profile.height)
        checks = (
            _check("dimensions", f"{observed.width}x{observed.height}", f"{profile.width}x{profile.height}"),
            _check("ratio", f"{ratio[0]}:{ratio[1]}", f"{target_ratio[0]}:{target_ratio[1]}"),
            _check("video_codec", observed.codec, profile.video_codec),
            _check("fps", str(observed.fps), str(profile.fps)),
            _check(
                "duration",
                _seconds(observed.duration),
                _seconds(expected_duration),
                passed=abs(observed.duration - expected_duration) <= tolerance,
            ),
            _check("audio", list(observed.audio), expected_audio),
            _check("decode", errors, 0),
            _check("overlay", collisions, []),
        )
        report = TechnicalValidationReport(
            report_id="tech-" + hashlib.sha256(f"{execution_id}\x1f{render.artifact_digest}".encode()).hexdigest()[:32],
            plan_digest=plan.plan_digest,
            artifact_digest=str(render.artifact_digest),
            checks=tuple(CanonicalJsonObject.model_validate(check) for check in checks),
            passed=all(check["verdict"] == "PASS" for check in checks),
        )
        async with self._sessions() as session:
            stored = await FormatRepository(session).append_technical_report(
                user_id=user_id, project_name=project_name, plan_id=plan.plan_id, report=report
            )
            await session.commit()
        return stored


__all__ = ["FormatValidationService", "MediaFacts", "decode_errors", "media_facts"]
