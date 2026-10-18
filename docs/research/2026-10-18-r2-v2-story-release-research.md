# R2 V2 release: V1 plus idea-to-story authoring — step 1 research

Date: 2026-10-18. Scope: choose the V2 release base, inventory the story parts that already exist, re-read the project's story-length and Human-gate decisions, and qualify the local Ollama models. Read-only; no product code changed.

## Sponsor intent (2026-10-18)

- V2 = all of V1 plus a working idea → complete, commercial-grade story flow.
- Integrate the existing story parts (M5, M6, the host script pipeline); no redesign; do not break existing code. Minimal glue code under the approved spec is authorized.
- Output: a standalone manuscript **and** a hand-off into the existing video flow.
- Story type/length: follow the project's existing decisions.
- Model: local Ollama first, cloud models later. Commercial quality is required; defects caused only by local-model limits are accepted.
- End point: real operation.
- **Automation: as little human involvement as possible.**

## Facts

### Release base

| Ref | Commit | Notes |
|---|---|---|
| `r2-v1.0.0` (annotated V1 tag) | `0fba84e8` | 2026-09-28 |
| `r2-v1/maintenance` | `6ab361a7` | 2026-09-29; ancestor of `r2-v2/main` |
| `r2-v2/main` (local) | `23cf146a` | M7 + M8 accepted; 585 commits after V1; not pushed (origin `6d4f7369`) |
| `design/r2-story-authoring` | `50184f9f` | `r2-v2/main` + M9 design docs/verifier scripts + story spec/plan/qualification; **no product-code diff** in `lib server r2 frontend alembic` vs `r2-v2/main` |
| `impl/r2-m9a…`, `impl/r2-m9b…` | `04b1b921`, `bba1bd96` | not merged; M9-B not accepted; opportunity research, unrelated to story writing |

`git merge-base --is-ancestor` confirms both the V1 tag and every V1 maintenance fix are in `r2-v2/main`.

### Story parts already built (all present since V1)

- `r2/narrative` (M5A Canon: append-only deltas, `CanonTransactionService`), `r2/narrative_plan` (`NarrativePlanService.commit_revision` requires an exact Human `NarrativePlanApproval`), `r2/narrative_context` (`NarrativeContextCompiler`), `r2/narrative_lifecycle` (M5C draft candidates, revisions, acceptance, `continuity_rules`, `coverage`, change-set parsing), `server/services/narrative_canon_handoff.py` (accepted narrative → Canon commit).
- `r2/adaptation` (M6 dual-profile adaptation: Western drama and Chinese short-drama 爽文 profiles, evaluation reports, screenplay admission).
- Host gates: `server/routers/gates.py` exposes greenlight (A), narrative-lock (B, M6 screenplay admission), script-lock, final-cut (C) and publish-approval (D).
- Host script pipeline: novel source text → `lib/episode_planner.py` → script/storyboard/video via the embedded agent and generation tasks.
- Local text model path: a custom provider with the `openai_chat` endpoint (`lib/custom_provider/endpoints.py::_build_openai_chat`) pointing at `http://localhost:11434/v1`; the custom-provider model already allows null prices for local providers (`tests/unit/lib/db/models/test_custom_provider_models.py`).

### What does not exist (glue)

No server route or service composes the M5 services into a writing flow. Nothing generates prose from an idea, and nothing feeds an accepted manuscript into the video source. The approved plan (`docs/superpowers/plans/2026-10-17-r2-idea-to-story-authoring.md`) owns exactly this glue. Its Task0 stopped at `TEXT_EXECUTION_CUSTODY_GAP` (`docs/r2/evidence/R2_STORY_AUTHORING_QUALIFICATION.md`): it needs a text-task checkpoint in `task_repo.py` and token ceilings in `ledger.py`/`budget_guard.py`, which are outside the plan's owner map.

### Existing decisions on story length and type

- The approved spec and plan fix the first acceptance corpus at **one Vietnamese short story, three chapters, visible ending**. Limits are explicit runtime inputs.
- ADR-0089 §8 lists "commercial long-form narrative authority" as V2 work that needs its own accepted packet. Long-form serials are therefore not part of this release.
- The V1 narrative video product is a 60–120 s drama scene (strategy §2).

### Human-authority decisions (cannot be automated away)

- R2-DEC-001: the Human Showrunner remains the final creative/governance authority; automation may prepare, never approve.
- ADR-0089 §3 and CONTEXT.md: Gates A–D are mandatory Human decisions bound to exact revisions; "Agent self-approval", "confidence threshold" and "automatic QA score" are explicitly not approvals.
- `NarrativePlanService` requires an exact Human plan approval. `NarrativeAcceptanceService` requires a real Showrunner authority adapter and has no permissive default.

