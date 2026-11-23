# Assembly plan — from donors to a running, fully automatic product

Status: **approved for implementation** under [GOAL](../GOAL.md) and [ADR-0170](../adr/0170-assemble-the-donors-best-stages-whole.md),
2026-11-23. Research trail: [redirection index](evidence/R2_REDIRECTION_2026-11-23.md). Every technical choice below is
decided; an implementer needs no further question except the sponsor prerequisites in §3 (accounts and keys, not
decisions). Facts cite the donor checkouts: DramaClaw `b299bfd` (`~/.cache/r2-donors/dramaclaw-full`), huohuo-drama
`f104b85` (`~/content-os-r1-8/work/huohuo-drama`), OpenMontage `08e2151` (`~/content-os-r1-8/work/OpenMontage`).

## 1. Architecture

```
 premise ──► huohuo (docker, :18088)  ──chapters zh──► translate (ours) ──story vi──┐
 story file ──────────────────────────────────────────────────────────────────────┤
                                                                                     ▼
                      connector (assembly/, ours) ──REST──► DramaClaw (docker: api :8780, web :8080,
                                                                        NewAPI gateway 127.0.0.1:3000)
                                                                        │ models via NewAPI channels:
                                                                        │ OpenRouter, Gemini, BytePlus
                                                                        │ voice: INDEXTTS2_PROVIDER=fal ─► voice adapter (ours, :23350)
                                                                        │                                   ─► VieNeu shim (:23340, running)
                                                                        ▼
                                                    final episode MP4 ─► post-stages (M4: finish, review) ─► film
```

- **Donors run whole, from their own containers**: DramaClaw `docker-compose.release.yml` (images
  `claymorelab/dramaclaw:2.0.2`, `dramaclaw-frontend:2.0.2`, `dramaclaw-gateway:v1.0.0-rc.24-dramaclaw.1`; 2.0.2 is the
  version of `b299bfd`'s `pyproject.toml`); huohuo `deploy/docker-compose.yml` (port `18088`). If a pinned image is
  unavailable, build from the pinned checkout with the donor's own `docker-compose.yml` (DramaClaw also needs
  `dramaclaw-gateway` cloned beside it, per its quickstart).
- **Our code lives in `assembly/`** (new top-level Python package in this repository, same `uv` environment), with
  tests under `tests/unit/assembly/` and `tests/integration/assembly/`. It imports nothing from `server/` or `r2/`; from
  `lib/` only `lib.story_translation` (translation) and, in M4, the finishing and review modules named there.
- **Runtime data** outside the repo: `~/assembly-data/` (run state files, downloaded films, voice samples, local
  secrets with mode 600).
- **ArcReel stays frozen** and in production; nothing in this plan changes it except item M2.4 (one public function).

## 2. Decisions (locked)

