"""Scene ambience: each scene's steady environment sound, generated once and looped under the scene.

A scene's ambience prompt is its look's English ``ambience`` (ADR-0141). A local MMAudio server turns the prompt into
an 8-second clip at a fixed seed; the clip is cached under the project by the prompt's digest and the renderer loops it
over the scene's window of the episode.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from lib.scene_looks import kept_look, scene_starts

CLIP_SECONDS = 8.0
SEED = 1


class AmbienceUnavailable(RuntimeError):
    """The ambience server could not produce the clip."""


@dataclass(frozen=True)
class SceneWindow:
    prompt: str
    start_us: int
    duration_us: int

    def digest(self) -> str:
        return hashlib.sha256(f"{self.prompt}|{CLIP_SECONDS}|{SEED}".encode()).hexdigest()[:24]


def scene_windows(
    items: Sequence[Mapping[str, Any]], durations: Mapping[str, int], *, id_field: str = "segment_id"
) -> list[SceneWindow]:
    """Each scene's ambience prompt and its window, from the episode's script items in order and each rendered
    unit's duration (µs); a scene without an ambience is skipped, a unit not rendered takes no time."""
    starts = scene_starts([item for item in items if item.get(id_field)], id_field=id_field)
    windows: list[SceneWindow] = []
    offset = 0
    current: str | None = None
    for item in items:
        unit = str(item.get(id_field) or "")
        duration = durations.get(unit, 0)
        if not unit or duration <= 0:
            continue
        look = kept_look(item)
        prompt = look.get("ambience") if look else None
        start = starts[unit]
        if isinstance(prompt, str) and prompt.strip() and start == current and windows:
            last = windows[-1]
            windows[-1] = SceneWindow(last.prompt, last.start_us, last.duration_us + duration)
        elif isinstance(prompt, str) and prompt.strip():
            windows.append(SceneWindow(prompt.strip(), offset, duration))
        current = start if isinstance(prompt, str) and prompt.strip() else None
        offset += duration
    return windows


class AmbienceService:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._transport = transport

    async def render(self, prompt: str, output: Path) -> Path:
        """Generate the clip for ``prompt`` into ``output`` (WAV); an existing ``output`` is returned as is."""
        if await asyncio.to_thread(output.is_file):
            return output
        try:
            async with httpx.AsyncClient(timeout=600.0, transport=self._transport) as client:
                response = await client.post(
                    f"{self._base}/v1/ambience", json={"prompt": prompt, "seconds": CLIP_SECONDS, "seed": SEED}
                )
                response.raise_for_status()
        except httpx.HTTPError as error:
            raise AmbienceUnavailable(f"ambience server: {error}") from error
        await asyncio.to_thread(_place, output, response.content)
        return output


def _place(output: Path, content: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.with_suffix(".part")
    staging.write_bytes(content)
    os.replace(staging, output)


def ambience_service_from_env(environ: Mapping[str, str] | None = None) -> AmbienceService | None:
    """``ARCREEL_AMBIENCE_URL`` (the MMAudio ambience server base); ``None`` when no server is configured."""
    env = os.environ if environ is None else environ
    base = env.get("ARCREEL_AMBIENCE_URL", "").strip()
    return AmbienceService(base) if base else None


__all__ = [
    "AmbienceService",
    "AmbienceUnavailable",
    "SceneWindow",
    "ambience_service_from_env",
    "scene_windows",
]
