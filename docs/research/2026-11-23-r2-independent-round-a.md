# Independent round A — what needs to be done (2026-11-23)

Reviewer: independent read-only agent (brief A + common context of `docs/r2/evidence/assembly-research-briefs.md`).

## Method

1. Read GOAL, ADR-0170, ASSEMBLY_PLAN, ASSEMBLY_ACCEPTANCE, the verification round, the coverage matrix and the
   old-app-vs-assembly notes.
2. Build a work breakdown from GOAL alone, then diff it against ASSEMBLY_PLAN.
3. Verify plan claims against pinned donor code (DramaClaw b299bfd, huohuo f104b85).
4. Inspect this repo's `frontend/src` for the UI question.
5. Every claim is labelled FACT (file:line) or INFER. Sections are appended as they are written.

## 1. DramaClaw step loop vs plan §5 (D3)

Source: `~/.cache/r2-donors/dramaclaw-full` @ `b299bfd` (confirmed by `git log -1`).

- **F1.1 `next_step` does not return the step keys the plan's §5 table is keyed on.** FACT
  `src/novelvideo/api/routes/pipeline.py:18-35,144,234`: the response is `"next_step": task_type or next_step`, so for
  steps that have a task type the value is `ingest_fast`, `build_characters`, `build_episodes`, `script_writer`,
  `sketch_generation`, `global_optimize_video`, `selected_regen`, `single_video`, `compose_episode`; only `configure`,
  `portraits`, `identity_plan`, `identity_images`, `coloring`, `tts`, `done` come back as plain names. The plan's §5
  column `next_step` lists `ingest`, `characters`, `episodes`, `script`, `sketches`, `first_frames`, `video`,
  `compose`. A dispatcher built from §5 would hit "unknown step" on the first call (ingest). The human-readable
  `next_step_name` is Chinese. Fix: key the dispatcher on the returned values (or on `episode_status` booleans), add
  a unit fixture captured from the real `/pipeline/status`. Severity: high (cheap to fix, but the plan's "every choice
  decided" claim is wrong here).
- **F1.2 Episode targeting is implicit.** FACT `pipeline.py:155-161`: without `?episode=` the status picks the first
  episode whose `ep{NNN}_final.mp4` is missing. The plan says `--episodes 1` *and* "per-episode steps run for every
  episode returned by `episodes`" (ASSEMBLY_PLAN.md:120-123) — contradictory. INFER: a loop that does not pass
  `episode` keeps going into episode 2..N after ep001 and spends the once-only Seedance pool. Fix: the connector
  always passes `episode=N` and stops at the requested count.
- **F1.3 `identity_plan` status covers identities only.** FACT `pipeline.py:163-165`: done = the episode has
  `identity_ids`. Scenes, props and scene masters (bundled into that step in plan §5, line 200) are not tracked by
  any status flag; FACT plugin `__init__.py:836-866` describes them as "before sketch generation". INFER: the status
  loop will never ask for them; the connector must call them explicitly after `identity_plan`, or sketches run
  without scene references (lower consistency). The plan does not say which. Fix: make it an explicit sub-sequence
  with its own completion check (scene list non-empty / master image exists).
- **F1.4 `coloring` is a misnomer in the plan.** FACT `pipeline.py:181-186`: done = sketches exist and every beat
  has `detected_identities` or `detected_props`; colour assignment happens inside the sketches handler (FACT plugin
  `__init__.py:886-941`, `auto_assign_colors` default true). Plan §5 mapping to `_handle_detect_sketch_identities`
  is correct. Note: FACT plugin `__init__.py:953-961` — on timeout the donor tells the agent to stop and ask the user;
  the connector's D15 retry must treat this as retryable-later, not fatal.
- **F1.5 Sketch defaults pull in the second image model.** FACT plugin `__init__.py:902-907`: sketches default to
  `model: "nanobanana"`, `aspect_ratio: "2:3"`. INFER: per D7 `LingShan-NB-2` (nanobanana) maps to a Gemini image
  model "if its free tier answers" — so sketches, the highest-volume image step (one grid per scene group, per
  episode), depend on the least certain pool. M1.0 must probe Gemini image *and* decide whether sketches are pinned
  to `LingShan-G2`/Seedream via `image_generation_selection` (accepted body key, line 913). Severity: high (quota).
- **F1.6 Video is per beat.** FACT plugin `__init__.py:1640-1676`: `single_video` takes one beat; the beat needs a
  first frame and `video_prompt`. The connector must iterate beats and poll each `single_video` task (task key has
  `beat_num`, FACT `__init__.py:629-633`). `episode_status.video` = an `.mp4` per beat (FACT `pipeline.py:200-202`).
  INFER: a beat whose `video_mode` from `global_optimize` is a still mode may still require an mp4; unknown until M2.
- **F1.7 `tts` completion requires `.mp3` per beat.** FACT `pipeline.py:197-199`. See §2 for the voice path.
- **F1.8 The "REWORK → `/beats/regenerate`" step of M4 regenerates first frames, not clips.** FACT plugin
  `__init__.py:1529-1561`: `beats/regenerate` is the `selected_regen` (first-frame) task. A rework therefore needs
  regenerate → `single_video` for those beats → `compose` → re-download → re-finish → re-review. Plan M4.2
  (ASSEMBLY_PLAN.md:172-173) underestimates this and it spends Seedance again. Severity: medium.
- **F1.9 Vendoring the plugin is optional, not required by D3.** FACT the plugin is a thin stdlib HTTP wrapper around
  REST paths (`__init__.py:310-347`, handlers 720-1676) and imports `tools.registry` (line 18), which needs the shim.
  INFER: vendoring it buys the donor's endpoint knowledge and prerequisite error texts; calling the same paths with
  httpx would be equally "whole". Either is acceptable; the plan should not count the shim as zero-risk (it couples
  us to Hermes' registry signature). Keep D3, but test the shim against the vendored file in CI.

## 2. Voice path (D9/D10, M1.3–M1.4) and media relay (D11)

- **F2.1 The reference sample reaches our adapter as a `data:` URL, not a downloadable URL.** FACT
  `seedance2_i2v/voice_clone.py:402-417` (`build_reference_audio_url` → `local_file_to_data_url`, comment "Reference
  audio still follows the v2.0 flow and travels as an inline data: URL"); FACT no caller passes a non-default
  `audio_url_builder` (`voice_audio_task.py:95`, `narration_audio_task.py:86` default `None`; grep of
  `audio_url_builder=` in `src/novelvideo`). The plan's D9 / M1.3 say the adapter maps "by SHA-256 of the
  downloaded `audio_url`" and falls back to "the sample's file name if the media relay re-encodes the bytes"
  (ASSEMBLY_PLAN.md:50,105-106). INFER: both framings are wrong — there is no download and no file name; the adapter
  must base64-decode the data URL. Good news: FACT `character_voice_storage.py:481-484` stores the uploaded bytes
  verbatim and returns `voice_content_sha256(content)`, so the SHA of the decoded bytes equals the SHA of the
  sample we uploaded; the mapping works and **TTS does not need Cloudinary**. Fix: adapter accepts `data:` (primary)
  and `http(s)` (secondary); drop the file-name fallback; cap 5 MB (FACT `voice_clone.py:411-416`).
- **F2.2 The adapter's returned URL is fetched by the DramaClaw container.** FACT `generators/indextts2_fal.py:342-345`
  (`client.get(result_url)` inside the api container). INFER: the adapter must return
  `http://host.docker.internal:23350/audio/<id>.wav`, not a `127.0.0.1` URL, and must listen on the docker bridge
  address (plan says this, line 101) — add a test that the URL host is the configured public host.
- **F2.3 Output bytes are written to `beat_NN.mp3` as received.** FACT `indextts2_fal.py:345`
  (`output_path.write_bytes(audio_response.content)`) and `voice_clone.py:70-71` (path ends `.mp3`). If the adapter
  returns WAV, DramaClaw stores WAV bytes with an `.mp3` name. INFER: ffmpeg probes content so compose likely works,
  but duration probing and later concat are risk points. Fix: the adapter returns MP3 (one ffmpeg call) — cheap.
- **F2.4 Auth header is `Key <FAL_API_KEY>`; `FAL_API_KEY=local` is required to be non-empty.** FACT
  `indextts2_fal.py:190-196,336`. Plan matches.
- **F2.5 Organization egress mode blocks the fal provider.** FACT `indextts2_fal.py:184-189`: when an egress context
  is present and the provider is not `newapi`, the result is `ORG_EGRESS_DENIED`. INFER: CE single-owner mode has no
  context (M0 runs CE), so fal works; but if the project is ever created under an organization scope the voice path
  silently fails. Record as a constraint in ASSEMBLY_MODELS.md.
- **F2.6 Every TTS call reserves usage credit first.** FACT `indextts2_fal.py:231-253`
  (`_reserve_tts_model_call` → usage meter; failure returns "credit reservation failed"). INFER: in Custom mode with
  local NewAPI this is probably a no-op or local ledger, but it is unverified; M1 acceptance (TTS preview) will show.
- **F2.7 Voice slots are per age group.** FACT `character_voice_storage.py:31-33` (`default`, `child`, `youth`,
  `middle`, `elder`) and `voice_clone.py:431-491` (identity override → age-group slot → character default). INFER:
  casting only into `default` (plan M1.4) loses DramaClaw's own child/adult voice change when an identity ages. Fix:
  cast per slot used by the character's identities (one VieNeu preset per slot, same gender), still connector-only.
- **F2.8 Media relay is mandatory for image/video reference inputs, and is a hard prerequisite of M2, not of M1.**
  FACT `storage/media_relay.py:279-317` (only `cloudinary` / `aliyun_oss`, else `MediaRelayConfigError`); FACT
  `generators/video_generator.py:2165-2195` (even `data:` inputs are uploaded through the relay). INFER: portraits
  may be text-only but identity images, sketches with references, first frames and video all need the relay. The
  plan lists Cloudinary as a sponsor prerequisite (§3) but M1's done-criterion (TTS preview) does not need it, so
  M1 can close while M2 is blocked. The handoff (`ASSEMBLY_HANDOFF.md` "Waiting on the sponsor" 1) shows it is
  still open. Fix: make "relay configured and a relay round-trip probe passes" an explicit M2 entry gate, and ask
  the sponsor now (it is the critical-path item, not the keys).

## 3. Story stage (M3) against huohuo @ f104b85

- **F3.1 Route sequence in ADR-0170 / M3.2 is correct.** FACT `workbench-server/src/routes/novel/novel.ts:167`
  (`generate-premise`, keywords required, ≤ 500 chars), `:313` (`dramas/:id/outline`), `:1573` (`memory/init`),
  `:1535` (`generate-remaining/stream`, modes `remaining|all|range|chapters`), mounted under `/novel` on the
  protected API (FACT `workbench-server/src/index.ts:97`). Create = `createUserProject` with `project_type:"novel"`,
  `novel_genre`, `premise`, `total_chapters` (default 10), which seeds chapter stubs (FACT
  `services/drama/drama-catalog-service.ts:106-166`). Outline uses `chapters.length` as the chapter count (FACT
  `novel.ts:330`), so `total_chapters` at create time decides book length.
- **F3.2 The batch stops when the HTTP stream drops.** FACT `novel.ts:1556-1566` (`shouldStop: () =>
  signal.aborted`); FACT `services/batch/batch-generation.ts:198-200` (`batch_stop_on_error` default true → stops at
  the first failed chapter, line ~372). INFER: a 10–30 chapter book on a free model is a multi-hour single SSE
  connection; any connector restart, timeout or proxy idle-cut aborts it. M3.2 says "read the server-sent events
  to the end" and has no resume. Fix: the connector re-issues `{mode:"remaining"}` after a drop or a failed chapter
  (the donor's own resume), counts chapters done from `GET /dramas/:id` chapters, and applies D15 per re-issue.
  Severity: high.
- **F3.3 D12 cannot work with the donor compose as written.** FACT `deploy/docker-compose.yml:11-30`: the service's
  `environment:` passes only DB, `SITE_*`, `CONFIG_ENCRYPTION_KEY`, `BOOTSTRAP_ADMIN_*`; no `HUOHUO_PRESET_*` and no
  `extra_hosts`. An `.env` next to it only feeds `${…}` substitution, so `HUOHUO_PRESET_TEXT_BASE_URL` never reaches
  the container, and `host.docker.internal` does not resolve on Linux without `host-gateway`. FACT
  `services/ai/ai-config-service.ts:50-64`: DB preset rows win over env; the API key is per preset card in the DB.
  Fix: an override compose file (as done for DramaClaw in M0) adding the preset env, `extra_hosts`, loopback port
  binding; then set the key through huohuo's own AI-config API/UI (a sponsor-pasted key, like DramaClaw's). Plan
  M3.1 (ASSEMBLY_PLAN.md:153-154) omits both. Severity: high (M3 blocks on it).
- **F3.4 huohuo publishes on all interfaces and ships a known default token.** FACT `deploy/docker-compose.yml:8`
  (`"${PUBLISH_PORT:-18088}:80"`, no `127.0.0.1:`), `:26` (`SITE_API_TOKEN` default
  `huohuo-dev-site-token-change-in-production`), FACT `common/security/secret-cipher.ts:7-9` (that token is the
  fallback encryption secret). Conflicts with D24's loopback-only stance. Fix in the override: `127.0.0.1:18088:80`,
  random `SITE_API_TOKEN` and `CONFIG_ENCRYPTION_KEY`.
- **F3.5 Admin bypasses credit and config checks.** FACT `services/credits/credits.ts:150-158` (admin returns early),
  `services/ai/user-ai-config-resolve.ts:402-408`. INFER: logging in as the bootstrap admin avoids huohuo's credit
  system entirely — good for automation, but then which AI config the admin's calls resolve to must be verified on
  the first premise call (M3 probe).
- **F3.6 Missing from M3: fetching chapter text and the cast list.** The plan says "fetch the chapters' text" and
  "collect the cast names from huohuo's story memory/state cards" without naming endpoints. FACT available:
  `GET /novel/dramas/:id/memory` (`novel.ts:1589`), `GET /novel/dramas/:id/state-cards` (`:550`); chapter content
  lives on episode rows (`scriptContent` holds the brief, FACT `batch-generation.ts:256,284`; the chapter body field
  is UNKNOWN from what I read). Fix: name the endpoints in the plan after one probe; a wrong field silently feeds
  the writing brief instead of the chapter into translation.
- **F3.7 `generate-premise` is optional in the plan's own flow.** INFER: create with `premise` + `outline` works
  without it (FACT `novel.ts:323-327` uses body premise or stored premise). D22 "app's own idea" needs it; the
  sponsor's idea can skip it. Minor.

## 4. Language through DramaClaw and the translation unit

- **F4.1 A Vietnamese story is classified as Chinese by DramaClaw.** FACT
  `src/novelvideo/utils/source_language.py:14,30-96`: the contract is `Literal["zh","en"]`; any other language
  "retain[s] the Chinese fallback" (comment at :92-95). FACT `:99-111`: the zh instruction tells models to write
  every user-visible free-text field in Chinese and keep names verbatim. Used by extraction, identity planner,
  literal script writing, keyframe/video prompt builders, global optimizer (grep of callers). INFER: character
  descriptions, scene names, beat visual descriptions will be Chinese. **Spoken text is protected:** FACT
  `workflows/literal_script_writing.py:668,746-749` — `narration_segment` is set by the system from the raw source
  line ("dialogue 提取台词，narration 保留解说文本"), not by the model. So TTS input and subtitles should stay
  Vietnamese; names stay as given (Latin Hán-Việt after M3.3). Remaining risk: any on-screen text the image/video
  model draws, and Chinese-language `next_step_name`/errors in our page. Not a blocker, but the M2 acceptance check
  must explicitly look at subtitles and on-screen text. (Round B owns the detail.)
- **F4.2 `translate_text` contract is real but needs an adapter the plan does not count.** FACT
  `lib/story_translation.py:172-194`: `_translate_text(text, *, target, terms, generate)` where `generate` takes a
  `lib.text_backends.base.TextGenerationRequest` with `response_schema=TranslatedBatch` and returns
  `TextGenerationResult`; batches of 4 000 chars (`:44`), 3 attempts (`:45`), CJK and length checks (`:83-102`).
  INFER: the connector needs a NewAPI-backed `generate` that honours `response_schema` (JSON schema output). Whether
  OpenRouter `ernie-5.5-flash-preview:free` supports structured output is UNKNOWN; if it does not, every batch fails
  JSON validation and burns 3 calls. Fix: add "structured output on the D5 writer" to the M1.0 probes, with the
  registry's next writer as decided fallback. The module also imports `lib.episode_ledger`, `lib.text_attestation`,
  `lib.json_io`, `lib.path_safety` (`:24-28`), so "imports only `lib.story_translation`" (plan §1) in practice drags
  several ArcReel modules — acceptable, but a freeze of ArcReel's `lib/` now constrains the assembly.
- **F4.3 Name glossary step (M3.3a) is a new mechanism, not reuse.** INFER: "translate cast names once to Hán-Việt and
  replace them in the Chinese text" is our own code with no donor; the old translator already keeps protected
  terms. It is small and justified by GOAL rule 2 (no donor has zh→vi), but it changes the Chinese source before
  translation; a partial replace (a name inside a longer word) corrupts text. Needs a test fixture with overlapping
  names. Medium.

## 5. Work breakdown derived from GOAL alone, and the diff with ASSEMBLY_PLAN

GOAL product rows and rules → minimum deliverables (INFER unless cited):

| # | Deliverable from GOAL | In plan? | Note |
|---|---|---|---|
| W1 | Run DramaClaw whole (GOAL row 2) | M0 ✅ accepted | FACT `ASSEMBLY_ACCEPTANCE.md:5-17` |
| W2 | Models configured for free pools (tolerance "spend above zero") | M1 | needs keys + relay (sponsor) |
| W3 | Vietnamese voices in DramaClaw (row 2 "Vietnamese voices") | M1.3–1.4 | correct the data-URL handling (F2.1) |
| W4 | Media relay working (no film without it, F2.8) | only §3 prerequisite | **missing as a gate** |
| W5 | Connector: story file → episode film, no human step (row 2, rule 4) | M2 | fix §5 keys (F1.1), episode param (F1.2), scenes/props (F1.3) |
| W6 | Two reviewers accept or sponsor accepts by eye (row 2) | M2 "agent and sponsor watch"; M4 reviewers | GOAL allows sponsor-by-eye, so **M4 review is not on the critical path** |
| W7 | huohuo whole → story (row 1) | M3 | compose override missing (F3.3), resume (F3.2) |
| W8 | Translation to natural Vietnamese, no Chinese left (row 1) | M3.3 | structured-output probe (F4.2) |
| W9 | Fully automatic premise → film (GOAL quotes "tự động hoàn toàn") | M3.4 | — |
| W10 | Operator can run it alone (GOAL "một mình tôi vận hành") | M2b, M6 | see §6 |
| W11 | OpenMontage forms (row 3, after drama) | M5 (research only) | correctly deferred |
| W12 | Retries, logs, reports — nothing more (rule 3) | D15 | ok |

What the plan adds beyond GOAL, and whether it conflicts:

- **D25 DramaClaw `vi` locale = a donor code change for a non-model reason.** FACT GOAL.md:26-27 allows a donor change
  "only when a required model has no substitute". FACT ASSEMBLY_PLAN.md:65 and verification round V6 make it a
  donor seam (5 886 strings, frontend image rebuilt). INFER: this contradicts rule 1 as written; GOAL.md:3-4 says a
  conflict is reported to the sponsor the same day. It is a sponsor requirement, so the fix is not to drop it but
  to record a GOAL amendment ("UI locale seams allowed") signed by the sponsor, and to put the work (translate,
  check placeholders, rebuild, retest on every DramaClaw upgrade) in a milestone with an estimate — today it floats
  in M6 "if not done earlier" with no estimate. Severity: high (process), effort ~1–1.5 days.
- **D21 step mode with per-step outputs, approve and redo in our page duplicates DramaClaw's UI (rule 2).** FACT
  DramaClaw already exposes every step's artifacts and regenerate endpoints (plugin getters
  `_handle_get_sketches`, `_handle_get_first_frames`, `_handle_get_character_media`, `_handle_get_episode_media`,
  `__init__.py:1009-1527`) and its own canvas/UI. INFER: rendering chapters, portraits, storyboards, frames, voices
  and clips again in `assembly/web/` is rebuilding a donor screen. Compliant version: the connector's `step` mode
  stops after each `next_step` change; our page shows step name, status, a thumbnail/link at most, and **Continue /
  Pause / Redo (calls the donor endpoint)**, with a deep link into DramaClaw's screen for that project/episode for
  looking and hands-on edits. Severity: high (scope and rule 2).
- **M4 finish/review — the review is a recurring-cost self-built gate.** FACT CLAUDE.md "周期性成本须审批" and
  ADR-0169 precedent; the M4 review re-runs reviewers and, on REWORK, Seedance (F1.8). INFER: GOAL accepts "both
  reviewers accept **or** the sponsor accepts by eye"; until the sponsor has watched the first films, M4.2 should be
  report-only (verdict recorded, no automatic rework loop). M4.1 loudness is cheap and deterministic — keep.
- **D19 run queue / parallel overnight** (M6). FACT pipeline status is per project; DramaClaw is one machine. INFER:
  parallel series compete for one GPU-less task backend and the once-only Seedance pool; the queue should be
  sequential first. Not a conflict, an estimate risk.
- **Jianying export in M6.** FACT verification round §3 rates it P2. INFER: it ports an ArcReel unit onto DramaClaw
  output; it is "post-stage where no donor has the step" so allowed, but it is not needed for any GOAL acceptance —
  move to M5 (rolling).

Estimates (FACT ASSEMBLY_PLAN.md:81-189; INFER judgement):

| Milestone | Plan | Realistic | Why |
|---|---|---|---|
| M1 | 1.5 d, ≤400 | 2 d agent + sponsor wait | probes depend on keys and relay; adapter + casting + per-slot upload + MP3 + data URL |
| M2 | 2 d, ≤600 | 3 d | ~15 step kinds, per-beat video and polling, scene/prop sub-sequence, episode targeting, resume, the first real run will surface donor-runtime surprises (task failures, timeouts, `detect-identities` timeout) |
| M2b | 1 d, ≤500 | 1 d only if cut to §6 scope; 4–6 d as written | "every step's output with pause/approve/redo" + catalog + results + settings is a second UI |
| M3 | 1.5 d, ≤400 | 2–2.5 d | compose override + key setup, SSE resume, chapter/cast endpoints, glossary, translation adapter + structured-output fallback, a multi-hour real book run |
| D25 vi locale | not estimated | 1–1.5 d | 5 886 strings, placeholder check, image rebuild, visual check |
| M4 | 2 d | 1 d finish + 0.5 d report-only review | rework loop deferred |
| M6 | 1 d | 1.5 d | three backup sets of three stacks, restore drill, autostart, alert |

GOAL tolerance is 2× per milestone; M2b as written would breach it on the first day.

## 6. Hidden dependencies in the M2 step order

- **F6.1 Voice casting cannot run where the plan puts it.** Plan M2.2: "create project, upload and start ingest,
  configure (D14), cast voices (M1.4), then loop" (ASSEMBLY_PLAN.md:119-121). FACT the voice upload route returns
  "Character '…' not found" when the character does not exist (`api/routes/characters.py:1365-1368`); characters
  exist only after `build_characters`; age-group slots matter only after `identity_plan` (F2.7). INFER: casting must
  run after `characters` (default + narrator) and be completed per age group after `identity_plan`, always before
  `tts`. The donor's `tts` prerequisite error (FACT plugin `__init__.py:37-40,63-88`) is the backstop. Severity: high
  (the first M2 run fails at the cast step as specified).
- **F6.2 The configure step can and should set more than D14.** FACT `api/schemas.py:87-105` (`ProjectUpdate`):
  `aspect_ratio` (`2:3|9:16|16:9`, D17), `add_subtitles` (M4.1 checks it), `sketch_image_selection` /
  `render_image_selection` (pins the image model, F1.5), `video_backend`, `video_resolution`, `visual_style`. FACT
  `api/routes/projects.py:715-736`: changing `spine_template` resets `aspect_ratio` to the spine default unless
  given. Fix: D14 lists the full configure body; D17's `--aspect` maps to `aspect_ratio`; subtitles on.
- **F6.3 Spend gate before video.** INFER: the plan's first real run (M2 acceptance) goes straight through `video`
  on the once-only Seedance pool. Using the plan's own `step` mode (D21), the first run should stop before `video`
  so frames, script and voices are checked by eye first; then continue. This needs the connector's step mode in M2,
  not only in M2b.

## 7. The UI question: old app UI vs new control page vs donor UIs

Facts:
- The old SPA (`frontend/src`) is a React 19 / Vite / Tailwind / zustand / wouter app (FACT `frontend/package.json`)
  with `vi` among `zh`, `en`, `vi` (FACT `frontend/src/i18n/index.ts:11,18-24`; `i18n/vi/*` 4 208 lines). Its API
  layer is one 3 701-line client against ArcReel's `/api/v1` with bearer-token auth (FACT `frontend/src/api.ts:553,
  809-882`). Feature code: production-run 22 files / 3 571 lines, creative-canvas 6 827, story-authoring 2 351, etc.
- The run panel is bound to R2's governance wire: `expected_input_digest`, `policy_digest`, `expected_version`,
  launch qualification, automation readiness, media probes (FACT `features/production-run/api/productionRunClient.ts:
  27-51,77-119`; `api/types.ts:5-37` 15 R2 statuses incl. `BLOCKED_INPUT_CHANGED`, 15 R2 stages, checkpoints).
  Components `AutomationQualification.tsx`, `AutomationSettingsEditor.tsx`, `RunPauseControl.tsx` carry those fields.
  The server side is `server/routers/production_runs.py` importing `r2.contracts.autopilot` and
  `server.production_run.autopilot` (FACT lines 19-28).
- DramaClaw's UI already shows and edits every film step and has a node canvas (FACT interface note §1; plugin
  getters for sketches, frames, character and episode media). Its locale is zh/en; a `vi` seam is D25.
- huohuo's UI has `vi` (FACT `workbench/app/i18n/messages/vi.ts`).

Options (INFER):

| Option | Coupling | Effort | Operator experience | Risk of dragging R2 back | GOAL rule 2 |
|---|---|---|---|---|---|
| A. Reuse the old SPA + ArcReel server as backend, add assembly routes | ArcReel server, DB, auth, R2 contracts | low to start, high to keep | familiar, Vietnamese, rich | **very high** — run panel speaks digests/qualification; every fix lands in frozen ArcReel; violates plan §1 "imports nothing from `server/` or `r2/`" and GOAL rule 3 | breaks "no governance" |
| B. Fork the SPA's shell (layout, design tokens, `vi` strings, RunGraph/timeline components) into a new React app against the connector | React toolchain in `assembly/`, copied components | 3–5 d to strip R2 types and rewire | closest to old feel | medium — copied components keep R2 vocabulary (stages, statuses) and invite re-adding governance | ok if stripped |
| C. New small server-rendered page (plan M2b) scoped to what no donor shows | connector only | 1 d **if scoped** (below) | plain but sufficient; donor screens for depth | low | compliant |
| D. Donor UIs only (DramaClaw + huohuo), CLI for runs | none | 0 | two apps, two languages, no cross-donor run view, no "start a series" button | none | compliant but fails "một mình tôi vận hành" ergonomics and D21/D22 |

Recommendation: **C, cut to a thin run console, plus the donors' own UIs for depth; reuse the old app's Vietnamese
wording and layout as text, not code.** Reasons: (1) the only things no donor shows are the cross-donor run (premise →
huohuo → translation → DramaClaw → finish), its retries/errors, the start form for D22 sources, and the finished
film + verdict — that is a small page; (2) everything per-step (chapters, portraits, storyboards, frames, voices,
clips, redo) already exists in huohuo's and DramaClaw's screens, so rebuilding it in A, B or the current M2b text
breaches rule 2 and the M2b estimate; (3) A is the exact path back into R2 (governance wire, frozen server) that
ADR-0170 exists to leave; B pays 3–5 days to remove R2 from copied components; (4) operator experience: Vietnamese
is reached by the control page (ours), huohuo `vi` (donor) and DramaClaw `vi` (D25 seam, needs the GOAL amendment
of §5) — that is where Vietnamese effort pays off, because DramaClaw is where the operator spends hands-on time.
Scope for M2b: run list (All/Active/Done/Failed), start form (source, setting, spine, aspect, mode), per-run step
timeline from `pipeline/status` with Continue/Pause/Redo-this-step (donor endpoint) and a deep link per step,
errors panel, film player + download, story zh/vi reader (plain text), links to donor settings. No catalog page
generated from the coverage matrix until M5 — the matrix is a planning document, not an operator need.

## 8. (a) Gap table

| # | Gap | Severity | Evidence | Fix |
|---|---|---|---|---|
| G1 | Media relay not a gate; sponsor item open; M2 impossible without it | **blocker** | `media_relay.py:279-317`; `video_generator.py:2165-2195`; `ASSEMBLY_HANDOFF.md` waiting #1 | M2 entry gate = relay configured + round-trip probe; ask sponsor now (Cloudinary) |
| G2 | Voice casting placed before characters exist | high | `characters.py:1365-1368`; plan :119-121 | cast after `characters`, complete per age group after `identity_plan`, before `tts` |
| G3 | §5 dispatcher keyed on names `next_step` does not return | high | `pipeline.py:18-35,144,234` | key on returned values; fixture from real status |
| G4 | Adapter assumes downloadable `audio_url`; it is a `data:` URL | high | `voice_clone.py:402-417`; `character_voice_storage.py:481-484` | decode data URL; drop file-name fallback; return MP3 at a `host.docker.internal` URL |
| G5 | huohuo preset env/extra_hosts not passed by donor compose; port on 0.0.0.0; default token | high | huohuo `deploy/docker-compose.yml:8,11-30`; `ai-config-service.ts:50-64` | override compose (like M0), loopback, random secrets; key via huohuo AI config |
| G6 | huohuo batch aborts on stream drop / first error, no resume in M3 | high | `novel.ts:1556-1566`; `batch-generation.ts:198-200` | re-issue `mode:"remaining"` with D15 |
| G7 | Sketch default model `nanobanana` → least certain image pool | high | plugin `__init__.py:902-913`; D7 | probe Gemini image; else pin `sketch_image_selection`/`render_image_selection` to Seedream in configure |
| G8 | D25 donor change contradicts GOAL rule 1; no estimate | high | GOAL.md:26-27; plan :65 | sponsor-signed GOAL amendment; own milestone 1–1.5 d |
| G9 | M2b scope duplicates DramaClaw/huohuo screens; estimate unrealistic | high | plan :136-151; plugin getters 1009-1527 | thin run console (§7) |
| G10 | Episode targeting implicit; may run all episodes on the once-only pool | medium | `pipeline.py:155-161` | always pass `episode`, stop at count |
| G11 | Scenes/props/scene masters not tracked by status | medium | `pipeline.py:163-165`; plugin 836-866 | explicit sub-sequence with own completion check |
| G12 | Translation needs structured output from the free writer; unprobed | medium | `story_translation.py:172-194` | add to M1.0 probes; decided fallback writer |
| G13 | M4 rework = frames + video + compose again; recurring-cost gate | medium | plugin 1529-1561; CLAUDE.md cost rule | M4.2 report-only until sponsor approves a rework loop |
| G14 | No spend gate before first `video` | medium | INFER, D21 | step mode in M2; first run pauses before `video` |
| G15 | Configure body incomplete (aspect, subtitles, image selections) | medium | `schemas.py:87-105` | full configure body in D14 |
| G16 | Chapter text / cast endpoints unnamed | medium | `novel.ts:550,1589`; chapter body field UNKNOWN | probe and name them |
| G17 | Vietnamese classified as zh → Chinese asset text; spoken text kept | medium | `source_language.py:14,92-111`; `literal_script_writing.py:668,746-749` | M2 acceptance checks subtitles and on-screen text explicitly |
| G18 | WAV bytes stored as `.mp3` | low | `indextts2_fal.py:345`; `voice_clone.py:70-71` | adapter returns MP3 |
| G19 | `detect-identities` timeout handled by donor as "ask user" | low | plugin 953-961 | connector treats as retry-later |
| G20 | Shim couples to Hermes `tools.registry` | low | plugin :18 | test shim against vendored file |
| G21 | Organization egress would silently disable fal voices | low | `indextts2_fal.py:184-189` | constraint note in ASSEMBLY_MODELS.md |
| G22 | Jianying export in M6 not needed for any GOAL acceptance | low | verification round §3 (P2) | move to M5 |

## 9. (b) UI recommendation (summary)

New thin Vietnamese run console in `assembly/web/` (server-rendered, connector-only) for what no donor shows; huohuo's
`vi` UI for story work; DramaClaw's UI (with the `vi` locale once the sponsor signs the GOAL amendment) and its canvas
for every film step, deep-linked from the console. Do not reuse the old SPA's code: its run panel is wired to R2's
digest/qualification contract and ArcReel's server; reuse its Vietnamese wording and the ComfyUI-style layout only.
Rejected: old SPA + ArcReel backend (drags R2 back, rule 3); fork of the SPA (3–5 d of stripping, governance
vocabulary lingers); donor UIs only (no cross-donor run view, fails single-operator use).

## 10. (c) Corrected task order

0. **Now, sponsor (parallel with 1):** Cloudinary account (G1); keys; sign GOAL amendment for UI-locale seams (G8)
   and confirm M4.2 report-only (G13).
1. **M1a (no keys):** profile JSON + ASSEMBLY_MODELS.md (with configure body incl. image selections, G7/G15);
   voice adapter (data URL, MP3, docker-reachable URL — G4/G18); `voices.py` casting per slot (G2/F2.7); tests.
2. **M1b (keys + relay):** probes — text, structured output on the writer (G12), vision, Seedream via OpenAI channel,
   Gemini image (decides G7), relay round trip (G1), Seedance one short call; TTS preview acceptance.
3. **M2 connector:** dispatcher keyed on real `next_step` (G3); explicit episode (G10); scenes/props sub-sequence
   (G11); cast after `characters` / after `identity_plan` (G2); step mode with a mandatory pause before the first
   `video` (G14); resume; D15 with donor timeout semantics (G19). Acceptance film from the story file; check
   subtitles and on-screen text (G17).
4. **M2b thin run console** (1 d, §7 scope).
5. **M4.1 finish** (loudness; captions only if `add_subtitles` off) — before M3 because it applies to every film and
   is cheap; **M4.2 review report-only.**
6. **M3 story stage:** huohuo override compose + key (G5); SSE resume (G6); chapter/cast endpoints (G16); glossary
   with overlap tests; translation adapter. Acceptance: premise → Vietnamese story → film.
7. **D25 DramaClaw `vi` locale** (after the amendment; 1–1.5 d), so hands-on work is in Vietnamese before daily use.
8. **M6 operations:** backups of three stacks + restore drill, autostart, alert, sequential run queue (D19).
9. **M5 rolling:** genre skills, Jianying export (G22), audiobook, OpenMontage driver research, M4.2 rework loop if
   the sponsor approves its cost.

Changes vs plan: relay becomes an explicit gate; casting moves inside the step loop; step mode moves from M2b into
M2; M2b shrinks; M4.1 moves before M3 and M4.2 becomes report-only; D25 gets its own slot after a GOAL amendment;
Jianying export leaves M6.
