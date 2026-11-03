# Stronger and cloud models for the automatic quality gate

Date: 2026-11-03. Branch `impl/autonomous-production` at `87984816a`. Sponsor question: research stronger or cloud
reviewer and generation models so an automatic run earns a real quality PASS.

## 1. Internal state (facts)

- The automatic run reaches QUALITY on real GPU (handoff, 2026-11-03). QUALITY combines two qualified reviewers;
  both must accept (`r2/automation/assessment.py::combine`: all five creative scores ≥ 4, no CRITICAL/MAJOR).
- Last run, episode 1 (35.2 s, 19 still-image clips):
  - `qwen2.5vl:7b` (probabilities method): story 4, **visual 3**, audio 5, continuity 4, pacing 4; four MINOR
    findings ("subtitles add information the narration lacks"). The same scores on a Ken Burns copy of the final,
    so motion is not the cause.
  - `gemma3:4b` (questions method): visual 5, but CRITICAL `FRAME_UPSIDE_DOWN` ("3 frames upside down"). Frames
    inspected by the agent: none is upside down; the frames are a water-reflection shot. The method ORs the
    standalone and the 180°-comparison answers (`evaluators.py`, `flipped.append(True if True in (alone, compared)…)`).
- What the visual 3 reflects (agent inspection of `characters/Nam.png` and storyboards E1S01-E1S04): storyboards that
  carry the character reference match the sheet (FLUX.2 klein i2i works); E1S01 lists no character, so its boy is a
  different person; the 9B writer's asset description of Nam does not fit the story's setting. Both are writer
  (planning/description) weaknesses, not image-model weaknesses.
- Reviewer contract: `OllamaReviewer` is the only evaluator. Independence group is per model identity
  (`quality_record.py:120`), so two models of one vendor are formally independent.
- Cloud already integrated: text/image/video backends for Gemini, OpenAI, Ark, Grok, Kling, Vidu, DashScope, MiniMax,
  Agnes (`lib/*_backends`). Text backends that take images: gemini, openai, ark, grok, ollama. A live probe of
  `gemini-2.5-flash` through the AI Studio provider passed with a $0.10 cap on 2026-10-24
  (`docs/r2/evidence/R2_STORY_CLOUD_UI.json`); the saved key lists the Gemini 3.x catalog
  (`docs/research/2026-10-23-v2-gemini-text-model-catalog.md`).
- Policy: automatic runs are `local_only` today; paid routes need `max_cost_per_call > 0`, a run cost cap and a
  matching currency (`preflight.py`).

## 2. Primary sources (Google AI Studio docs, read 2026-11-03; ai.google.dev now redirects there)

