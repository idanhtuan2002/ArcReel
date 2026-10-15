# R2-M9A Foundation and Cohort Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this packet task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change. Execute A0–A4 sequentially because they share one contract, migration and profile-authority boundary.

**Goal:** Establish the accepted M9 lineage gate, frozen contracts/digests/parity fold and Human-custodied append-only opportunity cohort profiles.

**Architecture:** M9 contracts reuse the accepted M8 canonical foundation while remaining a distinct module. A scoped PostgreSQL aggregate stores profile revisions, CAS heads and actor-scoped command receipts. Profile publication uses receipt preflight, a replayable 30-second Human authorization lease outside the transaction, a PostgreSQL transaction-scoped command-key guard, then atomic head/event/receipt finalization before exposing three authenticated profile endpoints.

**Tech Stack:** Python 3.12+, Pydantic 2.12+, SQLAlchemy 2.0 async, Alembic, PostgreSQL, FastAPI 0.138+, pytest, ruff, basedpyright, import-linter and deptry.

**Spec:** `docs/superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md`

**Umbrella:** `docs/superpowers/plans/2026-09-14-r2-m9-opportunity-research-intelligence.md`

**Execution contract:** `docs/r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json`

## Non-interactive execution rule

Read ADR-0081, the design, research, umbrella, execution contract and this packet before changing production files. Execute only in clean branch `impl/r2-m9a-opportunity-foundation`, created from the commit accepting `R2_M9_PREREQUISITE_ACCEPTANCE.json`. Never execute on a design branch (`design/r2-m5b-narrative-context`, `design/r2-m9-v2-revalidation` or any other `design/*`).

This packet is `PACKET_AUTHORED_FOR_REVIEW` and
`PACKET_EXECUTION_BLOCKED`. The **A0-preflight gate** is a read-only prerequisite
check and the only permitted action before acceptance; it is not Task A0
implementation and creates no production file. The preflight stops all further
activity before every prerequisite passes; it may use already accepted verifier
tooling and emit the uncommitted `docs/r2/evidence/R2_M9_STOP.json`, but it may
not create or modify production files. After all checks pass, the implementation
worktree base is the commit accepting `R2_M9_PREREQUISITE_ACCEPTANCE.json`, whose
parent is the bound clean combined base. Do not select a substitute authority,
canonicalizer, migration base, credential source, donor version or sponsor
input.

The only successful terminal state is a clean `M9_A_CANDIDATE` evidence HEAD awaiting independent Codex review. Do not begin M9-B.

Prerequisite failure routing is exact:

| Failed check | Stop code |
|---|---|
| ADR/spec/plan/execution-contract acceptance absent, rejected or hash-drifted | `M9_DESIGN_NOT_ACCEPTED` |
| accepted M8 implementation absent or rejected | `M9_M8_IMPLEMENTATION_NOT_ACCEPTED` |
| combined-base acceptance, clean worktree, disposable PostgreSQL evidence or the profile custodian's `HUMAN_SHOWRUNNER` grant absent | `M9_REQUIRED_EVIDENCE_MISSING` |
| accepted canonical/M8 import, factual contract import, signature, behavior or Alembic seam differs | `POST_M8_BASE_SEAM_CHANGED` |
| selected donor pin/path/inventory cannot be proven | `M9_DONOR_PARITY_INCOMPLETE` |
| execution would require changing a frozen M9 contract or digest domain | `M9_SCHEMA_CHANGE_REQUIRED` |

Write exactly one stop receipt using the first failure in this table order while retaining all detected failures in `failed_checks`.

## Exact owned file map

Create:

