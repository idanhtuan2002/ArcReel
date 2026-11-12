# Video-quality donor mechanisms (external research)

Date: 2026-11-13. Scope: concrete mechanisms other projects and vendors use to raise the quality of AI films and short videos, focused on what ArcReel/R2 lacks. License questions are out of scope by sponsor decision and are not covered. Read-only research; the only file written is this one.

## Method and limits

- Source repos were shallow-cloned (`git clone --depth 1`) into `/tmp/claude-1000/-home-anhtuan-content-production-os/9ab4f1ca-8a43-4753-9ca3-6b5ec550b684/scratchpad/donors/<name>/repo` and read only. No cloned code was executed. Star counts come from `gh api` on 2026-11-13.
- Web docs were read through the WebFetch tool, which summarizes pages with a small model. Quoted parameter values are therefore "as reported by the fetch summary" and should be re-checked against the page before they become a contract. Where the official page body was not retrievable, that is stated.
- Maturity labels: REAL = code that implements it; PROMPT = prompt/skill text only, no enforcing code; DOC = vendor-documented API; PAPER = paper/README only.
- Facts are what a source says. Inferences are marked "Inference". Unknowns are listed at the end.

## Pinned sources

| Donor | Commit / URL | Stars (2026-11-13) |
|---|---|---|
| benjiyaya/Calliope | 6e0716f88c86ee3ddf3cab499aef6239221ce058 (2026-11-09) | 299 |
| LudwigKienle/ai-video-production-editor (AIVPE) | a368af45b6cfd35e22bd3b5e101db198e1ac89a9 (2026-10-28) | 178 |
| openfilm/openfilm | 4ba036259f371984aa8775a70463fecd805c507f (2026-11-12) | 5,923 |
| 0xsline/OpenChatCut (OCC) | f96502a18e65a09c19324b10feb671bb505056bd (2026-11-12) | 3,085 |
| veedstudio/open-edit | e4dc93892268eaf04b64386935ba6e53098a5c79 (2026-11-11) | 1,798 |
| Zulgo/video-generation-automation (VGA) | e46e9d3cc4b67d5c12ef4bde5d4587d7b36b333c (2026-11-01), 1 commit | 1 |
| KlingAIResearch/MultiShotMaster (MSM) | 1df812dda262639e4a3ca6e4a1da9000b0a8e124 (2026-02-22); arXiv 2512.03041 | 187 |
| HKUDS/ViMax | fd4b72e7731be6e5f88486206d25ea59849b0285 (2026-09-30) | 12,908 |
| Wan-Video/Wan2.2 (README only) | 1ea34ff48f87168174e12956e200b1d908b1c5ff | 18,590 |
| Tencent-Hunyuan/HunyuanVideo-1.5 (README only) | 60783e704160023913bee78f0b47036d393d4dfa | 4,597 |
| Lightricks/LTX-Desktop (README only) | d23b8b3de2ab258459f1c1524d4ce1e49c6783f5 | 2,254 |
| pnnbao97/VieNeu-TTS (README only) | 22dd2ef2a89bba24a77da6dbc84c75f7f4fda05b | 3,222 |
| Topview | docs.topview.ai (llms.txt index, fetched 2026-11-13), topview.ai/mcp | n/a |
| Kling | kling.ai/document-api (llms.txt index and pages listed below) | n/a |
| Google | aistudio.google.com/docs/video; docs.cloud.google.com/vertex-ai/generative-ai/docs/video/overview | n/a |
| ComfyUI | docs.comfy.org router schemas (kling-v3, veo-3.1-generate-001, dreamina-seedance-2-0-260128, wan2.7-r2v) and tutorial seedance-2-5-draft | n/a |
| Papers | arXiv 2512.03041 (MSM), 2501.12909 (FilmAgent), 2503.07314 (MovieAgent), 2405.01434 (StoryDiffusion), CHAI 2604.21718 (cited by VGA, not opened) | n/a |

Not examined: Anim-Director (the arXiv id I tried, 2402.17525, is an unrelated survey, so I dropped it), Huobao drama, MoneyPrinterTurbo, NarratoAI, clapper. They were not chosen because the targets above covered the quality mechanisms more directly; this is a scoping decision, not a finding about them.

Why ViMax, FilmAgent, MovieAgent, StoryDiffusion were picked from item 7: ViMax is the only open pipeline I found with a camera-coverage tree, VLM reference selection and VLM best-of-N in running code. FilmAgent and MovieAgent are the two papers that formalize director/cinematographer role planning. StoryDiffusion is the reference for training-free image consistency usable with ComfyUI image models.

---

## A. Character and scene consistency across shots

