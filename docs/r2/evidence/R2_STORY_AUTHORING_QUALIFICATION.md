# R2 story-authoring Task0 qualification

Status: **DESIGN_GAP — TEXT_EXECUTION_CUSTODY_GAP**. This is not a provider failure, test-suite failure, authoring implementation or production acceptance.

## Authority and immutable baseline

Human approved the written spec85a2611ccca830f095b16d7abe1b88301e8bce7b, then confirmed plan4337ffefcafedc6d77bda657ea1de661fcebbe2a and Native inline execution on2026-10-17. Those approvals remain received. Do not ask for the same spec/plan approval again.

Worktree `/home/anhtuan/content-production-os/.worktrees/r2-story-authoring`, branch `design/r2-story-authoring`, source inspected at4337ffefcafedc6d77bda657ea1de661fcebbe2a. Its product code matches39b9c5dab5d0fd56cf52bf65e95355437cb1023b. M9-B cleanbba1bd9622eb4423160c771f4dde2dc927b58f0a preserved. No product code, dependencies, credentials, provider activation or production data changed.

## Native probe and observed results

Command actually run with exit0:

```bash
PYTHONPATH="$PWD" /home/anhtuan/content-production-os/.worktrees/r2-v2-main/.venv/bin/python .superpowers/sdd/2026-10-17-r2-idea-to-story-authoring/qualification_probe.py
```

The retained script creates a unique SQLite file in this plan's ignored workspace, registers existing metadata and exercises the real TaskRepository. No provider/backend is instantiated. It does not use the configured application database. SQLite results are not PostgreSQL concurrency proof.

```json
{
  "text_enqueue_exact_replay": "PASS",
  "changed_command_digest_refused": "ConflictError",
  "task_count_after_replay": 1,
  "existing_text_checkpoint_admission": "REFUSED_BY_VIDEO_ONLY_GUARD",
  "failed_checkpoint_writes": 0,
  "text_capability_profile": "ProviderCapabilityNotFoundError",
  "narrative-outline": "ADDITIVE_KIND_REQUIRED",
  "narrative-manuscript": "ADDITIVE_KIND_REQUIRED",
  "provider_calls": 0,
  "production_database_used": false
}
```

Probe SHA256: `b56b1b210cb331c8edc0379f9c7b2216caf51d4d6f8bda112e67feb72c762939`.
Output JSON SHA256: `7c8972677a95c4485d769aec488d361cc33155b5333caca843df0989a6d87098`.
Both files and the disposable probe DB are retained in `.superpowers/sdd/2026-10-17-r2-idea-to-story-authoring/`; do not clean that directory. Material source hashes are in `source-hashes.json` there.

## Confirmed source findings

1. **Reusable task identity, positive native proof.** `TaskRepository.enqueue` (`lib/db/repositories/task_repo.py:191`) accepts a string task_type, text media and actor-scoped command receipt. The probe inserted one `story_authoring_chapter` task; exact retry returned the same task and changed digest raised ConflictError. No second runtime/queue is necessary for enqueue.
2. **Missing compatible submit checkpoint, confirmed native refusal.** `persist_execution_checkpoint` (`lib/db/repositories/task_repo.py:1109`) requires a running video/reference_video task with empty checkpoint/job fields. A running authoring text task was refused, leaving zero checkpoint writes. Calling this API with an invented video type/job ID would violate its authority. The existing Task column can store a future authoring envelope, but an existing column is not a qualified text-submit API.
3. **No recorded synchronous story capability profile.** The registry inventory has asynchronous video families, a spatial profile and local FFmpeg format projection. The exact story-text profile lookup in the probe raised ProviderCapabilityNotFoundError. This does not mean every model API is unusable; it means M7 profile qualification cannot be inferred from the asynchronous inventory. No registry entry was created or marked qualified.
4. **Budget ceiling is not forwarded, source-confirmed.** `Ledger.record` builds PricingParams with call/model/media fields (`lib/ledger.py:151`), omitting input_tokens/output_tokens. PricingParams supports those fields (`lib/pricing/strategies.py:39`), and per-token pricing uses them (`:61`). `reserve_for_call` returns None in DEV (`lib/budget_guard.py:98`). Consequently the existing call surface does not prove the approved per-story input/output/cost ceiling, especially in a development trial. No actual monetary overspend is claimed or reproduced.
5. **Expected additive artifact gap.** The baseline ArtifactKind rejects narrative-outline and narrative-manuscript. The approved Task2 already owns this extension. Those missing enum values alone are not an additional scope blocker.
6. **Authority source is reusable, host composition remains to build.** GrantScopeV1 binds user_id/project_name/principal and checks HUMAN_SHOWRUNNER in `r2/governance/grant_transition.py`. NarrativeAcceptanceService requires a real authority adapter and never supplies a permissive default (`r2/narrative_lifecycle/acceptance.py:352`). This investigation neither issued a grant nor established current operator custody. Tests/factories must never stand in for production bootstrap.
7. **Provider qualification still pending.** The shared text result does not retain finish_reason and OpenAI native calls have their own bounded legacy retries. Task1 must qualify the opt-in single-call/truncation path. No Claude/OpenAI/local live call or authoring story was generated.

Graph: Tier2 predecessor project r2-v2-main, generation2026-10-15T01:19:44Z, fast/best-effort. Coverage checked every material source path; excluded docs/integration/profile ranges were read directly in the investigation. This is not an index of the new worktree or an exhaustive runtime audit.