### Local model qualification (2026-10-18, RTX 2070 8 GB, Ollama `/api/chat`, `think:false`, temperature 0.8)

Prompt: open chapter 1 (~350 words) of a Vietnamese family-drama short story.

| Model | Time | Output tokens | Speed | Finish | Observations |
|---|---|---|---|---|---|
| `ornith:9b` (qwen35 family, Q4_K_M, ctx 262k) | 22.0 s | 478 | 44 tok/s | stop | Fluent, idiomatic Vietnamese with dialogue and imagery. One kinship/pronoun slip and one fact slip ("bà cụ" for the father). |
| `qwen3.5-vimax:9b` | 26.8 s | 372 | 44 tok/s | stop | Leaks Chinese words into the Vietnamese prose (`扑面而来`, `像个`); no dialogue. |

## Inferences

1. **Base: `r2-v2/main` (`23cf146a`), via `design/r2-story-authoring`.** It is the accepted V2 line, it contains the full V1 and its fixes, and the story branch adds no product code. M9 is excluded: it is unaccepted and unrelated to story writing.
2. **Model: `ornith:9b`** through the existing custom-provider `openai_chat` path. `qwen3.5-vimax:9b` fails a hard criterion (mixed-script output).
3. **Expected local-model defects:** continuity slips such as pronouns, kinship and facts. The existing M5C continuity rules plus one bounded automatic repair pass are the reuse answer. Residual slips count as accepted local-model limits.
4. **Minimal Human touchpoints consistent with the decisions above:**
   - Text product: **(1)** submit idea + Greenlight (Gate A) in one action, binding the exact idea text; **(2)** approve the outline (`NarrativePlanApproval`); **(3)** accept the finished manuscript (narrative acceptance decisions recorded in one action, each bound to an exact revision).
   - Everything between (2) and (3) runs automatically: chapter generation, continuity and coverage checks, bounded repair, literary self-review as advice.
   - Video continuation: hand the accepted manuscript to the existing host pipeline as novel source text. The existing Gates B, C and D remain one action each.
5. **Hand-off to video** reuses the host's novel-source pipeline; no new adaptation code is needed for the first release.

## Unknowns

- Whether `NarrativeAcceptanceService` accepts several revision decisions from one authenticated Human action. To be qualified in Task3; otherwise the UI sends one decision per chapter from a single click.
- Whether the existing `openai_chat` custom backend surfaces `finish_reason` and token usage from Ollama. Task1.
- Literary quality across a full three-chapter run. Measured only by the live demonstration and the sponsor's read.
- Which deployment counts as "real operation": the V2 staging environment (`~/arcreel-v2-staging`) is the candidate. To be confirmed in the plan.

## Addendum — donor decisions re-check (2026-10-18, sponsor request)

The sponsor changed the story touchpoints to two: (1) enter and approve the idea, which is planned to be automated later; (2) receive and approve the final manuscript. Revision requests remain possible on any part at any step. The sponsor also asked for a re-check of every existing research note and donor decision, including documents on other branches, under the rule "take only the best from donors, at least equal to the original".

### Sources found (several are outside the V2 lineage)

| Source | Location | Content |
|---|---|---|
| R1.5 `R1_05_NARRATIVE_STACK_REALITY_CHECK.md` (1546 lines) and `R1_05_DECISION_SNAPSHOT.json` | `~/Bản tải về/conten os/content_production_os_r1_evidence_2026-09-06 (3)/` and the R1.1–R1.7 bundle zip; not in any branch | Donor roles for the whole Idea→Story→Canon→Draft→Review→Commit stack; decisions R2-D46…D55; benchmark plan A–E |
| `docs/research/2026-09-09-r2-donor-reuse-maximization.md` | only on branch `design/r2-m5b-narrative-context` | Donor file survey; sponsor rule of 2026-09-09: port donor modules to Python with quality "equal to or better than the original", proven by donor tests or a self-built corpus plus an exact-source Node harness |
| `docs/research/2026-09-08-r2-m5b-reuse-and-boundary-research.md`, `2026-09-08-r2-m5c-narrative-production-lifecycle-research.md`, `2026-09-08-r2-m5c-adr-decision-validation.md` | only on `design/r2-m5b-narrative-context` | Donor reuse boundaries for context, extraction, lifecycle. §144 of the M5B note: the writer gets a separately labelled author channel plus explicit forbidden-knowledge constraints; character simulation gets character-visible content only |
| `docs/research/2026-09-16-r2-m10-quality-evidence-packaging.md` and the M10 spec/plans | only on `design/r2-m5b-narrative-context`; not implemented | Multi-assessor quality evidence; a model cannot satisfy a required Human rubric; locale/cohort-specific rubrics |
| Frozen `R2_01` §20, `R2_02` §5.1 and §7, `R2_04` R2-DEC-004/005/007/008/031 | V2 lineage | Frozen donor roles and Candidate Writer permissions |

