# Character identity across scenes, and how donors solve our known problems (2026-11-13)

Asked by the sponsor: research more on keeping a character the same across different scenes, and on how donors and other projects solve the problems we already know about. Follows `2026-11-13-r2-film-craft-quality.md`, `2026-11-13-video-quality-donor-mechanisms.md` (§A identity, already read donors) and `2026-11-13-r2-donor-sweep-2026-agents.md`; facts there are not repeated.

Method: internal state read at `4de79529b` (`impl/r2-film-quality`). External facts come from primary sources fetched 2026-11-13 by one background agent. Pages were summarised by WebFetch, so the numbers are as the summary quoted them. Donor checkouts were read locally: ViMax (no `.git`, commit unknown), Jellyfish `a967819`. FACT = stated by the source; INFERENCE = ours.

## 1. Our identity path today (internal facts)

| # | Fact | Evidence |
|---|---|---|
| I1 | A storyboard's references are the sheets of the segment's characters, then the scene and prop sheets, extra references, then the previous storyboard. | `server/services/generation_tasks.py:552-616` |
| I2 | The local FLUX.2 klein reference endpoint has **3** reference slots (`ReferenceLatent`, 1 MP each). The ComfyUI backend keeps the first 3 and **silently drops the rest** (`request.reference_images[:slots]`). Two characters plus a scene fill it, so props and the previous storyboard are lost; three characters lose the scene. | `lib/custom_provider/comfyui_image_backend.py:106-172`; `docs/r2/evidence/media-local-2026-10-30/flux2-klein-reference/README.md` |
| I3 | A character's reference is its whole 16:9 three-view sheet (front, side and back on white) scaled to 1 MP, so the face is a small part of the pixels. No face close-up reference exists. | `lib/prompt_builders.py:26,88` |
| I4 | Only the Gemini backend tells the model which reference is which character. A ComfyUI prompt never binds "image N" to a name, so two-character shots can mix identities. | `lib/image_backends/gemini.py:162-182` |
| I5 | Costume and state variants (derivatives, ADR-0072: an edit of the base sheet) exist, but the automatic run never creates them, and the continuity judge compares a scripted costume change with the base sheet. The donor sweep's "new costume asset kind" proposal is superseded: the run should use derivatives. | no `derivative` under `server/production_run`; `server/production_run/continuity_judge.py` |
| I6 | Best-of-N for stills exists but is disabled (ADR-0112), and `pairwise_judge` has no caller. | `2026-11-13-video-quality-donor-mechanisms.md` §Synthesis; `audits.py:567` |

## 2. External facts on identity

**Reference slots in base models**
- FLUX.2 klein takes **up to 4 references**; dev is recommended up to 6; pro, max and flex take 8 through the API. FACT, https://docs.bfl.ai/flux_2/flux2_overview ("reference limits").
- A whole three-view sheet uses one slot.
- Gemini 3 Pro Image takes up to 14 references, of which 5 can be characters; 3.1 Flash Image takes 4 characters. FACT, https://aistudio.google.com/docs/image-generation.
- Qwen-Image-Edit-2509 works best with 1–3 inputs, including person + person. FACT, https://huggingface.co/Qwen/Qwen-Image-Edit-2509.
- Kling O1: 7 slots shared by elements, images and the start frame. Its element library keeps costumes as their own element category, and warns that front + side only "makes Kling guess" unseen parts. FACT, fal docs and the Kling guide.
- Wan 2.6 R2V: up to 5 characters, with references given as videos. FACT, https://www.alibabacloud.com/help/en/model-studio/wan2-6-r2v.
- Official Seedream limits: unknown (the BytePlus page did not render).

**Identity adapters on 8 GB**
- **DreamO** (FLUX.1) is the only open adapter whose README states an 8 GB path: Nunchaku + CPU offload, "24 GB → 6.5 GB", about 20 s per 1024 image on a 3080. It combines ID, IP and **try-on (garment)** conditions. FACT, https://github.com/bytedance/DreamO.
- PuLID-FLUX needs 16 GB (12 GB local). InfiniteYou needs ≥16 GB, as do UNO and XVerse. FACT (their READMEs).
- InstantID uses "only the largest face", so it cannot do two people. FACT.
- Published face similarity on real photos:
  - PuLID (SDXL) 0.733 / 0.659 and InstantID 0.725 / 0.614 FaceSim (PuLID paper, Table 1);
  - InfiniteYou ID loss 0.209 (cosine ≈ 0.79) against PuLID-FLUX 0.225.
