# Donor survey: how users add or swap LLM, VLM, image, video and TTS models (2026-11-08)

Scope: read-only. Pinned commits: ViMax `63bb9c7` (local checkout), DramaClaw `b299bfd`, OpenMontage `08e2151`, Jellyfish `a967819`.
Labels: **FACT** = read in source at the pinned commit; **INFER** = my reading; **UNKNOWN** = not verified.
Cite form: `path:line`. Paths are repo-relative. DramaClaw paths are under `src/novelvideo/`.
Coverage limit: I read only the files named below, not every file in each donor. Negative claims ("no X") apply to those files only, except where I say a repo-wide search was run.
I did not fetch LiteLLM docs. Reason: no donor uses LiteLLM as its main provider layer. DramaClaw only passes LiteLLM kwargs for Cognee/Instructor calls (`config.py:311-316`).

## 1. ViMax (`63bb9c7`)

**Provider abstraction and selection**
- FACT: Text uses LangChain `init_chat_model(**args)`, with args taken from the YAML `chat_model.init_args` (`pipelines/idea2video_pipeline.py:120-121`, `pipelines/script2video_pipeline.py:217-218`).
- FACT: The shipped config is `model_provider: openai` plus `base_url: https://openrouter.ai/api/v1`, so OpenRouter is used as an OpenAI-compatible endpoint (`configs/idea2video.yaml`, `chat_model.init_args`).
- FACT: `resolve_chat_model_config` has one built-in preset (minimax). It rewrites the provider to `openai`, fills `base_url`, takes the API key from the environment, and clamps temperature (`utils/provider_presets.py:19-31, 34-80`). Unknown providers pass through unchanged (`:46`).
- FACT: The agent runtime has a second LLM path, `OpenAICompatibleLLM`, which uses `AsyncOpenAI(base_url, api_key)` (`agent_runtime/llm.py:43-50`). Its settings come from `VIMAX_LLM_*` env vars or `configs/agent.local.yaml` (`agent_runtime/config.py:49-62`).
- FACT: A brand-new model id needs zero code change. The `model` string goes through to the endpoint (`configs/*.yaml`, `agent_runtime/config.py:49-50`).
- FACT: The only built-in presets are one `minimax` entry in `PROVIDER_PRESETS` (`utils/provider_presets.py:19-31`). Anything else is "OpenAI-compatible with a custom base_url".
- INFER: The universal protocol is OpenAI chat. Gemini native, Anthropic native and Ollama native are not first-class in this checkout.

**Vision / judge calls**
- FACT: Images go as OpenAI-style content parts, `{"type":"image_url","image_url":{"url": data-URI base64}}` (`agents/best_image_selector.py:112-125`, `agents/reference_image_selector.py:197-198`).
- FACT: The judge has no logprobs and no numeric score. It returns `best_image_index` plus `reason`, parsed with `PydanticOutputParser` (`best_image_selector.py:131-141`). An out-of-range index silently falls back to 0 (`:141-144`).
- FACT: Parse failures are retried with tenacity, 3 attempts (`best_image_selector.py:78-81`). A tolerant parser strips trailing commas, written for flash-lite via the OpenAI-compatible endpoint (`utils/robust_json_parser.py:1-30`).
- FACT: Structured output uses `with_structured_output(..., method="json_schema", strict=True)` (`agents/camera_image_generator.py:207-213`, `agents/screenwriter.py:239-241`, `agents/storyboard_artist.py:224-226`). The fallback is the original prompt plus `PydanticOutputParser` (`storyboard_artist.py:369-372`).
- INFER: Fallback is chosen by whether a `structured_chat_model` was injected, not by detecting that the provider ignored JSON mode. Judging this from the quoted lines only, not a full read of `storyboard_artist.py`.

**Media routes**
- FACT: Image and video backends are duck-typed Protocols (`generate_single_image`, `generate_single_video`) (`tools/protocols.py:14-35`).
- FACT: A backend is registered via YAML `class_path: tools.ImageGenerator...` plus `init_args`, instantiated with `importlib` (`tools/render_backend.py:56-62`). A user can point `class_path` at their own class with no change to the core.
- FACT: Adapters shipped: Google nanobanana/Veo, Yunwu (Doubao Seedream/Seedance, Veo, Omni), OpenRouter image and video (`tools/` listing). OpenRouter video is submit-then-poll with env-tunable timeouts: 60 s request, 600 s query, 10 s poll (`tools/video_generator_openrouter_api.py:62-64`).
- FACT: A new cloud model on an existing adapter is a config change (`model` argument, e.g. `tools/image_generator_openrouter_api.py:49`). A new vendor API means a new class file. There is no TTS in the pipeline (UNKNOWN beyond the files listed).