- `r2/contracts/opportunity.py`
- `r2/opportunity/__init__.py`
- `r2/opportunity/digests.py`
- `r2/opportunity/errors.py`
- `r2/opportunity/ports.py`
- `r2/opportunity/parity.py`
- `r2/opportunity/profiles.py`
- `lib/db/models/opportunity.py`
- `lib/db/repositories/opportunity.py`
- `server/services/opportunity.py`
- `server/routers/opportunity.py`
- `server/services/m9_custodian.py` — host custodian adapter over the ADR-0103 showrunner grants (spec §9)
- `lib/db/models/host_custodian.py` — `host_custodian_leases` ORM (host-owned replay state)
- `tests/integration/server/services/test_m9_custodian.py`
- `scripts/r2/verify_m9_scope.py`
- `scripts/r2/verify_m9_parity.py`
- `scripts/r2/verify_m9_evidence.py`
- `alembic/versions/9a9c4a0e0001_add_m9_opportunity_foundation.py`
- `tests/unit/r2/contracts/test_opportunity.py`
- `tests/unit/r2/opportunity/test_digests.py`
- `tests/unit/r2/opportunity/test_parity.py`
- `tests/unit/r2/opportunity/test_profiles.py`
- `tests/unit/scripts/r2/test_verify_m9_scope.py`
- `tests/unit/scripts/r2/test_verify_m9_parity.py`
- `tests/unit/scripts/r2/test_verify_m9_evidence.py`
- `tests/unit/server/routers/test_opportunity_router.py`
- `tests/integration/lib/db/migrations/test_alembic_m9_foundation.py`
- `tests/integration/lib/db/repositories/test_opportunity_profiles.py`
- `tests/integration/r2/opportunity/test_profile_concurrency.py`
- `tests/architecture/test_m9_opportunity_boundaries.py`
- `docs/r2/evidence/schemas/R2_M9_BASELINE.schema.json`
- `docs/r2/evidence/schemas/R2_M9_A_FOUNDATION.schema.json`
- `docs/r2/evidence/R2_M9_BASELINE.json`
- `docs/r2/evidence/R2_M9_A_FOUNDATION.json`

Modify only when exact accepted integration requires it:

- `r2/contracts/__init__.py` — public opportunity exports.
- `lib/db/models/__init__.py` — one ORM registration export.
- `lib/db/repositories/__init__.py` — one repository export.
- `server/app.py` — one router registration.
- `lib/i18n/en/errors.py`, `lib/i18n/vi/errors.py`, `lib/i18n/zh/errors.py` — stable M9 API error text.

No other production path is owned. If an accepted prerequisite cannot be adapted through this map, emit `POST_M8_BASE_SEAM_CHANGED`; generated caches, unrelated formatting and opportunistic refactors are outside scope.

## Fixed HTTP surface

Mount `opportunity.router` under `/api/v1` in `server/app.py` with `Depends(require_project_migration_ok)`. The publish route depends on `get_current_interactive_user`, so API keys and the auth-disabled anonymous user are refused; read routes depend on `get_current_user`. Handlers derive `user_id = current_user.id` and `actor_id = current_user.sub` (the ADR-0103 grant principal), and `project_name` from the path. Bodies cannot provide or override those values.

| Method | Route | Input | Success |
|---|---|---|---|
| `POST` | `/projects/{project_name}/m9/opportunity/cohort-profiles` | `PublishCohortProfileRequest` | `CohortProfileReceipt`, 200 for new or exact replay |
| `GET` | `/projects/{project_name}/m9/opportunity/cohort-profiles?after_id=&limit=` | `1 <= limit <= 100` | current head profile per logical ID, 200 |
| `GET` | `/projects/{project_name}/m9/opportunity/cohort-profiles/{profile_id}?revision=` | optional `revision >= 1` | current or exact historical profile, 200 |

Router-local request model:

```python
class PublishCohortProfileRequest(M8ContractModel):
    command_id: str
    profile_id: str
    parent_revision: int | None
    expected_head_version: int | None
    payload: OpportunityCohortProfilePayload
```

The router constructs `CommandContext(command_id, current_user.id, project_name, current_user.sub)`, and the custodian queries `GrantScopeV1(current_user.id, project_name, principal=current_user.sub)`. RED tests cover an API-key caller, auth disabled and a principal without a grant. Error mapping is fixed: validation 422; authentication 401; `M9_PROFILE_PUBLICATION_UNAUTHORIZED` 403; not-found 404; `M9_COMMAND_REPLAY_CONFLICT`, `M9_STALE_HEAD` and `M9_COHORT_LEAKAGE` 409; prerequisite/schema/seam errors 503. Error bodies contain stable stop code plus localized detail and reveal no foreign owner.

