# Donor inventory: content forms, story genres, video output types

Date: 2026-11-15. Read-only research. Labels: **FACT** = read in source at the pinned checkout (path:line), **PER-DOC** = taken from an existing repo research doc (not re-read), **UNKNOWN** = not established.

Roots used in citations:
- HH = /home/anhtuan/content-os-r1-8/work/huohuo-drama (f104b85)
- OM = /home/anhtuan/content-os-r1-8/work/OpenMontage (08e2151)
- TK = /home/anhtuan/content-os-r1-8/work/take (47c1721)
- DC = /home/anhtuan/.cache/r2-donors/dramaclaw-full (b299bfd); code under src/novelvideo/
- VM = /home/anhtuan/ViMax (63bb9c7)
- SB = (shallow clone of ThomasChangX/shenbi) (10efa7c); NS = (clone of YfengJ/novel-studio-ai) (9b690ae); BX = (clone of amcghm/StoryBox) (ba24ff6)
- Docs = /home/anhtuan/content-production-os/.worktrees/r2-film-quality/docs/research/

Scope note: the pinned ViMax checkout (63bb9c7) differs from the commit named in the 11-13 doc (fd4b72e7); everything below about ViMax is from the 63bb9c7 tree.

---

## 1. Per-donor inventory

### 1.1 huohuo-drama (HH) - short drama + web novel workbench

**Input forms (FACT)**
- Raw prose / novel text to formatted script (`agent-skills/drama_script_formatter/SKILL.md`; README.md:24, 40 "Novel -> short drama": import chapters or a whole AI novel, rewrite into screenplay, storyboard, video).
- Idea / premise to AI novel via brief -> chapter -> consistency review (README.md "Digital Writer"; `agent-skills/novel_premise|novel_outline|novel_writing_brief|novel_chapter_writer`).
- Uploaded cast images, uploaded references (README.md "Cast & locations - AI portraits, uploads").
- AI-text detection accepts text, file, audio, video (README.md:52 caption; route `workbench-server/src/index.ts:98` `/ai-detect`). This is a compliance tool, not a production input.
- No existing-video remix, no product/URL input found.

**Story genres (FACT)**
- 21 genre entries in `workbench-server/src/common/novel/novel-genre-registry.ts:15-173`, 18 `active`, 3 `planned` (都市文, 高武文, 历史文). Values: 脑洞, 末世, 诡异, 科幻, 游戏, 言情, 仙侠, 虐恋, 玄幻, 种田, 官场, 穿越, 异能, 校园, 悬疑, 武侠, 谍战, 驱魔 (+3 planned).
- Genre machinery: one Skill folder per genre under each of the four novel agents (premise, outline, writing_brief, chapter_writer), loaded by `novel_genre_skill_key` so only cross-cutting + one genre skill enter the prompt (`workbench-server/src/agents/skills.ts:5,95-96`). Chapter_writer additionally has `serial_pulse`, `stage_beat`, `scene_drama`, `chapter_role`, `compliance`, `continuity` cross-cutting packs. Cultivation-power special case at `workbench-server/src/agents/novel-defaults.ts:26`.
- Serial form: causal-chain "Change Record" at each chapter end + four-layer memory (README.md:~118 "Novel mode").
- Film genre is not separate: drama style is a visual style, not a genre pack.

**Output video types (FACT)**
- Two pipelines per episode (README.md:66): (a) AI image-to-video; (b) "frame slideshow" = keyframe sequence + FFmpeg Ken Burns (`workbench-server/src/services/drama/compose-ffmpeg.ts:231` zoompan; default 1920x1080 at :243-244), clip length aligned to TTS length, BGM.
- I2V providers: MiniMax, Volcengine Seedance (`doubao-seedance-1-5-pro-251215`, `services/ai/ai-config-service.ts:30`, `adapters/volcengine-video.ts:9`), Vidu (`viduq3-turbo`, `adapters/vidu-video.ts:63`), Ali Wan (`wan2.6-i2v-flash`, `adapters/ali-video.ts:11`). All image-to-video (lead frame), per shot, clip then per-shot FFmpeg mux and episode merge (`episode-merge-service.ts`).
- Voice: per-character voice assignment (`agent-skills/drama_voice_assign`), TTS = MiniMax only (README.md:113), dialogue lines parsed `speaker: text` with SKIP list for narration-less/SFX lines (`services/drama/compose-dialogue.ts:2-18`). Multi-speaker yes; voice cloning not found; lip sync not found (grep hits were only "alipay").
- Aspect ratio: per-request `aspect_ratio` (default 16:9 in `services/media/video-generation.ts:42`; 9:16/1:1/3:4/2:3 mapped to 720P for Wan `ali-video.ts:34`). 9:16 is selectable, default landscape.
- Subtitles/music/SFX: BGM in slideshow path (README.md:16 area); SFX only as parsed "ignorable" tokens. Subtitles: UNKNOWN.
- Episodic: yes, per-episode workbench, templates gallery (README.md:67), no explicit cliffhanger machinery found.