## Concrete minimal amendment for review

The approved file map omits the owners needed to close findings2 and4. Task0 explicitly says: “Otherwise record TEXT_EXECUTION_CUSTODY_GAP and stop before runtime code.” The plan also disallows silently expanding its exact owner map. Stop here rather than writing a private competing submit or budget authority in server/story_authoring.

Proposed additional owned paths, beyond the existing approved map:

- `lib/db/repositories/task_repo.py`: add a dedicated guarded authoring checkpoint transition. Keep the video method/guards unchanged. Bind owner/project/task/request digest, expected task status and once-only admission; reject stale/cross-scope/concurrent submit. Model I/O remains outside the transaction. A stored response can be finalized from retained bytes; ambiguous submit never becomes automatic resend.
- `lib/ledger.py`: accept explicit bounded text input/output reservation quantities from the authoring path, passing them into existing PricingParams. Existing callers retain compatible defaults. No second ledger or pricing store.
- `lib/budget_guard.py`: use the existing budget owner to enforce the explicitly authorized authoring run/step ceiling even when testing in DEV; ordinary legacy DEV behavior is unchanged. Unknown/missing pricing refuses a paid authoring request. Local operation still enforces token/call ceilings and never falls back to cloud.
- Existing regression files `tests/integration/lib/db/repositories/test_task_repo.py`, `test_task_command_idempotency.py`, `tests/integration/lib/test_budget_guard.py` and `tests/unit/lib/test_text_generator.py`, plus the already-owned authoring tests: verify cross-scope/wrong-status/replay/CAS, uncertain outcome, budget exhaustion and legacy behavior. PostgreSQL interleavings are required for database claims.

This amendment introduces no new database/table, governance authority, frozen R2 contract or capability-profile change. Prefer host task checkpoints plus existing paid admission for synchronous text; if that implementation proves a new M7 public contract/profile necessary, return the exact incompatibility before changing it. No production route is enabled by this proposal.

After the additional owner-map/submit-budget design is accepted, resume Task0 at these two gaps and continue the previously approved Native plan. No new spec reapproval, task-by-task review or extra final-review pass is requested.

---

## V2 Task0 closure (2026-10-18, amendment revision 5.1)

Status: **READY_WITHIN_OWNED_MAP**, with two recorded design facts for Task2 and Task3 (below). This is evidence, not runtime authority, and not acceptance of any later task.

Authority: the Human approved amendment revision 5.1 with conditions on 2026-10-18 ("đồng ý duyệt có điều kiện, bắt đầu Task0"). Only Task0–Task3 are open. That approval includes the owner-map additions proposed above (`task_repo.py`, `ledger.py`, `budget_guard.py` and their tests). **`TEXT_EXECUTION_CUSTODY_GAP` is closed as a design gap**; the guarded text checkpoint transition and the budget changes are built in Task1/Task2.

### Release branch and lineage (Change 0 §3–4)

- The worktree `/home/anhtuan/content-production-os/.worktrees/r2-v2-story-release` holds branch `release/r2-v2-story`, created from `r2-v2/main` `23cf146a`. The 19 story-authoring commits were cherry-picked without conflict; the last is the approval record. All further work happens on this branch.
- `git diff --name-only r2-v2/main..HEAD` lists only the six story documents. `scripts/r2/verify_m9_*` are absent.
- The full evidence is in `docs/r2/evidence/R2_V2_STORY_LINEAGE_2026-10-18.txt` (sha256 `161acde4…7a4fb`): root, commits, ancestry checks, refs/log/filesystem searches, and `git worktree list --porcelain` (25 worktrees, including the new release worktree). No `r2-v2-native-narrative` worktree or "Web Writer" ref exists. The only `native` ref is the unrelated `upstream/research/comfyui-native-api`.

### Schema sufficiency (Change 0 §2)

Probe: `.superpowers/sdd/2026-10-18-r2-v2-story-release/task0_schema_probe.py` (sha256 `8cdb858f…9ead`), output `task0_schema_probe.out.json` (sha256 `14bbe267…5bb0`). Both are retained in the ignored workspace; do not clean it.

- It ran against a disposable `postgres:16` container `arcreel-story-test-pg` (127.0.0.1:55480, tmpfs), migrated by `alembic upgrade head` to `918c4a0e0001`. It never touched staging or the V1 trial, and made 0 provider calls.
- Command: `DATABASE_URL='postgresql+asyncpg://arcreel:…@127.0.0.1:55480/arcreel_story_test' uv run python .superpowers/sdd/2026-10-18-r2-v2-story-release/task0_schema_probe.py`, exit 0.

| Record (amendment) | Existing home | Probe result |
|---|---|---|
| Run state: node heads + `generation_epoch`, revision index, intents, attempt ledger, budget counters, checkpoint cursor | `tasks.execution_checkpoint_json` of one `story_authoring_run` task, changed only by the guarded transition (row lock + `state_version` compare-and-set) that Task1/Task2 add to `task_repo.py` | 169,470-byte worst case (15 scenes, 264 attempts) round-trips equal. Two concurrent CAS writers: exactly 1 winner, final version 2. Enqueue replay returns the same task. |
| Immutable `RunBudget` | `tasks.payload_json` of the run task | Written by enqueue |
| Per-attempt usage (observability) | `api_calls` (Ledger): `currency` `LOCAL`, `input_tokens`/`output_tokens`, free-text `status`, `last_provider_response` JSON | Row with `LOCAL`, 9,000 input tokens, status `DISPATCHED` → `UNKNOWN` round-trips |
| Revision content, `ManuscriptCommitManifest`, quality record, export record | Project artifact files under the projects root, registered in the artifact manifest | `ArtifactKind` has no narrative kinds yet (expected; the additive kinds are owned by Task2 `lib/artifact_manifest.py`). The backup runbook covers every regular file under the projects root plus PostgreSQL. |
| Gate A decision | existing `gates` tables through `POST /gates/greenlight` | unchanged owner |

