# R2 V2 story release — amendment to the idea-to-story plan

Status: DRAFT_FOR_HUMAN_REVIEW, revision 5 (consistency amendment). Supersedes revision 4 (`9314799c`), revision 3 (`92d7eef9`), revision 2 (`04f2e2af`) and revision 1 (`e833e27a`). Amends `docs/superpowers/plans/2026-10-17-r2-idea-to-story-authoring.md` (approved 2026-10-17); everything in that plan stays in force unless this document changes it.

Research basis: `docs/research/2026-10-18-r2-v2-story-release-research.md`, through the addendum "revision 5 probes". Revision 5 closes the third review (P0-01…04, P1-01…06, P2-01…04). It changes only contracts, state machines and acceptance gates. Revision 4 answered the second review of 2026-10-18 (P0-01…05, P1-01…10, P2) in this order: data model, governance commit protocol, provider qualification, durable execution, acceptance and release. The overall architecture, scope, owners, donors, the two touchpoints, the six stages and the task order are unchanged.

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
   - Repository root `/home/anhtuan/content-production-os`, checked at commit `dbaf93a6` on 2026-10-18T18:50+07:00. `git worktree list --porcelain` lists 24 worktrees, none named `r2-v2-native-narrative`. No ref or commit message mentions "Web Writer" or `native-narrative`. A filesystem search of depth 5 from `/` finds no such directory. The only other Git repository in the home directory, `/home/anhtuan/ArcReel`, has one worktree (`main`).
   - Unknown: an earlier log reported creating that worktree. It may come from another repository, snapshot or machine, or the worktree may have been removed. Task0 asks for the log's repository path if it is still relevant. Branch names are never used as evidence.

   Task0 records this as evidence: root, commit, timestamp, the full `--porcelain` output and the search commands.
4. **Release branch from the start (P1-05).** Task0 creates `release/r2-v2-story` from `r2-v2/main` and cherry-picks only the story-authoring commits. All implementation (Task1–Task6) happens on that branch, so the commit Task6 accepts is the release HEAD itself. M9 files and any rolled-back code cannot enter V2. Release rules are in § Release.

## Change D — data model: inputs, generated nodes, revision intents (P0-01, P1-05, P1-08)

Three kinds of object, never mixed:

| Kind | Nodes | Who creates a revision |
|---|---|---|
| **Brief** (authoritative, Gate A) | `brief` = idea, genre, language, limits, model selection, scope | Human only |
| **Generated nodes** | Planning: `seed`, `story_bible`, `style_bible`, `outline`, `scene_contract[c,s]`. Prose: `scene_draft[c,s]`. Checks: `chapter_review[c]`, `manuscript_review`. Output: `packaging` | The run (model call or deterministic step) |
| **Revision intents** | `intent` (target node, Human note, Human principal, created_at) | Human only |

**Edges** (data dependency; "A → B" means B is produced from A):

- `brief` → `seed` → `story_bible`, `style_bible` → `outline` → `scene_contract[c,s]`.
- `scene_contract[c,s]`, `story_bible`, `style_bible` and the compiled context pack of `[c,s]` → `scene_draft[c,s]`. The context pack is compiled from the earlier scene heads in story order, so an earlier scene affects `[c,s]` only when it changes that pack's `content_hash`. A span repair that leaves the compiled context unchanged stales nothing downstream.
- All `scene_draft[c,*]` → `chapter_review[c]`.
- All `chapter_review[*]` and all `scene_draft` → `manuscript_review` → `packaging`.
- An `intent` targeting node X → X. Intents have no inputs; they are sources only.

**Intent lifecycle (P2-03).**
- Intents are stored rows: `intent_id`, target node, note, Human principal, `created_at`, status `ACTIVE | CONSUMED | SUPERSEDED | EXPIRED`.
- The revision that applies an intent records it in its fingerprint and marks it `CONSUMED`.
- A newer intent on the same node marks the older one `SUPERSEDED`.
- Discard, abort or `COMMITTED` mark every remaining intent `EXPIRED`.
- An intent created after a manifest was built makes that manifest stale.

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

The edge table is static code. A unit test runs a Kahn sort on the **expanded** graph: static edges plus `intent → target` edges, over randomized intent sets for every node kind.

