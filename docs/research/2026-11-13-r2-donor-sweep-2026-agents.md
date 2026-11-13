# Donor sweep, 2026 story and film agents: what to add for quality (2026-11-13)

- **Baseline:** `impl/r2-film-quality` at tag `r2-v2.5.17` (prepared, not deployed). Earlier research this extends (not repeated): [roadmap synthesis 11-13](2026-11-13-r2-quality-roadmap-synthesis.md), [stage re-audit 11-13](2026-11-13-r2-workflow-stage-reaudit.md), [video donor mechanisms 11-13](2026-11-13-video-quality-donor-mechanisms.md), [stage-by-stage 11-11](2026-11-11-r2-donor-stage-by-stage.md), [donor deep dive 11-11](2026-11-11-r2-donor-deep-dive.md), [writing capabilities 11-09](2026-11-09-r2-donor-writing-capabilities.md), [stage mechanisms 11-08](2026-11-08-r2-donor-stage-mechanisms.md). Donors already covered there: huohuo, OpenMontage, TAKE, DramaClaw, ViMax (repo), shenbi, ASF, BUT, JF, AIVPE, Calliope, openfilm, OpenChatCut, open-edit, VGA, Topview.
- **Method:** web search for projects published or updated in 2026, then primary sources only (arXiv abstract + HTML full text, GitHub READMEs and their linked docs, model cards). Long arXiv HTML pages were read verbatim for the first ~40k characters; details only seen in a summarized remainder are marked **[S]**. No code was cloned or run. Internal facts were checked in the worktree.
- **Labels:** **[F]** fact with a source, **[I]** inference, **[U]** unknown.
- **What already landed today (not proposals):** ADR-0133 mastering −14 LUFS, ADR-0134 continuity judge (+ cast check), ADR-0135 voice-paced planning, ADR-0136 batch launch qualification, ADR-0137 alerts, ADR-0138/0139 model switching and fallbacks.

## 1. New donors read

### Film / drama agents (papers)

| Donor | Date | What it does that we do not | Source |
|---|---|---|---|
| **DramaAgent** (arXiv 2610.00097, code `AIGeeksGroup/DramaAgent`) | 2026-09-08 | [F] K=3 candidate clips per scene; reflection score = weighted sub-scores identity 0.35 / semantic 0.30 / temporal 0.20 / audio-visual 0.15; accept if best ≥ τ = 0.80; repair rewrites the prompt for the **weakest sub-score only**; ≤ 2 rounds or stop when gain < ε = 0.02; [S] ≈ 4.1 API calls/scene. Per-line dialogue with speaker, emotion and delivery; multi-speaker TTS; ambience/BGM generated or retrieved. Ablation: subject consistency 92.10 → 97.02 with the loop. | abs + html |
| **CineCrew** (arXiv 2609.07720, ECCV 2026) | 2026-09-07 | [F] A clip DSL ("FilmDSL") that names stable references (`char_id`, `sheet_ref`, `set_ref`), **required / forbidden props** and a `continuity_link` per clip; staging layer with shot type (CU/MS/WS), camera move, framing, lighting; keyframe-first, then video; last-frame→first-frame chaining for continuous takes; a **Production Rulebook updated from the reviewer's critique logs**; reviewer edits continuity fields first, then keyframe prompt, then video prompt. VLM evaluator Gemini-3-Flash. Identity consistency 75.12 vs LTX-Studio 67.15. | abs + html |
| **FilmWorld** (arXiv 2607.19038) | 2026-07-21 | [F] Each entity **state** (character in a given costume/injury/age) gets a deterministic hash id, and its reference image is generated at first appearance and reused by id; [S] a shot's planned **end state drives the next shot's opening state**; sliding window (2 target shots, 1 context shot each side); verifier on keyframes then video, ≤ 3 rounds, **rollback to the best earlier output** when no improvement (Gemini 3.1 Pro). Ablation without world state 84.28 vs 90.15. | abs + html (partly [S]) |
| **ViMax paper** (arXiv 2606.07649, `HKUDS/ViMax`) | 2026-06-02 / v2 07-21 | [F] Camera-level dependency graph built at planning; generation in topological order with **parallel independent branches**; dependent cameras inherit "visual anchors"; transition videos between angles; best-of-2 keyframe chosen by a VLM; shot plans with over-the-shoulder / reverse / insert; [S] establishing wide → medium → close-up. No audio. ViMax-Bench (35 stories). | abs + html |
| **One Sentence, One Drama** (arXiv 2605.22144) | 2026-05-21 / v2 10-25 | [F] Story by multi-agent debate over an **Idea Bank**; text review by three LLM judges with a final decider; clip-script review rewrites by part (**hook, ending, twist density**); per-scene 360° panorama + 3D world for layout continuity; **BGM chosen from a library (8,122 tracks) by category, segments scored by an audio LLM; mix with LUFS calibration and speech-preserving compression**. [S] ≤ 3 retries then best candidate kept. Cost $25–27 per minute. | abs + html (partly [S]) |
| **FRAMEWORKERS** (arXiv 2608.29814) | 2026-08-30 | [F] Director edits a dynamic task stack; evaluator re-generates on "asset drift"; [S] audio sub-agents for narration, music, mix, ambience, translation. Mostly a planner paper; code "will be released". | abs + html |

