"""A video becomes the story of a transformed variant (ADR-0161 unit, reused whole from `lib.video_ingest`).

URL → `download_audio` (yt-dlp, one video) or a local file → `audio_chunks` → `transcribe` with local faster-whisper
large-v3 → `source_text` (title + paragraphs) and `origin_record` ("transformed variant only"). The story file then
goes through the normal film path, where DramaClaw's rewrite retells it as new narration with new pictures and voices.
"""

from __future__ import annotations

import asyncio
import base64
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


VISUAL_PROMPT = """Đây là {n} khung hình lấy theo thứ tự thời gian (mỗi ~{step} giây) từ một video ngắn không có lời.
Hãy kể lại câu chuyện mà video thể hiện thành văn xuôi tiếng Việt tự nhiên, theo từng cảnh, mỗi cảnh một đoạn:
nhân vật (ngoại hình, tính cách thể hiện qua hành động), bối cảnh, hành động, cảm xúc và diễn biến tới kết thúc.
Không thêm lời thoại không có trong hình; không nhắc tới "khung hình" hay "video". Chỉ trả về câu chuyện."""


def sample_frames(video: Path, workdir: Path, *, step: float = 3.0, limit: int = 24) -> list[Path]:
    out = workdir / "frames"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps=1/{step},scale=512:-2",
            "-frames:v",
            str(limit),
            str(out / "f%03d.jpg"),
        ],
        check=True,
    )
    return sorted(out.glob("f*.jpg"))


def visual_story(frames: list[Path], *, step: float, call: Any) -> str:
    """The story a wordless video tells, from its frames, by DramaClaw's vision model slot on NewAPI."""
    content: list[dict[str, Any]] = [{"type": "text", "text": VISUAL_PROMPT.format(n=len(frames), step=int(step))}]
    for frame in frames:
        data = base64.b64encode(frame.read_bytes()).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
    return str(call(content)).strip()


def _vision_call(content: list[dict[str, Any]]) -> str:
    import httpx

    from assembly.connector.setup import NEWAPI_URL, _relay_token

    response = httpx.post(
        f"{NEWAPI_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {_relay_token()}"},
        json={
            "model": "DC-freezone-vision-LLM",
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 4000,
        },
        timeout=600,
    )
    response.raise_for_status()
    return str(response.json()["choices"][0]["message"].get("content") or "")


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
    if not origin.get("segments") and audio.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}:
        # No speech: the story comes from the pictures (wordless Shorts are common).
        frames = sample_frames(audio, workdir)
        body = visual_story(frames, step=3.0, call=_vision_call)
        if not body:
            raise RuntimeError("the video has no speech and the vision model returned no story")
        text = f"{info.title.strip() or 'Video'}\n\n{body}\n"
        origin = {**origin, "language": "visual", "segments": 0, "frames": len(frames), "story_from": "pictures"}
    story = workdir / "story.txt"
    story.write_text(text, encoding="utf-8")
    (workdir / "origin.json").write_text(json.dumps(origin, ensure_ascii=False, indent=1), encoding="utf-8")
    return story, origin