| Donor | Mechanism (concrete) | Evidence | Maturity |
|---|---|---|---|
| ViMax | Per-frame reference selection by LLM: input is the target frame description plus a numbered list of reference descriptions (character portraits and previously generated frames). Rules: max 8 refs; at most one view (front/side/back) per character portrait; prefer refs from the same camera; recent frames outrank old ones; a new character in frame forces its portrait in. Two stages: text-only filter when 8 or more candidates, then multimodal filter with the images attached. Output is `ref_image_indices` plus an edit prompt saying which element copies which "Image N". | `agents/reference_image_selector.py:12-200@fd4b72e7` | REAL |
| ViMax | Camera tree: each camera has `parent_cam_idx`, `parent_shot_idx`, `is_parent_fully_covers_child`, and `missing_info`. A child camera's first frame is derived from the parent's frame. If the parent fully covers the child it is reused; otherwise only the listed missing elements are replaced (prompt: "The composition and background are correct... Wrong elements: {missing_info}... Don't change the background"). A short "transition video" from the parent first frame is generated to reach the child viewpoint. | `interfaces/camera.py:6-42@fd4b72e7`; `pipelines/script2video_pipeline.py:363-407@fd4b72e7` | REAL |
| ViMax | Shot description schema separates `ff_desc`, `lf_desc`, `motion_desc`, plus `variation_type` (large/medium/small) that says how far the last frame differs from the first. | `interfaces/shot_description.py:111-154@fd4b72e7` | REAL |
| Calliope | Latent chaining: previous clip's saved AV latent is downloaded after render and uploaded as the next clip's pinned head (22 frames, trimmed from delivery). Joined pairs are exported with a hard cut, not a crossfade. Needs the third-party `ComfyUI-H3-Motion-Context` node and a MiniMax H3 workflow. Fails the job loudly if the previous clip has no latent. | `calliope-backend/src/calliope/queue/chain.py:1-30,167-231@6e0716f8`; `README.md:180-184@6e0716f8` | REAL (only for that node/workflow) |
| Calliope | Identity phrase discipline: one signature detail per character, reused verbatim in every scene prompt; clothing as a set; sheet prompt says "front and side view, neutral pose, plain background"; fix the sheet first when drift appears. | `skills_builtin/character-consistency/SKILL.md:20-49@6e0716f8` | PROMPT |
| VGA | "Identity anchoring": restate the same 3-6 disambiguating attributes verbatim for each named subject in every shot of a multi-shot prompt; pronouns and "same character" do not work. | `skills/creative/video-gen-prompting.md:209-213@e46e9d3c` | PROMPT |
| AIVPE | Per-shot context references tagged by role (character -> wardrobe/identity, environment -> lighting/geometry, prop -> shape/scale, product -> logo), including a "world" mode that uses a panorama/thumbnail of the location for camera blocking. A reverse-angle request (`needsReverseAngle`, `reverseYaw` -180..180) feeds a location reference rendered from the opposite side. | `src/utils/shotContextComposer.ts:5-40@a368af45`; `src/utils/visualContinuity.ts:77@a368af45` | REAL |
| MSM | Multi-Shot Narrative RoPE (explicit phase shift at shot transitions) and Spatiotemporal Position-Aware RoPE (reference tokens with grounding). Open-source weights cover multi-shot text-driven consistency on Wan2.1-T2V 1.3B/14B. Per-shot cross-attention loops over `latent_shot_groups`. The multi-reference code/model is listed as not released (unchecked box in the README plan). | `README.md` (Note, Open-Source Plan)@1df812dd; `diffsynth/models/wan_video_dit.py:179-205@1df812dd`; arXiv 2512.03041 | REAL (research weights only), PAPER for multi-reference |
| StoryDiffusion | Consistent Self-Attention: zero-shot, shares attention across images in a batch to keep identity/clothing; Semantic Motion Predictor for image-to-video. Per the fetched abstract the page did not describe token sharing details. | arXiv 2405.01434 | PAPER (code not read) |
| Kling | Persistent "Element": multi-image (`image_refer`: one frontal image plus 1-3 other angles/close-ups, `element_description` required, optional bound `element_voice_id`) or video-character (`video_refer`: one 3-8 s 1080p mp4/mov of a realistic human, only for o3 and later). Async create returns `element_id`. | `kling.ai/document-api/api/video/4-0/elements.md` | DOC |
| Kling 4.0 Omni | Per-task limits: images+videos+elements+voices combined at most 15; images up to 10; elements up to 7 (at most 3 video-character); videos 3-30 s; references by `@image_1`, `@Video1`, `@element_1` with a stated purpose in the prompt; prompt up to 26,000 English chars. | `kling.ai/document-api/api/video/4-0/video-omni.md` | DOC |
| Veo (Vertex schema via Comfy) | `referenceImages` up to 3 `asset` images or 1 `style` image, each with `referenceType`; `image` + `lastFrame` for first/last-frame interpolation (Veo 3.0+); `video` + `task` (`extend`/`edit`/`upscale`) incompatible with image refs. | `docs.comfy.org/router-schemas/veo/veo-3.1-generate-001.json` | DOC |
| Gemini Omni Flash | "character consistency across up to 6 reference images", 3-15 s with native audio, multi-turn editing/extension via the Interactions API. | `aistudio.google.com/docs/video` | DOC |
| Seedance 2.x (Comfy Router schema) | `content[]` roles `first_frame`, `last_frame`, `reference_image`, `reference_video`, `reference_audio`; `return_last_frame` returns a PNG "usable to chain consecutive videos"; audio cannot be used alone. Third-party gateways report up to 9 images, 3 videos, 3 audios and that a last frame requires a first frame and cannot be combined with reference images. | `docs.comfy.org/router-schemas/byteplus/dreamina-seedance-2-0-260128.json`; Replicate/Cloudflare/GMI listings (secondary) | DOC (official BytePlus body not retrievable) |
| Wan 2.7 R2V (Comfy schema) | `media[]` with `first_frame` (max 1), `reference_image`, `reference_video`; refs total at most 5; `shot_type` `multi` only takes effect with `prompt_extend`. | `docs.comfy.org/router-schemas/wan/wan2.7-r2v.json` | DOC |
| Topview | Omni Reference (`<<<ImageN>>>`, `<<<VideoN>>>` in prompt, `generatingCount` 1-4), Video Recast (`motionTransfer` or `objectSwap`, 1-30 reference images, source video 4-30 s, fixed Seedance 2.5), Character Swap (image and video, mask-drawing sub-APIs). | `docs.topview.ai/reference/omni_reference_submit_task.md`, `video-recast.md` | DOC |

Inference: ViMax's camera tree plus `missing_info` is the closest existing mechanism to "same room, different angle" coverage (shot/reverse-shot), which our storyboard variants and reference-video units do not appear to model explicitly. It generates the new angle from the parent frame instead of from scratch, which should reduce background drift.

## B. Shot design and cinematography

