"""The voice adapter answers DramaClaw's IndexTTS2 fal request with VieNeu speech (ASSEMBLY_PLAN D9, §0)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from assembly.voice_adapter import app as adapter
from assembly.voices import registry


def _read(path: str | Path) -> bytes:
    return Path(path).read_bytes()


def _client(seen: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b"ID3-mp3-bytes", headers={"content-type": "audio/mpeg"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_cast_sample_is_spoken_in_its_preset_and_served_as_mp3(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(adapter, "OUT_DIR", tmp_path / "out")
    reg = tmp_path / "reg.json"
    registry.register(b"vy-sample", "Ngọc Huyền", reg)
    data_url = "data:audio/wav;base64," + base64.b64encode(b"vy-sample").decode()
    seen: list[dict] = []
    async with _client(seen) as client:
        url = await adapter.synthesize(
            adapter.FalSpeechRequest(audio_url=data_url, prompt="Bác ơi, bác còn sửa đồng hồ không ạ?"),
            client,
            registry_file=reg,
        )
    assert seen == [{"input": "Bác ơi, bác còn sửa đồng hồ không ạ?", "voice": "Ngọc Huyền", "response_format": "mp3"}]
    assert url.startswith(adapter.PUBLIC_BASE + "/audio/")
    assert url.endswith(".mp3")
    name = url.rsplit("/", 1)[1]
    assert (tmp_path / "out" / name).read_bytes() == b"ID3-mp3-bytes"


async def test_an_unknown_sample_is_refused_not_spoken_in_another_voice(tmp_path: Path) -> None:
    data_url = "data:audio/wav;base64," + base64.b64encode(b"never-cast").decode()
    async with _client([]) as client:
        with pytest.raises(HTTPException) as caught:
            await adapter.synthesize(
                adapter.FalSpeechRequest(audio_url=data_url, prompt="x"), client, registry_file=tmp_path / "reg.json"
            )
    assert caught.value.status_code == 422


async def test_a_reference_that_is_neither_data_nor_http_is_refused(tmp_path: Path) -> None:
    async with _client([]) as client:
        with pytest.raises(HTTPException) as caught:
            await adapter.synthesize(
                adapter.FalSpeechRequest(audio_url="file:///etc/passwd", prompt="x"),
                client,
                registry_file=tmp_path / "r.json",
            )
    assert caught.value.status_code == 422


async def test_the_newapi_speech_route_returns_mp3_for_a_cast_sample(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(adapter, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("ASSEMBLY_VOICE_REGISTRY", str(tmp_path / "reg.json"))
    registry.register(b"khang-sample", "Minh Đức", tmp_path / "reg.json")
    sample = "data:audio/wav;base64," + base64.b64encode(b"khang-sample").decode()

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        return real_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ID3-khang")))

    monkeypatch.setattr(adapter.httpx, "AsyncClient", fake_client)
    response = await adapter.newapi_speech(
        adapter.NewApiSpeechRequest(input="Sửa được thì sửa.", metadata={"audio_url": sample})
    )
    assert response.media_type == "audio/mpeg"
    assert _read(response.path) == b"ID3-khang"