### What is already decided (facts)

- **R2_01 §20 (frozen):**
  - Novel Studio = narrative workbench: hierarchical planning UX, context-pack patterns, and the draft → continuity → revise → accept workflow.
  - Shenbi = narrative skill and quality library: genesis, architecture, planning, **writing skills**, **audits**, import, drift/snapshot/revision patterns.
  - Huohuo = causal change record and novel → screen adaptation.
- **R1.5:**
  - **§17 Who writes:** a `CandidateWriter` interface whose candidates are "Novel Studio-derived chapter/scene drafting flow, Shenbi `chapter-drafting` skill, general LLM/model profile". The writer has zero Canon write authority.
  - **§18 Who reviews:**
    - L1 R2 deterministic validators;
    - L2 specialists (Novel Studio `hardRules`, Huohuo causal audit, Shenbi specialist audits);
    - L3 independent critics (Shenbi motivation, dialogue, pacing, POV, reader pull, resonance, texture, arc payoff), where the evaluator must be independent of the writer;
    - L4 Human.
  - **§19:** Shenbi G0–G7 is reused as the NG0–NG7 process concept. The numeric "94" threshold is a diagnostic, not truth.
  - **§29:** take Huohuo's "strict local repair loop" and "bounded continuity context heuristics".
  - **§14 / R2-D53:** the scene is the execution and review unit; chapter acceptance groups approved scenes.
- **2026-09-09 sponsor rule:** every donor module is ported to Python; quality ≥ original; parity proven against the exact pinned donor source.
- **R2-DEC-031 / ADR-0079:** a `DonorParityContract` per selected surface; every material row must be `PARITY` or `IMPROVED`.

### Gap (fact)

- The writer, planning and review surfaces assigned above were **never implemented or parity-tested**. M5C/M6 ported only parsing/QA pieces: the Huohuo change-record parser, Novel Studio `hardRules`, the Huohuo drama fields and the Take shot vocabulary.
- The 2026-10-17 spec/plan did not cite R1.5 or R2_01 §20 for the writer. It planned self-written prompts ("no donor writer parity is inferred"), which contradicts the frozen donor roles and the ≥-donor rule.
- R1.5 benchmarks A–E were never run: R1.7 could not clone upstream repositories. Same-fixture behavioural evidence for the writer donors therefore does not exist yet.

### Consequence for this release (inference)

The CandidateWriter, planning and review layers must be built from the frozen donor roles:

- Shenbi supplies the planning/drafting skills and audits.
- Novel Studio supplies the workflow shape.
- Huohuo supplies the strict local repair loop and continuity heuristics.

Each selected surface is ported to Python under a `DonorParityContract`:

- **Deterministic surfaces** get exact-source fixture parity.
- **Model-calling surfaces** get a same-idea, same-model (`ornith:9b`) quality differential against the donor's own pipeline, scored on one rubric and read by the sponsor.

Next research step: a per-surface inventory of Shenbi, Novel Studio and Huohuo at their pins, then the minimal donor runs needed for that differential.

## Addendum — per-surface writer donor inventory (2026-10-18)

Sources: Shenbi `65ddfc26` and Novel Studio `9b690ae2`, both fetched at their pins into the session scratchpad; Huohuo `f104b853` from the local checkout `~/content-os-r1-8/work/huohuo-drama`. Read-only so far.

### Shenbi (Python, 74 skills)

- **Long-form automated pipeline** (`src/shenbi/pipeline/genesis.py`, `chapter_loop.py`, 3442 lines):
  - 16 genesis steps: worldbuilding → genre-config → character-design → story-architecture → factions → volume-outlining → pacing-design → thread-weaver → foreshadowing-plant → power-system → locations → relationships → book-spine → intent → style-learning → anchor.
  - 15 chapter steps, in order:
    1. volume-align (deterministic)
    2. chapter-planning (an 8-section memo)
    3. context-prepare (deterministic)
    4. chapter-drafting
    5. post-draft-extract (deterministic)
    6. linguistic-drift-check (deterministic)
    7. foreshadowing-lifecycle
    8. state-settling
    9. audit group: factual (continuity, world rules, pacing)
    10. audit group: character (consistency, dialogue, motivation, POV)
    11. audit group: craft (texture, reader-pull, anti-AI)
    12. audit group: plan (memo compliance, foreshadowing)
    13. review-resonance
    14. review-sensitivity
    15. chapter-revision (conditional)