**Late results (P1-08, third-review P0-04).** Each node has a `generation_epoch` that increases monotonically on every head change, stale marking, intent or run-state change affecting it. Every attempt records, at dispatch:
- its input `fingerprint`;
- `expected_head_revision_id`;
- `generation_epoch`.

A result is promoted to head only in one transaction that locks the node row and requires all of:

```
node.required_fingerprint  == attempt.fingerprint
node.head_revision_id      == attempt.expected_head_revision_id
node.generation_epoch      == attempt.generation_epoch
run.state                  in {RUNNING}
```

Otherwise the result is stored as `STALE_RESULT`; the node head and epoch are unchanged. Two repair attempts with the same fingerprint cannot both win: the first promotion bumps the epoch, so the second fails the check. A revision request during a running call does not cancel the call; the late result is simply fenced.

Owned: `server/story_authoring/pipeline.py`, `tests/unit/server/story_authoring/test_pipeline.py`. Tests:
- acyclicity of the expanded graph;
- for each change type (brief, bible, outline, contract, scene, chapter, packaging), the exact stale set;
- topological order;
- a span repair with unchanged context stales nothing.

PostgreSQL fencing tests in `tests/integration/server/story_authoring/test_runtime.py`:
- two same-fingerprint attempts completing in reverse order: exactly one promoted;
- a result arriving after discard, and after abort: `STALE_RESULT`.

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
5. **`ManuscriptCommitManifest`.** An immutable host artifact built when the run reaches touchpoint 2. The digest covers exactly one canonical payload (RFC 8785 JSON canonicalization):

   ```
   manifest_payload = {
     schema: "story-commit-manifest-v1",
     run_id, brief_digest, gate_a_decision_id,
     predecessor_manifest_digest | null,
     committed_prefix: [ {step_index, step_kind, receipt_id, receipt_digest} ],   // empty for a first manifest
     plan:     {plan_revision_id, content_hash, expected_version} | null,         // null when already in the prefix
     chapters: [ {chapter, scene_revisions:[{node, revision_id, digest}], change_set_ids,
                  expected_canon_base_version, canon_commit_approval_digest,
                  expected_decision_heads} ],                                     // the uncommitted suffix only
     findings_open: [finding_id], exceptions_offered: [finding_id],
     export_digest
   }
   manifest_digest = sha256(canonical(manifest_payload))
   step_key(k)     = sha256("story-commit-v1" ‖ manifest_digest ‖ k)
   ```

   - Step keys are derived from the digest. They are listed in an audit view, never inside the payload.
   - `export_digest` is the sha256 of the Markdown bytes rendered deterministically **before** commit, from the scene heads, the chapter order and `packaging`. The renderer is versioned, and its version is part of `packaging`'s fingerprint.
   - Revision and receipt IDs created after approval are never written into the `.md` bytes. They live in a separate export record linked by digest.
