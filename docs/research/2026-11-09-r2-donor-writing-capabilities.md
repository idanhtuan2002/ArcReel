# Donor writing capabilities: story, script, adaptation, continuation, variants, import

Date: 2026-11-09. Read-only research; no donor code was run. Extends (does not redo)
[2026-11-08-r2-donor-stage-mechanisms.md](2026-11-08-r2-donor-stage-mechanisms.md) (stages 1 to 4, HUO outline and
length control, shenbi 7 phases, VIMAX develop_story) and [ADR 0114](../adr/0114-film-episodes-are-adapted-from-the-story.md).
Labels: **FACT** = read at the pinned commit (path:line); **INFER** = my reading; **UNKNOWN** = not found/not read.
Licensing is out of scope (project policy).

## 0. Pins, path abbreviations, search scopes

| Short | Checkout | Commit |
|---|---|---|
| HUO | `/home/anhtuan/content-os-r1-8/work/huohuo-drama` (code `workbench-server/src/`, skills `agent-skills/`) | f104b85 |
| OM | `/home/anhtuan/content-os-r1-8/work/OpenMontage` | 08e2151 |
| TAKE | `/home/anhtuan/content-os-r1-8/work/take` | 47c1721 |
| DC | `/home/anhtuan/.cache/r2-donors/dramaclaw-full` (code `src/novelvideo/`) | b299bfd |
| VM (ViMax) | `/home/anhtuan/ViMax` | 63bb9c7 |
| SH (shenbi) | GitHub `ThomasChangX/shenbi`, read via `gh api` | 10efa7c (HEAD 2026-11-09) |
| NSA (novel-studio-ai) | GitHub `YfengJ/novel-studio-ai` | 9b690ae (HEAD) |
| SB (StoryBox) | GitHub `amcghm/StoryBox` | ba24ff6 (HEAD) |
| AR (ArcReel) | `/home/anhtuan/.codex/worktrees/9b89/content-production-os` | 29acd16a9 |

Citation shorthand. HUO: `R:` = `routes/novel/novel.ts`, `NW:` = `services/novel/novel-writing.ts`, `NC:` =
`services/novel/novel-continuity.ts`, `NM:` = `common/novel/novel-meta.ts`, `SK:` = `agent-skills/`.
DC: `ING:` = `api/routes/ingest.py`, `CT:` = `api/routes/content.py`, `EP:` = `api/routes/episodes.py`, `CR:` =
`agents/content_rewriter.py`, `PL:` = `agents/episode_planner.py`, `RV:` = `agents/episode_reviewer.py`.
SH: `sh:<skill>:N` = `skills/shenbi-<skill>/SKILL.md` line N of the decoded file. AR paths are repo-relative.

Search scopes used for every "absent (...)" cell:
- S-HUO = `git grep` over `agent-skills/` and `workbench-server/src/` at f104b85, plus the file list of
  `services/novel/` (64 non-test files) and `routes/novel/novel.ts`. The frontend is `workbench/`; **UNKNOWN**: I did not read it (a grep of `workbench/src` for import-sources/humanize returned nothing, which I do not treat as proof).
- S-OM = `skills/`, `pipeline_defs/`, `schemas/artifacts/`, `tools/` (grep fountain|fdx|sequel|continuation|rewrite|import script).
- S-TAKE = all of `README.md`, `docs/`, `skills/take/`, `packages/core/src/io/` (only `markdown.ts`).
- S-DC = `src/novelvideo/{agents,workflows,cognee,api,utils}` and `cli.py`.
- S-VM = every `.py` under `agents/`, `pipelines/`, `agent_runtime/` (all listed by `git ls-files`).
- S-SH = full file tree (2498 paths) and all 74 `skills/*/SKILL.md` descriptions; README.
- S-NSA = full file tree (116 paths), README, 6 core `src/lib/` files read in full.
- S-SB = full file tree (289 paths), README, `reverie/run.py`, `reverie/agent/storyteller.py`.
- S-AR = `server/story_authoring/*.py`, `lib/episode_adaptation.py`, `docs/adr/0114-*`, `r2/contracts/narrative.py`.

Scope not claimed: SH, NSA, SB were read at HEAD (not a pinned old commit) and shallowly beyond the files cited;
SH skill bodies were read only for sequel-writing, import-analysis, canon-import, truth-sync, short-packaging,
length-normalizing (the other 68 by frontmatter description only). appolloqin/huohuo-drama was not needed (local
checkout is complete). OM, TAKE, VM have no fiction long-form engine (see section 1).

---

## 1. Per-donor capability inventory

### 1.1 HUO (huohuo-drama): the only donor with a full novel engine plus novel-to-drama bridge

Agent skills (all 10 top-level dirs at f104b85; `git ls-files agent-skills`):

| Skill dir | Files | What it does (FACT) |
|---|---|---|
| `novel_premise/` | 19 (base + 18 genre subdirs) | 200-500 char premise from keywords; world, protagonist, conflict, tone, selling points; not an outline (`SK:novel_premise/SKILL.md:1-5`) |
| `novel_outline/` | 21 (+ `continuity`, `chapter_hooks`) | book outline: world, master plot with drama tags, characters (name, title, relation, motive), volumes, per-chapter synopses; chapters 1-8 carry explicit four beats hate/thrill/urgency/hope; chapter ends ban warm pressure-release (`SK:novel_outline/SKILL.md:1-11`, `chapter_hooks/SKILL.md:1-6`) |
| `novel_writing_brief/` | 25 | 150-400 char per-chapter brief with plot goal, cast, mood, length emphasis, chapter-end hook, and a 15-item continuity ledger (`SK:novel_writing_brief/SKILL.md:1-8`) |
| `novel_chapter_writer/` | 26 (18 genres + `chapter_craft_core`, `chapter_role`, `compliance`, `continuity`, `scene_drama`, `serial_pulse`, `stage_beat`) | chapter prose, "write or continue" (续写 outputs only the new paragraphs, one-shot writes the whole chapter) (`SK:novel_chapter_writer/SKILL.md:1-4`); `compliance` = veto list (minors, explicit sex/violence, drugs); `chapter_role` = payoff/pressure/breath/travel intensity so no three equal chapters in a row; `serial_pulse` = emotional debt and promise bookkeeping |
| `ai_dehumanizer/` | 1 | de-AI rewrite of Chinese prose, four methodologies (translation-chain simulation, multi-turn rewrite, detection-guided, perplexity-guided) (`SK:ai_dehumanizer/SKILL.md:1-60`) |
| `drama_script_formatter/` | 1 | novel passage, idea or rough draft to a scene-headed screenplay `## S01 | INT/EXT · place · time`; keeps plot and ending, bans shot terms, 9:16 limits (3-8 scenes, 30-60 s per scene) (`:1-40`) |
| `drama_cast_scene_extract/`, `drama_storyboard_breakdown/`, `drama_image_prompt/` (4 files), `drama_voice_assign/` | 1+1+4+1 | video-side stages (covered in the stage doc) |

