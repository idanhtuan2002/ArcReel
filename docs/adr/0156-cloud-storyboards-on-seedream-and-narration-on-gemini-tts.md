---
status: accepted
---

# Cloud storyboards on Seedream and narration on Gemini TTS

Decided 2026-11-15. Sponsor: "ưu tiên ảnh, giọng đọc và dựng phim bằng model cloud"; then "đồng ý cho ảnh Seedream và giọng Gemini TTS lên trạng thái được dùng"; and a local-versus-cloud comparison on the same story.

Probe of the free cloud media the sponsor's keys reach (2026-11-15, one call each; `docs/r2/cloud-free-quota-registry.md`): BytePlus `seedream-4-5-251128` answered in 12 s with a 9:16 still of production quality; Gemini image models have no free quota (429); Gemini TTS `gemini-2.5-flash-preview-tts`, `gemini-3.1-flash-tts-preview`, `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts` answered in 4–6 s, and Whisper (Groq) read the Vietnamese back almost verbatim; Gemini's OpenAI-compatible layer has no `/audio/speech` (404). Editing and rendering stay local ffmpeg: no cloud service does that part better.

1. **Storyboards: endpoint `ark-seedream`.** A custom provider on the Ark protocol (BytePlus ModelArk or Volcengine) generates images through the existing `ArkImageBackend`: `POST /api/v3/images/generations`, references in the `image` field (Seedream 4.0/4.5 take up to 14), size from the aspect table (9:16 → 1600x2848, inside Seedream 4.5's 2560x1440–4096x4096 pixel range). The OpenAI `openai-images` endpoint sends references to `/images/edits`, which Ark does not have. `ArkImageBackend` now sends `watermark: false` (the official default is true, a visible "AI generated" mark).
2. **Narration: endpoint `gemini-tts`.** `GeminiAudioBackend` calls `generateContent` with `responseModalities: AUDIO` and a prebuilt voice (30 voices); the language is detected from the text. A WAV reply is written as is, raw L16 PCM is wrapped at its stated rate. Delivery cues (ADR-0152) become Gemini's inline tags (`[thở dài]` → `<sigh>`, `[cười]` → `<laugh>`); a cue without a Gemini tag is dropped. Endpoint inference sends a Google-format provider's TTS model to `gemini-tts`.
3. **Admission.** Both routes are paid cloud routes: in a release deployment each is used only after its route qualification (the host media probe's canary for the exact configuration, `qualification/media`) and with a per-call ceiling; the sponsor approved putting both into use once that evidence exists. Quotas are free: Seedream 4.5 + 4.0 + 5.0-lite ≈ 450 images once (about nine films); Gemini TTS daily per model.
4. **Comparison.** The trial story (`san-xuat-tu-ong-7fb4ef4b`, "Chuyến đò cuối") finishes on local media (FLUX.2 klein, VieNeu) as the control; the same story is then rendered with Seedream storyboards and Gemini narration. The sponsor listens to the narration; storyboards are judged by face identity (ADR-0151) and by eye.

Not covered: Seedance video (2M tokens once, ~18 clips; cloud video adapters stay `UNQUALIFIED` until their own evidence), Alibaba Qwen TTS (its endpoint answered `InvalidParameter: url error`; not pursued).