| Donor | Mechanism (concrete) | Evidence | Maturity |
|---|---|---|---|
| Calliope | Coverage expansion: one scene is split into N clips by an LLM under hard constraints: every numbered dialogue line covered by exactly one clip (`dialog_lines_covered`), durations 3..cap and summing about to the scene budget, clip cap default tied to "video models degrade beyond ~10 s", `shot_size` in {wide, medium, closeUp, insert, overShoulder}, chunks of 4 scenes per call, deterministic normalization afterwards. | `agent/coverage_agent.py:75-140@6e0716f8` | REAL |
| Calliope | Continuity ledger: one JSON plan for the whole film (`overview`: style/pace/soundscape/camera_grammar/lighting; nine locked `requirements`; per-shot `window`, `action`, `speakers`, `camera`, `lighting`, `spatial`, `state_after`). REALIZED clips keep their footage as ground truth. A deterministic fallback plan exists. The plan is hashed (`basis_hash`) so stale plans are detected. | `agent/continuity.py:60-98,237,288@6e0716f8` | REAL |
| Calliope | Continuation prompt rules: open mid-action; no progressive camera move across a join; put joins mid-walk not at a doorway; one short dialogue line per ~2.5 s split between sentences; end each clip with action still in progress; shift all timestamps by the pinned head (+0.92 s). | `skills_builtin/h3-continuation-prompt/SKILL.md:28-63@6e0716f8` | PROMPT |
| AIVPE | Director pass with enumerated vocab and rules: shot types (closeup, extreme_closeup, portrait, medium, full_body, wide, extreme_wide, low_angle, overhead, ots, b_roll), camera moves, a coverage rule ("establishing/wide on new location or time jump; master or two-shot plus OTS from both sides plus close-ups on key lines; inserts for props/hands/reveals; vary sizes; respect the 180-degree line"), per-shot `rationale`, and a shot-count target per scene. A `DirectorReview` function emits warnings for unknown shot types. | `src/utils/directorAgent.ts:9-18,164-251@a368af45` | REAL |
| VGA | Slideshow-risk scorer over the scene plan, 6 dimensions scored 0-5 (repetition, decorative_visuals, weak_motion, weak_shot_intent, typography_overreliance, unsupported_cinematic_claims); verdict strong <2.0, acceptable <3.0, revise <4.0, fail >=4.0 blocks compose. | `lib/slideshow_risk.py:1-80@e46e9d3c` | REAL |
| VGA | Variation checker: flags repetition of shot size across 4+ scenes and a list of generic phrases ("a beautiful", "stunning", "dynamic"...). Structural, not creative. | `lib/variation_checker.py:1-50@e46e9d3c` | REAL |
| VGA | Delivery-promise lock: a production declares `motion_led` (min 70% real motion cuts, no still fallback) vs `source_led` (min 30%) etc. at proposal; compose must stop and ask rather than silently downgrade. `validate_cuts` enforces the ratio. | `lib/delivery_promise.py:25-60,113@e46e9d3c` | REAL |
| VGA | Five-aspect shot spec (Subject, Subject Motion, Scene with overlays separate, Spatial Framing, Camera) taken from the CHAI study; mark non-applicable aspects "N/A" explicitly; static shot means zero movement/focus/zoom. | `skills/creative/video-gen-prompting.md:39-56,277-298@e46e9d3c` | PROMPT |
| OCC | Beat-edit density model: levels rest/sparse/medium/dense (cut on section boundary / downbeats / downbeats+off-beats / every beat), 3-6 content anchors planned first, dense is spice (about 8 s max), at least one held shot per 15 s, `shots_needed ~ (section_s/60) x BPM x cuts_per_beat`. | `src/agent/skills/beat-sync-montage/references/beat-density.md:1-89@f96502a1` | PROMPT |
| OCC | Shot fitness for cutting: legible onset, subject readable in ~0.5 s, one motion axis, enough handle, contrast with neighbours; two or more failures means replace the shot. Continuity checks: matched screen direction, no horizontal/vertical axis flips, no repeated extreme scale jumps, no bright/dark flashes. | `.../beat-sync-montage/references/shot-fitness.md:1-64@f96502a1` | PROMPT |
| FilmAgent (paper) | Director/screenwriter/actor/cinematographer agents with iterative feedback; reported 3.98/5 average human score over 15 ideas. Runs in 3D virtual spaces. | arXiv 2501.12909 | PAPER |
| MovieAgent (paper) | Hierarchical CoT planning across scenes, camera settings and cinematography with director/screenwriter/storyboard/location roles. | arXiv 2503.07314 | PAPER |
| Kling v3 (Comfy schema) | Native multi-shot: `multi_shot=true`, `shot_type` `customize`/`intelligence`, `multi_prompt` of 1-6 shots, each with `prompt` (max 512 chars) and `duration`; durations sum to the task duration; `camera_control` with simple/preset types and config fields in -10..10. | `docs.comfy.org/router-schemas/kling/kling-v3.json` | DOC |

## C. Prompt engineering for video models

| Donor | Mechanism (concrete) | Evidence | Maturity |
|---|---|---|---|
| VGA | Per-model prompt length table: Seedance 2.0 200-400 words for hero shots and 80-150 for inserts; Wan 2.2 200-400; Sora 2/Veo 3.1 100-250 (plateau past ~250); LTX-2 at most 80; Runway Gen-4 at most 60. Attributed to the CHAI paper; I did not open the paper. | `skills/creative/video-gen-prompting.md:56-66@e46e9d3c` | PROMPT |
| VGA | Per-model dialect files for Seedance, Sora, Veo, Grok, LTX, Hunyuan under `skills/creative/prompting/`; model guide table with key insight per model (Kling `++emphasis++`, Grok `<IMAGE_1>` placeholders, Runway "focus on motion, not appearance"). | `skills/creative/video-gen-prompting.md:13-26@e46e9d3c` | PROMPT |
| VGA | Visual cause instead of emotion adjectives: "sad character" becomes "tears on cheek, shoulders slumped, staring at empty chair"; avoid readable text; one speaker per clip or use reaction shots; do not pair conflicting lighting. | `.../video-gen-prompting.md:277-298@e46e9d3c` | PROMPT |
| VGA | Structured shot-language to prompt compiler, 5 layers (camera/lens, movement, subject plus texture, lighting key/temperature, style adapted from the playbook rather than a fixed prefix on every shot), with enum-to-phrase maps for shot size, camera movement and lighting. | `lib/shot_prompt_builder.py:1-120@e46e9d3c` | REAL |
| Calliope | H3 six-section prompt format (`subject_definitions`, `summary`, `retention_analysis`, `detailed_description` with timestamps, `overall_soundscape`, `non_diegetic_music`) and a ref2va format with `<Subject N>`/`<Picture N>` labels kept identical across a chain. | `skills_builtin/h3-video-prompt-enhancer/references/*.md@6e0716f8`; `h3-continuation-prompt/SKILL.md:28-40` | PROMPT |
| Calliope | A separate critic checks one clip prompt against the continuity plan on nine buckets (style, subjects, actions, dialogue, sound, camera, lighting, spatial, scene), "Report only failures... No second draft. No praise.", JSON `{ok, notes[]}`, 15 s timeout. | `agent/continuity.py:90-98,593-660@6e0716f8` | REAL |
| Kling v3 | `negative_prompt` up to 2,500 chars but the schema advises putting negations as negative sentences inside the positive prompt; `cfg_scale` 0-1 (default 0.5, higher means less model freedom). | `docs.comfy.org/router-schemas/kling/kling-v3.json` | DOC |
| Veo | `negativePrompt` (what to avoid), `seed` uint32, `sampleCount` 1-4, `durationSeconds` 4/6/8. | Comfy veo schema | DOC |
| Kling 4.0 Omni | Each reference should have a stated purpose in the prompt; unique ids; mixed prompt length rule E/26000 + N/11000 <= 1. | `kling.ai/document-api/api/video/4-0/video-omni.md` | DOC |

## D. Audio: TTS emotion, lip-sync, music, SFX, ducking, loudness

