# Donor stage mechanisms: how each donor implements each production stage

Date: 2026-11-08. Read-only research; no donor code was run, no service was touched. Labels: **FACT** = read in source at
the pinned commit (file:line); **INFER** = my reading of what a fact implies; **UNKNOWN** = not found or not read, with
the files searched. Stage 9 (quality) builds on
[2026-11-08-r2-best-of-n-and-judge-retry-donors.md](2026-11-08-r2-best-of-n-and-judge-retry-donors.md) and is not redone.
Licensing is out of scope (project policy).

Pins and short names (paths below are relative to each checkout):

| Short | Checkout | Commit |
|---|---|---|
| HUO | `/home/anhtuan/content-os-r1-8/work/huohuo-drama` (code in `workbench-server/src/`, skills in `agent-skills/`) | f104b85 |
| OM | `/home/anhtuan/content-os-r1-8/work/OpenMontage` | 08e2151 |
| TAKE | `/home/anhtuan/content-os-r1-8/work/take` | 47c1721 |
| DC | `/home/anhtuan/.cache/r2-donors/dramaclaw-full` (code in `src/novelvideo/`) | b299bfd |
| VIMAX | `/home/anhtuan/ViMax` | 63bb9c7 |
| GitHub-only | shenbi, ai-short-film (ASF), butterfly-director-ai (BUT), Jellyfish (JF, a9678194) read via `gh api` at HEAD (JF at the pinned sha); shallow reads only | HEAD at 2026-11-08 |

Scope of what is not claimed: GitHub-only donors were read shallowly (a few files each); statements about them are limited
to the files cited. TAKE is a thin storyboard/render toolkit (no story, no audio, no compose); OM is a skills-driven agent
framework; HUO and DC are the two full novel-to-video platforms; VIMAX is a research-style pipeline.

---

## 1. Automation level and runtime/cost per donor (summary first)

| Donor | Automation | Measured/documented time or cost |
|---|---|---|
| HUO | **FACT** one-call batch per episode `runDramaEpisodePipeline` (`services/drama/drama-episode-pipeline.ts:312-671`) runs raw, rewrite, extract, voice, storyboards, char/scene/shot images, dubbing, videos or slideshow, compose, merge with no human gate in the body; only `checkStop(shouldStop)` between steps (e.g. lines 336, 372, 389) and a credits check `assertUserCanGenerate`. Novel side also batch (README.md:22). | **UNKNOWN**: README.md has no time or per-video cost (grep for cost/minute/耗时 empty); the product is credit-billed (README table). Media waits poll up to 120 x 3 s image and 120 x 4 s video (lines 135, 148). |
| OM | **FACT** `human_approval_default: true` on proposal, script, scene_plan, assets stages (`pipeline_defs/cinematic.yaml:90,128,152,197`); storyboard is "a real approval gate" (README.md:164). Mid-pipeline automation is possible only by overriding gates. | **FACT** README examples: "THE LAST BANANA" 60 s, 6 Kling clips, total **$1.33** (README.md:87); 50 s film about **$4** (:99); showcase source generation about **$5** (:111). **FACT** manifest budget defaults and wall-time caps: cinematic `budget_default_usd: 2.00`, `max_wall_time_minutes: 12` (`cinematic.yaml:27,30`); documentary 60 min (`documentary-montage.yaml:24`); character-animation 20 min (`character-animation.yaml:51`). Caps are configuration, not measurements. Global budget default $10, per-action approval above $0.50 (README.md:686-689). |
| TAKE | **FACT** agent-in-the-loop: agent writes `shots.json`, then `take generate images/video` is batch with `--resume -c 4` (README.md quick start). Shot `status` enum includes draft/approved (`generateImages` filters `approved` or `draft`, `packages/provider/src/orchestration.ts:~113`). | **UNKNOWN**: no time or cost data in README, `docs/models.md`, `docs/workflow.md`. |
| DC | **FACT** mixed: pipeline stages are separate APIs, "run them in sequence, skip steps, or resume from any checkpoint" (`docs/en/concepts/architecture.md`, Processing Flow); in-process task backend with resume and cancel; render preflight demands identity detection or manual labelling per beat (`generators/render_identity_guard.py:1-38`). | **UNKNOWN**: no time/cost in `docs/en/concepts/*.md`, `docs/en/reference/environment-variables.md` (billing is a port, CE cost = 0, architecture.md "CreditQuote"). |
| VIMAX | **FACT** `Idea2VideoPipeline.__call__` runs story, characters, portraits, script, then script2video end to end without a human step (`pipelines/idea2video_pipeline.py:295-340`); `agent_runtime/` adds an LLM tool loop on top (not read in depth). | **UNKNOWN**: readme.md has no cost/runtime numbers (grep `cost|minutes|hours` empty). |
| shenbi | **FACT** checkpointed: `just pipeline-resume` runs to the next checkpoint; checkpoints are approved by a human with `just pipeline-review ... approve`; the wrapper script never auto-approves (README.md, "Pipeline 运行"). | **UNKNOWN** per chapter; a token/cost accounting plan exists (`docs/superpowers/plans/archive/2026-07-19-03-pipeline-cost-and-token-accounting-plan.md`) but no measured number was read. |
| ASF | **FACT** "Human-in-the-loop - assets and storyboards go through a review step before video generation proceeds" (README.md, design principles). | **UNKNOWN**. |
| BUT | **INFER** fully asynchronous Celery jobs per step (ARCHITECTURE.md section 0 pillar 3); human gate not read. | **UNKNOWN**. |
| JF | gate on inputs only (see best-of-n doc 3.4). | **UNKNOWN**. |

**INFER:** only OM publishes real cost per finished video, and its figures are for 50-60 s hybrid films made mostly from
5-6 generated clips; none of the five local donors publishes a measured end-to-end wall-clock for an episode. ArcReel
should measure its own.

