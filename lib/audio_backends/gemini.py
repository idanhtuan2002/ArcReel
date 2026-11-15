"""GeminiAudioBackend — Gemini TTS（``generateContent`` + ``responseModalities: AUDIO``）。

请求只带文本与预置音色；语种由模型按输入文本自动识别（官方 speech-generation 文档），
``language_type`` 不发送。应答音频在 ``inline_data``：3.8 系列为带 RIFF 头的 ``audio/wav``，
2.5/3.1 系列为裸 ``audio/L16``（24 kHz、单声道、16-bit 小端），后者按 mime 中的 rate 补 WAV 头落盘。
经自定义供应商 ``gemini-tts`` endpoint 包装为 ``CustomAudioBackend`` 后接入。
"""

from __future__ import annotations

import io
import logging
import re
import wave
from typing import Any

from lib.audio_backends.base import (
    AudioCapability,
    AudioSynthesisRequest,
    AudioSynthesisResult,
    VoiceOption,
)
from lib.config.url_utils import normalize_base_url
from lib.gemini_shared import resolve_gemini_api_key
from lib.providers import PROVIDER_GEMINI
from lib.retry import with_retry_async
from lib.video_backends.base import should_retry_paid_sdk_submit

logger = logging.getLogger(__name__)

# 官方 speech-generation 文档列出的 30 个预置音色（名称 -- 风格），见 docs/api-docs/endpoints/gemini-tts.md。
_VOICES: tuple[tuple[str, str], ...] = (
    ("Zephyr", "Bright"),
    ("Puck", "Upbeat"),
    ("Charon", "Informative"),
    ("Kore", "Firm"),
    ("Fenrir", "Excitable"),
    ("Leda", "Youthful"),
    ("Orus", "Firm"),
    ("Aoede", "Breezy"),
    ("Callirrhoe", "Easy-going"),
    ("Autonoe", "Bright"),
    ("Enceladus", "Breathy"),
    ("Iapetus", "Clear"),
    ("Umbriel", "Easy-going"),
    ("Algieba", "Smooth"),
    ("Despina", "Smooth"),
    ("Erinome", "Clear"),
    ("Algenib", "Gravelly"),
    ("Rasalgethi", "Informative"),
    ("Laomedeia", "Upbeat"),
    ("Achernar", "Soft"),
    ("Alnilam", "Firm"),
    ("Schedar", "Even"),
    ("Gacrux", "Mature"),
    ("Pulcherrima", "Forward"),
    ("Achird", "Friendly"),
    ("Zubenelgenubi", "Casual"),
    ("Vindemiatrix", "Gentle"),
    ("Sadachbia", "Lively"),
    ("Sadaltager", "Knowledgeable"),
    ("Sulafat", "Warm"),
)
_DEFAULT_PCM_RATE = 24000


def _wav_bytes(data: bytes, mime_type: str) -> bytes:
    """WAV 原样返回；裸 L16 PCM 按 mime 的 rate（缺省 24 kHz）补单声道 16-bit WAV 头。"""
    mime = (mime_type or "").lower()
    if data[:4] == b"RIFF" or mime in ("audio/wav", "audio/x-wav", "audio/wave"):
        return data
    match = re.search(r"rate=(\d+)", mime)
    rate = int(match.group(1)) if match else _DEFAULT_PCM_RATE
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(data)
    return buffer.getvalue()


class GeminiAudioBackend:
    """Gemini TTS 语音合成后端。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str,
        provider_name: str = PROVIDER_GEMINI,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from google import genai

            effective_base_url = normalize_base_url(base_url)
            http_options = {"base_url": effective_base_url} if effective_base_url else None
            client = genai.Client(api_key=resolve_gemini_api_key(api_key), http_options=http_options)  # type: ignore[arg-type]
        self._client = client
        self._model = model
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        return self._provider_name

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[AudioCapability]:
        return {AudioCapability.TEXT_TO_SPEECH}

    def list_voices(self) -> list[VoiceOption]:
        return [VoiceOption(id=name, label=f"{name} ({style})") for name, style in _VOICES]

    async def synthesize(self, request: AudioSynthesisRequest) -> AudioSynthesisResult:
        # 计费调用与写盘分离：重试只包 API 调用。
        data, mime_type = await self._request_speech(request)
        request.output_path.write_bytes(_wav_bytes(data, mime_type))
        logger.info("Gemini 语音合成完成: %s", request.output_path)
        return AudioSynthesisResult(
            provider=self._provider_name,
            model=self._model,
            characters=len(request.text),
            output_path=request.output_path,
        )

    @with_retry_async(retry_if=should_retry_paid_sdk_submit)
    async def _request_speech(self, request: AudioSynthesisRequest) -> tuple[bytes, str]:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=request.voice)
                )
            ),
        )
        logger.info(
            "调用 %s 语音合成 model=%s voice=%s chars=%d", self.name, self._model, request.voice, len(request.text)
        )
        response = await self._client.aio.models.generate_content(
            model=self._model, contents=request.text, config=config
        )
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    return inline.data, getattr(inline, "mime_type", "") or ""
        raise RuntimeError(f"Gemini TTS reply has no audio (model={self._model})")


__all__ = ["GeminiAudioBackend"]