### Production workspaces (code)

| Donor | License / activity | Mechanism | Source |
|---|---|---|---|
| **Jellyfish** (`Forget-C/Jellyfish`) | Apache-2.0, 7.2k stars | [F] Script breakdown extracts characters, scenes, props, **costumes** and dialogue into a shared entity model that shots link to; per-shot "unified readiness state"; single and batch pre-checks before generation; async tasks with cancel/recover. Video models and scoring not stated. | README |
| **AIDrama Studio** (`EvoLinkAI/ai-short-drama`) | MIT | [F] Novel → script analysis → storyboard → images → videos → voiceover; one gateway key routes Kling/Seedance/Vidu/Veo/MiniMax, FLUX/Imagen, CosyVoice; 2–4 candidates per shot **picked by hand**; "roughly $1–5" per 2-minute drama (FAQ, not measured). | README |

### Story agents (code)

| Donor | License / activity | Mechanism | Source |
|---|---|---|---|
| **InkOS** (`Narcooo/inkos`) | AGPL-3.0, 11.2k stars, 1,648 commits | [F] Roles Radar, Planner, Composer, Architect, Writer, **Settler** (emits a typed state delta per chapter, validated and applied immutably to authoritative JSON state; Markdown is only a projection; SQLite FTS index is rebuildable), reviewer, Reviser (acts only on an explicit goal). Audits produce **observations, not pass/fail**: character memory, material continuity, hook payoff, outline drift, pacing, emotional arc. De-AI is a separate swappable skill run on demand; "no hidden word list rewrites text". | README |
| **novel-agent** (`lipfei06/novel-agent`) | MIT, small | [F] 11 stages with human accept/edit/regenerate; memory = recent full chapters / chapter (80–150 字) and volume (300–500 字) summaries / vector store; **event ledger + item registry + foreshadowing ledger**; dual retrieval: vector ∪ temporal knowledge graph whose edges carry the chapter number so **queries see only earlier facts** (spoiler-safe); code quality gate (scene-duplicate check over a 3-chapter window, beats, style metrics) flags only; consistency repair of offending scenes, 3 rounds then Human; cost per chapter and model. | README |
| **AI-Novel-Writing-Assistant** (`ExplosiveCoderflome/...`) | AGPL-3.0, v0.8.1 dated 2026-11-13 | [F] Style asset extracted from sample text / book teardown and bound to a novel; anti-AI report at sentence, paragraph and narrative level, "a risk of expression, not the probability of AI writing"; whole-book flow with a **book contract** and **rhythm board** before chapter lists; low-risk issues fixed or logged as **"quality debt"**, structural ones pause; V2 chapter loop plan → draft → check → local edit within budget → recheck → save → state sync, per-chapter cap 100k tokens [S]. | README + docs |
| AI-Novel-MultiAgent (`Windyhhh/...`) | MIT, 0 stars | [F] Critic scores each chapter, < 7.0 goes back to the editor; README inconsistent with the repo tree. Low reliability; not a donor. | README |