No `SCHEMA_GAP`: no migration is needed.

### Design facts for later tasks

1. **LOCAL budget home (Task2).** `budget_reservations` enforces `reserved_amount > 0` (`ck_budget_reservations_reserved_amount_positive`); the probe's zero-amount `LOCAL` reservation was refused with `CheckViolationError`. So token/call reservations for `LOCAL` cannot use the money reservation table.
   - Decision, within the owned map: `LOCAL` token and call reservations live in the run-state row and are reserved in the same row-locked transaction that writes the attempt `RESERVED`. Budget and attempt are therefore one atomic step.
   - The `budget_guard` money path stays for priced currencies (cloud later), where missing pricing refuses the call.
   - The amendment Change E §4 wording is updated to match.
2. **Canon genesis and grant (Task3).**
   - A new project has no Canon branch. `CanonTransactionService.create_branch` (`r2/narrative/canon_transaction.py:100`, idempotent) and its `commit` (genesis when `head_version_id is None`, `:327`) with an exact `CanonCommitApproval` are the real path; no host caller exists yet.
   - The pre-touchpoint run compiles against a provisional genesis version built from the story bible. The manifest gains a step `canon_genesis` (branch + genesis commit) before the plan step, approved by the same touchpoint-2 Approve. Task3 proves it on PostgreSQL. If the approval contract cannot bind this way, Task3 stops with the exact incompatibility.
   - The Human's `HUMAN_SHOWRUNNER` grant comes only from the existing ADR-0103 activation ceremony (`scripts/r2/governance_ceremony.py`, offline signing). It is an operator setup step in the runbook; a run never creates or signs one.

---

## V2 Task1 qualification (2026-10-18, amendment revision 5.1 Change P)

Status: **QUALIFIED_WITH_RECORDED_LIMITS** for route `ollama-chat` → Ollama 0.32.6, `ornith-32k:9b`, on this host (RTX 2070 8 GB, 23 GB RAM). Only this endpoint is accepted by `AuthoringTextGateway`. Any other provider needs its own qualification.

### Code

- `be085c8c`:
  - `lib/text_backends/ollama.py`: native `/api/chat`; `stream`, `think`, `truncate` and `shift` all `false`; one HTTP request per call, no retry or fallback; typed over-context, unavailable, outcome-unknown, HTTP and protocol errors.
  - The `ollama-chat` endpoint in the registry, plus its display keys and API-docs index.
  - `server/story_authoring/{contracts,generation,script_guard,_cjk_ranges}.py`.
  - Vendored Unicode 16.0.0 data and transport fixtures (`tests/fixtures/ollama/`, real 0.32.6 responses).
- `28cc3721`: grammar-pattern fix (below), and the count check moved before the other acceptance checks.
- The next commit: prose as a bounded paragraph array (below).

Tests run on the final code:
- `uv run python -m pytest tests/unit/server/story_authoring/ -q` → 91 passed.
- Earlier on `be085c8c`: `tests/unit/lib/text_backends/ tests/unit/lib/custom_provider/ tests/unit/lib/i18n/test_i18n_consistency.py tests/unit/server/routers/test_custom_providers_api.py tests/unit/server/routers/test_system_config_options.py tests/unit/lib/test_text_generator.py` together with the story tests → 1739 passed. Frontend `pnpm check` → 2594 passed.
- ruff, `basedpyright --warnings` (0/0/0), `lint-imports` (23 kept), `deptry` and `audit_tests --check` are clean.

### Live results

Scripts and outputs are retained in `.superpowers/sdd/2026-10-18-r2-v2-story-release/` (sha256 prefix…suffix):
- `task1_live_qualification.py` `31b193e9…daebda7c`
- run 1 `task1_live_qualification.run1.json` `c49d2d22…fd03eb94` on `be085c8c`
- run 2 `task1_live_qualification.out.json` `0a1bf69a…e5bb3439`, whose canary, grammar_quality and count phases ran on the `28cc3721` code
- `task1_paragraph_schema_probe.out.json` `73c5adcb…bb1e2473`
- `task1_gateway_paragraphs_smoke.out.json` `6865da70…b3213b52`