**Roles and capability flags**
- FACT: One `chat_model` serves all agents. The runtime can build separate structured and storyboard models, but all three use the same `llm_model()` (`agent_runtime/vimax_adapters.py:577-589, 633-647, 653-667`). The only differences are `max_completion_tokens` and structured vs plain mode.
- FACT: There are no per-model capability flags (vision, json, size) in the files read.

**Cost, retry, rate limit**
- FACT: There is a per-service RPM and RPD limiter built from YAML `max_requests_per_minute` / `max_requests_per_day` (`utils/rate_limiter.py:14-37`, `tools/render_backend.py:48-53`).
- FACT: The LLM client retries 3 times with backoff (1 s, 4 s), only on 429, 5xx or connection errors, with a 300 s timeout (`agent_runtime/llm.py:16-29, 71-80`). Tool-calling mode degrades to a no-tools call after repeated bad response shapes (`:53-69`).
- FACT: There is no money budget cap in the files read. Qualification gate: none found.

## 2. DramaClaw (`b299bfd`)

**Provider abstraction and selection**
- FACT: Text is a PydanticAI `OpenAIChatModel` that always goes through one OpenAI-compatible gateway (NewAPI). Direct-provider transport was removed: `get_pydantic_model` "no longer select[s] a direct-provider transport" (`config.py:90-105, 125-134`).
- FACT: `PROVIDER_PRESETS` (openai/anthropic/gemini/openrouter/volcengine, `config.py:25-56`) now only supply a default model name and timeout. `MODEL_PROVIDER` / `MODEL_NAME` / `MODEL_TIMEOUT` env vars pick them (`config.py:106-133`).
- FACT: Per-feature overrides exist for multimodal prompt builders (`get_superpower_pydantic_model`, e.g. `GLOBAL_VIDEO_PROVIDER` / `GLOBAL_VIDEO_MODEL`, `config.py:319-346`) and per task via `get_newapi_text_model_name(model_env, default)` (`config.py:147-151`).
- FACT: Gateway credentials and mode (official / custom / hybrid) live in a local SQLite `settings.db` (`model_gateway_settings.py:35-38, 129-132`). Credentials are resolved per submit (`model_gateway_runtime.py:202-244`).
- FACT: A new model id needs no code change for text (a string sent to the gateway). Gemini-named models get an OpenRouter-derived `profile` (`config.py:154-162`); other names get no profile.
- FACT: Reasoning is force-disabled for structured calls with `openai_reasoning_effort: "none"`, because opaque aliases (`DC-*`) hide thinking capability from PydanticAI (`config.py:299-308`).

**Vision / judge calls**
- FACT: Images are passed as PydanticAI `BinaryContent(data=jpeg_bytes, media_type="image/jpeg")` after `compress_image` (`verification/image_verifier.py:8, 131-136`).
- FACT: Output is a Pydantic model with `passed: bool`, `score: float` (0-10) and `issues` (`verification/models.py:15-20`), with `output_retries=2` (`image_verifier.py:55-62`; also `sketch_scorer.py:34`, `consistency_verifier.py:40`). The score is the model's own number. Grep for "logprob" across the files I downloaded: 0 hits.
- FACT: Prompt input is sanitised before use (`image_verifier.py:91-94`).
- UNKNOWN: Whether PydanticAI's output mode falls back when a provider ignores JSON/tool mode. I found no explicit fallback code in the files read.

**Media routes (the interesting part)**
- FACT: Image and video models are a **data catalog**, `official_media_models.json` (17 entries). Each entry has `mediaType`, `provider`, `upstreamModel`, `aliases`, `enabled`, `sortOrder`, and `config` (`official_media_catalog_schema.py:21-65`).
- FACT: `config` is validated per media type. It carries a declarative `request` schema (endpoint must be `images/generations` or `video/generations`, plus parameter definitions with `requestPath`), ratio/resolution/quality options, supported modes, duration range, and reference limits (`media_model_request_schema.py:380-470`, `:621-634`). Reserved or dangerous keys (`model`, `url`, `headers`, `api_key`, `base_url`) are blocked (`:15-23`).
- FACT: The catalog can be updated from a remote manifest with sha256 and version check, a 2 MB cap, and ETag (`official_media_catalog_remote.py:25-37`; settings keys in `model_gateway_settings.py:45-52`). So a new cloud image/video model ships as JSON, not code.
- FACT: Counter-evidence: legacy env-var model names are still hardcoded in `config.py` (`NEWAPI_IMAGE_MODEL` `:505`, `SEEDREAM_MODEL` `:539`, `COSYVOICE_MODEL` `:671`, video model CSV `:768-776`). Video-backend names use a `newapi_<model>` prefix convention (`generators/video_generator.py:4377, 4395-4410`), but seedance-2.0 behaviour is switched on by `model.startswith("seedance-2.0")` (`:1505, 2326`).
- FACT: TTS is **not** in the catalog dispatch. `create_tts_generator` is a hardcoded `if provider == "cosyvoice" / "edge"` switch (`generators/tts_generator.py:783-830`). (The catalog schema does allow `mediaType: audio`, `official_media_catalog_schema.py:34`.)
- INFER: Schema-validated declarative catalog is the strongest pattern in the four donors for "models unknown at build time", but it works because everything sits behind one gateway that normalises request shape.

