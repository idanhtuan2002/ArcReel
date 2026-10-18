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

## Addendum — consolidated donor rationale (2026-10-18, sponsor request)

Sources: R1.5 §1–§5, §17–§19, §26–§29; `R2_01` §20; `2026-09-09-r2-donor-reuse-maximization.md` §1–§3 (branch `design/r2-m5b-narrative-context`); ADR-0079; `R2_M5C_DONOR_BASELINE.json`, `R2_M6_DONOR_BASELINE.json`.

### Why mix donors (fact, R1.5 §1)

No single repository can be the narrative system. Each donor is strong in one layer and unsafe as an authority: Novel Studio and Huohuo keep story truth in their own SQLite/Prisma memory; Shenbi's `state-settling` writes truth files during drafting, before its audits run (R1.5 §2), which breaks "Candidate ≠ Canon". R2 therefore owns the authority (Canon, Plan, Context compiler, Lifecycle) and takes from each donor only the layer where it is best.

### What each donor contributes and why

| Donor (pin) | Why it was chosen | Taken | Not taken |
|---|---|---|---|
| Novel Studio `9b690ae2` | Cleanest acceptance boundary: plan → context pack → draft → continuity → style revision → accept → extract; "drafts never update canon" matches R2 (R1.5 §3) | Workflow shape and hierarchy (bible → outline → chapter → scene beats), context-pack patterns, `hardRules` (already ported in M5C), drafting/continuity/revision prompt shapes | SQLite memory as truth, its project state, acceptance-as-mutation |
| Shenbi `65ddfc26` | Broadest craft library: 70+ skills, 18 specialist audits, G0–G7 gate philosophy, independent-evaluator rule (R1.5 §2, §4.4 "highest-value reusable section") | Planning/drafting skill content, specialist audits as L2/L3, NG0–NG7 process concept, output-integrity gate, short-story track (outline, drafting with ≤3 revisions and best-version fallback, packaging) | Truth files, state-settling order, pipeline runner and state, numeric 94 threshold |
| Huohuo `f104b853` | Unique causal change record and causal audit; strict local repair loop; novel → screen adaptation (R1.5 §5, §29) | Change record parser (already ported in M5C), drama fields (M6), strict local repair loop, bounded-context heuristics | Four-layer memory authority, DB runtime, Director/media stack |

### How a taken surface is integrated (facts: 2026-09-09 sponsor rule, ADR-0079, M5C/M6 precedent)

1. Pin the exact donor commit; vendor the unmodified source file under the parity fixtures.
2. Re-implement it in Python inside the R2 owner module (the host is Python; TypeScript cannot run in-process). Donor I/O and authority (DB, memory, truth files) are replaced by R2 ports.
3. Prove parity:
   - deterministic surface: a Node runner executes the donor file and the Python port on the same fixtures; outputs must be equal;
   - model-calling surface (prompt/skill): same idea, same model, scored differential against the donor's own flow.
4. Record every intentional deviation (here: Vietnamese prompt translation; R2-owned JSON output contract; object-rooted schemas).
5. Write a `DonorParityContract` JSON bound to the integrated HEAD; every material row `PARITY` or `IMPROVED`; independent review.

### Already integrated (facts)

- M5B: Novel Studio context-pack concept → `r2/narrative_context/compiler.py`.
- M5C: Huohuo `novel-change-record.ts` → `r2/narrative_lifecycle/changeset_parser.py`; Novel Studio `hardRules.ts` → `r2/narrative_lifecycle/continuity_rules.py`.
- M6: take shot vocabulary → `r2/contracts/production.py`; Huohuo drama fields → `r2/adaptation/shuangwen_profile.py`.
- Not yet integrated: every writer, planner, specialist-audit and repair surface (the gap this release closes).

### Lessons from the 2026-10-18 runs that change the "how"

