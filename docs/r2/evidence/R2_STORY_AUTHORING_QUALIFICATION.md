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
