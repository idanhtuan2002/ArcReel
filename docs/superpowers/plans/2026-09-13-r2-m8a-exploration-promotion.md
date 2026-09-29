# R2-M8A Exploration and Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`
> to implement this packet task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking. Use `superpowers:test-driven-development` for every behavior change.
> Do not dispatch parallel implementers across A0-A4 because they share one
> migration, repository and transaction boundary.

**Goal:** Establish the shared M8 contracts, donor-parity gate, append-only
exploration revisions and preview-bound atomic promotion.

**Architecture:** Frozen contracts and pure digest/parity folds sit above a
scoped PostgreSQL repository. One promotion service revalidates candidate,
preview, target, master and authorization inside the accepted M7 unit of work;
M8 never adds another Production or ProductionBinding writer.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async, Alembic,
PostgreSQL 18, FastAPI, pytest, ruff, basedpyright, import-linter and deptry.

**Spec:** `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`

**Umbrella:** `docs/superpowers/plans/2026-09-13-r2-m8-canvas-learning-multiformat.md`

**Execution contract:** `docs/r2/evidence/R2_M8_EXECUTION_CONTRACT_2026-09-13.json`

## Non-interactive execution rule

This packet is executable without architectural questions. Read the ADR, spec,
umbrella, execution contract and this packet before changing a file. An executor
must not choose a substitute authority, relax a contract, invent missing sponsor
evidence or continue across a failed prerequisite. On any such condition, write
the uncommitted `docs/r2/evidence/R2_M8_STOP.json` receipt with every field named
by the execution contract, report its stop code and stop.

Execute only in a clean implementation worktree created from the commit that
adds `docs/r2/evidence/R2_M7_IMPLEMENTATION_ACCEPTANCE.json`. That commit must
change only the independent acceptance artifact, its parent must equal the
accepted M7-E candidate HEAD, and its status must be `M7_IMPLEMENTATION_ACCEPTED`.
Never execute on
`design/r2-m5b-narrative-context`. The implementation branch name is
`impl/r2-m8a-exploration-promotion`. A caller may choose the worktree directory;
the branch, HEAD and cleanliness checks are normative.

The only successful terminal state is a clean M8-A evidence HEAD awaiting
independent Codex review. Do not begin M8-B.

## Exact owned file map

Create:

- `r2/contracts/advanced_creative.py`
- `r2/advanced_creative/__init__.py`
- `r2/advanced_creative/digests.py`
- `r2/advanced_creative/errors.py`
- `r2/advanced_creative/ports.py`
- `r2/advanced_creative/parity.py`
- `r2/advanced_creative/exploration.py`
- `r2/advanced_creative/promotion.py`
- `lib/db/models/advanced_creative.py`
- `lib/db/repositories/advanced_creative.py`
- `server/services/advanced_creative.py`
- `server/routers/advanced_creative.py`
- `scripts/r2/verify_m8_scope.py`
- `scripts/r2/verify_donor_parity.py`
- `scripts/r2/verify_m8_evidence.py`
- `alembic/versions/8a8c4a0e0001_add_exploration_authority.py`
- `tests/unit/r2/contracts/test_advanced_creative.py`
- `tests/unit/r2/advanced_creative/test_digests.py`
- `tests/unit/r2/advanced_creative/test_parity.py`
- `tests/unit/r2/advanced_creative/test_exploration.py`
- `tests/unit/r2/advanced_creative/test_promotion.py`
- `tests/unit/scripts/r2/test_verify_m8_scope.py`
- `tests/unit/scripts/r2/test_verify_donor_parity.py`
- `tests/unit/scripts/r2/test_verify_m8_evidence.py`
- `tests/unit/server/routers/test_advanced_creative_router.py`
- `tests/integration/lib/db/migrations/test_alembic_m8_exploration.py`
- `tests/integration/lib/db/repositories/test_advanced_creative.py`
- `tests/integration/r2/advanced_creative/test_promotion_atomicity.py`
- `tests/architecture/test_m8_advanced_creative_boundaries.py`
- `docs/r2/evidence/schemas/R2_M8_BASELINE.schema.json`
- `docs/r2/evidence/schemas/R2_M8_A_EXPLORATION_PROMOTION.schema.json`
- `docs/r2/evidence/R2_M8_BASELINE.json`
- `docs/r2/evidence/R2_M8_A_EXPLORATION_PROMOTION.json`