Services and routes (FACT, `R:` line = route):

| Capability | Inputs / outputs | Auto or human | Safeguards | Cite |
|---|---|---|---|---|
| Premise, title, writing brief, outline | keywords/premise to text | human triggers each; batch possible | outline phased above 30 chapters, gap-patch up to 3 rounds (stage doc) | `NW:137,199,231,546`; `R:167,199,849` |
| Chapter generate (full) | outline row + brief + memory to chapter | auto per chapter; batch `generate-remaining` modes remaining/all/range/chapters, `overwrite` flag | beat-sequential, length band, polish with floor, continuity audit loop, craft audit, humanize hook, memory update (stage doc) | `NW:1272`; `R:1062,1407,1535-1572` |
| **Continue chapter (续写)** | `existingText` (body or stored) + outline + brief + `lengthHint` (default 800, `continue_segment_chars`) to new segment only | human triggers; auto audit after | craft hook (rewrite on low score), change-record split off, continuity check on `existing + segment` unless `skip_continuity_check`; polish in `segment` mode | `R:890-978`, `NW:684,861`, `NM:21` |
| Context injection for write/continue | previous chapter tail, older summaries scaled by chapter number, retrieved ledgers, canon-lock prefix (reminder, key actions, protagonist knowledge, relations, realm) | auto | forced injection at generation | `NC:141,172-230,274,420-468` |
| Per-chapter continuity ledger and book snapshot | chapter text to ledger (content-hashed) | auto at accept; **batch rebuild from existing chapters** `continuity/rebuild` | skips chapters whose hash is unchanged | `NC:469,499,621-660`; `R:525-548` |
| State card per chapter | chapter text (+ outline beats) to state card, validate, repair | auto or human; `rebuild`, `validate`, per book | LLM or project-only extraction, skip if unchanged | `R:550-800`; `services/novel/novel-state-card-extract.ts:71` |
| Three-layer long memory + anchor | `world_bible.md`, `character_sheets.md`, `plot_ledger.md`, `causal_chain.md`, one-line `anchor.txt` | init, edit by human (`PUT memory/:file`), update by `applyNovelMemoryFromChapter` | `review(vol,lastChapter)` issues, `snapshot(vol)`, prompt builder per chapter | `R:1573-1702`; `services/novel/novel-memory/novel-memory-manager.ts:97,145,263,282`; `novel-chapter-pipeline.ts:570,1133` |
| Chapter-end change record | trigger, process, outcome appended to every chapter and stored apart | auto | audited; orphan repair | `common/novel/novel-change-record.ts:16-152`; README.md:22 |
| Craft audit and commercial-appeal audit | chapter to score, hard fails (opening pressure, hate/thrill/urgency/hope beats, ending decompress) | auto | min score 70 (`chapter_craft_min_score`), rewrite max 3, compliance veto | `services/novel/novel-chapter-craft-check.ts:166`; `novel-commercial-appeal-audit.ts:688`; `NM:47-51` |
| AI-rate detect + humanize | text to perplexity or statistical probability; rewrite up to `MAX_HUMANIZE_CHARS` | human route `ai-detect/humanize`, or auto loop (`ai_humanize_auto` default on, max 3 rounds, target 39) | statistical fallback when perplexity unavailable | `R:802-848`; `routes/ai/ai-detect.ts:92`; `services/ai/ai-dehumanizer.ts:370`; `NM:59-125` |
| **Novel to drama import** | `import-sources` (own/template/platform novels), chapter list, `content?mode=chapter|full` to episode raw text | human picks; platform-internal only | access check own/template/platform | `R:126-165`; `common/novel/novel-import-access.ts:88-140` |
| Idea to episode raw text | one-line idea + previous-episode tail + roster to 800-2500 char episode draft | auto inside pipeline | cross-episode continuity block | `services/drama/episode-raw-content.ts:10-80` |
| Raw to screenplay ("rewrite") | `content` to `formatted_script` by `drama_script_formatter` | auto in one-call pipeline | must produce non-empty or throws | `services/drama/drama-episode-pipeline.ts:~387-400` |
| Drama synopsis / title | project to description and title | auto | none read | `services/drama/drama-synopsis.ts:21,83` |

Negative findings (S-HUO): no sequel, spin-off, fan-fiction, variant, genre-swap, POV-swap or translation feature (grep sequel|续集|续作|番外|spinoff|同人|fanfic: 0 hits);
no import of an external novel file (`mammoth` and `pdf-parse` in `package.json:41-43` are used by `services/ai/ai-detect-document.ts` for AI detection only);
no chapter splitter for pasted text. The only "genre profile" is the 18 genre subdirs of the four novel skills plus `NM` flags.
**INFER:** the closest thing to importing an existing story is `rebuildNovelContinuityFromChapters` (`NC:621`) after chapters are
created by hand (`R:355` creates empty chapters; content is edited by the user), which extracts ledgers and state cards from text.

### 1.2 DC (DramaClaw): import-first novel/screenplay to video

