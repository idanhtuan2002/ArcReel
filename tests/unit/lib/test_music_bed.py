"""The music bed client against a scripted ACE-Step REST server."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from lib.music_bed import MusicCue, MusicService, MusicUnavailable, cue_for, music_service_from_env

pytestmark = pytest.mark.asyncio
WAV = b"RIFF" + bytes(2048)
CUE = MusicCue(caption="slow piano", bpm=72, seconds=50.0)


def _server(status_after: list[int], seen: list[httpx.Request]) -> httpx.MockTransport:
    statuses = iter(status_after)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/free":
            return httpx.Response(200, json={})
        if request.url.path == "/release_task":
            return httpx.Response(200, json={"code": 200, "data": {"task_id": "t1", "status": "queued"}})
        if request.url.path == "/query_result":
            status = next(statuses)
            result = json.dumps([{"file": "/v1/audio?path=a.wav", "status": status}]) if status == 1 else ""
            return httpx.Response(200, json={"data": [{"task_id": "t1", "status": status, "result": result}]})
        return httpx.Response(200, content=WAV)

    return httpx.MockTransport(handle)


async def test_the_cue_is_asked_as_an_instrumental_at_a_fixed_seed_after_freeing_the_gpu(tmp_path: Path):
    seen: list[httpx.Request] = []
    service = MusicService(
        "http://music", free_urls=["http://comfy/free"], poll_seconds=0, transport=_server([0, 1], seen)
    )

    path = await service.render(CUE, tmp_path / "bed.wav")

    assert path.read_bytes() == WAV
    assert [request.url.path for request in seen][:2] == ["/free", "/release_task"]
    body = json.loads(seen[1].content)
    assert body["lyrics"] == "[Instrumental]"
    assert (body["bpm"], body["audio_duration"], body["seed"], body["thinking"]) == (72, 50.0, CUE.seed, False)
    assert body["use_random_seed"] is False


async def test_a_cached_bed_is_not_generated_again(tmp_path: Path):
    seen: list[httpx.Request] = []
    target = tmp_path / "bed.wav"
    target.write_bytes(b"old")

    await MusicService("http://music", transport=_server([], seen)).render(CUE, target)

    assert seen == []


async def test_a_failed_generation_raises(tmp_path: Path):
    service = MusicService("http://music", poll_seconds=0, transport=_server([2], []))
    with pytest.raises(MusicUnavailable):
        await service.render(CUE, tmp_path / "bed.wav")
    assert not (tmp_path / "bed.wav").exists()


def test_the_cue_comes_from_the_overview_and_covers_the_episode():
    project = {"overview": {"music_caption": " piano ", "music_bpm": 400}}

    cue = cue_for(project, 46.0)

    assert cue is not None
    assert (cue.caption, cue.bpm, cue.seconds) == ("piano", 160, 50.0)
    assert cue_for({"overview": {}}, 46.0) is None
    assert cue.digest() == cue_for(project, 46.0).digest()


def test_no_music_url_means_no_music():
    assert music_service_from_env({}) is None
    assert music_service_from_env({"ARCREEL_MUSIC_URL": "http://127.0.0.1:8001"}) is not None


async def test_an_answer_that_is_not_audio_is_never_cached(tmp_path: Path):
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/release_task":
            return httpx.Response(200, json={"data": {"task_id": "t1"}})
        if request.url.path == "/query_result":
            result = json.dumps([{"file": "/v1/audio?path=a.wav"}])
            return httpx.Response(200, json={"data": [{"task_id": "t1", "status": 1, "result": result}]})
        return httpx.Response(200, content=b"<html>error</html>")

    service = MusicService("http://music", poll_seconds=0, transport=httpx.MockTransport(handle))
    with pytest.raises(MusicUnavailable):
        await service.render(CUE, tmp_path / "bed.wav")
    assert not (tmp_path / "bed.wav").exists()