| Donor | Mechanism (concrete) | Evidence | Maturity |
|---|---|---|---|
| VGA | Voice performance contract: script carries `voice_performance` (intent, pacing_profile, energy_curve, pause_policy, per-provider notes) and per-section `delivery_cues` (pace, energy, emphasis_words, pause_before/after seconds, delivery_note, provider-specific text such as SSML `<break>`), then verified with a sample. | `skills/meta/voice-performance-director.md:1-60@e46e9d3c` | PROMPT (schema-backed) |
| VGA | Sidechain ducking recipe: `sidechaincompress` keyed by speech, threshold 0.02, ratio 9, attack 200 ms, release 500 ms; loudness targets per platform (social -14 LUFS / 5-7 LU, YouTube -14 to -16 / 7-11, podcast -16, broadcast -24). | `skills/core/ffmpeg.md:58-80@e46e9d3c` | PROMPT |
| openfilm | Loudness delivery: measure with `ebur128=peak=true`, apply one global gain then a 4x-oversampled `alimiter` (attack 3, release 60) to catch true peaks, re-measure on the encoded file, retry at most twice; tolerance 0.5 LU, true-peak ceiling -1 dBTP, limiter starts 1 dB under ceiling because AAC adds peak (measured -1.5 dBFS became -0.4 dBTP). | `packages/openfilm/src/loudness.mjs:1-70@4ba03625` | REAL |
| Calliope | Export chain: normalize, `acrossfade` 0.5 s (hard cut where a clip continues via latent), then `loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000` (resample back because loudnorm outputs 192 kHz). | `export/runner.py:34,184-270@6e0716f8` | REAL |
| OCC | `normalize_loudness` tool, default target -14 LUFS, per-item measured LUFS and gain; separate `detect_beats` DSP (spectral flux, autocorrelation BPM 60-180, phase-fitted grid, 4/4 downbeat heuristic, confidence >= 1.2 else no beat) and silence tools. | `src/agent/tools/loudness-tools.ts:6-57@f96502a1`; `src/audio/beats.ts:1-30@f96502a1` | REAL |
| AIVPE | Audio mastering and remaster runtimes with `targetLufs` default -14 clamped to -16..-9. | `electron/audio-mastering-utils.js:22,52@a368af45` | REAL |
| open-edit | `sfx search` returns real stock sounds and excludes sounds the run already saved, so the next cut gets a different effect (a generated effect repeats the same sound at every cut). | `cli/src/commands/sfx.ts:1-30@e4dc9389` | REAL (needs a library URL) |
| open-edit | `mux-audio` puts delivery-loudness sound on a render; `mix-audio` lays video-own sound under voice. | `.claude/skills/open-edit/SKILL.md:68-69@e4dc9389` | REAL |
| Kling | `advanced-lip-sync`: face recognition first (`session_id`, `face_id`), one person only, audio 2-60 s from TTS `audio_id` (generated within 30 days) or a 5 MB mp3/wav/m4a/aac file; the sound window must overlap the face's lip-sync interval by at least 2 s; results deleted after 30 days. Avatar and Avatar-TTS endpoints also exist. | `kling.ai/document-api/api/video/lip-sync.md` | DOC |
| Kling 4.0 Omni | `settings.audio` `native` (default) or `original`; up to 3 `voice` references by `voice_id` from the Custom Voice API; with `original`, voice references are not allowed. | `.../4-0/video-omni.md` | DOC |
| Kling v3 | `sound` on/off, `voice_list` of 1-2 voices referenced as `<<<voice_1>>>`, `<<<voice_2>>>` in prompt. | Comfy kling-v3 schema | DOC |
| VieNeu | v3 Turbo: 25 preset voices over North/Central/South regions, OpenAI-compatible `/v1/audio/speech`, first audio about 115 ms, `style` parameter deprecated and has no effect. | `README.md:25-36,242-252@22dd2ef2` | REAL (README) |

Inference: our VieNeu path has no emotion lever (`style` is a no-op), so emotion must come from voice choice and text/pause shaping. The VGA `delivery_cues` contract (pause_before/after, emphasis words) is a way to express those within text; it does not solve emotion on its own.

## E. Editing and post

| Donor | Mechanism (concrete) | Evidence | Maturity |
|---|---|---|---|
| OCC | FCPXML 1.10 serializer as a pure function of timeline state (deterministic, headless-testable), NLE formats `fcp_xml` and `fcp_xml_resolve`; audio transcript edits are split into multiple asset-clips so deleted words do not play in the NLE; also a Jianying export and an FCPXML import. | `src/export/fcpxml.ts:1-30@f96502a1`; `server/external-agent/jianying-export.ts@f96502a1`; `src/agent/tools/timeline-import-fcpxml.ts` | REAL |
| OCC | Caption avoidance: analyzes the video layers beneath each caption interval and moves caption placement away from detected faces (`captionFaceConflicts`, `bestCaptionLayoutForGeometries`); runs after enabling captions. | `src/agent/tools/caption-avoidance-tools.ts:1-40@f96502a1` | REAL |
| open-edit | Caption timing check from subtitling practice: hold 0.5-7 s per caption (Netflix timed-text style 5/6 s to 7 s, lower end reduced for fast captions), flags speech with no caption for more than the dead-tail seconds, captioned if captions cover at least 1/3 of spoken words. | `cli/src/verify/captions.ts:12-30@e4dc9389` | REAL |
| open-edit | Safe zone: all text in `[data-safe]`, platform safe zone clears every detected face on screen; text must be at least 75% visible per frame; text under the size floor is drawn at the floor. | `.claude/skills/open-edit/SKILL.md:85-136@e4dc9389` | REAL |
| openfilm | Captions are a WebVTT beside each audio/video file with a timestamp tag per word; Studio builds a caption track and regenerates speech captions after cuts (`SPEECH_NOTE`). Large template library of lower-thirds/callouts/transitions. | `packages/openfilm/src/captions.mjs:1-30@4ba03625`; `packages/openfilm/library/text/*` | REAL |
| AIVPE | Colour wheels baked into 3D LUTs, waveform/histogram scopes, offline auto-cut (silence, scenes, filler words), OFX/DCTL plugin install. | `README.md` (Why people use it)@a368af45 | README-only for depth (code not read) |
| Calliope | Normalize all clips to 1080p at the majority frame rate of the clips (mixed-rate projects conform to the most common), xfade common timebase. | `export/runner.py:81@6e0716f8`; `README.md:96@6e0716f8` | REAL |
| VGA | Subtitles in the bottom 20% of frame and never over the face; no audio clipping or silence gaps at cut points (checklist). | `skills/core/ffmpeg.md:82-95@e46e9d3c` | PROMPT |
| OCC/open-edit | Draft render: `--draft` draws frames at half size with a cheap encode and its own cache; a draft is never the deliverable. | `open-edit .claude/skills/open-edit/SKILL.md:166-170@e4dc9389` | REAL |

## F. Automated QA