| Capability | Inputs / outputs | Auto or human | Safeguards | Cite |
|---|---|---|---|---|
| Novel/screenplay upload | `.txt`, `.md`, `.docx`; UTF-8 or GBK; CRLF normalized | human uploads | size limit, text-size/billing-char limit, parse errors typed | `utils/document_parsers.py:9-11,60-90`; `ING:169-274` |
| Chapter detection + preview | text to chapters (Chinese numerals handled) or single-chapter fallback | auto | `build_import_format_check`: scene-header status, line-aware issues, chapter structure issues shown before `start` | `cognee/chapter_detector.py:20-245`; `utils/screenplay_quality.py:194,348,553`; `ING:296-` |
| Knowledge-graph ingest | novel to Cognee graph; events, characters, scenes extracted | human starts, background task | event extractor emits events sequentially with `is_last`; scene-header normalizer | `ING:296`; `cognee/event_extractor.py:48,164`; `cognee/screenplay_normalizer.py:213-267` |
| Episode planning | `target_episodes` + `planning_mode` (`chapters` deterministic default, `ai` graph-driven, no current UI selects `ai`) to episodes: title, chapter range, summary (10-100 chars), main conflict, **cliffhanger** (min 5 chars), 1-5 key events, 3-6 cast | human triggers | `EpisodePlan` schema; structure guide (ep 1 builds world, last 1-2 climax); `EpisodePlanReviewer` checks chapter continuity, coverage, character names, structure; `EpisodePlanFixer` patches (fuzzy character names) | `EP:295-346`, `api/schemas.py:142-144`; `PL:46-75,100-160`; `RV:225-531`; `agents/episode_fixer.py:320-622` |
| **Raw to adapted (rewrite)** | raw episode text to line-per-beat narration: `target_beats` (18), `beat_chars` 14-20, `narration_style` (default first person), protagonist name | human triggers `rewrite/generate`; stored as `adapted_content`, editable/deletable | rules: every line is a new action, new information or new confrontation shift; no mood-padding; dialogue as `speaker + manner: “verbatim quote”`; keeps conflict, turns, climax, ending hook; output retries 3 | `CT:62-160`, `api/schemas.py:154-158`; `CR:12-204` |
| Literal script (beat metadata) | adapted lines to beats, speaker/dialogue split, scene blocks | auto | one line = one beat, line text preserved, LLM adds metadata only; screenplay import-quality gate; content-filter hints | `workflows/literal_script_writing.py:1-40,382-1474`; `workflows/script_writing.py:1-54` |
| Narration vs drama mode | `spine_template` narrated / drama | per project | selects `audio_type_mode` | `workflows/script_writing.py:35-50`; `project_config.py:29,447` |
| Asset language | detect `en` vs `zh`; "keep every supplied name verbatim, never translate" | auto | name preservation rule | `utils/source_language.py:30-112` |

Negative findings (S-DC): no idea-to-novel writer, no continuation of a novel, no sequel, no variant or style-transfer of a story
(grep sequel|续集|番外|spinoff|age_rating|分级 hits are unrelated config/model files), no translation of a story, no title/blurb generator.
DC never writes the story; it imports and adapts.

### 1.3 OM (OpenMontage): non-fiction video; scripts as artifacts

| Capability | What it does | Auto or human | Safeguards | Cite |
|---|---|---|---|---|
| Research, proposal, script, scene plan stages per pipeline (13 pipeline defs) | script-director per pipeline writes `script` artifact (`schemas/artifacts/script.schema.json`) | `human_approval_default: true` on proposal, script, scene_plan, assets, publish | `max_revisions_per_stage: 3`, decision log, research brief traceability | `pipeline_defs/cinematic.yaml:28,60-280` |
| Cinematic script: beat map hook, escalation, reveal, landing; sparse dialogue; trailer title cards | beat truth in metadata (`beat_map`, `dialogue_selects`, `music_turns`) | agent | every factual claim traceable to research brief | `skills/pipelines/cinematic/script-director.md:17-72` |
| Localization dub script (translate an existing script) | source transcript truth, target-language copy per language, glossary and protected terms, review status by language, structure and timing preserved | agent + review before synthesis | glossary preservation gate | `skills/pipelines/localization-dub/script-director.md:14-48` |
| Storytelling craft | explainer arc, hook types, but/therefore, 30-second rule | guidance | none enforced in code | `skills/creative/storytelling.md:7-189` (hook types at :86) |

Negative findings (S-OM): no fiction writer, no import of a screenplay format, no continuation/sequel/rewrite-by-instruction.
The 13 pipelines are explainer, animation, cinematic, documentary, talking-head, podcast-repurpose, localization-dub, etc. (`pipeline_defs/`).

### 1.4 TAKE: screenplay in, storyboard out

- **FACT** inputs are `script.md` or pasted text written to `script.md` first ("everything is a file"), or an existing `shots.json` (skip analysis) (`skills/take/references/workflow.md:5-9`).
- **FACT** the agent does beat decomposition (`summary`, `purpose`, `emotion`; 5-15 beats under 3 minutes) and shot design with controlled vocabularies; "text analysis never calls an LLM API" (`skills/take/SKILL.md:40-55`, `references/workflow.md:11-35`).
- **FACT** `storyboard.md` is exported for human review and re-imported (`take export import`) (`references/workflow.md:68`, `docs/workflow.md:58`); shot `source` is `agent|manual|imported` (`references/output-contract.md:25`).
- Negative (S-TAKE): no Fountain/FDX parser, no story writing, rewrite, continuation or variant.

### 1.5 VM (ViMax)