- In video, FaceSim is far lower. OpenS2V Table 3 (arXiv 2505.20292): Kling 1.6 40.1%, Vidu 2.0 35.1%, Phantom-14B 51.5%, VACE-14B 55.1%.

**Per-character LoRA**
- BFL's klein 4B LoRA guide states a minimum of **12 GB VRAM** plus 32 GB RAM; for a character, 1500–3000 steps at LR 8e-5–1e-4, taking 1–3 h. FACT, https://docs.bfl.ai/flux_2/flux2_klein_training.
- No source confirms training on 8 GB, so this route needs a cloud or rented GPU. Dataset size (10–60 images) has only weak third-party sources.

**Training-free story methods**
- StoryDiffusion and ConsiStory/1Prompt1Story need attention hooks on SD/SDXL, which a ComfyUI GGUF klein does not expose.
- IdentityStory (arXiv 2512.23519, snippet only) reports pairwise ArcFace face similarity of 55.5% against 27.1% for the next best method. INFERENCE: methods without adapters top out around 0.3–0.55.
- VideoMemory (2601.03655), StoryMem (2512.19539) and STAGE (2512.12372) are real papers; only their abstracts were read. Their patterns are an entity memory bank updated after each shot, a keyframe memory, and start + end frame pairs per shot.

**Post-hoc repair**
- ReActor (inswapper_128 + CodeFormer) has a face-similarity node and face index mapping for several faces. It works at 128 px, so faces in a 576×1024 frame are often below its sweet spot, and stylised faces are out of its domain (INFERENCE).
- No official ArcFace "same person" threshold exists. Community nodes use 0.45 (default) and 0.60 (strict).
- ViStoryBench's character identity score combines ArcFace 0.4, AdaFace 0.4 and FaceNet 0.2 on Grounding-DINO crops, for realistic characters only. FACT, https://github.com/ViStoryBench/vistorybench.
- **The threshold must be calibrated on our own approved and rejected pairs.**

**How the story-to-film projects do it** (FACT, local checkouts)
- **ViMax** generates the same three-view sheet we do (`agents/character_portraits_generator.py`). Then:
  - `agents/reference_image_selector.py` sends **at most one view per character**, preferring the view taken by the same camera, plus earlier frames, up to 8 references in total. The prompt maps each element to "Image N". Its library can hold several outfits per character, and the LLM picks "the version described".
  - `agents/best_image_selector.py` generates 2 candidates in parallel and an MLLM picks the one most consistent on gender, ethnicity, age, face, body, outfit, hair and layout.
  - `pipelines/script2video_pipeline.py` (around line 401) reuses an earlier frame as the plate and replaces only the characters ("Don't change the background").
- **Jellyfish** (`a967819`) keeps a **costume timeline**: per character and per `shot_index`, a `costume_note`, the `changes`, the evidence span in the source text and the `scene_id` (`front/src/services/generated/models/CostumeTimelineEntry.ts`). It also runs script consistency and variant analysis.
- From the donor sweep: FilmWorld hashes each entity *state* (costume, injury, age) and generates its reference at first appearance. CineCrew names stable references plus required and forbidden props per clip.

## 3. Known problems → what donors do → what we add