## Fixed persistence map

Migration `9a9c4a0e0001` creates exactly:

- `m9_cohort_profiles`: scope, profile ID, revision, parent revision, canonical payload JSON, payload/profile digests, creator, custodian authorization/policy/evidence identity, admitted time and aware creation time; primary key `(user_id, project_name, profile_id, revision)`; unique profile digest within scope; genesis/parent check.
- `m9_cohort_profile_heads`: scope, profile ID, current revision and head version; primary key `(user_id, project_name, profile_id)`; both versions positive.
- `m9_command_receipts`: scope, actor, operation, command ID, request digest, result kind/ref/digest, committed time; unique `(user_id, actor_id, operation, command_id)` and scoped result index.
- `m9_events`: monotonic event ID, scope, event kind, aggregate identity/revision, payload digest and committed time; no raw/profile payload or token-like fields.
- `host_custodian_leases` (host-owned, not an M9 authority table): user, project, actor, operation, command ID, subject digest, authorization ID, policy ID/version, grant event digest, issued time and `admit_not_after`; unique `(user_id, project_name, actor_id, operation, command_id)`; `admit_not_after` never exceeds the grant's `expires_at`. The M9-A migration owns creation and downgrade of this host replay table, so downgrade requires host custodian callers quiesced and dependent packets removed first; it is not an independently surviving host schema. A replay with the same subject returns the stored lease; a different subject, or an expired lease, is refused (spec §9).

Rows in profiles, receipts and events are append-only. Only profile-head CAS updates. Repository methods flush but never commit; the application service owns begin/commit/rollback.

## Task A0 implementation: Freeze accepted lineage, seams and scope

**Files:** `scripts/r2/verify_m9_scope.py`, its unit test, baseline schema and `R2_M9_BASELINE.json`.

**Consumes:** execution contract plus accepted M8 and M9 design-acceptance artifacts. (M9-A uses only the existing factual contracts; the durable Factual Authority is gated at M9-D.)

**Produces:** `verify_m9_scope(repo: Path, contract: Mapping[str, object]) -> list[str]` and a baseline binding exact HEAD, singleton Alembic predecessor, document hashes, seam hashes, donor pins and owned paths.

- [ ] **A0.1 — Write verifier RED tests.** Parameterize dirty worktree; design branch; absent/rejected M9 design acceptance; invalid sealed-review schema; duplicate reviewer identity/output ref; review-output hash mismatch; candidate/contract/rubric mismatch; incomplete or failed rubric checks; seal/share ordering violation; absent M8 acceptance; absent or invalid combined-base acceptance (`R2_M9_PREREQUISITE_ACCEPTANCE.json`, umbrella Task P0); acceptance-parent mismatch; wrong accepted status; SHA/document/seam drift; multiple Alembic heads; missing donor pin; required skip/material unknown; and owned-path collision. Each fixture asserts one normative stop code and verifies no production file is created.