- **Short-story track** (skills only, agent-orchestrated, not in the pipeline code):
  - `shenbi-short-outline`: fewer than 30 chapters → `outline/short_story_map.md`.
  - `shenbi-short-drafting`: generates chapters strictly in order, runs a per-chapter audit chain (memo-compliance, anti-ai, character, motivation), revises at most 3 rounds and otherwise falls back to the best version, then re-checks the adjacent 2 chapters.
  - `shenbi-short-packaging`: publication and sales materials.
- Other: `style-polishing`, `length-normalizing`, `anti-detect`, `review-highpoint`, `review-long-span`. Scoring/gates G0–G7 (`src/shenbi/gates`); `llm_output_integrity.py`.
- LLM routing is any OpenAI-compatible endpoint (`SHENBI_LLM_BASE_URL`/`MODEL`/`API_KEY`), so Ollama can serve it.
- Prompts/skills are written in Chinese; genre fatigue-word lists are Chinese.

### Novel Studio (TypeScript, AI layer ≈ 2,000 lines)

- Flow (`src/lib/ai/prompts.ts`, 207 lines; `schemas.ts` zod):
  1. `projectIdeaPrompt` (brief → seed, `ProjectIdeaSchema`)
  2. story bible
  3. style bible
  4. volume outline
  5. arc pack (5 chapters)
  6. chapter outline
  7. scene beats
  8. `chapterDraftPrompt` (Context Pack only, no chat memory)
  9. `continuityPrompt` merged with `hardRules`
  10. `styleRevisionPrompt`
  11. `memoryExtractorPrompt`
- Model client: OpenAI SDK, OpenAI-compatible. Chinese prompts.

### Huohuo (TypeScript, 54 novel services)

- **Writer pipeline** (`novel-chapter-pipeline.ts`):
  1. generate
  2. continuity check
  3. bounded rewrite/patch loop
  4. outline-compliance gate
  5. craft hook
  6. AI-humanize hook
  7. seam fix
  8. memory/causal update
  9. replacement-char repair
  10. intra-chapter dedupe

  It is coupled to Prisma/DB/billing. Commercial modules: `novel-commercial-appeal-audit.ts` (802 lines, LLM), `novel-prose-polish.ts`.
- **Deterministic modules** (no I/O, but Chinese-specific punctuation, lexicon and regex):

  | Module | Lines | CJK characters in source | Han regexes |
  |---|---|---|---|
  | `novel-continuity-deterministic-fix` | 121 | 272 | 2 |
  | `novel-intra-chapter-dedupe` | 412 | 402 | 7 |
  | `novel-chapter-seam` | 1669 | 6658 | 44 |
  | `novel-continuity-precheck` | 731 | 1645 | 8 |
  | `novel-chapter-beat-budget` | 233 | 701 | 6 |
  | `novel-stakes-common-sense` | 186 | 861 | 14 |

  Only the normalized-fingerprint core of the dedupe/seam logic is plausibly language-agnostic.

### Frozen role → candidate surfaces for a Vietnamese short story

| Stage | Candidates (pin) | Question the differential must answer |
|---|---|---|
| Idea → seed | Novel Studio `projectIdeaPrompt` | Is the seed specific and commercially hooked? |
| Bible / style | Novel Studio story+style bible; Shenbi genesis subset (worldbuilding, character-design, story-architecture, style) | Is the compact Novel Studio form enough for 3 chapters? |
| Outline | Shenbi `short-outline`; Novel Studio chapter outline + scene beats | Beat coverage, ending, hook per chapter |
| Draft | Shenbi `chapter-drafting`/`short-drafting`; Novel Studio `chapterDraftPrompt` | Prose quality, plan compliance, length |
| Audit (L2/L3) | Shenbi audit groups + resonance; short chain memo-compliance/anti-ai/character/motivation | Finding precision on the same chapter |
| Repair | Shenbi `chapter-revision` (≤3 rounds, best-version fallback); Huohuo strict local repair loop | Fixes findings without collateral damage |
| Polish / anti-AI | Shenbi `style-polishing`, `anti-detect`; Novel Studio style revision; Huohuo humanize | Natural Vietnamese, no AI tells |
| Packaging | Shenbi `short-packaging` | Title, blurb, commercial readiness |
| Deterministic checks | Shenbi `linguistic-drift-check`, `llm_output_integrity`; Huohuo dedupe/seam core; R2 L1 + ported `hardRules` | Exact parity on fixtures; Vietnamese adaptation is an intentional deviation |

