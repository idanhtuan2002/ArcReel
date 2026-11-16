"""Transcription of a final film's sound for the speech check of every review (``final_checks.speech_findings``).

The route is the app's transcription model (a Whisper model enabled on a custom provider, the one video sources use).
The final's sound is cut to mono 16 kHz MP3 — a 60-second episode is well under Groq's 25 MB upload limit — and sent
once; the quality adapter keeps the transcript beside the reviews. No route, or a failed call, gives ``None``, which
leaves the speech unchecked.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from lib.openai_shared import create_openai_client
from lib.video_ingest import IngestRefused
from server.services.video_sources import whisper_route

logger = logging.getLogger(__name__)


def _sound(final: Path, out: Path, ffmpeg: str) -> bool:
    completed = subprocess.run(
        [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(final), "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "64k", str(out)],
        capture_output=True,
        timeout=300,
        check=False,
    )  # fmt: skip
    return completed.returncode == 0 and out.is_file() and out.stat().st_size > 0


def whisper_transcriber(sessions: Any, *, ffmpeg: str | None = None) -> Callable[[Path, str], Awaitable[str | None]]:
    """A transcriber of final films through the app's Whisper route."""

    async def transcribe(final: Path, language: str) -> str | None:
        binary = ffmpeg or shutil.which("ffmpeg")
        if binary is None:
            return None
        try:
            base_url, key, model_id = await whisper_route(sessions)
        except IngestRefused:
            return None
        with tempfile.TemporaryDirectory(prefix="arcreel-final-speech-") as work:
            sound = Path(work) / "speech.mp3"
            if not await asyncio.to_thread(_sound, final, sound, binary):
                logger.warning("could not extract the sound of %s", final)
                return None
            data = await asyncio.to_thread(sound.read_bytes)
        client = create_openai_client(api_key=key, base_url=base_url, max_retries=2)
        result = await client.audio.transcriptions.create(
            file=("speech.mp3", data), model=model_id, language=language.split("-")[0], response_format="json"
        )
        text = getattr(result, "text", None)
        return text if isinstance(text, str) else None

    return transcribe


__all__ = ["whisper_transcriber"]
