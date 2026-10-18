# R2 V2 story release — amendment to the idea-to-story plan

Status: DRAFT_FOR_HUMAN_REVIEW, revision 4. Supersedes revision 3 (`92d7eef9`), revision 2 (`04f2e2af`) and revision 1 (`e833e27a`). Amends `docs/superpowers/plans/2026-10-17-r2-idea-to-story-authoring.md` (approved 2026-10-17); everything in that plan stays in force unless this document changes it.

Research basis: `docs/research/2026-10-18-r2-v2-story-release-research.md`, through the addendum "provider contract probes" (revision 4). Revision 4 answers the second review of 2026-10-18 (P0-01…05, P1-01…10, P2) in this order: data model, governance commit protocol, provider qualification, durable execution, acceptance and release. The overall architecture, scope, owners, donors, the two touchpoints, the six stages and the task order are unchanged.

**Goal:** Release V2 = V1 + an automated idea → complete Vietnamese short story flow. The output is an exported manuscript that can also continue into the existing video flow. Run on local Ollama first, then take it to real operation.

## Decisions recorded (sponsor, 2026-10-18)

- Base: `r2-v2/main` `23cf146a` lineage. Design work happens on `design/r2-story-authoring`; the release branch carries only story-authoring commits (§ Release). M9 is excluded.
- Integrate existing owners only. Glue code is authorized; no redesign and no change to accepted ADRs. The one new provider surface (the `ollama-chat` endpoint, Change P) is listed for this approval.
- Model: `ornith:9b` on local Ollama. Claude and OpenAI stay fixture-qualified only until they are configured.
- Story: one Vietnamese short story, three chapters, visible ending, size envelope in § Size and budget. Long-form is out of scope (ADR-0089 §8).
- Three separate acceptance classes; none of them can excuse another:
  1. **Invariants** (zero CJK, zero truncated input or output, binding equality, complete structure). They always block. They can never be labelled "local-model limit".
  2. **Donor parity** (R2-DEC-031, sponsor rule 2026-09-09). Hard gate: every donor-derived surface is `PARITY` or `IMPROVED` on the same fixture. An exception exists only as an explicit sponsor decision recorded in the parity contract row.
  3. **Model quality.** Severity policy in Change G. Only the stylistic class may stay open as "local-model limit", and only with Human acceptance at touchpoint 2.
- Human touchpoints. A **touchpoint** is a Human action that the happy path cannot pass without; only touchpoints are counted.
  - **Story: 2.** (1) enter and approve the story brief (Gate A); (2) approve the final manuscript. Automatic brief entry and approval may replace (1) later; that change is not part of V2.
  - **Video: 3**, unchanged — Gates B, C and D.
  - **Optional, not counted:** revision requests, discard, withdraw, and a Gate A re-approval caused by a Human edit of the brief. The run never waits for them and never asks for them. The clean acceptance run has zero optional actions.

## Change 0 — Task0 closes with owner map, schema sufficiency and lineage proof

1. Owner-map additions (from `R2_STORY_AUTHORING_QUALIFICATION.md`), unchanged from revision 1:
   - `lib/db/repositories/task_repo.py`: a dedicated guarded text-task checkpoint transition. Video checkpoint methods and guards stay unchanged.
   - `lib/ledger.py`: optional explicit input/output token quantities passed into the existing `PricingParams`. Existing callers keep their defaults.
   - `lib/budget_guard.py`: enforce an explicitly authorized authoring run/step ceiling in every release mode. Legacy DEV behaviour stays unchanged. Missing pricing refuses a paid call; currency `LOCAL` enforces call/token ceilings.
   - Tests: `tests/integration/lib/db/repositories/test_task_repo.py`, `test_task_command_idempotency.py`, `tests/integration/lib/test_budget_guard.py`, `tests/unit/lib/test_ledger.py`, `tests/unit/lib/test_text_generator.py`.
