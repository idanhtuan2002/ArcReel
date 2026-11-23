# Assembly models — slot → model → pool → fallback

Source of truth for values: `assembly/config/dramaclaw-profile.json` (applied in DramaClaw → Settings → Models & Channels
→ My Config). Probe evidence: `evidence/ASSEMBLY_ACCEPTANCE.md` (M1.0, M1a). Quotas: `cloud-free-quota-registry.md`.

| Slot (DramaClaw name) | Model | Channel | Pool | Fallback |
|---|---|---|---|---|
| All `DC-*-LLM` text features, Hermes | `baidu/ernie-5.5-flash-preview:free` | OpenRouter (NewAPI ch 1) | OpenRouter free, 1 000 req/day shared; upstream TPM 429s are transient | change `featureModels.text` to `gemini-3.5-flash-lite` (Gemini channel) |
| Vision features (`DC-video-*`, `DC-freezone-vision-LLM`, `DC-style-analyzer-LLM`) | `gemini-3.5-flash` | Gemini (ch 2) | 20 req/day/model; 503 "high demand" seen, 38 s answer | `gemini-3.5-flash-lite`, `gemini-2.5-flash` (both probed OK) |
| `DC-cognee-embedding` (768) | `gemini-embedding-001` | Gemini (ch 2) | free tier | — (bound per project at creation) |
| Images `LingShan-G2`, `LingShan-NB-2` | `seedream-4-5-251128`, `watermark: false` | VolcEngine type → BytePlus ap-southeast (ch 3) | 200 images once-only | local image adapter in front of ComfyUI (M6) |
| Video `Wan22-5B-local` (project default) | Wan2.2 TI2V 5B Q4 GGUF, 480p, 2–5 s, first frame | ComfyUI (gateway task channel, bridge `172.17.0.1:8189`) | local GPU, ~3 min per 2 s clip | `seedance-1.0-pro-fast` |
| Video `seedance-1.0-pro-fast` | `seedance-1-0-pro-fast-251015`, `watermark: false` | VolcEngine (ch 3) | once-only, ~18–23 clips | — |
| Speech (IndexTTS2 fal path) | VieNeu-TTS v3 Turbo presets via `assembly/voice_adapter` | env `INDEXTTS2_PROVIDER=fal` → `host.docker.internal:23350` | local | — |
| Media relay | Cloudinary folder `dramaclaw-relay` | DramaClaw Media Storage | free tier | inline relay (D28, probes pass) |

Aspect ratios: only `Wan22-5B-local` is limited to 9:16 (its graph renders 480×848 whatever size is requested, to fit
8 GB of VRAM); Seedream, Seedance and any future model keep their own ratio options.