### Evaluation research

| Work | Finding that matters to us | Source |
|---|---|---|
| **LitBench** (EACL 2026; arXiv 2507.00769) | [F] On 2,480 human-preference story pairs, the best off-the-shelf **pairwise** judge (Claude 3.7 Sonnet) is right **73 %**; GPT-4.1 70 %, DeepSeek-V3 70 %, Gemma-3-12B 66 %, Qwen-2.5-7B 60 %. Trained reward models (Bradley-Terry on Llama-8B; generative RM) reach **78 %**. In a human study the RM-preferred story won 57 % vs 41 %, and the best LLM judge was at chance. Length bias had to be pruned (65 % of preferred stories were longer). | arXiv text |
| **LongStoryEval / NovelCritique** (arXiv 2512.12839) | [F] Reader-derived rubric of 8 aspects: **plot, characters, writing, world, theme, emotion, enjoyment, expectation** ("plot and characters are the most influential"; emotion, enjoyment and expectation "all play critical roles"). **Summary-based evaluation** (plot summary, character analysis, writing excerpts) is recommended for book length. An 8B critic fine-tuned on 176k reader reviews correlates with human ratings at Kendall 27.7 vs 15.2 for GPT-4o aggregation. | arXiv html |

### Audio (models we could run)

| Model | Fact | Fit for us |
|---|---|---|
| **ACE-Step 1.5** (MIT) | [F] music 10 s–10 min; "less than 4GB of VRAM"; 6–8 GB tier runs the 2B turbo DiT + 0.6B LM; < 10 s per song on an RTX 3090. Instrumental-only from a text prompt not stated explicitly (Simple Mode, Vocal2BGM exist) [U]. | [I] Local background music on the RTX 2070 is feasible (between ComfyUI and TTS jobs, the GPU being shared). |
| Chatterbox Multilingual (MIT) | [F] 23 languages, **no Vietnamese**; `exaggeration` control; watermark; "retired research" since 2026-08. | Not usable for Vietnamese. (A search snippet claiming Vietnamese support was wrong.) |
| Qwen3-TTS (Apache-2.0) | [F] 10 languages, **no Vietnamese**. | Not usable. |
| ThinkSound | [F] video→foley/ambience; **non-commercial** licence. | Not for a commercial product. |
| MOVA (Apache-2.0) | [F] joint video + synchronized audio incl. lip-sync; lowest stated VRAM 12 GB (8 s 360p). | Not on our 8 GB GPU; cloud only. |

[F] No open model with Vietnamese **and** explicit emotion control was found. VieNeu v4 is reported proprietary (search snippet of its README, not verified; v3 is what we run). The Vietnamese emotional TTS question (U2 of the synthesis) stays open and goes to the cloud A/B (Alibaba `qwen-audio-3.1-tts-*` free quota, Gemini TTS).

## 2. Where we stand against them, stage by stage

