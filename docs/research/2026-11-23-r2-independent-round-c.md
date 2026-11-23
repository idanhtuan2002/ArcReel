# R2 independent round C — What could make the assembly fail (pre-mortem)

Date: 2026-11-23. Reviewer: independent read-only agent (Opus). Brief: section C + common context of
`docs/r2/evidence/assembly-research-briefs.md`.

## Method

1. Read GOAL, ADR-0170, ASSEMBLY_PLAN, ASSEMBLY_ACCEPTANCE, the verification round, and the 2026-11-23 off-course
   research, its review, the waste audit and the operating-model note.
2. Read pinned donor code (DramaClaw b299bfd, huohuo f104b85, OpenMontage 08e2151) where a risk depends on it.
3. Pre-mortem: assume the assembly failed by 2027-02-23; write failure stories; then a risk register.
4. Labels: FACT (file:line) = verified in the file at that line; INFER = my reasoning. No docker, no network.

Findings are appended as they are found (the session may be cut off).

## 1. Early structural findings (from the governing documents)

- **F1. The donor-baseline spike that the round-4 review demanded was skipped.** FACT: the review of the off-course
  research says "Whether a donor makes a better Vietnamese film on our free tiers is unknown — it is the first thing to
  measure, not a premise" and proposes a one-day DramaClaw spike before the re-foundation decision
  (`docs/research/2026-11-23-r2-review-of-the-off-course-research.md` §2.2, §4.2). FACT: ADR-0170 then decides
  "no bake-off, choose from the research we have" (`docs/adr/0170-...md:9-10`). INFER: the assembly is a
  re-foundation committed on an unmeasured premise — exactly round 3's pattern 8 "froze before discovering"
  (`operating-model-vs-large-organisations.md` row 8). M2 is now the de-facto spike, but it is framed as a delivery
  milestone with a 2-day estimate, not as a Go/Kill test. Severity: High.
- **F2. Running image ≠ pinned source.** FACT: M0 runs `claymorelab/dramaclaw:2.0.2` (`ASSEMBLY_ACCEPTANCE.md:7-8`);
  the plan equates it with b299bfd only because `pyproject.toml` says 2.0.2 (`ASSEMBLY_PLAN.md:26-27`). INFER: a
  version string does not prove the image was built from b299bfd; every "FACT (file:line)" about DramaClaw in the plan
  is about source that may differ from the code actually executing. Nobody diffed the image's `/app` against the
  checkout. Also the Vietnamese-UI seam (D25) and any donor seam requires rebuilding from source, at which point the
  running system silently changes from "their image" to "our build". Severity: Medium-High.
- **F3. Plan contradicts itself on the code it owns.** FACT: GOAL rule 2 limits our code to connector, config, small
  adapters, post-stages (`GOAL.md:28-29`); FACT: the plan adds a run queue (D19), auto/step modes with pause/approve/redo
  per step (D21), a remake source via the old app's video→story unit (D22), a 500-line control page (M2b), M4
  finishing + two-reviewer review + AIVPE guards, Jianying export, alerting, backups (`ASSEMBLY_PLAN.md:59-64,136-182`).
  INFER: D21 is an orchestration/HITL layer on top of DramaClaw, which already has its own UI and canvas with per-step
  regenerate; it is the same "own control layer in front of the donor" that produced class G waste
  (`resource-waste-audit.md` §2). Severity: High (recurrence risk).
- **F4. "No governance machinery" vs. D15/D21/M4.** FACT: GOAL rule 3 forbids gates; D21 `step` mode is a human gate per
  step; M4 review with REWORK→regenerate is a quality gate (`ASSEMBLY_PLAN.md:61,171-173`). INFER: allowed by the letter
  (the sponsor asked for D21), but each gate is a state machine we own, and every state the run can be in will need a
  resume path — the exact place (resume semantics fixed piecemeal, audit §3.6) where R2 bled.

## 2. Donor-code findings that turn into failure stories

