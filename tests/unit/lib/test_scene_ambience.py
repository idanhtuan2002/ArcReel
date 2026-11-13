"""Scene ambience windows and the ambience client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from lib.scene_ambience import AmbienceService, AmbienceUnavailable, ambience_service_from_env, scene_windows


def _item(sid: str, ambience: str | None, *, scene_break: bool = False) -> dict:
    look = {"ambience": ambience} if ambience is not None else None
    return {"segment_id": sid, "segment_break": scene_break, "image_prompt": {"scene": "s", "look": look}}


def test_each_scene_gets_one_window_spanning_its_rendered_shots():
    items = [
        _item("S1", "rain on a roof"),
        _item("S2", "rain on a roof"),
        _item("S3", "night insects", scene_break=True),
        _item("S4", None, scene_break=True),
        _item("S5", "market chatter", scene_break=True),
    ]
    durations = {"S1": 4_000_000, "S2": 3_000_000, "S3": 5_000_000, "S4": 2_000_000, "S5": 6_000_000}

    windows = scene_windows(items, durations)

    assert [(w.prompt, w.start_us, w.duration_us) for w in windows] == [
        ("rain on a roof", 0, 7_000_000),
        ("night insects", 7_000_000, 5_000_000),
        ("market chatter", 14_000_000, 6_000_000),
    ]


@pytest.mark.asyncio
async def test_the_clip_is_asked_once_and_cached(tmp_path: Path):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"RIFF")

    service = AmbienceService("http://amb", transport=httpx.MockTransport(handle))
    target = tmp_path / "a.wav"

    await service.render("rain", target)
    await service.render("rain", target)

    assert target.read_bytes() == b"RIFF"
    assert len(seen) == 1
    assert json.loads(seen[0].content) == {"prompt": "rain", "seconds": 8.0, "seed": 1}


@pytest.mark.asyncio
async def test_a_failing_server_raises(tmp_path: Path):
    service = AmbienceService("http://amb", transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
    with pytest.raises(AmbienceUnavailable):
        await service.render("rain", tmp_path / "a.wav")


def test_no_ambience_url_means_no_ambience():
    assert ambience_service_from_env({}) is None
    assert ambience_service_from_env({"ARCREEL_AMBIENCE_URL": "http://127.0.0.1:8002"}) is not None
