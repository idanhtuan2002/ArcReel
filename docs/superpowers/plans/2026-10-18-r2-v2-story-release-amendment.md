# R2 V2 story release — amendment to the idea-to-story plan

Status: DRAFT_FOR_HUMAN_REVIEW, revision 2. Supersedes revision 1 (`e833e27a`). Amends `docs/superpowers/plans/2026-10-17-r2-idea-to-story-authoring.md` (approved 2026-10-17). Everything in that plan stays in force unless this document changes it. Research basis: `docs/research/2026-10-18-r2-v2-story-release-research.md` (addenda through `12945df3`).

**Goal:** Release V2 = V1 + an automated idea → complete Vietnamese short story flow. The output is an exported manuscript that can also continue into the existing video flow. Run on local Ollama first, then take it to real operation.

## Decisions recorded (sponsor, 2026-10-18)

- Base: `r2-v2/main` `23cf146a` lineage, worked on `design/r2-story-authoring`. M9 is excluded.
- Integrate existing owners only. Glue code is authorized; no redesign and no change to accepted ADRs.
- Model: `ornith:9b` on local Ollama through the existing custom provider `openai_chat` endpoint. Claude and OpenAI stay fixture-qualified only until they are configured.
- Story: one Vietnamese short story, three chapters, visible ending, with explicit limits. Long-form is out of scope (ADR-0089 §8).
- Quality: commercial grade. Defects attributable only to the local model's limits are accepted and recorded as such.
- Donor rule (R2-DEC-031, sponsor rule 2026-09-09): every donor-derived surface is at least equal to its donor on the same fixture (`DonorParityContract`, rows `PARITY` or `IMPROVED`).
- Human touchpoints:
  - **Story: 2.** (1) enter and approve the idea; (2) receive and approve the final manuscript. Automatic idea entry and approval may replace (1) later; that change is not part of V2.
  - **Video: 3**, unchanged — Gates B, C and D.
  - The Human may request a revision of any part at any step (see Change 4).
  - Everything else runs without a human.

## Change 1 — close Task0 with the recorded owner-map amendment

Unchanged from revision 1. Add to the owned file map the paths that `R2_STORY_AUTHORING_QUALIFICATION.md` proposes:

- `lib/db/repositories/task_repo.py`: a dedicated guarded text-task checkpoint transition. Video checkpoint methods and guards stay unchanged.
- `lib/ledger.py`: optional explicit input/output token quantities passed into the existing `PricingParams`. Existing callers keep their defaults.
- `lib/budget_guard.py`: enforce an explicitly authorized authoring run/step ceiling in every release mode. Legacy DEV behaviour stays unchanged. Missing pricing refuses a paid call; a local provider still enforces token/call ceilings.
- Tests: `tests/integration/lib/db/repositories/test_task_repo.py`, `tests/integration/lib/db/repositories/test_task_command_idempotency.py`, `tests/integration/lib/test_budget_guard.py`, `tests/unit/lib/test_ledger.py`, `tests/unit/lib/test_text_generator.py`.

No new table, migration, governance authority, frozen R2 contract or capability-profile change.

## Change 2 — Ollama is the first live provider, with guards

Facts from the research: Ollama silently truncates input above the server context (prompt cut to about 4,098 tokens at `OLLAMA_CONTEXT_LENGTH=8192`); the model leaks CJK characters with both Chinese and Vietnamese prompts; and both donors failed end to end on this model because of structured-output format, not content.

- Task1 qualifies the custom provider `openai_chat` backend against Ollama `/v1/chat/completions`: exact request, `finish_reason` (`stop`/`length`), usage tokens, timeout, cancellation, unavailable endpoint. Transport fixtures first, then one live probe.
- **Model tag:** the operator registers `ornith-32k:9b` (`ornith:9b` + `PARAMETER num_ctx 32768`; verified 6.4 GB VRAM, about 40 tok/s, 16,180 prompt tokens accepted). The runbook carries the Modelfile.
- **Truncation guard:** a call whose reported `prompt_tokens` is lower than the locally counted input by more than the counter's tolerance is refused as `INPUT_TRUNCATED` and never stored as a candidate.
- **Output contract owned by R2:** each structured call returns exactly one JSON object validated against a Pydantic schema. On failure, one bounded repair call receives the validation errors (not a blind retry), followed by a deterministic coercion of string-expected fields. Prose calls return plain text checked for termination and `finish_reason`.
- **CJK leak detector:** deterministic. Any Han/CJK character in Vietnamese output marks the affected sentences for a strict local repair (Huohuo repair-loop role). The chapter cannot pass with a leak left.
- No cloud fallback. A down local endpoint gives a visible, resumable "model unavailable" state.
- Limits (`StoryLimits` defaults, editable by the operator): output ≤ 4,096 tokens per call, input ≤ 24,576 tokens per call, `max_repairs` 2 per scene, cost 0 minor units in currency `LOCAL`, and a per-run call ceiling computed from the stage table in Change 3 (fixed in Task4 from measured counts).

## Change 3 — the writer pipeline, built from the frozen donor roles

Roles are frozen in `R2_01` §20 and R1.5 §17–§19: Shenbi = planning/drafting skills and audits; Novel Studio = workflow; Huohuo = change record, adaptation and the strict local repair loop. The scene is the execution and review unit (R1.5 §14, R2-D53). Review layers: L1 deterministic (R2), L2 specialist audits, L3 independent critic, L4 Human (touchpoint 2).

Stage order (Novel Studio workflow shape, short-story scale):