- **F5. The TTS step can never be "complete" for a film with a silent beat — the run loops or stops at `tts`.**
  FACT: `pipeline/status` marks `tts` done only when **every** beat with `beat_number > 0` has
  `audio/epNNN/beat_NN.mp3` (`api/routes/pipeline.py:55-63,196-198`). FACT: the IndexTTS2 task skips beats whose
  `audio_type` is `silence`, non-dialogue/narration, or empty text — no file written
  (`audio/indextts2_beat_audio_task.py:317-323,479-490`). FACT: `POST …/audio/generate` then answers
  `{"ok": false, "code": "audio_generation_not_required"}` when nothing is billable
  (`api/routes/generation.py:2534-2539`). INFER: a connector that loops on `next_step` (plan M2.2, `ASSEMBLY_PLAN.md:119-122`)
  will see `next_step = tts` forever; with D15 retries it burns 3 attempts and stops the run, on every drama with a
  silent shot (most dramas). This is **the same class** that cost R2 releases 2.5.85/2.5.87 (`resource-waste-audit.md`
  §3.2). The donor's own driver is an LLM agent that reads the error and moves on; a deterministic loop cannot.
  Severity: Critical for M2; earliest warning: first M2 run. Prevention: the connector treats `next_step` as advisory —
  for each step it knows the "nothing to do" codes and advances by calling the next handler explicitly; test against a
  fake with a silent beat.
- **F6. `next_step` values are not the plan's keys.** FACT: the endpoint returns `next_step: task_type or next_step`, i.e.
  `ingest_fast`, `build_characters`, `build_episodes`, `script_writer`, `sketch_generation`, `global_optimize_video`,
  `selected_regen`, `single_video`, `compose_episode` for those steps (`api/routes/pipeline.py:18-35,144,234`); the plan's
  §5 table keys on `ingest`, `characters`, `episodes`, `script`, … (`ASSEMBLY_PLAN.md:193-210`). INFER: trivially fixable,
  but it shows the step table was written from the `_STEP_MAP` keys, not from the response; tests against a fake built
  from the plan's table would pass and the real run would fail at step 1.
- **F7. Other "never complete" predicates.** FACT: `portraits_done = bool(main_chars) and all(...)` — a story where
  character build marks no `is_main` character can never pass `portraits` (`pipeline.py:111-113`); `identity_plan` is
  done only if the episode has ≥1 identity id (`pipeline.py:157-158`); `sketches` needs a PNG in grids/ or sketches/
  (`pipeline.py:173-175`); `first_frames`/`video` need a file for every beat (`pipeline.py:190-201`). INFER: any beat
  whose image or clip is refused by a content filter, or a model that returns nothing, pins the run to that step; each
  retry re-bills the whole step unless the handler supports `missing_only`. Quota drain + stop.