**Visual styles (FACT)**: `workbench-server/src/common/drama/drama-style.ts` catalog of 34 styles (realistic, cinematic, anime, digital art, watercolor, pixel art, paper-cut, cyberpunk, steampunk, dieselpunk, solarpunk, lunarpunk, biopunk, atompunk, gothpunk, retrofuturism, synthwave, vaporwave, sci-fi, fantasy, dark fantasy, gothic, surrealism, chinoiserie, Dunhuang art, sumi-e, impressionism, expressionism, cubism, pop art, minimalism, maximalism; lines 26-77), bilingual cn/en labels, preview SVGs (`drama-style-previews.ts`).

**Character consistency (FACT)**: cast reference sheets (`character-reference-sheet-prompt.ts`), per-character "forms" (outfit/age variants, `character-form-route-service.ts`), grid split/assign storyboard (`grid-split.ts`, `grid-workflow.ts`), reference images passed to image model.

**Languages (FACT)**: UI i18n en, zh-CN, vi, fil (`workbench/app/i18n/messages/`), READMEs zh-CN/zh-TW/ja/th/vi/ru. Prompts and genre packs are Chinese-only (webnovel idiom: 爽文 style rules in `agents/webnovel-prose-style.ts:134`). Output language for the drama: follows input (UNKNOWN beyond that).

### 1.2 OpenMontage (OM) - agentic video production, mostly non-fiction

**Input forms (FACT)**
- Topic / idea prompt (pipeline `animated-explainer`, `pipeline_defs/animated-explainer.yaml:3`).
- Existing video: YouTube video/Short/Reel/TikTok URL or local clip as reference for analysis (README.md:131-145; tools `video_downloader.py`, `video_analyzer.py`, `scene_detect.py`, `transcriber.py`).
- Raw talking-head footage (`pipeline_defs/talking-head.yaml:3-7`).
- Long-form (webinar/stream/interview) to N short clips (`clip-factory.yaml:3-6`).
- Podcast audio/video to audiogram/captions/quote clips (`podcast-repurpose.yaml:3-7`).
- Existing source video to translated subtitles + dubbed audio + optional lip-synced variants (`localization-dub.yaml:3-6`, beta).
- Screen recording or live capture (`screen-demo.yaml:3-8`; tools `screen_recorder.py`, `cap_recorder.py`).
- Supplied footage/stills for brand film or trailer (`cinematic.yaml:3-8`); source footage + generated inserts (`hybrid.yaml:3-6`).
- Stock/archive retrieval corpus (Pexels, Archive.org, NASA, Wikimedia, Unsplash) with CLIP retrieval (`documentary-montage.yaml:3-9`).
- No novel, no screenplay input, no long serial.

**Genres/types (FACT)**: none for fiction. Content kinds are explainer, documentary montage, brand film/trailer, product promo, kinetic typography/math/diagram animation, screen demo, spokesperson, talking head. Story craft is explainer-arc only (`skills/creative/storytelling.md:1-12`). Narrative animation appears only as example prompts ("Pixar-style animated short" README.md:87; "anime-style animation of an underwater temple" README.md:346).

**Output video types (FACT)** - 12 pipeline defs in `pipeline_defs/`:
1. animated-explainer (generated stills/clips + TTS narration + music + captions)
2. animation (motion graphics, kinetic type, math via ManimCE, Three.js worlds)
3. character-animation (local reusable cartoon characters, rigged SVG/Canvas/Remotion/HyperFrames, deterministic, not remote video-gen; `character-animation.yaml:3-8`; `ink-theater/` black-ink mascot style, `skills/creative/ink-theater.md:1-12`)
4. avatar-spokesperson (digital presenter, lip sync, `avatar-spokesperson.yaml:3-8`)
5. cinematic (trailers, brand films, 3D fly-through)
6. clip-factory, 7. documentary-montage, 8. hybrid, 9. localization-dub, 10. podcast-repurpose, 11. screen-demo, 12. talking-head.
- Video-gen providers (`tools/video/`): Kling (t2v+i2v `kling_video.py:45-48`; official + Omni `_kling/`), Seedance (ark/replicate/fal), Veo, Sora, Runway, MiniMax, Grok, Hunyuan, Wan, LTX (local/modal), CogVideo, Higgsfield, Jimeng, HeyGen, Gemini Omni, ComfyUI.
- Composition: Remotion (React, word-level TikTok captions, TalkingHead composition) and HyperFrames (HTML/GSAP) (README.md:297-298, 617-618). When no video-gen provider exists, stills + Remotion motion (README.md:617).
- Audio: TTS (ElevenLabs incl. cloning `elevenlabs_tts.py:54`, Google 700+ voices/50+ languages, Azure, OpenAI, Piper local, DashScope, Doubao, Fish, Kling TTS), music (Suno, ElevenLabs, Google, Pixabay, Freesound), SFX (ElevenLabs), mixer, loudness. Voice cloning: ElevenLabs true; DashScope and Doubao false (`dashscope_tts.py:60`, `doubao_tts.py:54`).
- Lip sync / avatars: `tools/avatar/lip_sync.py` (Wav2Lip, :31), `talking_head.py` (SadTalker, :34), `kling_avatar.py`, `kling_lip_sync.py`.
- Aspect ratios and platform profiles (README.md:641-654): 16:9 1080p, 4K, 9:16 Shorts/Reels/TikTok, 1:1 Feed, 21:9 cinematic.
- Durations: example outputs 30-100 s (README.md:87-117); no episode/series concept.
- Subtitles: `tools/subtitle/subtitle_gen.py`, Remotion captions, WhisperX skill (`skills/core/whisperx.md`).

