# Film craft quality: character, prompts, directing, camera, light, colour, music (2026-11-13)

Asked by the sponsor before the first cloud-writer story-to-film trial: research what drives product quality in character building, prompt writing, directing, shot design, camera angles, lighting, colour and music, then rank additions by value per effort. Builds on `2026-11-13-video-quality-donor-mechanisms.md` (donor mechanisms: ViMax, Calliope, AIVPE, VGA, OpenChatCut, openfilm) and `2026-11-13-r2-donor-sweep-2026-agents.md`; neither is repeated here.

Method: internal state read at `18d299bb6` (branch `impl/r2-film-quality`, = deployed `r2-v2.5.17` plus this research). External facts from primary sources fetched 2026-11-13 by one background research agent and spot-checked by the main agent (ffmpeg filters run locally; VieNeu README and shim read on the host). FACT = stated by the cited source; INFERENCE = ours.

## 1. Internal facts (what the automatic film does today)

| # | Fact | Evidence |
|---|---|---|
| C1 | A shot carries `scene` (free text), `composition{shot_type, lighting, ambiance}` and `video_prompt{action, camera_motion, ambiance_audio}`. `shot_type` is 9 values that mix size with OTS/POV; there is no camera angle (eye/low/high/overhead/dutch), lens or depth of field, 9:16 composition, screen direction, time of day or colour. | `lib/script_models.py:30-160` |
| C2 | The prompts deliberately give no criteria for choosing `shot_type` or `camera_motion` ("不强加倾向", "按画面内容自行选择"; design note at the top of the file). There is no coverage rule and no shot-variety check. The only pacing guidance: hook in the first ~4 s, end on a close-up. | `lib/prompt_builders_script.py:5,352-359`; `agent_runtime_profile/.claude/references/episode-pacing-narration.md` |
| C3 | Lighting is written per shot, and well (source, direction, Kelvin, film terms), but nothing anchors light or time of day for the scene, so shots in one scene are lit independently. | `lib/prompt_builders_script.py:162` |
| C4 | The image prompt is a YAML block `{Style, Scene, Composition}` in the story's language, ending in a negative tail "画面避免：水印、多余文字、Logo". There is one format for every image model. | `lib/prompt_utils.py:50-78`; `lib/prompt_builders.py:57-63` |
| C5 | A character is free text up to 600 characters ("appearance only") plus a 16:9 three-view sheet on white. There are no structured traits, palette or signature item, and no expression sheet. Costume/state derivatives exist in the app (ADR-0072), but the automatic run never creates them. | `lib/asset_extraction.py:36,59`; `lib/prompt_builders.py:26,88`; no `derivative` under `server/production_run` |
| C6 | The launch profile's video route `still-clip-local` holds the storyboard still unchanged for N frames. `camera_motion` is ignored and there is no zoom or pan. | `docs/r2/evidence/media-local-2026-10-30/still-clip/README.md:9-13`; `r2/automation/launch_profiles/fiction_narration_vi_v1.json` |
| C7 | The render has no colour grade or LUT; colour comes only from the style text. | no `lut3d`/`colorbalance`/`eq=` in the render paths |
| C8 | Audio: a two-pass `loudnorm` to the contract exists. There is no music bed, ambience or SFX mix, and no ducking; `ambiance_audio` is written and never used. | `lib/presentation_renderer.py:8,254-301` |
| C9 | The deployed TTS is VieNeu **v3 Turbo** (shim `MODEL_ID = "vieneu-tts-v3-turbo"`). The host GPU is an RTX 2070 with 8 GB. | `~/arcreel-v2-staging/vieneu-tts-shim`; `nvidia-smi` |
| C10 | Judges: the image judge checks narration match; the continuity judge (ADR-0134) checks identity, wardrobe and location. Nothing checks cinematography or variety. | `server/production_run/image_judge.py`, `continuity_judge.py` |

## 2. External facts that change what we should build

**Character and prompts**
- FLUX.2 understands prose and a JSON prompt equally well. BFL recommends JSON for automation and multi-subject shots. The keys are `scene`, `subjects[]{description, position, action}`, `style`, `color_palette`, `lighting`, `mood`, `background`, `composition`, `camera{angle, lens, depth_of_field}`. FACT, https://docs.bfl.ml/guides/prompting_guide_flux2 ("JSON Structured Prompts").
- More from the same BFL guide (FACT):
  - Earlier words weigh more; the order is subject → action → style → context.
  - FLUX.2 **does not support negative prompts**: phrase what you want instead.
  - Hex colours work best when bound to one object ("the jacket is #8B1E2D").
  - For multi-panel work, "define the character in full detail and repeat that description in every panel prompt".