6. **Touchpoint 2.** The Human sees the manuscript, findings and outline, all bound to one manifest digest, and chooses **Approve**, **Request revision** or **Discard**. Approve is one authenticated Human request through the existing interactive-auth dependency, bound to the manifest digest and to the list of exceptions the Human ticked. It authorizes exactly the decisions listed in the manifest and nothing else; each decision record carries the Human principal and the manifest digest. Task3 proves that the real Showrunner authority adapter accepts decisions created in one authenticated Human request. If an authority requires one interaction per decision, Task3 returns the exact incompatibility before Task4.
7. **Commit execution**, through the existing owners only (`NarrativePlanService.commit_revision`, `NarrativeAcceptanceService.decide_revision` → `review_change_set` → `admit_canon_handoff`); no parallel authority. State machine:
   - `APPROVING` → step k (plan, then per chapter the three decisions) → `PARTIALLY_COMMITTED(k)` after each step → `COMMITTED` after a read-back verifies every receipt against the manifest.
   - Before each step: check the current versions and heads the manifest expects (optimistic concurrency, using the services' existing `expected_version`/`expected_latest_decision_id` checks), recompile that chapter's context from the real committed state, and compare with the manifest.
   - Any difference or refusal → `COMMIT_BLOCKED(step, reason)`. No further decision is sent.
   - Every step uses its idempotency key. The existing exact-retry paths (`get_version_by_revision`, admission retry resolution) return the original receipt for a repeated step.
   - **Per-transition idempotency (third-review P1-03).** A step runs in this order:
     1. look up an existing receipt for its key and expected subject: plan version by `plan_revision_id`, decision by the kernel's command identity, admission by the admission retry resolution;
     2. if a receipt is found, verify that it matches the manifest and record it;
     3. otherwise send the decision;
     4. then record the receipt in the run.

     A crash between the authority commit and the run record is closed by step 1 on resume, never by sending again. Task3 proves, for each of the four call kinds, that this lookup exists and returns the original receipt. If one lacks it, Task3 stops with that exact incompatibility.
   - **Resume** after a crash re-reads receipts, skips completed steps by key, and continues from the first incomplete step.
   - **Successor manifest after `COMMIT_BLOCKED` (frozen committed prefix).** When a concurrent Canon change blocks step k, the steps before k stay committed and are never sent again.
     1. The affected scenes become stale and are regenerated against the new committed state.
     2. A successor manifest M2 is built with `predecessor_manifest_digest = M1`. Its `committed_prefix` is M1's exact receipts, and only the uncommitted suffix may differ.
     3. Before M2 is offered, every prefix receipt is re-verified: it is still the effective decision, and the plan version is still as committed. If any prefix receipt is no longer effective, M2 cannot be built; the run offers only abort (below), and any later correction goes through the normal R2 revision lifecycle as a new append-only revision.
     4. M2 needs its own Approve (an optional action; not counted). M1's approval is never reused for M2's suffix: the keys differ, and the approval binds M2's digest.
     5. Task3 proves `PARTIALLY_COMMITTED(M1)` → `COMMITTED(M2)` on PostgreSQL: no duplicate decision, no reuse of M1's approval, every chapter consistent.
   - Export and video hand-off are allowed only in `COMMITTED`.
8. **Run lifecycle and who may end it (third-review P0-03).** Every action below is a Human action through the existing interactive-auth dependency, by a principal holding the project's authoring grant — the same principal class that may Approve. An agent or a run never performs any of them.

   | State | Allowed Human actions | Result |
   |---|---|---|
   | `RUNNING`, `AWAITING_GATE_A`, `BLOCKED_*`, `READY_FOR_APPROVAL` | revise, retry (blocked), **discard** | `DISCARDED` (terminal): no governance record, export or hand-off; in-flight attempts fenced |
   | `APPROVING` | none (the sequence is running) | — |
   | `PARTIALLY_COMMITTED`, `COMMIT_BLOCKED` | resume, approve successor manifest, **abort** | `ABORTED_PARTIAL` (terminal) |
   | `COMMITTED` | export, send to video, **withdraw** | `WITHDRAWN` (terminal for hand-off and export) |

   - `ABORTED_PARTIAL` keeps every committed receipt unchanged; R2 records are append-only, so the committed plan and chapters remain real R2 state. It blocks export and hand-off and marks the run as not resumable. The UI states exactly which chapters were committed. Further changes go only through the normal R2 lifecycle.
   - `WITHDRAWN` blocks `send_to_video` and further export, and labels the export superseded.
   - **Video after withdrawal (P2-04).** A source already handed to video stays, and video jobs already enqueued keep running under their existing owners. Withdrawal does not cancel them. The UI says so, and points to the existing video task cancellation and to Gate B, which the Human simply does not approve. There is no parallel cancellation mechanism. Removing the source uses the existing source deletion.

**Task3 is a hard gate.** Task4 does not start until Task3 passes PostgreSQL integration tests with the real authority adapter:
- the manifest with plan plus three chapters;
- a crash after each of the four transition kinds (plan commit; per chapter `decide_revision`, `review_change_set`, `admit_canon_handoff`), and between an authority commit and the run's receipt record, then resume with no duplicate decision;
- `PARTIALLY_COMMITTED(M1)` → successor M2 → `COMMITTED(M2)`;
- abort in `PARTIALLY_COMMITTED` → `ABORTED_PARTIAL`, receipts intact, export refused;
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
| `POST /api/tokenize` → 404. | No tokenizer endpoint. |
| The same request sent 3 times reports `prompt_eval_count` 1,478 each time; only the prefill time drops (1.33 s → 0.07 s). | The reported count is exact even with a cache hit; revision 4 wrongly said a cache could lower it. A `num_predict: 1` probe of the exact request gives the server's own exact count, and the real call then reuses the cache. |
| `shift` absent or `false`, `num_ctx` 256: generation stops at the context end with `done: true`, `done_reason: "length"` (prompt 39 + output 217 = 256). | No silent context shift was observed. The field may be ignored by 0.32.6; the guarantee rests on `done_reason`. |

Decisions:

1. **New endpoint `ollama-chat`** in the existing custom-provider registry: `lib/custom_provider/endpoints.py` `EndpointSpec`, plus a backend `lib/text_backends/ollama.py`. Story calls use only this endpoint. `openai_chat` stays as it is for other uses and for cloud later. Before the change, follow `docs/api-docs/AGENTS.md` and `.claude/rules/provider-capabilities.md`.
2. **Exact request** (`POST {base}/api/chat`):

   ```json
   {"model": "<tag>", "stream": false, "think": false, "truncate": false, "shift": false,
    "messages": [{"role": "system", "content": "<stage system prompt>"}, {"role": "user", "content": "<rendered>"}],
    "format": <JSON schema>,
    "options": {"num_ctx": 32768, "num_predict": <limit>, "temperature": <t>, "top_p": <p>, "top_k": <k>,
                "presence_penalty": <pp>, "seed": <seed>},
    "keep_alive": "<operator setting>"}
   ```

   - The response fields used are `done`, `message.content`, `done_reason`, `prompt_eval_count` and `eval_count`.
   - **Acceptance of a response (third-review P1-04)** requires all of: HTTP 200; `done == true`; `done_reason == "stop"`; valid JSON matching the schema; the shared detector clean; and every L1 completeness check passing (closing punctuation, minimum length, scene-contract coverage, no meta text). `stop` is necessary, not sufficient.
   - No SDK retry, no fallback. One HTTP request is one attempt in the attempt ledger.
   - Task1 verifies that `options.num_ctx` equal to the tag value does not reload the model.
3. **Structured calls:** `format` is the Pydantic schema. **Prose calls** use the envelope `{"type":"object","properties":{"text":{"type":"string","minLength":1,"pattern":"<NO_CJK>"}},"required":["text"],"additionalProperties":false}`. The result is unwrapped by `json.loads`, validated with the Pydantic model, then checked by the shared detector. The unwrapped text and the raw envelope digest are stored.
4. **HTTP 200 but non-compliant** (invalid JSON, a missing field, a schema or pattern violation, or a detector hit): typed `OUTPUT_INVALID`, never stored as a head. One error-feedback repair attempt follows, counted in the budget.
5. **Grammar ignored or unsupported:** Task1 runs an adversarial canary (the prompt asks for CJK) at n ≥ 20 for every schema kind. Any CJK that passes the grammar means the provider is **not qualified**, and story runs refuse it with `PROVIDER_NOT_QUALIFIED`. A provider without grammar support (cloud later) needs its own qualification; it is never assumed.
6. **Shared CJK detector** (`server/story_authoring/script_guard.py`, one module imported by both runtime validation and acceptance). Its range table is generated from vendored Unicode data files — `Scripts.txt` and `Blocks.txt` at one pinned Unicode version, stored with their sha256 under `server/story_authoring/data/unicode/`. It does not depend on the interpreter's `unicodedata` version (P2-02). The table covers:
   - scripts Han (including Extensions A–H and compatibility ideographs), Hiragana, Katakana, Hangul, Bopomofo;
   - CJK Symbols and Punctuation, Halfwidth and Fullwidth Forms, CJK Compatibility Forms, Kangxi and CJK radicals, Ideographic Description characters.

   Unit tests:
   - verify the vendored files' checksums;
   - check that the generated table equals the committed table;
   - test boundary code points of every extension block (Han Extensions A–I as present in the pinned version, the compatibility ideographs and supplement, Hangul Jamo Extended, Kana supplements).

   It applies to every model output, every scene head, the chapter assembly, title, blurb, the manuscript and the exported `.md` bytes; the last check runs immediately before export and again in `send_to_video`. The grammar pattern carries the BMP ranges; Task1 tests whether astral ranges work in the grammar. The detector covers all ranges regardless.
7. **Token quantities and truncation (third-review P1-01).** Four quantities are kept apart:

   | Quantity | Source | Use |
   |---|---|---|
   | `estimated_input_tokens` | `utf8_bytes / 3.0` | stage planning only; never a limit or proof |
   | `counted_input_tokens` | `prompt_eval_count` of a count probe: the exact request with `num_predict: 1`, sent first | the exact pre-dispatch count; enforces the `StoryLimits` input limit (24,576) and the reservation |
   | `actual_input_tokens` | `prompt_eval_count` of the real call | must equal `counted_input_tokens`; a difference → `OUTPUT_INVALID` |
   | `server_context_limit` | `num_ctx` (32,768) | enforced by the server with `truncate: false` → `INPUT_OVER_CONTEXT` with the exact count |

   - The count probe is an attempt of kind `COUNT` in the ledger, with its own `count_calls_max`. Its prefill is cached for the real call.
   - Task1 proves `counted == actual` on n ≥ 20 requests, including structured `format` calls.
   - With `counted_input_tokens` exact and output bounded by `num_predict` (server-enforced), the reservation `counted_input_tokens + num_predict` is a true upper bound, so the token ceilings are hard limits.
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
   - `UNKNOWN`: set on restart for every `DISPATCHED` row without an outcome. Its usage is unknown, so it is charged at its reserved maximum (step 4).
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
   - Each generate attempt reserves `counted_input_tokens + num_predict` **before** dispatch, under a row lock through the existing `budget_guard` reservation path; a count probe reserves its byte upper bound (UTF-8 bytes + template tokens; byte-level BPE emits at least one byte per token) + 1. Completion releases the unused part; an `UNKNOWN` attempt keeps the full charge.
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

**Length allocation (P2-01).**
- The outline validator (L1, deterministic) requires 9–15 scenes in total, each scene target within 600–1,000 syllables, and the sum of targets within 7,000–11,000. A failing outline gets one repair attempt, then `BLOCKED_QUALITY` (hard structural).
- At the manuscript stage, a total below 6,000 or above 12,500 syllables is hard structural. A total inside that range but outside 7,000–11,000 is a stylistic finding.
- A scene over the hard maximum gets one length-normalizing repair (Shenbi S10 role), counted in its cap. A scene contract whose target cannot fit is split at the outline stage, never at drafting time.

## Change W — writer pipeline (unchanged roles)

Roles stay frozen (R2_01 §20, R1.5 §17–§19). Shenbi supplies planning/drafting skills and audits; Novel Studio supplies the workflow; Huohuo supplies the change record, adaptation and the strict local repair loop. The scene is the execution and review unit. Review layers: L1 deterministic, L2 specialist audits, L3 independent critic, L4 Human. Stages:
1. brief → seed;
2. bibles;
3. outline and scene contracts;
4. per scene: compile context → draft → L1 → L2 → bounded repair;
5. per chapter: the chapter loop below;
6. manuscript review, ending check, packaging.

**Chapter loop (third-review P1-02).** States: `REVIEWING(k)` → `REPAIRING` → `REFRESHING` → `REVIEWING(k+1)` …, ending in `SEALED`, `SEALED_WITH_FINDINGS` or `BLOCKED_QUALITY`.
- `REPAIRING`: span repairs on the scenes the review names.
- `REFRESHING`: recompile the context packs of the later scenes in the chapter. Only scenes whose pack `content_hash` changed are stale and regenerated (Change D).
- `k` ≤ 2. All repairs and regenerations draw from the per-scene caps.

A chapter can be sealed only if all of these hold:
- no stale node in the chapter;
- no hard structural or hard integrity finding;
- the last review ran on the current heads.

With open narrative-critical or stylistic findings, the state is `SEALED_WITH_FINDINGS`; they go to touchpoint 2 under Change G. After cycle 2 with any hard finding or stale node, or with a cap exhausted, the state is `BLOCKED_QUALITY` or `BLOCKED_BUDGET`, and touchpoint 2 is not offered. Chapter `c+1` starts only after chapter `c` is sealed.

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
| Task1 | transport fixtures (stop, length, `done: false`, 400 over-context, 200 non-compliant, 200 `stop` with incomplete content, timeout, cancel, unavailable); count probe `counted == actual` n ≥ 20; boundary prompts 24,000–24,576 and 32,769; generation at context end with `shift: false`; adversarial CJK canary n ≥ 20 per schema kind; system-prompt override; resource envelope | Fail closed in every case; no output accepted without proof |
| Task2 | two workers reserve budget concurrently (PostgreSQL); attempt state machine; crash between content write and transaction; crash after `DISPATCHED`; same-fingerprint reverse-order completion; result after discard/abort | No ceiling exceeded; exactly one promotion; reconcile to a consistent state or `RECOVERY_INCONSISTENT` |
| Task3 | manifest canonical payload and derived keys; plan + 3 chapters; crash after each transition kind and between authority commit and run record; Canon change between proof and commit; successor manifest M1 → M2; abort → `ABORTED_PARTIAL`; concurrent Approve; stale manifest; Gate A rebind; authority adapter batch | Each decision has the right authority, revision and approval digest; no duplicates; no approval reused across manifests; blocked, never wrongly committed |
| Task4 | stale set per change type (brief, bible, outline, contract, scene, chapter, packaging); expanded-graph acyclicity; revision during a running call (late result fenced); chapter loop to `SEALED`, `SEALED_WITH_FINDINGS` and `BLOCKED_QUALITY`; outline length allocation; restart during chapter 2; donor parity n ≥ 10 | Exact stale sets; no seal with stale nodes or hard findings; chapter 1 not regenerated; parity rows `PARITY`/`IMPROVED` |
| Task5 | withdraw, re-export, duplicate hand-off, Approve disabled with unticked critical exceptions, two-tab Approve | Withdrawn text is never sent; no wrong or duplicate source |
| Task6 | clean live run; separate live restart, revision and discard runs; adverse cases (endpoint down mid-run, kill during a call, a CJK-baiting brief, an over-long brief); 3 variation runs with different ideas and genres | Two separate passes, both required. **Safety pass:** every run (adverse and variation) ends at touchpoint 2 or a typed blocked state, with no invariant breach, crash or hang. **Completion pass:** at least 2 of the 3 variation runs reach touchpoint 2 with no hard finding, and reach `COMMITTED` after the sponsor's decision. Completion rate, blocking causes and latency per stage are recorded as observations, never as a long-run reliability estimate. Evidence is separate per property and bound to HEAD. |
| Task7 | fast-forward check; tag on the accepted commit; deploy from the tag; staging smoke | Tagged commit == accepted commit; code, model blob digest, Modelfile hash, schema/prompt versions and alembic head match the evidence |

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
   - `release/r2-v2-story` has the current `r2-v2/main` as an ancestor;
   - `git diff r2-v2/main..release` contains only story-authoring paths and their docs, and no `scripts/r2/verify_m9_*`;
   - the worktree is clean;
   - the release HEAD equals the commit named in `R2_STORY_ACCEPTANCE_RUN.json`.
2. **Fast-forward only.** `git merge --ff-only release/r2-v2-story` into `r2-v2/main`, so the accepted commit becomes `r2-v2/main` unchanged. Annotate tag `r2-v2.0.0` on that exact commit (ADR-0089 §7).
   - If `r2-v2/main` moved after acceptance, a fast-forward is impossible. The release branch is rebased, and Task6's acceptance checks run again on the new commit with new evidence before any tag. A merge commit is never tagged without its own qualification.
   - The release evidence records the tag object, the commit, the model blob digest, the Modelfile hash, the prompt/schema version table and the alembic head.
   - Push only with Human confirmation.
3. Back up `~/arcreel-v2-staging` with `docs/r2/runbooks/m7-backup-restore.md`. Deploy the tag, run `alembic upgrade head` (expected: no new revision unless Task0 found a `SCHEMA_GAP` and the Human approved a migration), register the Ollama provider with the `ollama-chat` endpoint and the model, and run the staging smoke.
4. Write `docs/r2/runbooks/story-authoring.md`: Modelfile and setup, the 2 + 3 touchpoints and the optional actions, revision, resume, recovery states, limits and budget, the severity policy, model swap to cloud later (with its own qualification), and backup coverage.
5. Production activation only on explicit Human confirmation at that time.

## Execution

Main agent, inline and serial: Task0 → Task1 → Task2 → Task3 (hard gate) → Task4 → Task5 → Task6 → Task7. One progress report per task gate; one final independent review (Codex) and at most one repair.