- Neither donor runner completes on a local 9B model: Shenbi 51/52 outputs quarantined; Novel Studio fails on schema shape (nested values where strings are expected; a root array requested under `response_format: json_object`, a donor defect on any provider). Runners are therefore not taken; prompt content is.
- The R2 output contract (one object-rooted JSON per call, validation-error feedback repair, bounded coercion) is recorded as `IMPROVED` against both donors, with a regression fixture for the root-array defect.

## Addendum — small-model failure research and step standardization (2026-10-18, sponsor request)

### Primary sources checked

- Ollama `docs/api/openai-compatibility.mdx`: `/v1` accepts `response_format`, `reasoning_effort` (`"none"` disables thinking), `seed`, `stop`, `max_tokens`; context size cannot be set through `/v1`, only through a Modelfile `num_ctx`.
- Ollama `docs/capabilities/structured-outputs.mdx`: a JSON schema in `format` (`/api/chat`) or `response_format` (`/v1`); also put the schema in the prompt.
- Ollama source (`llm/llama_server.go`, `openai/openai.go`, main branch): the schema is converted to a GBNF grammar (constrained decoding), applied after thinking when thinking is on; `presence_penalty` is passed to the sampler.
- Ollama issue #14645 ("format is ignored when think is disabled for qwen3.5", closed 2026-07-07): re-verified on the installed 0.32.6 below.
- Qwen3.5-9B model card: thinking is on by default; non-thinking general preset temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5; presence_penalty reduces endless repetition but "may occasionally result in language mixing".
- Installed: Ollama 0.32.6; `ornith-32k:9b` capabilities `completion, tools, thinking`; Modelfile defaults temperature 0.6, top_k 20, top_p 0.95.

### Probe (2026-10-18, `ornith-32k:9b`, `<scratchpad>/probes/smallmodel_probe.py`)

Structured output, two schemas (style bible: string fields; scene beats: object-rooted array of objects with integer/number fields), schema also in the system prompt, n = 4 per cell:

| Mode | Schema-valid | Mean latency | Thinking chars |
|---|---|---|---|
| `/v1` `json_object`, thinking default (donor mode) | 8/8 | 18.4 s | 680–1,610 |
| `/v1` `json_schema` strict, `reasoning_effort: none` | 8/8 | 8.5 s | 0 |
| `/api/chat` `format` schema, `think: false` | 8/8 | 10.3 s | 0 |
| `/api/chat` `format` schema, `think: true` | 8/8 | 19.3 s | 610–1,460 |

Facts:

