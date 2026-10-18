# R2 V2 story release — amendment to the idea-to-story plan

Status: DRAFT_FOR_HUMAN_REVIEW, revision 3. Supersedes revision 2 (`04f2e2af`), which superseded revision 1 (`e833e27a`). Revision 3 answers the nine review points of 2026-10-18 (touchpoint definition, dependency graph, binding-proof bound, token counter, CJK ladder, LOCAL ledger, probe vs acceptance run, resume checkpoint, discard). Amends `docs/superpowers/plans/2026-10-17-r2-idea-to-story-authoring.md` (approved 2026-10-17). Everything in that plan stays in force unless this document changes it. Research basis: `docs/research/2026-10-18-r2-v2-story-release-research.md` (addenda through `12945df3`).

**Goal:** Release V2 = V1 + an automated idea → complete Vietnamese short story flow. The output is an exported manuscript that can also continue into the existing video flow. Run on local Ollama first, then take it to real operation.

## Decisions recorded (sponsor, 2026-10-18)

- Base: `r2-v2/main` `23cf146a` lineage, worked on `design/r2-story-authoring`. M9 is excluded.
- Integrate existing owners only. Glue code is authorized; no redesign and no change to accepted ADRs.
- Model: `ornith:9b` on local Ollama through the existing custom provider `openai_chat` endpoint. Claude and OpenAI stay fixture-qualified only until they are configured.
- Story: one Vietnamese short story, three chapters, visible ending, with explicit limits. Long-form is out of scope (ADR-0089 §8).
- Quality: commercial grade. Defects attributable only to the local model's limits are accepted and recorded as such.
- Donor rule (R2-DEC-031, sponsor rule 2026-09-09): every donor-derived surface is at least equal to its donor on the same fixture (`DonorParityContract`, rows `PARITY` or `IMPROVED`).
- Human touchpoints. A **touchpoint** is a Human action that the happy path cannot pass without. Only touchpoints are counted.
  - **Story: 2.** (1) enter and approve the idea (Gate A); (2) receive and approve the final manuscript. Automatic idea entry and approval may replace (1) later; that change is not part of V2.
  - **Video: 3**, unchanged — Gates B, C and D.
  - **Not counted:** revision requests and discard (Change 4 §5, §7). They are optional; the run never waits for them and never asks for them. A run that reaches touchpoint 2 with zero optional actions is the acceptance case.
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
- **Truncation guard.** Ollama 0.32.6 exposes no tokenizer endpoint (`POST /api/tokenize` → 404), so there is no exact local count. The guard uses a calibrated byte bound instead, in two layers:
  - Preflight (prevention): `estimate_max = ceil(utf8_bytes(rendered messages) / 3.0) + template_overhead` must be ≤ the input limit (24,576), else the call is refused before sending as `INPUT_OVER_LIMIT` and the stage splits or trims its context by its own rule. Measured on `ornith-32k:9b` (2026-10-18, n = 10, Vietnamese prose, Shenbi memos with Chinese, JSON): 3.61–5.04 UTF-8 bytes per token, so the real count is at most `bytes / 3.6` < 24,576 < 32,768 − 4,096 output. Truncation cannot occur while preflight holds.
  - Post-check (defence in depth): reported `prompt_tokens` < `floor(utf8_bytes / 6.0)` is refused as `INPUT_TRUNCATED` and never stored. The observed truncation cut about 75 % of the prompt, far below this floor.
  - Task1 recalibrates the two constants on the fixture corpus with `num_predict: 1` probes and records min/max ratio, the constants and the margin in the qualification evidence. A constant changes only through that evidence.
- **Output contract owned by R2:** each structured call returns exactly one JSON object validated against a Pydantic schema. On failure, one bounded repair call receives the validation errors (not a blind retry), followed by a deterministic coercion of string-expected fields. Prose calls return plain text checked for termination and `finish_reason`.
- **CJK prevention, then detection.** Zero CJK is an invariant, not a quality finding; it can never be labelled "local-model limit".
  1. Prevention: every Vietnamese prose and JSON-string output is generated under a grammar that excludes the CJK ranges (Ollama `format` schema, string `pattern` `^[^\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]*$`). Probe 2026-10-18, same model: free decoding leaked CJK in 3/5 adversarial and 2/5 normal scene outputs; under the grammar 0/10, same speed (about 43 tok/s), one JSON-wrapping failure out of 10 handled by the output contract. Task1 repeats this at n ≥ 20 and also checks that the grammar does not lower the scene rubric.
  2. Detection: the deterministic detector still runs on every output (covers a provider without grammar support, such as cloud later).
  3. Ladder when a leak is found: span-local repair (Huohuo role) up to `max_repairs` 2 → regenerate the whole scene up to `max_scene_regens` 2 → scene `BLOCKED_QUALITY`. The run then stops before touchpoint 2 and shows the exact scene and spans; the Human may retry or request a revision. A manuscript with a CJK character is never offered.