| Check | Result | Verdict |
|---|---|---|
| Count probe = generation input (n = 24: 12 prose, 12 structured, prompts of 150–14,000 tokens, run 2) | 24/24 accepted, 0 `COUNT_MISMATCH`, only `num_predict` differs between the two requests | PASS |
| Boundary (exact counts) | 24,693 and 27,994 → `INPUT_OVER_LIMIT` after 1 request. 32,994 → HTTP 400 with the exact count → `INPUT_OVER_CONTEXT`, 1 request. 23,985 and 24,546 pass the count and are dispatched; both generations then failed the output shape with `max_out` 200 (run 1, old envelope) | PASS for input enforcement |
| Generation at the context end (`shift:false`) | prompt 32,614 + output 154 = 32,768, `done:true`, `done_reason:"length"` | PASS: no silent shift; a length stop is never accepted |
| System prompt | Without a system message: "Tôi là Ornith, trợ lý lập trình…" 3/3. With one: 0/3 | PASS: every call sends a system message |
| CJK canary, n = 20 per kind (adversarial prompt demanding 突然, 心里, 。, 、 and 𠀀) | Free decoding: 16/20 outputs with CJK. Run 1 BMP-only pattern: BMP CJK 0/40; every leak was U+20000, which the pattern deliberately did not cover. **Run 2 pattern with astral ranges: 0/20 prose, 0/20 structured**; JSON invalid 0/20 and 1/20 (a length stop). | PASS with the shipped pattern |
| Resource envelope (24,592 in + 4,096 out) | `ollama ps` 100 % GPU; VRAM 6.54/8.19 GB; host RAM available ≥ 10 GB; prefill about 31,900 tok/s (cached prefix), generation 37.5 tok/s; wall time 110.4 s | PASS; per-call worst case about 111 s |

### Defects found and fixed during qualification

1. **The pattern broke JSON strings.** Ollama applies a string `pattern` to the raw characters between the quotes, in place of the JSON-string grammar.
   - The first pattern `^[^CJK]*$` admitted `"` and raw newlines. With a single-string envelope the model closed the string early and added keys outside the schema (`characters`, `setting`), or emitted raw newlines: 7/20 invalid JSON.
   - Fix (`28cc3721`): the pattern excludes `"`, `\` and U+0000–U+001F; admits only the escapes `\" \\ \/ \b \f \n \r \t`, with no `\u` escapes, so CJK cannot be spelled as an escape; and covers the astral ranges by default.
2. **A single-string prose envelope shortens prose.** Same scene prompt, "about 700 words", n = 20: free decoding gave a median of 627 words but 12/20 outputs with CJK. The fixed single-string envelope gave 372 words, 0 CJK, 0 invalid. A paragraph array (8–14 items, each ≥ 20 characters, same pattern) gave a median of 852 words, 10/10 valid, 0 CJK.
   - Decision: `OutputMode.PROSE` is a bounded paragraph array (`min_paragraphs`/`max_paragraphs` per step), joined by blank lines.
   - Gateway smoke, 5 scenes: 5/5 accepted, 962–1,228 words, 148 → 1,173–1,483 tokens.
   - Task4 tunes the paragraph bounds and prompt wording to each scene's length target.

### Recorded limits and facts for later tasks

- **English code-mixing (F25) rises when CJK is blocked**: 12/20 prose and 10/20 structured canary outputs contained English words, against 1/20 in free decoding. In the normal scene prompt it was 1/20 (envelope) against 4/20 (free). The F25 detector in Task4 L1 stays mandatory.
- **Budget basis**: worst case about 111 s per generate call; a count probe costs one prefill, about 1 s with the cache. `wall_clock_max` is derived from these in Task4.
- **`StoryLimits` defaults stand**: 24,576 input + 4,096 output inside 32,768. The model stays 100 % on the GPU at the worst case, so no lowering is needed on this host.

---

## V2 Task2: durable run state, attempt ledger, content store (2026-10-18)

Status: **DONE within the owned map**. These are runtime primitives; no story executor is registered yet. That is Task4, after Task3.

### What exists now

- **`lib/db/repositories/task_repo.py`** (story run task type `story_authoring_run`):
  - `read_story_run_state`;
  - `write_story_run_state`: first write and version compare-and-set under `SELECT … FOR UPDATE`;
  - `transform_story_run_state`: read, pure transform and conditional write in one row-locked transaction;
  - `requeue_story_run`.

  Video checkpoint methods and guards are unchanged. `lib/generation_queue.py` gains the `requeue_story_run` wrapper.
- **`lib/generation_worker.py`:**
  - story runs get their own rate bucket `story_authoring` (text default 1), so an hours-long run never occupies the shared `text` bucket;
  - an orphaned running story run is requeued for reconciliation instead of `[restart_lost_text]`.
- **`server/story_authoring/runtime.py`:**
  - `RunState`: phase lifecycle, node heads with `generation_epoch` and `required_fingerprint`, revision index, attempt ledger, budget usage and checkpoint.
  - Pure transitions: `reserve`, `mark_dispatched`, `complete`, `fail`, `mark_unknown`, `require`, `promote`, `reconcile`, `orphan_digests`.
  - `RunStateStore.apply`: one row-locked transaction per transition.
  - `StoryAttemptSink`: the durable `AttemptSink` for the Task1 gateway.
  - `recover_run`.
- **`server/story_authoring/artifacts.py`:** `StoryBlobStore`, content-addressed and immutable under `<project>/story_authoring/blobs/`.
  - Atomic write; the digest is verified on every read and on a repeated put.
  - Malformed digests are refused, and so is a symlink anywhere below the project directory.

### Decisions and facts found while implementing

1. **No change to `lib/ledger.py` or `lib/budget_guard.py`.** The Task0 owner map allowed both, but neither is needed for V2.
   - `Ledger.record` always calls `reserve_for_call`, which outside DEV reserves money (at least `MIN_RESERVATION`) against a currency scope. That is wrong for a local model.
   - `LOCAL` attempts write their usage rows directly through the existing `UsageRepository` (`call_type` text, currency `LOCAL`, cost 0, real token counts).
   - Every money aggregation already filters `cost_amount > 0`; a test proves `cost_by_currency` stays empty.
   - The priced path stays untouched until a priced provider is qualified; the gateway refuses every other endpoint.
