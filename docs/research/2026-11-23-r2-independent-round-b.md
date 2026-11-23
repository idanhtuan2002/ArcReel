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

