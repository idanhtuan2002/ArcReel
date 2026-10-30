# Autonomous production implementation handoff — in progress

Sponsor approved design, plan and continuous native execution: “dung dung lai, lam luon”. Do not ask again for routine step approval. Execute the 12-task plan; do not call the whole workflow complete from a foundation packet.

## Resume authority

- Worktree: `/home/anhtuan/.codex/worktrees/9b89/content-production-os` (native managed creation; keep tool task cwd, pass this path explicitly).
- Branch: `impl/autonomous-production`.
- Latest committed foundation checkpoint: `9b4dcb9fe80accab4424c91d35244705fadec1d3`; base plan `127d44e544eb2dbfcfe154f0ab62791a04b453e1`, released application base `0cef69a772f1d2946e452b918a8839b0f37fd2d9`.
- Plan: `docs/superpowers/plans/2026-10-30-autonomous-production-workflow.md`; approved spec adjacent under specs.
- Ledger: `.superpowers/sdd/2026-10-30-autonomous-production-workflow/progress.md`. Read ledger, `git status` and task brief before resuming. Workspace contains task-start briefs, scoped task-done1/2/3 markers and exact test logs.
- Root checkout and other worktrees are unrelated; preserve them. Release checkout has not changed; production is not activated.
- This worktree needs escalated exec for writes because native placement is outside original writable root; user authorized work. Shared `/tmp` also hit quota, so default sandbox setup can fail. Use explicit workdir and authorized escalation; do not modify security settings or clean unrelated data.
- `.venv` is a locally ignored symlink to existing `r2-m10-c/.venv`; use `uv run --no-sync`, do not mutate shared dependencies.

## Current implementation and verification

Task 1 implements immutable policy/run/outcome/review/target contracts, canonical dispatch IDs, auto/semi checkpoint policy, phase-aware stage transitions, rework limits, generation fencing and affected-target invalidation. ADR-0111 and glossary record prospective automatic authority; no Human role bypass or runtime grant has been implemented.

Core TDD: 44 tests failed before implementation; three additional edge failures reproduced double-counted Quality after semi approval, forward-skipping repair and missing fencing/unaffected-target preservation. Current focused suite: **682 passed** (48 new + existing contracts/production), 4 baseline warnings. Full ruff, basedpyright, import-linter (23 kept), deptry and test audit passed.

The first full backend attempt was **unusable**: shared `/tmp` quota caused OSError 122 and xdist internal error (1542 failed/578 errors/16201 passed/380 skipped before abort). Do not classify that as a product pass/fail. Switching temp storage made the ComfyUI image/governance CLI probe pass 33 tests.

Second full backend invocation is running with `TMPDIR=/home/anhtuan/.cache/arcreel-autonomous-tests-9b89`, `uv run --no-sync python -m pytest -n 4 --dist loadfile`. Session **88865**; log `task-1-backend-full-isolated.log`. Final result: **27 failed, 18979 passed, 435 skipped, 2 collection errors** in 6157.53s. Own automation test package marker fixes basename collisions; short secure /var/tmp/ar9b retest addresses Unix-socket path and ancestor custody failures. One anonymous packaging archive endpoint returns422 vs401; investigate/fix by Task10. M7 dirty-path failure needs clean-HEAD retest. Exact logs retained; **full backend gate is not passed**. Four worker processes were children of 3899783; inspect only owned processes if diagnosis is needed. Source bytes stayed fixed through RED preparation, then HEAD advanced 127d44e54→e288a522c; storage implementation may proceed while legacy renders finish. Do not regard this run as final frozen-branch acceptance. Git/head-sensitive failures need fixed-HEAD retests.

Task 2 implements PostgreSQL-scoped run/intent/policy/usage storage and frozen PG/SQLite migration b7a310300001. UNKNOWN retains held budget; immutable triggers prevent raw-SQL rollback/release, late actual usage preserves cancelled status. TDD reproduced those defects and lease expiry during row-lock wait; lease admission now reads DB time after locking. First combined focused verification: **88 passed** (24 storage/schema + 53 automation + 11 Host budget compatibility); final rerun after lease repair: **89 passed**. Ruff, targeted basedpyright and test audit passed. Task3 now adds runtime delegation primitives; controller and owner adoption remain pending. Exact command uses `DATABASE_URL=postgresql+asyncpg://autotest@127.0.0.1:32769/autonomous_test`, same private TMPDIR, log `task-2-red.log`. Inspect actual log before implementing.