---

## 2. Stage 1: IDEA to STORY (idea, brief, long-form story)

### HUO (the only donor with a true long-form novel engine)

- **FACT premise, title, brief, outline are separate calls.** `generateNovelPremise` (`services/novel/novel-writing.ts:137-171`,
  temperature 0.78, 2048 tokens), `generateNovelTitle` (:199), `generateNovelWritingBrief` (:231), `generateNovelOutline` (:546).
  Genre skills are loaded per genre from `agent-skills/novel_premise|novel_writing_brief|novel_outline/<genre>/` (about 18 genres).
- **FACT outline length control.** Up to `OUTLINE_PHASED_THRESHOLD = 30` chapters: one shot (`generateNovelOutlineSingleShot`,
  :555-559, max tokens 16384 via :321). Above 30: a skeleton call, then one call per volume chunk
  (`generateVolumeChapterSummaries`), a gap-patch call when chapters are missing in the chunk (:586-603), then up to 3 more
  tail-patch rounds (`guard < 3`, :619-642), then `ensureOutlineBookDramaFields`. **INFER:** call count is about
  1 + volumes + patches; the design assumes the model drops chapters and repairs by listing missing numbers.
- **FACT chapter drafting.** `generateNovelChapterFull` (:1272) either goes beat-sequential when the outline has 2+ beats
  (`shouldUseBeatSequentialGenerate`, `novel-chapter-beat-generate.ts:421`, per-beat char budgets in
  `novel-chapter-beat-budget.ts:130`), or does one draft call plus a polish call (:1340-1349). Length target is clamped
  500-20000 chars (:1303).
- **FACT length gates.** `assertNovelChapterLengthBand` throws when `n < 0.97 x minLen` (`common/novel/novel-char-limit.ts:11-35`);
  `enforceAssembledLengthFloor` rejects a polish that shrinks the draft below `max(0.75 x minLen, 0.85 x assembled)` and
  reverts to the draft (:42-60, used at novel-writing.ts:1352-1360).
- **FACT continuity memory.** Per-novel files `world_bible.md`, `character_sheets.md`, `plot_ledger.md`, `causal_chain.md`
  (`services/novel/novel-memory/novel-memory-paths.ts:15-19`) updated after each chapter by `applyNovelMemoryFromChapter`
  (imported at `novel-chapter-pipeline.ts:9`); every chapter ends with a **Change Record** (trigger, process, outcome) that
  is stored and audited (README.md:22). Seam handling between chapters strips replayed openings (`novel-chapter-seam.ts`,
  called at novel-writing.ts:1286-1304).
- **FACT review and rewrite loop.** After drafting, a continuity check runs; while `strictContinuity && !passed` it patches or
  regenerates (`novel-chapter-pipeline.ts:795-815`); default `DEFAULT_CONTINUITY_REWRITE_MAX = 30` rewrites, stagnation
  streak 5, min score 78 (`common/novel/novel-meta.ts:169-190`); parse failure of the model audit aborts instead of looping
  (`novel-chapter-pipeline.ts:797-799`); max attempts aborts the chapter (:801). Deterministic prechecks, outline-boundary
  audit, AI-tell stripping, humanize hook and commercial-appeal audit exist as separate files under `services/novel/`.
- **INFER:** most valuable for ArcReel: file-based per-book memory plus chapter-end structured change record, length band
  with a floor against shortening edits, stagnation-based abort, and parse-failure-abort. Weak spot: 30 rewrite default is
  a large worst-case call budget (each rewrite plus audit is two or more calls).

### shenbi (GitHub-only, novel framework)

- **FACT** 7 phases: Genesis, Architecture, Planning, Drafting, Audit, Foundation, Management (`docs/getting-started/first-novel.md`);
  planning generates a chapter memo `plans/chapter-N-plan.md` and plants hooks into `truth/pending_hooks.md`; drafting
  chains drafting, state-settling, foreshadowing-track, style-polishing, review-resonance, anti-detect, length-normalizing;
  18 review skills audit finished chapters (continuity, character, pacing, world rules, AI traces, foreshadowing...).
  Truth files are 15 kinds, state is updated by `shenbi-state-settling` (`docs/getting-started/concepts.md`).
- **FACT** the 0-100, 94-advance, 100-converge scoring and G0-G7 gates (concepts.md) are for testing the *skills*, not for
  grading a produced chapter at runtime (concepts.md lines 65-71 describe T1/T2/T3 tests). **INFER:** do not treat them as
  a runtime quality loop to copy.
- **UNKNOWN** model calls per chapter: not read (cost plan file only).

### VIMAX (short story only)

- **FACT** `Screenwriter.develop_story(idea, user_requirement)` is a single call (`pipelines/idea2video_pipeline.py:193-211`);
  prompt `agents/screenwriter.py:20-70` requests title, audience, 100-200 word summary, characters, narrative, optionally
  split into N scenes; length is a free-text requirement ("5 key scenes", "10-minute short film"). No outline stage, no
  review, no retry beyond tenacity on other agents. **INFER:** unsuitable as a long-form donor.
- **FACT** novel input is compressed rather than written: chunks of 65536 chars with 8192 overlap
  (`agents/novel_compressor.py:86-87`), compressed chunk by chunk with `Semaphore(5)` (`pipelines/novel2movie_pipeline.py:111`),
  then sequential event extraction until `is_last`, capped by `MAX_EXTRACTED_EVENTS = 50` (:142-143, :1001).

### DC, OM, TAKE, HUO-video-side