| Capability | What it does | Cite |
|---|---|---|
| idea to story | `Screenwriter.develop_story(idea, user_requirement)`; requirement carries audience, genre, scene count (single call) | `pipelines/idea2video_pipeline.py:193-211`, `agents/screenwriter.py:20-70` |
| story to scene scripts (dramatization) | `write_script_based_on_story(story, user_requirement)`: scenes by same time/location, filmable concrete actions, faithful to original; if story has `Scene N:` headers the count is enforced | `agents/screenwriter.py:66-110,145-200` |
| script2video | takes a script text directly (screenplay-like) plus requirement ("no more than 15 shots") and style | `main_script2video.py:1-40`, `pipelines/script2video_pipeline.py:228` |
| novel2movie | chunk and aggregate a novel (`novel_compressor`), extract events sequentially with `is_last`, cap `MAX_EXTRACTED_EVENTS = 50`, scenes per event, merge characters across scenes and into the book | `pipelines/novel2movie_pipeline.py:95,142-143,225-257`; `agents/novel_compressor.py:49-63`; `agents/event_extractor.py:100-127`; `agents/scene_extractor.py:80`; `agents/global_information_planner.py:158,220` |
| Script planner with intent routing | idea to planned script via narrative / motion / montage prompt, retry 3 | `agents/script_planner.py:315-396` |
| Script enhancer | polish a planned script: no plot change, concrete sensory detail, repeated character voice descriptors | `agents/script_enhancer.py:10-60` |

Negative/caution (S-VM): `ScriptPlanner` is referenced only by `tests/test_robustness.py:24,146` and `ScriptEnhancer` by nothing outside its own file (grep over all `.py`), so **both are dead code in the shipped pipelines**.
No continuation, sequel, rewrite-by-instruction, translation or memory/continuity check.

### 1.6 SH (shenbi): skill framework, 74 skills (`skills/*/SKILL.md`)

Phases and counts (README.md:95-105): Genesis 11, Architecture 5, Planning 3, Drafting 9, Audit 18, Foundation 4, Management 9, Import 4, Short Story 3, Out-of-pipeline 7. Checkpointed; a human approves checkpoints and the wrapper never auto-approves (README.md:57).

Complete skill list (name: one line), grouped:

- **Genesis/architecture:** `worldbuilding` (new world + story bible), `power-system`, `faction-builder`, `location-builder`, `character-design` (profiles, arcs, voice), `relationship-map`, `story-architecture` (frame, volume map, core conflict), `volume-outlining`, `pacing-design` (build-up, escalation, explosion, aftermath), `plot-thread-weaver` (A/B/C lines), `genre-config` (genre rules, fatigue words, chapter types, audit dimensions), `foreshadowing-lifecycle`, `book-spine-init`, `market-radar` (platform trends, leaderboards, positioning), `foundation-review`, `intent-management` (author intent and current focus).
- **Per chapter:** `chapter-planning` (memo), `foreshadowing-plant`, `context-composing`, `chapter-drafting`, `state-settling` (9 fact categories to truth files), `foreshadowing-track`, `foreshadowing-recall`, `foreshadowing-resolve`, `style-polishing`, `anti-detect`, `length-normalizing`, `chapter-revision`, `chapter-pattern` (detect structural monotony).
- **Audit (independent agent):** continuity, character, dialogue, motivation, POV, world-rules, era, pacing, highpoint, reader-pull, resonance, texture, long-span repetition (6-char n-gram), anti-ai, foreshadowing, memo-compliance, sensitivity, plus 4 grouped audits (`review-group-factual|character|craft|plan`), and mode audits `review-fanfic` (canon/au/ooc/cp fidelity) and `review-spinoff` (main-story consistency: event conflict, future-info leak, world rules, hook isolation).
- **Management:** `snapshot-manage`, `drift-guidance`, `memory-distill` (arc synthesis every 12 chapters, stratum every 36), `volume-consolidation`, `escalation-review`, `score-arc|volume|stratum`, `anchor-curate`, `truth-sync`.
- **Import (4):** `import-analysis`, `character-extraction`, `world-extraction`, `style-learning`, plus `canon-import` (fan-fiction canon) and `sequel-writing`.
- **Short story (3):** `short-outline` (under 30 chapters), `short-drafting` (batch all chapters, generate-review-revise), `short-packaging`.
- **Meta:** `using-shenbi`, `writing-skills`.

Capabilities relevant here (FACT unless marked):

| Capability | What it does | Safeguards | Cite |
|---|---|---|---|
| **import-analysis** | `import/source/*.txt` to `import/analysis/*.md` in 8 passes (parse, characters, world, plot, foreshadowing, style, highlights, state reconstruction); passes 4-7 parallel | "zero guessing" (every item locatable in source or marked unconfirmed); state reconstruction is a *suggestion*, never writes `truth/`, needs human approval; every conclusion carries chapter and paragraph; style pass uses no LLM | `sh:import-analysis:33-59` |
| character-extraction, world-extraction | reverse-extract profiles, speech fingerprints, `story_bible`, rules, locations, factions, power system from analyzed chapters | evidence-bound (description only read) | frontmatter of both |
| style-learning | statistical fingerprint: sentence/paragraph length, TTR, high-frequency patterns | no LLM; feeds style-polishing and drift detection | `sh:import-analysis:58`; frontmatter |
| truth-sync | re-extract 9 fact categories from edited or imported chapters, diff against truth files, human arbitrates conflicts, incremental update, character-profile cross-check | chapter text is authority; extraction vs inference labelled, inferred at most 20%, tagged `[inferred]` | `sh:truth-sync:39-86` |
| **sequel-writing** | continue a paused novel from the latest approved snapshot: locate breakpoint, rebuild 6 context classes (world state, relationship matrix, emotional arcs, active hooks+thread map, style fingerprint, current focus), ask the human whether intent changed, run drift detection over the last N=5 chapters, then loop planning to drafting | breakpoint must be an audited+settled chapter; never assume memory; author intent confirmed first; first 3 chapters drift-checked; published chapters never edited | `sh:sequel-writing:56-99` |
| **canon-import** (fan-fiction base) | extract 5 sections (world, character, event, relationship, timeline canon) with source chapter for each claim; modes canon / au / ooc / cp with an explicit keep-and-change list | mode filtering transparent, no mixing, OOC must declare deviations | `sh:canon-import:33-100` |
| review-fanfic / review-spinoff | audit a variant against the preserved canon / main story | independent agent | frontmatter |
| length-normalizing | below 3000 chars expand, above 10000 compress; compression must stay at least 3000 and at least 25% of original, else REJECT; no event added or removed | hard gate | `sh:length-normalizing:36-72` |
| short-packaging | 3-5 titles, 2-3 blurbs (100-300 chars, no spoiler), 3-5 selling points each with evidence, cover prompt, 5-10 platform tags, human selects | multi-version, evidence-bound | `sh:short-packaging:40-93` |
| market-radar | platform trend and leaderboard research for positioning | UNKNOWN body not read | frontmatter |