- No cloud fallback. A down local endpoint gives a visible, resumable "model unavailable" state.
- Limits (`StoryLimits` defaults, editable by the operator): output ≤ 4,096 tokens per call, input ≤ 24,576 tokens per call, `max_repairs` 2 per scene, `max_scene_regens` 2 per scene, `max_binding_regens` 2 per scene, and a per-run call ceiling computed from the stage table in Change 3 (fixed in Task4 from measured counts).
- **Ledger and budget for a local provider.** Price is 0 minor units in currency `LOCAL`. Each call still writes a ledger row with its input/output token quantities (Change 1) for observability: throughput, per-stage usage and the call-ceiling basis. They are not billing. The budget guard enforces calls and tokens for `LOCAL`; money ceilings apply only to priced currencies. `LOCAL` rows are excluded from any money total.

## Change 3 — the writer pipeline, built from the frozen donor roles

Roles are frozen in `R2_01` §20 and R1.5 §17–§19: Shenbi = planning/drafting skills and audits; Novel Studio = workflow; Huohuo = change record, adaptation and the strict local repair loop. The scene is the execution and review unit (R1.5 §14, R2-D53). Review layers: L1 deterministic (R2), L2 specialist audits, L3 independent critic, L4 Human (touchpoint 2).

Stage order (Novel Studio workflow shape, short-story scale):

1. Idea → story seed (premise, characters with Vietnamese kinship terms, POV, tone, ending direction).
2. Story bible + style bible (genre-aware schema; no long-form-only fields).
3. Outline: three chapters → scene contracts (R2 `NarrativePlan` content).
4. Per scene, sequentially: compile context (R2 `NarrativeContextCompiler`) → draft → L1 checks → L2 audits → bounded repair → candidate.
5. Per chapter: continuity check (M5C `continuity_rules` + donor continuity prompt) → style revision pass.
6. Whole manuscript: L3 critic pass (advisory findings), ending check, packaging (title, blurb).

Each model-calling stage takes its prompt content from the donor surface that wins the same-fixture differential (`DonorParityContract`); Vietnamese translation of a donor prompt is a recorded intentional deviation. The provisional selection (surfaces S01–S11, pins, source hashes, deviations, rejected surfaces) is `docs/r2/evidence/R2_STORY_DONOR_BASELINE.json`; Task4 confirms it with n ≥ 10.

Every step follows the standard step contract and handles the failure taxonomy F01–F71 from the research (addendum "small-model failure research").

**Artifact dependency graph.** Staleness is computed from recorded inputs, never inferred from text or from the stage order.

- Nodes: `idea` → `seed` → `story_bible`, `style_bible` → `outline` → `scene_contract[c,s]` → `scene_draft[c,s]` → `chapter[c]` (continuity + style pass) → `manuscript_review` (L3, ending check) → `packaging`.
- Every stored proposal revision records `inputs: [(node, revision_id, digest)]`, the exact revisions it was produced from. A `scene_draft` also records its `context_pack_id`/`content_hash`. Because the context compiler includes earlier scenes, `scene_draft[c,s]` depends on every earlier `scene_draft`.
- A node is **stale** when any recorded input digest differs from the current revision of that input, transitively. A stale node is never offered at touchpoint 2 and never committed. Regeneration walks stale nodes in topological order; a fresh node is never regenerated.
- The table of edges lives in the stage table (`server/story_authoring/pipeline.py`, below). Task4 tests it table-driven: for each node, a revision stales exactly the expected set. Examples:
  - `chapter[2]` → its scenes, `chapter[2]`, all of chapter 3, `manuscript_review`, `packaging`. Chapter 1, bibles and outline stay fresh.
  - `story_bible` → `outline` and everything below it.
  - `packaging` → nothing else.
- Over-regeneration is preferred to under-regeneration: when a field-level dependency is uncertain, the edge stays at node level.

Additional owned paths (added to the 2026-10-17 file map):

