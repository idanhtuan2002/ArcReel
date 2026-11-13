# Cloud model access and free quotas (reference)

What each sponsor key can call, with which limits, and what it is good for in R2. Keys live only in the app's provider
settings (production DB `provider_credential` / `custom_provider`); never in this repo. Every row says how it was
verified and when; a free tier changes without notice, so re-check before relying on a number.

Sponsor decisions (2026-11-13): trial content may go to free tiers (providers may use free-tier inputs); stay on free
tiers, no billing. "Free only" switches are on where a provider has one.

Legend — **[V]** verified by a call or a 429 message from the provider on the date shown; **[C]** read in the
provider console by the sponsor; **[D]** from the provider's docs or third-party listings, not yet verified.

## Summary by use

| Use in R2 | Usable now (free) | Notes |
|---|---|---|
| Continuity judge / vision reviewer (ADR-0134, ADR-0113) | BytePlus `seed-2-0-pro`, `seed-2-0-lite`, `dola-seed-2-1-turbo`, `deepseek-v4-1-flash` (500k tokens each, once); Gemini `gemini-2.5-flash`, `gemini-3-flash-preview` (20 req/day each); Groq `qwen/qwen3.8-27b` (~28 judge calls/day) | Qualification needs 76 calls on one model identity: ~6.6k tokens each on Seed 2.0 Pro (≈ the whole 500k); 3–4 days per model on Gemini/Groq |
| Text writer / text reviewer | Gemini Flash models (20 req/day each); Groq `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` (1,000 req/day, 200k tokens/day) | Alibaba `qwen-*-character` only (role-play tuned) |
| Vietnamese TTS A/B (B1) | Alibaba `qwen-audio-3.1-tts-flash` / `-next` (1M), `-plus` (10K) | Vietnamese quality not tested yet |
| ASR (narration vs subtitles check) | Alibaba `qwen-audio-3.1-asr-flash*` (1M), `fun-asr-flash-2026-06-15` (36K); Groq `whisper-large-v3(-turbo)` | |
| Image generation | BytePlus Seedream 4.0 / 4.5 (200 images each), 5.0-lite (50) [C] | local FLUX.2 klein (ComfyUI) stays the default |
| Video generation (bake-off B1) | BytePlus Seedance 1.0 pro / pro-fast (2M tokens each) [C] | ≈ 108k tokens per 5 s 720p clip → ~18 clips per model; Seedance 2.x has no free quota |

## Google AI Studio (Gemini)

- App provider: built-in `gemini-aistudio`. Key: **free tier** (no billing).
- **[V 2026-11-13]** Limit: **20 generate requests per model per day** (429 `generate_content_free_tier_requests, limit: 20`
  seen for `gemini-3.5-flash` — reported under metric model `gemini-3.6-flash` — and for `gemini-2.5-flash`). Resets at
  midnight Pacific = 15:00 ICT. Each model has its own 20.
- **[V 2026-11-13]** Model list (`GET /v1beta/models`), Flash/Pro family: `gemini-2.5-flash` (version `001`),
  `gemini-2.5-flash-lite`, `gemini-2.5-pro`, `gemini-2.5-flash-image`, `gemini-2.5-flash-preview-tts`,
  `gemini-2.5-pro-preview-tts`, `gemini-3-flash-preview` (`3-flash-preview-12-2025`), `gemini-3-pro-image(-preview)`,
  `gemini-3.1-flash-image(-preview)`, `gemini-3.1-flash-lite(-preview)`, `gemini-3.1-flash-tts-preview`,
  `gemini-3.1-pro-preview`, `gemini-3.5-flash` (`3.5-flash-05-2026`), `gemini-3.5-flash-lite`, `gemini-3.6-flash`,
  `gemini-3.7-flash`, `gemini-3.8-flash`, `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts`, `gemini-flash-latest`,
  `gemini-pro-latest`, `gemini-omni-1.1-flash`, `gemini-omni-1.2-flash`, `gemini-omni-flash-preview`,
  `lyria-3-pro-preview`, `nano-banana-pro-preview`, `deep-research-pro-preview-12-2025`.
- **[V 2026-11-13]** Answered: `gemini-2.5-flash`, `gemini-3-flash-preview`. `gemini-3.7-flash` did not answer within
  2 min on the free key. Image, video (Omni/Veo) and Pro models on the free tier: not tested (Veo 3.1 preview ids shut
  down 2026-10-22, see FILM handoff).
- Lite models are excluded as judges (2026-11-03 probes accepted real defects).
- Continuity qualification progress: `docs/r2/evidence/R2_FILM_QUALITY_HANDOFF.md`.

## Groq

- App provider: custom provider **`Groq` = `custom-4`**, base `https://api.groq.com/openai/v1`, endpoint
  `openai-chat`. Free tier ("on_demand").
- **[V 2026-11-13]** Limits for `qwen/qwen3.8-27b` (response headers and 429 text): **1,000 requests/day,
  8,000 tokens/minute, 200,000 tokens/day** (rolling). A continuity judge call (3 images + prompt + 2,048 max output)
  counts ~6.9k tokens → about 28 calls/day, about 1 per minute.
- **[V 2026-11-13]** `qwen/qwen3.8-27b` accepts **at most 3 images per request** (400 "Too many images provided");
  run the judge with `--max-pictures 3` (references on one sheet).
- **[V 2026-11-13]** Models (`GET /models`): `qwen/qwen3.8-27b` (only vision model, 131k context),
  `openai/gpt-oss-120b`, `openai/gpt-oss-20b`, `openai/gpt-oss-safeguard-20b`, `allam-2-7b`,
  `canopylabs/orpheus-v1-english`, `canopylabs/orpheus-arabic-saudi` (TTS, no Vietnamese),
  `meta-llama/llama-prompt-guard-2-22m/86m`, `whisper-large-v3`, `whisper-large-v3-turbo`.