- Constrained decoding works on 0.32.6 with thinking on and off (issue #14645 does not reproduce).
- Thinking is on by default through `/v1`; every donor call therefore paid about 2× latency for hidden reasoning.
- With a short prompt that contains the exact schema, even `json_object` stayed valid. The donor failures come from long prompts whose wanted shape is described loosely; the grammar removes that class entirely.
- CJK leaked into JSON values in 2 of 32 outputs.

Prose (one scene, "about 700 words", `think: false`, n = 3 per preset): every sample stopped normally and was under length (329–683 syllables; Vietnamese `\w+` counts syllables). One CJK leak (`生根`, presence_penalty 1.5 preset). One sample shows several Vietnamese-specific defects at once: kinship/pronoun errors (Minh, the older brother, calls himself "em" to his younger sister and is called "người chị"; Lan says "cha nó" of her own father), age drift (32 → "bốn mươi tuổi"), odd collocations ("tiếng chim hót leng keng"), purple metaphors and tears in nearly every paragraph. n = 3 cannot rank the presets; that is measured again in Task4 with n ≥ 10.

### Failure taxonomy for small local models

O = observed in the 2026-10-18 runs; P = predicted (literature, donor design notes, model card). Each row gets the same four answers: detect, prevent, repair, stop.

| ID | Failure | O/P | Detect | Prevent | Repair / stop |
|---|---|---|---|---|---|
| F01 | Silent input truncation | O | reported `prompt_tokens` < local count | `num_ctx` 32k tag; input budget per call | refuse `INPUT_TRUNCATED`; never stored |
| F02 | Output cut at limit | P | `finish_reason=length` | `num_predict` sized to step | JSON: refuse and retry once; prose: one continuation call |
| F03 | Hidden thinking eats time/tokens | O | reasoning length | `think:false` by default; thinking only where a differential shows gain | — |
| F04 | Endpoint down, model unloaded, VRAM OOM | P | preflight `/api/ps`, transport errors | `keep_alive`; one model resident | visible "model unavailable", resumable |
| F05 | Non-determinism across runs | O | — | record seed, model digest, options | evidence stores exact bytes; never re-derived |
| F10 | Wrong types, missing fields, wrapped arrays, extra prose | O (5 kinds) | schema validation | grammar-constrained schema, object-rooted schemas, schema text in prompt | one repair call with validation errors; logged bounded coercion; then stop |
| F11 | Schema field descriptions ignored | P | — | field meaning written in the prompt | — |
| F12 | Valid but empty/generic JSON (placeholders, copied example) | P | min lengths, placeholder and copy detection | concrete instructions, no literal example values | repair once |
| F13 | Enum/label drift; values in the wrong language | O (Shenbi Chinese values) | enum in schema; language check on values | Vietnamese prompts | local repair |
| F20 | CJK leakage | O | Han/CJK regex on every output | Vietnamese prompts | sentence-local repair; accepted manuscript must have 0 |
| F21 | Token glitches, merged Latin (`bàSix`) | O | merged-case and non-Vietnamese token regex | — | sentence-local repair |
| F22 | Kinship/pronoun (xưng hô) errors | O | xưng hô matrix check on attributed dialogue; L2 audit | story bible holds a xưng hô matrix (who calls whom what, self-reference), injected into every scene context | span repair |
| F23 | Calques, odd collocations, purple prose | O | L2 Vietnamese style audit | style bible with Vietnamese examples and banned patterns | style revision; residue recorded as local-model limit |
| F24 | Diacritic/spelling errors | P | Vietnamese syllable-validity check | — | span repair |
| F25 | English code-mixing ("cú call", "cánh gate") | O | non-Vietnamese syllable check + allow-list for loanwords | style bible rule | span repair |
| F30 | Attribute drift (age, job, relation) | O | extract numbers/attributes vs canon | canon facts in context pack | span repair |
| F31 | Timeline contradiction | O (language probe) | `story_time` vs stated times; L2 continuity | `story_time` in context | span repair |
| F32 | Physical/causal impossibility | O | L2 continuity audit | scene contract lists setting state | span repair |
| F33 | Unplanned names/characters, name drift | P | names not in canon/plan whitelist | entity list in context | span repair |
| F34 | POV drift | P | L2 POV audit | POV in scene contract | scene repair |
| F35 | Epistemic leak (secret known too early) | P (central to this plot) | R2 epistemic view + L2 audit | forbidden-knowledge constraints in the writer channel (M5B §144) | scene repair |
| F40 | Beat skipped, reveal too early, ending missing | P | L1 coverage of required turn; L2 memo compliance | scene contract with required turn and forbidden events | scene repair |
| F41 | Length undershoot | O (all 9 samples) | length window per scene | scene-sized calls (≈ 600–900 syllables) | targeted expansion (Shenbi length-normalizing), not a blind "write longer" |
| F42 | Premature summary/closure at scene end | P | closing-pattern detector | contract "end on the turn" | tail repair |
| F43 | Meta text, headings, notes | P | pattern detector | "content only" instruction | deterministic strip, else repair |
| F50 | Repetition loops | O (low) / P | repeated n-gram and dedupe core (Huohuo) | presence_penalty (trade-off with F20) | span repair |
| F51 | Clichés, AI tells, melodrama | O | Shenbi anti-AI audit adapted to Vietnamese with a Vietnamese fatigue list | style bible | style revision |
| F52 | Telling instead of showing | O | L2 craft audit | drafting skill instructions | revision |
| F60 | Lenient self-review | P | — | blocking decisions come from L1 and evidence-bearing findings only; L3 uses a separate critic prompt (same local model recorded as a local-model limit) | — |
| F61 | Hallucinated findings | P | every finding must quote an exact span; quote is verified deterministically | — | unverifiable finding dropped |
| F62 | Repair damages other parts, oscillates | P | rerun all L1 after each repair; diff outside span | span-local repair (Huohuo); best-version fallback (Shenbi) | max rounds, keep best, record |
| F70 | Cross-chapter inconsistency | P | R2 `continuity_rules`, canon delta | R2 context compiler with prior accepted content | scene repair |
| F71 | Chapter seam repeats previous ending | P | seam check (Huohuo normalized-fingerprint core) | — | opening repair |

### Standard step contract (every model-calling step)

Every step uses one shape so that each failure above is handled once, in one place:

1. **Spec:** step id and version, donor prompt reference and translation version, decoding preset, output kind (structured schema or bounded prose), validator list, audit list, repair policy, budget.
2. **Preflight:** endpoint and model digest, resident model, local token count ≤ input budget.
3. **Call:** structured → grammar-constrained schema with the schema text in the prompt, `think:false` unless the spec says otherwise; prose → scene-sized, fixed preset, seed recorded.
4. **Transport checks:** F01, F02, F04.
5. **L1 deterministic checks:** schema, language (F20, F21, F24), length (F41), meta (F43), repetition (F50), names (F33), attributes/time (F30, F31), xưng hô (F22), coverage (F40).
6. **L2/L3 audits:** findings must quote exact spans (F61); model findings are advisory unless backed by a verified quote.
7. **Repair:** span-local, bounded rounds, all L1 rerun after each round, best version kept (F62).
8. **Evidence:** request digest, prompt and output bytes, reported vs counted tokens, finish reason, seed, options, latency, findings and their status (fixed, open, local-model limit).
9. **Persist:** the output becomes an unapproved proposal or an R2 candidate exactly as Change 4 of the amendment describes.

Still open (measured in Task4, n ≥ 10): presence_penalty 0 vs 1.5 against F20/F50; thinking on for outline only; best scene size for length compliance.

## Addendum — same-idea donor differential results (2026-10-18)

Setup: same idea (`bench/idea.txt`), same model `ornith-32k:9b`, same endpoint `/v1`, donor sampling settings. Novel Studio `9b690ae2` run headless in UI order through `scripts/bench-run.ts` (≤ 3 "regenerate" clicks per step and ≤ 3 revise/check rounds, as a user would). Shenbi `65ddfc26` per-surface run (`bench/shenbi_surface.py`): `chapter-planning` → `chapter-drafting` skills verbatim plus a Vietnamese-output instruction, on the Novel Studio run's own story bible, style bible, volume outline and arc.

Bench harness deviations, recorded (not donor code): Novel Studio structured calls use a grammar-constrained `json_schema` generated from the donor's zod schema (root arrays wrapped in an object) plus a logged coercion fallback (used once in 8 runs' worth of calls); without them the donor never got past chapter 1 in six attempts.

