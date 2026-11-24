# Assembly acceptance record

One section per milestone of the [assembly plan](../ASSEMBLY_PLAN.md): what was checked, the evidence, the verdict.

## M0 — DramaClaw up — ACCEPTED 2026-11-23

- Stack: `assembly/deploy/dramaclaw/up.sh` (DramaClaw `b299bfd` own `docker-compose.release.yml` + our override),
  project `assembly-dramaclaw`; images `claymorelab/dramaclaw:2.0.2` (4.64 GB), `dramaclaw-frontend:2.0.2`,
  `dramaclaw-gateway:v1.0.0-rc.24-dramaclaw.1`.
- `docker compose ps`: api (healthy) `127.0.0.1:8780`, newapi (healthy) `127.0.0.1:3000`, web `127.0.0.1:8080` —
  loopback only.
- `GET /api/v1/projects` → 200; web `/` → 200; NewAPI `/api/status` answers.
- `POST /api/v1/model-gateway/custom/newapi/init` → `ok`, mode `custom`, relay token `dramaclaw-ce-runtime` created;
  root password in `~/assembly-data/secrets/newapi-root` (600).
- Merged compose config shows `INDEXTTS2_PROVIDER=fal`, `INDEXTTS2_FAL_ENDPOINT=http://host.docker.internal:23350/…`,
  `host.docker.internal=host-gateway` on the api service.
- Disk after pull: 16 GB free on `/`.

## M1a — Vietnamese voice path — transport verified 2026-11-23

- Service: `assembly/deploy/voice-adapter.service` (user unit `voice-adapter`, active), listening on `172.17.0.1:23350`
  (docker0; DramaClaw's container resolves `host.docker.internal` to `172.17.0.1`).
- Probe: a 3.68 s WAV sample made by the VieNeu shim with preset "Ngọc Huyền" registered by SHA-256; from **inside**
  `assembly-dramaclaw-api-1`, the fal request `{"audio_url": "data:audio/wav;base64,…", "prompt": "Bác ơi, bác còn sửa
  đồng hồ cơ không ạ?"}` to `http://host.docker.internal:23350/fal-ai/index-tts-2/text-to-speech` returned
  `{"audio": {"url": "http://host.docker.internal:23350/audio/<id>.mp3"}}`; the container downloaded it: MP3, 2.48 s.
- Unit tests: `tests/unit/assembly/` 9 passed; ruff, basedpyright, deptry, test audit clean.
- Not yet verified: DramaClaw's own TTS task using a character voice sample uploaded through its API (M2).

## M1.0 — model probes through NewAPI — 2026-11-23

Keys pasted by the sponsor in DramaClaw "My Config" with `assembly/config/dramaclaw-profile.json`; DramaClaw created NewAPI
channels 1 `DC-openrouter` (type 20), 2 `DC-gemini` (24), 3 `DC-volcengine` (45, base `https://ark.ap-southeast.bytepluses.com`).
Calls with DramaClaw's own relay token on `127.0.0.1:3000`:

| Slot | Result |
|---|---|
| Text `DC-*-LLM` → OpenRouter `baidu/ernie-5.5-flash-preview:free` | first call 429 (upstream shared pool `tpm_rate_limit_exceeded`); retry 200, natural Vietnamese sentence |
| Vision → Gemini `gemini-3.5-flash` | 503 "high demand" twice, then channel test success in 38 s; `gemini-3.5-flash-lite` 1.0 s and `gemini-2.5-flash` 1.6 s succeed (fallback candidates); `gemini-2.5-flash-lite` 404 for new users |
| Embedding → Gemini `gemini-embedding-001` (768) | success 0.45 s |
| Image `LingShan-G2` → Seedream 4.5 via **VolcEngine type** channel, `/v1/images/generations` | 200, 1440×2560 (`m1-probes/seedream-text2img.jpg`); default output carries an "AI generated" mark; the Vietnamese prompt "đồng hồ quả quýt" was drawn literally as a tangerine clock |
| Image with **base64 reference** (`image: ["data:image/jpeg;base64,…"]`), `watermark: false` | 200, reference kept, no mark (`m1-probes/seedream-ref-base64.jpg`) |
| DramaClaw's own reference path `/v1/images/edits` JSON, `width`/`height`, base64 reference | 200, 1440×2560 |

Decisions from the probes:
- Image route = the VolcEngine-type channel (plan D7's OpenAI-type route is not needed; the `byteplus_openai` channel holds
  the key in DramaClaw but has no NewAPI channel).
- `watermark: false` set as a request-schema default on `LingShan-G2`, `LingShan-NB-2`, `seedance-1.0-pro-fast`; verified
  with DramaClaw's own `apply_media_request_schema` and in its saved mappings.
- D28: Seedream accepts base64 references, so the inline relay is viable for images; the ComfyUI first-frame half is still
  to probe with the Wan channel.

## M1a — local Wan video through DramaClaw's ComfyUI channel — 2026-11-23

- Route: DramaClaw CE calls ComfyUI through the gateway's ComfyUI task channel (dramaclaw-gateway@ed1e234
  `relay/channel/task/comfyui`), not its direct `ComfyUIVideoGenerator` (that path accepts only a loopback ComfyUI
  address for local principals, and its GGUF workflow is Wan2.2 I2V **A14B** Q3_K_S — ~23 GB of models not on this host,
  too heavy for 8 GB VRAM).