2. **Schema sufficiency, proven, not declared.** Task0 maps every record this amendment needs to an existing table and column: proposal revisions, revision intents, attempt ledger, checkpoint, run budget, `ManuscriptCommitManifest`, quality record, export record. Each mapping is tested by a round-trip in an integration test. If any record has no home, Task0 stops with `SCHEMA_GAP` naming the record, and the Human decides on a migration. No migration is assumed either way.
3. **Lineage proof.** Facts checked 2026-10-18:
   - `r2-v2/main` and `r2-v1.0.0` are ancestors of `design/r2-story-authoring`.
   - The 31 commits between them are documents, plus M9 design-verifier scripts and their tests (`scripts/r2/verify_m9_*`, 5 files). There is no runtime M9 code.
   - No branch, ref, worktree or commit message named "Web Writer" or `r2-v2-native-narrative` exists in this repository.

   Task0 records this as evidence. At release the branch `release/r2-v2-story` is built from `r2-v2/main` with only the story-authoring commits, so neither M9 files nor any rolled-back code can enter V2. The pre-merge check is in § Release.

## Change D — data model: inputs, generated nodes, revision intents (P0-01, P1-05, P1-08)

Three kinds of object, never mixed:

| Kind | Nodes | Who creates a revision |
|---|---|---|
| **Brief** (authoritative, Gate A) | `brief` = idea, genre, language, limits, model selection, scope | Human only |
| **Generated nodes** | Planning: `seed`, `story_bible`, `style_bible`, `outline`, `scene_contract[c,s]`. Prose: `scene_draft[c,s]`. Checks: `chapter_review[c]`, `manuscript_review`. Output: `packaging` | The run (model call or deterministic step) |
| **Revision intents** | `intent` (target node, Human note, Human principal, created_at) | Human only |

**Edges** (data dependency; "A → B" means B is produced from A):

- `brief` → `seed` → `story_bible`, `style_bible` → `outline` → `scene_contract[c,s]`.
- `scene_contract[c,s]`, `story_bible`, `style_bible`, every `scene_draft` before `[c,s]` in story order → `scene_draft[c,s]`.
- All `scene_draft[c,*]` → `chapter_review[c]`.
- All `chapter_review[*]` and all `scene_draft` → `manuscript_review` → `packaging`.
- An `intent` targeting node X → X.

There is no "chapter" content node; a chapter is the ordered list of its scene heads, assembled deterministically at export. `chapter_review[c]` produces findings only. A finding becomes a **repair revision inside the same scene node**: a node has a revision chain r0 (draft), r1, r2 … (repairs), and its *head* is the last accepted revision. Repair findings are not inputs to the node, so there is no `chapter → scene` edge and no cycle. Chapter `c+1` starts only after chapter `c` is **sealed**: its review passed, or its repair budget is spent and the remaining findings are recorded.

**Fingerprint.** Each node revision records `fingerprint = sha256(canonical JSON)` of its effective inputs:
- the input revisions and digests, and its intents;
- prompt template ID and hash, donor source hash;
- `NarrativeContextCompiler` version and `context_pack_id`/`content_hash` (scenes);
- model name and Ollama blob digest, Modelfile hash, decoding parameters, schema hash;
- L1 rule-set version and the relevant `StoryLimits` fields.

A node is **stale** when its recomputed fingerprint differs from the one recorded on its head.

**Revision intents map to nodes:**

| Human target | Mapped to |
|---|---|
| brief | new `brief` revision → Gate A re-approval (Change C §4) |
| bible, outline, scene contract | an intent on that node; it is regenerated with the note, or the Human edits it directly |
| scene | an intent on `scene_draft[c,s]` |
| chapter `c` | one intent per `scene_draft[c,*]`, all carrying the same note |
| packaging | an intent on `packaging` |

**Impacted-node algorithm** (`server/story_authoring/pipeline.py`):
1. The new revision or intent on X defines `impacted = forward_closure(X)` over the static edge table.
2. Every impacted node whose recomputed fingerprint changed is stale.
3. Regenerate stale nodes in topological order (story order for scenes). A node is regenerated at most once per revision event.
4. Fresh nodes are never regenerated.

The edge table is static code, checked acyclic by a Kahn sort in a unit test.

**Late results (P1-08).** Every attempt carries the fingerprint it was dispatched with. Its result becomes the head only through a compare-and-set in the same transaction that checks `node.required_fingerprint == attempt.fingerprint`. Otherwise the result is stored as `STALE_RESULT` (record only) and never replaces a newer head. A revision request during a running call does not cancel the call; the late result is simply fenced.