Negative (S-SH): no rewrite-by-instruction skill, no translation skill, no POV/market/age-rating variant skill (full list above), no screenplay/dramatization skill (writing only; video is outside shenbi).
**INFER:** variants exist only as fan-fiction modes (canon-import + review-fanfic); `style-polishing` changes surface only.

### 1.7 NSA (novel-studio-ai): plan, context pack, draft, check, revise, accept, extract

FACT, from README "Why This Exists" workflow and files: Plan, Build Context Pack, Draft, Check Continuity, Revise Style, Accept, Extract Memory, reuse. **Drafts never update canon; only accepted chapters write** summaries, character states, graph triples, timeline events and memory chunks.

| Capability | Detail | Cite |
|---|---|---|
| Hybrid context pack | story bible, style bible, chapter outline, scene beats, active character states, graph facts, keyword chunks, vector chunks | `src/lib/context/contextPack.ts:16-18,90-149` |
| Continuity check = model report + deterministic hard rules | dead character appears, Story Bible `forbidden_contradictions` hit; merge sets `pass=false` on any high/critical issue; stored per chapter | `src/lib/continuity/hardRules.ts:14-52`; `src/lib/ai/checkContinuity.ts:26-37` |
| Style revise | rewrites draft to Style Bible using the latest continuity report, temperature 0.55 | `src/lib/ai/styleRevision.ts:16-30` |
| Accept with optional `finalText` | accepts the supplied text instead of the draft; blocks on failed check/empty text | `src/app/api/projects/[projectId]/chapters/[chapterId]/accept/route.ts:12-22` |
| Memory extraction schema | chapter summary, scene summaries with evidence text and confidence, new characters, states, relations | `src/lib/ai/schemas.ts:210-313`; `src/lib/ai/extractMemory.ts:7-22` |
| Ideate, story bible, style bible, outline generation, graph, export | one route each | `src/app/api/projects/ideate/route.ts`, `.../story-bible/generate`, `.../outline/generate` |

**INFER:** `accept` with `finalText` is a de-facto import path for one chapter (paste, accept, memory extracted), but no multi-chapter import, splitter, continuation or variant exists (S-NSA).

### 1.8 SB (StoryBox): simulation then story

FACT: personas simulate days in a world (`reverie/run.py:50-69`); then `Storyteller` runs summaries, title, type, background, themes, chapters (n=5), conflicts (10), plot points, content, save (`run.py:74-84`). Each plot point is written with `faiss_manager.query(plot_point, k=5)` events and the running chapter summaries; every chapter is summarized after writing (`reverie/agent/storyteller.py:376-450`). **INFER:** useful only as a memory-retrieval and chapter-summary-chain pattern; no import, continuation or variant (S-SB), no continuity audit. ADR 0114 already excludes character simulation.

---

## 2. Capability matrix

Legend: **cite** = FACT; `~` = INFER; `absent (S-x)` = searched, none; `UNK` = UNKNOWN. AR = ArcReel today (29acd16a9).

### 2.1 Creating and importing a story

| Capability | HUO | DC | OM | TAKE | VM | SH | NSA | SB | AR |
|---|---|---|---|---|---|---|---|---|---|
| idea to story | `NW:137,546,1272` | absent (S-DC) | absent (S-OM) | absent (S-TAKE) | `idea2video_pipeline.py:193` (short, 1 call) | genesis + `short-drafting` | `ideate/route.ts`, outline, chapters | simulation then `storyteller.py:376` | full run `driver.py:264`, 3 chapters, 7000-11000 syllables (`driver.py:107,158`) |
| import complete story | internal novel to drama only `novel-import-access.ts:88`; no file upload (S-HUO) | `.txt/.md/.docx` + chapter preview `ING:169`, `document_parsers.py:9` | absent (S-OM) | `script.md` or pasted text `workflow.md:5` | novel text via `novel2movie_pipeline.py:479`; script text via `script2video` | `import-analysis` 8 passes `sh:import-analysis:33` | `finalText` accept `accept/route.ts:15` (~one chapter) | absent (S-SB) | absent (S-AR) |
| import ongoing story | create chapters by hand then rebuild ledgers `R:355,525` (~) | absent (single import, no incremental; S-DC) | absent | absent | absent (S-VM) | `import-analysis` + `truth-sync` bootstrap + `sequel-writing` | accept chapters one by one (~) | absent | absent (S-AR) |
| continue/extend chapters | `R:890`, `NW:684,861` (segment) and `R:1535` (batch remaining) | absent (S-DC) | absent | absent | absent | `sequel-writing` `sh:sequel-writing:56` | next chapter via context pack (README) | next chapter in `generate_story` only | absent (chapters fixed at `driver.py:107`) |
| sequel (new story, same canon) | absent (S-HUO) | absent | absent | absent | absent | `canon-import` canon mode, `review-spinoff` (continue/complete the original) `sh:canon-import:61-66` | absent (S-NSA) | absent | absent; `CanonBranchType` has `NARRATIVE_BRANCH` + `parent_version_id` (`r2/contracts/narrative.py:76,392-399`), unused by story |
| character bible from existing text | `rebuild` cards/ledgers `NC:621`, `R:550` | graph extraction `event_extractor.py:48`, cast `PL:46` | absent | absent | `character_extractor.py`, `global_information_planner.py:220` | `character-extraction` | memory extraction `schemas.ts:210` | persona files (generated, not extracted) | absent for imported text (bible is generated `story_bible` node `pipeline.py:25`) |
| world / plot ledger | `world_bible`, `plot_ledger`, `causal_chain` `R:1589` | Cognee graph (`ING:296`) | research brief only | absent | event list `event_extractor.py` | 15 truth files, `world-extraction` | graph triples, timeline, states | event DB + faiss | Canon genesis + locked facts (`commit.py:262`, `audits.py:117`) |

