"""A video becomes a story source (ADR-0161): its sound is fetched, transcribed and written as prose paragraphs.

The source is never reused as footage. Its transcript is the material a variant is written from (ADR-0115 variant
profiles): new storyline, new narration, new voice and new pictures, so the result is a transformed work, as the
platforms' reused-content rules require. Only the audio is downloaded; it is cut into mono 16 kHz MP3 chunks that fit
an OpenAI-compatible transcription endpoint's upload limit (Whisper on Groq: 25 MB).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The longest source taken, in seconds.
MAX_SOURCE_SECONDS = 3 * 3600
#: Chunk length sent to the transcription endpoint (64 kbit/s mono → about 9.6 MB per 20 minutes).
CHUNK_SECONDS = 1200
#: A pause at least this long between two transcribed segments starts a new paragraph.
PARAGRAPH_GAP_SECONDS = 1.6
PARAGRAPH_MAX_CHARS = 900


class IngestRefused(ValueError):
    """The source cannot be taken; the code names why."""


@dataclass(frozen=True)
class SourceInfo:
    url: str
    title: str
    uploader: str
    duration: float
    extractor: str


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str | None
    segments: list[Segment] = field(default_factory=list)


def download_audio(url: str, workdir: Path) -> tuple[Path, SourceInfo]:
    """The best audio stream of ``url`` (one video, no playlist) and what it is; refuses a source longer than
    ``MAX_SOURCE_SECONDS``. Blocking: run it in a thread."""
    import yt_dlp

    if not re.match(r"^https?://", url):
        raise IngestRefused("UNSUPPORTED_URL")
    workdir.mkdir(parents=True, exist_ok=True)
    options: Any = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(workdir / "source.%(ext)s"),
        "restrictfilenames": True,
    }
    with yt_dlp.YoutubeDL(options) as client:
        info = client.extract_info(url, download=False)
        duration = float(info.get("duration") or 0)
        if duration > MAX_SOURCE_SECONDS:
            raise IngestRefused("SOURCE_TOO_LONG")
        info = client.extract_info(url, download=True)
        path = Path(client.prepare_filename(info))
    if not path.is_file():
        found = sorted(workdir.glob("source.*"))
        if not found:
            raise IngestRefused("DOWNLOAD_FAILED")
        path = found[0]
    return path, SourceInfo(
        url=str(info.get("webpage_url") or url),
        title=str(info.get("title") or ""),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=duration,
        extractor=str(info.get("extractor_key") or info.get("extractor") or ""),
    )


async def _run(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, err = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode(errors='replace')[-400:]}")


async def audio_chunks(source: Path, workdir: Path, *, chunk_seconds: int = CHUNK_SECONDS) -> list[Path]:
    """The source's sound as mono 16 kHz 64 kbit/s MP3 chunks of ``chunk_seconds``."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not installed")
    out = workdir / "chunks"
    await asyncio.to_thread(out.mkdir, parents=True, exist_ok=True)
    pattern = out / "chunk-%03d.mp3"
    await _run(
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-reset_timestamps",
        "1",
        str(pattern),
    )
    return await asyncio.to_thread(lambda: sorted(out.glob("chunk-*.mp3")))


Transcribe = Callable[[Path], Any]


async def transcribe(
    chunks: Sequence[Path], call: Callable[[Path], Any], *, chunk_seconds: int = CHUNK_SECONDS
) -> Transcript:
    """Every chunk transcribed by ``call(path)`` (an OpenAI ``verbose_json`` transcription: ``language`` and
    ``segments`` with ``start``, ``end``, ``text``), stitched on one timeline."""
    transcript = Transcript(language=None)
    for index, chunk in enumerate(chunks):
        result = await call(chunk)
        body = result if isinstance(result, dict) else json.loads(json.dumps(result, default=lambda o: o.__dict__))
        transcript.language = transcript.language or body.get("language")
        offset = index * chunk_seconds
        segments = body.get("segments") or []
        if not segments and body.get("text"):
            segments = [{"start": 0.0, "end": float(chunk_seconds), "text": body["text"]}]
        for segment in segments:
            text = str(segment.get("text") or "").strip()
            if text:
                transcript.segments.append(
                    Segment(offset + float(segment.get("start") or 0), offset + float(segment.get("end") or 0), text)
                )
    return transcript


def paragraphs(transcript: Transcript) -> list[str]:
    """Segments joined into paragraphs, broken at a pause of ``PARAGRAPH_GAP_SECONDS`` or past
    ``PARAGRAPH_MAX_CHARS``."""
    out: list[str] = []
    current = ""
    last_end: float | None = None
    for segment in transcript.segments:
        gap = segment.start - last_end if last_end is not None else 0.0
        if current and (gap >= PARAGRAPH_GAP_SECONDS or len(current) + len(segment.text) > PARAGRAPH_MAX_CHARS):
            out.append(current)
            current = ""
        current = f"{current} {segment.text}".strip()
        last_end = segment.end
    if current:
        out.append(current)
    return out


def source_text(info: SourceInfo, transcript: Transcript) -> str:
    """The transcript as a story source: the title as its first line, then paragraphs."""
    body = paragraphs(transcript)
    title = info.title.strip() or "Video source"
    return "\n\n".join([title, *body]) + "\n"


def origin_record(info: SourceInfo, transcript: Transcript) -> dict[str, Any]:
    """Where the source came from, kept beside it for credit and audit (never narrated)."""
    return {
        "schema": "r2.video-source-origin.v1",
        "url": info.url,
        "title": info.title,
        "uploader": info.uploader,
        "extractor": info.extractor,
        "duration_seconds": info.duration,
        "language": transcript.language,
        "segments": len(transcript.segments),
        "use": "transformed variant only: new storyline, narration, voice and pictures; no footage reused",
    }


__all__ = [
    "CHUNK_SECONDS",
    "IngestRefused",
    "Segment",
    "SourceInfo",
    "Transcript",
    "audio_chunks",
    "download_audio",
    "origin_record",
    "paragraphs",
    "source_text",
    "transcribe",
]