- [ ] **A0.2 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/unit/scripts/r2/test_verify_m9_scope.py -q
  ```

  Expected: collection/import failure because the verifier is absent; zero collected tests is failure.

- [ ] **A0.3 — Implement the fail-before-write verifier.** Run
  `scripts.r2.verify_m9_design_acceptance.verify_repository` before trusting the
  M9 acceptance record; the sealed-review check is only one internal stage.
  Parse JSON with duplicate-key rejection,
  validate both sealed outputs, recompute SHA-256, enforce distinct reviewers
  and output refs, exact candidate/contract/rubric equality, complete PASS
  checks and seal-before-share order; then require a clean non-design branch,
  prove acceptance parent/HEAD ancestry, run `uv run alembic heads`, and inspect
  exact accepted symbols/import paths. Return all failures in deterministic
  check order without modifying the repository.
  Task A0 implementation reruns the same repository entry point and treats any
  artifact mismatch, non-status ADR change, acceptance-parent
  mismatch, extra acceptance path or dirty tree as `M9_DESIGN_NOT_ACCEPTED`.

- [ ] **A0.4 — Write and verify baseline evidence.** Schema rejects unknown fields and requires `schema_version`, `status`, `base_head`, `branch`, `alembic_predecessor`, `m8_acceptance`, `m9_design_acceptance`, document/seam hashes, donor pins, scope allowlist, required skips, material unknowns and creation time. `status` is `M9_BASELINE_VERIFIED`; skip/unknown arrays are empty.

- [ ] **A0.5 — Run GREEN and commit.** Run:

  ```bash
  uv run python -m pytest tests/unit/scripts/r2/test_verify_m9_scope.py -q
  uv run python scripts/r2/verify_m9_scope.py docs/r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json
  git diff --check
  ```

  Expected: tests pass, verifier prints `M9_BASELINE_OK`, one Alembic head is recorded and diff check passes. Stage only A0 files and commit `test(r2): freeze M9 accepted baseline`.

## Task A1: Implement frozen contracts, digests, ports and parity

**Files:** contract/opportunity modules, exports, contract/digest/parity tests, parity verifier and architecture test.

**Consumes:** accepted M8 `M8ContractModel`, `CanonicalJsonObject`, `Sha256Digest`; current factual contracts.

**Produces:** every spec §§4–7 class/protocol, every §8 digest function, `evaluate_m9_parity(report, integrated_head) -> ParityVerdict` and stable error types.

- [ ] **A1.1 — Write contract RED tests.** Cover extra-field rejection; frozen assignment and nested deep-copy; aware UTC; UUIDv7/slug/SHA formats; every enum wire value; forward-reference rebuild; profile uniqueness/dimensions/candidate expiry; command genesis/append pairs; retained-digest names; Canvas scope; validity projection; invalidation target non-emptiness; and all normative cross-field rules from §7.1.

- [ ] **A1.2 — Write digest RED tests.** For each §8 domain, assert stable canonical JSON under mapping-order changes, Unicode preservation, domain separation, semantic-field sensitivity and exclusion of server-assigned request fields. Add bridge fixture proving M9 creative-content digest maps into M8 content basis only at the explicit Canvas adapter.

- [ ] **A1.3 — Write parity/verifier RED tests.** Reject wrong donor SHA/path, missing reachable behavior, required skip, material unknown, excluded applicable row, below-parity dimension, stale integrated HEAD, duplicate row and donor-defect claim without fail-donor/pass-R2 fixture.

- [ ] **A1.4 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/unit/r2/contracts/test_opportunity.py tests/unit/r2/opportunity/test_digests.py tests/unit/r2/opportunity/test_parity.py tests/unit/scripts/r2/test_verify_m9_parity.py tests/architecture/test_m9_opportunity_boundaries.py -q
  ```

  Expected: missing-module failures; zero collected tests is failure.

- [ ] **A1.5 — Implement the minimum contracts and pure folds.** Copy no M8 canonicalizer. Import the A0-recorded accepted module, implement exact domain-tag functions and parity recomputation, and expose only protocols at external seams. Architecture tests reject imports of credentials, direct provider SDKs, M8/Factual repositories, Canon/Narrative/Production writers and commit calls from repository modules. `OpportunityCohortProfilePayload.creative_profile_id` accepts only the exact identities the accepted M8 lineage carries (`WESTERN_GENERIC`, `CN_SHORT_DRAMA_SHUANGWEN`, `arcreel.host`; ADR-0105) and refuses labels such as `generic-western`, with a RED test. Its required `creative_policy_pack_digest` byte-equals the admitted M6 policy pack or the accepted host policy digest. RED tests change only that digest while keeping profile ID/version equal, and prove profile/closure/payload/lineage hash sensitivity and `M9_COHORT_LEAKAGE` for queries, M8 evidence and seeds in their owning packets.

- [ ] **A1.6 — Run GREEN and static checks.** Run the A1 selection, then:

  ```bash
  uv run ruff check r2/contracts/opportunity.py r2/opportunity scripts/r2/verify_m9_parity.py tests/unit/r2 tests/unit/scripts/r2 tests/architecture/test_m9_opportunity_boundaries.py
  uv run basedpyright r2/contracts/opportunity.py r2/opportunity scripts/r2/verify_m9_parity.py
  ```

  Expected: zero failures/warnings relevant to owned files. Stage only A1 files and commit `feat(r2): define M9 opportunity contracts`.