| Stage | We have [F] | Donors do better | Gap |
|---|---|---|---|
| Idea | ADR-0125 drawn profile + duplicate check vs 20 latest projects | One Sentence: Idea Bank + multi-agent debate | small |
| Book plan | ADR-0116 book plan, hook ledger (`book.py`, one new hook per chapter), chapter digests, bounded memory | novel-agent: **item registry** + **temporal (spoiler-safe) retrieval**; AI-Novel: **book contract + rhythm board** before chapters | medium: no item/prop ownership ledger in the story engine; memory is digests, not time-indexed facts |
| Chapter writing | ADR-0128 writer sees plan/voice/digests; repair with history; F1–F14 | InkOS **Settler**: typed state delta after every chapter, validated against authoritative state | [U] our canon commits per story; a per-chapter typed delta (who knows what, where items are, injuries, relationships) is not visible in the driver — needs a code read before deciding |
| Story review | L2 audits (continuity, character, memo, craft, safety, hooks, drift), L3 critic, gemma3:12b craft judge; findings recorded, commit accepts them | LitBench: absolute LLM scores are weak, **pairwise** is the reliable judge mode; LongStoryEval: **reader aspects (emotion, enjoyment, expectation)** and summary-based book evaluation | **[F] `pairwise_judge` exists in `server/story_authoring/audits.py:567` but nothing calls it.** No reader-enjoyment/expectation judgement; no book-level summary evaluation at commit |
| Adaptation | ADR-0114 (hook ≤ 6 s, cliffhanger, length ±20 %), deterministic | One Sentence: review rewrites by part — hook, ending, **twist density** | small–medium |
| Shot planning | `image_prompt.composition.shot_type`; no coverage rule | CineCrew staging layer (shot type, camera move, framing, lighting) + **required/forbidden props per clip**; ViMax coverage (establishing → medium → close, OTS/reverse/insert) | medium (already P1 in the synthesis) |
| Assets / identity | asset kinds `character`, `scene`, `prop`, `product`; continuity judge checks wardrobe from the character sheet | Jellyfish **costumes as entities**; FilmWorld **entity states with their own reference** (same character, other costume/injury) | **medium–high for drama**: one sheet per character cannot show a costume change; the judge then flags a correct change as drift |
| Storyboard checks | ADR-0134 judge (11 checks, cast check, one regeneration with `prompt_fix`, better version kept); best-of-N off (judge not qualified) | DramaAgent K = 3 + weighted sub-scores + τ + **repair the weakest dimension** + ε stop; FilmWorld rollback to best | small once a judge qualifies: our loop is the same shape; add per-dimension weights/threshold and K > 1 |
| Cross-shot state | previous storyboard of the scene as the previous frame | FilmWorld end-state → next opening state; CineCrew last→first frame chaining | small (still clips); matters with real video |
| Learning across runs | none | CineCrew **Production Rulebook** fed from critique logs | **new**: our runs record findings (story audits, continuity verdicts, QUALITY) but nothing feeds them forward |
| Audio | narration TTS (VieNeu v3), −14 LUFS master | One Sentence BGM library + audio-LLM scoring + speech-preserving compression; DramaAgent per-line emotion + ambience | **high**: no music bed (I3), no emotion control (I4) |
| Efficiency | serial generation | ViMax dependency graph → parallel branches | matters on cloud only |
| Cost (reference) | synthesis: $4–8 per 60 s all-API | AIDrama "$1–5 per 2 min" (unmeasured); One Sentence $25–27/min (measured, premium) | — |

## 3. Proposals, ranked by quality gain per effort

Each is research-first → ADR → implement → measure, as before.

**P0 — no cloud key needed**
1. **Background music bed with ducking.** ACE-Step 1.5 (MIT, fits the 6–8 GB tier) generates an instrumental bed per scene/episode from the scene's mood (the adaptation already has tone); mix under narration with speech-preserving sidechain compression, then the existing −14 LUFS master (ADR-0133). Measure on 3 finals by listening. [U] instrumental-only quality and the time-sharing with ComfyUI on one GPU. *Donors:* One Sentence (mix), FRAMEWORKERS (music/mix agents).
2. **Use the pairwise judge where we select.** Wire the existing `pairwise_judge` into the places where the engine chooses between versions (repair vs original chapter, variant openings, title candidates) instead of absolute scores; position-swap both orders (LitBench averages positions) and length-normalize. *Why:* LitBench shows absolute/pointwise judging is the weak mode; our engine already has the function. Cheap.
3. **Costume / state as an asset.** Add a `costume` (or character-state) asset kind with its own sheet; segments name the costume; the storyboard tool and continuity judge use the costume sheet when named. *Why:* drama needs costume changes; without it the judge flags correct changes and the image model drifts. *Donors:* Jellyfish, FilmWorld, CineCrew.
4. **Production rulebook (cross-run learning).** Aggregate recurring findings per project/workspace (continuity verdict categories, QUALITY findings, story audit codes) into short rules ("Linh always carries the red umbrella", "no garbled signage: avoid readable text on signs") injected into the storyboard and writer prompts; each rule cites its evidence and expires when not seen again. *Donor:* CineCrew.

