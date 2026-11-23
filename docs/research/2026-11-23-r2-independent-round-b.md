# R2 independent round B — What the assembly will produce (2026-11-23)

Reviewer: independent read-only agent (Opus), brief B + common context of
`docs/r2/evidence/assembly-research-briefs.md`. No edits outside this file, no docker, no network, DramaClaw untouched.

## Method

1. Read common context (GOAL, ADR-0170, ASSEMBLY_PLAN, ASSEMBLY_ACCEPTANCE, verification round) and B-specific docs
   (cloud-free quota registry, donor stage mechanisms 2026-11-08, craft quality program incl. smoke run b961dc0a).
2. Walk one story through each step, reading the pinned donor code/prompts (DramaClaw b299bfd, huohuo f104b85,
   OpenMontage 08e2151) to predict the output with the stated models.
3. Count model calls per episode vs quotas; compare with GOAL's quality bar and the old app's films.
4. Every claim labelled FACT (file:line) or INFER. Findings appended as found.

## Findings (appended in order)

### 0. Baseline and constraints read from the documents

- FACT (`docs/GOAL.md:20-21`): acceptance bar — story "natural Vietnamese, complete chapters, no Chinese left"; drama
  "no human step; Vietnamese voices; characters consistent; both reviewers accept or the sponsor accepts by eye".
- FACT (`docs/r2/evidence/R2_CRAFT_QUALITY_PROGRAM.md`, last bullet of the 2026-11-22/23 entry): the old app's best drama
  result is smoke run b961dc0a — 1 episode, **28.2 s, 576x1024**, only 3 spoken lines, first speech at 10.1 s, verdict
  REWORK (reviewer_b MAJOR overlay cut-off), and **identity drift** (Vy reads old/young, Khang's glasses change). So the
  bar the assembly must beat is low on length and consistency but already includes Vietnamese voices and -14 LUFS.
- FACT (`docs/r2/cloud-free-quota-registry.md:151-158`): BytePlus pools are **once per account**: Seedream 4.5 = 200
  images; Seedance 1.0 pro-fast = **2M tokens**; Seedream 4.0 another 200 (not mapped in the plan).
- FACT (`cloud-free-quota-registry.md:50`): OpenRouter `:free` = 20 req/min, **1,000 req/day shared** across all free ids.
- FACT (`cloud-free-quota-registry.md:82-84`): Gemini AI Studio free = **20 requests per model per day**.
- FACT (`ASSEMBLY_PLAN.md:46-49`, D5–D8): every DramaClaw LLM slot → ernie free; vision → gemini-3.5-flash then
  nemotron-vl free; images → Seedream 4.5 behind `LingShan-G2`; `LingShan-NB-2` → Gemini image "if the free tier
  answers", else Seedream; video → seedance-1-0-pro-fast.
- INFER (to verify below): the plan never states how many images/clips/LLM calls one episode costs; the quota rows say
  "200" and "2M" without converting tokens to clips. This is the central question of this round.

### 1. Ingest with spine "drama" refuses prose — the plan's default path cannot ingest huohuo's output (BLOCKER)

- FACT (`dramaclaw-full/src/novelvideo/structured_ingest.py:82-87`, and the same rule in `cognee/store.py:647-653`):
  when `spine_template == "drama"`, `assess_screenplay_scene_headers(content).status == "missing"` raises
  `ValueError("精品剧必须包含场景头，请补充后重新导入")` ("a premium drama must contain scene headers").
- FACT (`utils/screenplay_quality.py:104-120`): scene boundaries "must come from the source text … AI … must never invent
  scene boundaries for headerless prose during import". Recognised headers are Chinese (`第N场`, `场次:`, `内/外`,
  Chinese time tokens) or English `INT./EXT. LOCATION - DAY|NIGHT|…` (`utils/screenplay_scene_parser.py:36-45,155-161`).
- FACT: huohuo's novel engine writes chapters of prose (`2026-11-08-r2-donor-stage-mechanisms.md` §2,
  `generateNovelChapterFull`), and the M2 acceptance story `chiec-dong-ho-cua-ong.txt` (57 lines, 3,963 bytes, read from
  the scratchpad copy) is plain Vietnamese prose with quoted dialogue and **no scene headers**.
- INFER: D26 ("`drama` for dialogue stories (default)", `ASSEMBLY_PLAN.md:66`) fails at the very first DramaClaw step for
  every story the assembly can produce today, including the M2 acceptance story. Only `spine_template="narrated"`
  ingests prose (`story_analysis.py:72-75` chunks it by chapter instead of by scene).
- Fix options: (a) **configuration** — use `narrated` for all huohuo/prose stories (works today, but changes the
  product: narrated = 16:9 default, narration-led, see §2); (b) **donor seam already in the donor family** — huohuo has
  its own novel→drama episode path (`project_type: drama`, `generateEpisodeRawContent`,
  `services/drama/episode-raw-content.ts`) that writes short-drama scripts; whether its output carries DramaClaw-parsable
  headers is UNKNOWN (not read in this round); (c) **post-stage of ours** — a prose→screenplay adapter emitting
  `INT. <địa điểm> - DAY` headers + `Tên: lời thoại` lines (that is building a stage no donor offers in the needed
  format — a GOAL rule 2 question, must go to the plan explicitly, not discovered in M2).