Modify only when required by the exact integration:

- `r2/contracts/__init__.py` — public contract exports.
- `lib/db/models/__init__.py` — ORM registration exports.
- `lib/db/repositories/__init__.py` — repository export.
- `server/app.py` — one authenticated/migration-gated router registration.
- `lib/i18n/en/errors.py`, `lib/i18n/vi/errors.py`, `lib/i18n/zh/errors.py` — exact
  M8 API error keys.

No other production path is allowed. If the accepted M7 seam cannot be adapted
through this list, stop `M8_BASE_SEAM_CHANGED`; do not expand scope. Generated
caches, unrelated formatting and opportunistic refactors are forbidden.

## Fixed API surface

Mount `advanced_creative.router` under `/api/v1` in `server/app.py` with both
`Depends(get_current_user)` and `Depends(require_project_migration_ok)`.
Handlers receive `CurrentUser` and pass `current_user.id` plus the path
`project_name`; request bodies cannot override either value. Append requires
`candidate.created_by == current_user.id`; promotion requires
`authorization.actor_id == current_user.id`; lineage/authorization project names
must equal the path project before any repository call.

| Method | Route | Request model | Success |
|---|---|---|---|
| `POST` | `/projects/{project_name}/m8/exploration/revisions` | `AppendRevisionRequest` | `CandidateHead`, 200 new or exact replay |
| `GET` | `/projects/{project_name}/m8/exploration/candidates/{candidate_id}/revisions/{revision}` | none | `ExplorationRevision`, 200 |
| `GET` | `/projects/{project_name}/m8/exploration/candidates/{candidate_id}/revisions?after_revision=&limit=` | query, `1 <= limit <= 100` | tuple/list of revisions, 200 |
| `POST` | `/projects/{project_name}/m8/exploration/promotion-previews` | `CreatePromotionPreviewRequest` | `PromotionPreview`, 200 new or exact replay |
| `POST` | `/projects/{project_name}/m8/exploration/promotions` | `PromoteExplorationRequest` | `PromotionReceipt`, 200 new or exact replay |

The router-local frozen request models are exact wrappers:

```python
class AppendRevisionRequest(M8ContractModel):
    candidate: ExplorationRevision
    expected_head_version: int | None
    command_id: str

class CreatePromotionPreviewRequest(M8ContractModel):
    candidate_id: str
    revision: int
    target: PromotionTarget
    command_id: str

class PromoteExplorationRequest(M8ContractModel):
    authorization: PromotionAuthorization
    expected_candidate_head_version: int
```

Map Pydantic validation to 422 through FastAPI. Translate domain failures only
through `lib.api_errors`: unknown or foreign identity → 404
`m8_exploration_not_found`; divergent command → 409 `m8_command_conflict`;
candidate/head conflict → 409 `m8_candidate_conflict`; stale/expired binding →
409 `m8_promotion_binding_stale`; unsupported target/seam → 409
`m8_promotion_target_unavailable`. Add all five keys to `en`, `vi` and `zh` and
run the backend i18n consistency test. Never return an owner ID, internal path,
SQL error or existence distinction across scopes.

## Fixed persistence map

Migration `8a8c4a0e0001` has `down_revision = "7b7c4a0e0001"`. Use PostgreSQL
JSON/JSONB according to the accepted M7 model convention discovered by A0;
canonical bytes/digests, not database JSON ordering, are hash authority.
All opaque IDs/refs/scopes use `String(255)`, SHA-256 fields use `String(71)`,
enum/operation/result-kind fields use `String(32)`, versions use `Integer`, JSON
fields are non-null, and every timestamp uses `DateTime(timezone=True)`. Constraint
names use `ck_m8_<table>_<rule>`, `uq_m8_<table>_<identity>` and
`ix_m8_<table>_<lookup>`; migration tests enumerate and compare their semantics.