1. Idea → story seed (premise, characters with Vietnamese kinship terms, POV, tone, ending direction).
2. Story bible + style bible (genre-aware schema; no long-form-only fields).
3. Outline: three chapters → scene contracts (R2 `NarrativePlan` content).
4. Per scene, sequentially: compile context (R2 `NarrativeContextCompiler`) → draft → L1 checks → L2 audits → bounded repair → candidate.
5. Per chapter: continuity check (M5C `continuity_rules` + donor continuity prompt) → style revision pass.
6. Whole manuscript: L3 critic pass (advisory findings), ending check, packaging (title, blurb).

Each model-calling stage takes its prompt content from the donor surface that wins the same-fixture differential (`DonorParityContract`); Vietnamese translation of a donor prompt is a recorded intentional deviation. Final selection per stage is recorded in the parity contract document, not here.

## Change 4 — two touchpoints and revisions at any step

1. **Touchpoint 1 (Gate A).** One form takes the idea, genre and limits. Submit records Gate A greenlight through the existing `POST /gates/greenlight`, bound to the digest of the exact idea text, and enqueues the run.
2. **Automatic.** Stages 1–6 run. Every output is an unapproved proposal stored as a host artifact with exact digests; nothing is committed to R2 governance yet.
3. **Pre-touchpoint binding proof.** Before the manuscript is offered, the run simulates the exact commit sequence with provisional in-memory readers (plan as its next version, canon after each chapter's change set) through the *same* `NarrativeContextCompiler`, and checks that every scene's `context_pack_id` and `content_hash` equal those used at generation. A mismatch regenerates that scene automatically.
4. **Touchpoint 2.** The Human reads the manuscript, the findings and the outline. One click records, in order, each a Human decision bound to an exact revision:
   - the `NarrativePlanApproval` through `NarrativePlanService.commit_revision`;
   - per chapter: `decide_revision` → `review_change_set` → `admit_canon_handoff` (with the exact `CanonCommitApproval`) through `NarrativeAcceptanceService` and the real Showrunner authority adapter.

   After each commit the context is recompiled and compared again; any difference stops the sequence before the next decision and reports the exact scene. Task3 must prove this sequence on PostgreSQL; if a decision family cannot be bound this way, Task3 returns the exact incompatibility before Task4 starts.
5. **Revisions.** At any time the Human may open the idea, a bible, the outline, a chapter or a scene and request a change with a note.
   - Before touchpoint 2: the system writes a new proposal revision of that part, marks everything downstream stale, and regenerates downstream automatically. No governance record changes.
   - After touchpoint 2: a revision is a new R2 candidate/revision through the normal lifecycle and needs a new Human acceptance.
6. **Automatic.** The accepted manuscript is exported as Markdown through host artifacts, with exact revision IDs.

A run never approves anything by itself. Model reviews are recommendations (ADR-0089: an automatic QA score is not an approval).

## Change 5 — hand-off into the video flow

Unchanged from revision 1. `StoryAuthoringService.send_to_video(scope, manuscript_ref, command_id)` calls `server/tool_runtime.py::upload_source` with the exported `.md` and an explicit `on_conflict`. The existing novel-source pipeline (episode planning → script → storyboard → video) then runs unchanged, followed by Gates B–D. The project must already be `source_kind=novel`. The UI offers this as one button after acceptance; it is not a gate.

Owned additions: `server/story_authoring/handoff.py` and `tests/unit/server/story_authoring/test_handoff.py`.

## Change 6 — release and real operation (new Task7)

Unchanged from revision 1, with the touchpoint count updated:

1. Merge `design/r2-story-authoring` into `r2-v2/main`. Annotate the release tag `r2-v2.0.0` on the exact accepted commit (ADR-0089 §7 lineage rule). Push only with Human confirmation.
2. Back up the V2 staging environment (`~/arcreel-v2-staging`) with `docs/r2/runbooks/m7-backup-restore.md`. Deploy the tag, run `alembic upgrade head` (expected: no new revision), register the Ollama custom provider and `ornith-32k:9b`, and run one live story plus the video hand-off.
3. Write `docs/r2/runbooks/story-authoring.md`: setup, the 2 + 3 touchpoints, revision requests, resume, limits, the model swap to cloud later, and backup coverage of the authoring artifacts.
4. Production activation happens only on explicit Human confirmation at that time.

## Acceptance additions

- `DonorParityContract` for every selected surface: deterministic surfaces with exact-source fixtures; model surfaces with the same idea, same model and a scored differential. All material rows `PARITY` or `IMPROVED`.
- One live `ornith-32k:9b` run from idea to an exported three-chapter manuscript with an ending, with zero Human actions besides the two story touchpoints. A restart in the middle of chapter 2 resumes without regenerating chapter 1. One revision request (e.g. chapter 2) regenerates only chapter 2 and what depends on it.
- Zero CJK characters and zero truncated calls in the accepted manuscript.
- The quality record lists every L1/L2/L3 finding, each marked fixed, open, or "local-model limit".
- The sponsor reads the manuscript; their approval at touchpoint 2 is the quality verdict.
- The video hand-off creates `source/<story>.md`, and the existing episode-planning step accepts it.
- Regression: the affected-domain static gates plus the related tests listed in each task. PostgreSQL interleavings for the checkpoint/budget and decision-sequence changes. No full suite unless asked.

## Execution

Main agent, inline and serial: Task0 close → Task1 → Task2 → Task3 (including the binding proof) → Task4 (Changes 3–5) → Task5 → Task6 → Task7. One progress report per task gate; one final independent review (Codex) and at most one repair.