### 2. What "narrated" does to a Vietnamese prose story (the path that actually runs)

- FACT (`workflows/script_writing.py:1-10,41`; `literal_script_writing.py:367-368`, `screenplay_scene_parser.py:180-182`):
  2.0 default is "one line = one beat, keep the original line text, the LLM only adds metadata". A prose paragraph is
  one line → **one paragraph = one beat = one clip**.
- FACT (`literal_script_writing.py:1328-1332`, `:1413-1420`): in narrated mode `silence` becomes `narration`; only
  `narration` / `dialogue` exist.
- FACT (`literal_script_writing.py:39`, `:1309-1326`): the spoken text of a dialogue beat is cut out only when the line
  matches `^Speaker[：:]speech$`; otherwise the **whole raw line** is spoken. A Vietnamese prose line such as
  `"Bác ơi, bác còn sửa đồng hồ cơ không ạ?" cô gái hỏi, giọng run vì lạnh.` has no colon → if labelled dialogue, the
  character's voice also reads "cô gái hỏi, giọng run vì lạnh"; if labelled narration, the narrator reads the girl's line.
  INFER: either way the drama loses the "character speaks her own line" quality the GOAL drama bar implies; a paragraph
  mixing two speakers (the story has several: `"Của ông nội cháu," cô gái nói. "Cháu tên Vy…"`) is spoken by one voice.
- FACT (`project_config.py:38-40`): `narrated` defaults the aspect ratio to **16:9**, contradicting D17 (9:16 drama
  default) unless the connector sets `aspect_ratio` explicitly at configure time (configuration; `api/routes/projects.py:735`
  shows aspect is updated together with the spine).
- FACT (`scene_prerequisites.py:85-97`): scene build does not apply to `narrated` — the scene/master-scene steps the
  plan lists for identity_plan (`ASSEMBLY_PLAN.md:200`) are skipped. INFER: fewer images (good for quota), weaker
  location consistency.

### 3. Durations, clip length, speech truncation (compose)

- FACT (`task_backend/runners/video.py:399-406`, `manual_shots.py:197-218`): a beat's video duration = the beat's TTS
  audio duration (unless `duration_seconds` is set), default 5 s.
- FACT (`dramaclaw-full/.env.example:289`, `video_duration.py:40-55,71-88`): `seedance-1.0-pro-fast` is clamped to
  **2–12 s** per clip.
- FACT (`task_backend/runners/video.py:525-547`): compose muxes each beat's video with its own audio using
  `-shortest` → when the speech is longer than the 12 s clip, **the speech is cut off** at 12 s.
- FACT (`generators/video_composer.py:697-816`): `adjust_video_duration` (trim / 1.5x stretch / freeze last frame) exists
  but has **no caller** besides the package export (`generators/__init__.py:32,95`; grep over `src/novelvideo`). The
  2026-11-08 study's claim that DramaClaw fits video to TTS this way (its §7) is therefore not on the running path.
- Measurement (INFER, from the M2 story file): narrated spine → 29 beats (non-empty lines), 660 Vietnamese syllables;
  paragraph sizes 5–54 syllables. At VieNeu-like 3.5 / 4.0 / 4.5 syllables per second: spoken 189 / 165 / 147 s,
  clip seconds after the 2–12 s clamp 189 / 175 / 161 s, beats over 12 s = 5 / 1 / 0. So the M2 episode is roughly
  **2.5–3 min** (vs the old app's 28.2 s) and loses the tail of 0–5 long paragraphs. A huohuo chapter (default
  thousands of Chinese characters; length band 500–20000, `novel-writing.ts:1303`) translated to Vietnamese is several
  times longer, so per-episode beat counts of 60–150 are plausible (INFER; depends on DramaClaw's episode planner
  chapter ranges).
- Fix: **configuration** — none in DramaClaw for the clamp except choosing a model with a longer range; **connector**
  — split long paragraphs into sentences before ingest (one sentence per line ⇒ more, shorter beats; this is text
  preparation in the connector, not a donor change), which also raises clip count and video quota use (§6).

### 4. Picture size, subtitles, music, loudness (compose output)

- FACT (`api/schemas.py:252-255`; `api/routes/generation.py:2022-2042`; `runners/video.py:467-470,500-503,629-635`):
  compose output is `resolution` from the request, default **720x1280**; every clip is scaled and padded into it.
  A 16:9 (`narrated` default) project composed with the default request is letterboxed inside 720x1280 unless the
  connector passes `resolution: "1280x720"` (configuration of the call).
- FACT (`runners/video.py:469,679-682`): `add_subtitles` is only echoed back as `add_subtitles_requested`; the compose
  runner **burns no subtitles**. `add_bgm` is accepted by the schema (`schemas.py:254`) and copied into the payload
  (`generation.py:2025-2027`) but the runner never reads it → **no music**. There is no `loudnorm` / volume step
  anywhere in compose (grep `loudnorm|LUFS` over `src/novelvideo/generators` and `task_backend` finds none) → **no
  loudness target**; audio is AAC 128k, 44.1 kHz, levels as VieNeu produced them, silent `anullsrc` for beats without
  audio.
- FACT (`export/episode_export.py:19-45`, from the 2026-11-08 study §8): subtitles exist only as an exported **SRT** in
  the export bundle, timed from probed beat audio (5.0 s fallback). INFER: with the `-shortest` cut the SRT can run past
  the audible speech on long beats.