| Donor | What is judged / mechanism | Judge | Threshold / policy | Evidence | Maturity |
|---|---|---|---|---|---|
| AIVPE | Per storyboard frame (not video): 11 ordered checks: identity, wardrobe, props, location, lighting, screen_direction (180-degree rule, reverse shots look opposite ways), eyeline (posture and height carry across the cut), staging (establishing shot defines geography; enclosed spaces limit who can be present), text, framing, artifacts (ghosted bodies, extra fingers, duplicated people = high severity). The judge receives current frame, previous/next shot, establishing shot, and character/outfit/location/prop references. Output: score, status, issues[{category, severity, message}], `promptFix` (1-2 sentences to add to the image prompt), `needsReverseAngle`. | Gemini Flash (`GEMINI_TEXT_MODEL_FLASH`) | score 90-100 aligned (and all issues low), 70-89 watch, <70 drift; any high-severity issue caps score at 69; an unparseable reply is rejected instead of read as score 0; drifted shots enter a ranked "re-film priority" queue, re-run in order, loop stops on first error | `src/utils/visualContinuity.ts:9,44-80,130-165@a368af45`; `src/services/geminiService.ts:3032-3056@a368af45`; `src/workspaces/ProjectHubWorkspace.tsx:13359-13392@a368af45` | REAL |
| ViMax | Best-of-N for keyframes: N candidates (default 2) are generated, a VLM compares each against reference images and the target description on character consistency, spatial consistency (who is left/right, layout), description accuracy; also prefers images without borders. Returns `best_image_index` plus `reason` under a pydantic schema with StrictInt, retried with backoff; candidates and selection status persisted per shot (resumable). | VLM via chat_model | pick the relatively best even when none is ideal | `agents/best_image_selector.py:12-80@fd4b72e7`; `utils/image_selection.py:5@fd4b72e7`; `pipelines/script2video_pipeline.py:535-610@fd4b72e7` | REAL |
| Calliope | Prompt-vs-plan critic (nine buckets, failures only). | LLM | `ok`/`notes` | `agent/continuity.py:90-98@6e0716f8` | REAL |
| VGA | Reviewer protocol per pipeline stage: schema validation first (critical if it fails), then manifest `review_focus` items with severities critical/suggestion/nitpick/investigation; every critical finding must carry a concrete `proposed_fix`; findings must point to a field/line/frame ("forbid hallucinated criticism"); scan for the same class of mistake before returning; max 2 revision rounds then PASS_WITH_WARNINGS ("never block indefinitely"). Based on the CMU/Harvard CHAI critique-quality axes (accurate, complete, constructive). | the agent itself | 0 critical = pass; 1+ = revise, max 2 rounds | `skills/meta/reviewer.md:1-130@e46e9d3c` | PROMPT |
| VGA | Provider scoring across 7 dimensions with weights: task_fit 0.30, output_quality 0.20, control 0.15, reliability 0.15, cost_efficiency 0.10, latency 0.05, continuity 0.05; `explain()` prints the top three weighted contributors; a production-path score exists with budget_fit, fallback_integrity, consistency_fit. | none (heuristic inputs 0-1) | weighted sum | `lib/scoring.py:23-60,66-80@e46e9d3c` | REAL |
| open-edit | `openedit review <video>` runs all delivery checks and prints one report that changes nothing: blank frames, dead air (scan 10 Hz, 128 px, 8x8 blocks, frozen/nudge/still thresholds), dead tail, captions missing under speech, length, text size/contrast, numbers nobody said, text over burned-in graphics. "A finding is yours to judge, not an order to re-render." Skips checks that need a transcript when none exists. | deterministic pixel/transcript analysis | reports only | `.claude/skills/open-edit/SKILL.md:204-217@e4dc9389`; `cli/src/verify/dead-air.ts:16-67@e4dc9389` | REAL |
| openfilm | `openfilm look`: contact sheet of the whole film with sound, single frame, or range; checks that the same `t` always draws the same picture (determinism) and loudness slack; the agent uses it as its eyes. | deterministic + agent vision | `SAME_LIMIT=32` block diff, `LOUDNESS_SLACK=0.5` LU | `packages/openfilm/src/look.mjs:1-30@4ba03625`; `src/shared.mjs:454` | REAL |
| VGA | Delivery promise check (see B) and `source_media_review.py` for source footage (not read in depth). | n/a | n/a | `lib/source_media_review.py@e46e9d3c` | REAL (not read) |

Inference: our best-of-N is disabled because the local judge is weak. AIVPE and ViMax both run the judge on still images (storyboard frames / keyframes) with a cloud VLM, where it is cheap and where the judge is most reliable (identity, wardrobe, spatial layout), and then reuse the approved frame as the video start frame. That moves selection upstream of the expensive video call. AIVPE's rule "any high issue caps the score at 69" and "unparseable verdict is not score 0" are small, copyable guards.

## G. Reference video to new video

| Donor | Mechanism (concrete) | Evidence | Maturity |
|---|---|---|---|
| open-edit | `shots <reference>`: lists every shot's start and length, spoken words, and shot size (close-up/medium/wide/no face, derived from face boxes written by a prior `faces` command), plus storyboard sheets with the first/middle/last frame of each shot (middle only for sub-second shots or when too many shots). Known limits written in the doc: dissolves read as one longer shot; about one jump cut in three is missed; flicker reads as extra cuts (`--threshold 0.2`); profile faces can be one size off. "Look at the sheets with the list before planning from it." | `.claude/skills/open-edit/SKILL.md:55@e4dc9389` | REAL |
| VGA | Video reference analyst: runs a `VideoAnalyzer` (up to 20 keyframes), records per-scene `motion_type` (`motion_clip`, `animated_still`, `static_image`) and `flow_variance`, then forces a 5-aspect breakdown per shot (Subject incl. transitions revealing/disappearing/switching, Subject Motion, Scene with overlays separate, Spatial Framing, Camera), a capability audit against available tools, 2-3 creative variants, and a mandatory 10-15 s sample before the full run with cost estimate and approval. "Never guess whether a reference uses images or video." | `skills/meta/video-reference-analyst.md:28-110,328-365@e46e9d3c` | PROMPT plus analyzer tool (analyzer code not read) |
| Topview | Video Recast: `motionTransfer` (source video supplies motion for subject in reference images) or `objectSwap`; source 4-30 s; fixed Seedance 2.5; 720 or 1080. Omni Reference accepts `inputImages` and `inputVideos`. Marketing site mentions a "Viral Video Agent" taking a product image and a reference video; I found no documented analysis of structure or pacing. | `docs.topview.ai/reference/video-recast.md`; Product Hunt listing (secondary) | DOC for Recast; marketing only for Viral Video Agent |
| Kling 4.0 Omni | `base_video` (edit), `feature_video`/reference videos 3-30 s with `settings.audio=original` to keep source sound; at most 5 reference videos without video-character elements. | `.../4-0/video-omni.md` | DOC |
| Seedance 2.x | `reference_video` role; third-party docs say the prompt can say "use video 1's camera movement". | Comfy schema; Evolink (secondary) | DOC / secondary |

