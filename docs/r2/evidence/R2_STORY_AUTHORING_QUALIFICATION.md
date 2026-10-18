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
