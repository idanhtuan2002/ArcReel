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

## Plan amendments required (step 2)

1. Approve the Task0 owner-map amendment (`task_repo.py`, `ledger.py`, `budget_guard.py` and their tests) recorded in `R2_STORY_AUTHORING_QUALIFICATION.md`.
2. Make Ollama the first qualified provider; Claude and OpenAI remain fixture-only until configured.
3. Replace per-chapter Human steps with the three-touchpoint automation above, plus finite automatic repair.
4. Add the manuscript → project novel-source hand-off.
5. Add production activation steps after acceptance.