- [Video understanding](https://aistudio.google.com/docs/video-understanding): Gemini processes "both the audio and
  visual streams"; default sampling 1 frame/s; about 258 tokens/frame (66 at low media resolution) plus 32
  tokens/s of audio, i.e. roughly 100-300 tokens per second of video; inline data for small requests (text says
  under 20 MB), Files API otherwise; "All Gemini models can process video data".
- [Models](https://aistudio.google.com/docs/models): stable `gemini-3.6-flash`, `gemini-3.5-flash-lite`,
  `gemini-3.1-flash-lite`; new `gemini-3.8-flash`, `gemini-nano-banana-2.1` (image); flagship `gemini-4-argon`;
  `gemini-3.1-pro-preview`; `gemini-2.5-flash` is deprecated (routes to `gemini-3.5-flash-lite` from 2026-12-01).
- [Pricing](https://aistudio.google.com/docs/pricing), paid standard tier per 1M tokens: `gemini-3.8-flash` and
  `gemini-3.6-flash` $0.75 in / $3.75 out until 2026-12-31 (then $1.50 / $7.50); `gemini-3.5-flash-lite` $0.30 /
  $2.50; `gemini-4-argon` $2 / $10 until 2026-11-30 (then $4 / $20). Flash models also have a free tier, whose
  content Google may use to improve products; paid-tier content is not.
- Local 8 GB alternatives (secondary sources only, no head-to-head video benchmark found): Qwen3-VL (4B/8B), Gemma 4
  E4B, MiniCPM-V 4.6 accept images and sampled video frames. `qwen3-vl:8b` was already rejected here (ignores
  `think:false`); `gemma3:12b` rejected every clean case.

## 3. Inferences

- A Gemini reviewer can watch the actual final (picture, narration audio and burned subtitles in time), which the
  local reviewers approximate from 8 sampled frames plus SRT text; the upside-down and subtitle/narration false
  findings are artefacts of that approximation.
- Cost is negligible: a 35 s final is about 3.5-10.5 k input tokens, so one Flash review is about $0.01; requalifying
  on the 40-case corpus with two reviewers is about $1.
- Generation strength matters most at the writer: the visual-consistency loss comes from planning and asset
  descriptions. A cloud writer/script model (Gemini Flash) addresses it directly; FLUX.2 klein with references is
  adequate locally. Cloud image/video (Nano Banana, Seedream, Kling, Veo, Vidu) raise visual quality further but are
  not needed to pass the gate.

## 4. Unknowns

- Whether a Gemini review of a real final scores ≥ 4 on all five dimensions (needs a bounded live probe).
- Whether the saved key is on the paid tier (pricing and data-use terms differ).
- Whether a second, different-vendor reviewer (OpenAI or Ark vision on frames) is required for real independence, or
  two Gemini models are accepted by the sponsor.

## 5. Options

1. **Cloud reviewers (recommended first):** add a `GeminiReviewer` evaluator (inline mp4 + narration + subtitles, the
   same JSON assessment contract), qualify `gemini-3.8-flash` and a second identity (`gemini-3.6-flash` or a
   different vendor) on the existing corpus (about $1), and route `reviewer_a`/`reviewer_b` to them in a paid policy
   with a small run cap. Keeps the local generation pipeline.
2. **Cloud writer/script:** route `writer` and `script` to Gemini Flash under the same paid policy; Story already has a
   cloud gateway qualification path (ADR-0109). Fixes the consistency root cause.
3. **Cloud image/video:** Nano Banana / Seedream for images, Kling/Veo/Seedance/Vidu for video, for commercial quality.
4. **Stronger local reviewers:** fix gemma's orientation OR → AND and requalify; try Qwen3-VL 4B / Gemma 4 E4B. Free,
   but the 8-frame approximation and the writer weaknesses remain.

Recommended order: 1, then 2; 3 when commercial quality is the target; 4 as the free local fallback.

## 6. Live Gemini probes (2026-11-03, key on the free tier)

Watch-method reviews (`server/production_run/gemini_reviewer.py`), mp4 inline, temperature 0:

| Model | d18 upside down | d03 other-story images | c05 clean (inconsistent characters) | debug final (`kb`) |
| --- | --- | --- | --- | --- |
| gemini-3.6-flash | rejected: "rotated 180° from 00:05" | rejected: visuals do not match narration | rejected: inconsistent characters (3s) | rejected: story 3, visual 3, no findings |
| gemini-3.5-flash-lite | accepted (4s) | accepted (5s) | accepted (5s) | accepted (5s) |

- Lite models accept real defects: unusable as reviewers.
- `gemini-4-argon` answered 429 (quota; no free tier), `gemini-3.8-flash`, `gemini-3.6-flash` and `gemini-3.1-flash-lite`
  answered 503 (high demand) for minutes at a time; the reviewer now backs off up to six times.
- Inference: a real reviewer (3.6 Flash) judges the local productions at 3/5 — the debug story is a sentence pool
  from several stories (story 3 is correct) and the pictures are still images with uneven characters. With a strict
  reviewer a local run will not earn PASS; reaching EXPORT locally needs either a coherent real-writer story plus
  better pictures, or a policy that records the quality verdict without gating export (sponsor decision).
