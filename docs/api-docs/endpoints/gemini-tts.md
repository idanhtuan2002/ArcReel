# gemini-tts

- 协议：[Gemini API speech generation (TTS)](https://ai.google.dev/gemini-api/docs/speech-generation)（`generateContent`，`responseModalities: AUDIO`，`speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName`；语种自动识别；行内音频标签 `<sigh>` / `<laugh>`；30 个预置音色）
- 计费：[Gemini API 定价](https://ai.google.dev/gemini-api/docs/pricing)
- 代码：`lib/custom_provider/endpoints.py::ENDPOINT_REGISTRY["gemini-tts"]`、`lib/audio_backends/gemini.py::GeminiAudioBackend`、`lib/narration_delivery.py::synthesis_text`