- **Unknown:** whether the distilled FLUX.2 klein 4B follows hex and JSON as the documented pro and max models do.
- Gemini image: positive "semantic negatives", photographic camera language, and the template "A photorealistic [shot] of [subject] in [setting]. [light]. Shot from a [angle] with a [lens]". It takes up to 14 reference images (per model, e.g. 4–5 character images) and builds 360° views iteratively by feeding back earlier images. FACT, https://aistudio.google.com/docs/image-generation.
- Kling: short sentences, one movement sized for 5 s, camera language kept separate from camera motion. "Models are not sensitive to numbers", so counts drift. FACT, https://kling.ai/quickstart/text-to-video-prompt-guide.
- Veo: prompt slot order subject / action / scene / camera / lens / style / temporal; one subtle change per short clip; negatives are nouns, not "no …". It gives the example "dolly out … to emphasize their isolation". FACT, https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/video-gen-prompt-guide.
- **Not read:** the BytePlus Seedream and Seedance official guides (JavaScript shells; they need a browser render), Runway, LTX (403), and Wan (no official guide).

**What models reliably understand about cinematography** (this decides what a judge may check)
- ShotBench (arXiv 2506.21356) covers 8 dimensions. FACT (summarized table, re-check before quoting outside the team):
  - Best accuracy by dimension: shot size 75.1%, framing 85.4%, angle 58.2%, lighting type 65.5%, composition 55.2%; lens size, lighting condition and camera movement at most ~49%. Camera movement is near chance for many models.
  - ShotVL-3B is +19 points over its base model.
- CineTechBench (arXiv 2505.15145): video generators do badly on camera moves with intense rotation. CameraBench (arXiv 2504.15376): VLMs fail on geometric motion primitives, and zoom is confused with dolly. FACT (abstracts).
- INFERENCE:
  - A VLM may judge shot size and framing.
  - Lighting and colour consistency must be checked numerically: luminance, R/B ratio, dominant-colour ΔE.
  - The planner should use only motion moves the models do well: static, slow push-in or pull-out, slow pan or tilt; never orbit, whip pan, dolly-zoom or combined moves.

**Directing.** The 180° rule, eyeline match and shot/reverse shot (MIT film lexicon; Frame.io interview with a cinematographer) are FACT as definitions. There is no primary source for coverage patterns, headroom/lead room or the emotional meaning of camera moves, so those stay planner priors. 9:16 safe zones: third-party values disagree and no TikTok or Meta document was found.

**Colour.**
- Pixar colour scripts map each scene's emotional tone to colour; secondary sources only (Romano, Eggleston interviews).
- ffmpeg 8.0.1, checked locally with `-h filter=` (FACT):
  - `lut3d=file=…:interp=tetrahedral`;
  - `haldclut` with 2 inputs;
  - `colorbalance` with `rs…bh` in −1..1 and `pl`.
- A uniform grade is therefore a single filter on the deliverable.