2. **`api_calls.execution_id` is a foreign key to M7 `execution_attempts`** (`fk_api_calls_execution_attempt`). PostgreSQL rejected binding story attempt IDs to it; SQLite tests did not, because they run with foreign keys off.
   - The attempt ID goes in `request_id` instead. Each attempt is exactly one provider request, and recovery looks rows up by `(task_id, request_id)`.
   - This is why every Task2 database test also runs on PostgreSQL.
3. **Charging rules:**
   - A reservation charges its maximum until settled.
   - Completion charges the actual usage.
   - A dispatched failure charges the known input (or the reserved input), plus the reserved output unless the failure produced no generation (`MODEL_UNAVAILABLE`, `INPUT_OVER_CONTEXT`).
   - A never-dispatched attempt releases its call and its tokens.
   - `UNKNOWN` keeps its full charge.
   - The wall-clock cap is cumulative model time, so Human waiting time does not count.
4. **Promotion fencing**: the conditions are equal fingerprint, equal expected head, equal epoch and phase `RUNNING`. The first promotion bumps the epoch.
5. **Backup:** blobs are regular files under the projects root, so `r2/host_hardening/deployment_backup.py` captures them; it refuses symlinks, as the store does. The backup also refuses to run while tasks are active (`ACTIVE_TASK_STATUSES`), so the runbook must say not to back up during a story run.

### Tests

Unit (SQLite or none) — `uv run python -m pytest tests/unit/server/story_authoring tests/integration/server/story_authoring -q` → 133 passed:
- `test_runtime_state.py`: reservations, caps, charges, fencing including same-fingerprint and after-discard cases, reconcile, orphans;
- `test_artifacts.py`: store, tamper, digest injection, symlinked directory and file;
- the Task1 suites.

PostgreSQL 16 on the disposable `arcreel-story-test-pg` (per-test schemas) — `DATABASE_URL=postgresql+asyncpg://…@127.0.0.1:55480/arcreel_story_test uv run python -m pytest tests/integration/server/story_authoring "tests/integration/lib/db/repositories/test_task_repo.py::TestStoryRunState" -q` → 14 passed:
- 12 concurrent reservations against a cap of 5: exactly 5 granted, the run `BLOCKED_BUDGET`;
- the usage row: currency `LOCAL`, cost 0, tokens, `request_id` equal to the attempt ID;
- the run stopped before dispatch: nothing sent, call released;
- restart recovery: in-flight → `UNKNOWN`, not dispatched → `FAILED NOT_DISPATCHED`, usage rows closed, idempotent;
- two same-expectation promotions on two connections: exactly one head;
- a finished run task refuses every change;
- the repository guards.

Regression: every generation queue and worker suite (12 files) → 259 passed. Queue, worker, repository and accounting suites together with the story suites → 437 passed, 1 skipped. ruff, ruff format, `basedpyright --warnings` (0/0/0), `lint-imports` (23 kept), `deptry` and `audit_tests --check` are clean.

### Open for later tasks

- **Task4:**
  - registers the story executor;
  - runs `recover_run` at every start;
  - maps `CancelledError` of an in-flight call to `UNKNOWN` before the task is cancelled;
  - for a priced currency, stops at `UNKNOWN` instead of continuing. `LOCAL` continues with a new visible attempt.

---

## V2 Task3 finding: `NARRATIVE_CANON_EXTRACTION_GAP` (2026-10-18)

Status: **STOPPED FOR HUMAN DECISION** (amendment Change C §6–7: "if a decision family cannot be bound this way, Task3 returns the exact incompatibility before Task4"). No Task3 code has been written.

### Facts (source-traced on `release/r2-v2-story`)

1. **The real per-scene chain is longer than the amendment's "per chapter: `decide_revision` → `review_change_set` → `admit_canon_handoff`".** The R2 unit is the scene (`NarrativeRevision.scene_contract_version`), and the chain is:
   1. `record_draft_candidate` and `record_revision` (needs an approved plan version ≥ 1, a scene contract version, a Canon base version and a `context_pack_id`);
   2. **`decide_revision`** (Human);
   3. `admit_extraction`: the `ExtractionAttempt` must name the `revision_acceptance_decision_id`, so extraction can only start after the Human accepts the revision;
   4. an extractor produces `NarrativeChangeSet`s; `record_successful_extraction`;
   5. **`review_change_set`** (Human, per change set);
   6. `admit_compilation`;
   7. `CanonDeltaCompiler.compile` under a `CompilerPolicy`;
   8. `record_successful_compilation`;
   9. **`admit_canon_handoff`** with an exact `CanonCommitApproval` (Human);
   10. `NarrativeCanonHandoffFacade.commit_from_admission` → `CanonTransactionService.commit`.
