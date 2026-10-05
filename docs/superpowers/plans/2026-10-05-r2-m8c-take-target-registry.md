# M8-C Take Target Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The repository's one-background-agent budget and main-agent authority rules take precedence.

**Goal:** Register exact Take-derived Scene and Shot target versions from one current admitted screenplay, with scoped immutable versions, one current head per target and replay-safe bundle writes.

**Architecture:** A server-internal service owns one `AsyncSession` transaction. It uses the transaction-bound screenplay reader from the preceding packet, derives with the existing `TakeDirectorAdapter`, then writes scene and shot versions through one scoped repository in the common admission → scene → shot lock order. The service locks and checks the full upstream admission before repository target-head verification. Repository current reads recompute body/version digests under target locks; no caller-supplied target body is accepted.

**Tech Stack:** Python 3.13, SQLAlchemy 2 async, Pydantic v2, Alembic, pytest, PostgreSQL 16 and SQLite migration checks.

**Spec:** `docs/superpowers/specs/2026-09-30-r2-m8c-binding-authority-design.md` (proposed first target-registry packet), ADR-0102, `tests/fixtures/r2/m8c_target_registry_vectors.json`.

## Global Constraints

- This packet depends on `docs/superpowers/plans/2026-10-05-r2-m8c-transaction-bound-screenplay-reader.md`; it does not duplicate admission fold logic or open a second UoW.
- Accept only one full stored `AdmittedScreenplayRef`, including `profile_ref`, in the caller's trusted `(user_id, project_name, principal)` scope. The service is internal; no HTTP route or second human approval is created here.
- One registration command derives one complete Take scene/shot bundle; Scene heads lock by ID before Shot heads by ID. For each key in that order, an absent head is inserted as an uncommitted nullable genesis row and immediately locked/re-read before visiting the next key. Every attempt and replay read uses scoped keys and its own transaction. A unique-command race rolls back the losing attempt before a new transaction verifies the winner.
- The proposed body/version domains and exact bytes come from the checked-in target-vector fixture and Preparation's `r2.contracts.canonical_json_bytes`; M8's float encoder is not a substitute.
- Version body `1` from `TakeDirectorAdapter` is distinct from registry version `1, 2, ...`. The producer pins `r2-take-director-v1` as its derivation label.
- Schema, service and tests stay internal. No binding CAS, pair decision, provider call, migration of a live database or production activation belongs to this packet.

## Review Focus

- A forged profile, wrong user/project or stale screenplay admission must create no target version; Task 3 tests each.
- Same target IDs and body version `1` after a new admission must advance registry versions and digests; Task 3 tests this.
- Same command ID with changed admission/derivation input must conflict; same exact current command must replay the verified original result without a second version, while a stale replay fails; Task 3 tests all three.
- A corrupt body, version digest, scene link, command result or head pointer must fail on authority read/replay; Tasks 2 and 3 test these.
- Two writers creating the same absent head must serialize through its scoped unique key and never commit a genesis row; Tasks 2 and 4 test this.
- Partial bundle failure and racing registrations/re-admission must leave one complete current bundle with no stale success or deadlock; Task 4 tests this on PostgreSQL.

---

### Task 1: Scoped Target Registry Schema

**Files:**
- Create: `lib/db/models/production_target.py`
- Modify: `lib/db/models/__init__.py`
- Create: `alembic/versions/8c8c4a0e0001_add_production_target_registry.py` (down revision `8b8c4a0e0001`; recheck live heads before writing)
- Create: `tests/integration/lib/db/migrations/test_production_target_registry.py`
- Modify: `tests/integration/lib/db/migrations/test_alembic_m8_exploration.py`
- Modify: `tests/integration/lib/db/migrations/test_spatial_frame_receipts.py`

**Interfaces:**
- Produce `ProductionTargetHeadModel`, `ProductionTargetVersionModel` and `ProductionTargetCommandModel` with table names and scoped keys from the spec.
- `production_target_heads` has a nullable genesis `(current_version, current_version_digest)` pair and a scoped FK to the populated exact version. SHOT version rows have a scoped FK on `(user_id, project_name, scene_target_type='SCENE', scene_target_id, scene_registry_version)` to a SCENE version and store its digest separately for revalidation.