### Language finding (fact + inference)

Every donor prompt and heuristic is Chinese. `ornith:9b` is a Qwen-family model, and the 2026-10-18 probe already showed CJK leakage from the other Qwen model. The differential must therefore measure two variants of each model-calling surface on the same idea:

- (a) the donor prompt verbatim plus a Vietnamese-output instruction;
- (b) a faithful Vietnamese translation of the prompt.

Translation is an intentional deviation that has to be recorded in the `DonorParityContract`.

### Language probe result (2026-10-18, n = 3 per case)

Setup: `ornith:9b` via Ollama `/v1/chat/completions`, temperature 0.8, seeds 100–102, `max_tokens` 1500. Prompts: Novel Studio `projectIdeaPrompt`/`chapterDraftPrompt` shapes, (a) Chinese verbatim plus "write in Vietnamese" and (b) Vietnamese translation; same idea and same hand-made context pack. All 12 calls finished with `stop`.

| Case | Valid JSON | Samples with CJK leakage | Leaked characters |
|---|---|---|---|
| zh idea | 1/3 (2 broken brackets) | 1/3 | 藏着 |
| vi idea | 3/3 | 0/3 | — |
| zh draft | n/a | 1/3 | 台阶 |
| vi draft | n/a | 2/3 | 留下一, 令他 |

Conclusions:

- **Fact:** CJK leakage is a property of this model with both prompt languages.
- **Inference:** a deterministic leak detector with local repair is mandatory regardless of which prompt is used.
- **Fact:** the Vietnamese prompt is more reliable for structured JSON. Use translated prompts for structured stages.
- **Open:** prose quality is not separable at n = 3. Both variants show 9B-typical continuity slips (e.g. "ten years since the father died" against "the father has just died"; a token glitch "bàSix"). This confirms the need for the L1/L2 audit and repair layers.
- **Open:** a full-pipeline differential is still required.

Raw output is retained at `<scratchpad>/probes/langprobe.json` (session-local, not evidence for acceptance).

### Shenbi pinned pipeline run (2026-10-18)

Setup: Shenbi `65ddfc26` verbatim, `uv run pipeline next` loop with automatic checkpoint approval, `ornith-32k:9b` via Ollama `/v1`, seed with Vietnamese content (`bench/shenbi-seed.md`). Stopped manually after 27 iterations (about 2 hours).

| Measure | Result |
|---|---|
| Model dispatches | 52 |
| Outputs quarantined by the output-integrity gate | 51 |
| Outputs written | 1 (worldbuilding, iteration ~20) |
| Furthest step | genesis step 1 of 16 (`shenbi-worldbuilding`), looping worldbuilding ×3 → escalation review → approve |
| Language of written world files | Chinese (`language: zh` hard-coded; Chinese skills) |

Conclusions:

- **Fact:** the verbatim Shenbi pipeline cannot run end to end on a local 9B model. The dominant failure is format, not content: the model returns the requested files inside a fenced JSON object, and Shenbi's literal-path parser rejects it ("declared literal paths not in parsed output"). The escalation-review skill fails the same way.
- **Fact:** Shenbi's output-integrity gate behaved correctly. It never let a malformed output through, so its *gate* is worth porting.
- **Inference:** Shenbi's role stays as frozen in `R2_01` §20 — skills (planning/drafting prompts, audit dimensions) and audits — not its runner. The R2 host must own the output contract: one structured JSON response per call, validated by schema, with a bounded local repair.
- **Parity consequence:** Shenbi end-to-end output cannot serve as the quality baseline on this model. Model-calling Shenbi surfaces are compared per surface (same prompt content, same model, same input) instead.

## Plan amendments required (step 2)

1. Approve the Task0 owner-map amendment (`task_repo.py`, `ledger.py`, `budget_guard.py` and their tests) recorded in `R2_STORY_AUTHORING_QUALIFICATION.md`.
2. Make Ollama the first qualified provider; Claude and OpenAI remain fixture-only until configured.
3. Replace per-chapter Human steps with the three-touchpoint automation above, plus finite automatic repair.
4. Add the manuscript → project novel-source hand-off.
5. Add production activation steps after acceptance.