2. **No production extractor exists.** `r2/narrative_lifecycle/changeset_parser.py` is the Huohuo change-record parser; its own docstring says its output "is not a `NarrativeChangeSet`". Nothing maps prose to `NarrativeChangeSet`s with `NarrativeSemanticEffectKey`s.
3. **No production compiler policy exists.** `CanonDeltaCompiler` expands accepted effect keys into Canon operations only through `CompilerPolicy.mutation_rules` (`CanonMutationRule`: an exact `(subject kind, subject ref, effect descriptor)` → explicit `CanonOperation`s). No code authors those rules.
4. **Consequence for a single Approve.** If extraction ran after the click, the Human's `review_change_set` and `CanonCommitApproval` would approve change sets and Canon operations that did not exist when they clicked. That is not a decision bound to an exact revision.
5. **No production `NarrativeShowrunnerAuthorityPort` adapter exists.** Only the test fake exists. The grant source does exist: the ADR-0103 ceremony and `server/services/governance_grants.py` `CurrentShowrunnerGrantReader` / `CheckpointedShowrunnerGrantReader`. Accepted M8 services already authorize with it in production (`format_review.py`, `spatial_pair_decision_v2.py`). A Narrative adapter over the same reader is host composition owned by Task3; it mints and infers no grant.
6. **`NarrativeContextCompiler` has no production composition** (no non-test `NarrativeContextCompiler(` call). Readers to compose:
   - Canon: `lib/db/repositories/canon_repo.py`;
   - plan: `NarrativePlanService`;
   - accepted narrative: the existing `AcceptedNarrativeAdapter`;
   - creative policy, retrieval snapshot and token counter.

   This is glue owned by Task3, not a blocker.
7. **Decision IDs must be content-derived.** The accepted-narrative reference is a revision-acceptance decision ID, and it enters the next scene's `context_pack_id`, the revision and so the manifest. Deriving decision IDs from the manifest digest (amendment Change C §5) would therefore be circular. They must be derived from content: `sha256("story-decision-v1" ‖ run_id ‖ node_id ‖ revision digest)`. Manifest step keys stay host-side bookkeeping only. As a consequence, unchanged prefix scenes keep their decision IDs in a successor manifest.

### Options presented to the Human

- **A — outcome-only Canon for V2 (recommended).**
  - At touchpoint 2, the one Approve covers:
    - the Canon genesis: entities and facts deterministically mapped from the story bible, shown and bound in the manifest;
    - the plan commit;
    - one `decide_revision` ACCEPT per scene.
  - No extraction, change-set review or Canon handoff per scene. Story continuity comes from the plan, the genesis Canon and the accepted prose (the `RECENT_ACCEPTED` context channel).
  - Every Human decision binds content shown before the click. 2 touchpoints are kept, and no new R2 component is built.
  - Canon does not record story events; a later version can add extraction.
- **B — build an extractor and compiler policy now.**
  - A model writes change records → `NarrativeChangeSet`s plus `CanonMutationRule`s. They are pre-computed before touchpoint 2 and shown and bound in the manifest, so the full chain runs in one Approve.
  - This is a large new component outside "integrate existing owners": an extra model step per scene on a 9B model, model-authored Canon operations, and many more items for the Human to review at touchpoint 2.
- **C — as B, with a third Human touchpoint** after acceptance to review change sets and approve the Canon handoff. This breaks the 2-touchpoint decision.

### Decision (2026-10-18): option A

The Human delegated the choice ("nghiên cứu chọn phương án phù hợp nhất": research and choose the most suitable option). Research basis:

- `AcceptedNarrativeAdapter.get_exact` treats a revision as accepted narrative when its revision-acceptance decision is the current effective ACCEPT for its work scope. Extraction, compilation and Canon handoff play no part in that.
- The M5C design (`2026-09-09-r2-m5c-narrative-lifecycle-design.md` §1, flow) lists extraction after the Human revision decision and allows a stop without M5A. §2.1 says a revision acceptance decision "cannot mutate prose or Canon". No rule requires every accepted revision to be extracted. The M5C acceptance suite includes `test_an_outcome_only_selection_mutates_no_canon`.
- The Canon genesis can be expressed with existing operations (`ADD_ENTITY`, `ADD_FACT`, `ADD_EVENT`, …) mapped deterministically from the story bible.
- Option B would need model-authored `CanonMutationRule`s on a 9B model, which is new authority-adjacent machinery outside "integrate existing owners". Option C breaks the 2-touchpoint decision.

**Chosen: A.** The touchpoint-2 Approve records, in order:
1. the Canon genesis when the project has no Canon branch: `CanonTransactionService.create_branch`, then `commit` of the bible-derived genesis delta with its exact `CanonCommitApproval`;
2. the plan: `NarrativePlanService.commit_revision` with the exact `NarrativePlanApproval`;
3. per scene in story order: `record_draft_candidate` and `record_revision` (evidence), then `NarrativeAcceptanceService.decide_revision` ACCEPT.

There is no extraction, change-set review or Canon handoff for story scenes. The Huohuo change-record surface is **deferred** to a later version, not rejected. Revision-acceptance decision IDs are content-derived (fact 7). The amendment is updated accordingly.

---

## V2 Task3: touchpoint-2 binding and commit protocol (2026-10-18)

Status: **PASSED (hard gate)** for option A, on disposable PostgreSQL 16 with the real R2 owners and a real signed Showrunner grant. Task4 stays closed until the Human opens it (amendment § Execution).

### Code (owned under `server/story_authoring/`)