**Roles and capability flags**
- FACT: Roles are by env var per task, not a general reviewer/writer split (`config.py:147-151, 333-342`). Capability flags live in the media catalog (modes, durations, reference counts, `supportsGenerateAudio`, `humanReview`, `media_model_request_schema.py:402-424`). Text has no flags beyond the Gemini profile hack.

**Cost, retry, rate limit**
- FACT: `provider_costs.py` classifies HTTP statuses as "definitely no cost" (400-404, 413, 415, 422, 429) vs unknown (408, 409, 5xx may already be billed) (`shared/provider_costs.py:5-32`).
- FACT: Provider error normalisation maps vendor messages and `VIDEO_*` codes to user-facing codes, and redacts signed URLs and keys (`shared/provider_errors.py:25-58`).
- FACT: For organisation requests, PydanticAI output retries are set to 0 to avoid duplicate paid submits (`model_gateway_runtime.py:93-98`); they use an idempotent submit digest instead (`:179-199, 39-70`).
- Qualification gate: UNKNOWN for models. A large `verification/` package exists, but it checks outputs, not models.

## 3. OpenMontage (`08e2151`)

**Provider abstraction**
- FACT: The host coding agent (Claude Code, Codex, Cursor, etc.) is the LLM. The repo ships per-agent instruction files (`CLAUDE.md`, `CODEX.md`, `CURSOR.md`, `COPILOT.md`, tree listing). The `llm:` block in `config.yaml:3-7` and `LLMConfig` (`lib/config_model.py:28-32`) exist. I did not find code that consumes it in the files read (UNKNOWN repo-wide).
- FACT: Everything else is a **tool plugin**. Each tool subclasses `BaseTool` and declares `capability`, `provider`, `capabilities`, `supports`, `best_for`, `not_good_for`, `dependencies` (`env:KEY`, `cmd:bin`), `retry_policy`, `fallback_tools`, `idempotency_key_fields`, `quality_score` and `historical_success_rate` (`tools/base_tool.py:237-292`, `:304-317`).
- FACT: `ToolRegistry.discover()` imports every module under `tools/` with `pkgutil.walk_packages` and registers concrete tools (`tools/tool_registry.py:118-134`). Adding a file registers a tool automatically.
- FACT: Selectors (`tts_selector`, `image_selector`, `video_selector`) route by `registry.get_by_capability(...)` and need no code change for a new provider (`AGENT_GUIDE.md:502-512`).
- FACT: Routing is "preferred_provider, then ranking by availability", with a weighted score: task_fit 0.30, quality 0.20, control 0.15, reliability 0.15, cost 0.10, latency 0.05, continuity 0.05 (`lib/scoring.py:36-45`, `tools/audio/tts_selector.py:262-288`). Reliability uses `historical_success_rate` if set, else 0.95 (production), 0.8 (other), 0.4 (degraded) (`lib/scoring.py:400-410`).

**Model id handling**
- FACT: Within a provider the model id is a request parameter (`model` input, default `gpt-4o-mini-tts`, `tools/audio/openai_tts.py:149`). Feature gating is by string prefix (`_supports_instructions`, `:126-127`).
- FACT: The OpenAI TTS tool reads only `OPENAI_API_KEY` and uses `OpenAI()` without a base_url (`openai_tts.py:118, 144`), so an OpenAI-compatible third-party endpoint is not configurable there. A new cloud vendor means a new tool file. There are ~22 audio tools and ~44 video tools in the tree listing.

**Vision / judge**
- FACT: Review is done by the host agent following markdown skills, not by a configured VLM. `skills/meta/reviewer.md` is advisory, runs after each stage, max 2 rounds, then passes with warnings (`AGENT_GUIDE.md:574-583`). Human gates are binding per manifest and enforced in `lib/checkpoint.py` (`AGENT_GUIDE.md:589-592`).
- FACT: `tools/analysis/video_understand.py` uses local CLIP / BLIP-2 (HF models) selectable by a `model` input (`:84-88, 155, 410-422`). There is no cloud VLM judge in it. `visual_qa.py` is ffprobe-based (`:214-220`).