**Visual styles (FACT)**: 5 playbooks in `styles/`: anime-ghibli, clean-professional, flat-motion-graphics, minimalist-diagram, premium-minimalist (`styles/*.yaml`; anime-ghibli identity `best_for: Narrative animations...` line 6). Plus `ink-sketch`.
**Character consistency (FACT)**: per-model prompting dialect files (`skills/creative/prompting/seedance|veo|sora|ltx|grok|hunyuan-prompting.md`); `skills/creative/prompting`-level identity phrases (per doc, see 11-13 VGA row); local rigged characters for repeatability.
**Languages (FACT, partial)**: localization-dub pipeline "10 languages" (README.md:398), Google TTS 50+ languages (README.md:554). Pipeline prose is English.

### 1.3 take (TK) - script to storyboard and clips

**Input forms (FACT)**: screenplay / story / script text as `script.md` (`skills/take/SKILL.md:3-10,31-34`). Nothing else.
**Genres (FACT)**: none; genre-agnostic. Beat schema has `emotion` only (`packages/core/src/schemas.ts:12`).
**Outputs (FACT)**: storyboard (beats -> shots with controlled shot size/angle/movement vocab, `schemas.ts:28-60`), images via GPT-image-2, video clips via Seedance 2.0/2.5 primary, MiniMax H3 fallback (`skills/take/references/model-routing.md:7,20-23,28`). Explicit non-goals: final edit/post, audio (SKILL.md "DO NOT USE": no editing/post). No TTS, no dialogue audio, no music, no lip sync in the package. Clips are per shot 5/10 s (`packages/provider/src/seam.ts:45`).
**Aspect ratios (FACT)**: `16:9, 9:16, 1:1, 4:3, 21:9` (`schemas.ts:66,75`).
**Styles/consistency (FACT)**: free-form `style` string and `visual.characterRefs` / `styleRef` per shot (`schemas.ts:17-21,67`); no presets.
**Languages**: UNKNOWN (agent-native; SKILL.md in Chinese, README in English).

### 1.4 dramaclaw (DC) - novel/screenplay to short-drama series + infinite canvas

**Input forms (FACT)**
- Novel manuscript and screenplay; Fountain screenplay supported (README.md:191 "Structured ingest"; `utils/screenplay_scene_parser.py`, `utils/screenplay_quality.py`).
- Two spine templates: `drama` (screenplay-like, default) and `narrated` (prose novel narration) (`project_config.py:38-40,165,453`).
- Images, video, audio, 3D, scripts as canvas nodes (README.md:170-180, "18 node types"); reference images/videos/web links as omni-reference; reference image to extract a project-wide style (README.md:198 "Visual Style").
- Existing video: shot analysis, video edit/erase/upscale/audio-separation tools on canvas (README.md:175 "Video tools"). Recap/commentary of existing video: not found.

**Genres (FACT)**: no story-genre packs for writing. Genre-like looks appear only as visual style templates: `freezone/style_templates.json` has 45 "short-drama looks" including period_idol, palace_intrigue, wuxia, cn_urban, urban_romance, crime_suspense, korean_muted, healing_life, youth_film, psychological_horror, neon_punk, hard_scifi, steampunk, chinese_myth, greek_myth, western_fantasy, western_cowboy, modern_warfare, documentary_realism, stop_motion, claymation, chinese_ink, ukiyo_e, shadow_puppet (key list read from file). Script modes adaptive / literal / staged with review-repair (README.md:193; `workflows/script_writing.py`, `literal_script_writing.py`).