- **FACT** DC starts from an imported novel, not an idea (`cli.py:115 import_novel`); no idea-to-novel writer found in
  `src/novelvideo/{agents,workflows,cli.py}` (listed above). TAKE starts from `script.md` (README.md). OM's cinematic
  idea-director/research-director/proposal-director produce briefs and 2-3 differentiated concepts, not stories
  (README.md:139; `skills/pipelines/cinematic/idea-director.md`). HUO also has `generateEpisodeRawContent` for a short
  drama episode (about 800-2500 characters) from a one-line idea (`services/drama/episode-raw-content.ts:~25-40`).
- **UNKNOWN** GitHub-only ASF/BUT/JF idea-to-story: BUT has `story_architect` and `decision_detector` agents
  (agent dir listing) but I did not read them.

---

## 3. Stage 2: ASSET_ANALYSIS (characters, scenes, props; reference sheets)

- **DC (strongest extraction design).** **FACT** `structured_extraction.py` module docstring (lines 1-22): the model reports
  only what a span supports; every candidate must quote the span; a quote not verbatim in the chunk is dropped
  (`verify_evidence`, :285-300) and a name the source never writes is dropped (:489-512); merging is conservative because a
  name is also a SQLite key and an asset directory (docstring). Output schema `CharacterEvidence/CharacterCandidate/
  ChunkCharacterOutput` (:90-107), adjudication of same-person groups `SamePersonGroup/CharacterAdjudication` (:727-735),
  appearance generation `CharacterAppearance` (:954-967), scenes `SameLocationGroup/SceneAdjudication` (:1480-1488),
  props in `structured_builders.py:562`. Chunking: scene headings for screenplays, chapter markers for prose, fall back to
  windows; oversize chunks split and tiny ones packed (`story_analysis.py:62-91`). Concurrency via `map_bounded`.
  **FACT** identity layer: one character can have multiple identities (e.g. emperor/monk) each with `reference_images`,
  `face_prompt`, `portrait_image`, `costume_image` (`models.py:960-1046`); `IdentityPlanner` runs Pass A (default identity)
  and Pass B (other identities) per episode (`agents/identity_planner.py:1-12`). **INFER:** the quote-must-be-verbatim guard
  is a cheap anti-hallucination filter ArcReel can apply to any extraction.
- **HUO.** **FACT** an agent (`drama_cast_scene_extract`, max 20 tool steps `drama-episode-pipeline.ts:174`, retried up to 3
  times only on transient network errors :167-188) calls `save_dedup_characters`, `save_dedup_character_forms`,
  `save_dedup_props`, `save_dedup_scenes` which upsert and merge against the project cast (`agent-skills/drama_cast_scene_extract/SKILL.md`
  tool flow and field table). Appearance must be 200-500 Chinese characters and follow the project `visual_style_brief`;
  named animals become their own characters; forms (transformation/costume) are separate rows with a base character.
  **FACT** reference sheet prompt: `character-reference-sheet-prompt.ts` builds a fixed industrial layout (face hero closeup
  left third, front/back/profile/costume/material panels, white background) after an LLM refine pass that may append
  "visual anchors JSON" (face_shape, facial_features, unique_marks, color_anchors, skin_texture, hair_style) (lines 1-60).
  **FACT caveat:** the automatic episode pipeline does *not* use that builder; it generates each character image from the
  string `"${name}, ${appearance}, 高质量, 正面, 白色背景"` (`drama-episode-pipeline.ts:460`). **INFER:** the sheet builder is
  a manual-UI path; the automatic path is simpler and reference use downstream is: character image URLs go as
  `referenceImages` for scenes (first character only, `.slice(0,1)`, :484-504) and shots (up to 6 refs, :210-224).
- **VIMAX.** **FACT** `CharacterExtractor` (retry 3, `agents/character_extractor.py:73`) and `SceneExtractor` (retry 5,
  `scene_extractor.py:77`); portraits are front, then side and back derived from the *front* image as edit references
  (`pipelines/script2video_pipeline.py:709-770`, `idea2video_pipeline.py:232-292`); failures of side/back copy the front
  image instead of aborting (`idea2video_pipeline.py:257-270`). Each shot then picks references from this registry
  (stage 5). Multi-scene naming `identifier_in_scene` and `_scope_characters_to_scene` (:25) keep per-scene cast.
- **OM.** **FACT** only the character-animation pipeline has a design stage (`character-design-director`,
  `schemas/artifacts/character_design.schema.json` with `characters`, `style`) and a `character_qa_report` artifact with
  `status`, `checks`, `issues`, `recommended_action`. Other pipelines have no cast extraction (asset-director consumes the
  scene plan). **UNKNOWN** how the QA report is generated (not read).
- **TAKE.** **FACT** `Shot.characters: string[]` and `VisualReference.characterRefs: Record<name, url|token>`
  (`packages/core/src/models/types.ts:36-41,63`), authored by the agent; no extraction code (core is "Zero I/O, zero AI",
  README). **FACT negative:** generation never reads `characterRefs` (stage 5).
- **ASF.** **FACT** (workflow-spec.md:781) per stage asset gets a `look_lock` (hair/hairline, beard, clothing colour/style/
  material, collar/cuff/belt, accessories, injuries, props) and face/full-body/side images may change only framing and
  angle; parse orchestrator with `asset_registry_builder.py`, `continuity_seed_builder.py` (status default `needs_review`).
- **JF.** **FACT** agents: `element_extractor_agent` (entities + per-shot links, also emits camera defaults), `entity_merger_agent`,
  `costume_info_analysis`, `variant_analyzer`, `character_portrait_analysis` (agent listing); contents beyond the extractor
  prompt were not read.

---

## 4. Stage 3: EPISODE_PLAN and adaptation