### Novel Studio full run (run 8)

| Measure | Result |
|---|---|
| Steps | 30, each first click except chapter 3 acceptance |
| Chapters accepted by the donor's own gate | 2 of 3; chapter 3 refused after 3 revise/check rounds (timeline conflict: the notebook "page 10" repeats page 5 read in chapter 2; revisions did not converge) |
| Length | 1,069 + 1,804 + 2,630 = 5,503 syllables vs 9,000 target |
| CJK in final chapters | 0 (run 7: style revision introduced `灶`) |
| Dialogue lines | 1 / 2 / 2 |
| Ending | **none** — the volume outline is a longer serial (midpoint at "page 35"); chapter 3 ends mid-discovery |
| Premise drift | outline says "ba năm xa cách" against the idea's 10 years |

### Chapter 1 drafting surface (same upstream)

| | Novel Studio (run 7) | Shenbi seed 1 | Shenbi seed 2 |
|---|---|---|---|
| Syllables (target 3,000) | 1,397 | 1,157 | 3,650 (mostly loop) |
| CJK | 2 | 0 | 4 |
| Repetition | motif repetition | one paraphrased paragraph repeated | degenerate loop: one 3-sentence block × 12 |
| Other defects | English code-mixing ("cú call", "cánh gate"), mother and sister both "Lan", no dialogue | age arithmetic (1985 "anh mới bốn tuổi"), grandmother/mother confusion, decisions-sidecar JSON leaked into prose | — |
| Planning memo | — | Chinese despite the Vietnamese instruction | Chinese |