**P1 — after a cloud judge qualifies (Mistral/Cerebras/Gemini)**
5. **Judge loop shape from DramaAgent:** per-dimension weights and an acceptance threshold measured on corpus 2; K = 2–3 candidates; repair only the weakest dimension; stop on ε; keep the best (we already keep the better version). Turns ADR-0112 best-of-N back on.
6. **Reader-aspect book evaluation at STORY_COMMIT:** summary-based (plot summary, character analysis, excerpts) with the LongStoryEval aspects, emotion / enjoyment / expectation included; recorded, not blocking, until thresholds are measured against human reading of a few books.
7. **Episode review for hook, ending and twist density** at ADAPTATION (One Sentence), as model review on top of the deterministic checks.
8. **Shot grammar + required/forbidden props per segment** (CineCrew staging layer, ViMax coverage); the continuity judge already checks props, so the plan should state them.

**P2 — story engine depth (needs a code read first)**
9. **Typed per-chapter state delta** (InkOS Settler) and **spoiler-safe temporal retrieval** (novel-agent): verify what our canon and digests already hold, then decide. Long books (30+ chapters) are where this pays.
10. **Book contract + rhythm board** (AI-Novel-Writing-Assistant) before chapter lists; compare with our book plan.
11. **Parallel generation by dependency** (ViMax) once routes are cloud.

**Not adopted:** 3D world/panorama per scene (One Sentence: heavy, premium cost); MOVA/joint AV on our GPU (≥ 12 GB); Chatterbox and Qwen3-TTS (no Vietnamese); ThinkSound (non-commercial); Windyhhh (unreliable).

## 4. Facts / inferences / unknowns

- **Facts:** the numbers and mechanisms quoted per donor above (sources linked); internal: asset kinds are `character, prop, product, scene` (`lib/asset_types.py`); `pairwise_judge` has no caller; no music/bgm/ducking code in `lib server r2`.
- **Inferences:** the ranking in §3; that ACE-Step fits our GPU schedule; that costume assets remove a class of false continuity drift.
- **Unknowns:** ACE-Step instrumental quality for Vietnamese drama moods; whether our canon already tracks item ownership per chapter (P2 #9); Vietnamese emotional TTS quality of the cloud options; DramaAgent's judge model (not stated); FilmWorld results beyond the summarized part.

## Sources

- arXiv: [2610.00097](https://arxiv.org/abs/2610.00097) DramaAgent · [2609.07720](https://arxiv.org/abs/2609.07720) CineCrew · [2607.19038](https://arxiv.org/abs/2607.19038) FilmWorld · [2606.07649](https://arxiv.org/abs/2606.07649) ViMax · [2605.22144](https://arxiv.org/abs/2605.22144) One Sentence, One Drama · [2608.29814](https://arxiv.org/abs/2608.29814) FRAMEWORKERS · [2507.00769](https://arxiv.org/abs/2507.00769) LitBench ([EACL 2026](https://aclanthology.org/2026.eacl-long.362/)) · [2512.12839](https://arxiv.org/abs/2512.12839) LongStoryEval
- GitHub: [Narcooo/inkos](https://github.com/Narcooo/inkos) · [lipfei06/novel-agent](https://github.com/lipfei06/novel-agent) · [ExplosiveCoderflome/AI-Novel-Writing-Assistant](https://github.com/ExplosiveCoderflome/AI-Novel-Writing-Assistant) · [Windyhhh/AI-Novel-MultiAgent](https://github.com/Windyhhh/AI-Novel-MultiAgent) · [Forget-C/Jellyfish](https://github.com/Forget-C/Jellyfish) · [EvoLinkAI/ai-short-drama](https://github.com/EvoLinkAI/ai-short-drama) · [AIGeeksGroup/DramaAgent](https://github.com/AIGeeksGroup/DramaAgent) · [HKUDS/ViMax](https://github.com/HKUDS/ViMax) · [ace-step/ACE-Step-1.5](https://github.com/ace-step/ACE-Step-1.5) · [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) · [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) · [OpenMOSS/MOVA](https://github.com/OpenMOSS/MOVA) · [FunAudioLLM/ThinkSound](https://github.com/FunAudioLLM/ThinkSound)
- Lists used to find donors: [awesome-ai-short-drama](https://github.com/charliewwdev/awesome-ai-short-drama) · [awesome-ai-micro-drama](https://github.com/ken-fs/awesome-ai-micro-drama)