- **DC (most complete).** **FACT** `EpisodePlannerAgent` uses graph-search tools (plot points, character arcs, relationship
  changes, timeline, story structure) in a documented 5-step procedure and outputs `EpisodePlan{number, title, chapter_start,
  chapter_end, content_summary 10-100 chars, main_conflict, cliffhanger, key_events 1-5, character_names}`
  (`agents/episode_planner.py:46-156`); guidance: 3-6 characters, 3-5 minute episodes, every episode ends on a hook.
  **FACT** `EpisodePlanReviewer` scores deterministic checks (chapter gaps/overlaps/out-of-range, valid character names,
  structure) plus LLM narrative checks; pass = `score >= 8.0` and no critical (`agents/episode_reviewer.py:24-50,87-97,256-292`);
  `EpisodePlanFixer` applies patches (`episode_fixer.py:217-380`). **FACT** only `EpisodePlannerAgent` is called from the task
  runner (`task_backend/runners/graph_build.py:188,224`); a repo-wide grep for `EpisodePlanReviewer|EpisodePlanFixer`
  outside `agents/` returned nothing, so reviewer and fixer are **not wired** in this checkout (searched `src/`).
  **FACT** script adaptation: `workflows/literal_script_writing.py` (literal) and `script_writing.py` produce `VisualBeat`s
  (`models.py:828-957`) with narration, visual description, speaker, `estimated_duration` (stored as `len(narration)/4.0`
  at `sqlite_store.py:2515`, i.e. 4 chars per second).
- **HUO.** **FACT** novel to drama: import chapters or an AI novel into a drama project (README.md:24); episode raw text is
  either imported or generated (`generateEpisodeRawContent`, episode-raw-content.ts), then `drama_script_formatter` rewrites
  to a formatted script with scene headers: keep main plot and ending, convert narration to visible action, compress
  narration, about 30-60 s per scene, no camera terms (SKILL.md, "核心目标" table). Cross-episode continuity block =
  previous episode tail + short earlier summaries + character roster (`buildGenerateContinuityBlocks`,
  episode-raw-content.ts:6-23). **UNKNOWN** how a novel is *split* into episodes in code (did not trace the import route;
  searched `services/drama/*.ts` names only).
- **VIMAX.** **FACT** novel2movie: compress, then sequential event extraction (max 50), then per-event scene extraction and
  script writing (`pipelines/novel2movie_pipeline.py:73-260`); idea2video: `write_script_based_on_story` returns scene
  scripts (`idea2video_pipeline.py:213-230`). No episode concept; one film.
- **OM, TAKE, ASF, JF.** **FACT** TAKE splits script into beats (5-15 beats for under 3 minutes, `skills/take/references/workflow.md`
  step 2) by the agent's own model. ASF has an `episode_builder.py` + `blueprint_planner.py` (parsing dir listing); JF has
  `script_divider_agent.py` ("full script text in, shot list out", docstring lines 1, 31). Details **UNKNOWN**.

---

## 5. Stage 4: SCRIPT and shot breakdown (shot grammar, narration vs dialogue, image prompts)

| Donor | Shot unit and grammar | Duration rule | Narration vs dialogue | Prompt writing |
|---|---|---|---|---|
| HUO | storyboard row with `shot_type`, `angle`, `movement`, `action`, `dialogue`, `result`, `atmosphere`, `bgm_prompt`, `sound_effect`, `scene_id`, `character_ids`, `image_prompt`, `video_prompt` (storyboard SKILL.md output contract) | **FACT** 10-15 s per shot, 4-12 shots for a 1-3 min episode; segments count = `ceil(duration/3)`; short-clip models (<=5 s) get shorter shots | `dialogue` field per shot; narrator is a character excluded from visual casting (`isNarratorCharacter`, pipeline :455) | `video_prompt` in 3-second segments with `<location>`, `<role>`, `<voice>`, `<n>` tags (SKILL.md template); `image_prompt` English; pipeline builds first/last frame prompts by joining title, image_prompt, shot_type, angle, location, action, atmosphere plus "首帧/尾帧" and "高质量，电影感" (`buildShotImagePrompt`, :194-209) |
| DC | `VisualBeat` (`models.py:828`): narration, visual description, `scene_ref`, `audio_type`, `speaker`, `video_mode` first_frame or keyframe (:892-900) | char-count estimate then audio probe | beats carry narration or dialogue (`DIALOGUE_RE` in `literal_script_writing.py`) | `KeyframePromptBuilder` (`agents/keyframe_prompt_builder.py:1-50`): prompts only for first/last frame pairs, 4-6 present-tense sentences, must include a camera move with displacement, bans static verbs, abstract emotion labels, character names (use visual features), reversing motion |
| VIMAX | `ShotBriefDescription` then `ShotDescription` with `ff_desc`, `lf_desc`, `motion_desc`, `audio_desc`, `variation_type` small/medium/large, camera tree (`interfaces/shot_description.py:1-160`; `storyboard_artist.py:110-112`) | **UNKNOWN** explicit (video tool duration 5 or 10 s, 8 s for Veo: `tools/video_generator_doubao_seedance_yunwu_api.py:36`, `..._veo_google_api.py:38`) | dialogue is written into `visual_desc` as `<NAME> says: "..."`; sound in `audio_desc` | `ReferenceImageSelector` selects up to 8 references and writes the frame prompt (best-of-n doc 3.1) |
| TAKE | `Shot` with `shotSize`, `angle`, `movement` from controlled enums, `durationSec`, `lighting`, `tone` (`types.ts:48-84`) | **FACT** 2-3 s for dense action, 5-8 s for emotional beats, avoid three same-size shots in a row (`skills/take/references/workflow.md` step 3); video prompts best at 5 s or less | none (visual only) | imagePrompt = subject+action, scene, camera language, light/tone, style closing; camera words mid-prompt, style words last (workflow.md step 4) |
| OM | `scene_plan` with a mandatory 5-aspect checklist per beat: subject, subject motion, scene, spatial framing, camera (`skills/pipelines/cinematic/scene-director.md`); `lib/shot_prompt_builder.py:1-50` compiles `shot_language` enums (shot size, movement, lens, lighting) into a 5-layer provider prompt (camera, movement, subject, lighting, style) and explicitly rejects a fixed prefix "which made all scenes look the same" | **FACT** script word budget = target seconds x 2.5 words/s, within +-10% (`skills/pipelines/animation/script-director.md:26,112`) | narration-led or text-led declared explicitly; TTS delivery cues from `voice-performance-director` | transitions vocabulary limited to hard cut, fade to black, slow dissolve, restrained push (scene-director.md) |
| JF | `element_extractor_agent` suggests `camera_shot` in {ECU, CU, MCU, MS, MLS, LS, ELS}, angle, movement, duration, action_beats (agent prompt lines 22-42); first/last/key-frame prompt agents take `camera_shot`, `duration`, `retry_guidance` (`shot_frame_prompt_agents.py:29-178`) | integer seconds | dialogue extracted with entities | has an explicit `retry_guidance` slot to feed a failure reason back into the prompt agent (**INFER:** reuse for ArcReel regenerate with feedback) |
| ASF | `shot_prompt_agent.py` `ShotPromptInput` fields: target model, segment code/function, shot function, `transition_type`, duration split `seg1/seg2`, continuity context, voice profiles, dialogue + performance, reference image block, asset contract | `duration` default 5 | dialogue text + performance direction | prompt tailored per target model ("seedance-2.0" default) |