| Table | Required identity and fields | Required constraints/indexes |
|---|---|---|
| `m8_candidate_heads` | `candidate_id`, `user_id`, `project_name`, `current_revision`, `head_version`, timestamps | PK `candidate_id`; unique `(user_id, project_name, candidate_id)`; revisions/versions >= 1; scope index |
| `m8_candidate_revisions` | scope, `candidate_id`, `revision`, `parent_revision`, `kind`, canonical `payload_json`, `payload_digest`, canonical `lineage_json`, `created_by`, `created_at` | PK `(candidate_id, revision)`; FK candidate; unique `(user_id, project_name, candidate_id, revision)`; kind check; revision >= 1; unique `(candidate_id, payload_digest)` is forbidden because equal content may be a new explicit revision |
| `m8_command_receipts` | scope, `actor_scope`, `operation`, `command_id`, `command_digest`, `result_kind`, `result_ref`, `result_digest`, `created_at` | PK `(user_id, project_name, actor_scope, operation, command_id)`; operation check `APPEND_REVISION/PREVIEW/PROMOTE`; immutable |
| `m8_promotion_previews` | spec `PromotionPreview` fields plus `user_id`; target fields stored separately; canonical impact JSON | PK `preview_id`; unique scoped `preview_command_id`; FK exact revision; target/version nonnegative; TTL check `(0,3600]`; target/master null coupling checks; expiry index |
| `m8_promotion_authorizations` | spec `PromotionAuthorization` plus `user_id`, `authorization_digest` | PK `(user_id, project_name, command_id)`; unique scoped authorization digest; FK preview; decision check `APPROVE`; immutable |
| `m8_promotion_receipts` | spec `PromotionReceipt` plus `user_id`, `authorization_digest` | PK `receipt_id`; unique `(user_id, project_name, command_id)`; FK preview/revision/authorization; target/result-master coupling check; immutable |

Do not add cascade deletion from any evidence table. Downgrade removes only the
six M8 tables in reverse dependency order. ORM definitions and migration must
declare the same names, lengths, nullability and constraints; the migration test
compares both.

## Task A0: Prove the executable base before implementation files

**Files:** Create `scripts/r2/verify_m8_scope.py`,
`tests/unit/scripts/r2/test_verify_m8_scope.py`, baseline schema and baseline.

**Produces:**
`verify_m8_scope(repo: Path, baseline: Mapping[str, object]) -> list[str]`, where
an empty list is the only pass result. CLI prints sorted stop codes/details and
returns 0 on pass, 2 on any failed prerequisite.

- [ ] **A0.1 — Verify the caller-provided worktree before writing.** Run:

  ```bash
  git status --short
  git rev-parse --abbrev-ref HEAD
  git rev-parse HEAD
  uv run alembic heads
  ```

  Expected: empty status, branch `impl/r2-m8a-exploration-promotion`, one head
  `7b7c4a0e0001`, and HEAD equal to the independent M7 acceptance commit whose
  parent is the accepted M7-E candidate HEAD. Otherwise emit
  `M8_PREREQUISITE_NOT_ACCEPTED` and stop.

- [ ] **A0.2 — Discover required seams without choosing replacements.** Use the
  codebase-memory graph at Tier 2 to find `AtomicPromotionService.promote`,
  `MasterResolver.get_exact`, `CommandReceiptRepository.get_exact/add`, the sole
  ProductionBinding writer, M7 UoW/session owner and project-event append seam.
  Trace both directions for each material symbol; paginate; call
  `check_index_coverage` for every path. Read reported missed ranges directly.
  Record qualified names, signatures, paths, line spans and SHA-256 values.
  Missing, duplicate or non-atomic authority emits `M8_BASE_SEAM_CHANGED`.

- [ ] **A0.3 — Write verifier RED tests.** Tests are named:
  `test_rejects_design_branch`, `test_rejects_dirty_tree`,
  `test_rejects_missing_or_rejected_m7_evidence`,
  `test_rejects_head_or_alembic_mismatch`,
  `test_rejects_multiple_alembic_heads`, `test_rejects_document_hash_drift`,
  `test_rejects_seam_signature_or_path_drift`,
  `test_rejects_donor_pin_or_path_drift`, and `test_accepts_exact_clean_base`.