- INFER: so the assembly's raw episode is below the old app on finish: no burned captions, no music, no -14 LUFS. M4's
  finish post-stage (old app's loudness, music bed, ambience, captions "only if DramaClaw's film has none") is
  therefore **required, not optional**, for parity — and the caption branch will always fire. The plan's M4 wording
  "check `add_subtitles` result first" (`ASSEMBLY_PLAN.md:171`) should become "always burn captions from DramaClaw's SRT".

### 5. Character language, names, identities (asset analysis)

- FACT (`utils/source_language.py:14,30-35,92-96`): asset language is `Literal["zh","en"]`; any other language,
  "including … Latin languages that happen to be ASCII-only", falls back to **Chinese**. Vietnamese prose has no Han
  characters; `langdetect` returns `vi`, not `en` → result `zh`. INFER (high confidence): every LLM-written asset field
  (character appearance, `face_prompt`, identity descriptions, scene/prop descriptions, beat `visual_description`,
  keyframe and video prompts) is written **in Chinese** under the instruction "所有面向用户的自由文本字段都使用中文。
  人物名和地点名必须按输入原样保留" (`source_language.py:107-110`; used by `literal_script_writing.py:423,481,642`,
  `agents/keyframe_prompt_builder.py:15`, `agents/video_prompt_builder.py:19`, `agents/identity_planner.py:27`).
- INFER: consequences — (a) image/video prompts in Chinese with Vietnamese names embedded: Seedream and Seedance are
  ByteDance models and read Chinese well, so picture quality is probably *not* hurt; (b) the operator (Vietnamese UI
  after D25) sees Chinese descriptions in DramaClaw's screens — UI strings get translated, data does not; (c) the
  "ethnicity = Vietnamese" project field (D14) is the only cue that people look Vietnamese; whether it reaches the
  image prompts was not traced in this round (UNKNOWN).
- FACT: names must be verbatim in the source (`structured_extraction.py:285-300,489-512`, via the 2026-11-08 study §3).
  INFER: with the connector's Hán-Việt glossary (M3.3) names are stable Vietnamese strings — good; but one character
  referred to as "ông Khang", "Khang", "ông", "bác" in Vietnamese prose may be split or merged unpredictably; the M2
  story calls Vy "cô gái" until she gives her name.