**Budget**
- FACT: `config.yaml:9-14` sets budget `mode: observe|warn|cap`, `total_usd: 10`, `reserve_pct`, `single_action_approval_usd: 0.50` and `require_approval_for_new_paid_tool`. `tools/cost_tracker.py:101-150` enforces them: approval required above the single-action threshold or on first use of a paid tool (unless `observe`), and `cap` raises `BudgetExceededError`. Tools report `estimate_cost` (`openai_tts.py:122-123`).
- Qualification gate: none for models. `stability` (experimental/beta/production) feeds scoring (`lib/scoring.py:406`).

## 4. Jellyfish (`a967819`)

**Provider abstraction and selection**
- FACT: Providers and models are **DB rows**: `Provider` (name, `base_url`, optional `image_base_url` and `video_base_url`, `api_key`, `api_secret`, status active/testing/disabled), `Model` (name, category text/image/video, `provider_id`, JSON `params`), and a singleton `ModelSettings` with default text, image and video model ids (`models/llm.py:54-162`). UI/API CRUD: `api/v1/routes/llm.py` (path seen in listing; contents not read).
- FACT: Text runtime builds `ChatOpenAI(**model.params, model=model.name, api_key, base_url)` (`services/llm/runtime.py:46-76`). `base_url` resolves category override, then common, then built-in default (`provider_resolver.py:88-106`). So any OpenAI-compatible endpoint with any model id works with zero code change, and arbitrary kwargs go through `params` (`runtime.py:62-69`). Thinking is disabled via `extra_body.enable_thinking=False` (`:71-74`).
- FACT: The provider **key** is a registry. Built-ins are `openai` (text/image/video), `volcengine` (image/video) and `aliyun_bailian` (text) (`provider_bootstrap.py:7-36`). `resolve_provider_key_from_name(provider.name)` raises 503 for unknown names (`provider_registry.py:89-101`), and `ProviderKey` is a closed `Literal["openai","volcengine"]` for media (`core/contracts/provider.py:8`). So the async media path needs the provider name to match a registered alias, even though the sync text path does not check it (`runtime.py` imports only `resolve_effective_base_url`).
- INFER: Rule of thumb: text accepts any OpenAI-compatible endpoint, while media accepts only providers with a code adapter (OpenAI-style, Volcengine).

**Vision / judge**
- FACT: Agents use LangChain structured output: `STRUCTURED_OUTPUT_METHOD = "function_calling"` (`chains/agents/base.py:16`). Fallback on any exception: take raw text, extract JSON from fences or the first `{}`, repair unquoted keys and Python-style literals, then validate with Pydantic (`base.py:21-130, 313-345`). A broad `except Exception: pass` hides the first failure.
- FACT: No `image_url` or VLM judge in `backend/app/chains` by GitHub code search (may be incomplete). Image reference handling is in generation payloads only (`core/integrations/openai/images.py`).

**Media routes**
- FACT: Image: `httpx` POST to `{base_url}/images/generations` or `/images/edits` (`core/integrations/openai/images.py:39-99`). Capability is a per-provider registry matched by lowercased **model-name prefix**, `register_*_capability(model_prefix=..., capability=...)` (`image_capabilities.py:22-50`, `openai/video_capabilities.py:12-25`). Fields: seed, watermark, allowed sizes, ratios, n range (`image_capabilities.py:23-33`), validated before submit (`:117-136`).
- FACT: Video: submit then poll, `poll_interval_s=2.0`, `timeout_s=120` (`core/tasks/video_generation_tasks.py:37-43, 97-98`).
- FACT: New image/video model on a known provider = add a `Model` row (and optionally a capability override); unknown defaults apply otherwise. New vendor = new integration package. TTS: none seen in the files read.

**Cost, retry, qualification**
- FACT: `api_timeout` is a global setting (default 30 s) (`models/llm.py:156`). I found no retry/backoff or budget code in `services/llm/*` or the task files (grep for retry returned only poll/timeout params). Qualification gate: none.

## 5. Comparison