## Task 3 implementation checkpoint

Separate immutable child grant history/head and owner decisions now bind exact Start, activated signed/checkpointed parent, scope, policy/input, canonical durable intent, stage, generation/version and active worker lease. Only real interactive scoped Showrunner may issue/revoke; workers retain no JWT. Parent/child revocation and checkpoint movement refuse replayed authority. No Human role, event or assessment is fabricated. `issue_locked` exists for atomic Start in Task6; owner adapters must preserve documented lock order. Mode/policy successor delegation is a Task6 consumer extension, never inferred from old grant.

TDD final combined **125 passed** (63 automation unit tests + 25 run storage/schema + 37 scoped service tests); actual Alembic SQLite CLI roundtrips for both revisions **2 passed**. Refreshed full ruff, basedpyright (0 errors/warnings) and test audit (0 violations) passed; import-linter 23 kept/0 broken and deptry passed. Source files/migration are included in this Task3 checkpoint. Task4 preflight, Task5 owner authority adoption and Task6 controller remain next. Full backend acceptance is still open as described above.

Research child owns `docs/research/2026-10-30-drama-speech-route-qualification.md`. First result: installed RTX2070/8GiB and silent Wan TI2V cannot prove drama lip sync; child is comparing pinned official source of audio-driven MuseTalk/Wav2Lip candidates. No download/provider/config changes allowed in that research. Do not overwrite its concurrent doc. Main must review findings before an explicit design addendum; no drama qualification yet.

## Test infrastructure and constraints

A disposable owned PostgreSQL 16-alpine container is running: **arcreel-auto-test-9b89**, localhost **32769**, database `autonomous_test`, user `autotest`, local-only trust auth, 512 MB/1 CPU. Cached image pin `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`. No production DB/container was changed. Stop this container when all verification finishes. Failed initdb attempt only created empty `/tmp/arcreel-autonomous-pg-9b89`; no native cluster exists.

Test temp cache is owned by this execution and already several GB; remove only its own completed artefacts when safe, never shared `/tmp` or other workers' data. Keep logs/failed case evidence needed for diagnosis. Root had 26+ GiB free near end of full run; monitor before another broad run.

Graph `r2-v2-main` generation 2026-10-15 is older than source. Graph-first searches/traces/coverage were used; direct source fallback covers missing story/Quality and new modules. Do not infer exhaustive absence from old graph.

## Rulings carried to next tasks

- Define future DTOs at their first tested consumer, not speculative placeholders: command/budget Task 2, grants/auth Task 3, preflight Task 4, render/device Task 8, assessments Task 9. The plan documents this execution ruling.
- Rework increments run generation and removes only affected target outputs. Unaffected outputs may retain older generation when input/policy and owner evidence stay current. Final owner-currentness checks are mandatory; generation equality is not sole truth.
- Existing Host BudgetReservationService remains provider monetary authority. New run allocations enforce run-wide cost/call/task/runtime limits and preserve owner usage references; do not create another provider charge ledger or mutate Host Usage.
- Existing `concurrent_session_factory` is PG-aware, `file_session_factory` is SQLite-only. Assert real PG for authority/interleaving tests.
- All lib-level device/render seams consume pure contracts/injected ports, never import server read-model/services. Device lease expiry is not quiescence proof.
- Tasks1–3 have scoped implementation checkpoints; Task4 source checkpoint is described below, Tasks5–12 remain. Full launch still requires actual authority adapters, backend controller, native renderer, qualified automatic Quality, UI, fresh product/recovery and export acceptance. Drama speech/lip-sync route research remains prerequisite.

## Task4 source checkpoint and next entry