| # | Decision | Evidence |
|---|---|---|
| D1 | Story = huohuo novel engine whole, Chinese output | ADR-0170; only full long-form engine (2026-11-08 study §2) |
| D2 | Translation zh→vi = `lib/story_translation.py` (made public as `translate_text`) | in production since ADR-0120; protected names, length bands, 3 retries |
| D3 | Film = DramaClaw whole; driven through **its own agent toolset** (`.hermes/plugins/dramaclaw/__init__.py`, the same handlers its MCP server `novelvideo.chat.dramaclaw_mcp` exposes), loaded with the bridge's `tools.registry` shim; step order from `GET /api/v1/projects/{p}/pipeline/status` → `next_step` | donor docs `docs/en/guides/mcp-claude-code.md`; `api/routes/pipeline.py` `_STEP_MAP` |
| D4 | DramaClaw gateway mode = **Custom** with our profile JSON (`assembly/config/dramaclaw-profile.json`, no keys in it) | `docs/en/getting-started/configuring-models.md` "My Config" |
| D5 | Text models: all `DC-*-LLM` → OpenRouter `baidu/ernie-5.5-flash-preview:free`; Hermes/agent the same | free registry: best free writer, Vietnamese and Chinese |
| D6 | Vision features → Gemini `gemini-3.5-flash`, fallback OpenRouter `nvidia/nemotron-3.5-super-vl:free` (NewAPI channel priority) | registry; Gemini 20/day/model |
| D7 | Images → BytePlus `seedream-4-5-251128` (200 free) mapped to DramaClaw's image IDs (`LingShan-G2`, `LingShan-NB-2`, `newapi_gpt_image2` selections); fallback Gemini image when the pool ends | registry; `.env.example` 225–245 |
| D8 | Video → BytePlus `seedance-1-0-pro-fast-251015` behind DramaClaw's own default `seedance-1.0-pro-fast` | `.env.example` 276–277 |
| D9 | Voices: `INDEXTTS2_PROVIDER=fal`, `INDEXTTS2_FAL_ENDPOINT=http://host.docker.internal:23350/fal-ai/index-tts-2/text-to-speech`, `FAL_API_KEY=local`; our **voice adapter** answers DramaClaw's fal request (`{audio_url, prompt, emotion_prompt}` → `{"audio": {"url": …}}`, `generators/indextts2_fal.py:315-360`) with VieNeu speech. VieNeu has preset voices only, so the connector **casts** one preset per character and uploads a sample of it as the character's voice sample; the adapter maps a sample (by SHA-256 of the downloaded `audio_url`) back to its preset | `generators/indextts2_fal.py`; VieNeu shim `~/arcreel-v2-staging/vieneu-tts-shim/server.py` (`/v1/audio/speech`, presets) |
| D10 | Narrator voice: a VieNeu preset sample uploaded through `POST /api/v1/projects/{p}/narrator-voice/upload`; characters through `POST …/characters/{name}/voice-samples/{slot}/upload` | `api/routes/projects.py:786`, `characters.py:1355` |
| D11 | Media relay for reference images/audio = **Cloudinary** (free account) | donor docs "Reference media storage" |
| D12 | huohuo text → the same NewAPI gateway (`HUOHUO_PRESET_TEXT_BASE_URL=http://host.docker.internal:3000/v1`, model `baidu/ernie-5.5-flash-preview:free`, also `HUOHUO_PRESET_AGENT_MODEL`), one key store and one usage ledger | `services/ai/ai-config-service.ts:45-75` |
| D13 | New DramaClaw projects are `structured_v1` (no embedding model needed) | `api/routes/projects.py:630-641` |
| D14 | Configure step: `ethnicity = "Vietnamese"`, `narration_style` = the value DramaClaw's settings UI offers for a narrator voice (read the allowed values from `project_config.py` at implementation time; default the first non-empty) | `api/routes/pipeline.py` `_user_has_configured` |
| D15 | Retries: each DramaClaw step and each huohuo call up to 3 attempts with 30/120/300 s waits; a step that still fails stops the run with its error recorded in the run state and `docs/r2/evidence/R2_RUN_BLOCK_LEDGER.md` | GOAL rule 3 |

## 3. Sponsor prerequisites (actions, not decisions)

1. **Cloudinary**: create a free account; paste cloud name, API key, API secret in DramaClaw UI → Settings → Media
   Storage (after M0).
2. **Keys**: paste the OpenRouter, Gemini (AI Studio) and BytePlus keys once in DramaClaw UI → Settings → Models &
   Channels → Custom → My Config, after loading `assembly/config/dramaclaw-profile.json` (M1). Keys never enter the repo.
The agent sets the NewAPI root password itself and stores it in `~/assembly-data/secrets/newapi-root` (mode 600).

## 4. Milestones

Estimates are working days of agent time. Our code budget is per milestone (lines of Python, tests excluded).

### M0 — DramaClaw up (0.5 day, 0 code)
1. `assembly/deploy/dramaclaw/.env` (template in repo as `.env.example`): `PROMPT_EXPORT_PASSWORD` random,
   `INDEXTTS2_PROVIDER=fal`, `INDEXTTS2_FAL_ENDPOINT`, `FAL_API_KEY=local`, ports 8780/8080/3000 as donor defaults,
   `extra_hosts: host.docker.internal:host-gateway` via a compose override file `assembly/deploy/dramaclaw/override.yml`.
2. `docker compose -f <checkout>/docker-compose.release.yml -f override.yml --env-file .env up -d`.
3. Initialize Local NewAPI through the UI flow's API (or the UI), password as in §3.
**Done when** `docker compose ps` shows api, newapi, web running; `GET http://localhost:8780/api/v1/projects` answers;
the UI opens on `:8080`.

### M1 — Models and voices (1.5 days, ≤ 400 lines)
1. `assembly/config/dramaclaw-profile.json`: channels `openrouter`, `gemini`, `volcengine` (BytePlus base URL
   `https://ark.ap-southeast.bytepluses.com/api/v3` as Base URL Override); `featureModels` per D5/D6; `mediaModels`
   per D7/D8 keeping DramaClaw's model IDs and setting the upstream model. No embedding entry (D13).