**Output video types (FACT)**
- Vertical-first short drama: default aspect ratio 2:3 for drama, 16:9 for narrated (`project_config.py:35-40`). Image catalog ratios up to 21:9/9:16 (`official_media_models.json`).
- Per-beat shots: sketch -> first frame -> video generation -> voiceover -> compose -> MP4 + subtitles/SRT + full asset pack (README.md:196; `docs/en/concepts/features.md:23`).
- Video models in catalog (`official_media_models.json` mediaModels keys): seedance-2.5, 2.0, 2.0-fast, 2.0-mini, 1.5-pro, 1.0-pro-fast, wan3.0-video(-prime), MiniMax-H3, happyhorse-1.0/1.1; images: gpt-image-2 alias (LingShan-G2), Nano Banana 2/Pro, Seedream 4.5/5.0.
- Dialogue and voices: `seedance2_i2v/` pipeline parses `Speaker: line` for Seedance 2.0 voice references (`spoken_dialogue.py:12-19`), has voice clone and reference voices (`voice_clone.py`, `voice_reference_service.py`, `character_voice_storage.py`), narration audio (`narration_audio_task.py`), IndexTTS2 per-beat audio (`audio/indextts2_beat_audio_task.py`), narration style first_person/third_person (`project_config.py:29,34`). So: multi-speaker dialogue, narration, voice cloning = yes. Lip sync is the video model's native audio (Seedance 2 voice-reference), no separate lipsync tool found.
- Episode series with multi-episode arcs and beat planning (README.md:193); cliffhanger machinery not read (UNKNOWN).
- Spatial consistency: Director World, image -> 3D Gaussian splat set, 360 panoramas (README.md:180).
- Music generation as audio node (README.md:175). SFX: script format carries sound-effect lines (features.md "unified script format"); generation UNKNOWN.

**Visual styles (FACT)**: 6 project presets `styles/presets/` anime, chinese_period_drama, guoman_fantasy, post_apocalyptic, realistic, republican_era_drama (each has `style_instructions`, `avoid_instructions`, `style_tag`, `style_family`, `animation_subtype`); 45 style-wall looks (above); reference-image style extraction.
**Character consistency (FACT)**: asset library with stable identities across episodes, portraits and per-episode variants, three-view prop sheets (README.md:189; features.md "Characters and Props"); scene variants/360.
**Languages (FACT)**: UI i18n en + zh (`frontend/src/i18n/`, `frontend/public/locales/en|zh`); backend emits Chinese text plus i18n codes (`i18n_message.py:3-11`); docs en/zh.

### 1.5 ViMax (VM) - idea/script/novel to multi-shot video

**Input forms (FACT)**
- Idea (`main_idea2video.py:5-18`), explicit screenplay with `NAME: (action) line` dialogue (`main_script2video.py:5-24`), long novel (`pipelines/novel2movie_pipeline.py:46`, README.md:82 "Novel2Video"), reference photo of person/pet for AutoCameo (README.md:83; no source file found for it in this tree, so FACT only at README level), uploaded files via Web UI (README.md:85).
- Not found: existing video, URL, audio input.

**Genres (FACT)**: none. Style and audience are free-text; screenwriter prompt adapts to audience "children, teenagers, adults" (`agents/screenwriter.py:23,81`). Output language = input language (`agents/screenwriter.py:54,100`).

**Output video types (FACT)**
- Multi-scene, multi-shot cinematic short: scene extraction, shot description with `motion_desc` + `audio_desc` fed together into the video model prompt (`pipelines/script2video_pipeline.py:547`), so audio/dialogue/SFX come from the video model's native audio (Veo 3.x, Seedance 2 Fast, Google Omni, via `tools/video_generator_*`). No separate TTS/lip-sync tool in `tools/` (list read).
- Camera-level continuity: reference images + first frames + camera image generator (`agents/camera_image_generator.py`, `reference_image_selector.py`, `best_image_selector.py`); dependency graph and anchors per paper (PER-DOC, sweep doc).
- Episodic adaptation via novel compression (`agents/novel_compressor.py`).
- Aspect ratio: landscape-first with guard that rejects portrait frames (`tools/image_orientation.py:9-27`); `allow_portrait` option exists. Durations: user_requirement string (e.g. "no more than 3 scenes / 15 shots", `main_idea2video.py:15`).
**Styles (FACT)**: free-text `style` ("Realistic, warm feel", "Anime Style", `main_idea2video.py:18`, `main_script2video.py:24`); no presets.
**Character consistency (FACT)**: `character_extractor.py`, `character_portraits_generator.py` (front/side/back portraits), reference selection; AutoCameo for real-person identity.
**Languages**: follows input (FACT above); UI zh/en readmes (readme.md, README_ZH.md).

### 1.6 shenbi (SB) - long-form Chinese web-novel writing framework (text only)