- Workflow `assembly/config/comfyui/wan22-5b-i2v.json`: the Wan2.2 TI2V 5B Q4 GGUF graph proven on 2026-10-30
  (`media-local-2026-10-30/wan-2.2`), with a `PrimitiveFloat` titled `duration` feeding `ComfyMathExpression`
  `min(121, max(25, round(a*6)*4+1))` into `Wan22ImageToVideoLatent.length`, so the gateway's own inference binds prompt
  (node 6 `text`), first frame (`LoadImage` 56), width/height (55), duration (60) and seed (3).
- The gateway cannot infer a mode for non-MiniMax workflows ("generation mode cannot be inferred from workflow"); the
  route declares `match: {modes: [image_to_video], min_duration: 2, max_duration: 5, reference_images: {max: 1}}`.
- Network: `assembly/deploy/comfyui-bridge.service` (socat `172.17.0.1:8189` → `127.0.0.1:8188`); both DramaClaw
  containers read `/system_stats` through it. ComfyUI itself was not restarted.
- Direct ComfyUI run (duration 2): 49 frames 480×848, 212 s, peak GPU 6 773 MiB, success.
- Through NewAPI `/v1/video/generations` as DramaClaw sends it (`model: Wan22-5B-local`, `image: data:image/jpeg;base64,…`,
  `duration: 2`, `width: 480`, `height: 854`, `metadata.ratio: 9:16`): task succeeded in 160 s, MP4 H.264 480×848,
  49 frames (`m1-probes/wan-newapi-contact.jpg`). `result_url` is `http://localhost:3000/…`; DramaClaw rewrites
  loopback result URLs to its gateway (`video_generator.py` `_resolve_result_url`).
- D28: the gateway accepts a base64 first frame (`decodeDataURL`), so with Seedream's base64 references both halves of
  the inline-relay probe pass.
- Cost per clip: ~3 min for 2 s; 5 s (121 frames) not yet timed.

## M2 — film 1 produced (narrated, "Chiếc đồng hồ của ông") — 2026-11-24, not yet accepted

- File: `~/assembly-data/runs/films/01M84JWC2DRNK6SAX24RX3VMG4-ep01.mp4` — 53.3 s, H.264 720×1280 24 fps, AAC, 12.8 MB.
  Contact sheet (one frame every 8 s): `m1-probes/film1-contact.jpg`.
- Pipeline: DramaClaw v2.1.3 driven end to end by the connector; 18 beats; Vietnamese narration (DramaClaw zh rewrite →
  translation) and VieNeu voices per speaker; beats 1–14 video on Seedance (accident, see ledger), 15–18 on local Wan.
- Visible defects on the contact sheet (to confirm by the sponsor's viewing): letterboxed frames (black bars inside
  9:16), plain white studio backgrounds on several beats, garbled sign text ("MANLEQ"), at least one split frame showing
  two images side by side. Audio, subtitles and sync not yet reviewed.
- Acceptance: pending the sponsor's viewing (GOAL: both reviewers accept or the sponsor accepts by eye).

## Xia Director (DramaClaw chat agent, Codex backend) — enabled 2026-11-24

- Codex is bundled in the 2.1.3 image (`/usr/local/bin/codex-dramaclaw`, `DRAMACLAW_CHAT_BACKEND=codex`). In CE Custom
  mode it calls `DC-codex-agent-LLM` through NewAPI with the Responses API; the Custom feature list maps only the retired
  `DC-hermes-LLM`, so `assembly/ops/newapi_agent_channel.py` keeps a server-side clone of the OpenRouter channel
  (`assembly-agent`, ch 9) serving `DC-codex-agent-LLM` with ERNIE + the OpenRouter fallback chain; zero internal price.
- Probe (film 1 project, chat in the UI): turn 1 "kiểm tra tiến độ tập 1…" → the model reasoned (180 tokens) and ended
  with no tool call or text ("已执行，但没有返回正文"); turn 2 → it called the pipeline-status tool and answered in correct
  Vietnamese (episode complete, steps listed). Each turn sends ~14.5–16.4 k prompt tokens.
- The Codex log's "bubblewrap needs access to create user namespaces" does not block the agent: DramaClaw forces a
  read-only sandbox per thread and pre-approves only its own MCP tools (`chat/backend_sdk.py`), and the MCP server
  started with its tools. The Codex sandbox was therefore left as it is (no security setting changed).
- Assessment: works on the free model but unreliably (1 of 2 turns empty); each turn costs ~15 k tokens of the shared
  free text pool. `director-auto` (whole-episode runs) not yet tried.

## OpenMontage drivers — same task, both drivers (2026-11-24)

Task: `localization-dub` on film 1 (Vietnamese, 53 s) → English SRT only; stop at the first human checkpoint.
Working copy `~/assembly-data/openmontage` @ `4f682c8`; logs `~/assembly-data/openmontage-runs/20261124-110811-codex.log`,
`…-111031-claude.log`.

| | Codex + free NewAPI (`DC-codex-agent-LLM` → ERNIE chain) | Claude Code headless |
|---|---|---|
| Time | 121 s, 41 shell commands | 78 s, 12 turns |
| Tokens / cost | 1.46 M input (1.32 M cached), 10 k output; $0 | 624 k input (cache), 7 k output; $0.70 equivalent on the subscription |
| Followed AGENT_GUIDE, wrote brief + decision log + checkpoint | yes (also installed missing `pillow` in the venv) | yes |
| Checkpoint summary in Vietnamese | yes: scope, languages, tools, duration risk, budget | yes, fuller: SRT standard (42 chars × 2 lines, 17 cps), optional vi SRT / burned-in variant with a recommendation, glossary plan, reviewers, risks |
| Project | `projects/vie-ep01-english-subs` | `projects/vie-ep01-english-subs-claude` |

Both are usable up to the first checkpoint; Claude's plan is more complete. Next stages (transcribe, translate, SRT)
not yet run.