2. `docs/r2/ASSEMBLY_MODELS.md`: the table slot → upstream model → pool → fallback, from this plan and the free
   registry.
3. `assembly/voice_adapter/app.py` (FastAPI, `127.0.0.1:23350` and the docker bridge address): `POST
   /fal-ai/index-tts-2/text-to-speech` (D9), `GET /audio/{id}.wav`; sample registry `~/assembly-data/voices.json`
   (`sha256 → preset`); unknown sample → narrator preset with a logged warning. Calls the VieNeu shim
   `POST http://127.0.0.1:23340/v1/audio/speech {model, input, voice, response_format:"wav"}`.
   systemd user unit `assembly/deploy/voice-adapter.service`.
4. `assembly/connector/voices.py`: preset list from the shim's `/health` (`voices`); cast rule = gender from the
   character record, then age group, northern accent by default, distinct presets for distinct characters while
   presets remain; sample text: one fixed Vietnamese sentence; uploads per D10; registers hashes.
**Done when** (acceptance) a DramaClaw TTS preview (`POST /api/v1/projects/{p}/tts/preview`) of a Vietnamese line with
a cast character returns Vietnamese speech in that character's preset; unit tests for the adapter (request shape,
registry, unknown sample) pass.

### M2 — Film from a story file, fully automatic (2 days, ≤ 600 lines)
1. Vendor DramaClaw's toolset whole: `vendor/dramaclaw/hermes_plugin/__init__.py` (verbatim from
   `.hermes/plugins/dramaclaw/__init__.py`) and the `tools.registry` shim from `chat/dramaclaw_mcp.py`; record in
   `vendor/dramaclaw/PORTING.md`. Environment: `DRAMACLAW_API_URL=http://localhost:8780`, `DRAMACLAW_CE_OWNER=1`.
2. `assembly/connector/dramaclaw.py`: create project (`POST /api/v1/projects {name}`), upload and start ingest, configure
   (D14), cast voices (M1.4), then loop: `pipeline/status` → `next_step` → the plugin handler for that step (table in
   §5) → wait for the task (`get_task` / `list_tasks`) → repeat until `done`; then `get_final_video` and download to
   `~/assembly-data/films/<run>/ep<NNN>.mp4`. Per-episode steps run for every episode returned by `episodes`.
3. `assembly/run.py` CLI: `uv run python -m assembly.run film --story <file> --title <t> [--episodes 1]`;
   `--resume <run-id>` continues from the run state file `~/assembly-data/runs/<id>.json` (current step, project id,
   episode, attempts, errors).
4. `lib/story_translation.py`: rename `_translate_text` to public `translate_text` and keep the old name as an alias
   (the only ArcReel change).
5. Tests: the step loop against a fake DramaClaw (httpx `MockTransport`): order follows `next_step`, retries per D15,
   resume from state, voice-prerequisite error surfaces.
**Done when** (acceptance, by validation not by tests): `assembly.run film --story chiec-dong-ho-cua-ong.txt --episodes
1` (the story of the drama-smoke project, copied to `~/assembly-data/stories/`) produces `ep001.mp4` with **no human
step**; the agent and the sponsor watch it: Vietnamese voices for both characters, both characters consistent across
shots, picture and speech in sync. The result is recorded in `docs/r2/evidence/ASSEMBLY_ACCEPTANCE.md` with the film
path, run time, model calls, and the verdict.

### M3 — Story stage (1.5 days, ≤ 400 lines)
1. huohuo up: `assembly/deploy/huohuo/.env` from its `deploy/docker-compose.yml` (sqlite, `BOOTSTRAP_ADMIN_*`,
   `CONFIG_ENCRYPTION_KEY` random, D12 presets); `docker compose up -d`.
2. `assembly/connector/huohuo.py`: login `POST /api/v1/auth/login` (JWT); create `POST /api/v1/dramas
   {title, project_type:"novel", novel_genre, premise?, total_chapters}` (`services/drama/drama-catalog-service.ts:120-160`);
   `POST /api/v1/novel/generate-premise {keywords, genre, title, total_chapters}`; `POST
   /api/v1/novel/dramas/{id}/outline {premise}`; `POST …/memory/init`; `POST …/generate-remaining/stream {mode:"all"}`
   (read the server-sent events to the end); fetch the chapters' text.
3. `assembly/connector/translate.py`: `translate_text(text, target="vi", terms=<character names>, generate=<NewAPI chat
   call with JSON schema, model D5>)`.