- `server/story_authoring/prompts/` (`outline.py`, `planning.py`, `drafting.py`, `packaging.py`): donor-derived Vietnamese prompt templates, each citing its donor path and hash.
- `server/story_authoring/checks.py`: L1 deterministic checks (language, length, repetition/dedupe core, names, attributes, xưng hô matrix, coverage, meta).
- `server/story_authoring/audits.py`: L2 specialists and L3 critic; quote-verified findings.
- `server/story_authoring/repair.py`: Huohuo span-local repair port and length normalizing.
- `server/story_authoring/pipeline.py`: stage table, dependency edges, staleness, checkpoint cursor.
- Tests: `tests/unit/server/story_authoring/test_checks.py`, `test_audits.py`, `test_repair.py`, `test_prompts.py`, `test_pipeline.py`.
- Donor parity: `tests/integration/donor_parity/huohuo_continuity_patch_runner.mjs`, `huohuo_dedupe_runner.mjs`, fixtures under `tests/integration/donor_parity/fixtures/{huohuo_continuity_patch,huohuo_dedupe}/`, vendored unmodified sources, and `docs/r2/evidence/R2_STORY_*_PARITY.json` per selected surface.

## Change 4 — two touchpoints and revisions at any step

1. **Touchpoint 1 (Gate A).** One form takes the idea, genre and limits. Submit records Gate A greenlight through the existing `POST /gates/greenlight`, bound to the digest of the exact idea text, and enqueues the run.
2. **Automatic.** Stages 1–6 run. Every output is an unapproved proposal stored as a host artifact with exact digests; nothing is committed to R2 governance yet.
3. **Pre-touchpoint binding proof.** Before the manuscript is offered, the run simulates the exact commit sequence with provisional in-memory readers (plan as its next version, canon after each chapter's change set) through the *same* `NarrativeContextCompiler`, and checks that every scene's `context_pack_id` and `content_hash` equal those used at generation.
   - The hashes are pure functions of the compiler inputs, not of model output, so model nondeterminism cannot cause a mismatch. A mismatch means an input changed after generation (for example an earlier scene was regenerated) or a code defect.
   - On a mismatch the scene is marked stale and regenerated with everything stale after it (dependency graph), then the whole proof runs again from the first regenerated scene.
   - Bound: `max_binding_regens` 2 per scene. If the same scene still mismatches, the run enters `BLOCKED_BINDING_MISMATCH`: touchpoint 2 is not offered; the UI shows the scene, the expected and actual hashes and the differing input; the record files it as a defect (never "local-model limit"). The Human may retry the run or request a revision.
4. **Touchpoint 2.** The Human reads the manuscript, the findings and the outline, then chooses **Approve**, **Request revision** (§5) or **Discard** (§7). Approve records, in order, each a Human decision bound to an exact revision:
   - the `NarrativePlanApproval` through `NarrativePlanService.commit_revision`;
   - per chapter: `decide_revision` → `review_change_set` → `admit_canon_handoff` (with the exact `CanonCommitApproval`) through `NarrativeAcceptanceService` and the real Showrunner authority adapter.

   After each commit the context is recompiled and compared again; any difference stops the sequence before the next decision and reports the exact scene. Task3 must prove this sequence on PostgreSQL; if a decision family cannot be bound this way, Task3 returns the exact incompatibility before Task4 starts.
5. **Revisions.** At any time the Human may open the idea, a bible, the outline, a chapter or a scene and request a change with a note.
   - Before touchpoint 2: the system writes a new proposal revision of that part, marks the stale set from the dependency graph (Change 3), and regenerates only that set automatically. No governance record changes.
   - After touchpoint 2: a revision is a new R2 candidate/revision through the normal lifecycle and needs a new Human acceptance.
   - A revision request during the automatic run pauses at the next step boundary (never mid-call), writes the new revision, and the run continues from the stale set.
6. **Automatic.** The accepted manuscript is exported as Markdown through host artifacts, with exact revision IDs.
7. **Discard.**
   - Before touchpoint 2 approval: the Human may discard the run at any time, including at touchpoint 2. The run becomes `DISCARDED` (terminal). The in-flight call finishes or times out, and its result is kept only as a record. Proposals stay as read-only host artifacts for audit. There is no governance record, no export and no hand-off. A new idea starts a new run.
   - After touchpoint 2 approval: R2 records are append-only and stay. The Human may **withdraw** the manuscript: a host marker that blocks `send_to_video` and further exports and labels the export superseded. A source file already handed to video stays in the project; removing it uses the existing source deletion. Changing the story itself is a new revision (§5).

**Resume.** A story run persists a checkpoint through the new guarded text-task checkpoint transition in `task_repo.py` (Change 1).
- When: after each stored proposal revision, i.e. per stage for stages 1–3 and 5–6 and per scene step (draft, repair, candidate) in stage 4.
- What: the stage cursor (node, attempt) and the digest of every stored node.
- On restart: nodes whose stored revision exists and is fresh are skipped. A call in flight at the crash is never resent silently: its attempt is recorded as `ABANDONED_UNKNOWN` and a new attempt with a new attempt ID is issued visibly. With price `LOCAL` 0 it costs nothing, and it counts against the call ceiling.
- Task4 proves this with the "restart during chapter 2" test.

A run never approves anything by itself. Model reviews are recommendations (ADR-0089: an automatic QA score is not an approval).

## Change 5 — hand-off into the video flow

Unchanged from revision 1. `StoryAuthoringService.send_to_video(scope, manuscript_ref, command_id)` calls `server/tool_runtime.py::upload_source` with the exported `.md` and an explicit `on_conflict`. The existing novel-source pipeline (episode planning → script → storyboard → video) then runs unchanged, followed by Gates B–D. The project must already be `source_kind=novel`. The UI offers this as one button after acceptance; it is not a gate.

Owned additions: `server/story_authoring/handoff.py` and `tests/unit/server/story_authoring/test_handoff.py`.

## Change 6 — release and real operation (new Task7)

Unchanged from revision 1, with the touchpoint count updated:

1. Merge `design/r2-story-authoring` into `r2-v2/main`. Annotate the release tag `r2-v2.0.0` on the exact accepted commit (ADR-0089 §7 lineage rule). Push only with Human confirmation.
2. Back up the V2 staging environment (`~/arcreel-v2-staging`) with `docs/r2/runbooks/m7-backup-restore.md`. Deploy the tag, run `alembic upgrade head` (expected: no new revision), register the Ollama custom provider and `ornith-32k:9b`, and run one **staging smoke**: one live story plus the video hand-off, evidence `docs/r2/evidence/R2_V2_STAGING_SMOKE.json`. It confirms the deployment; it is not the acceptance run.
3. Write `docs/r2/runbooks/story-authoring.md`: setup, the 2 + 3 touchpoints, revision requests, resume, limits, the model swap to cloud later, and backup coverage of the authoring artifacts.
4. Production activation happens only on explicit Human confirmation at that time.

## Acceptance additions

Three distinct live runs, all on the same local GPU host and `ornith-32k:9b`:

| Run | Task | Purpose | Evidence |
|---|---|---|---|
| Transport probe | Task1 | One call per contract case (stop/length/usage/timeout/cancel/unavailable), plus the token and grammar calibration | `R2_STORY_AUTHORING_QUALIFICATION` update |
| Acceptance run | Task6 | The full idea → manuscript run below, in the dev worktree | `docs/r2/evidence/R2_STORY_ACCEPTANCE_RUN.json` bound to HEAD |
| Staging smoke | Task7 | Deployment check on the tag | `R2_V2_STAGING_SMOKE.json` |

Acceptance criteria:

- `DonorParityContract` for every selected surface: deterministic surfaces with exact-source fixtures; model surfaces with the same idea, same model and a scored differential. All material rows `PARITY` or `IMPROVED`.
- **Acceptance run (clean):** idea → exported three-chapter manuscript with an ending, with zero Human actions besides the two story touchpoints and zero optional actions.
- **Resume and revision (separate runs, so the clean run stays clean):**
  - A restart during chapter 2 resumes from the checkpoint without regenerating chapter 1.
  - A revision request on chapter 2 regenerates exactly the stale set from the dependency graph: chapter 2, chapter 3, `manuscript_review`, `packaging`.
  - A discard before touchpoint 2 leaves no governance record.
  - All three are proved by Task4 integration tests with a fixture model, then once live in Task6 (evidence in the same file).
- Zero CJK characters and zero truncated calls in the accepted manuscript; every call row carries its preflight estimate and reported `prompt_tokens`.
- The quality record lists every L1/L2/L3 finding, each marked fixed, open, or "local-model limit". CJK, truncation and binding mismatch are never in the last class.
- The sponsor reads the manuscript; their approval at touchpoint 2 is the quality verdict.
- The video hand-off creates `source/<story>.md`, and the existing episode-planning step accepts it.
- Regression: the affected-domain static gates plus the related tests listed in each task. PostgreSQL interleavings for the checkpoint/budget and decision-sequence changes. No full suite unless asked.

## Execution

Main agent, inline and serial: Task0 close → Task1 → Task2 → Task3 (including the binding proof) → Task4 (Changes 3–5) → Task5 → Task6 → Task7. One progress report per task gate; one final independent review (Codex) and at most one repair.