**Input forms (FACT)**: seed outline Markdown (`outline-example.md`, parsed by `src/shenbi/pipeline/seed_parser.py:185` for 题材/类型/genre); existing novel import (`skills/shenbi-canon-import`, `shenbi-import-analysis`); fanfic canon (`shenbi-review-fanfic`, `using-shenbi/SKILL.md:57`); spinoff/sequel (`shenbi-review-spinoff`, `shenbi-sequel-writing`, `using-shenbi/SKILL.md:62`); short story <30 chapters (`skills/shenbi-short-outline|short-drafting|short-packaging`); style learning from samples (`shenbi-style-learning`).
**Genres (FACT)**: genre is a free list in `novel.json` (e.g. 架空历史, 战争史诗, 穿越, 轮回, 轻喜剧, `outline-example.md:4`), with `shenbi-genre-config` (fatigue words, pacing, chapter types, audit dimensions per genre) and `shenbi-power-system`, `faction-builder`, `review-era`, `review-highpoint` for 爽点. Worldbuilding prompt names 玄幻/仙侠/都市/科幻/历史 (`shenbi-worldbuilding/SKILL.md:158`). No fixed pack catalog like HH.
**Output (FACT)**: novel text only (chapters, truth files, market packaging: `shenbi-market-radar`, platform split 起点/番茄 in `outline-example.md:1184`). Audio-drama friendliness is a note only (`outline-example.md:1184`). No video.
**Languages (FACT)**: hard-coded `novel_json["language"] = "zh"` (`seed_parser.py:220`). Chinese only.

### 1.7 novel-studio-ai (NS) - local long-fiction workbench (text only)

**Input**: project brief + preferred genre free text -> idea generation (`src/lib/ai/prompts.ts:8-26`, `ideateProject.ts:12`), word-count target (default 800000, `ProjectListClient.tsx:23`), POV (default 第三人称有限视角).
**Genres**: free-text field "类型，如玄幻/科幻/悬疑" (`ProjectListClient.tsx:161`); no genre packs.
**Output**: serialized novel chapters, story bible, style bible, outlines, memory/graph facts, Markdown/JSON export (`src/lib/export/`). No video.
**Languages**: Chinese UI/prompts; README en + zh-CN.

### 1.8 StoryBox (BX) - research simulation for long stories (text only)

**Input**: seeds in `data/story.json` (premise, setting, characters; ~20 premises such as time-freeze sci-fi) plus world.yaml sandbox per story (`data/story01/world.yaml`). No user prompt interface in README quick start.
**Genres**: model generates `story_type` and `story_themes` itself (`reverie/agent/storyteller.py:248,287`); no packs.
**Output**: long-form story JSON from agent simulation (README.md "Quick Start"); no video.
**Languages**: English prompts (`reverie/prompts/`).

---

## 2. Donors known only from repo docs (PER-DOC; source not read)

| Donor | Forms / types as the docs record them | Doc |
|---|---|---|
| Calliope (benjiyaya/Calliope, 6e0716f8) | ComfyUI-based film maker: LLM splits a scene into N coverage clips (shot_size wide/medium/closeUp/insert/overShoulder), dialogue-line coverage, latent chaining of clips with MiniMax H3 workflow, continuity ledger, character-consistency skill, per-model continuation prompts | 11-13 video-quality-donor-mechanisms rows 47,48,67-69 |
| AIVPE (ai-video-production-editor, a368af45) | Editor + director pass: shot-type vocabulary, per-shot context references by role (character/environment/prop/product incl. logo), world panorama mode, reverse-angle requests; product/ad references implied | same doc rows 50,70 |
| openfilm (4ba03625) | Coding-agent video: agent writes `film.html` with three.js/WebGL/canvas/SVG/CSS/GSAP/video; captions as per-word WebVTT; loudness master; look/contact-sheet check. Non-fiction/motion-design leaning (UNKNOWN for fiction) | rows 101,122,138,198 |
| OpenChatCut (OCC), open-edit (veedstudio) | chat-driven editors (existing-footage editing); forms not read | pinned list, same doc |
| VGA (Zulgo/video-generation-automation, e46e9d3c) | Same lineage as OpenMontage prompts: motion_led vs source_led delivery promise, slideshow-risk scorer, per-model prompt dialects (Seedance, Sora, Veo, Grok, LTX, Hunyuan, Wan, Runway) | rows 49,71-74,85-87 |
| MultiShotMaster (KlingAIResearch, arXiv 2512.03041) | Model-level multi-shot single-pass generation (research model); input is shot-level text + references | same doc, pinned list |
| Topview (docs.topview.ai) | Commercial API: Omni Reference (images and videos in prompt), Video Recast (motion transfer, object swap on source video 4-30 s, Seedance 2.5), Character Swap; product/avatar ad video family implied by the product, forms UNKNOWN | row 59 |
| DramaAgent (arXiv 2610.00097) | Multi-speaker dialogue drama clips with per-line emotion/delivery, ambience/BGM, K=3 candidate repair loop | 11-13 sweep doc, papers table |
| CineCrew (2609.07720) | FilmDSL clips with stable char/set refs, keyframe-first, last-frame chaining | sweep doc |
| FilmWorld (2607.19038) | Entity-state hash ids, world-state continuity | sweep doc |
| One Sentence, One Drama (2605.22144) | Idea to drama: multi-agent story debate, hook/ending/twist-density review, per-scene 360/3D, BGM selection | sweep doc |
| FRAMEWORKERS (2608.29814) | Director + audio sub-agents (narration, music, mix, ambience, translation); code unreleased | sweep doc |
| Jellyfish (Forget-C/Jellyfish) | Script breakdown to shared entity model (characters, scenes, props, costumes, dialogue); shot readiness; Apache-2.0 | sweep doc |
| AIDrama Studio (EvoLinkAI/ai-short-drama) | Novel -> script -> storyboard -> images -> videos -> voiceover; Kling/Seedance/Vidu/Veo/MiniMax, FLUX/Imagen, CosyVoice; 2-4 candidates per shot | sweep doc |
| InkOS, novel-agent, AI-Novel-Writing-Assistant | Text-only serial novel agents (state deltas, event ledgers, style assets, anti-AI) | sweep doc |
| Industry survey (Sora, Vidu, Kling, Seedance, Hailuo, Pika, Runway, Veo/Flow) | Model forms: reference-to-video 1-7 images (Vidu reference2video, Kling multi-image up to 7), first/last frame (Kling, Veo 3.1, Hailuo, Jimeng), storyboard editors (Sora, Flow Scenebuilder, Jimeng story mode, Runway Multi-Shot recipe); clip lengths 3-16 s | storyboard-to-video-industry-survey.md:1-40 |