- [ ] Write migration tests that reject cross-user/project head and Shot→Scene links, SHOT rows with partial or non-SCENE dependency, SCENE rows with dependency columns, and a head pointing to a missing version. Confirm one valid scene+shot bundle inserts under both supported test dialects where constraints apply.
- [ ] Update the existing M8 migration tests that assert the sole Alembic head is `8b8c4a0e0001` and the exact downgrade table delta. Keep their historical parent-revision and frame-constraint assertions; add the three new registry tables only to the expected current-head/downgrade footprint.
- [ ] Run those tests RED before adding models/migration. Add the minimal schema and model exports; keep the nullable genesis row uncommitted by service convention.
- [ ] Upgrade and downgrade the migration on disposable PostgreSQL 16 and run the migration test file. Record the exact migration head and observed FK/check behavior; do not apply to a live database.
- [ ] Commit this task's schema, model and tests only.

### Task 2: Typed Digest and Current-Read Contract

**Files:**
- Create: `r2/contracts/production_target.py`
- Create: `r2/target_registry/digests.py`
- Create: `lib/db/repositories/production_target.py`
- Test: `tests/unit/r2/advanced_creative/test_m8c_target_registry_vectors.py`
- Create: `tests/integration/lib/db/repositories/test_production_target_registry.py`

**Interfaces:**
- Produce `TargetVersionRef` containing `(target_type, target_id, registry_version, version_digest)` and `TargetRegistrationResult` containing ordered Scene then Shot refs and a result digest. Reject unsupported target types.
- Produce `target_body_digest(target_type: ProductionBindingTarget, target: SceneSpec | ShotSpecV2) -> str` and `target_version_digest(version_body: TargetVersionBody) -> str` using the spec's domains and Preparation canonical bytes. `TargetVersionBody` contains the exact fields of the proposed fixture. Define `registration_command_digest(...)` and `registration_result_digest(...)` for the two command/result domains in the spec; exclude audit timestamp and command ID from target-version digest.
- Produce repository methods `get_command_receipt`, `lock_target_head`, `get_current_verified`, `append_version`, `advance_head` and `record_command`; all take or retain the caller's `AsyncSession` and never commit it. `get_command_receipt` checks receipt columns, canonical result JSON and result digest without locking target heads; the service validates referenced heads only after locking the command's full admission. `get_current_verified` accepts the expected full admission ref and verifies target rows under its lock, but does not acquire the upstream admission lock itself. `record_command` relies on the scoped unique key; an absent command row is never considered locked.

- [ ] Extend the vector tests RED for typed digest functions, including the `1e-7` numeric bytes, full admission ref, Shot's SCENE dependency type/version/digest, and separate registry/body versions. Add command/result vectors with one exact replay and one changed-admission variant before implementing digest helpers.
- [ ] Implement the smallest contracts and digest helpers that make those vectors GREEN; do not change existing M8 or Preparation canonical serializers.
- [ ] Write repository tests that tamper each stored body/version/head/scene dependency/command result in turn and require a typed integrity conflict on read or replay. Check the head points to the maximum stored version and all stored digests are recomputed from JSON rather than trusted as columns. Exercise genesis insert-if-absent followed by immediate lock/read for every key in Scene-then-Shot order.
- [ ] For a Shot current read, capture primitive Scene-dependency hint values before any target lock, lock Scene then Shot, re-read both with ORM identity refresh, compare the immutable hint and verify Scene is still current. Force a coherent same-version Shot row/digest change between hint and lock to prove the comparison catches identity-map refresh.
- [ ] Prove a consumer that starts with only a target ID treats its first admission lookup as an untrusted hint, locks/verifies that admission, then locks/re-reads and compares the target. A changed hint or target head must fail; do not acquire a target lock before admission. Keep this orchestration with the consumer packet if no consumer is implemented in Task 2.
- [ ] Implement the scoped repository and run the affected unit/repository selection on SQLite and PostgreSQL. Commit the contracts, vectors, repository and tests.