- [ ] **A0.4 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/unit/scripts/r2/test_verify_m8_scope.py -q
  ```

  Expected: collection/import failure because `verify_m8_scope.py` is absent.

- [ ] **A0.5 — Implement schema and verifier.** The baseline schema requires:
  `schema_version`, `base_head`, `accepted_m7_candidate_head`, `branch`,
  `alembic_heads`, `m7_evidence` path/hash/status list, `design_artifacts`
  path/hash list, `seams` qualified-name/signature/path/hash list, `donors`
  name/URL/commit/selected-path/hash list, exact `scope_allowlist`, graph project/
  generation/coverage and `created_at`. Reject unknown fields. Sort all emitted
  diagnostics and canonicalize JSON before hashing.

- [ ] **A0.6 — Run GREEN and self-check.** Run:

  ```bash
  uv run python -m pytest tests/unit/scripts/r2/test_verify_m8_scope.py -q
  uv run python scripts/r2/verify_m8_scope.py docs/r2/evidence/R2_M8_BASELINE.json
  git diff --check
  ```

  Expected: tests pass, verifier exits 0 with `M8_BASELINE_OK`, diff check exits 0.

- [ ] **A0.7 — Commit only A0 paths.** Run `git status --short`, stage the four
  A0 files explicitly and commit `test(r2): freeze M8 accepted baseline`.

## Task A1: Implement exact contracts, digests and donor parity fold

**Files:** Create contract/digest/error/port/parity and evidence-verifier modules
and their exact unit tests from the owned file map; modify only
`r2/contracts/__init__.py`.

**Produces:** Every spec §4 model and §5 protocol;
`canonical_json_bytes(value: object) -> bytes`,
`digest_canonical(value: object) -> Sha256Digest`,
`digest_payload(payload: CandidatePayload, lineage: LineageBinding) -> Sha256Digest`,
`digest_command(operation: str, user_id: str, project_name: str, actor_scope: str,
request: object) -> Sha256Digest`, and
`evaluate_parity(report: DonorParityReport, current_head: str) -> ParityVerdict`.
`verify_m8_evidence(document: object, schema: object,
expected_tested_head: str) -> list[str]` is the shared strict-schema/evidence fold.

- [ ] **A1.1 — Write contract RED tests.** Cover frozen assignment, extra fields,
  aware timestamps, lowercase SHA-256, finite numbers, recursive deep freeze,
  stable key sorting, array order, all three discriminators, revision/payload
  kind mismatch, TTL boundaries, target/master coupling and receipt result coupling.

- [ ] **A1.2 — Write digest/parity RED tests.** Verify the payload digest domain
  is exactly `{contract_version, kind, payload, lineage}`; excluded metadata does
  not change it and every lineage field does. Test empty rows, HEAD drift,
  required skip, material unknown, reachable exclusion and each below-parity
  dimension independently.

- [ ] **A1.3 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/unit/r2/contracts/test_advanced_creative.py tests/unit/r2/advanced_creative/test_digests.py tests/unit/r2/advanced_creative/test_parity.py tests/unit/scripts/r2/test_verify_donor_parity.py tests/unit/scripts/r2/test_verify_m8_evidence.py -q
  ```

  Expected: imports fail for the missing modules.

- [ ] **A1.4 — Implement the normative spec shapes.** Copy spec §4 annotations,
  validators and `model_rebuild()` exactly. Canonical serialization emits UTF-8,
  no whitespace, unescaped Unicode, lexicographically sorted object keys and
  ordered arrays. Integers use base-10; finite `Decimal`/float values use fixed
  decimal notation with trailing fractional zeroes removed and negative zero
  normalized to `0`. Strings use JSON escaping. `digest_canonical` returns
  `sha256:` plus lowercase hex over those bytes. `digest_payload` hashes exactly
  `{"contract_version":"1","kind":payload.kind,"payload":payload,
  "lineage":lineage}`. `digest_command` hashes exactly
  `{"contract_version":"1","operation":operation,"user_id":user_id,
  "project_name":project_name,"actor_scope":actor_scope,"request":request}`.
  Preview/authorization/result digests cover the complete validated model dump.
  The parity CLI recomputes all referenced hashes and the verdict; it never
  trusts the report's verdict field. The evidence verifier rejects unknown fields,
  missing artifacts, nonzero exits, nonempty skips/unknowns and a tested HEAD that
  differs from its expected parent.

- [ ] **A1.5 — Run GREEN and static checks.** Run:

  ```bash
  uv run python -m pytest tests/unit/r2/contracts/test_advanced_creative.py tests/unit/r2/advanced_creative/test_digests.py tests/unit/r2/advanced_creative/test_parity.py tests/unit/scripts/r2/test_verify_donor_parity.py tests/unit/scripts/r2/test_verify_m8_evidence.py -q
  uv run basedpyright r2/contracts r2/advanced_creative scripts/r2
  uv run ruff check r2/contracts r2/advanced_creative scripts/r2 tests/unit/r2 tests/unit/scripts/r2
  ```