Other repo docs (donor deep dive, stage mechanisms, writing capabilities, long-novel gaps) were not re-read for this inventory; run `grep -n` on them by donor name if a specific mechanism is needed.

---

## 3. Consolidated matrix

Legend: F = FACT (source read), D = PER-DOC, - = not supported/not found in what was read, ? = UNKNOWN.
Donor columns: HH huohuo, OM OpenMontage, TK take, DC dramaclaw, VM ViMax, SB shenbi, NS novel-studio-ai, BX StoryBox, +Docs = other donors (docs only).

### 3.1 Input forms

| Form | HH | OM | TK | DC | VM | SB | NS | BX | +Docs |
|---|---|---|---|---|---|---|---|---|---|
| Idea / one-line prompt | F novel premise | F explainer topic | - | ? | F main_idea2video.py:5 | F seed outline | F prompts.ts:8 | F story.json premise | D One Sentence One Drama, VM |
| Short story / short fiction | F script formatter | - | F script.md | F | F | F short-outline/drafting | - | - | - |
| Novel / long serial in | F README.md:24 | - | - | F README.md:191 | F novel2movie_pipeline.py:46 | F canon-import | - | - | D AIDrama Studio, Jellyfish |
| Novel / long serial out (text) | F Digital Writer | - | - | - | - | F | F | F | D InkOS, novel-agent |
| Script / screenplay | F | - | F | F incl. Fountain | F script2video | - | - | - | D Calliope |
| Existing video (analysis/reference) | - | F README.md:131 | - | F canvas shot analysis | - | - | - | - | D Topview recast, OCC, open-edit |
| Product / URL | - | F website-to-video HyperFrames README.md:298 | - | - | - | - | - | - | D AIVPE product refs, Topview |
| Reference images (characters/style) | F uploads | F | F characterRefs | F omni refs, style extract | F AutoCameo photo (README) | - | - | - | D most |
| Audio (podcast / speech) | - (AI detect only) | F podcast-repurpose | - | F audio node | - | - | - | - | - |
| Screen recording | - | F screen-demo | - | - | - | - | - | - | - |
| Fanfic / spinoff / sequel | - | - | - | - | - | F review-fanfic/spinoff | - | - | - |

### 3.2 Story genres and genre machinery

| Genre / type | HH | OM | TK | DC | VM | SB | NS | BX | +Docs |
|---|---|---|---|---|---|---|---|---|---|
| Xianxia / cultivation | F registry:63-71 packs | - | - | F visual look "wuxia"/"chinese_myth" only | - | F genre-config/power-system | free text | - | - |
| Xuanhuan / high-fantasy | F :79 | - | - | F look "western_fantasy" | - | F | free | - | - |
| Wuxia | F :135 | - | - | F look | - | free | free | - | - |
| Romance / angst romance | F 言情, 虐恋 | - | - | F look urban_romance, period_idol | - | free | free | - | - |
| Suspense / mystery / spy | F 悬疑, 谍战 | - | - | F look crime_suspense | - | free | free | - | - |
| Horror / weird / exorcism | F 诡异, 驱魔 | - | - | F look psychological_horror | - | free | free | - | - |
| Sci-fi / apocalypse / game-system | F 科幻, 末世, 游戏 | - | - | F look hard_scifi, post_apocalyptic preset | - | free | free | F premise sci-fi | - |
| Urban / campus / farming / officialdom | F 校园, 种田, 官场, 都市 planned | - | - | F look cn_urban, youth_film, healing_life | - | free | free | - | - |
| Historical / palace / republican era | F 历史 planned; 穿越 | - | - | F palace_intrigue, republican_era_drama preset | - | F era review | free | - | - |
| 爽文 / webnovel serial pulse | F serial_pulse, stage_beat packs | - | - | - | - | F review-highpoint, market-radar | - | - | - |
| Comedy / light | - | - | - | - | - | F "轻喜剧" tag | - | - | - |
| Children's | - | - | - | - | F audience adaptation screenwriter.py:23 | - | - | - | - |
| Educational / explainer | - | F explainer, storytelling.md | - | - | - | - | - | - | - |
| True crime / documentary | - | F documentary-montage | - | F look documentary_realism | - | - | - | - | - |
| Biography / how-to | - | F (explainer) | - | - | - | - | - | - | - |
| Interactive / branching | - | - | - | F "interactive series" in README compare table (claim) | - | - | - | - | - |