Task4 adds candidate launch JSON, strict model-route pins in policy, launch_profile_id/local_only, pure read-only preflight checks, owner-bound reviewer/launch qualification contracts and actual host configuration inspector. `resolve_launch_profile` returns LaunchProfile metadata, not RunPolicy (runtime caps and model/Quality pins cannot be resolved from a static ID). Both presets remain CANDIDATE; drama explicitly blocks pending audio-driven route qualification. Inspector reads real DB/ConfigResolver and capability metadata without a provider backend, exposes only digests and refuses disabled-model fallback.

TDD/regression: **93 component tests**, **727 contracts/production/preflight tests**, **53 PostgreSQL scoped authority/run tests** passed; full ruff, basedpyright0/0 and test audit0. These counts overlap; do not add them as unique coverage. Actual owner-qualified corpus and launch receipts have not been produced. Positive preflight tests inject synthetic read-port data; no live production readiness inferred.

Plan/ledger ruling moves real snapshot assembly to Task6's first Start/controller consumer and actual qualification record resolution to Tasks9/12. These are mandatory remaining gates; no fake qualified reader should be created. Task5 starts next: versioned automatic narrative/master authority while preserving old Human wire bytes. Initial source discovery found legacy NarrativeDecisionAuthorization/RetryAuthentication and Adaptation/Gate literals are Human-only; Canon/Plan approvals are data passed to owner UoWs, no automatic final grant fence. Need main-owned design/actual source probes before changes. Existing SqlAlchemy owner UoWs expose `.session`, while pure R2 protocol does not; any automatic final guard must operate in the owner transaction, after owner locks, and fail closed without the real server authority. Never authenticate on a separate transaction and reuse that as final grant currentness. No Task5 source edits yet.

Research completed: docs/research/2026-10-30-drama-speech-route-qualification.md has pinned official VieNeu/Wan/MuseTalk/Wav2Lip sources. MuseTalk is an unqualified investigation candidate for RTX2070/8GiB, not installed/selected. All research children finished; no active implementation child. Approval review hit a usage-limit error once; after user said continue, retry through the same approval mechanism succeeded. Do not bypass review on a recurrence.

## Task5 currently in progress

HEAD **bc825a6e74574f2776f024dee18bb03451cf777e**; Task4 component checkpoint committed. Clean-HEAD M7 verifier passed. Task5 brief extracted at this HEAD. This recovery correction checkpoint contains `lib/db/repositories/automation_grants.py` and `tests/integration/server/services/test_automation_grants.py`. A real PG test reproduced failed receipt replay after controller takeover; replacement claim changes run.version while logical intent is unchanged. Fix ignores only expected_run_version in durable command replay comparison after fresh authority validation, verifies original stored digest against original stored subject and reuses immutable original proof. Old worker denied. Full authority file **38 passed**; scoped ruff passes. Targeted basedpyright0errors/warnings and test audit0 also passed. Continue implementing owner seams. Do not repeat the RED/implementation.

Task5 source evidence: NarrativeLifecycle AuthorityKernel obtains authorization after owner heads/applicability but current legacy Human port uses another transaction. New automatic method must receive owning UoW through an explicit pure port; server adapter extracts only approved concrete SQL UoW.session, validates same owner transaction, and invokes RunAutomationAuthority under existing lock order. Canon/Plan need failclosed automatic variants and owner guard; do not reinterpret unguarded approval DTO as runtime authority. Preserve Human APIs and historical JSON. Avoid implicit global/ContextVar session binding.

One STORY_COMMIT manifest spans Canon/Plan/many revision decisions: bind shared Task3 intent authorization to exact immutable ManuscriptCommitManifest and verify typed subcommand membership against it; do not change Task3 subject digest per subcommand under the same command ID. This is a proposed seam pending actual fixture proof, not a completed architecture/implementation gate. Relevant source already read: server/story_authoring/{authority,commit}.py, r2/narrative_lifecycle/{authority_kernel,ports,acceptance}.py, r2/narrative_plan/service.py, lib/db/{canon_uow,narrative_plan_uow,narrative_lifecycle_uow}.py. Parent graph evidence old generation2026-10-15; source fallback required for new story code. No owner source edits yet.