### 2.2 Rewriting, variants, adaptation

| Capability | HUO | DC | OM | TAKE | VM | SH | NSA | SB | AR |
|---|---|---|---|---|---|---|---|---|---|
| rewrite variant by human instruction | absent (S-HUO); only per-chapter revision via audit loop | absent (S-DC); only `rewrite/generate` with numeric params `CT:112` | absent | absent | `user_requirement` free text to scenes `screenwriter.py:36-44` | absent for stories; `chapter-revision` for audit findings | `style-revise` | absent | `revise(target, note)` `service.py:397` regenerates node + closure |
| automatic variant by profile (genre / market / POV / tone / age) | genre skill packs (18) `SK:novel_*/<genre>` select style at first write; no re-genre of a finished book (S-HUO) | `narration_style` and beats params `schemas.py:154`; no genre/market (S-DC) | absent | absent | audience and genre in requirement (free text) | `canon-import` modes (au/ooc/cp) only | absent | absent | `StorySeed` has genre, tone, pov (`prompts/schemas.py:35-44`) but chosen once at seed |
| style transfer | genre skill + `ai_dehumanizer` | absent | absent | absent | absent | `style-learning` (stats) + `style-polishing` | style bible + `styleRevision.ts:16` | absent | `style_bible` node generated, not learned from text |
| condense / expand | `ensureNovelChapterWithinLength` `novel-prose-polish.ts:164`; floor `enforceAssembledLengthFloor` (stage doc) | rewrite to `target_beats` `CR:162` | absent | absent | `novel_compressor.py:49` (merge chunks) | `length-normalizing` `sh:length-normalizing:36` | absent | absent | scene length window + normalizing (`driver.py:1423`, `checks.py:SceneLengthWindow`) |
| novel to screenplay | `drama_script_formatter` `SK:drama_script_formatter/SKILL.md:1-40` | rewrite + literal script `CR:162`, `literal_script_writing.py:382` | absent | script.md to shots only | `write_script_based_on_story` `screenwriter.py:145` | absent (S-SH) | absent | absent | `episode_adaptation` step, screen mode (ADR 0114; `lib/episode_adaptation.py:217,380`) |
| dramatization (narration to dialogue/action) | formatter: dialogue drives conflict, narration compressed | rule: dialogue lines as `speaker+manner: “quote”` `CR` | cinematic script: sparse dialogue (`script-director.md:28`) | absent | filmable concrete actions `screenwriter.py` | absent | absent | absent | drama adaptation lines narration/dialogue/voiceover/action (ADR 0114 item 3) |
| dialogue polishing | humanize hook (prose, not dialogue-specific) | verbatim-quote rule | absent | absent | `script_enhancer.py:10` (dead code) | `review-dialogue`, `review-group-character` | absent | absent | ANTI_AI + CHARACTER audits (`audits.py:107-114`) |
| multi-language translation | absent (S-HUO) | language detect, names verbatim `source_language.py:99` | `localization-dub` script `script-director.md:14` | absent | absent ("output language same as input") | absent (S-SH) | absent | absent | absent; story prompts Vietnamese-only (`prompts/planning.py:13`) |
| AI-tone removal | `ai_dehumanizer`, detect+loop `NM:59-125` | absent | absent | absent | absent | `anti-detect`, `review-anti-ai` | absent | absent | `anti_ai_findings` `audits.py:497` |

### 2.3 Planning, hooks, quality

| Capability | HUO | DC | OM | TAKE | VM | SH | NSA | SB | AR |
|---|---|---|---|---|---|---|---|---|---|
| episode planning | drama episodes per novel chapter, one-call pipeline (stage doc) | `plan_episodes` + reviewer + fixer `EP:295`, `RV:225` | pipeline stages, not episodes | absent | scenes per event | absent | absent | absent | `episode_plan` + ADR 0114 adaptation |
| cliffhanger / hook design | `novel_outline/chapter_hooks` `SK:...:1-6`, craft hard fails `novel-commercial-appeal-audit.ts:640` | `EpisodePlan.cliffhanger` `PL:46-75` | hook types `storytelling.md:86` | absent | absent | `review-reader-pull` | absent | absent | adaptation cliffhanger + first spoken line at most 6 s (ADR 0114 item 4) |
| title / synopsis / selling points | `generateNovelTitle` `NW:199`; `generateDramaSynopsis/Title` | absent | absent | absent | story has title (`screenwriter.py:20`) | `short-packaging` `sh:short-packaging:40-93` | absent | title generation `storyteller.py:191` | `packaging` node (`pipeline.py:31`) with blurb faithfulness check (`audits.py:529`) |
| continuity check | `R:414`, rewrite loop, min 78 `NM:25` | plan-level only `RV:301` | absent | schema validate only | absent | `review-continuity`, `review-long-span` | model + hard rules `hardRules.ts:14` | absent | CONTINUITY audit with locked facts (`audits.py:117`) |
| consistency repair | continuity patch/deterministic fix files (`services/novel/novel-continuity-patch.ts`, `...-deterministic-fix.ts`) | `episode_fixer.py:378` (plan) | revision limit 3 | absent | absent | `chapter-revision`, `truth-sync` | style-revise uses report | absent | `_repair_once` span repair `driver.py:852`, at most 2 chapter cycles |
| length control | band + floor (stage doc) | beat chars 14-20 `schemas.py:155-157` | duration caps | shot duration | requirement text | 3000/10000 + 25% floor | absent | absent | scene window + story total window (`driver.py:158,1423`) |
| change records / audit trail | chapter change record `novel-change-record.ts` | task state | decision log `schemas/artifacts/decision_log.schema.json` | `source` field | absent | snapshots, audit record (`src/shenbi/audit/`) | continuity_reports table | DB | node heads + fingerprints + intents (`pipeline.py:121-140`) |

---

## 3. Gaps in ArcReel today (FACT from S-AR)