Genre-specific machinery that exists in source: HH only (per-genre Skill folders, premise/outline/brief/chapter agents; registry:15-173). SB has per-novel genre-config (fatigue words, pacing, audit dims). DC has genre as visual style template only. OM, TK, VM, NS, BX have no genre packs.

### 3.3 Output video types

| Output type | HH | OM | TK | DC | VM | SB | NS | BX | +Docs |
|---|---|---|---|---|---|---|---|---|---|
| Narration over stills / motion comic (Ken Burns) | F compose-ffmpeg.ts:231 slideshow + TTS | F Remotion stills when no video-gen (README.md:617) | - | F narrated spine (project_config.py:40) | - | - | - | - | - |
| Multi-character drama with dialogue | F per-speaker TTS compose-dialogue.ts | - | - | F Seedance2 voice refs spoken_dialogue.py | F audio_desc to video model | - | - | - | D DramaAgent, Calliope |
| Generated video clips i2v | F Seedance/MiniMax/Vidu/Wan | F many (Kling, Veo, Seedance, ...) | F Seedance 2.x, MiniMax H3 | F Seedance 2.5/2.0, Wan3, MiniMax-H3 | F Veo, Seedance 2 Fast, Omni | - | - | - | D AIDrama Studio |
| t2v | ? | F kling_video.py:45 | - | F "text/image/keyframe to video" README.md:175 | ? | - | - | - | - |
| Multi-shot continuity | F grid/forms | D VGA/OM prompting | F per-shot refs | F identity + Director World | F ref images + camera graph | - | - | - | D Calliope latent chain, CineCrew, FilmWorld, MSM |
| Short-drama vertical series (episodes) | F episodes; 9:16 selectable | - | - | F 2:3 default, multi-episode arcs | - | - | - | - | D One Sentence One Drama |
| Cliffhanger / hook mechanics | ? | - | - | ? | - | F chapter hooks (text) | - | - | D sweep doc (hook/ending/twist) |
| Anime / manga style | F style catalog | F anime-ghibli | free-text | F anime preset | F style text | - | - | - | - |
| Live-action / realistic style | F realistic, cinematic | F cinematic pipeline | free-text | F realistic preset | F style text | - | - | - | - |
| Music video | - | F Suno songs + montage (partial: music tools, no lyric-video pipeline read) | - | ? | - | - | - | - | - |
| Explainer / educational | - | F animated-explainer, animation | - | - | - | - | - | - | - |
| Ad / product video | - | F cinematic, hybrid, HyperFrames promos | - | - | - | - | - | - | D Topview, AIVPE |
| Podcast / talking head / avatar | - | F podcast-repurpose, talking-head, avatar-spokesperson | - | - | - | - | - | - | - |
| Slideshow | F | F | - | - | - | - | - | - | - |
| Trailer | - | F cinematic.yaml:3 | - | - | - | - | - | - | - |
| Recap / commentary of existing video | - | F clip-factory + reference analysis (clips and re-make, not commentary) | - | - | - | - | - | - | D Topview recast |
| Dub / localization of existing video | - | F localization-dub | - | - | - | - | - | - | - |
| Screen demo | - | F | - | - | - | - | - | - | - |

### 3.4 Audio and presentation

| Feature | HH | OM | TK | DC | VM | SB | NS | BX | +Docs |
|---|---|---|---|---|---|---|---|---|---|
| Narrator voice | F MiniMax TTS | F 10+ TTS | - | F narration_audio_task.py | model-native | - | - | - | - |
| Multi-speaker voices | F voice_assign | F | - | F | model-native | - | - | - | D DramaAgent |
| Voice cloning | - | F ElevenLabs only elevenlabs_tts.py:54 | - | F voice_clone.py | - | - | - | - | - |
| Lip sync | - | F Wav2Lip/SadTalker/Kling | - | F via Seedance voice refs (no separate tool) | model-native | - | - | - | D Topview |
| Music | F BGM | F Suno etc. | - | F music node | - | - | - | - | D One Sentence BGM selection |
| SFX | parsed only | F ElevenLabs SFX | - | script field, gen ? | model-native | - | - | - | - |
| Subtitles | ? | F Remotion/subtitle_gen | - | F SRT export | - | - | - | - | D openfilm per-word WebVTT |
| Avatars (digital presenter) | - | F | - | - | - | - | - | - | D Topview |
| Aspect ratios | 16:9 default, 9:16 etc. selectable | 16:9, 9:16, 1:1, 21:9 profiles | 16:9, 9:16, 1:1, 4:3, 21:9 | 2:3 default, 16:9, ratios up to 21:9 | landscape-first guard | n/a | n/a | n/a | - |