4. CLI: `assembly.run story-film --premise "<idea>" --genre <g> --chapters <n>` = M3 → M2.
**Done when** a premise produces a translated Vietnamese story that the sponsor reads as natural, and M2 turns its
first episode into a film with no human step.

### M4 — Parity post-stages (2 days, ≤ 500 lines)
1. **Finish** the downloaded MP4 with the old app's units, called as plain functions on the file: loudness to −14 LUFS
   (ADR-0133), music bed (ADR-0143) and ambience (ADR-0150) when their local services answer, burned captions/title
   card only if DramaClaw's film has none (check `add_subtitles` result first).
2. **Review** the finished film with the two configured reviewers and the AIVPE guards (ADR-0169); REWORK → the
   connector asks DramaClaw to regenerate the named beats (`/beats/regenerate`) once, then records the verdict.
**Done when** a film passes through finish and review automatically and the verdicts are in the acceptance record.

### M5 — Coverage (rolling, after M4)
Genre skills from shenbi (comedy, fanfic/spinoff) and ViMax (children's) as huohuo genre skill folders (recorded donor
seam); the old app's action, family, bedtime, storytime packs; audiobook from the story; OpenMontage forms
(coverage matrix, 2026-11-23). Each item is its own task with a film/story acceptance.

## 5. DramaClaw step → toolset handler

| `next_step` | Handler (vendored plugin) | Endpoint |
|---|---|---|
| ingest | `dramaclaw_post` ×2 | `/projects/{p}/ingest/upload`, `/ingest/start` |
| configure | `dramaclaw_patch` | `/projects/{p}` (D14) |
| characters | `_handle_build_characters` | `/projects/{p}/characters/build` |
| episodes | `_handle_plan_episodes` | `/projects/{p}/episodes/plan` |
| portraits | `_handle_generate_portrait` per main character | `/characters/{name}/portrait-async` |
| identity_plan | `_handle_plan_identities`, then `_handle_plan_scenes`, `_handle_plan_props`, `_handle_generate_scene_master` per scene | `/episodes/{e}/identities/plan-async`, `/scenes/plan`, `/props/plan` |
| identity_images | `_handle_generate_identity_image` per identity | `/characters/{name}/identities/{id}/generate-async` |
| script | `_handle_generate_script` | episode script |
| sketches | `_handle_generate_sketches` | sketches |
| coloring | `_handle_detect_sketch_identities` | sketch identity detection |
| global_optimize | `_handle_optimize_video_global` | `/episodes/{e}/optimize/video-global` |
| first_frames | `_handle_render_first_frames` | render first frames |
| tts | `_handle_generate_audio` | `/episodes/{e}/audio/generate` |
| video | `_handle_start_single_video` per beat | `/episodes/{e}/beats/{b}/video` |
| compose | `_handle_compose_episode` | `/episodes/{e}/videos/compose` |
| done | `_handle_get_final_video` | `/episodes/{e}/final` |

Where the plugin's tool descriptions give a different order or extra arguments, the plugin wins (it is the donor's own
automation contract); the table is updated in the same commit.

## 6. Decided fallbacks (no question needed)

| Event | Action |
|---|---|
| BytePlus image pool exhausted | switch D7 mapping to Gemini image; record in ASSEMBLY_MODELS.md |
| BytePlus video pool exhausted | DramaClaw's still/Ken Burns path if its video step allows it; otherwise stop and report (tolerance: paid spend) |
| Gemini vision 429 | NewAPI falls to the OpenRouter vision channel (D6) |
| OpenRouter ernie fails or 429 | next free writer in the registry order (particle-1, ling-3.2-flash) |
| A DramaClaw step needs a donor code change | stop, record the seam need, report (GOAL tolerance) |
| Translation batch fails 3× | retry the batch with the next registry writer once, then stop |
| Pinned image tag missing | build from the pinned checkout (M0) |

## 7. How this plan keeps the direction

- Each task's commit carries `Donor:` (which donor part it connects or configures) and, for a fix, `Consumers:` (hook).
- A milestone is accepted only by its film/story result recorded in `ASSEMBLY_ACCEPTANCE.md`; tests are necessary, not
  sufficient.
- Code budgets per milestone; going over by 50 % or a donor code change is a GOAL tolerance breach → sponsor.
- No new ADR unless a decision in §2 changes; such a change cites GOAL and is approved by the sponsor first.
- Each run block → one line in the run ledger with its class; a repeat gets its root cause and the class fix.