- **Negative prompts and consistency tokens.** **FACT** HUO: matches for `negative` exist only in `services/ai/adapters/ali-image-helpers.ts`,
  `ali-video.ts`, `services/drama/grid-workflow.ts`, `common/media/video-gen-options.ts` and DB schema files (grep over
  `workbench-server/src`); i.e. not part of the main shot prompt path. **FACT** DC: style presets carry `avoid_instructions`
  merged into `negative_prompt`, and Seedream sketch mode disables negative prompts entirely (`generators/image_generator.py:376-382,525-529`).
  OM/TAKE/VIMAX: no negative-prompt mechanism found (searched `lib/shot_prompt_builder.py`, `packages/provider/src`,
  `agents/*.py`). Consistency tokens: HUO's `visual anchors JSON` (stage 2) and `character_tag` in DC `CharacterIdentity`
  (`models.py:976`); **UNKNOWN** how `character_tag` is injected (not traced).
- **INFER:** HUO's "3-second segment" video prompt with a deterministic segment count and DC's keyframe-transition prompt
  rules (camera displacement required; no names, no abstract emotion) are the two concrete, testable prompt contracts here.

---

## 6. Stage 5: STORYBOARD images (consistency, candidates, selection)

- **HUO.** **FACT** per shot: first and last frame images (AI-video path) or `ceil(duration/3)` min 2 keyframes (slideshow
  path, `common/drama/storyboard-frame-meta.ts:162-165`), each by one `generateImage` with up to 6 reference images
  = characters of that shot, the scene image, and the shot's own first/last frame
  (`collectShotReferenceImages`, `drama-episode-pipeline.ts:207-224`); style reference is applied by
  `applyStyleReferenceToImageGeneration`. No candidates: one image per request, waiting loop only (:128-140). **FACT** a "grid"
  path (`services/drama/grid-workflow.ts:401,490,550`, `grid-split.ts`) generates multi-panel images and splits them
  (manual UI). **INFER:** consistency = reference images only; no verification.
- **DC (richest).** **FACT** storyboard sketches via a 3x3 grid per call, `ceil(N/9)` grids per episode, then
  `grid_splitter` and Seedream image-to-image HD repair (`generators/nanobanana_grid.py:1-14`); character colour markers in
  sketches enable colour-based identity detection (`verification/sketch_*`, `render_identity_guard.py`); identity reference
  with explicit "identity locking" prompt rule: reference is an identity anchor not a pose template; keep face structure,
  change clothes/background/pose/light (`generators/nanobanana_character.py:1-12`); up to 9 character reference images
  per Seedream call with `reference_scale` default 0.7 (`image_generator.py:112-120,468-503`). Candidate pools and selection
  covered in the best-of-n doc 3.2. **FACT** render preflight blocks a beat that lacks identity detection state
  (`render_identity_guard.py:20-37`).
- **VIMAX.** **FACT** per camera: first frame of the first shot is generated from selected references (front/side/back
  portraits of visible characters plus the previous first frame), prompt prefixed "Image i: description"
  (`script2video_pipeline.py:555-622`); size 1600x900 (:460, :612); camera tree with `parent_shot_idx`: a new camera view is
  made by generating a *transition video* from the parent shot's first frame and extracting a frame from it (:380-410);
  priority shots first, then the rest (`asyncio.gather` at :518-519); selector output is cached in
  `<frame>_selector_output.json` (:575-581). Best-of-N exists but unused (best-of-n doc).
- **ASF.** **FACT** consistency by `face_lock` and `look_lock` plus assets bound to every shot; `last_frame` is only a
  continuity aid and "cannot be an identity anchor" (workflow-spec.md:99-100,391); images by Seedream.
- **TAKE.** **FACT negative (important):** `generateImages` calls `router.generateImage({ prompt: shot.imagePrompt })`
  only (`packages/provider/src/orchestration.ts:131`); `characterRefs`, `referenceImages` (defined in `seam.ts:25`) are never
  passed, so the documented "reference characterRefs" step (`skills/take/references/workflow.md` step 4) is not enforced by
  code. Output file is a placeholder `# <url>` text, not downloaded bytes (:132). **INFER:** TAKE is a schema/contract donor,
  not a consistency donor.