- FACT (`structured_extraction.py:1286-1305`, `structured_builders.py:270-290`): `is_main` is held by **at most one**
  character ("narrator"). FACT (`api/routes/pipeline.py:30,112-114,164-172`): the pipeline's portrait gate and its
  identity-image completeness check look only at `main_chars`. INFER: `next_step` advances past `identity_images`
  when only the main character's identities have images; the secondary characters get identity images only if the
  connector itself calls `_handle_generate_identity_image` for every identity in the episode (plan §5 says "per
  identity" — keep it that way; do not trust `next_step` for completeness). This is the exact place the old app failed
  (Vy drift in b961dc0a).

### 6. Model calls per step (what each episode consumes)

- FACT (`literal_script_writing.py:410-430`): script = one structured LLM call **per line/beat** (slot
  `LITERAL_BEAT_META_MODEL`, `output_retries=model_gateway_output_retries(2)`), i.e. N calls (+ up to 2 retries each).
- FACT (`agents/global_video_optimizer.py:199-204,412-470,250-377`): `global_optimize` calls
  `optimize_single_beat` **once per beat, each call carrying that beat's sketch image** (`BinaryContent` JPEG) — a
  **vision** call per beat on slot `GLOBAL_VIDEO_OPTIMIZER_MODEL=DC-video-prompt-optimizer-LLM` (`.env.example:140`).
- FACT (`api/routes/generation.py:6128` ff., batch loop `batch_size = 25`; `global_video_optimizer.py:762-820`):
  sketch identity detection = one vision call per 25 beats (slot `GLOBAL_VIDEO_IDENTITY_DETECTOR_MODEL`).
- INFER (plan defect): D5 says "all `DC-*-LLM` → ernie" and D6 "vision features → Gemini" (`ASSEMBLY_PLAN.md:46-47`),
  but `DC-video-prompt-optimizer-LLM` and `DC-video-identity-detector-LLM` are `DC-*-LLM` slots that **send images**.
  If they go to ernie (`baidu/ernie-5.5-flash-preview:free`), whether that free id accepts images is UNKNOWN (not in
  the registry probes). If they go to Gemini, the per-beat optimizer alone needs N vision calls per episode against
  **20 per model per day** (`cloud-free-quota-registry.md:82-84`) — one 29-beat episode already exceeds one Gemini
  model's day; the fallback `nemotron-3.5-super-vl:free` returned "invalid / cut JSON" in the registry probe
  (`cloud-free-quota-registry.md:61`), and DramaClaw's agents use strict structured output. **Expected stall at
  `global_optimize`.** Fix (configuration): spread the vision slot over several Gemini models as separate NewAPI
  channels (the registry lists ≥5 Flash ids answering or listed: 2.5-flash, 3-flash-preview, 3.5-flash, 3.6/3.7/3.8
  Flash — each its own 20/day), probe ernie and Groq `qwen/qwen3.8-27b` (vision, 1,000/day, ≤3 images —
  fits a 1-image call) as the vision fallback instead of nemotron; M1.0 must probe *structured output with an image*
  for each.
- Shared pools (INFER, but from documented facts): the old ArcReel production keeps running (ADR-0170 "keeps serving
  production") and uses the **same** OpenRouter key (ernie as story writer and agent, registry :21,26) and the **same**
  Gemini key (reviewers gemini-3.5-flash / 2.5-flash, craft program b961dc0a entry). The assembly's per-day budget is
  what is left after production, not the full 1,000 / 20.

Per-episode call table (narrated spine, N beats, E identities in the episode; INFER from the facts above):

| Step | Text LLM (ernie) | Vision | Images (Seedream) | Video | TTS (VieNeu, local) |
|---|---|---|---|---|---|
| ingest (structured extraction, per chunk) | ~1 per chunk of the episode's text (amortised over the novel) | 0 | 0 | 0 | 0 |
| characters (adjudication + appearance, batched) | ~2–5 per project | 0 | 0 | 0 | 0 |
| episodes plan | ~1–3 per project | 0 | 0 | 0 | 0 |
| portraits (main only) | 0 | 0 | 1 per project | 0 | 0 |
| identity plan (cast / analysis / appearance) | ~3–6 | 0 | 0 | 0 | 0 |
| props plan / narrated scene assets | ~2 | 0 | props: 0–5 ref images (UNKNOWN whether auto) | 0 | 0 |
| identity images (every identity, connector-driven) | 0 | 0 | E (2–5) | 0 | 0 |
| script (one per beat) | N (+retries) | 0 | 0 | 0 | 0 |
| sketches (3x3 grid) | 0 | 0 | ceil(N/9) | 0 | 0 |
| coloring / detection | 0 | ceil(N/25) | 0 | 0 | 0 |
| global optimize (per beat, with image) | 0 | N | 0 | 0 | 0 |
| first frames (location grids ≤8 cells, `LOCATION_POOL_TEMPLATE`, `nanobanana_grid.py:1464`) | 0 | 0 | ≈ ceil(N/8) + locations | 0 | 0 |
| tts | 0 | 0 | 0 | 0 | N (minus silent) |
| video | 0 | 0 | 0 | N clips, Σ = speech length clamped 2–12 s | 0 |
| compose | 0 | 0 | 0 | 0 | 0 |

For the M2 story (N = 29, 1 location-ish, E ≈ 3): text ≈ 40–50, vision ≈ 31, images ≈ 1 + 3 + 4 + 5 ≈ **13**,
video ≈ **29 clips, 161–189 s**. For a translated huohuo chapter-sized episode (N ≈ 80–120): text ≈ 100–140,
vision ≈ 85–125, images ≈ 30–40, video ≈ 6–10 min of clips.

### 7. Episodes: structured_v1 means one chapter = one episode, and "Chương" is not a chapter marker

- FACT (`task_backend/runners/graph_build.py:185-213`): for a `structured_v1` project (D13) episode building raises
  `KnowledgePipelineUnsupported("structured_v1 only supports deterministic chapter/episode mapping")` unless
  `planning_mode == "chapters"`; then `store.build_episodes_from_chapters` makes **one episode per chapter marker**
  (`sqlite_store.py:1799-1810`). The `EpisodePlannerAgent` (graph tools, conflict/cliffhanger/3–6 cast — the
  strength ADR-0170 §3 and the 2026-11-08 study §4 cite) runs **only on the graph track**, which D13 turns off.
- INFER: D13 + D23 ("episode length follows the story; DramaClaw's episode planner decides") are inconsistent — with
  D13 no planner decides; huohuo's chapter length decides. Either accept "episode = chapter" in the plan, or use the
  graph track (needs an embedding model: `COGNEE_EMBEDDING_MODEL=DC-cognee-embedding`, `.env.example:117`; the free
  registry has Alibaba `qwen3.7-text-embedding` 1M and BytePlus Skylark embedding 500k, both once-only).
- FACT (`cognee/chapter_detector.py:43-46`): chapter markers recognised are `第N章`, `第N集`, `Chapter N`,
  `Episode N`. Vietnamese `Chương N` is **not** recognised. Fix (connector text preparation, no donor change): write
  each translated chapter under an `Episode N` / `Chapter N` heading line.
- FACT (`huohuo …/common/novel/novel-meta.ts:18`): huohuo's default chapter target is **3,000 Chinese characters**.
  INFER: translated, ≈3,600–4,500 Vietnamese syllables ≈ **13–19 min** of narration per chapter at 4 syl/s, ≈ 100–200
  paragraph-beats. With "episode = chapter" one episode is a 15-minute film — far outside TikTok/YouTube Shorts forms
  (D17) and, below, far outside the video pool. **The connector must set huohuo's chapter target small** (e.g. 600–900
  Chinese chars ⇒ ~2–4 min episodes) — configuration of huohuo's `generate-remaining` length (band 500–20,000,
  `novel-writing.ts:1303`), and a product decision for the sponsor (episode length was "follow the story", D23).

### 8. Story stage (huohuo → translation) — what the text will be like

- FACT (ADR-0170 §1; 2026-11-08 study §2): huohuo writes Chinese prose with per-book memory, change records, length
  floor, continuity check with up to 30 rewrites (`novel-meta.ts:169-190`), genre skill folders (~18 genres).