- **F8. The voice contract is not what the plan designed for.** FACT: the reference audio sent to IndexTTS2 is an
  inline `data:` URL built from the local file (`seedance2_i2v/voice_clone.py:402-417`, "Reference audio … travels as
  an inline data: URL", cap 5 MB), not a relayed URL. FACT: the plan's adapter "maps a sample (by SHA-256 of the
  downloaded `audio_url`)" and falls back to "the sample's file name" if the relay re-encodes (`ASSEMBLY_PLAN.md:50,104-106`).
  INFER: the hash design still works (decode the data URL, hash the bytes — actually simpler and offline), but the file
  name fallback does not exist for a data URL, and an implementer following the plan literally will `GET` a `data:`
  URL with httpx and fail. FACT: voice resolution is 3-tier — identity `reference_audio_path` → character
  `voice_samples_by_age_group[identity.age_group]` → character `reference_audio_path` (`voice_clone.py:437-441`).
  INFER: if the casting uploads only one slot, a character's child/elder identity resolves to a sample we never
  registered → adapter's "unknown sample → narrator preset with a logged warning" (`ASSEMBLY_PLAN.md:103`) → **a wrong
  voice that no check notices**. The warning goes to a log nobody reads. Make unknown samples a hard error.
- **F9. Output format mismatch.** FACT: the fal path writes whatever bytes the result URL returns into
  `beat_NN.mp3` (`generators/indextts2_fal.py:342-349`, path from `beat_audio_path`); the plan's adapter returns WAV
  (`ASSEMBLY_PLAN.md:104`). INFER: WAV bytes in a `.mp3` file usually survive ffmpeg (content sniffing) but duration
  probes, the compose concat, and any mutagen-style metadata read may not; silent truncation or A/V drift is the likely
  symptom. Return MP3 from the adapter.
- **F10. `emotion_prompt` and `should_use_prompt_for_emotion` are dropped.** FACT: DramaClaw sends emotion control
  (`indextts2_fal.py:323-328`); VieNeu presets have no emotion input (`ASSEMBLY_PLAN.md:50`). INFER: every line is read
  in the preset's neutral tone; a drama with flat voices is a likely "sponsor rejects by eye" outcome. Not a blocker,
  a quality ceiling that no plan item addresses.
- **F11. Language: every asset prose prompt will tell the model to write Chinese.** FACT: `detect_asset_language`
  returns only `zh`/`en`; Vietnamese is not `en` under langdetect/langid, so it falls to `"zh"` ("Unsupported natural
  languages … retain the Chinese fallback", `utils/source_language.py:14,30-35,92-96`), and the shared instruction says
  "所有面向用户的自由文本字段都使用中文" (`source_language.py:107-110`). FACT: it is used by the identity planner, scene
  builder, literal script writer, video/keyframe prompt builders, global optimizer, structured extraction (grep of
  `source_language` imports: 12 modules). FACT: in the literal script path dialogue text is extracted by the system from
  the source line, not written by the model (`workflows/literal_script_writing.py` prompt constraint
  "narration_segment 由系统根据 audio_type 定型：dialogue 提取台词"). INFER: dialogue voiced in Vietnamese is
  likely to survive; identity names, scene names, descriptions, any LLM-written narration (narrated spine), and
  anything the UI shows will be Chinese — run 010a7912's "Chinese identity names" is this, by design, not a bug
  (`review-of-the-off-course-research.md` §2.2). Fixing it is a donor code change (GOAL tolerance). The plan has
  **no item** for it; D25 translates the UI only. Severity: High for "Vietnamese product" acceptance; medium for M2 film.
- **F12. The "Ken Burns" fallback is not a production path.** FACT: Ken Burns exists only as `MockVideoGenerator`
  ("模拟视频生成器（测试用）"), reachable only through the legacy `use_mock=True` argument, default 1920x1080
  (`generators/video_generator.py:270-296,4552-4554`). FACT: plan §6 relies on "DramaClaw's still/Ken Burns path if
  its video step allows it" when the Seedance pool runs out (`ASSEMBLY_PLAN.md:220`). INFER: that fallback does not
  exist without a donor change; the real fallback is `COMFYUI` ("Claymore 1.0 本地服务", `video_generator.py:4530`) —
  a workflow contract we have not read — on an 8 GB RTX 2070 shared with VieNeu and Ollama.

## 3. Quotas, machine, security, maintenance

- **F13. The free video pool cannot finish even the acceptance episode, let alone a series.** FACT: Seedance 1.0
  pro-fast free quota is **2M tokens, once per account, no reset** (`docs/r2/cloud-free-quota-registry.md`, BytePlus
  table). FACT: DramaClaw submits Seedance-fast at `"resolution": "720p"`, duration clamped to 4–12 s
  (`generators/video_generator.py:~633`, `video_duration.py:60`), one clip **per beat** (`single_video` per beat,
  `pipeline.py:200-201`). INFER (BytePlus token formula W×H×fps×s/1024 from provider docs, not re-verified here):
  720×1280×24×4/1024 ≈ 86k tokens per 4 s clip, ≈108k per 5 s → **≈18–23 clips for the whole pool, ever**. The
  M2 smoke story alone has 29 non-empty paragraphs / 660 words (FACT: `wc` of
  `~/arcreel-v2-staging/data/drama-smoke-chiec-ong-ho-62d166d0/source/chiec-dong-ho-cua-ong.txt`), so its episode will
  plausibly need 25–60 beats. A huohuo chapter (thousands of characters) is several times that. **D19 "many series in
  parallel overnight" is arithmetically impossible on free tiers**; D20 defers money until after the first film, but the
  first film may not complete. Whether part of the pool was already spent on R2 bake-offs is UNKNOWN (registry says
  "kept for bake-offs"). Severity: Critical. Earliest warning: count beats after `script` in M2 and multiply before
  starting `video`. Prevention: decide BEFORE M2 what happens at beat N+1 — this is a money/product question for the
  sponsor (GOAL rule 6), not a technical fallback.
- **F14. Images: 200 Seedream, once.** FACT: Seedream 4.5 = 200 images once (registry). INFER: per episode DramaClaw
  makes portraits per main character, identity images, scene masters, sketches/grids and one first frame per beat
  (§5 table) — order of 50–120 images per episode → **1–3 episodes, then the image path is dead**. The plan's fallback
  "Gemini image" is unverified on the free key ("Image … on the free tier: not tested", registry Gemini section) and
  would be 20/day/model if it works. The local fallback needs an OpenAI-images adapter in front of ComfyUI that does
  not exist yet (verification round V2). 
- **F15. Vision fallback is a model the registry already marked broken.** FACT: D6 falls back from Gemini (20/day/model)
  to OpenRouter `nvidia/nemotron-3.5-super-vl:free` (`ASSEMBLY_PLAN.md:47`); FACT: the registry probe lists
  `nemotron-3.5-super-vl:free` under "invalid / cut JSON — not used" (registry OpenRouter probe table). INFER:
  DramaClaw's vision features (sketch identity detection per beat in `coloring`, identity detection for video) are
  structured-output calls; on day 1, after 20 Gemini calls, every remaining vision call returns invalid JSON → the
  `coloring`/`global_optimize` predicates never complete (F7). Also NewAPI only fails over between channels that serve
  the **same model name**; Gemini and OpenRouter channels need a model-mapping alias — not in the plan.
- **F16. One text pool for everything.** FACT: OpenRouter `:free` = 1,000 requests/day, 20/min, shared (registry);
  D5 + D12 route all DramaClaw `DC-*-LLM` slots, the Hermes agent, huohuo writing and (M3) translation to the same
  ERNIE id. FACT: the literal script writer makes one structured call **per source line** with output retries
  (`workflows/literal_script_writing.py:642-700`, `output_retries=model_gateway_output_retries(2)`). INFER: a 30-chapter
  huohuo novel + its translation + one DramaClaw episode can exceed 1,000/day; preview `:free` ids also disappear without
  notice (ERNIE is a "preview"). The plan has no daily budget per stage and no "stop before the pool is empty" rule.
- **F17. Silent model changes.** FACT: images are pulled by **tag**, not digest (`docker-compose.release.yml:11,56,80`);
  the gateway is a release candidate fork `v1.0.0-rc.24-dramaclaw.1`; the gateway source is not cloned locally (only
  `~/.cache/r2-donors/{dramaclaw,dramaclaw-full,openmontage}` exist). FACT: CE runs an official media catalog updater
  that polls GitHub `main` / an Aliyun OSS manifest every 300 s when auto-update is switched on (default off)
  (`api/app.py:393-403`, `official_media_catalog_remote.py:25-30,192-214`, `model_gateway_settings.py:640`). INFER: one
  click in Settings turns on remote rewriting of DramaClaw's model catalog; a `docker compose pull` or a re-pushed tag
  changes code under a "pinned" system. Upstream free models (`:free`, preview ids) change weekly. Nothing in the plan
  re-probes models on a schedule; the registry itself says "a free tier changes without notice".
- **F18. Disk: 16 GB free on a 195 GB disk at 92 %.** FACT: `df -h /` → 195G size, 170G used, 16G free (this session);
  M0 recorded 16 GB free after a 4.64 GB image pull (`ASSEMBLY_ACCEPTANCE.md:15`); `~/arcreel-v2-staging` = 12 GB and
  stays in production (ADR-0170 "ArcReel/R2 is frozen … keeps serving production"). FACT: R2 already failed runs with
  `INSUFFICIENT_DISK` twice and kept every backup set (`resource-waste-audit.md` §1). INFER: still to come on the same
  disk — huohuo built from source (node + build cache, several GB), the DramaClaw frontend rebuilt for `vi` (another node
  build), episode media (hundreds of PNGs + clips per episode), M6 backups of **three** stacks with three sets each.
  The disk fills during M3–M6, most likely mid-render, and DramaClaw's file-existence predicates (F7) turn a write
  failure into an endless step. Severity: High, likelihood High.
- **F19. GPU: one 8 GB card for everything local.** FACT: RTX 2070 8 GB (machine facts; `nvidia-smi` 578 MiB used now).
  INFER: VieNeu (TTS, every line), the M4 local reviewers (`qwen2.5vl:7b` + `gemma3:4b`, ADR-0169), the R2 production
  Ollama models, and every "local fallback" in §6 (ComfyUI images, Wan video) contend for it. Wan video at 720×1280 on
  8 GB is minutes per clip if it fits at all; the fallback that is supposed to save the series when pools run out is the
  slowest and least proven path. No GPU scheduling or mutual exclusion in the plan.
- **F20. Security: CE = everyone is the owner.** FACT: CE local auth returns `role="owner"` for any request, cookie or
  not (`ports/local/auth.py:21-23`); no CORS or TrustedHost middleware in the API (`grep add_middleware` finds only a
  coverage middleware, `shared/api_coverage.py:63`). FACT: ports bound to loopback (`override.yml` comment;
  `ASSEMBLY_ACCEPTANCE.md:9-10`); NewAPI bind is one env var away from `0.0.0.0`
  (`docker-compose.release.yml:63-65`). INFER: loopback stops the LAN, not the operator's browser — any web page can send
  "simple" cross-site requests (multipart uploads, form posts) to `127.0.0.1:8780` blind, and a DNS-rebinding page gets
  full read access, including Settings that hold OpenRouter/Gemini/BytePlus/Cloudinary keys. FACT: the OpenRouter account
  holds bought credits ("≥ 10 credits", registry) — a stolen key can bill non-free models. The voice adapter binds to the
  docker bridge too (`ASSEMBLY_PLAN.md:101`), reachable by every container on the host. The control page (D24) has no
  login. Likelihood low, impact high. Prevention: Host-header allow-list proxy in front of 8780/8080/3000/control page;
  OpenRouter credit limit 0 / key restricted to `:free`.
- **F21. huohuo stops writing when the stream drops.** FACT: `generate-remaining/stream` passes
  `shouldStop: () => signal.aborted` — the batch stops when the HTTP client disconnects
  (`workbench-server/src/routes/novel/novel.ts:1556-1565`). INFER: a connector restart, read timeout, laptop sleep, or
  control-page reload during a multi-hour novel silently stops it; resume works (`mode: "remaining"`) only if the connector
  knows to use it. The plan says `{mode:"all"}` and "read the server-sent events to the end" (`ASSEMBLY_PLAN.md:158-159`) —
  `all` without `overwrite` semantics must be checked, otherwise a resume rewrites finished chapters (quota).
- **F22. Hidden coupling of the story stage to the film stack.** FACT: D12 sends huohuo's text through DramaClaw's
  NewAPI at `host.docker.internal:3000` (`ASSEMBLY_PLAN.md:53`). INFER: DramaClaw down or upgrading = no stories either;
  the "one key store" is also one point of failure and one ledger that two donors' retries drain.
- **F23. Voices depend on the frozen old stack.** FACT: the VieNeu shim lives at `~/arcreel-v2-staging/vieneu-tts-shim/server.py`
  (`ASSEMBLY_PLAN.md:50`), i.e. inside the R2 production deployment that the assembly is meant to replace. INFER: the
  day R2 is retired or redeployed, voices break; the shim is not in the plan's backup or systemd list (M6 lists only the
  voice adapter and control page).

- **F24. A donor strength worth keeping (to be fair).** FACT: CE runs tasks inline in the API process
  (`ports/local/tasks.py:70-86`, `InlineTaskBackend`) and sweeps tasks left ACTIVE by an earlier process on first DB
  open (`task_state.py:152-158,1397-1413`). INFER: a container restart loses running work but leaves a clean "failed"
  state; the connector must re-issue the step, not wait on `get_task` forever. This also means DramaClaw has **no
  parallelism across projects beyond its lane thread pools** — D19's overnight parallel series share one process.
- **F25. The vendored toolset is an LLM-facing layer, not an API.** FACT: the plugin's handlers are thin wrappers around
  REST calls whose docstrings and descriptions instruct an LLM ("you do NOT pass a prompt", "do not call it again in the
  same turn; report the timeout and stop") and return JSON *strings* with chat error hints
  (`.hermes/plugins/dramaclaw/__init__.py:310-345,1640-1662,2022-2023`). INFER: D3 couples us to the donor's most
  volatile layer (2,373 lines that change whenever their agent's prompting changes) to gain almost nothing — each
  handler is one `_request`. Vendoring it verbatim also freezes it while the server image may move (F2). It does give
  a donor-maintained map of endpoints and arguments, which is its real value. Better: read it as the endpoint map, call
  REST directly with httpx, keep the vendored copy as a contract-test fixture.

## 4. Process recurrence (the first 2.5 months' failure modes, checked against today)

- **P1. Research about research, again.** FACT: 45 commits on 2026-11-23, 30 of them `docs(...)`, 3 touching
  `assembly/` (this session's `git log --since=2026-11-23`); round 4 had warned "Four rounds in one day … Research needs
  a time and quota box like any stage" (`review-of-the-off-course-research.md` §2.5). After that warning came: options,
  coverage matrix, separate-vs-assembly, plan review, interface research, verification round, and now three more
  independent rounds (this one included). INFER: the time-box was never set; the pattern "verification over-built,
  validation missing" (`operating-model…md` row 1) is recurring at the document level. No film has been attempted.
- **P2. The sponsor is still asked technical questions.** FACT: the handoff lists "Answer: old app UI vs new control
  page" under *Waiting on the sponsor* (`ASSEMBLY_HANDOFF.md` "Waiting on the sponsor" item 3); GOAL rule 6 says the agent
  decides technical choices (`GOAL.md:36-37`). FACT: D16–D26 are eleven sponsor decisions recorded in one day
  (`ASSEMBLY_PLAN.md:56-66`). INFER: several are product (fine), but the volume shows the sponsor is again the router.
- **P3. Plan grows before the first film.** FACT: the plan went from M0–M5 to M0, M1, M2, M2b, M3, M4, M5, M6 plus
  D16–D26 the same day (commit subjects "add the control page (M2b) and operations (M6)", "D17–D20", "D21–D24",
  "D25/D26"). INFER: scope creep before validation — Gall's law cited in round 3 row 9 is being re-violated.
- **P4. Old machinery pulled back in.** FACT: M4 calls "the old app's units" for loudness, music, ambience and "the two
  configured reviewers and the AIVPE guards (ADR-0169)" (`ASSEMBLY_PLAN.md:168-174`); M6 adds the old app's alert
  channel and Jianying export; `assembly` may import `lib/` modules (`ASSEMBLY_PLAN.md:31-32`). INFER: these modules
  carry their R2 dependencies (local GPU reviewers, qualification history, config); the reviewer stack is exactly the
  class Q work that consumed 12 % of releases (`resource-waste-audit.md` §2). Re-entry path for R2 complexity.
- **P5. "Tests pass" as completion, in disguise.** FACT: M1 "Done when" includes unit tests for the adapter; M2.5 tests the
  loop "against a fake DramaClaw (httpx MockTransport)" (`ASSEMBLY_PLAN.md:111-113,128-129`). INFER: a fake built from
  the plan's assumptions would encode F5/F6/F8 as correct. Fakes must be recorded from the running DramaClaw.
- **P6. Per-instance fixing.** INFER: F5 and F7 are one class ("a step whose completion predicate can never become
  true"); the class-fix rule (CLAUDE.md) should be applied before M2, not after the first three blocked runs.

## 5. Failure stories (pre-mortem: it is 2027-02-23 and the assembly has failed)

**Story 1 — "The pool ran dry in episode one" (most likely).** M1 probes pass. M2 runs the smoke story: ingest,
characters, portraits, identities, script (41 beats), sketches, frames — 70 Seedream images gone. `video` starts; at
beat 19 BytePlus returns `SetLimitExceeded`. The connector retries 3×, stops, ledger line. §6 says "Ken Burns path if
its video step allows it" — it does not (F12). ComfyUI Wan on the 2070 takes 9 min a clip and OOMs while VieNeu holds
VRAM. The sponsor is asked for money (D20) for a film he has not seen; the half-film cannot be judged. Two weeks pass on
"a cheaper video route" research. Root cause: quota arithmetic was never done before choosing a per-beat video pipeline
on a once-only pool (F13, F14).

**Story 2 — "Stuck at tts forever."** The run reaches `tts`; two beats are silent; `pipeline/status` keeps returning
`tts`; `audio/generate` answers `audio_generation_not_required`; D15 retries thrice and stops. A fix adds a skip; then
`portraits` loops on a story with no `is_main` character; then `coloring` loops after the vision fallback returns bad
JSON. Each is a release, a redeploy, a resume — the 2.5.85/2.5.87 pattern rebuilt inside the connector (F5, F7, F15, P6).

**Story 3 — "Vietnamese in the ears, Chinese everywhere else."** The film plays with Vietnamese voices, but identity
names, scene names, character descriptions in DramaClaw's UI, canvas and export ZIP are Chinese; the narrated spine's
narration is written in Chinese and VieNeu reads Chinese text as noise. The sponsor rejects by eye. Fixing
`detect_asset_language` is a donor change (tolerance), then 12 call sites (F11). The `vi` UI translation (5,886
strings) was done, and shows Chinese data in a Vietnamese frame.

**Story 4 — "Wrong voice, nobody noticed."** A character's elder identity resolves to an age-group sample we never
registered; the adapter logs a warning and uses the narrator preset. Episodes 1–4 ship with the grandfather speaking
as the narrator in some scenes. Found by the sponsor weeks later (F8).

**Story 5 — "The disk."** huohuo build + DramaClaw `vi` frontend build + 3 episodes of media + nightly backups of three
stacks + R2 still in production. At 2 GB free a Seedance download writes a 0-byte clip; the predicate sees the file
exists (F7 inverse) or the compose fails. Backups were tar of live SQLite and the one restore attempt fails (F18, R-backup).

**Story 6 — "Upstream moved."** A `docker compose pull` after a reboot (or the auto-update toggle) changes the gateway
or the model catalog; ERNIE `:free` preview is withdrawn; `LingShan-G2` mapping silently points at a model the
channel cannot serve. Every image call fails with a message in Chinese that the operator cannot read (F17).

**Story 7 — "The control layer ate the project."** D21 step mode, pause/approve/redo, a run queue (D19), M4 review with
REWORK → regenerate, alerts — each has states; each state needs resume; resume is fixed piecemeal across releases. By
February `assembly/` is 6–8 k lines, most of it orchestration that DramaClaw's own canvas already offers. The 2,600-line
budget (sum of milestone budgets) was breached in M2b and recorded as a "tolerance" nobody acted on (F3, P3, P4).

**Story 8 — "The keys walked."** The operator opens a malicious page while the stack runs; DNS rebinding reads DramaClaw
settings; the OpenRouter key with bought credits is used on paid models. Free pools are burned in an afternoon (F20).

- **F26. Backups across three stacks have no restore test and ignore the donor's own tools.** FACT: DramaClaw keeps
  project state in SQLite under the `ce-data` volume and NewAPI (with every provider key) in
  `/newapi-data/one-api.db` (`docker-compose.release.yml:36-47,61-67`); it ships its own backup code
  (`src/novelvideo/backup/{db_daily,files_sync,wal_migrator}.py`, Litestream support in `api/app.py:382-390`). huohuo keeps
  `./workbench-data` (`huohuo-drama/deploy/docker-compose.yml:9-10`). FACT: M6 says only "Backups include DramaClaw's and
  huohuo's Docker volumes and `~/assembly-data` (three sets kept)" (`ASSEMBLY_PLAN.md:179`). INFER: a tar of a live
  SQLite volume is not a consistent backup; no restore drill is planned, although R2's restore drills and power-loss
  recovery were the one thing its governance bought (`review-of-the-off-course-research.md` §2.1). The secrets file
  `~/assembly-data/secrets/newapi-root` and the `.env` live in the same tree that gets backed up — backups contain keys.
- **F27. A forgotten fallback to the vendor's cloud.** FACT: `NEWAPI_BASE_URL` defaults to DramaClaw's commercial relay
  `https://relayclaw.cdnfg.com/v1`, described as the fallback; the gateway actually used is decided by `settings.db`
  `model_gateway_mode` (`docker-compose.release.yml:30-32`). INFER: if `settings.db` is lost or restored from an old set,
  the mode can revert to "official" and calls go to a third-party paid relay (fail without a DC key; story text leaves
  the machine). Low likelihood; set `NEWAPI_BASE_URL` to the local gateway in our `.env`.

## 6. Risk register

L = likelihood, I = impact (H/M/L). "Decided response" = what the agent does without asking, unless it is a GOAL
tolerance (then: report to the sponsor with Go/Kill/Hold/Recycle).

| # | Risk | L | I | Earliest warning | Prevention | Decided response |
|---|---|---|---|---|---|---|
| R1 | Free video pool (Seedance 2M once) exhausted before one episode completes (F13) | H | H | beats × seconds after `script`; BytePlus usage before `video` | Compute token need before `video`; pass `resolution` "480p" where allowed (`_handle_start_single_video` accepts it, plugin:1657); M2 on a short test story first; ask the money question **before** M2, not after | Stop before `video` if need > remaining pool; report to sponsor as a money decision (tolerance), with a cost per episode |
| R2 | Image pool (Seedream 200 once) exhausted in 1–3 episodes (F14) | H | H | image count per episode from M2 | Count per-episode images in M2; verify Gemini image free tier in M1.0 or drop it from §6 | Same as R1; local ComfyUI images only after the OpenAI-images adapter exists and is probed |
| R3 | Steady state needs paid models; D19 "many series overnight" impossible on free tiers | H | H | R1/R2 arithmetic | State it in the plan now; make D19 conditional on D20 | Report to sponsor now (product/money), not after M2 |
| R4 | Completion predicates that never turn true (silent beats, no main character, no identities, refused images) (F5, F7) | H | H | first M2 run; reproducible today from source | Connector knows each step's "nothing to do" codes and advances explicitly; per-step max attempts; class test with a silent beat and a refused image | Class fix in one change; ledger line; never loop on `next_step` blindly |
| R5 | Plan's step table keys differ from `next_step` values (F6) | H | M | first fake-vs-real mismatch | Record real responses from the running DramaClaw as fixtures | Fix table and fake together |
| R6 | Asset prose in Chinese for Vietnamese stories; narrated spine narration in Chinese (F11) | H | H | identity/scene names after `identity_plan` in M2 | Probe: one Vietnamese chapter through `characters`/`identity_plan` and read the language; decide early | Donor seam in `detect_asset_language` (add `vi`, map to a Vietnamese instruction) → GOAL tolerance report; meanwhile `drama` spine only |
| R7 | Wrong voice silently (unknown sample → narrator) (F8) | M | H | adapter "unknown sample" log lines | Cast every identity's age-group slot; unknown sample = HTTP 400 to DramaClaw, not a fallback | Fail the TTS beat; ledger |
| R8 | WAV in `.mp3`, flat emotion (F9, F10) | M | M | duration mismatch in compose; sponsor's ear | Adapter returns MP3; accept flat delivery as a known ceiling | Fix format; record emotion as a quality gap, not a blocker |
| R9 | Vision fallback returns invalid JSON (F15) | H | M | day 1 after 20 Gemini calls | Probe the fallback with DramaClaw's real schema in M1.0; NewAPI model-mapping alias; pick a fallback that passed JSON (registry) | Replace fallback; if none passes, cap vision calls/day and continue the next day (resume) |
| R10 | Shared OpenRouter 1,000/day across huohuo, translation, all DramaClaw text (F16) | M | M | NewAPI usage log ≥ 70 % by noon | Per-stage daily budget; story writing at night, film by day | Pause the run at the cap; resume after reset (15:00 ICT for Gemini, UTC midnight OpenRouter) |
| R11 | Silent model or image changes (tags, catalog auto-update, `:free` ids withdrawn) (F17) | M | H | a step error after a pull or reboot | Pin images by digest; keep auto-update off; cache gateway source; weekly 1-call probe per mapped model | Roll back to the recorded digest; take the registry's next model |
| R12 | Running image differs from b299bfd source (F2) | M | M | behaviour not matching cited code | Diff `/app/src` in the image against the checkout once; record result | If different, cite the image, not the checkout; rebuild from checkout only via one documented script |
| R13 | Disk full (16 GB free, 92 %) (F18) | H | H | < 10 GB free | Budget per episode measured in M2; move donor media volumes and backups off `/` or to a second disk; prune build caches after builds; retire R2 backups per the 3-set rule | Stop new runs below 8 GB; prune; report if a disk purchase is needed (money) |
| R14 | GPU contention on 8 GB (F19) | M | M | VieNeu latency/OOM during reviewers or ComfyUI | One GPU user at a time (simple lock file in the connector); local video fallback only after a measured clip time | Serialize; drop local video fallback if > N min/clip |
| R15 | Security: CE trusts every request; browser/DNS-rebinding; keys in settings (F20) | L | H | unexpected projects or NewAPI usage | Host-header allow-list reverse proxy; OpenRouter key spend limit 0 or no credits; never set `ST_NEWAPI_BIND=0.0.0.0` | Rotate keys; check usage; no further process |
| R16 | Coupling to the donor's LLM toolset (F25) | M | M | plugin signature drift on any upgrade | Use REST directly; plugin as reference fixture | Pin and re-record fixtures on upgrade |
| R17 | huohuo stops on stream drop; `all` may rewrite chapters (F21) | M | M | SSE disconnect in log | Run the stream inside a supervised process; resume with `mode: "remaining"`; never `overwrite` | Resume automatically |
| R18 | Story stage depends on DramaClaw's NewAPI (F22) | M | M | huohuo 5xx when DramaClaw restarts | Accept, or give huohuo its own OpenRouter base URL (direct) | Accept; document |
| R19 | Voice shim lives inside the R2 deployment (F23) | M | H | R2 redeploy or retirement | Move the shim to `assembly/deploy` as a systemd unit before R2 is touched | Move it in M1 |
| R20 | Backups not restorable; keys inside backups (F26) | M | H | first restore attempt | Use DramaClaw's own `backup/` (or `sqlite3 .backup`) and one restore drill in M6 | Drill once; record |
| R21 | Vendor-cloud fallback URL (F27) | L | M | NewAPI calls to `relayclaw` in logs | Set `NEWAPI_BASE_URL` to the local gateway | Config fix |
| R22 | Process recurrence: research rounds instead of a film; sponsor routing; plan creep; old machinery back (P1–P6) | H | H | days since last `assembly/` code commit; plan line count; docs/code commit ratio | A hard rule: no new research note until M2's film exists, except a probe that answers a blocking unknown | Next action is M1.0 probes + an M2 attempt on a short story; everything else waits |
| R23 | Operator load: a non-technical operator with Chinese error messages, three UIs (DramaClaw zh/en, huohuo, control page), sudo deploys, key pasting, Cloudinary sign-up | H | M | sponsor messages asking "what does this error mean" | Control page translates the top-20 donor error codes; one start button; deploys only for host changes (assembly needs no sudo except docker group) | Collect unknown error strings into the page's map weekly |
| R24 | DramaClaw fails acceptance and the §6 fallback (huohuo's film pipeline) is equally unproven | M | H | M2 verdict | Treat M2 as the spike: write the Go/Kill criteria into M2 before running it | Go/Kill/Hold/Recycle to the sponsor with the film |