| Problem (our evidence) | Donor solution (source) | Our addition | Value / effort |
|---|---|---|---|
| **Identity drift between shots** (continuity judge corpus; I2–I3) | ViMax: one view per character, matched to the camera, plus earlier frames; Kling: frontal image + angles as one element; BFL: repeat the full description in every prompt | **ID-1** Cut the sheet into its three views (the layout is fixed, so the crop is deterministic) and send the view that matches the shot, plus a **face crop** of the front view. Raise the klein endpoint to its **4** slots. Pick references in priority order, never silently: characters' view, then face, then scene, then previous approved shot of the same scene. Report what was left out. | high / S |
| | ViMax best-of-2 with an MLLM pick; DramaAgent K=3 with a weighted identity score | **ID-2** Enable N=2–3 candidates on stills (the 4-step local klein takes about 21 s each) and pick with the continuity judge plus face cosine; wire up the uncalled `pairwise_judge` for ties. | high / M |
| | ViStoryBench character identity score; community ArcFace thresholds | **ID-3** Measure face cosine (InsightFace) from each shot to the sheet face. **Calibrate the threshold** on 50–100 of our own approved and rejected pairs before it gates anything. Check that it works on our art style. | enables ID-2/ID-5 / S–M |
| **Two characters mix** (I4) | ViMax "Image N = element" binding; Kling `@Element1`; Gemini labelled references | **ID-4** Name each reference in the prompt ("image 1: Lan, front view; image 2: Minh …") and place each character left or right in the scene text. When a shot holds more characters than the slots, plan it as over-the-shoulder or single shots instead. | high / S |
| **A scripted costume change is judged as drift** (I5) | Jellyfish costume timeline with evidence; FilmWorld state hashes; ViMax picks "the version described" | **ID-5** The asset stage writes a costume/state timeline (character, segment, state, evidence text), registers a derivative sheet per state through the existing ADR-0072 edit path, and lets segments name `Name/state`. The storyboard and the **continuity judge use the state's sheet**. Age is handled as a state. | high (drama) / M |
| **A bad face in an otherwise good frame** | ReActor face swap; inpainting with a reference | **ID-6** Repair loop: when the face cosine is below the threshold, crop the face, re-render the crop with a klein edit using the face reference, then feather-paste. ReActor only for frontal faces ≥100 px. | medium / M |
| **Ceiling of reference-only identity** | Per-character LoRA (BFL klein guide); DreamO ID + try-on at 6.5 GB | **ID-7** Run DreamO against klein on 20 fixed shots (face cosine, outfit retention, seconds per image). Train a cloud LoRA for **main characters only**, from ArcFace-filtered generated shots, if a free GPU path exists. | medium / M–L |
| **Background changes between angles of one room** | ViMax camera tree + plate reuse ("replace the characters … don't change the background") | P1: reuse the scene's first approved wide shot as the plate for later shots in the same scene, using a slot from ID-1. | medium / M |
| **Still slideshow** (craft C6) | Calliope latent chaining, VGA slideshow-risk score | Craft P0-1: Ken Burns from `camera_motion`; later a cloud I2V with start + end frames (STAGE). | high / S |
| **Colour and light drift** (craft C3, C7) | CineCrew staging layer; BFL `lighting` / `color_palette` keys | Craft P0-2 / P0-3: one grade plus a scene look record. | high / S |
| **No music or ambience** (craft C8) | One Sentence BGM + mix; FRAMEWORKERS audio agents; VGA ducking recipe | Craft P0-5 (ACE-Step) and P1 ambience. | high / M |
| **Flat narration** (craft C9) | DramaAgent per-line emotion; VGA delivery cues | Craft P0-6: VieNeu `[thở dài]` cues plus pauses. | medium / S |
| **Monotonous shots** (craft C2) | AIVPE coverage rule; Calliope `shot_size` enum; VGA variety checker | Craft P0-7 (ADR). | medium / S–M |
| **Model quota and errors mid-run** | — | Done: ADR-0139 fallbacks. | — |
| **Long-story continuity** | novel-agent event, item and foreshadowing ledgers; spoiler-safe retrieval | Donor sweep P2 (typed state delta). | — |

## 4. Recommended order

1. **ID-1 + ID-4** (S): reference selection, crops, the 4th slot, name binding, no silent truncation. This is all in `generation_tasks.py`, the klein endpoint definition and the prompt builder. Measure on a fixed set of 20 shots with ID-3's cosine, before and after.
2. **ID-3** (S–M): the face-cosine instrument and its calibration. Every later loop depends on it.
3. **ID-2** (M): N candidates plus the pick, re-enabling ADR-0112 with this signal.
4. **ID-5** (M): the costume/state timeline into derivatives. It is needed before drama and before any story with costume changes.
5. ID-6, then ID-7, once the numbers from steps 1–3 show what is left.

These sit beside the craft P0 list. A sensible first build is craft P0-1/P0-2 (render) with ID-1/ID-4 (references), because they touch different files and all are visible in the first trial film.

## 5. Unknowns

- How well klein 4B GGUF keeps identity from a single-view crop or a face crop compared with the whole sheet. Only our own A/B can say.
- Whether ArcFace separates our painted or stylised characters (InsightFace is trained on real faces). If it does not, the MLLM judge stays the signal.
- DreamO's real speed and quality on the RTX 2070 (Turing has no bf16).
- LoRA training on 8 GB (undocumented; 12 GB is the documented floor), and whether any free GPU path exists.
- Official Seedream reference limits; the code paths of huobao-drama, ai-short-drama, MovieAgent, AniMaker and Toonflow were not read.