## H. Cost and throughput controls tied to quality

| Donor | Mechanism (concrete) | Evidence | Maturity |
|---|---|---|---|
| Seedance 2.5 draft/final | Draft model produces a 480p preview plus a `draft_task_id`; a second node renders the final at 1080p or 4K from that id, reusing prompt, input, duration, aspect ratio and audio setting; drafts stay renderable 7 days; Stage 1 must stay bypassed after approval or it creates a new draft; 4K is enterprise-only per Comfy. Sources disagree on whether finalizing is billed like a direct render (Segmind) or in addition to the draft; ByteDance's claimed saving is 57% for four draws (secondary news). Comfy docs state no price figures. | `docs.comfy.org/tutorials/partner-nodes/bytedance/seedance-2-5-draft.md`; `docs.comfy.org/router-schemas/byteplus/...` (`draft_task` content type, 2.5 only); Segmind and Atlas Cloud posts (secondary) | DOC (Comfy), cost figures secondary |
| VGA | Sample-first production (10-15 s with real TTS, visuals, music, subtitle preview, cost shown) before a full run. | `skills/meta/video-reference-analyst.md:328-365@e46e9d3c` | PROMPT |
| open-edit | `--draft` render at half size with separate cache; render once without `--draft` when settled. | `SKILL.md:166-170@e4dc9389` | REAL |
| Kling | `mode` std vs pro; Omni `settings.resolution` 720p/1080p; output URLs retained 30 days; `usage.output_duration` is the billed duration. | Comfy kling-v3 schema; `video-omni.md` | DOC |
| Seedance (Comfy) | `service_tier` `flex` (offline inference) exists but is not supported on 2.0/2.0 fast/2.5 per the schema. | Comfy schema | DOC |
| Topview | Points per second: Avatar 4 0.1 pt/s (max 120 s), Avatar 4 Fast 0.06 pt/s, Avatar 2 0.4 pt/s (max 28 s), Character Swap 0.3 pt/s (max 60 s); image-to-video by quality tier (5 s: Lite 2.5, Pro 3.5, Plus 5, Best 10 points). Credits are charged after task completion and read from `costCredit`. | `docs.topview.ai/reference/rules-for-consumption-rules.md`; `storyboard-submit-task.md` | DOC |
| VGA | Provider score includes `cost_efficiency` and `budget_fit` for the whole path. | `lib/scoring.py@e46e9d3c` | REAL |
| AIVPE | Aggregated provider pricing reference and "Auto" per-shot model routing (people to Nano Banana/GPT Image 2, creatures to Krea, environments to Seedream, typography to Ideogram, dialogue to Veo 3.1, performance to Kling v3, action/long takes to Seedance 2.5). The routing rule table is a README claim; I did not locate the routing code. | `README.md` (Why people use it)@a368af45; `docs/model-pricing-reference.md` | README-only |
| MiniMax H3 Turbo via MachGen | "5-15 s clips with native audio (about $0.02/s)". Vendor claim in AIVPE README. | `README.md` (What is new)@a368af45 | README-only |