- [ ] **A1.6 — Commit.** Stage only A1 files and commit
  `feat(r2): define M8 contracts and donor parity gate`.

## Task A2: Persist append-only revisions, commands and previews

**Files:** Create ORM/repository/migration and exact migration/repository tests;
modify model/repository exports.

**Produces:** Exact `ExplorationRepository` methods from spec §5 plus repository
methods `get_command_receipt`, `stage_command_receipt`, `stage_preview`,
`get_preview_for_update`, `stage_authorization` and `stage_promotion_receipt`.
All stage methods flush but do not commit; the service/UoW owns commit/rollback.

- [ ] **A2.1 — Write SQLite migration-structure RED tests.** Assert exact six-table set, columns,
  PK/FK/unique/check/index names from the persistence map, revision/down-revision,
  one Alembic head and downgrade removal of only M8 tables.

- [ ] **A2.2 — Write repository RED tests.** Using real PostgreSQL, cover genesis
  race, append race, exact replay, divergent command, parent mismatch, head CAS,
  immutable historical bytes, same payload in a later explicit revision,
  foreign/unknown equivalence, ordered pagination and rollback after every flush.

- [ ] **A2.3 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/integration/lib/db/migrations/test_alembic_m8_exploration.py tests/integration/lib/db/repositories/test_advanced_creative.py -q
  ```

  Expected: missing migration/model/repository failures; a zero-test selection is failure.

- [ ] **A2.4 — Implement migration and ORM parity.** Follow `lib.db.base.Base`,
  `utc_now`, `Mapped`/`mapped_column` and repository `AsyncSession` conventions.
  Scope every query before interpreting existence. Use database constraints as a
  second line of defense, never as the public error surface.

- [ ] **A2.5 — Implement lock/replay sequence.** For append: scoped command
  receipt lookup → command-key insert/lock → candidate-head lock → predecessor
  and CAS validation → immutable revision/head update → receipt. For preview:
  scoped command lookup → command-key insert/lock → candidate-head lock → exact
  revision/digest/target validation → preview → receipt. Exact completed replay
  returns before currentness checks and changes no row/version.

- [ ] **A2.6 — Run GREEN and migration round trips.** Run the migration test with
  its repository-standard SQLite `alembic_cfg`. Run repository concurrency with
  the repository-supported disposable PostgreSQL target attested by the execution
  environment; never infer or reuse an application/production URL. Under that
  same disposable target, run upgrade to head → downgrade to `7b7c4a0e0001` →
  upgrade to head → `uv run alembic heads`. If no attested disposable PostgreSQL
  target exists, stop `M8_REQUIRED_EVIDENCE_MISSING`; SQLite cannot prove locking.

- [ ] **A2.7 — Commit.** Stage only A2 files/exports and commit
  `feat(db): persist M8 exploration evidence`.

## Task A3: Expose scoped routes and bridge promotion atomically

**Files:** Create exploration/promotion services, host composition, router and
their unit/integration/architecture tests; modify app/router/i18n files listed above.

**Produces:** Exact spec `create_preview()` and `promote()` protocols plus the
fixed HTTP surface. `ExplorationPromotionService.promote` is the only M8 import
site permitted to invoke an A0-recorded authority adapter.

- [ ] **A3.1 — Write service RED tests.** Cover stale candidate head, revision,
  payload, target version, master ID/digest, authorization scope/digest, preview
  expiry and candidate/target mismatch; simultaneous actors; preview and promote
  retry after unknown outcome; divergent command; adapter failure before/after
  staged writes; exact replay after later head changes; and ProductionBinding
  translation rejecting `GAP` assertions. Reject any mismatch between path
  `project_name`, lineage `project_name`, authorization `project_name` and the
  authenticated user/actor binding before a write.

- [ ] **A3.2 — Write router RED tests.** Cover authentication dependency,
  migration gate, path-derived user/project scope, body scope injection attempt,
  all five stable API error keys/statuses, foreign/unknown equality, pagination
  bounds and byte-equivalent 200 responses for new commands and exact replays.

- [ ] **A3.3 — Write architecture RED tests.** AST/import checks reject M8 calls
  to Canon/Narrative/Policy/Claim writers, direct manifest/current-version writes,
  direct provider/queue calls, commits inside repository stage methods, authority
  imports outside `promotion.py`/host adapter and a second M8 router registration.

- [ ] **A3.4 — Run RED.** Run:

  ```bash
  uv run python -m pytest tests/unit/r2/advanced_creative/test_exploration.py tests/unit/r2/advanced_creative/test_promotion.py tests/unit/server/routers/test_advanced_creative_router.py tests/integration/r2/advanced_creative/test_promotion_atomicity.py tests/architecture/test_m8_advanced_creative_boundaries.py -q
  ```

- [ ] **A3.5 — Implement the transaction.** Exact replay lookup occurs first.
  For a new promotion lock command guard → candidate head → preview → authority
  target → master head for `ARTIFACT_SLOT`; revalidate every bound field; stage
  authorization, authority mutation, promotion receipt and durable event in the
  one A0-proven M7 UoW; commit once. On any exception roll back all staged state.
  Compatibility projection remains the M7 projector's responsibility.

- [ ] **A3.6 — Implement the router and translations.** Register one router with
  authentication and project-migration dependencies. Use injected services and
  controllable clock/UUID sources. Add exact error keys in all three backend locales.

- [ ] **A3.7 — Run GREEN and regressions.** Run the A3 selection, backend i18n
  consistency, M2 production regressions and all M7 promotion/master tests named
  by the A0 baseline. Every selection must contain at least one test and have zero failures/skips.

- [ ] **A3.8 — Commit.** Stage only A3 files and commit
  `feat(r2): add preview-bound exploration promotion`.

## Task A4: Seal machine-verifiable M8-A evidence

**Files:** Create the M8-A evidence schema and evidence JSON only; tests for the
schema/verifiers remain in the owned paths.

The evidence schema rejects unknown fields and requires: `schema_version`,
`status`, `tested_head`, `tested_parent`, `branch`, `alembic_graph`, `baseline_digest`,
`scope_allowlist`, `contract_digest`, `seam_digest`, `commands` with command/
exit/test counts/log digest, `fault_matrix`, `cross_scope_results`,
`architecture_results`, `required_skips`, `material_unknowns`, `artifacts`,
`independent_review` and `created_at`. `status` is `M8_A_CANDIDATE` until Codex
independently records acceptance; Claude cannot write `ACCEPTED`.

- [ ] **A4.1 — Run all affected repository gates.** Because A2 changes Alembic/
  DB and A3 changes i18n, `CONTRIBUTING.md` requires the complete backend gate:

  ```bash
  uv run ruff check .
  uv run ruff format .
  uv run basedpyright --warnings
  uv run lint-imports
  uv run deptry lib server alembic scripts tests r2
  uv run python -m pytest -n 4 --dist loadfile
  uv run python scripts/audit_tests.py --check
  ```

  Re-run `git diff --check` after formatting. Any failure, skip required by M8 or
  zero selected test blocks evidence.

- [ ] **A4.2 — Run M8 fault and verifier gates.** Run all A0-A3 files explicitly,
  migration upgrade/downgrade/upgrade, PostgreSQL concurrent promotion, restart/
  retry-after-unknown cuts, architecture boundary test, scope verifier and donor
  parity verifier. Record exact commands, exits, counts and log SHA-256 values.

- [ ] **A4.3 — Build and verify evidence.** Write the schema first, prove it
  rejects missing/extra fields and false PASS claims, then write evidence bound to
  the current candidate HEAD. Required skips and material unknowns are empty.
  The evidence schema and `R2_M8_A_EXPLORATION_PROMOTION.json` are the only
  expected dirty paths before the evidence commit.

- [ ] **A4.4 — Refresh graph evidence.** At the candidate HEAD, record the graph
  project/generation; check coverage for every created/modified file and read all
  reported missed ranges. Re-run the authority bypass search from the architecture test.

- [ ] **A4.5 — Commit and stop.** Stage only the evidence schema/JSON. Commit
  `test(r2): prove M8 exploration authority`. The evidence records `tested_head`
  as the clean A3 code HEAD; the evidence commit must have that SHA as its parent
  and may change only the schema/evidence files. Verify `git status --short` is
  empty after the commit, then stop for independent Codex review. Do not push,
  migrate a live database, call a provider, deploy or begin M8-B.