## Task A2: Persist append-only cohort profiles and receipts

**Files:** ORM, repository, migration, exports and migration/repository/concurrency tests.

**Consumes:** `OpportunityCohortProfile`, head, command/receipt and digest contracts.

**Produces:** `OpportunityProfileRepository` with scoped `get_exact`, `get_head_for_update`, `list_heads`, `get_command_receipt`, `stage_profile`, `stage_head`, `stage_command_receipt`, `stage_event`; `OpportunityUnitOfWork` owns one `AsyncSession` transaction.

- [ ] **A2.1 — Write migration RED tests.** Assert exact five-table set (four M9 tables plus the host-owned `host_custodian_leases`), named PK/unique/check/index constraints, `revision='9a9c4a0e0001'`, `down_revision` equal A0 baseline predecessor, one Alembic head and downgrade removal of only those five tables.

- [ ] **A2.2 — Write repository RED tests on disposable PostgreSQL.** Cover genesis race, append race, parent mismatch, head-version mismatch, immutable historical bytes, exact scoped lookup/list pagination, foreign/unknown equivalence, absent-receipt concurrent first calls, transaction-scoped command-key guard serialization, equal-digest winner reread, divergent-digest conflict and rollback after every staged flush. Include a synthetic advisory-hash collision proving the full receipt key remains authority and collision only serializes.

- [ ] **A2.3 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/integration/lib/db/migrations/test_alembic_m9_foundation.py tests/integration/lib/db/repositories/test_opportunity_profiles.py tests/integration/r2/opportunity/test_profile_concurrency.py -q
  ```

  Expected: missing migration/model/repository failures. If no repository-attested disposable PostgreSQL target exists, emit `M9_REQUIRED_EVIDENCE_MISSING` and stop; SQLite is not a substitute.

- [ ] **A2.4 — Implement schema and repository.** Follow accepted `Base`, aware-time and `AsyncSession` conventions. Scope predicates precede existence interpretation. Canonicalize `m9.command-key-guard.v1` plus the full command tuple, SHA-256 it, convert the first eight bytes into two signed big-endian 32-bit integers for `pg_advisory_xact_lock`, acquire that transaction-scoped guard before receipt/head locks, re-read the full receipt key under the guard, sort IDs lexicographically, flush without commit, and translate uniqueness/CAS races into exact replay or stable conflict. Never use the advisory hash as identity or authorization.

- [ ] **A2.5 — Run GREEN and reversible migration proof.** Run A2 tests, then upgrade → downgrade to A0 predecessor → upgrade → `uv run alembic heads` on the same disposable database. Expected: exact row/history behavior, one head `9a9c4a0e0001`, no leaked M9 table after downgrade.

- [ ] **A2.6 — Commit.** Stage only A2 files/exports and commit `feat(db): persist M9 cohort profiles`.

## Task A3: Publish and read cohort profiles through the scoped API

**Files:** `profiles.py`, service/route composition, app/i18n modifications and service/router/architecture tests.

**Consumes:** profile repository/UoW and `OpportunityProfileCustodianPort.authorize_publication(command_id, ProfilePublicationSubject) -> CustodianAuthorizationLease`.

**Produces:** exact `publish_cohort_profile`, `list_cohort_profiles` and `get_cohort_profile` protocols plus the fixed HTTP surface.

- [ ] **A3.1 — Write service RED tests.** Cover principal/actor mismatch, cross-project command UUID reuse yielding a conflict without revealing a receipt, unauthorized/non-Human custodian, scope mismatch, invalid profile rules, same command/same digest exact replay after later head change without a custodian call, same command/different digest conflict, genesis/append/CAS mismatch, concurrent first publishers, crash after authorization/before transaction, lost commit acknowledgement, changed-subject custodian replay, authorization/policy/evidence mismatch, expired or over-30-second lease, refusal to refresh an expired unadmitted lease under the same command ID, admission at the deadline, policy change before a new lease, 24-hour candidate-expiry bound and cross-cohort corpus/calibration reuse.

- [ ] **A3.2 — Write router RED tests.** Cover authentication and migration dependencies, path-derived scope, body scope injection rejection, all fixed HTTP mappings, limit/revision bounds, current-head list semantics, historical read semantics and byte-equivalent replay response.

- [ ] **A3.3 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/unit/r2/opportunity/test_profiles.py tests/unit/server/routers/test_opportunity_router.py tests/integration/r2/opportunity/test_profile_concurrency.py tests/architecture/test_m9_opportunity_boundaries.py -q
  ```