1. A run starts only from `StoryBrief(idea, genre, target syllables)` (`driver.py:158-170`); every node is generated. There is no way to enter the graph with existing text.
2. The story is fixed at 3 chapters and 7000-11000 syllables (`driver.py:107,158`); `build_graph` already takes any `scenes_per_chapter` list (`pipeline.py:53`), so growth is a parameter, not a redesign.
3. `revise(target, note)` (`service.py:397`) applies a Human note to one node and its closure; there is no structured variant spec, no fork that keeps the original, and `retry` only resumes blocked runs (`service.py:415`).
4. Seed fields `genre`, `tone`, `pov` exist (`prompts/schemas.py:35-44`) but language is Vietnamese-only (`prompts/planning.py:13`).
5. Canon supports `MAIN` and `NARRATIVE_BRANCH` with parent version (`r2/contracts/narrative.py:76-79,392-399`), but the story commit creates only `MAIN` (`commit.py:268-274`).
6. Episode adaptation (ADR 0114) assumes the story is the source; it is agnostic to whether the story was written or imported, which is what makes feature (a) cheap.

---

## 4. Recommended design for the three new features

Principle (INFER from all of the above): all three are **different entry points to the same node graph**, not new engines. A node head can be
`GENERATED` (today), `IMPORTED` (adopted from text, with source locators) or `HUMAN_EDITED`; the fingerprint machinery
(`pipeline.py:121-140`) then keeps imported nodes fresh and regenerates only what is stale. Donors differ on how much to trust the model; adopt the strict ones.

### (a) Automatic run from an existing story (skip writing)

New front door `import_story` that produces `seed`, `story_bible`, `style_bible`, `outline`, `chapter_plan[c]` and `scene_draft[c,s]` heads from supplied text, then joins the existing audits, packaging, manifest and the `episode_plan` to `episode_adaptation` flow unchanged.

| Step | Adopt | Evidence |
|---|---|---|
| Accept `.txt/.md/.docx`, UTF-8/GBK, normalize line endings | DC loader | `document_parsers.py:9-11,60-90` |
| Chapter detection (incl. Chinese numerals; Vietnamese `Chương N` to add) with a **preview and format check before any model call**, single-chapter fallback | DC | `chapter_detector.py:20-245`, `screenplay_quality.py:348`, `ING:169-274` |
| Language/script detection, names kept verbatim | DC | `source_language.py:30-112` |
| Split chapters into scenes at deterministic boundaries first (blank-line/time/location cues); LLM only to label, never to rewrite text | DC literal rule "line text preserved, LLM adds metadata only" | `literal_script_writing.py:1-10` |
| Reverse extraction in passes: parse, characters, world, plot, foreshadowing, style, highlights, state; **zero guessing, every item carries chapter+paragraph, unconfirmed items marked** | shenbi | `sh:import-analysis:53-59` |
| Per-chapter state/ledger extraction, content-hashed, skip unchanged; batch rebuild | HUO | `NC:469-660` |
| Fact provenance: extracted vs inferred, inferred at most 20% and tagged | shenbi truth-sync | `sh:truth-sync:59` |
| Style fingerprint by statistics only (no LLM) to fill `style_bible` and later to detect drift | shenbi | `sh:import-analysis:58` |
| Extracted Canon is a **proposal**; the Human approves once (existing manifest/approval point), conflicts listed for arbitration; imported text stays authoritative | shenbi (suggestion state, human approval), truth-sync | `sh:import-analysis:57`, `sh:truth-sync:55-56` |
| Audits run in **audit-only** mode on imported scenes (report, no rewrite), because "do not rewrite history" and ADR 0114 "story never shortened"; findings feed adaptation constraints | shenbi, ADR 0114 | `sh:sequel-writing:62`, ADR 0114 item 1 |
| No length gate on imported story (its length is a product fact); `story_target_syllables` window applies only to generated runs | ADR 0114 | ADR 0114 item 1 |
| Packaging node (title, blurb, selling points) still runs; multi-version output with evidence | shenbi short-packaging, AR packaging | `sh:short-packaging:51-57`, `pipeline.py:31` |

Automation: fully automatic after upload; one Human touchpoint (canon proposal) can be waived by a profile flag, but the preview/format check
failing (no chapters detected, scene headers missing for screenplay input) should block with a typed reason, as DC does (`ING:296-`).
Risk: extraction quality on long novels. Measure before promising: **UNKNOWN** for all donors (no published accuracy).

### (b) Continuation of an imported or own story

Two modes, both reusing the node graph:

1. **Extend (same story):** append `chapter_plan[c+1..]` and their scenes to the same run/Canon `MAIN` as a new Canon version; `build_graph` already supports more chapters, `scene_draft` already depends on all earlier drafts through the compiled context (`pipeline.py:61-70`).
2. **Sequel (new story, same world):** new project/run whose Canon branch records `parent_branch_id`/`parent_version_id` (`CreateCanonBranch`, `r2/contracts/narrative.py:392-399`) and whose seed is built from the parent's ending state.

Mechanisms to adopt:

| Mechanism | Donor evidence |
|---|---|
| Breakpoint must be an audited and settled head (committed version, not a draft); never edit committed text | `sh:sequel-writing:58,62` |
| Rebuild context from the Canon version, not from memory: world state, relationship matrix, emotional arcs, active hooks and thread map, style fingerprint, current focus | `sh:sequel-writing:77-86` |
| Ask the Human whether intent/direction changed before drafting (one prompt, recorded as an intent on `outline`) | `sh:sequel-writing:60,88-95`; AR `add_intent` (`runtime.py:419`) |
| Drift detection on the first 3 new chapters against the last N=5 (style stats, settings) | `sh:sequel-writing:61,97-99` |
| Canon-lock prefix of last-known state injected at generation (reminder, key actions, protagonist knowledge, relations, realm) | `NC:141-170` |
| Previous chapter tail and older summaries scaled by chapter number; seam handling so a new chapter does not replay the previous opening | `NC:172-230,274`; `services/novel/novel-chapter-seam.ts` |
| Retrieve relevant earlier facts per scene (graph facts + keyword + vector; or FAISS k=5 per plot point) | `contextPack.ts:16-18`; `storyteller.py:401-435` |
| Chapter summary chain plus periodic distillation (arc synthesis every 12 chapters) so context stays bounded | `storyteller.py:437`; `sh:memory-distill` frontmatter |
| Hook ledger with lifecycle (plant, track, recall overdue, resolve) so continuation pays off earlier threads | `sh:foreshadowing-*`; HUO `plot_ledger` (`R:1589`) |
| Outline extension with gap-patch and phased generation beyond 30 chapters | HUO (stage doc section 2, `NW:555-642`) |
| Per-chapter change record (trigger, process, outcome) appended to Canon | HUO `novel-change-record.ts`, README.md:22 |
| Only accepted chapters write memory; drafts never update canon | NSA README; AR commit manifest already behaves this way (`commit.py:262`) |
| Length of a continuation chunk is a parameter (HUO default 800 chars per segment, `NM:21`); keep the scene window, raise chapter count (`driver.py:107`) | HUO, AR |