Owned: `server/story_authoring/pipeline.py`, `tests/unit/server/story_authoring/test_pipeline.py` (acyclicity; for each change type brief, bible, outline, contract, scene, chapter and packaging, the exact stale set; topological order; late-result fencing).

## Change C — governance commit protocol (P0-02, P0-03, P1-01)

1. **Gate A binds the whole brief.** Gate A uses the existing `POST /gates/greenlight` with `source_digest = sha256(canonical JSON of brief)`, not of the idea text alone. Task3 verifies how a later `source/<story>.md` hand-off interacts with the project's Gate A semantics on the video side. If they conflict, Task3 stops with `GATE_A_SCOPE_CONFLICT` before Task4.
2. **Automatic stages.** Every output is an unapproved proposal stored as a host artifact; nothing is committed to R2 governance.
3. **Pre-touchpoint binding proof (as-of, P1-01).** Each `scene_draft` head records the exact as-of inputs it was compiled from:
   - plan version expected;
   - canon base version and the preceding chapters' change-set IDs;
   - the compiler input digests.

   The proof rebuilds each scene's context from those frozen inputs through provisional readers: the plan as its next version, and the canon after each preceding chapter's change set. It uses the same `NarrativeContextCompiler`, never the live current Canon, and requires equal `context_pack_id`/`content_hash`. The hashes depend on inputs only, so model nondeterminism cannot cause a mismatch.
   - On a mismatch, the scene is marked stale and regenerated (Change D), within the scene's attempt budget (§ Size and budget).
   - If the budget is spent, the run enters `BLOCKED_BINDING_MISMATCH`. Touchpoint 2 is not offered; the scene, the expected and actual hashes and the differing input are shown, and the case is recorded as a defect.
4. **Brief revision.** A Human edit of the brief writes a new `brief` revision. The run pauses at `AWAITING_GATE_A` and stales everything (Change D). It resumes only after a new Gate A greenlight on the new digest, and the old greenlight is revoked through the same route. This is optional, so the touchpoint count of the clean run does not change.
5. **`ManuscriptCommitManifest`.** An immutable host artifact with a digest, built when the run reaches touchpoint 2. It holds:
   - run ID, brief digest and Gate A decision ID;
   - plan proposal: revision ID, content hash, expected version;
   - per chapter, in order: scene revision IDs and digests, change-set IDs, expected canon base version, the `CanonCommitApproval` payload digest, the expected decision heads;
   - one deterministic idempotency key per step: `sha256(manifest_digest ‖ step_index)`;
   - unresolved findings and the exceptions offered for Human acceptance (Change G);
   - the expected export digest.