- [ ] **A3.4 — Implement receipt-first publication.** Preflight the full receipt key first; exact completed replay returns byte-equivalent output before currentness or custodian calls and changed replay conflicts. For an absent command, validate request shape, call `authorize_publication` outside a database transaction, and require a replayed lease for the exact command/subject/policy. Open one transaction, acquire the command-key advisory guard, re-read the full receipt key, resolve a concurrent winner, validate and admit the lease with database time no later than its maximum 30-second deadline, then lock the profile head. Revalidate currentness, append profile/head/event/receipt and commit once. Crashes roll back all staged rows; a retry after lost commit acknowledgement returns the original receipt without reauthorization.

- [ ] **A3.5 — Implement routes and localized errors.** Register one router, inject service/clock/ID sources, and add every new backend error key to English, Vietnamese and Chinese catalogs. No endpoint accepts credentials, raw payloads, model decisions or direct database objects.

- [ ] **A3.6 — Run GREEN and regressions.** Run A3 selection plus:

  ```bash
  uv run python -m pytest tests/unit/lib/i18n/test_i18n_consistency.py -q
  uv run lint-imports
  uv run deptry lib server alembic scripts tests r2
  ```

  Expected: non-zero test counts, zero failures/skips and no boundary violation. Stage only A3 paths and commit `feat(r2): add custodied M9 cohort profiles`.

## Task A4: Seal machine-verifiable M9-A evidence

**Files:** M9-A evidence schema/JSON plus verifier tests already owned.

**Consumes:** clean A3 code HEAD.

**Produces:** independently reviewable `R2_M9_A_FOUNDATION.json`; Claude records candidate status only.

- [ ] **A4.1 — Extend evidence-verifier RED tests.** Schema rejects unknown/missing fields and false PASS. Require `schema_version`, `status`, `tested_head`, `tested_parent`, `branch`, baseline/document/contract/seam/migration digests, scope allowlist, commands with exit/test counts/log digests, fault matrix, cross-scope/concurrency/architecture results, donor inventory, required skips, material unknowns, graph coverage, artifacts, independent review and creation time.

- [ ] **A4.2 — Run complete affected gates.** Because A2 changes DB/Alembic and A3 changes router/i18n, run:

  ```bash
  uv run ruff check .
  uv run ruff format .
  uv run basedpyright --warnings
  uv run lint-imports
  uv run deptry lib server alembic scripts tests r2
  uv run python -m pytest <every test path owned or affected by M9-A, listed explicitly>
  uv run python scripts/audit_tests.py --check
  git diff --check
  ```

  Expected: every command exits 0, the explicit selection has non-zero tests, and required skips/material unknowns remain empty. The full suite runs only on explicit sponsor request (`ARCREEL_FULL_SUITE=1`, repository rule).

- [ ] **A4.3 — Run focused fault and evidence gates.** Re-run A0–A3 tests explicitly, migration round trip, PostgreSQL concurrency, scope/architecture verifier and parity verifier. Save logs outside the repository, record SHA-256/logical test counts and verify the recorded tested HEAD equals the clean A3 code HEAD.

- [ ] **A4.4 — Refresh graph coverage.** At candidate HEAD, record codebase-memory project/generation; call coverage check for every changed file; read every reported missed range directly; rerun the architecture bypass scan. A clean best-effort signal is recorded as such, never as proof of completeness.

- [ ] **A4.5 — Commit and stop.** Write `R2_M9_A_FOUNDATION.json` with `status: M9_A_CANDIDATE`, empty required skips/material unknowns and no claimed independent approval. Stage only schema/evidence files, commit `test(r2): prove M9 opportunity foundation`, verify clean status, then stop. The evidence commit parent is the tested A3 code HEAD; do not push, start M9-B, migrate a live database or activate a provider.