- **OM.** **FACT** providers expose reference-image inputs (Seedance up to 9 refs: `tools/video/seedance_video.py:159-166`;
  Kling reference and tail images: `tools/video/kling_official_video.py:104-109`); sample-first rule and seed management for
  A/B variants in `skills/pipelines/animation/asset-director.md:80`; backlot storyboard gate shows takes, prompts, cost and
  quality scores per asset (README.md:164). **UNKNOWN** automatic identity checking: `tools/analysis/visual_qa.py`
  extracts frames only (best-of-n doc 3.3).

---

## 7. Stage 6: VIDEO clips (image-to-video, Ken Burns, chaining, duration, provider)

- **HUO.** **FACT** two pipelines per episode: `ai_video` and `frame_slideshow` (pipeline :498-650). AI-video: `buildVideoParams`
  uses first+last frame (`referenceMode='first_last'`), or a single frame (`'single'`), `duration = sb.duration || 10`,
  aspect, `generateAudio`, `generateSubtitles` from episode metadata (:268-290); shots are generated **sequentially**, wait
  poll 120 x 4 s, and a shot without frames throws (:622-640). Slideshow: Ken Burns with `zoompan` (`services/drama/compose-ffmpeg.ts:231`)
  from `ceil(duration/3)` keyframes, then clip length aligned to TTS duration after dubbing
  (`resyncFrameSlideshowsAfterDubbing`, :255-266). No video-model credits in slideshow mode (README.md "More features").
- **DC.** **FACT** `video_mode` first_frame or keyframe (`models.py:892-900`); provider durations are bounded per backend
  (`video_duration.py:41-70`: e.g. seedance-2.0-mini 4-15 s, grok 6-30 s, legacy seedance_fast 4-12 s); Seedance 2 input prep
  with up to 3 reference audios totalling 15 s (`seedance2_i2v/pipeline.py:32-33`); keyframe transition prompt agent
  (stage 4); `adjust_video_duration` trims or stretches (max 1.5x) or freezes the last frame to fit the TTS duration
  (`generators/video_composer.py:697-712`); local ComfyUI workflows `wan2-2-FLF-LightX2V.json`, `ltx2-3-I2V.json` are shipped
  in `generators/`; Ken Burns exists (`video_composer.py:63-67`).
- **VIMAX.** **FACT** per shot: first frame always; last frame only when `variation_type` is medium or large
  (`script2video_pipeline.py:540-548`); video prompt = `motion_desc + "\n" + audio_desc` (:551); all clips submitted
  concurrently once their frames exist (`asyncio.gather`, :334); providers Seedance (5 or 10 s), Veo (8 s), OpenRouter, Omni.
- **ASF.** **FACT** chained generation: next shot receives previous `last_frame` (Seedance `return_last_frame`); batches
  must be sequential because the next shot needs the previous last frame; last frames must be re-hosted, not temporary
  links (workflow-spec.md:408-411); `generate_audio=true` for dialogue shots (:748).
- **TAKE.** **FACT** `generateVideos` sends only a prompt (no first/last frame) to Seedance with Minimax fallback via the
  router chain (`orchestration.ts:173`, `router.ts:101`), although `seam.ts:40-42` defines `firstFrameUrl/lastFrameUrl` and
  the openai-compatible adapter forwards them (`openai-compatible.ts:118-122`); unused by the batch path. Primary and
  fallback providers are config-only (`docs/models.md`, "Router semantics").
- **OM.** **FACT** scored provider selection across 7 dimensions with weights task fit 30, quality 20, control 15, reliability
  15, cost 10, latency 5, continuity 5 (README.md:672); `lib/slideshow_risk.py:1-24` scores a plan on 6 dimensions (0-5,
  `>= 4.0` fails and must not proceed to compose), and the cinematic compose skill forbids silent downgrade to FFmpeg Ken
  Burns for motion-led work (`compose-director.md`, "Runtime Routing"). **INFER:** a deterministic "slideshow risk" gate
  is a cheap pre-render check; ArcReel currently ships Ken Burns static clips (best-of-n doc section 2).
- **JF.** **FACT** only a readiness gate before video (best-of-n doc 3.4).

---

## 8. Stage 7: AUDIO (voice, timing, music, SFX)

- **HUO.** **FACT** voice assignment is an agent step in the manual UI (`drama_voice_assign`, SKILL.md: one unique `voice_id`
  per speaking character from the provider catalog, consistent across episodes) but the automatic pipeline uses
  `assignDramaVoicesByHeuristic` (pipeline ~:372-380). TTS per shot: `parseDialogueForTTS` then `synthesizeStoryboardTTS`
  only when the shot has dialogue and no audio yet (:226-229, :232-249); provider catalog per project audio config, e.g. MiniMax and Alibaba (voice_assign SKILL.md; adapter chosen by `getTTSAdapter(config.provider)`, `services/media/tts-provider-client.ts:19`).
  Timing: slideshow clips are re-aligned to TTS duration; for AI video the model may add audio (`generateAudio`). Music:
  `bgm_prompt` and `sound_effect` fields exist per shot; the code in the slideshow path synthesises a **sine-pad ambient loop
  WAV** (24 s default) rather than generating music (`common/media/frame-slideshow-bgm.ts:5,27-55`), mixed on dialogue-free
  shots (README.md:20). **UNKNOWN** whether `bgm_prompt` is consumed anywhere in the pipeline (grep not done).
- **DC.** **FACT** providers cosyvoice (DashScope) and edge-tts with a mock (`generators/tts_generator.py:817-823`), IndexTTS2
  via fal (`generators/indextts2_fal.py`, `audio/indextts2_beat_audio_task.py`), voice cloning and reference audio per
  character (`seedance2_i2v/voice_clone.py`, `NovelCharacter.reference_audio_path`, `fish_voice_id` at `models.py:1097-1101`);
  edge-tts SubMaker/sentence boundaries are collected (`tts_generator.py:319-327`; **INFER** used for subtitle timing); SRT built from probed beat audio length,
  defaulting to 5.0 s if probing fails (`export/episode_export.py:19-45`). Per-beat audio files `audio/epNNN/beat_NN.mp3` (:23).