### 3.5 Styles, consistency, languages

| Dimension | HH | OM | TK | DC | VM | SB | NS | BX |
|---|---|---|---|---|---|---|---|---|
| Style presets | F 34 (drama-style.ts:26-77) | F 5 playbooks + ink-sketch | F free-text | F 6 presets + 45 looks + ref extraction | F free text only | n/a | F Style Bible | n/a |
| Character consistency | F ref sheets, forms | F local rigs, prompt dialects | F refs per shot | F identity library, variants, 3D world | F portraits + ref selection, AutoCameo | n/a | F character state versions | simulated personas |
| Languages | UI en/zh/vi/fil; prompts zh | English; dub 10 langs, TTS 50+ | ? | UI en/zh; backend zh | follows input | zh only (seed_parser.py:220) | zh | en |

---

## 4. How they do it (mechanism notes)

- **Genre packs (HH only):** registry of 21 genre entries; per-agent per-genre SKILL.md; agent loads only cross-cutting skills + the one genre skill (skills.ts:5,95). Premise/outline/brief/chapter each have genre-specific guidance, so the story form is steered by prompt packs, not code.
- **Webnovel audit (SB):** genre-config.json (fatigue words, pacing, chapter types, audit dimensions); T1/T2/T3 scoring; 8 gates; market-radar and platform chapter-length rules. Text only.
- **Narration over stills (HH, OM):** HH Ken Burns via FFmpeg zoompan, clip duration forced to TTS length (compose-ffmpeg.ts:231); OM Remotion stills with spring animation + captions.
- **Dialogue drama (DC, VM):** DC passes `Speaker: line` plus a per-character reference voice into Seedance 2.0 so lip-synced speech is generated by the video model (spoken_dialogue.py, voice_clone.py); VM folds `audio_desc` into the same video prompt (script2video_pipeline.py:547). HH does it the older way: separate TTS per line then FFmpeg mux (compose-dialogue.ts, compose-ffmpeg.ts).
- **i2v clips:** HH adapters to four vendors, one lead frame per shot; TK failover Seedance -> MiniMax H3 with a contract validator before generation; OM tool-registry of ~25 providers selected at runtime; DC catalog with Seedance 2.5 recommended.
- **Short-drama vertical series (DC):** 2:3 default, episodes from structured ingest, beat planning, adaptive/literal/staged script modes.
- **Non-fiction forms (OM only):** 12 pipelines each a stage graph (idea -> script -> scene -> assets -> edit -> compose -> publish) with director skills per stage (`skills/pipelines/*/..director.md`).
- **Consistency:** HH ref sheets and forms; DC identity library + 3D Gaussian splat sets + 360 panoramas; VM portraits + camera-level references; TK per-shot characterRefs; OM mainly prompt discipline (PER-DOC) plus local rigs.

## 5. Gaps for comparison with ArcReel (facts for the caller to weigh)

Forms supported by donors that are rare or single-source:
- Reference-video analysis/remake, podcast repurposing, screen demo, localization dub, avatar presenter, product/brand film, documentary montage from stock: OpenMontage only (FACT).
- Voice cloning with dialogue-in-video: DramaClaw (FACT); ElevenLabs cloning in OpenMontage.
- Real-person/pet cameo into story: ViMax AutoCameo (README claim; source not found in pinned tree).
- Fanfic, spinoff, sequel, short-story compression, platform packaging: shenbi only.
- Per-genre prompt packs for 18+ genres: huohuo only (all Chinese webnovel genres; no children's, true crime, educational, slice-of-life as dedicated packs anywhere).
- Interactive/branching: DramaClaw README comparison table claims it; not verified in code (UNKNOWN).
- No donor in source provides: music-video-from-lyrics pipeline (OM has Suno + montage pieces only), recap/commentary of existing video with narration, children's picture-book form.

## 6. UNKNOWN / not verified

- HH subtitles and output-language policy for drama; HH cliffhanger/hook logic for episodes.
- DC cliffhanger logic, SFX generation, branching episodes, bundled narrator voices list.
- TK language policy.
- VM AutoCameo source (README only); VM audio source of truth (relies on video-model native audio, not verified per model).
- OM actual novel/fiction support beyond example prompts; ink-theater inputs.
- Calliope, AIVPE, openfilm, OCC, open-edit, VGA, MSM, Topview forms beyond what the 11-13 docs record (source not read here).
- The other repo docs (11-11 deep dive, 11-08/11-11 stage docs, 11-09 writing capability docs) were not re-read; they may add mechanisms on HH/DC/OM/ViMax/shenbi not captured here.