- INFER: with ernie-5.5-flash (Chinese-native, best free writer in the registry probe) the Chinese prose quality is
  likely the strongest available on free tiers. Risk: `DEFAULT_CONTINUITY_REWRITE_MAX = 30` × (rewrite + audit) can burn
  a large share of the 1,000/day OpenRouter pool on one stuck chapter — set it low (configuration) for unattended runs.
- Calls per story (INFER): premise 1 + title 1 + brief 1 + outline 1–4 + per chapter (beat drafts 2–6 + polish 1 +
  continuity 1 + memory 1–2 + commercial/AI-tell audits 1–3 ≈ 6–13) ⇒ a 10-chapter story ≈ 70–140 calls nominal,
  hundreds in the worst case; translation (`lib/story_translation.py:46-47,172-195`: 4,000-char batches, ≤3 attempts)
  ≈ 1–2 calls per 3,000-char chapter, ×1–3 on retries.
- FACT (`lib/story_translation.py:113-115,122-145`): translation keeps paragraph count 1:1, keeps protected names
  verbatim, rejects any CJK in the output, and checks a length band. INFER: GOAL's "no Chinese left" is enforced per
  batch; "natural Vietnamese" is not checked by anything (only the sponsor's reading).
- INFER: dialogue stays inside prose paragraphs (`"…," cô gái nói.`) — fine for a story, wrong shape for DramaClaw's
  drama spine (§1) and for per-character voices (§2).

### 9. Voices

- FACT (`audio/indextts2_beat_audio_task.py:205-260,323,487`): narration beats use the project narrator reference
  audio; dialogue beats use the speaker's reference audio (per age group: `voice_samples_by_age_group`, :234). Missing
  voices are listed as prerequisite errors (`collect_indextts2_voice_prereq_errors`, :409).
- FACT (`generators/indextts2_fal.py:315-360`): the fal body is `{audio_url, prompt, should_use_prompt_for_emotion:
  true, emotion_prompt?}`; the response must carry an audio URL. The plan's adapter contract matches.
- FACT (`docs/research/2026-11-13-video-quality-donor-mechanisms.md:110`): VieNeu v3 Turbo has ~25 presets over
  North/Central/South; `style` "has no effect". INFER: **no emotion** — IndexTTS2's emotion control is dropped; every
  line is read in the preset's neutral delivery (same as the old app). Distinct presets per character are possible for
  casts ≤ ~10 per gender/region; the shim's own OpenAI-id map has only one female voice (`Trúc Ly`,
  `vieneu-tts-shim/server.py:24-38`) — the connector must cast from the full `/health` list, not that map.
- INFER: in `narrated` mode most beats are narration (one narrator voice); character voices appear only on beats the
  LLM labels dialogue, and then speak the whole paragraph including the attribution (§2). The GOAL wording "Vietnamese
  voices" is met; "a drama with characters speaking" is only partly met.

### 10. Images: Seedream through DramaClaw's gpt-image-2-shaped calls

- FACT (`config.py:903-907,944-955`): sketches and first frames default to selection `newapi_gpt_image2` → model
  `LingShan-G2`; character/identity images default to `CHARACTER_IMAGE_MODEL = "nanobanana"` → `LingShan-NB-2`
  (`config.py:549`, alias table `:961-968`; `generators/image_generator.py:1374-1420`). So D7's two mappings carry
  everything: G2 → Seedream 4.5; NB-2 → Gemini image "if the free tier answers" (registry: free-tier image models
  "not tested", `cloud-free-quota-registry.md:93-95`) else Seedream — INFER: in practice **all images hit the one
  200-image pool**.
- FACT (`nanobanana_grid.py:1-10,1464`, `build_regen_plan` `:2592-2640`): sketches are 3x3 grids (`ceil(N/9)`), first
  frames are location grids from `LOCATION_POOL_TEMPLATE = ["2x4_4-3","2x3_1-1","2x2_2-3","1x2_4-3","1x1_2-3"]`, then
  split into cells. INFER: each first frame is a cell of a ≤4K grid (≈ 500–900 px on the long side for 8-cell grids),
  later fed to Seedance as a 720p first frame → softer than a native 720x1280 frame; and whether Seedream 4.5 draws a
  clean 2x4 grid that DramaClaw's splitter can cut is **UNKNOWN** — DramaClaw tunes these prompts for GPT Image 2 /
  Nano Banana (module docstring). Must be in the M1.0 probe (one real sketch grid + one render grid through Seedream).
- FACT (`nanobanana_grid.py:92-95,565-680`, sketch modes `:1047-1083` use `"1K"`): DramaClaw sizes requests for GPT
  Image 2 (min 655,360 px; "1K" ≈ 1024 long edge) and sends `quality` for `LingShan-G2` (`:520-528`, sketch quality
  `low`, `config.py:899-900`). [D, from memory of BytePlus docs, not verified here] Seedream 4.5 requires a much larger
  minimum pixel count (around 2560x1440) → 1K sketch calls may be **rejected 400** by Ark; Seedream 4.0 accepts smaller
  sizes. Probe; fallback is configuration (map G2 sketches to Seedream 4.0, which also adds its own 200-image pool).

### 11. Quota arithmetic

Assumptions, labelled: Seedance tokens per second of 720x1280 video — **21,600** by the BytePlus formula
w×h×fps×s/1024 at 24 fps [D, memory, unverified], or **60,000** by the old app's own estimate constant
(`lib/cost_calculator.py:24-26`). 480p (480x864): ≈ 9,720/s by the same formula. Speech 4 syl/s.