- **`narrative.py`:** maps one run onto the R2 owners.
  - Bible → Canon genesis delta (`ADD_ENTITY` and `ADD_FACT` description facts), with a version id derived from the delta and passed through `CanonTransactionService(version_id_factory=…)`, its existing public parameter.
  - Outline → v1 `NarrativePlan` revision: CHAPTER nodes, and per scene a `SceneContract` with POV, location, participants, a one-hour story-time window and beats as creative constraints.
  - Content-derived draft candidate, revision and revision-acceptance decision ids.
  - The real `NarrativeContextCompiler` over two reader sets:
    - provisional: genesis view, provisional plan, and earlier acceptances through the real `AcceptedNarrativeAdapter` over an in-memory store;
    - committed: `CanonResolutionService`, `NarrativePlanService.get_version` and `AcceptedNarrativeAdapter`.
  - The style bible serves as the creative policy; there is no retrieval snapshot; the word token counter is `story-words-v1`.
- **`authority.py`:** `GrantNarrativeShowrunnerAuthority` is the production `NarrativeShowrunnerAuthorityPort`. It reads the current `HUMAN_SHOWRUNNER` grant through the existing `CurrentShowrunnerGrantReader` (in production, `app.state.governance_grants`, the checkpointed reader), and denies without a reader, without a grant, or for a command naming another actor. It mints or infers no grant. The same check guards the plan and Canon approvals.
- **`commit.py`:** `ManuscriptCommitManifest`; its digest is the sha256 of its canonical JSON, which is also its blob id.
  - `ManuscriptCommitter` provides `offer`, `approve`, `resume`, `abort` and successor offers.
  - `ApprovalRecord` is persisted in phase `APPROVING` before any decision is sent.
  - Steps run in order: `canon` (create branch + genesis commit), `plan`, then per scene: recompile and compare the binding → `record_draft_candidate` → `record_revision` → `decide_revision` ACCEPT.
  - `COMMITTED` follows only a read-back of the Canon content hash, the plan content hash and every accepted revision.
  - An owner refusal or binding difference moves the run to `COMMIT_BLOCKED` with the step and reason.
- **`runtime.py`:** `RunState.commit` holds `CommitProgress`: offered digest, approval and completed steps.

### Evidence

`DATABASE_URL=postgresql+asyncpg://…@127.0.0.1:55480/arcreel_story_test uv run python -m pytest tests/integration/server/story_authoring/ -q` → **23 passed**, three consecutive runs. SQLite: `tests/integration/server/story_authoring tests/unit/server/story_authoring` → 149 passed. `test_narrative.py` and `test_commit.py` prove:

| Task3 gate (amendment verification matrix) | Result |
|---|---|
| Binding proof: provisional contexts equal committed contexts (`context_pack_id` and `content_hash`), 3 scenes, earlier accepted prose present | PASS |
| One Approve records genesis, plan and every scene; decisions carry the grant principal | PASS: 1 Canon version, 1 plan version, 3 decisions, `actor_id` = sponsor |
| Principal without a grant; deployment without grants; command naming another actor | refused; nothing written |
| Stale manifest digest; unticked critical exception | `STALE_MANIFEST`; `EXCEPTIONS_NOT_ACCEPTED`; Approve succeeds once ticked and records the exception |
| Two concurrent Approves | exactly one sequence; the other is refused; 3 decisions |
| Crash after `canon`, `plan`, first scene and last scene (after the owner committed, before the run recorded it), then resume | `COMMITTED`, no duplicates. Only the approver may resume (`NOT_THE_APPROVER`). |
| A concurrent plan commit between proof and commit | `COMMIT_BLOCKED` at `plan`; only `canon` committed; 0 decisions |
| Binding difference at scene 3 | `COMMIT_BLOCKED` with the exact step; prefix = `canon`, `plan` and two scenes |
| Successor with an unchanged prefix | offered and approved → `COMMITTED` |
| Successor changing a committed scene | `SUCCESSOR_REFUSED` naming the scene; abort → `ABORTED_PARTIAL`; the two accepted scenes stay; a second abort → `NOT_ABORTABLE` |
| Determinism | rebuilding from the same inputs gives the same manifest digest; changing the last scene changes only its entry |

### Closed review items

- **Fourth-review P0-B (context identity and rebase revision):** with content-derived decision ids, `recent_accepted_refs` changes only when an earlier scene's content changes, and then `content_hash` changes too. So a rebase revision is never needed (proved by the determinism test). No compiler hash or Canon authority was changed.
- **P0-C (successor inside a chapter):** under option A each scene is one step, and a successor may change only uncommitted steps. Every committed step's subject (the genesis delta, the plan proposal, the scene entry) must be identical, or the offer is refused.
- **Per-transition idempotency (third-review P1-03):** proved through the owners' exact-retry paths at every step kind.

### Facts

- **Gate A:** `POST /gates/greenlight` appends a decision to a per-project history. No backend code reads it to gate a later step, and the frontend only lists it. The story's Gate A (brief digest) and any later video greenlight are independent history entries, so there is no `GATE_A_SCOPE_CONFLICT`. Video keeps Gates B–D unchanged.
- **Test fixture timing:** importing the same signed grant twice in different seconds is a different event; the tests import it once per test.

### Regression

- M5C architecture boundary suites (unit and DB) plus `tests/integration/r2/narrative_lifecycle`, `narrative_plan`, `narrative` and `tests/unit/r2/narrative_context` → 230 passed, 7 skipped (PostgreSQL-only concurrency cases; no R2 code changed).
- ruff, ruff format, `basedpyright --warnings` (0/0/0), `lint-imports` (23 kept), `deptry` and `audit_tests --check` are clean.

## V2 Task4.5: run driver, executor, service, routes and video hand-off (2026-10-19)