### Task 3: Atomic Take Bundle Registration

**Files:**
- Create: `r2/target_registry/service.py`
- Modify: `r2/production_intelligence/take_director.py` only to expose a pinned `TAKE_DERIVATION_VERSION` constant with value `r2-take-director-v1`
- Create: `tests/integration/r2/target_registry/test_take_registration.py`

**Interfaces:**
- Produce `RegisterTakeTargetsCommand(user_id, project_name, principal, command_id, admitted_screenplay_ref)` and `TakeTargetRegistrationService.register(command: RegisterTakeTargetsCommand) -> TargetRegistrationResult` over a caller-supplied session factory. The trusted caller, not a candidate or free-form request body, supplies user/project/principal. The service owns one session/transaction and constructs `TransactionBoundApprovedScreenplayReader(AdaptationRepository(session), expected_admission=command.admitted_screenplay_ref)` from the prerequisite packet.
- The service uses `TakeDirectorAdapter`, checks `APPROVED`, unique IDs and exact Shot→Scene membership, locks target heads SCENE IDs ascending then SHOT IDs ascending, revalidates each current row, appends only changed semantic versions and records one command receipt in the same transaction.

- [ ] Write RED integration tests with real persisted admissions for exact registration, wrong scope, stale decision, forged profile, two successive admissions retaining target IDs/body version `1` but changing body and registry version, exact same-command replay, stale replay and changed-command conflict.
- [ ] Implement only the Take path. Verify a new Shot version binds the Scene registry version selected in the same transaction, even when only the admission provenance changes. A writer must not accept a caller-provided SceneSpec/ShotSpecV2 as target authority.
- [ ] Run the whole affected admission/Take/registry test selection on SQLite and PostgreSQL; run Ruff, basedpyright, import contracts, deptry and test audit. Commit only the service/constant/tests after GREEN.

### Task 4: PostgreSQL Interleavings and Fault Rollback

**Files:**
- Create: `tests/integration/r2/target_registry/test_take_registration_concurrency.py`
- Modify: `r2/target_registry/service.py` and `lib/db/repositories/production_target.py` only for concrete defects exposed by these tests

**Interfaces:**
- Keep the Task 3 API and transaction ownership unchanged.

- [ ] Force a re-admission writer to reach its own locked admission-head update while registration holds the head and has not committed. Identify that writer's backend PID or a test-owned SQL barrier, then release registration and prove the resulting target version is tied to the admission that was current at its commit.
- [ ] Force two registration commands for the same target bundle to overlap after derivation, including the first creation of absent Scene/Shot heads; assert a single monotonic head sequence, exact replay for identical input, typed conflict for changed input, and no committed genesis or partial Scene/Shot set. Also race one command ID across different target bundles: the unique-key loser must roll back its whole attempt before reading the winner in a new transaction. Inject a flush failure after Scene append and assert rollback of all versions, heads and command receipt.
- [ ] Run these tests on disposable PostgreSQL 16 with `-n 4 --dist loadfile`, then rerun the complete affected selection and repository static gates on the final code HEAD. Obtain independent exact-HEAD review before marking target registry accepted; keep binding, pair and production gates closed.
- [ ] Commit only verified fixes and the exact-HEAD evidence packet.

## Plan Self-Review

The four tasks cover the target-registry prerequisite from the proposed spec, not binding authority or M8-C acceptance. They preserve one transaction, verified upstream admission, full profile provenance, deterministic locks, canonical digest domains, scoped FKs, replay, rollback and adversarial reads. The five review-focus classes each map to a named task test. The plan depends on the transaction-bound reader packet and on design review of ADR-0102; no implementation or production authorization is implied by this document.

## Task 1 execution checkpoint — 2026-10-05