- **VIMAX.** **FACT negative:** no TTS; sound is a prompt line (`audio_desc`) sent to the video model with the motion text
  (`script2video_pipeline.py:551`). Searched `agents/ pipelines/ tools/ agent_runtime/` for `tts|elevenlabs|edge_tts|voice`:
  only prompt text in `agents/script_enhancer.py:29-34` and `screenwriter.py` (instructions about dialogue voice descriptions).
- **OM.** **FACT** many TTS tool modules (azure, google, openai, elevenlabs, piper, doubao, dashscope, fish, kling) plus `tts_selector`, music tools (Suno, Pixabay, Freesound, ComfyUI, ElevenLabs via fal)
  under `tools/audio/`; narration timing by measured audio and word-level captions (`skills/core/subtitle-sync.md`:
  3-4 words per cue on vertical, cue end about 200 ms after last word); script word budget 2.5 words/s; TTS delivery cues
  from `voice-performance-director`; sample one TTS line before batching (asset-director.md:59).
- **BUT.** **FACT** `VoiceAgent`: an LLM extracts a `DialogueScript` with a repair note on invalid output (max 3 attempts,
  `agents/voice/agent.py:38,99-141`), then each line is synthesised concurrently with `asyncio.gather` and up to 3
  attempts per line, returning partial `failed_lines` rather than failing the whole step (:144-211; DashScope provider).
- **ASF.** **FACT** voice profiles flow into shot prompts; reference audio for important characters is listed as future work
  (workflow-spec.md:564).
- **TAKE.** none (no audio in `packages/`; searched `packages/*/src`, `skills`, `docs`).

---

## 9. Stage 8: RENDER and COMPOSE (timeline, subtitles, transitions, renderer, format)

- **HUO.** **FACT** per-shot compose then merge. Per-shot: mux video with TTS audio or silent AAC, libx264 `-preset fast -crf 23`,
  AAC, `-shortest`, `+faststart` (`compose-ffmpeg.ts:11,90-106`); subtitles through ffmpeg `subtitles` filter if the build
  supports it (`ffmpegSupportsSubtitles`, :15-19; `buildSubtitleDocument`, `compose-dialogue.ts:33`); BGM mixed on
  dialogue-free shots. Merge: normalise each clip to h264+stereo AAC then concat demuxer
  (`normalizeClipForConcat`, `compose-ffmpeg.ts:~140`; `episode-merge-service.ts:84-117`, model tag `ffmpeg-concat-h264-aac`
  :62). No transitions found (grep `xfade|fade` in `episode-merge-service.ts` empty). Renderer: plain FFmpeg.
- **DC.** **FACT** FFmpeg and MoviePy composers (`generators/video_composer.py:1-12,564,682`: `create_video_composer(use_moviepy)`),
  subtitles via ASS conversion (:488-520), episode SRT + ZIP export bundle (`export/episode_export.py:19-124`), per-title
  drawtext; task subprocess timeout 30 min (:21).
- **VIMAX.** **FACT** MoviePy `concatenate_videoclips` + `libx264 preset=medium` into `final_video.mp4`; skip when the file exists;
  hard cuts only, no subtitles or audio mix (`script2video_pipeline.py:341-350`).
- **OM.** **FACT** renderer routing by `edit_decisions.render_runtime`: Remotion (default for video-led, `CinematicRenderer`),
  HyperFrames (HTML/GSAP), FFmpeg (plain concat); `runtime_swap_detected` check; silent swap is a "CRITICAL governance
  violation"; Remotion preflight before render; Remotion scene components include CaptionOverlay, HeroTitle, EndTag etc.
  (`remotion-composer/src/components/`); render quality tooling `tools/analysis/composition_validator.py`.
- **BUT.** **FACT** one ffmpeg graph: video-only concat, per-track audio shifted with `adelay` at precomputed offsets, `amix`,
  then mux; shots' own audio dropped (`integrations/providers/ffmpeg_editor_provider.py:22-26,82-86`).
- **TAKE.** none (no compose; stops at per-shot assets and `storyboard.md` export).
- **INFER:** ArcReel already has Remotion; the transferable ideas are OM's locked-runtime/no-silent-downgrade check and
  BUT's offset-based audio placement.

---

## 10. Stage 9: QUALITY (stage-specific additions only)

The best-of-n doc already covers ViMax's unwired `BestImageSelector`, DC's sketch/frame/episode judges, OM's host-LLM
reviewer with max 2 revision rounds, JF's readiness gate. Stage-specific items not covered there:

- **FACT** HUO: continuity check with rewrite cap 30, stagnation 5, parse-failure abort (stage 1); length band and floor
  gates (stage 1). Not video/image quality.
- **FACT** DC episode-plan review is deterministic plus LLM and *unwired* (stage 3 above).
- **FACT** OM `lib/slideshow_risk.py` (6 dimensions, fail at >= 4.0) and `lib/variation_checker.py:26` (scene variation) are
  deterministic plan-level gates before compose; `docs/stage-gates/` exists (not read).
- **FACT** BUT voice: output-repair loop with error text fed back (stage 7).
- **FACT** ASF: `continuity_report.status` defaults to `needs_review` (`continuity_seed_builder.py`).
- **FACT** shenbi gating thresholds apply to skill tests, not runtime (stage 1).

---

## 11. Stage 10: PACKAGE and PUBLISH