**Per episode**

| Episode shape | Beats N | Clip seconds | Seedance tokens @720p | @480p | Seedream images | Text calls | Vision calls |
|---|---|---|---|---|---|---|---|
| M2 story (29 paragraphs) | 29 | 161–189 | 3.5–4.1M (formula) / 9.7–11.3M (old constant) | 1.6–1.8M | ~13 (+redo) | ~40–50 | ~31 |
| Same story split per sentence | ~60 | ~165–175 | same seconds ⇒ same tokens (min 2 s/clip adds a little) | ~1.7M | ~20 | ~75 | ~63 |
| huohuo default chapter (3,000 zh chars) | 100–200 | 780–1,140 | 17–25M / 47–68M | 7.6–11M | 30–50 | 120–230 | 105–210 |
| huohuo short chapter (≈700 zh chars) | 25–45 | 180–270 | 3.9–5.8M / 11–16M | 1.7–2.6M | 12–18 | 40–60 | 27–47 |

**Per pool**

| Pool | Size | Kind | What it buys | Verdict |
|---|---|---|---|---|
| Seedance 1.0 pro-fast | 2M tokens | **once per account** | 33–93 s of 720p video *in total, forever*; ≈ 206 s at 480p | **cannot finish even the M2 episode at 720p**; at 480p roughly one M2 episode and the pool is gone |
| Seedance 1.0 pro, 1.5 pro | 2M each | once | another ~1–2 M2 episodes at 480p if mapped as extra channels (1.0 pro: same token rule; 1.5 pro not activated, registry :164) | stop-gap only |
| Seedream 4.5 | 200 images | once | ≈ 15 M2-size episodes, ≈ 5 chapter-size episodes; any redo costs more | runs out within the first week of D19 volume |
| Seedream 4.0 | 200 images | once | doubles the image budget if mapped (not in the plan) | add as second channel |
| OpenRouter `:free` | 1,000 req/day, 20/min, **shared with production ArcReel** | daily | ≈ 10–20 M2-size episodes of DramaClaw text, *or* one 10-chapter huohuo story + translation + a few episodes | adequate for 1 series/day; not "many series overnight" |
| Gemini AI Studio | 20/model/day, shared with production reviewers | daily | the per-beat optimizer needs N per episode ⇒ < 1 episode/day per model; ≈ 3 short episodes/day if 5 Flash models are spread as channels | **daily bottleneck after video** |
| VieNeu (local) | GPU time | unlimited | all TTS | fine; shares the GPU with ComfyUI fallbacks |

INFER, headline: on free pools the assembly can produce **at most one short episode with real generated video**, and
then has no video model. Everything after that depends on the local fallback (plan §6: NewAPI ComfyUI channel with the
local Wan workflow) or money. D19 ("many series in parallel overnight") is not reachable on free cloud pools at all;
it is reachable only with a local video path whose throughput (GPU minutes per clip) was not measured in any document
read for this round (UNKNOWN).

### 12. The plan's video fallback does not exist on the API path

- FACT: `KenBurnsEffect` / `VideoComposer` live in `generators/video_composer.py:63-121` and are used only by the legacy
  CLI (`cli.py:400`) — not by the API pipeline, whose video step needs one MP4 per beat
  (`api/routes/pipeline.py:189-191` `_beat_file_series_complete(... "mp4", beats)`) and whose compose runner simply
  **skips** a beat that has no video (`runners/video.py:510-512`).
- INFER: plan §6 row "BytePlus video pool exhausted → DramaClaw's still/Ken Burns path if its video step allows it"
  has no target. The real choices are (a) the NewAPI ComfyUI video channel (type 63, video-only, verification round §1)
  in front of a local Wan i2v workflow, or (b) a small **still-clip adapter** at the model boundary: an endpoint that
  NewAPI's channel calls and that returns a Ken Burns MP4 made from the first frame (the old app's "still-clip"
  backend, registry :27) — GOAL rule 2 allows "small adapters at a donor's model boundary". Either must exist before
  M2, because §11 shows the cloud pool ends inside the first episode.

### 13. Step table — premise to compose (what each output will be)

