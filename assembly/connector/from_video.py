"""A video becomes the story of a transformed variant (ADR-0161 unit, reused whole from `lib.video_ingest`).

URL → `download_audio` (yt-dlp, one video) or a local file → `audio_chunks` → `transcribe` with local faster-whisper
large-v3 → `source_text` (title + paragraphs) and `origin_record` ("transformed variant only"). The story file then
goes through the normal film path, where DramaClaw's rewrite retells it as new narration with new pictures and voices.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from lib.video_ingest import SourceInfo, audio_chunks, download_audio, origin_record, source_text, transcribe

OPENMONTAGE_PYTHON = Path.home() / "assembly-data/openmontage/.venv/bin/python"
WHISPER_SCRIPT = Path(__file__).with_name("whisper_local.py")
# CTranslate2 needs CUDA 12 cuBLAS/cuDNN; MMAudio's venv on drive D already carries them (no extra download).
CUDA_LIBS = Path("/mnt/arcreel/D/ArcReel/mmaudio/.venv/lib/python3.11/site-packages/nvidia")


def _whisper_env() -> dict[str, str]:
    env = dict(os.environ)
    libs = ":".join(str(p) for p in sorted(CUDA_LIBS.glob("*/lib")))
    env["LD_LIBRARY_PATH"] = f"{libs}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


async def _whisper(chunk: Path) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        str(OPENMONTAGE_PYTHON),
        str(WHISPER_SCRIPT),
        str(chunk),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_whisper_env(),
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"whisper failed on {chunk.name}: {err.decode(errors='replace')[-400:]}")
    return json.loads(out)


def story_from_video(source: str, workdir: Path) -> tuple[Path, dict[str, Any]]:
    """Return the story file and its origin record for a URL or a local video/audio file."""
    workdir.mkdir(parents=True, exist_ok=True)
    if source.startswith(("http://", "https://")):
        audio, info = download_audio(source, workdir)
    else:
        audio = Path(source).expanduser()
        info = SourceInfo(url=str(audio), title=audio.stem, uploader="", duration=0.0, extractor="local")

    async def run() -> tuple[str, dict[str, Any]]:
        chunks = await audio_chunks(audio, workdir)
        transcript = await transcribe(chunks, _whisper)
        return source_text(info, transcript), origin_record(info, transcript)

    text, origin = asyncio.run(run())
    story = workdir / "story.txt"
    story.write_text(text, encoding="utf-8")
    (workdir / "origin.json").write_text(json.dumps(origin, ensure_ascii=False, indent=1), encoding="utf-8")
    return story, origin