Status: **PASSED (scripted model)** at HEAD `9de851aa` on `release/r2-v2-story`. The live end-to-end run and the
n ≥ 10 differential are Task4.6.

### What was built

| Part | Code | Behaviour |
|---|---|---|
| Node graph and staleness | `pipeline.py` (`75c99f4b`) | acyclic graph for 3–5 scenes per chapter; fingerprints over template, route, decoding, input heads, intents and binding; forward closure equals the Change D stale set |
| Run driver | `driver.py` (`f45f010b`, `7dbfd051`) | converges in topological order, skips a node whose head carries its fingerprint, regenerates the rest under per-node call caps; L1 checks and repair ladder per scene; 4 L2 audits with ≤ 2 repair cycles per chapter; the critic's `NO_ENDING` rewrites the final scene once; packaging keeps only quoted selling points (≥ 3); whole-story length outside 6,000–12,500 is hard structural, outside 7,000–11,000 stylistic; builds and offers the manifest, with successor fields after a partial commit |
| Executor | `executor.py`, `_TASK_EXECUTORS` (`4a984608`) | reconciles after a restart, re-resolves the frozen route against the custom provider (changed base URL, endpoint or credential presence → `MODEL_UNAVAILABLE` before any call), drives the run; a run that is not `RUNNING` is returned unchanged |
| Service and routes | `service.py`, `server/routers/story_runs.py` (`9de851aa`) | brief draft with frozen route; start only on a current Gate A greenlight of the exact brief digest; touchpoint 2 through the committer; revise, retry, discard, withdraw, resume, abort; every changing action needs an interactive session and the Showrunner grant |
| Hand-off | `handoff.py` (`9de851aa`) | `COMMITTED` only, once per run, digest-checked, CJK re-scanned, ASCII slug name with a digest suffix on collision, `PENDING` before the upload |

### Verification (PostgreSQL `arcreel-story-test-pg`, scripted model through the real gateway and attempt sink)

| Property | Test | Result |
|---|---|---|
| Clean run reaches touchpoint 2 with 9 scenes, 3 chapters, export bound to the manifest | `test_driver::test_a_clean_run_converges_and_offers_one_manifest` | pass |
| A converged run calls no model again; the same manifest digest | `test_a_second_run_of_a_converged_story_calls_no_model` | pass |
| Crash at scene 5 → `MODEL_UNAVAILABLE`; resume regenerates only scenes 5–9, no planning node | `test_a_crash_mid_run_resumes_without_regenerating_converged_nodes` | pass |
| Revision of scene [3,1] keeps scenes 1–6 decisions, regenerates 7–9 and chapter 3 review only | `test_a_scene_revision_regenerates_that_scene_and_everything_after_it` | pass |
| A quoted continuity error is patched before the chapter is sealed | `test_a_quoted_continuity_error_is_repaired_before_the_chapter_is_sealed` | pass |
| Node cap → `BLOCKED_QUALITY`; unresolved ending rewritten once, then blocked; packaging needs 3 quoted points; short story blocked | 5 tests | pass |
| A revision requested while the run converges is honoured before the offer | `test_a_revision_requested_while_running_is_honoured_before_the_offer` | pass |
| Route change refused before any call; finished run not re-driven; queue dispatch | `test_executor`, `test_generation_tasks_dispatch` | pass |
| Brief → Gate A → start → run → Approve → `COMMITTED` → export → hand-off (real `upload_source`) → repeat returns the same record → other command refused → withdraw blocks export | `test_service::test_a_greenlit_brief_runs_to_an_approved_manuscript_handed_to_video` | pass |
| Crash after the source write, before the record → retry completes with no second upload, one source file | `test_a_pending_hand_off_whose_source_was_written_completes_without_a_second_upload` | pass |
| Gate A: digest mismatch, missing, superseded by revoke, principal without grant; repeated start → same run | `test_start_requires_a_current_greenlight_of_this_exact_brief` | pass |
| Blocked → retry (new epoch) → ready; unknown target refused; chapter revision; discard → Approve refused | `test_revise_discard_and_retry_follow_the_lifecycle` | pass |
| HTTP: non-interactive session → 401; refusal codes; stale manifest 409; approve, export, send-to-video, withdraw | `test_routes` (3 tests) | pass |

Commands: `DATABASE_URL=… pytest tests/integration/server/story_authoring` → 48 passed; SQLite: story unit + integration,
dispatch, worker module and task repository tests → 414 passed. ruff, `basedpyright --warnings` (0/0/0),
`lint-imports` (23 kept), `deptry` and `audit_tests --check` are clean.

### Recorded deviations and open values

- **Brief edit = new run.** A Human brief edit is a new draft, a new Gate A and a new run; the `AWAITING_GATE_A` pause of Change C §4 is not used. The old run can be discarded. Same touchpoint count.
- **One hand-off per run.** A second command id for the same run is refused (`ALREADY_HANDED_OFF`), so a duplicate source cannot be written.
- **Intent expiry.** Discard, abort and `COMMITTED` are terminal for the driver, so remaining intents are inert; they are not rewritten to `EXPIRED`.
- **Default limits** (`DEFAULT_LIMITS`): the Change "Size and budget" upper bounds (132 calls, 132 × 24,576 input tokens, 132 × 4,096 output tokens, 6 h). Task4.6 replaces them with measured p95 × 1.2.
- The scripted model proves control flow and owners, not prose quality; quality evidence is Task4.6.