| # | Step (who) | Model | Output language / form | Expected quality | Main risk |
|---|---|---|---|---|---|
| 1 | Premise (huohuo `generate-premise`, genre skill) | ernie free | Chinese premise; `setting=vn` keywords add Vietnam | good (Chinese-native) | none significant |
| 2 | Outline + chapters (huohuo) | ernie free | Chinese prose, default 3,000 chars/chapter, memory + change records | best free prose available | chapter length ⇒ 15-min episodes; 30-rewrite loop burns quota |
| 3 | Translation (ours, `lib/story_translation.py`) | ernie free (D5) | Vietnamese prose, paragraphs 1:1, Hán-Việt names from glossary, no CJK | readable; "natural" unverified | dialogue stays embedded in prose |
| 4 | Ingest (DramaClaw) | — | — | — | **`drama` spine refuses prose (§1)**; `Chương N` not a chapter marker (§7) |
| 5 | Configure (connector) | — | ethnicity Vietnamese, third person; must also set aspect 9:16 for `narrated` | — | narrated defaults to 16:9 |
| 6 | Characters (structured extraction) | ernie | names verbatim (Vietnamese); descriptions **in Chinese** (`source_language` → zh) | evidence-checked, conservative | aliases ("ông", "bác", "cô gái") split/merge |
| 7 | Episodes | — (structured_v1) | one episode per chapter | deterministic | no AI planner (§7) |
| 8 | Portraits | Seedream (via NB-2/G2) | 1 image, main character only | good | — |
| 9 | Identity plan / images | ernie; Seedream | identity rows in Chinese; one image per identity *if the connector asks for every identity* | likely better than the old app (multi-reference) | secondary characters skipped if `next_step` is trusted (§5) |
| 10 | Script (literal, one call per paragraph) | ernie | beat narration = the Vietnamese paragraph; `visual_description` in Chinese with `{{identity}}` markers | faithful text | dialogue beats speak the attribution; paragraph-long beats |
| 11 | Sketches (3x3) | Seedream | grid images | UNKNOWN on Seedream | 1K size may be refused; grid adherence |
| 12 | Coloring / detection | vision (Gemini) | identity markers per beat | ok | Gemini 20/day |
| 13 | Global optimize (per beat, with image) | vision slot | Chinese motion prompts | ok if the slot works | **N vision calls per episode; quota stall** (§6) |
| 14 | First frames (location grids) | Seedream | grid cells → frames | consistent within a grid | low per-cell resolution |
| 15 | TTS | VieNeu via our fal adapter | Vietnamese speech, narrator + cast presets, no emotion | same as old app | sample-hash mapping through Cloudinary |
| 16 | Video (first_frame i2v) | Seedance 1.0 pro-fast 720p | 2–12 s clip per beat, no audio | good motion | **pool ends inside episode 1** (§11) |
| 17 | Compose | ffmpeg | 720x1280 MP4, H.264 CRF 23, AAC 128k, speech cut at clip end, no captions, no music, no loudness | below old app finish | SRT only in export bundle |
| 18 | Finish post-stage (ours, M4) | old app units | -14 LUFS, music bed, ambience, burned captions from SRT | parity with old app | must always run, not "if missing" |

### 14. Against GOAL's bar and the old app's films

| Criterion | GOAL / old app (b961dc0a) | Assembly as planned (INFER from the above) |
|---|---|---|
| No human step | old app: needed many fixes but ran | blocked at ingest under D26 default; after switching to `narrated` and chapter headings: plausible |
| Vietnamese voices | yes, VieNeu, 3 lines | yes, VieNeu; many more lines; narrator-dominant; attribution read aloud |
| Characters consistent | failed (Vy drift, glasses) | better for characters with identity images; equal or worse for those without |
| Length | 28.2 s | 2.5–3 min for the M2 story; 13–19 min for a default huohuo chapter |
| Picture | 576x1024 stills/clips | 720x1280 Seedance motion (while the pool lasts); then whatever the local fallback gives |
| Subtitles | burned, title card | none burned; SRT only |
| Music / loudness | music bed + ambience, -14 LUFS | none, unnormalised, until M4 |
| Both reviewers accept | REWORK | unknown; length + dead-air rules of the old reviewers will see long narration and cut speech |

INFER: the assembly is a clear improvement in identity handling and motion **for the first ~90 s of video it can
afford**, and a regression in finish until M4. It will not reach GOAL's drama bar as "characters speak their lines"
without a prose→screenplay step, which no chosen donor stage provides in DramaClaw's header format.

### 15. Executed check: which screenplay headers DramaClaw accepts (pure function, no services)

Ran DramaClaw's own `assess_screenplay_scene_headers` from the pinned checkout (`python3 -I`, import only, no network):

| Input first line | Result |
|---|---|
| huohuo `drama_script_formatter` format `## S01 \| 内景 · 便利店收银台 \| 深夜` (`huohuo …/agent-skills/drama_script_formatter/SKILL.md:40,47,61`) | **missing** (0 headers) |
| `INT. TIỆM SỬA ĐỒNG HỒ - DAY` + `Khang: Đặt lên quầy đi cháu.` | **standard** (1/1) |
| `Chương 1` + Vietnamese prose | **missing** |

- FACT (above + `huohuo …/services/drama/drama-episode-pipeline.ts:401`): huohuo does have a donor unit that turns
  novel text into a scene-headed screenplay (`drama_script_formatter`, 9:16 short-drama constraints, dialogue on its own
  lines, "+20–30 % length"), but its header shape is not one DramaClaw parses.