| Aspect | ViMax | DramaClaw | OpenMontage | Jellyfish |
|---|---|---|---|---|
| Text protocol | OpenAI-compat (LangChain) | OpenAI-compat via one gateway | Host agent | OpenAI-compat (LangChain `ChatOpenAI`) |
| Model chosen by | YAML/env | env + local settings DB | none (agent) | DB rows + default row |
| Unknown model id, no code | yes | yes | n/a (per-tool param) | yes (text) |
| Image/video registry | YAML `class_path` | validated JSON catalog | auto-discovered tool classes | DB rows + prefix capability map |
| TTS registry | none | hardcoded switch | auto-discovered tools | none seen |
| VLM judge | index pick + reason | 0-10 score + bool | host agent / CLIP | none found |
| Logprobs | no | no | no | no |
| Budget cap | no | no-cost HTTP classifier | yes (cap/warn/observe) | no |
| Model qualification | no | no | stability tag only | no |

## 6. What ArcReel should copy (INFER, not donor fact)

Premise (from the task, not re-verified here): ArcReel has `lib/text_backends` (openai/gemini/ollama, images and `response_schema`), UI-added custom providers with endpoints `openai-chat` / `gemini-generate` / `ollama-chat`, and an automatic run whose writer/reviewer/judge are hardcoded to Gemini allowlists or Ollama `/api/chat`.

1. **Role slots resolved from data, not code.** Copy Jellyfish's "default model per category" idea, extended to roles: `writer`, `reviewer`, `judge` each map to `(provider_id, model_id)` stored in config/DB. DramaClaw's per-task `*_MODEL` env override is the same idea in a weaker form. Replace the Gemini name allowlists with a lookup of that slot. No donor has a writer/reviewer/judge split, so this part is original design.
2. **Capability flags per model row, not name matching.** Jellyfish and DramaClaw both keep per-model flags (prefix map vs catalog `config`). Prefix matching on names is brittle for unknown cloud ids. Prefer explicit per-row flags set by the user or by a probe: `vision`, `json_schema`, `max_images`, `max_image_bytes`, `video_input`. The default for an unknown model should be "unproven", not "supported".
3. **Qualification gate before trust.** No donor does this (all four: none found), so it is the gap to fill. ArcReel already has a judge-qualification probe in the scratchpad (`judge_prob_probe.py`, `judge-qual.log`; contents not read here). Gate a model for the `judge` slot only after it passes a small fixed fixture set: valid JSON, a stable ordering of known good/bad images, and the repeat-run agreement you need.
4. **Judge output shape.** All donors use schema-validated JSON with an index or score, none use logprobs. Copy: Pydantic/JSON-schema output with `passed` and bounded `score`, validated range, bounded retries (DramaClaw `output_retries=2`, ViMax 3 attempts). Improve on ViMax's silent "index out of range becomes 0" (`best_image_selector.py:141-144`) by treating it as a failure.
5. **JSON fallback ladder per `ollama-chat` / `openai-chat` / `gemini-generate` endpoint.** Combine ViMax (json_schema strict first, then prompt+parser, `storyboard_artist.py:369-372`), Jellyfish (extract/repair JSON text then validate, `base.py:21-130`) and ViMax's trailing-comma strip. Record which rung succeeded per model, so the qualification gate can read it. Avoid Jellyfish's silent `except: pass`; log the first failure.
6. **Media models as validated data.** DramaClaw's catalog schema is the best fit for "cloud models unknown at build time": mediaType, upstream id, aliases, declarative request-parameter mapping with blocked roots, option lists and limits, validated at install time. ArcReel's custom-provider UI could take a JSON entry of this shape. Constraint: it only works where the endpoint shape is normalised (DramaClaw has a gateway); for raw vendor APIs ArcReel still needs an adapter class (ViMax `class_path` or OpenMontage auto-discovery for that part).
7. **TTS.** Only OpenMontage makes TTS pluggable (registry plus selector plus scoring). DramaClaw hardcodes it. For ArcReel, treat TTS as a media route in the same catalog as image/video.
8. **Cost and retry.** Copy OpenMontage's budget modes (`observe|warn|cap`, single-action approval, first-paid-tool approval; `cost_tracker.py:101-150`) and DramaClaw's rule that 408/409/5xx may already be billed, so submits are not blindly retried (`provider_costs.py:5-32`, `model_gateway_runtime.py:93-98`). ViMax's retry-only-429/5xx/connection-error with 1 s and 4 s backoff (`llm.py:21-29, 71-80`) is a fine default for text and judge calls. Add per-provider RPM/RPD limits like ViMax (`rate_limiter.py:14-37`).
9. **Do not copy:** OpenMontage's host-agent-as-LLM design (ArcReel runs unattended); Jellyfish's closed `ProviderKey` Literal for media (it blocks custom providers); DramaClaw's collapse to a single gateway (that is a product decision, not a flexibility pattern, and not available for Ollama-local roles).