Schema/migration/test commit `67760c9d06cb8c689ca3783234dee411551fde59` adds the three scoped tables. The new migration test failed first because revision `8c8c4a0e0001` was absent. A later test caught SQL three-valued `CHECK` behavior that accepted a Shot with null scene registry version; the model and migration now explicitly require nonnull version. The affected SQLite migration suite returned **8 passed**; the complete affected SQLite selection returned **46 passed, 2 PostgreSQL-only skipped**. On disposable PostgreSQL 16, `upgrade head`, downgrade to `8b8c4a0e0001` and re-upgrade succeeded, a real Scene/Shot bundle inserted and a partial Shot dependency was rejected. The affected admission/Take/vector selection returned **40 passed** with `-n 4 --dist loadfile`. Ruff, changed-file formatting, basedpyright (**0 errors, 0 warnings**), lint-imports (**22 kept**), deptry, test audit (**0 violations**) and `git diff --check` passed. The PostgreSQL container was stopped and auto-removed. No registry repository or writer exists yet; Task 2 remains open, as do independent review and authority acceptance.

## Task 2 digest checkpoint — 2026-10-05

Commit `ceb6c30017eae57bc68e5fdaecb68b312ee47a8e` adds typed target-version, scene-dependency and registration command/result bodies plus Preparation-canonical digest helpers. The new test first failed because `r2.target_registry` did not exist, then all **6 vector/adversarial tests passed**. It checks the fixed Scene/Shot and command/result hashes, small floating duration, wrong target type, missing Shot scene dependency and duplicate target refs. Ruff, changed-file format, basedpyright (**0 errors, 0 warnings**) and test audit (**0 violations**) passed. This is only the pure digest portion of Task 2; verified repository reads, append/head operations, command replay and PostgreSQL concurrency remain open.

## Task 2 current-read checkpoint — 2026-10-05

Commit `06c29983276e40b9661e5696afcea34c9b692bdd` adds scoped `get_current_verified` over the caller's session. It checks head/latest version, body and version rehash, exact full expected admission, approved Scene/Shot body, Shot scene ID and current Scene dependency. For Shot it reads an untrusted dependency hint, locks Scene before Shot, captures primitive hint values and re-reads with `populate_existing`; a coherent same-version row/digest change between hint and lock is rejected. The test first failed because the repository module was absent; the repository selection returned **9 passed on SQLite** and **9 passed on disposable PostgreSQL 16**. The combined affected selection returned **57 passed, 2 PostgreSQL-only skipped** on SQLite and **59 passed** on PostgreSQL with `-n 4 --dist loadfile`. Ruff, changed-file formatting, basedpyright (**0 errors, 0 warnings**), lint-imports (**22 kept**), deptry, test audit (**0 violations**) and `git diff --check` passed; the PostgreSQL container was stopped and auto-removed. The caller must still lock and validate upstream admission before invoking this local integrity reader. Command receipts, head creation, append/advance and replay remain unimplemented, so Task 2 and target authority are not accepted.

## Task 2 repository-write checkpoint — 2026-10-05

Code/test commit `efffa2cbb1702825c3f493174e0b0f9fc043fe7d` adds scoped command receipt integrity/conflict reads, insert-if-absent genesis head claim followed by a lock, canonical Scene/Shot version append, expected-predecessor head advance and command receipt write. Each method retains the caller's session and does not commit. The new test first failed on the missing command-conflict API. It exercises receipt scope and corrupt JSON/digest/command columns, ordered Scene then Shot registration, full rollback including a recorded receipt, wrong head predecessor, and second-admission version advancement while preserving history. The affected selection returned **55 passed, 2 PostgreSQL-only skipped** on SQLite and **57 passed** on disposable PostgreSQL 16 with `-n 4 --dist loadfile`; both runs emitted two existing SQLAlchemy expression-index reflection warnings from the migration tests. Ruff check and format on changed files, basedpyright (**0 errors, 0 warnings**), lint-imports (**22 kept**), deptry, test audit (**0 violations**) and staged diff check passed. This is a repository primitive checkpoint, not an accepted registration service: upstream admission lock ownership, referenced-target replay validation, concurrent unique-command loser retry, forced PostgreSQL interleavings and independent exact-diff review remain open. Continue with Task 3 using `TransactionBoundApprovedScreenplayReader` and `TakeDirectorAdapter`, then Task 4 concurrency and rollback gates. Do not touch the separate C1 worktree or activate a live migration/provider.