- INFER — the cheapest whole-donor route to a real drama: run huohuo's `drama_script_formatter` on each Chinese chapter
  (donor unit, whole), translate the lines (ours), and have the connector rewrite only the header line
  `## Sxx | 内景/外景 · <地点> | <时段>` → `INT./EXT. <địa điểm> - DAY/NIGHT/…` (deterministic text mapping in the
  connector; time tokens map to DramaClaw's `ENGLISH_TIME_TOKENS`, `screenplay_scene_parser.py:38-45`), keeping
  `Tên: lời thoại` lines that `DIALOGUE_RE` (`literal_script_writing.py:39`) splits correctly. Then `spine=drama`
  works, dialogue beats speak only the line, silence beats exist, scenes/scene masters are built. Not verified end to
  end; whether huohuo exposes the formatter through its API outside `runDramaEpisodePipeline` is UNKNOWN.
- Could not run `detect_asset_language` (`langid` not installed outside DramaClaw's container); §5 stays INFER from code.

## Expected shortfalls and fixes (ranked)

| # | Shortfall | Severity | Evidence | Fix (kind) |
|---|---|---|---|---|
| S1 | Seedance free pool (2M tokens, once) buys ~33–93 s of 720p video in total; the M2 episode needs 161–189 s | **Blocker for M2 as written** | §11; registry :156; `lib/cost_calculator.py:26` | Before M2: (a) build the local video path first (NewAPI ComfyUI channel → local Wan i2v, or a still-clip adapter at the model boundary) and make it the default; keep Seedance for a 480p showcase episode (**config** `NEWAPI_VIDEO_RESOLUTION=480p` + **adapter**); (b) or **money** — sponsor decision D20 with a per-episode cost figure (measure real `usage.total_tokens` on the first Seedance call in M1.0) |
| S2 | `spine=drama` (D26 default) refuses prose; huohuo and the M2 story are prose | **Blocker** | §1, §15 | Short term **config**: `narrated` + aspect 9:16 + resolution `720x1280` passed to compose. Proper: huohuo `drama_script_formatter` (whole donor unit) + header rewrite in the connector (§15) |
| S3 | Plan's video fallback (DramaClaw Ken Burns) does not exist on the API path | High | §12 | Replace the §6 row with S1(a) |
| S4 | Per-beat vision optimizer vs Gemini 20/model/day; D5/D6 ambiguous for image-carrying `DC-*-LLM` slots | High | §6 | **Config**: name the vision slots explicitly in `ASSEMBLY_MODELS.md`; spread over several Gemini Flash models as separate channels; probe ernie-with-image and Groq `qwen3.8-27b` (1 image) as fallback; drop nemotron-vl (bad JSON) |
| S5 | Episode = chapter (structured_v1), huohuo chapter default 3,000 zh chars ⇒ 13–19-min episodes | High (product) | §7 | **Config** huohuo chapter target ~600–900 chars for short-form series; sponsor confirms episode length (replaces D23 wording); or graph track with an embedding model (once-only pools) |
| S6 | `Chương N` not a chapter marker | High (silent: whole story one episode or windowed) | §7 | **Connector**: emit `Chapter N` heading lines |
| S7 | Speech longer than 12 s is cut by `-shortest` | Medium | §3 | **Connector** text prep: one sentence per line in narrated mode (shorter beats); with S2's screenplay route lines are short anyway |
| S8 | Dialogue in prose: character voice reads attribution or narrator reads lines | Medium (drama bar) | §2 | S2 proper fix |
| S9 | No burned subtitles, no music, no loudness in DramaClaw's compose | Medium (parity) | §4 | **Post-stage** M4 finish: always burn captions from DramaClaw's SRT, -14 LUFS, music bed; make M4 part of the first accepted film, not later |
| S10 | Secondary characters may get no identity images if `next_step` is trusted | Medium (consistency) | §5 | **Connector**: generate identity images for every identity in the episode's `identity_ids`, verify files before sketches |
| S11 | All images on one 200-image Seedream 4.5 pool; 1K sketch sizes may be refused by 4.5; grid adherence unknown | Medium | §10 | **Config**: map sketches to Seedream 4.0 (second 200 pool, smaller sizes), renders to 4.5; M1.0 probes one sketch grid and one render grid |
| S12 | Asset prose (descriptions, prompts) in Chinese because `source_language` is zh/en only | Low for pictures, Medium for the Vietnamese operator | §5 | Accept (pictures fine); a donor change to add `vi` is a GOAL tolerance item — not worth it now |
| S13 | Free daily pools shared with production ArcReel (OpenRouter 1,000, Gemini 20/model) | Medium | §6 | Operations: schedule assembly runs when production idles, or give the assembly its own keys (sponsor action) |
| S14 | No emotion in voices (VieNeu style ignored) | Low (same as old app) | §9 | Accept; later a voice model with emotion via the same fal adapter |
| S15 | huohuo 30-rewrite continuity loop can drain the daily text pool | Low–Medium | §8 | **Config**: lower `continuityRewriteMax` for unattended runs |

### Corrections this round asks of the plan (for the reconciler)

1. D26: default `narrated` until the screenplay route (S2) exists; set aspect and compose resolution explicitly.
2. D13 vs D23: state "episode = chapter" and choose huohuo's chapter target per form.
3. §6 video fallback: replace "Ken Burns" with the local video channel/adapter, and **move it before M2**.
4. M1.0 probes: add Seedream at 1K and as a 3x3 grid, Seedance real token usage at 480p/720p, vision with structured
   output for each candidate vision model.
5. M4 finish is required for parity; caption branch always fires.
6. Connector text preparation (chapter headings, sentence-per-line or screenplay headers) is a real task with a code
   budget; it is not in M2's ≤600 lines estimate.

## Coverage limits of this round

- Not run: any service, any model call, DramaClaw's container. One pure donor function was executed locally (§15).
- Not read in depth: huohuo chapter drafting call counts (estimated), DramaClaw props reference-image generation,
  whether `ethnicity` reaches image prompts, OpenMontage (out of scope for the drama path).
- Seedance and Seedream numeric limits marked [D, memory] must be re-checked against BytePlus docs or a probe.
