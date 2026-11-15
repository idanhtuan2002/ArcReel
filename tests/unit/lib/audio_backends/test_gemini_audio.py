"""GeminiAudioBackend: Gemini TTS through generateContent, written as a WAV file."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib.audio_backends.base import AudioSynthesisRequest
from lib.audio_backends.gemini import GeminiAudioBackend


class _Models:
    def __init__(self, parts):
        self.calls: list[dict] = []
        self._parts = parts

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=self._parts))])


def _backend(parts) -> tuple[GeminiAudioBackend, _Models]:
    models = _Models(parts)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiAudioBackend(api_key="k", model="gemini-3.8-flash-tts", client=client), models


def _part(data: bytes, mime: str):
    return SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type=mime))


def _wav(frames: bytes, rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames)
    return buffer.getvalue()


async def test_raw_pcm_is_wrapped_as_a_wav_at_its_stated_rate(tmp_path: Path):
    backend, models = _backend([_part(b"\x01\x00" * 2400, "audio/L16;codec=pcm;rate=24000")])
    output = tmp_path / "n.wav"

    result = await backend.synthesize(
        AudioSynthesisRequest(text="Ông Bảy chèo đò.", output_path=output, voice="Charon")
    )

    with wave.open(str(output)) as written:
        assert (written.getframerate(), written.getnchannels(), written.getsampwidth()) == (24000, 1, 2)
        assert written.getnframes() == 2400
    assert (result.provider, result.model, result.characters) == ("gemini", "gemini-3.8-flash-tts", 16)
    config = models.calls[0]["config"]
    assert config.response_modalities == ["AUDIO"]
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Charon"
    assert models.calls[0]["contents"] == "Ông Bảy chèo đò."


async def test_a_wav_reply_is_kept_as_it_is(tmp_path: Path):
    body = _wav(b"\x02\x00" * 100)
    backend, _models = _backend([_part(body, "audio/wav")])
    output = tmp_path / "n.wav"

    await backend.synthesize(AudioSynthesisRequest(text="Chào.", output_path=output, voice="Kore"))

    assert output.read_bytes() == body


async def test_a_reply_without_audio_fails(tmp_path: Path):
    backend, _models = _backend([SimpleNamespace(inline_data=None, text="no")])
    with pytest.raises(RuntimeError, match="audio"):
        await backend.synthesize(AudioSynthesisRequest(text="Chào.", output_path=tmp_path / "n.wav", voice="Kore"))


def test_the_voice_catalog_is_the_prebuilt_voices():
    backend, _models = _backend([])
    voices = {voice.id for voice in backend.list_voices()}
    assert len(voices) == 30
    assert {"Charon", "Kore", "Sulafat"} <= voices


def test_a_gemini_tts_model_voices_the_delivery_cue_as_its_own_tag():
    from lib.narration_delivery import synthesis_text

    assert synthesis_text("[thở dài] Ông lặng đi.", "gemini-3.8-flash-tts") == "<sigh> Ông lặng đi."
    assert synthesis_text("[cười] Cô đáp.", "gemini-2.5-flash-preview-tts") == "<laugh> Cô đáp."
    assert synthesis_text("[hắng giọng] Ông nói.", "gemini-3.8-flash-tts") == "Ông nói."
    assert synthesis_text("[thở dài] Ông lặng đi.", "gemini-2.5-flash") == "Ông lặng đi."