Inference: the Seedance 2.5 draft->final flow is the first vendor-native low-res-preview-then-final mechanism found in this research that keeps the same generation identity (the final reuses the draft's inputs). If our Seedance integration is on 2.0, this needs the 2.5 model id and the `draft_task` content type; whether our ModelArk account can call it is unknown.

---

## Topview: documented vs marketing

| Topic | Documented (official docs) | Marketing or unverified |
|---|---|---|
| API surface | Core, Character Swap (image/video), Image Translate, Photo Avatar/Avatar4, Avatar Marketing Video, Video Avatar, Product Avatar, Product AnyShoot, Common Task (Video Recast, Image2Video, Text2Video, Omni Reference, Motion Control, Text2Image, Image Edit), Scraper, Upload, Voice (clone, text2voice), Board, Video Object Remove, AI Music, StoryBoard, Instant Voice Clone. No "Video Agent" endpoint in the llms.txt index. | The "Video Agent" product (script, shot selection, voiceover, assembly) is described only by third-party reviews (unite.ai, pollo.ai); internals undocumented. |
| Async model | Submit returns `taskId`; poll Query Task (Photo Avatar: poll every 3-5 s, timeout 5 min); optional `noticeUrl` callback on several endpoints (StoryBoard, Omni Reference); status includes `init`, `running`. | n/a |
| Billing | Credits shared with the web account; Ultra credits cannot be used for API; charged after completion for several tasks; `costCredit` in the query response; points per second tables as above. | n/a |
| Storage | API-returned image/video URLs "valid for 7 days only" (`docs.topview.ai/docs/concurrency-and-storage.md`). Queue priority Business Annual > Business Monthly > Pro Annual > Pro Monthly > Free; no numeric concurrency limits. | The "60 days" figure in the prior report was not found. |
| MCP | `topview.ai/mcp` workflow Connect -> Research -> Strategy -> Production; outputs Market Insights Report (PDF), Campaign Plan Pack, creative assets; "Unlimited does not support any automated workflows" so Unlimited cannot use MCP, Plugin or Skill. Models listed: Seedance 2.0, Kling 3.0, Nano Banana 2.0, GPT Image 2, Seedream 5.0 Pro, Veo (page says 3.1 in one place and 3.2 in another). | FAQ says a brief can "activate a Market Researcher, Strategist, and Producer"; demos label only Researcher and Strategist; Campaign Plan Pack is "3 docs" in one demo and "4 docs" in another; demo result images are placeholders. |
| Storyboard API | Stage 1 only: story (max 5,000 chars) to a grid preview image (2-25 panels, preset 4/9/25), models GPT Image 2 / Nano Banana 2 / Nano Banana Pro, up to 6-16 reference images depending on model, `targetDurationSeconds` default 15; docs do not say one panel equals one shot. | n/a |
| Character consistency | Not documented as a mechanism; the closest are Omni Reference, Character Swap, and Photo/Video Avatar APIs. | Marketing claims on consistency not backed by documented method. |
| Lip-sync | No separate lip-sync endpoint in the index; Avatar APIs accept a script or imported audio (priced per 100 characters or per second of audio). | "Physics layer for hand placement" (vantaige.io) is unverified. |

---

## Claims checked from the prior ChatGPT report (license parts skipped)

| Claim | Verdict | Evidence |
|---|---|---|
| Calliope ~299 stars | VERIFIED | `gh api`: 299 on 2026-11-13 |
| Calliope ComfyUI + FastAPI + SvelteKit | VERIFIED | README: backend FastAPI (`calliope-backend`), frontend SvelteKit (`calliope-web`), drives your own ComfyUI |
| Calliope SQLite | VERIFIED | README: "projects live in SQLite"; `calliope-backend/src/calliope/db.py` |
| Calliope latent passing | VERIFIED with condition | Real code (`queue/chain.py`) but only works with the third-party `ComfyUI-H3-Motion-Context` custom node and a workflow with Load/Save Latent nodes; README:180-184@6e0716f8 |
| Calliope "CLI text-only" | VERIFIED, scoped | `docs/changelogs/2026-10-06-cli-authoring-bridge.md`: CLI "Finished text only. It never calls the in-app LLM, and it never writes image or video files." The main app still renders. |
| AIVPE 177 stars | VERIFIED (now 178) | `gh api` |
| AIVPE 9-step workflow | VERIFIED with nuance | `docs/ui-production-workflow-guide.md:54-62` lists 9 Production Hub steps (Library, Script, World, Director, Concept, Scene Wall, Storyboard, Filming, Review); README's tour lists a different chain (Script, Director, Concept & casting, Storyboard, AI filming, Continuity review, Re-film queue, Edit/Color/Sound, Deliver) |
| OpenFilm ~5.8k stars | VERIFIED (5,923) | `gh api` |
| OpenFilm turns Codex/Claude Code into a video agent with HTML/CSS/WebGL | VERIFIED | README: agent writes `film.html`; each shot is a page with `frame(t)` using three.js, WebGL, canvas, SVG, CSS, GSAP, video |
| OpenChatCut ~3.1k stars | VERIFIED (3,085) | `gh api` |
| OpenChatCut React/Remotion/FFmpeg/Electron | VERIFIED | `package.json`: react 19.3.1, remotion 4.0.537, ffmpeg-static 5.3.0, electron 43.8.3 |
| OpenChatCut FCPXML export | VERIFIED | `src/export/fcpxml.ts:1-5@f96502a1` (FCPXML 1.10 serializer, `fcp_xml`, `fcp_xml_resolve`); also a Jianying export under `server/external-agent/` |
| video-generation-automation has 1 commit | VERIFIED | `git rev-list --count HEAD` = 1; 1 star |
| Topview Unlimited plan excluded from MCP/API | VERIFIED for MCP | `topview.ai/mcp`: "Unlimited does not support any automated workflows" (so also Plugin and Skill). The API billing doc separately says Ultra credits cannot be used for API; it says nothing about the Unlimited plan |
| Topview API files retained 60 days | WRONG (as far as docs show) | `docs.topview.ai/docs/concurrency-and-storage.md`: API URLs "valid for 7 days only"; no 60-day figure found in any fetched official page (Kling, for comparison, is 30 days) |
| Topview MCP has Market Researcher / Strategist / Producer agents | PARTIAL | Named in the MCP page FAQ; the demos label only Researcher and Strategist; whether Producer is a distinct agent is undocumented |
| Wan2.2 I2V A14B 720p needs 80 GB on a single GPU | VERIFIED | Wan2.2 README: `--task i2v-A14B --size 1280*720 ... --offload_model True --convert_model_dtype` followed by "can run on a GPU with at least 80GB VRAM" (the TI2V-5B 720p command needs 24 GB) |
| HunyuanVideo 1.5 minimum 14 GB with offload | VERIFIED | README:136 "Minimum GPU Memory: 14 GB (with model offloading enabled)"; Wan2GP is listed at as low as 6 GB (third-party) |
| LTX Desktop Linux 24 GB recommended | VERIFIED with nuance | README:81 "NVIDIA GPU ... 24 GB or more VRAM (32 GB recommended)"; app still enables local generation from 9 GiB VRAM on fp8-capable GPUs and says it does not recommend lower-spec machines (README:88) |
| MultiShotMaster based on Wan2.1 T2V 1.3B/14B | VERIFIED | README Note: "open-source version is based on Wan2.1-T2V-1.3B and Wan2.1-T2V-14B"; multi-reference code/model not yet released |
| VieNeu v3 Turbo open, v4 proprietary | VERIFIED | README:16-22: v4 via vieneu.io API only, "v3 Turbo remains the latest open-source version" |

## Vendor-side findings that affect our integration

1. Veo 3.1 Preview models in the Gemini API were "shut down on October 22, 2026" per `aistudio.google.com/docs/video`, which points to `gemini-omni-1.2-flash` or GA Veo models on the Gemini Enterprise Agent Platform. The Vertex schema (`veo-3.1-generate-001`) is still published. If our Veo 3.1 backend uses the Gemini API preview ids, it needs a check. Fact: the shutdown statement. Unknown: which ids our code calls (I did not inspect our repo).
2. Gemini Omni Flash: 3-15 s, native audio, up to 6 reference images, conversational editing/extension, resolutions 360p-4K, seed support.
3. Kling: native multi-shot (`multi_prompt` up to 6 shots, 512 chars each) exists on v3; Omni 4.0 caps combined references at 15, elements at 7; persistent Elements from 1 frontal + 1-3 angle images; lip-sync is one person per request with a face-recognition pre-step.
4. Seedance 2.5 draft->final (section H). Wan 2.7 R2V and Seedance reference-video roles are available through the Comfy router schemas.
5. ComfyUI: the docs index I read exposes router schemas for Kling, Veo, Wan 2.x, Seedance, LTX, and an upscaler (`crystal-video-upscaler`, `ltx-video-upscale`), but I found no official multi-shot or character-consistency workflow guide in `llms.txt`. Calliope's example workflow `example_ComfyUI_workflows/MiniMaxH3-Singularity-Continuity-5Ref1Latent-API.json` is third-party.

## Where a donor does something we already have, but better

(Based on the project description in the task, not on a fresh read of our repo.)

- Continuity QA: AIVPE's 11-category rubric with explicit 180-degree/eyeline/staging rules, severity-capped scoring, `promptFix`, `needsReverseAngle`, and a ranked re-film queue is more specific than a generic VLM check. Calliope's nine-bucket prompt-vs-plan critic checks the prompt before generation, which is cheaper than checking after.
- Best-of-N: ViMax runs it at keyframe stage with a reference-aware VLM and persists candidates; our version runs at video stage with a weak local judge.
- Loudness: openfilm's true-peak oversampled limiter and re-measure-after-encode loop is stricter than a single `loudnorm` pass (Calliope) or a plain LUFS gain (OCC).
- Caption QA: open-edit checks timing windows, missing captions under speech, and face avoidance with numeric rules.

## Inferences (not stated by any source)

1. A camera tree with `missing_info` can be added to our storyboard variants as metadata (`parent_unit`, `covers_parent`, `delta`), and used to choose which unit's frame becomes the reference for the next unit.
2. Our provenance per artifact can store the `promptFix` text, the judge score and severity list, and the `draft_task_id`, making repair prompts auditable.
3. A "delivery promise" record (VGA) maps cleanly to our cost/budget reservation: if the budget forces stills where video was promised, stop and ask instead of degrading silently.
4. Beat-density and shot-fitness rules (OCC) matter mainly for music-led output; for dialogue-led output the Calliope rule "one short line per ~2.5 s, split between sentences" is the relevant pacing constraint.
5. Seedance `return_last_frame` plus Kling/Veo first/last frame are an API-only substitute for Calliope's latent passing, with weaker motion continuity (a still frame carries no velocity). Whether the loss is visible depends on content; untested.

## Unknowns and gaps

- Official BytePlus Seedance page body (parameter table, reference counts, multi-shot support) was not retrievable; the numbers 9 images / 3 videos / 3 audios and "last frame needs first frame" come from third-party gateways.
- Seedance 2.5 draft billing: sources conflict; Comfy gives no prices.
- Topview Video Agent behavior, Viral Video Agent analysis method, retention beyond the 7-day URL validity, and the Unlimited plan's API status are not documented in the pages I could read.
- MSM: no API; open weights are Wan2.1 T2V and need far more VRAM than the RTX 2070 8 GB. Multi-reference release status unknown. I did not read the paper PDF, only the abstract page and code.
- CHAI paper (arXiv 2604.21718) is cited by VGA for the 5-aspect format and critique-quality rules; I did not open it, so the prompt-length table's claim that it comes from the paper's Section 6 is unverified.
- AIVPE "Auto" model routing and its cost table are README claims; the routing code was not located. AIVPE color/LUT code was not read.
- VGA's `VideoAnalyzer` tool, `source_media_review.py`, and pipeline manifests were not read in depth.
- FilmAgent/MovieAgent/StoryDiffusion were checked at abstract level only; no code was read.
- VieNeu emotion control: README says `style` is deprecated with no effect; whether v3 Turbo has any other emotion lever is not established.

## Synthesis: our gaps vs donors, re-evaluated conclusions (main agent, 2026-11-13)

Internal baseline read at tag `r2-v2.5.16` (`git show`/`git grep` on the tag; this checkout's branch was not used).

### Internal facts (our weak points)
| # | Fact | Evidence @ r2-v2.5.16 |
|---|---|---|
| I1 | The only automatic profile that may launch is narration: FLUX.2 klein 4B stills, `still-clip-local` video, VieNeu v3 TTS, 576×1024, 45 s target. | `r2/automation/launch_profiles/fiction_narration_vi_v1.json` |
| I2 | Drama (dialogue) is always refused: `requires_lip_sync` → `DRAMA_ROUTE_NOT_QUALIFIED`; no lip-sync backend exists. | `server/production_run/preflight.py:47`, `fiction_drama_vi_v1.json` |
| I3 | No music bed, SFX, ambience or ducking anywhere in composition/render. | no match for music/bgm/sfx/duck in `r2/m3`, `server/production_run`, `lib/presentation_renderer.py` |
| I4 | TTS backends take no emotion/style/delivery parameter. | `lib/audio_backends/*` |
| I5 | Image judge asks only "does the picture show this narration line" (yes-prob or 0–10); no identity/continuity/180°/artifact check; deterministic unit checks are technical (blank, size, silence). | `server/production_run/image_judge.py:35-43`, `unit_checks.py` |
| I6 | Final checks: subtitles text sanity + black/fill picture only; LUFS is measured in quality probes but never normalized on the deliverable. | `final_checks.py`, `r2/quality/probes.py:108` |
| I7 | Gemini registry still lists `veo-3.1-*-preview` ids; the donor report says Veo 3.1 Preview was shut down in the Gemini API on 2026-10-22 (WebFetch-summarized, re-check). | `lib/config/registry.py:464-493` |

### Prioritized adoption (inference; each needs its own ADR/research-first pass)
P0 — raise the quality of the film we already ship automatically:
1. **Motion, not slideshow.** Qualify a cloud image-to-video route for the narration profile (Kling / Seedance with draft→final reuse) and add VGA's slideshow-risk score + delivery-promise lock as a final check (no silent downgrade to stills).
2. **Audio master.** Music bed + ambience with ducking under narration; openfilm loudness recipe (measure → one gain → oversampled limiter → re-measure; target −14 LUFS, −1 dBTP, 0.5 LU tolerance) applied to the deliverable; per-line delivery cues for TTS where the backend supports them.
3. **Continuity judge on stills with a cloud VLM.** Adopt AIVPE's 11-check ordered rubric (identity, wardrobe, props, location, lighting, screen direction, eyeline, staging, text, framing, artifacts; high severity caps score; `promptFix` feeds the regenerate prompt) and move best-of-N to the keyframe stage with ViMax-style comparison against reference sheets. This is what ADR-0112 lacks today (I5) and also unblocks the disabled best-of-N.
P1 — shot craft and drama:
4. Shot-size/camera enum and coverage rule (Calliope), camera tree + bounded reference selection ≤8 per frame (ViMax).
5. Unblock drama: Kling elements (frontal + 1–3 angles, voice-bound) and Kling lip-sync (one face per request) as a `lip_sync` route.
6. Per-model prompt dialects and length bands (VGA).
7. Delivery review checks: dead air/tail, caption timing and safe zones, caption styling (open-edit, OpenChatCut face avoidance).
P2: reference-video shot analysis (open-edit `shots`), FCPXML export, Topview/HeyGen only as optional backends, MultiShotMaster watch-only (no API, >8 GB).
Ops now: verify I7 against the official Gemini model list.

### Re-evaluation of the prior ChatGPT reports
- Right: hybrid local+cloud; do not depend on one vendor; hardware limits of the RTX 2070; benchmark the same script across backends; Topview Unlimited excluded from automation.
- Wrong or outdated: Topview 60-day retention (docs say API URLs valid 7 days); "build Video Director / router / queue / registry / cost manager" (exist already); placing V2 above R2 (V2 is R2; a second orchestrator is forbidden by ADR-0089); prioritizing Calliope/AIVPE as platforms to run (their value is specific mechanisms, adopted as donors).
- Missed entirely: the actual quality gaps I1–I6 (motion, audio master, continuity judging, drama/lip-sync), ViMax, and vendor features we already pay for but do not use (Kling multi_prompt/elements/lip-sync, Seedance draft→final).