6. **Touchpoint 2.** The Human sees the manuscript, findings and outline, all bound to one manifest digest, and chooses **Approve**, **Request revision** or **Discard**. Approve is one authenticated Human request through the existing interactive-auth dependency, bound to the manifest digest and to the list of exceptions the Human ticked. It authorizes exactly the decisions listed in the manifest and nothing else; each decision record carries the Human principal and the manifest digest. Task3 proves that the real Showrunner authority adapter accepts decisions created in one authenticated Human request. If an authority requires one interaction per decision, Task3 returns the exact incompatibility before Task4.
7. **Commit execution**, through the existing owners only (`NarrativePlanService.commit_revision`, `NarrativeAcceptanceService.decide_revision` → `review_change_set` → `admit_canon_handoff`); no parallel authority. State machine:
   - `APPROVING` → step k (plan, then per chapter the three decisions) → `PARTIALLY_COMMITTED(k)` after each step → `COMMITTED` after a read-back verifies every receipt against the manifest.
   - Before each step: check the current versions and heads the manifest expects (optimistic concurrency, using the services' existing `expected_version`/`expected_latest_decision_id` checks), recompile that chapter's context from the real committed state, and compare with the manifest.
   - Any difference or refusal → `COMMIT_BLOCKED(step, reason)`. No further decision is sent.
   - Every step uses its idempotency key. The existing exact-retry paths (`get_version_by_revision`, admission retry resolution) return the original receipt for a repeated step.
   - **Resume** after a crash or block re-reads receipts, skips completed steps by key, and continues from the first incomplete step. A block caused by a concurrent Canon change requires a new manifest: the affected scenes become stale and are regenerated, and a new touchpoint 2 follows. This is optional, so it is not counted. Already-committed steps stay; R2 records are append-only.
   - Export and video hand-off are allowed only in `COMMITTED`.
8. **Discard and withdraw.**
   - Before Approve: `DISCARDED` (terminal). The in-flight attempt is fenced as `STALE_RESULT`; proposals stay read-only; there is no governance record, export or hand-off.
   - After `COMMITTED`: **withdraw** is a host marker that blocks `send_to_video` and further export, and labels the export superseded. A source already handed to video stays; it is removed only through the existing source deletion.
   - In `PARTIALLY_COMMITTED` or `COMMIT_BLOCKED`, discard is refused; the Human resumes or withdraws.

**Task3 is a hard gate.** Task4 does not start until Task3 passes PostgreSQL integration tests with the real authority adapter:
- the manifest with plan plus three chapters;
- a crash after chapter 1 and after chapter 2, then resume with no duplicate decision;
- a Canon change between the binding proof and the commit → `COMMIT_BLOCKED`, nothing wrong committed;
- concurrent Approve from two sessions → exactly one sequence;
- a stale manifest digest refused.

## Change P — provider qualification for Ollama (P0-04, P0-05, resource envelope)

Facts from the provider-contract probes (Ollama 0.32.6, `ornith-32k:9b`, 2026-10-18; research addendum):

| Fact | Consequence |
|---|---|
| `/api/chat` with `"truncate": false` and a 56,071-token prompt returns HTTP 400 `exceed_context_size_error` with the exact token count. Without it, the prompt is silently cut to 16,386 tokens. `/v1/chat/completions` ignores `truncate` and cuts silently. | Only the native API gives a fail-closed, server-side truncation guarantee. |
| The model's Modelfile carries `SYSTEM You are Ornith, an open-source agentic coding assistant…`. Without our own system message, it answers as a coding assistant. | Every call sends an explicit system message. |
| The existing `openai_chat` backend retries silently up to 4 times (`with_retry_async`) and silently falls back to Instructor when the native schema fails. | It must not be used for story calls: hidden retries break the budget, and a silent fallback breaks fail-closed structured output. |
| The grammar `pattern` (no CJK) is honoured on both `/api/chat format` and `/v1 response_format json_schema`: 0 CJK in 15 constrained outputs. The model then code-mixes English instead ("Suddenly"). | The grammar prevents CJK; the F25 code-mixing detector stays mandatory. |
| `POST /api/tokenize` → 404. | There is no exact local count; the server's 400 is the exact check. |

Decisions:

1. **New endpoint `ollama-chat`** in the existing custom-provider registry: `lib/custom_provider/endpoints.py` `EndpointSpec`, plus a backend `lib/text_backends/ollama.py`. Story calls use only this endpoint. `openai_chat` stays as it is for other uses and for cloud later. Before the change, follow `docs/api-docs/AGENTS.md` and `.claude/rules/provider-capabilities.md`.
2. **Exact request** (`POST {base}/api/chat`):

   ```json
   {"model": "<tag>", "stream": false, "think": false, "truncate": false,
    "messages": [{"role": "system", "content": "<stage system prompt>"}, {"role": "user", "content": "<rendered>"}],
    "format": <JSON schema>,
    "options": {"num_ctx": 32768, "num_predict": <limit>, "temperature": <t>, "top_p": <p>, "top_k": <k>,
                "presence_penalty": <pp>, "seed": <seed>},
    "keep_alive": "<operator setting>"}
   ```

   - The response fields used are `message.content`, `done_reason`, `prompt_eval_count` and `eval_count`.
   - No SDK retry, no fallback. One HTTP request is one attempt in the attempt ledger.
   - Task1 verifies that `options.num_ctx` equal to the tag value does not reload the model.
3. **Structured calls:** `format` is the Pydantic schema. **Prose calls** use the envelope `{"type":"object","properties":{"text":{"type":"string","minLength":1,"pattern":"<NO_CJK>"}},"required":["text"],"additionalProperties":false}`. The result is unwrapped by `json.loads`, validated with the Pydantic model, then checked by the shared detector. The unwrapped text and the raw envelope digest are stored.
4. **HTTP 200 but non-compliant** (invalid JSON, a missing field, a schema or pattern violation, or a detector hit): typed `OUTPUT_INVALID`, never stored as a head. One error-feedback repair attempt follows, counted in the budget.
5. **Grammar ignored or unsupported:** Task1 runs an adversarial canary (the prompt asks for CJK) at n ≥ 20 for every schema kind. Any CJK that passes the grammar means the provider is **not qualified**, and story runs refuse it with `PROVIDER_NOT_QUALIFIED`. A provider without grammar support (cloud later) needs its own qualification; it is never assumed.
6. **Shared CJK detector** (`server/story_authoring/script_guard.py`, one module for runtime validation and acceptance). It is a range table generated from Unicode `Scripts.txt` and pinned to the Unicode version of the running `unicodedata`:
   - scripts Han (including Extensions A–H and compatibility ideographs), Hiragana, Katakana, Hangul, Bopomofo;
   - CJK Symbols and Punctuation, Halfwidth and Fullwidth Forms, CJK Compatibility Forms, Kangxi and CJK radicals, Ideographic Description characters.

   A unit test cross-checks the table against `unicodedata` names. It applies to every model output, every scene head, the chapter assembly, title, blurb, the manuscript and the exported `.md` bytes; the last check runs immediately before export and again in `send_to_video`. The grammar pattern carries the BMP ranges; Task1 tests whether astral ranges work in the grammar. The detector covers all ranges regardless.
7. **Truncation, input:** the server-side `truncate: false` is the guarantee; an over-context call is refused as `INPUT_OVER_CONTEXT` with the server's exact count. The byte preflight (`bytes / 3.0` ≤ 24,576) is only a cost-saving heuristic and is never cited as proof. `prompt_eval_count` is recorded for observability only: cached prefixes can lower it, so it is not used as a floor.
   **Truncation, output:** `done_reason = "length"` or a missing `done_reason` → `OUTPUT_TRUNCATED`, never stored.
   The acceptance claim "zero truncated calls" rests on the server refusal plus `done_reason`, and is proven by Task1 tests at the boundary: prompts of 24,000–24,576 tokens with the real system prompt, schema and template, and at 32,769 tokens (→ 400).
8. **Resource envelope (Task1).** Measure at the worst case (24,576 in + 4,096 out): `ollama ps` GPU share (must be 100 % GPU), VRAM, host RAM, prompt and generation tok/s, and wall time per call. These set the per-call timeout and the run's wall-clock budget. If the model spills to CPU at the worst case, the input limit is lowered until it does not, and the new value is recorded.
9. Operator setup: the `ornith-32k:9b` Modelfile (`FROM ornith:9b`, `PARAMETER num_ctx 32768`) is in the runbook. The blob digest and the Modelfile hash enter every fingerprint and the release evidence.
10. No cloud fallback. A down endpoint gives a visible, resumable `MODEL_UNAVAILABLE` state.

Owned additions: `lib/custom_provider/endpoints.py`, `lib/text_backends/ollama.py`, `server/story_authoring/script_guard.py`; tests `tests/unit/lib/text_backends/test_ollama.py`, `tests/unit/lib/custom_provider/test_custom_provider_factory.py`, `tests/unit/server/story_authoring/test_script_guard.py`; transport fixtures under `tests/fixtures/ollama/`.

## Change E — durable execution (P1-02, P1-03, P1-04)

1. **Attempt ledger.** Every model call is one attempt row: `RESERVED → DISPATCHED → COMPLETED | FAILED | UNKNOWN`.
   - `RESERVED`: written in a transaction that also reserves budget (step 3) before any HTTP request.
   - `DISPATCHED`: committed immediately before sending.
   - `COMPLETED` / `FAILED`: written with the response or typed error, token counts, `done_reason` and durations.
   - `UNKNOWN`: set on restart for every `DISPATCHED` row without an outcome. Its usage is unknown, so it is charged at its reserved maximum (input estimate + `num_predict`).
2. **Atomic visibility.** The node revision's content is written first, content-addressed by digest; this is immutable and idempotent. Then one database transaction:
   - inserts the revision row;
   - sets the attempt to `COMPLETED`;
   - compare-and-sets the node head (Change D fencing);
   - advances the run checkpoint (`run_id`, `node_id`, `revision_id`, `attempt_id`, `digest`) through the new guarded `task_repo` transition.

   A revision exists for the run only if that transaction committed.
3. **Recovery reconciliation** on start:
   - `DISPATCHED` attempts → `UNKNOWN`;
   - content blobs with no revision row → recorded as orphans, never used, kept for audit;
   - checkpoints are verified against revision rows by `(run_id, node_id, revision_id, attempt_id, digest)`. Any disagreement stops the run as `RECOVERY_INCONSISTENT` with the exact rows, never "just run the model again".

   Resume then continues from the stale or missing nodes (Change D). It never resends silently: the replacement attempt has a new attempt ID and is visible.
4. **`RunBudget`, immutable at run start** and recorded in the run: `calls_max`, `input_tokens_max`, `output_tokens_max`, `wall_clock_max`, `regenerations_max`, plus the per-scene and per-chapter caps from § Size and budget.
   - Each attempt reserves its maximum (input estimate + `num_predict`) **before** dispatch, under a row lock through the existing `budget_guard` reservation path. Completion releases the unused part; an `UNKNOWN` attempt keeps the full charge.
   - Every retry layer — schema repair, span repair, scene regeneration, binding regeneration, chapter-review repair — draws from the same caps. Layers never multiply.
   - Exhausting a cap → `BLOCKED_BUDGET` with the exact cap.
5. **Ledger for `LOCAL`.** The price is 0 minor units in currency `LOCAL`, so there is no billing. It is not free: every attempt still uses GPU time, wall clock and budget. Ledger rows carry token quantities for observability; `LOCAL` rows are excluded from money totals.

Owned: the attempt ledger, checkpoint and budget glue live in `server/story_authoring/runtime.py` (already in the 2026-10-17 file map) over the Change 0 owners. Tests: `tests/integration/server/story_authoring/test_runtime.py` and `test_resume.py` (already owned).

## Size and budget

| Item | Value (operator-editable `StoryLimits` defaults; Task4 fixes them from measured counts and records the evidence) |
|---|---|
| Chapters | 3 |
| Scenes per chapter | 3–5 |
| Scene length | target 600–1,000 Vietnamese syllables; hard maximum 1,400 (about 1,800 tokens, inside `num_predict` 4,096 with the envelope) |
| Story length | 7,000–11,000 syllables |
| Input per call | ≤ 24,576 tokens (lowered if Task1's resource envelope requires it) |
| Output per call | ≤ 4,096 tokens |
| Per-scene attempt cap | 6 model attempts of any kind (draft, schema repair, span repair, regeneration, binding regeneration) |
| Per-chapter review cycles | 2 |
| Run `calls_max` | upper bound = planning (≤ 10) + scenes (≤ 15 × 6) + chapter reviews (≤ 3 × 2 × 4) + manuscript review and packaging (≤ 8) = 132. Task4 sets the default to the measured p95 × 1.2, never above the bound. |
| Run `wall_clock_max` | from Task1's per-call worst-case time × `calls_max` |

A scene over the hard maximum gets one length-normalizing repair (Shenbi S10 role), counted in its cap. A scene contract whose target cannot fit is split at the outline stage, never at drafting time.

## Change W — writer pipeline (unchanged roles)

Roles stay frozen (R2_01 §20, R1.5 §17–§19). Shenbi supplies planning/drafting skills and audits; Novel Studio supplies the workflow; Huohuo supplies the change record, adaptation and the strict local repair loop. The scene is the execution and review unit. Review layers: L1 deterministic, L2 specialist audits, L3 independent critic, L4 Human. Stages:
1. brief → seed;
2. bibles;
3. outline and scene contracts;
4. per scene: compile context → draft → L1 → L2 → bounded repair;
5. per chapter: chapter review (continuity, style) → repair revisions inside scene nodes → seal;
6. manuscript review, ending check, packaging.

Prompt content comes from the donor surfaces in `docs/r2/evidence/R2_STORY_DONOR_BASELINE.json` (S01–S11). Task4 confirms them with n ≥ 10. The **scoring rubric and winning rule are fixed before the benchmark** and committed in the baseline file before any Task4 run:
- deterministic rubric: words, CJK, English code-mixing, trigram repetition, dialogue, truncation, names, ending present, scene-contract coverage;
- blind pairwise L3 judgment with quote-verified reasons;
- winning rule: a surface wins if no invariant fails, its median rubric score is not lower than the donor's, and it is not worse on any blocking criterion.

Owned paths (unchanged from revision 2):
- `server/story_authoring/prompts/{outline,planning,drafting,packaging}.py`, `checks.py`, `audits.py`, `repair.py`;
- their unit tests;
- the donor parity runners and fixtures under `tests/integration/donor_parity/`;
- `docs/r2/evidence/R2_STORY_*_PARITY.json`.

## Change G — quality severity policy (P1-06, P1-07)

| Class | Examples | Handling |
|---|---|---|
| Hard structural | missing chapter or scene, no ending, scene contract not covered | Block. Touchpoint 2 is not offered. |
| Hard integrity | CJK, truncated input/output, binding mismatch, invalid output, donor parity row below `PARITY` without a sponsor exception | Block. Never "local-model limit". |
| Narrative critical | serious character contradiction, plot break, xưng hô matrix violation, named-entity drift | Bounded repair. If still open: offered at touchpoint 2 as an explicit exception the Human must tick; otherwise Approve is disabled. |
| Stylistic | slow pace, unnatural dialogue, repetition below threshold, English code-mixing of a single word | Listed findings; the Human decides. |
| Local-model limitation | prose not refined enough after bounded repair | Recorded; must be accepted by the Human at touchpoint 2 if still open. |

The Approve record stores the manifest digest plus the exact IDs of every open finding and every ticked exception, so one click never silently clears a critical finding. The classifier and thresholds live in `checks.py`/`audits.py`, and are tested per class.

## Change V — video hand-off with integrity (P1-09)

`StoryAuthoringService.send_to_video(scope, manuscript_ref, command_id)` calls `server/tool_runtime.py::upload_source`. It requires:
- run state `COMMITTED` and not withdrawn;
- the exported bytes' digest equal to the manifest's export digest;
- the shared detector re-run on those bytes.

Further rules:
- The file name is a sanitized ASCII slug from the title: no path separators or control characters, length ≤ 80, `.md`. A collision gets a short digest suffix.
- `on_conflict` is explicit and defaults to `fail`.
- `command_id` makes it idempotent: a repeated call returns the first result, and never writes a second source.
- The project must be `source_kind=novel`.
- The existing novel-source pipeline and Gates B–D follow unchanged.

Owned: `server/story_authoring/handoff.py`, `tests/unit/server/story_authoring/test_handoff.py`.

## Verification matrix (added to the task gates)

| Task | Required tests | PASS condition |
|---|---|---|
| Task0 | schema round-trips for every new record; lineage evidence | Every record has a home, or `SCHEMA_GAP`; lineage recorded |
| Task1 | transport fixtures (stop, length, 400 over-context, 200 non-compliant, timeout, cancel, unavailable); boundary prompts 24,000–24,576 and 32,769; adversarial CJK canary n ≥ 20 per schema kind; system-prompt override; resource envelope | Fail closed in every case; no output accepted without proof |
| Task2 | two workers reserve budget concurrently (PostgreSQL); attempt state machine; crash between content write and transaction; crash after `DISPATCHED` | No ceiling exceeded; reconcile to a consistent state or `RECOVERY_INCONSISTENT` |
| Task3 | manifest plan + 3 chapters; crash after chapter 1 and 2, then resume; Canon change between proof and commit; concurrent Approve; stale manifest; Gate A rebind; authority adapter batch | Each decision has the right authority, revision and approval digest; no duplicates; blocked, never wrongly committed |
| Task4 | stale set per change type (brief, bible, outline, contract, scene, chapter, packaging); acyclicity; revision during a running call (late result fenced); restart during chapter 2; donor parity n ≥ 10 | Exact stale sets; chapter 1 not regenerated; parity rows `PARITY`/`IMPROVED` |
| Task5 | withdraw, re-export, duplicate hand-off, Approve disabled with unticked critical exceptions, two-tab Approve | Withdrawn text is never sent; no wrong or duplicate source |
| Task6 | clean live run; separate live restart, revision and discard runs; adverse cases (endpoint down mid-run, kill during a call, a CJK-baiting brief, an over-long brief); 3 variation runs with different ideas and genres | Separate evidence per property, bound to HEAD; every variation run ends at touchpoint 2 or a typed blocked state, with no crash or hang; rates recorded |
| Task7 | deploy from the release tag; staging smoke | Code, model blob digest, Modelfile hash, schema/prompt versions and alembic head match the evidence |

The two hardest cases — concurrent approval with a Canon change, and recovery after a partial commit — run on PostgreSQL with the real authority adapter, not with fixture models alone.

## Acceptance

Live runs, all on the same local GPU host and model, each with its own evidence:

| Run | Task | Evidence |
|---|---|---|
| Transport probe and calibration | Task1 | `R2_STORY_AUTHORING_QUALIFICATION` update |
| Clean acceptance run | Task6 | `docs/r2/evidence/R2_STORY_ACCEPTANCE_RUN.json` |
| Restart, revision, discard, adverse and variation runs | Task6 | `docs/r2/evidence/R2_STORY_RESILIENCE_RUNS.json` |
| Staging smoke | Task7 | `docs/r2/evidence/R2_V2_STAGING_SMOKE.json` |

Criteria:
- All donor parity contracts pass (Decisions, class 2).
- **Clean run:** brief → `COMMITTED` → exported three-chapter manuscript with an ending; exactly two Human actions; zero optional actions.
- **Invariants on the accepted manuscript:** zero CJK by the shared detector on the exported bytes; zero `INPUT_OVER_CONTEXT`/`OUTPUT_TRUNCATED` among stored heads; every attempt row has an outcome.
- Restart during chapter 2 does not regenerate chapter 1. A chapter-2 revision regenerates exactly the Change D stale set. Discard leaves no governance record.
- The quality record classifies every finding per Change G.
- **Human verdict:** the sponsor's Approve, bound to the exact manifest digest and the exact open findings and exceptions, is the quality verdict.
- The video hand-off creates `source/<slug>.md` with the manifest's export digest, and the existing episode-planning step accepts it.
- **Regression:** the affected-domain static gates. Related tests only, never the full suite unless asked. Explicitly included:
  - the Change 0 test list;
  - `tests/integration/server/story_authoring/` (runtime, narrative, resume);
  - `tests/unit/server/story_authoring/`;
  - PostgreSQL integration tests for `r2/narrative_plan` and `r2/narrative_lifecycle` touched by Task3;
  - `tests/unit/lib/custom_provider/`, `tests/unit/lib/text_backends/`;
  - the gates router tests (Gate A rebind);
  - the router and auth tests for story authoring.

## Release (Task7)

1. **Pre-merge checks**, recorded in evidence:
   - the release branch `release/r2-v2-story` has `r2-v2/main` as an ancestor;
   - `git diff r2-v2/main..release` contains only story-authoring paths and their docs, and no `scripts/r2/verify_m9_*`;
   - the worktree is clean;
   - the HEAD equals the accepted commit of the acceptance evidence.
2. Merge into `r2-v2/main`; annotate tag `r2-v2.0.0` on that exact commit (ADR-0089 §7). The release evidence records the tag object, the commit, the model blob digest, the Modelfile hash, the prompt/schema version table and the alembic head. Push only with Human confirmation.
3. Back up `~/arcreel-v2-staging` with `docs/r2/runbooks/m7-backup-restore.md`. Deploy the tag, run `alembic upgrade head` (expected: no new revision unless Task0 found a `SCHEMA_GAP` and the Human approved a migration), register the Ollama provider with the `ollama-chat` endpoint and the model, and run the staging smoke.
4. Write `docs/r2/runbooks/story-authoring.md`: Modelfile and setup, the 2 + 3 touchpoints and the optional actions, revision, resume, recovery states, limits and budget, the severity policy, model swap to cloud later (with its own qualification), and backup coverage.
5. Production activation only on explicit Human confirmation at that time.

## Execution

Main agent, inline and serial: Task0 → Task1 → Task2 → Task3 (hard gate) → Task4 → Task5 → Task6 → Task7. One progress report per task gate; one final independent review (Codex) and at most one repair.