### Conclusions (provisional, small n; final selection by the Task4 differential with n ≥ 10)

- **Fact:** neither donor reaches a complete three-chapter story with an ending on this model. Novel Studio's workflow is serial-first (no closure), and its revise loop does not converge on a real timeline conflict. Shenbi's long drafting skill destabilizes the 9B model (loop, meta leakage).
- **Selection direction:**
  - Story shape and closure: Shenbi `short-outline` (three-act compression, a task per chapter, mandatory ending, generate → review → revise).
  - Scene contract fields: Novel Studio chapter outline + scene beats, enriched with Shenbi memo sections "withheld cards" (`压住的底牌`) and "changes required by chapter end" — these carry the secret-reveal pacing that Novel Studio lost (F35, F40).
  - Drafting prompt: Novel Studio `chapterDraftPrompt` base (more stable on 9B), plus Shenbi craft rules that are short and checkable (no narrator conclusions, show-don't-tell, dialogue presence), not the full skill text.
  - Review: Novel Studio continuity prompt + `hardRules` (already ported) for L2; Shenbi specialist audits for L3; the donor acceptance gate pattern (block on high/critical) kept.
  - Repair: span-local (Huohuo) instead of whole-chapter style revision, because whole-chapter revision changed almost nothing (1,397 → 1,396) yet introduced a CJK leak and did not converge.
- **New failure rows:** F25 English code-mixing (observed); F50 degenerate loop confirmed at paragraph level; F30 age arithmetic; F43 sidecar leakage; F13 memo language.

Raw outputs: `<scratchpad>/bench/ns-run`, `ns-run7`, `shenbi-surface` (session-local).

## Plan amendments required (step 2)

1. Approve the Task0 owner-map amendment (`task_repo.py`, `ledger.py`, `budget_guard.py` and their tests) recorded in `R2_STORY_AUTHORING_QUALIFICATION.md`.
2. Make Ollama the first qualified provider; Claude and OpenAI remain fixture-only until configured.
3. Replace per-chapter Human steps with the three-touchpoint automation above, plus finite automatic repair.
4. Add the manuscript → project novel-source hand-off.
5. Add production activation steps after acceptance.

## Addendum — token-count calibration and grammar CJK ban (2026-10-18)

Facts, Ollama 0.32.6, `ornith-32k:9b`, `think: false`:

- `POST /api/tokenize` returns 404; no exact local token count is available through Ollama.
- Calibration via `/api/chat` with `num_predict: 1`, subtracting a one-character baseline (n = 10 texts: Vietnamese prose, Shenbi memos containing Chinese, JSON): 1.75–3.77 characters per token, **3.61–5.04 UTF-8 bytes per token**. Bytes are the tighter basis. Chosen constants: preflight upper bound `bytes / 3.0`; post-check floor `bytes / 6.0`.
- Grammar ban: `format` = object schema whose string has `pattern` `^[^<CJK ranges>]*$`.

| Prompt | Decoding | n | Outputs with CJK | Invalid JSON | tok/s |
|---|---|---|---|---|---|
| Adversarial ("insert 突然 and 心里") | free | 5 | 3 | — | 30–37 |
| Adversarial | grammar | 5 | 0 | 1 | 30–41 |
| Scene 1, about 700 words | free | 5 | 2 | — | 44–45 |
| Scene 1 | grammar | 5 | 0 | 0 | 43–45 |

Inference: grammar exclusion removes CJK leakage at no speed cost. Unknown: its effect on prose quality and length at scale; Task1 repeats this at n ≥ 20 with the scene rubric.