Imported stories need (a) first, so continuation always starts from an approved Canon head. Own stories already have one.
Budget caution: HUO allows up to 30 continuity rewrites per chapter (`NM:169-190`); keep AR's cap of two chapter cycles (`driver.py` header) and add a stagnation abort instead.

### (c) Variant fork of a finished story

Define a **variant spec** (structured, digest-bound like `StoryBrief`): `keep` (plot spine, character set, ending, chapter order), `change` (style, tone, POV, genre, market, age rating, language), `scope` (surface or structural), `source_version` (Canon version id), and `origin` (human instruction text or profile id). Fork = new run on a new Canon `NARRATIVE_BRANCH` with `parent_version_id = source_version`, original untouched.

| Variant scope | Starting node | What stays | Donor mechanism |
|---|---|---|---|
| Surface (style, tone, POV, language, age-rating softening) | re-draft `scene_draft` from the same `chapter_plan` (keeps events) | outline, chapter plans, locked facts | style bible swap + `style-revise` using the continuity report (NSA `styleRevision.ts:16`); `style-polishing` "no plot or character change" (`sh` frontmatter); `anti-detect`, humanize loop (HUO `NM:59-125`) |
| Structural (genre, market, ending direction) | regenerate `outline` and below with the spec as an intent on `seed`/`outline` | characters and canon facts the spec lists in `keep` | shenbi `canon-import` modes: explicit keep-and-change list, no silent mixing, deviations declared (`sh:canon-import:51-68`); genre skill packs (HUO `SK:novel_*/<genre>`) |
| Language | translate per chapter after the surface pass | names, glossary, protected terms | OM localization-dub glossary and protected terms with per-language review status (`script-director.md:32-41`); DC names verbatim (`source_language.py:99`) |

Fidelity safeguards (the part donors do worst; this is the quality bar for "at least as flexible"):
- A variant must realize the same chapter-plan beats: reuse the MEMO_COMPLIANCE audit (`audits.py:107-114`) against the **source** plan; shenbi's equivalent is `review-memo-compliance` and, for forks, `review-fanfic`/`review-spinoff` (character fidelity, main-story consistency, `sh` frontmatter).
- Canon facts in `keep` become locked facts in the variant (AR already feeds locked facts to CONTINUITY, `audits.py:117`); facts in `change` are replaced explicitly so the audit does not flag them.
- Length: same scene window; condense/expand only with a double floor (at least absolute minimum and at least 25% of original) and no event added or removed (`sh:length-normalizing:36,59-62`).
- Surface variants must be cheap: nodes whose fingerprint inputs do not change are kept (`pipeline.py:121-140`), so a POV swap regenerates scenes but not bible or plans.

Automatic variant by profile: a profile is a named variant spec plus a prompt/skill pack. Evidence that the pack model works: HUO loads per-genre skill directories for premise, outline, brief and chapter writer (18 genres), and its `compliance` skill is the age-rating/market guardrail (`SK:novel_chapter_writer/compliance/SKILL.md`); DC exposes `narration_style` and beat parameters as per-project profile fields (`project_config.py:29`). Recommended profile fields: genre, tone, POV, language, market (platform tag system, cf. shenbi tags `sh:short-packaging:89-93`), age rating (compliance rule set), length target, hook intensity. Profiles apply the same fork machinery without a human note; a human note is the same spec with `origin = instruction`.
Run both kinds through the existing Human touchpoints: fork is offered like any manuscript (single approval), original remains committed.

### What not to adopt

- StoryBox character simulation (cost, no continuity audit; ADR 0114 excludes it) and VM `ScriptPlanner`/`ScriptEnhancer` (dead code, S-VM).
- shenbi 0-100/94/G0-G7 gates: they test the skills, not produced chapters (stage doc section 2).
- HUO 30-rewrite default and its Chinese-web-fiction craft heuristics (hate/thrill/urgency/hope beats) as universal rules; keep them as an optional genre profile.
- DC `planning_mode="ai"` (no current UI uses it, `cognee/tools.py:19-20`) and TAKE's "no LLM for analysis" rule (an agent-runtime choice, not a quality mechanism).

### Suggested order (INFER; effort is my estimate)

1. Parameterize chapter count and syllable window; add `IMPORTED` head source (small).
2. Import front door with preview, chapter/scene splitter, reverse extraction passes, canon proposal (medium; highest value, enables (b) and (c) on foreign stories).
3. Extend mode of continuation with Canon-lock, summary chain, hook ledger (medium).
4. Variant spec and `NARRATIVE_BRANCH` fork, surface scope first (medium), then structural and language.
5. Packaging multi-version and platform tags (small).

## 5. Unknowns

- Extraction accuracy and cost per chapter for any donor: not published; measure on ArcReel fixtures before committing to an SLA.
- HUO frontend import and humanize UI (`workbench/`) not read; SH skill bodies for 68 skills not read; SH `market-radar` body not read; BUT `story_architect` still unread (carried over from the stage doc).
- Whether Canon `NARRATIVE_BRANCH` is intended for story variants: type exists, no story use found in S-AR (INFER only).