**Music and sound** (FACT, https://github.com/ace-step/ACE-Step-1.5 README and `docs/en/Tutorial.md`)
- **ACE-Step 1.5:**
  - length 10–600 s, where `duration` is a target that "may vary"; 30–60 s is stable;
  - the 2B turbo model fits ≤6 GB with INT8 and offload, so on the 8 GB 2070 it runs only between FLUX jobs, not alongside them;
  - `[Instrumental]` plus short section tags such as `[Outro - fade out]`;
  - BPM, key and time signature go in metadata, never in the caption;
  - the caption is "the most important factor" (genre, mood, instruments, timbre, era).
- **Ambience and foley:**
  - Stable Audio Open 1.0: ≤47 s, English prompts, good at SFX and field recordings.
  - MMAudio: ~6 GB, 8 s windows, text-only mode; can produce speech-like artefacts.

**Vietnamese narration** (FACT, https://github.com/pnnbao97/VieNeu-TTS README "Emotion cues", and the host clone)
- VieNeu v3 Turbo takes inline experimental cues `[cười]`, `[thở dài]`, `[hắng giọng]`.
- `style` has no effect on v3, so reading style comes from the chosen voice or a cloned reference clip.
- There is no documented pause control.
- **Correction** to `2026-11-13-r2-donor-sweep-2026-agents.md`: our deployed TTS has non-verbal emotion events. It still has no continuous emotion control.

**Short vertical drama.** A hook in the first 3 s and a cliffhanger per episode are industry convention (trade press only; no controlled retention data found).

## 3. Ranked additions (value per effort)

Value means visible quality in the narration film we ship today (C6: a still slideshow). Effort assumes the existing seams.

| Rank | Addition | Why (fact → gain) | Effort | Needs |
|---|---|---|---|---|
| **P0-1** | **Motion on still clips:** a slow push-in, pull-out, pan or tilt (Ken Burns) driven by the shot's `camera_motion`, using `crop` or `zoompan` with easing, ~3–8% scale over the clip. The enum the planner may use is restricted to these moves. | C6: every shot is a frozen frame, which is the strongest "slideshow" signal. Benchmarks say slow single moves are the reliable ones. | S: a ComfyUI graph or ffmpeg step plus an enum subset | none, local |
| **P0-2** | **A uniform grade on the deliverable:** a grade preset per project (`neutral`, `warm_nostalgic`, `cold_blue`, `teal_orange`, `desaturated_drama` → one `.cube` file or one `colorbalance` string), chosen from genre and mood and applied before subtitles. | C7. Independently generated stills drift in colour; one transform unifies them. The ffmpeg filters are verified. | S | none |
| **P0-3** | **A scene look record:** each scene gets `time_of_day`, a key-light setup (direction, quality, Kelvin, practicals), `palette{dominant, accent}` and `mood`, written once per scene (a colour script), copied into every shot's prompt, and used to pick the scene's grade offset. | C3: lighting is per shot today. BFL's `lighting` and `color_palette` keys are the documented lever; a colour script ties colour to the emotional arc. | S–M: a schema field plus a prompt section | none |
| **P0-4** | **A character bible plus a canonical block:** structured traits (age range, build, 3–5 stable face/hair traits, an outfit with hex bound to each garment, a signature item, a voice), rendered into one fixed ≤60-word block injected verbatim at the head of every shot prompt that names the character. The sheet adds a 3/4 view and 2–3 expressions. | C5. BFL's "repeat the full description in every panel" and the earlier-words-weigh-more rule; it directly lowers the identity drift our continuity judge reports. | M | test klein's hex adherence |
| **P0-5** | **A music bed:** one ACE-Step 1.5 2B-turbo instrumental cue per film (caption from genre and mood, BPM from average shot length, requested length plus 3 s, `[Outro - fade out]`), then trimmed, faded, ducked under narration (donor recipe), mastered by the existing loudnorm. Batch 3 candidates and pick one numerically. | C8: no music at all. It fits the 2070 when run between image jobs. | M | install and a VRAM check on the host |
| **P0-6** | **Narration delivery:** let the script place `[thở dài]` / `[cười]` / `[hắng giọng]` at story beats (sparingly, behind a quality check); build pauses by splitting the text and inserting silence; strip cues from subtitles; pick the voice per story mood. | C9: the cue support is already deployed, so this costs prompt text and a subtitle filter. | S | A/B listen on 2–3 samples |
| **P0-7** | **Shot grammar in the planner:** add a camera `angle` (eye, low, high, overhead, dutch) beside size; defaults of an establishing wide at each `segment_break`, inserts/cutaways for objects and hands under narration, and a close-up at emotional peaks; a deterministic check of no more than 2 same-size shots in a row and a first shot that plants a question. Reverses C2's no-criteria design note, so it needs an ADR. | C2: no variety rule today. Shot size and framing are what models follow and judge best (ShotBench). | S–M | ADR (design change) |
| P1-8 | **An image-prompt dialect per model.** FLUX.2: English JSON or prose, subject first, positive-only (drop the "画面避免" negative tail, which FLUX.2 does not support), lens phrased as "35mm f/1.4". Gemini: its photoreal template. Kling/Veo: noun negatives. | C4 is one Chinese/Vietnamese YAML format for all models. The gain is unmeasured. | M | A/B on klein, same seeds, judged pairwise |
| P1-9 | **A numeric look-consistency check:** per scene, mean luminance, R/B ratio and dominant-colour ΔE against the scene look record; regenerate the outlier. A VLM judges only size and framing (variety). | VLMs read lighting and lens at ≤49%. Numbers are deterministic and cost no quota. | S–M | P0-3 |
| P1-10 | **Wardrobe/state variants in the automatic run:** the asset stage registers derivatives (ADR-0072) when the story changes a character's outfit or state, and shots reference them. | C5: the variants exist but are unused. The continuity judge flags scripted costume changes as drift. | M | none |
| P1-11 | **An ambience bed** from the existing `ambiance_audio` field: Stable Audio Open (English prompt translated from the field, ≤47 s, crossfade-looped) mixed low under narration and music. | C8: the field is written today and wasted. | M | install, ≈ VRAM check |
| P1-12 | **Screen direction:** per scene `axis_side`, per character `screen_side` and `look_dir`; a check on consecutive shots that two characters face each other. | 180° rule and eyeline match. It matters mainly for dialogue, so it ranks above P2 only once drama ships. | M | — |
| P2-13 | Per-clip foley with MMAudio once clips have real motion; a leitmotif (same caption fragment and key per lead character); ShotVL-3B as a local shot-size/angle classifier. | Lower marginal value before real video. | M–L | real video route |
| P2-14 | Read the BytePlus Seedream/Seedance guides through a browser render before writing their dialects. | Official rules are unknown. | S | browser |

Order to build: P0-1 and P0-2 together (the render path, both local, visible on the very first trial film), then P0-3 with P0-4 (both are prompt and schema work on the script stage), then P0-5 and P0-6 (audio), then P0-7 under an ADR. P1-8 and P1-9 need P0-3 and a measured A/B.

## 4. Unknowns

- Whether FLUX.2 klein 4B follows hex colours, JSON prompts and English better than our Chinese/Vietnamese YAML; measure with fixed seeds and a pairwise judge.
- ACE-Step 2B-turbo peak VRAM and time on the 2070 with ComfyUI resident; whether its instrumentals suit Vietnamese drama.
- How natural VieNeu's emotion cues sound across voices (labelled experimental upstream).
- The official Seedream/Seedance, Runway, LTX and Wan prompt rules; platform safe zones for 9:16; Vietnamese narration words per minute (we measured 3.7 syllables/s on our own run).
- ShotBench per-dimension numbers are from a summarized table; re-check the paper before citing them externally.