- **OM (only real publish tooling).** **FACT** `tools/publishers/export_bundle.py` is "the first PUBLISH-tier tool": copies the
  render, writes metadata files and chapter timestamps, thumbnail or `thumbnail_concept`, lays out the export directory, and
  returns a schema-valid `publish_log` entry with `status: "exported"`; no upload, no account, no cost (docstring lines 1-20;
  `_chapter_lines` :143; `thumbnail_*` inputs :99-102). Publish-director produces hero vs derivative outputs (teaser,
  social cutdown, poster frame) and tone-matched metadata (`skills/pipelines/cinematic/publish-director.md`).
  `schemas/artifacts/publish_log.schema.json` has `entries`, `metadata`.
- **DC.** **FACT** export = per-episode MP4 + SRT + ZIP asset bundle (`export/episode_export.py:48-124`). Platform upload:
  grep for `youtube|tiktok|douyin|bilibili` in `src/` returned nothing.
- **HUO, VIMAX, TAKE.** **FACT negative:** grep for platform names and upload-to-platform in `workbench-server/src`, the
  ViMax python tree (excluding tests) and `take/packages` found no publish/distribution code. TAKE exports `storyboard.md`
  (`packages/cli/src/commands/export.ts`).
- **UNKNOWN** ASF, BUT, JF, shenbi publish (not searched).

---

## 12. Adoption table (INFER: effort is my estimate; "evidence" is the cited facts above)

| Stage | Best donor mechanism worth adopting | Evidence | Effort guess |
|---|---|---|---|
| 1 IDEA to STORY | HUO: per-book memory files + chapter-end change record + length band/floor + stagnation and parse-failure aborts; phased outline with gap-patch for more than 30 chapters | novel-writing.ts:546-683,1272-1392; novel-char-limit.ts:11-60; novel-meta.ts:169-190; novel-memory-paths.ts:15-19 | M-L (memory + audit loop); S for the length floor and gap-patch alone |
| 2 ASSET_ANALYSIS | DC: quote-must-be-verbatim evidence, name attestation, conservative merge; per-character identity rows with `face_prompt`/reference images; VIMAX front-then-derived side/back portraits with fallback to front | structured_extraction.py:1-22,285-300,489-512; models.py:960-1046; idea2video_pipeline.py:232-292 | M (guard) ; S (portrait fallback) |
| 3 EPISODE_PLAN | DC: `EpisodePlan` schema (chapter range, conflict, cliffhanger, key events, 3-6 cast) + deterministic gap/overlap checks (copy the checks, do not rely on the unwired fixer) | episode_planner.py:46-156; episode_reviewer.py:24-50,256-292; graph_build.py:188,224 | S-M |
| 4 SCRIPT/SHOT | HUO storyboard contract (3-second video-prompt segments, `ceil(duration/3)`, scene_id/character_ids binding, self-check list); OM 5-aspect scene check and enum-to-prompt compiler; DC keyframe-transition prompt bans | storyboard SKILL.md; shot_prompt_builder.py:1-50; scene-director.md; keyframe_prompt_builder.py:1-50 | S-M (mostly prompt + validators) |
| 5 STORYBOARD | VIMAX reference selection (up to 8, same camera/most recent first) + DC identity-lock prompt rule and render preflight that blocks beats without identity labels; HUO ref packing (chars + scene + own frames, max 6) | script2video_pipeline.py:555-622; nanobanana_character.py:1-12; render_identity_guard.py:20-37; pipeline.ts:207-224 | M |
| 6 VIDEO | HUO first_last or single reference mode with sequential generation; DC `adjust_video_duration` (trim, 1.5x stretch, freeze) to fit TTS; ASF last-frame chaining with sequential order and re-hosted frames; VIMAX variation_type gates last frame (cost saver) | drama-episode-pipeline.ts:268-290; video_composer.py:697-712; workflow-spec.md:408-411; script2video_pipeline.py:540-548 | M |
| 7 AUDIO | DC per-beat audio + probed duration -> SRT (and edge-tts word boundaries); BUT per-line synthesis with bounded retry and partial-failure list; OM sample-one-line-first and 2.5 words/s budget | export/episode_export.py:19-45; tts_generator.py:319-327; voice/agent.py:144-211; script-director.md:26 | S-M |
| 8 RENDER | OM locked-runtime check (no silent downgrade); BUT offset-based `adelay`+`amix` timeline; HUO normalise-then-concat | compose-director.md; ffmpeg_editor_provider.py:82-86; compose-ffmpeg.ts:140; episode-merge-service.ts:84-117 | S |
| 9 QUALITY | OM `slideshow_risk` plan gate (deterministic, pre-render); JF `retry_guidance` field to feed failure reasons into regeneration (see best-of-n doc for the rest) | slideshow_risk.py:1-24; shot_frame_prompt_agents.py:59,178 | S |
| 10 PACKAGE | OM `export_bundle` (render + metadata + chapters + thumbnail concept + schema-valid publish_log); DC SRT + ZIP bundle | export_bundle.py:1-20,143; episode_export.py:48-124 | S |

## 13. Unknowns and cautions

- **UNKNOWN** measured wall-clock and cost per finished episode for HUO, DC, VIMAX, TAKE; only OM publishes cost and its
  numbers are for 50-60 s films.
- **UNKNOWN** how HUO splits a novel into episodes; how DC `character_tag` is injected; whether HUO `bgm_prompt` is consumed.
- **UNKNOWN** GitHub-only donors beyond the files cited; BUT ARCHITECTURE.md calls itself an architecture-only deliverable
  while agent files exist (**INFER:** maturity unclear, treat as design reference).
- **Caution (FACT):** TAKE's docs promise character references and first-frame video input that its batch code does not
  pass (`orchestration.ts:131,173`); DC's reviewer/fixer for episode plans are present but not wired; ViMax's best-image
  selector is present but not called. Prefer mechanisms verified as called.
- Line numbers marked with `~` were taken from a nearby grep hit, not an exact read.
