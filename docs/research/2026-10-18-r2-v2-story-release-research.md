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

## Plan amendments required (step 2)

1. Approve the Task0 owner-map amendment (`task_repo.py`, `ledger.py`, `budget_guard.py` and their tests) recorded in `R2_STORY_AUTHORING_QUALIFICATION.md`.
2. Make Ollama the first qualified provider; Claude and OpenAI remain fixture-only until configured.
3. Replace per-chapter Human steps with the three-touchpoint automation above, plus finite automatic repair.
4. Add the manuscript → project novel-source hand-off.
5. Add production activation steps after acceptance.
