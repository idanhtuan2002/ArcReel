# Assembly models — slot → model → pool → fallback

Source of truth for values: `assembly/config/dramaclaw-profile.json` (applied in DramaClaw → Settings → Models & Channels
→ My Config). Probe evidence: `evidence/ASSEMBLY_ACCEPTANCE.md` (M1.0, M1a). Quotas: `cloud-free-quota-registry.md`.

| Slot (DramaClaw name) | Model | Channel | Pool | Fallback |
|---|---|---|---|---|
| All `DC-*-LLM` text features, Hermes | `baidu/ernie-5.5-flash-preview:free` → OpenRouter `models` fallback `particle-1:free`, `ling-3.2-flash:free` (`assembly/ops/newapi_text_fallback.py`) | OpenRouter (NewAPI ch 1) | OpenRouter free, 1 000 req/day shared; upstream TPM 429s are transient | change `featureModels.text` to `gemini-3.5-flash-lite` (Gemini channel) |
| Vision features (`DC-video-*`, `DC-freezone-vision-LLM`, `DC-style-analyzer-LLM`) | `gemini-3.5-flash` + pool `gemini-3.5-flash-lite`, `gemini-2.5-flash`, `gemini-3-flash-preview` | Gemini ch 2 + clones ch 5–7 (`assembly/ops/newapi_vision_pool.py`), NewAPI `RetryTimes=3` moves a 429 to the next channel | ~20 req/day/model; an episode needs ~36 vision calls | `gemini-3.6-flash` has no free quota; `gemini-3.6-flash-lite` does not exist (probed 2026-11-24) |
| `DC-cognee-embedding` (768) | `gemini-embedding-001` | Gemini (ch 2) | free tier | — (bound per project at creation) |
| Images `LingShan-G2`, `LingShan-NB-2` | `seedream-4-5-251128`, `watermark: false` | VolcEngine type → `assembly/image_adapter` (172.17.0.1:23360, raises DramaClaw's fixed 1K sizes to Seedream 4.5's 3 686 400-pixel minimum) → BytePlus ap-southeast (ch 3) | 200 images once-only | local image adapter in front of ComfyUI (M6) |
| Video `Wan22-5B-local` (project default) | Wan2.2 TI2V 5B Q4 GGUF, 480p, 2–5 s, first frame | ComfyUI (gateway task channel, bridge `172.17.0.1:8189`) | local GPU, ~3 min per 2 s clip | `seedance-1.0-pro-fast` |
| Video `seedance-1.0-pro-fast` | `seedance-1-0-pro-fast-251015`, `watermark: false` | VolcEngine (ch 3) | once-only, ~18–23 clips | — |
| Speech `index-tts-2` | VieNeu-TTS v3 Turbo presets via `assembly/voice_adapter` (`/v1/audio/speech`, sample in `metadata.audio_url`) | `INDEXTTS2_PROVIDER=newapi` → NewAPI channel `assembly-voice` (`assembly/ops/newapi_voice_channel.py`) → 172.17.0.1:23350 (the fal path is refused inside tasks) | local | — |
| Media relay | Cloudinary folder `dramaclaw-relay` | DramaClaw Media Storage | free tier | inline relay (D28, probes pass) |

Aspect ratios: only `Wan22-5B-local` is limited to 9:16 (its graph renders 480×848 whatever size is requested, to fit
8 GB of VRAM); Seedream, Seedance and any future model keep their own ratio options.