- In the app the default model of `custom-4` should be `qwen/qwen3.8-27b` (it was `allam-2-7b` after discovery).

## Alibaba Cloud Model Studio (international)

- App provider: built-in `dashscope`, base URL **`https://dashscope-intl.aliyuncs.com`** (the app's default is the
  Beijing host, which a Singapore key cannot use). OpenAI-compatible path: `/compatible-mode/v1`.
- **[C 2026-11-13]** Free quota, Singapore region only, **Stop-on-Exhaust enabled** (exhausted → 403
  `AllocationQuota.FreeTierOnly`), all expire **2027-02-11**:

  | Model | Type | Free quota |
  |---|---|---|
  | `qwen-plus-character` | LLM (role-play) | 1M tokens |
  | `qwen-flash-character` | LLM (role-play) | 1M tokens |
  | `qwen-mt-image-2.0` | image translation | 100 |
  | `qwen-audio-3.1-tts-flash` | TTS | 1M |
  | `qwen-audio-3.1-tts-next` | TTS | 1M |
  | `qwen-audio-3.1-tts-plus` | TTS | 10K |
  | `qwen-audio-3.1-asr-flash` | ASR | 1M |
  | `qwen-audio-3.1-asr-flash-streaming` | ASR | 1M |
  | `qwen-audio-3.1-asr-flash-filetrans` | ASR | 1M |
  | `qwen-audio-3.1-asr-flash-message` | ASR | 1M |
  | `fun-asr-flash-2026-06-15` | ASR | 36K |
  | `qwen3.8-livetranslate-flash-realtime` | speech translation | 1M |
  | `qwen3.7-text-embedding` | embedding | 1M |

- **[V 2026-11-13]** `qwen-flash-character` answers. Every model outside the list answers 403
  `AccessDenied.Unpurchased` (tried `qwen3.7-plus-2026-05-26`, `qwen3-vl-plus`, `qwen3.8-flash`, `qwen-plus`,
  `qwen3.5-flash`). The account lists 102 models (`/compatible-mode/v1/models`), including `qwen3-vl-plus`,
  `qwen3.5/3.6/3.7/3.8-*`, `qwen3.x-omni-*`, `wan2.7-image(-pro)` — all paid.
- **[D]** Wan video free quotas were removed for `wan2.7-*` and `wan3.0-video-prime` on 2026-10-29.

## BytePlus ModelArk (international)

- App provider: custom provider **`BytePlus(Ark)` = `custom-5`**, base `https://ark.ap-southeast.bytepluses.com/api/v3`
  (OpenAI-compatible chat; video uses the Ark task API, endpoint `ark-seedance`). The built-in `ark` provider defaults to
  the Volcengine (China) host and `doubao-*` ids, which a BytePlus key cannot use.
- **[C 2026-11-13]** "Free credits only" mode **on**: a model stops when its free quota is used up; nothing is billed.
  Free quotas are once per account (no daily reset):

  | Model (console name) | Free quota | Notes |
  |---|---|---|
  | Seed 2.0 pro / lite / mini / code, Dola-Seed 2.1 turbo, Seed 1.8, Seed 1.6 (+flash), Seed Translation | 500k tokens each | Seed 2.x are vision models |
  | DeepSeek V4 / V4.1 Flash (+Economy, GA), V4 Pro (+GA), V3.2; GLM 5.2, 5.3 Flash, 4.7 | 500k tokens each | V4.1 Flash takes images |
  | Seedance 1.0 pro, 1.0 pro-fast, 1.5 pro | 2M tokens each | video; 1.5 pro has audio |
  | Seedream 4.0, 4.5 | 200 images each | |
  | Seedream 5.0-lite | 50 images | |
  | Seedance 2.0 / 2.0 fast / 2.0 mini / 2.5 / 2.5 flash; Seedream 5.0 pro / flash, 5.5 | none | paused in free-only mode |
  | Skylark embedding vision | 500k tokens | |

- **[V 2026-11-13]** `GET /models` lists 35 ids, e.g. `seed-2-0-pro-260328`, `seed-2-0-lite-260428`,
  `seed-2-0-mini-260428`, `dola-seed-2-1-turbo-260628`, `deepseek-v4-1-flash-261017` (VLM), `deepseek-v4-pro-ga-260813`,
  `glm-5-2-260617`, `seedance-1-0-pro-250528`, `seedance-1-0-pro-fast-251015`, `seedream-4-0-250828`,
  `seedream-4-5-251128`, `dreamina-seedance-2-*`. Seed 1.8 / 1.6 / Seedance 1.5 pro are not listed (not activated).
- **[V 2026-11-13]** Image questions answered by `seed-2-0-pro`, `seed-2-0-lite`, `dola-seed-2-1-turbo`,
  `deepseek-v4-1-flash`. One continuity judge case (4 images, no cap) on `seed-2-0-pro`: 5,777 prompt + 862 output
  tokens (815 reasoning), 17 s.

## Pending registration

| Provider | Expected free offer [D] | Would serve | App provider |
|---|---|---|---|
| OpenRouter | `:free` models, 50 req/day, 20 req/min | fallback text / vision | custom provider, `https://openrouter.ai/api/v1` |
| Mistral La Plateforme | free plan; terms differ between sources (may require training opt-in) | third-family reviewer (Pixtral / Mistral Medium) | custom provider, `https://api.mistral.ai/v1` |
| GitHub Models | reported retired 2026-07-30 | — | — |

When a key is added: verify with one model-list call and one tiny call, then fill a section above with [V] rows.
