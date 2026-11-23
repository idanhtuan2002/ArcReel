"""Voice adapter at DramaClaw's model boundary (ASSEMBLY_PLAN D9, §0).

DramaClaw (``generators/indextts2_fal.py:315-360``, ``INDEXTTS2_PROVIDER=fal``) posts
``{"audio_url": <reference voice>, "prompt": <line>, "emotion_prompt": …}`` and expects ``{"audio": {"url": …}}``, then
downloads that URL. The reference arrives inline as a ``data:`` URL (or as an http URL when a media relay is used); its
SHA-256 names the VieNeu preset the connector cast (``assembly.voices.registry``). An unknown sample is an error, never
a silent fallback voice. VieNeu has no emotion control, so ``emotion_prompt`` is ignored.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from assembly.voices import registry

SHIM_URL = os.environ.get("VIENEU_SHIM_URL", "http://127.0.0.1:23340")
PUBLIC_BASE = os.environ.get("ASSEMBLY_VOICE_PUBLIC_BASE", "http://host.docker.internal:23350")
OUT_DIR = Path(os.environ.get("ASSEMBLY_VOICE_OUT", str(Path.home() / "assembly-data/voice-out")))
_AUDIO_ID = re.compile(r"^[0-9a-f]{32}$")

app = FastAPI(title="Assembly voice adapter (DramaClaw IndexTTS2 fal → VieNeu)")


class FalSpeechRequest(BaseModel):
    audio_url: str
    prompt: str
    emotion_prompt: str = ""


async def _reference_bytes(audio_url: str, client: httpx.AsyncClient) -> bytes:
    if audio_url.startswith("data:"):
        header, _, payload = audio_url.partition(",")
        if ";base64" not in header or not payload:
            raise HTTPException(status_code=422, detail="reference audio data URL is not base64")
        return base64.b64decode(payload)
    if audio_url.startswith(("http://", "https://")):
        response = await client.get(audio_url, follow_redirects=True)
        response.raise_for_status()
        return response.content
    raise HTTPException(status_code=422, detail="unsupported reference audio URL")


async def synthesize(request: FalSpeechRequest, client: httpx.AsyncClient, *, registry_file: Path | None = None) -> str:
    sample = await _reference_bytes(request.audio_url, client)
    preset = registry.load(registry_file).get(registry.sample_digest(sample))
    if preset is None:
        raise HTTPException(status_code=422, detail="unknown voice sample: cast it with assembly.voices before speech")
    response = await client.post(
        f"{SHIM_URL}/v1/audio/speech", json={"input": request.prompt, "voice": preset, "response_format": "mp3"}
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"VieNeu answered {response.status_code}: {response.text[:200]}")
    audio_id = uuid.uuid4().hex
    await asyncio.to_thread(_store, audio_id, response.content)
    return f"{PUBLIC_BASE}/audio/{audio_id}.mp3"


def _store(audio_id: str, content: bytes) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{audio_id}.mp3").write_bytes(content)


@app.post("/fal-ai/index-tts-2/text-to-speech")
async def text_to_speech(request: FalSpeechRequest) -> dict[str, dict[str, str]]:
    async with httpx.AsyncClient(timeout=600) as client:
        return {"audio": {"url": await synthesize(request, client)}}


class NewApiSpeechRequest(BaseModel):
    model: str = "index-tts-2"
    input: str
    metadata: dict[str, object] = {}


@app.post("/v1/audio/speech")
async def newapi_speech(request: NewApiSpeechRequest) -> FileResponse:
    """DramaClaw's in-pipeline IndexTTS2 path: NewAPI `audio/speech` with the sample in `metadata.audio_url`
    (`generators/indextts2_fal.py` `_generate_via_newapi`; the direct fal path is refused inside tasks)."""
    audio_url = str(request.metadata.get("audio_url") or "")
    emotion = str(request.metadata.get("emotion_prompt") or "")
    async with httpx.AsyncClient(timeout=600) as client:
        url = await synthesize(
            FalSpeechRequest(audio_url=audio_url, prompt=request.input, emotion_prompt=emotion), client
        )
    audio_id = url.rsplit("/", 1)[1].split(".", 1)[0]
    return FileResponse(OUT_DIR / f"{audio_id}.mp3", media_type="audio/mpeg")


@app.get("/audio/{name}")
async def audio(name: str) -> FileResponse:
    audio_id, _, ext = name.partition(".")
    path = OUT_DIR / f"{audio_id}.mp3"
    if ext != "mp3" or not _AUDIO_ID.match(audio_id) or not path.is_file():
        raise HTTPException(status_code=404, detail="no such audio")
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok", "registered_samples": len(registry.load())}
