# R2-M8 Canvas, Learning, and Multi-format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Deliver a donor-parity Creative Canvas, bounded spatial candidates,
lineage-bound learning recommendations, and semantically reviewed multi-format
projection without adding authority or runtime outside ArcReel/R2.

**Architecture:** One R2 advanced-creative kernel stores append-only exploration
revisions and evidence in PostgreSQL, promotes through the accepted M7 Production
Authority boundary, and runs expensive work through M7 execution. DramaClaw and
OpenMontage behavior enters only through replaceable adapters whose selected
surfaces pass exact-source `DonorParityContract` differential gates.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL
18, FastAPI, React 19, TypeScript, Zustand 5, React Flow 12, Vitest, Playwright,
FFmpeg, Remotion, pytest, ruff, basedpyright, import-linter and deptry.

**Spec:** `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`

**ADR:** `docs/adr/0079-m8-integrated-exploration-learning-format-kernel.md`

**Research:** `docs/research/2026-09-13-r2-m8-reuse-first-comprehensive-research.md`

**Execution contract:** `docs/r2/evidence/R2_M8_EXECUTION_CONTRACT_2026-09-13.json`

## Global Constraints

- Start in a new M8 worktree from an accepted clean M7 implementation HEAD at
  Alembic head `7b7c4a0e0001`. Task A0 exits 2 with
  `M8_PREREQUISITE_NOT_ACCEPTED` before any implementation file if lineage,
  evidence, cleanliness, document hashes or migration head differ.
- ArcReel, PostgreSQL, existing Production Authority and M7 execution remain
  the host, durable store, master writer and work/recovery authority.
- Candidate payloads and evidence are append-only; mutable heads use exact
  expected-version CAS. Browser storage is recovery cache only.
- Recommendation modules import no Canon, Narrative, policy, routing,
  production-authority or governance write port.
- Every donor-derived surface passes the locked `R2-DEC-031` baseline, coverage,
  same-fixture parity and exact-HEAD completion gates. `PASS` permits no required
  skip, material unknown or applicable dimension below `PARITY`.
- Donor defects are not preserved; each correction has a fixture demonstrating
  the donor failure and stronger R2 result.
- Licensing does not affect selection, scoring, rejection or sequencing.
- Every public operation scopes by `(user_id, project_name)` and hides foreign
  IDs as not-found. Global uniqueness failures disclose no owner.
- Tests use controllable clocks/IDs/fakes and real PostgreSQL for OCC, locking,
  migration and concurrency. No sleeps, private-symbol monkeypatching or
  mock-only parity claims.
- Each behavior task runs RED, implements minimum behavior, runs GREEN plus
  affected regressions, audits changed tests, checks status, stages only owned
  paths and commits.
- Every packet ends at a clean exact HEAD with machine-readable evidence and
  independent Codex review. Claude Code does not cross a pending/rejected gate.
- Executors do not ask for or invent architectural choices. They follow the
  active packet; a missing prerequisite, seam or human-owned input produces the
  execution-contract stop receipt and the normative stop code.
- No task authorizes live migration, credentials, provider/platform calls,
  paid generation, worker activation, deployment, cleanup, publication or
  production approval.

---

## Fixed file and interface map

| File | Responsibility |
|---|---|
| `r2/contracts/advanced_creative.py` | frozen extra-forbid Pydantic v2 models and discriminated candidate payloads |
| `r2/advanced_creative/digests.py` | canonical versioned digests |
| `r2/advanced_creative/ports.py` | repository/authority/execution protocols |
| `r2/advanced_creative/parity.py` | pure parity verdict and manifest validation |
| `r2/advanced_creative/exploration.py` | revision append/read orchestration |
| `r2/advanced_creative/promotion.py` | preview creation and sole promotion bridge |
| `r2/advanced_creative/spatial.py` | spatial schema validation and pure normalization |
| `r2/advanced_creative/learning.py` | corrections, cohort folds and recommendations |
| `r2/advanced_creative/formats.py` | output/reframe planning and validation folds |
| `lib/db/models/advanced_creative.py` | M8 ORM rows |
| `lib/db/repositories/advanced_creative.py` | scoped PostgreSQL repositories/UoW |
| `server/services/advanced_creative.py` | host composition and M7 adapters |
| `server/routers/advanced_creative.py` | authenticated M8 HTTP surface |
| `frontend/src/features/creative-canvas/` | graph domain, recovery, UI and API client |
| `frontend/src/features/learning/` | recommendation evidence/disposition UI |
| `frontend/src/features/format-projection/` | format plan/review UI |
| `scripts/r2/verify_m8_scope.py` | prerequisite, bypass, document and evidence verifier |
| `scripts/r2/verify_donor_parity.py` | exact-source parity report verifier |

Public names and signatures in spec sections 4-5 are normative. If the accepted
M7 seam makes them impossible, stop `M8_BASE_SEAM_CHANGED`; do not create a
parallel authority or silently rename the contract.

### Linear migration chain

```text
7b7c4a0e0001
  -> 8a8c4a0e0001  exploration revisions, previews and promotion evidence
  -> 8d8c4a0e0001  observations, corrections, recommendations and decisions
  -> 8e8c4a0e0001  output/overlay profiles, format plans and validation reports
```

Accepted migrations are immutable. A later defect stops
`M8_ACCEPTED_SCHEMA_CHANGE_REQUIRED` for a separately designed additive revision.

### Execution packets

| Checkpoint | Packet | Tasks |
|---|---|---|
| M8-A | `2026-09-13-r2-m8a-exploration-promotion.md` | A0-A4 |
| M8-B | `2026-09-13-r2-m8b-creative-canvas.md` | B1-B4 |
| M8-C | `2026-09-13-r2-m8c-spatial-candidates.md` | C1-C3 |
| M8-D | `2026-09-13-r2-m8d-learning-recommendations.md` | D1-D4 |
| M8-E | `2026-09-13-r2-m8e-multiformat-projection.md` | E1-E4 |
| M8-F | `2026-09-13-r2-m8f-integrated-utility.md` | F1-F3 |

Only M8-A is released for the first Claude Code handoff. Its packet contains the
exact owned paths, API, persistence, error, test and evidence contract. B-F are
released one at a time only after the prior accepted implementation fixes their
actual integration paths. Human-owned inputs and missing-input stop behavior are
enumerated in the execution contract; Claude never substitutes its preference.

---

### Task A0: Freeze accepted lineage and donor surfaces

**Files:** Create `scripts/r2/verify_m8_scope.py`, its unit test, and
`docs/r2/evidence/R2_M8_BASELINE.json`.

**Interfaces:** `verify_m8_scope(repo: Path, baseline: Mapping[str, object]) -> list[str]`;
baseline binds M7 acceptance, full Alembic graph, research/ADR/spec/plan/packet
hashes, host/M7 seam hashes, donor pins and selected path inventories.

The accepted M7 source of truth is
`docs/r2/evidence/R2_M7_E_PRODUCTION_CANDIDATE.json` plus the independently
authored `docs/r2/evidence/R2_M7_IMPLEMENTATION_ACCEPTANCE.json`. The acceptance
commit changes only that acceptance artifact, has the accepted M7-E candidate
HEAD as parent, and is the exact clean base for the M8 worktree. M7-E must bind
M7-A through M7-E evidence and Alembic head `7b7c4a0e0001`.

- [ ] Write failures for dirty state, wrong ancestor/head, absent M7 acceptance,
  changed document/seam/donor path hash, incomplete migration graph and multiple heads.
- [ ] Run `uv run pytest tests/unit/scripts/r2/test_verify_m8_scope.py -q`;
  expected RED is missing verifier.
- [ ] Implement fail-before-write verification and emit exact prerequisite/drift codes.
- [ ] Run focused test, verifier and `git diff --check`; expected GREEN binds one clean base.
- [ ] Commit `test(r2): freeze M8 accepted baseline`.

### Task A1: Define contracts, digests and donor parity fold

**Files:** Create `r2/contracts/advanced_creative.py`,
`r2/advanced_creative/{__init__,digests,ports,parity}.py`, exports and unit tests;
create `scripts/r2/verify_donor_parity.py` and tests.

**Interfaces:** Implement every spec section-4 model and section-5 protocol;
`evaluate_parity(report: DonorParityReport, current_head: str) -> ParityVerdict`.

- [ ] Write frozen-assignment, construction, extra-field, timestamp, hash, enum,
  candidate-kind/discriminator and deep-snapshot tests plus exhaustive parity
  failures for empty rows, drift, skip, unknown, excluded reachable behavior,
  non-current HEAD and every below-parity dimension.
- [ ] Run contract/parity/verifier tests; expected RED is missing modules.
- [ ] Implement canonical JSON digests and pure fail-closed verdict recomputation.
- [ ] Run focused tests and `uv run basedpyright r2/contracts r2/advanced_creative`.
- [ ] Commit `feat(r2): define M8 contracts and donor parity gate`.

### Task A2: Persist exploration revisions and previews

**Files:** Create ORM/model exports, migration
`8a8c4a0e0001_add_exploration_authority.py`, repository and migration/repository tests.

**Interfaces:** Implement `ExplorationRepository`, preview/authorization/receipt
storage, scoped command receipts and candidate-head CAS.

- [ ] Write real-PostgreSQL tests for genesis race, append race, exact replay,
  same-key/different-payload conflict, foreign scope, immutable payload and history pagination.
- [ ] Run model/migration/repository tests; expected RED is missing revision/models.
- [ ] Implement reversible migration, constraints and short transactions using
  the normative command-key guard → candidate head → preview → authority target
  → artifact master relative lock order from spec §6.
- [ ] Run upgrade/downgrade, concurrency and repository tests; expected GREEN has one head.
- [ ] Commit `feat(db): persist M8 exploration evidence`.

### Task A3: Implement preview-bound atomic promotion

**Files:** Create `exploration.py`, `promotion.py`, host service/router wiring and
unit/integration tests.

**Interfaces:** Exact spec `create_preview()` and `promote()`; a typed adapter
invokes accepted M7 atomic Production Authority inside the shared transaction/UoW.

- [ ] Write stale candidate/target/master/preview/scope/expiry, TTL-over-3600,
  target-kind/candidate mismatch, concurrent actor, preview-command and
  promotion-command retry-after-unknown, duplicate-effect and cross-scope failures.
- [ ] Run focused tests; expected RED is missing services/routes.
- [ ] Implement full revalidation, deterministic lock order, receipt-first exact replay
  and one atomic authority bridge; changed bindings write nothing.
- [ ] Run promotion plus M2/M7 approval regressions; expected GREEN preserves prior master.
- [ ] Commit `feat(r2): add preview-bound exploration promotion`.

### Task A4: Seal M8-A evidence

**Files:** Create `docs/r2/evidence/R2_M8_A_EXPLORATION_PROMOTION.json`.

- [ ] Run M8-A focused suites, migration chain, static/import gates, scope verifier,
  bypass search and restart/concurrency fault tests.
- [ ] Record exact commands, exit codes, test counts, artifacts, HEAD and zero skips.
- [ ] Run evidence schema/parity verifier and `git diff --check`.
- [ ] Record the clean A3 code SHA as `tested_head`; commit only schema/evidence
  files with that SHA as parent using `test(r2): prove M8 exploration authority`,
  then stop for Codex review. Claude records `M8_A_CANDIDATE`, never `ACCEPTED`.

### Task B1: Freeze and port pure DramaClaw Canvas behavior

**Files:** Create donor baseline JSON/fixtures and
`docs/r2/evidence/R2_M8_B_CANVAS_BENCHMARK_PROTOCOL.json`; create
`frontend/src/features/creative-canvas/domain/` pure modules and Vitest tests.

**Interfaces:** Stable graph/node/edge/group/history/bookmark/save-decision types;
no React, Zustand, API or storage imports in pure modules.

- [ ] Inventory the exact reachable donor surface and run all selected donor tests;
  add canonical differential fixtures for every branch/failure path.
- [ ] Before benchmark results, freeze exact node/edge ladder, operation mix,
  browser/build/hardware, repetitions, p50/p95, memory, bundle and pass thresholds
  in the Canvas benchmark protocol.
- [ ] Require the sponsor-approved production graph envelope from the execution
  contract input; if absent, stop `M8_REQUIRED_EVIDENCE_MISSING` without choosing one.
- [ ] Run port tests; expected RED is missing domain modules.
- [ ] Port selection/layout/group/history/bookmark/payload/clear-decision behavior.
- [ ] Run donor and R2 fixtures and emit behavior rows; expected all rows parity/improved.
- [ ] Commit `feat(canvas): port parity-proven graph behavior`.

### Task B2: Port save coordination and recovery cache

**Files:** Create `saveCoordinator.ts`, `draftRecovery.ts`, Zustand slice and tests.

- [ ] Write races for one in-flight save, coalescing, version waiters, canvas switch,
  corrupt/oversized/expired drafts, history shedding and explicit empty clear.
- [ ] Run focused tests; expected RED is missing coordinator/recovery.
- [ ] Port behavior using injected clock/storage/API; key cache by user/project/candidate/revision.
- [ ] Run fixtures and browser-reload tests; expected GREEN never silently overwrites server.
- [ ] Commit `feat(canvas): preserve saves and recover drafts safely`.

### Task B3: Integrate React Flow and ArcReel API/UI

**Files:** Add pinned React Flow and direct `axe-core@4.13.0` dependencies; create
Canvas page/components/API; modify host router/nav and the `en`, `vi`, and `zh`
catalogs under `frontend/src/i18n/`; add Vitest/browser tests.

- [ ] Write keyboard/screen-reader/focus, graph operations, conflict/reload and
  promotion-preview UI tests before the route exists.
- [ ] Run selected frontend tests; expected RED is missing route/components.
- [ ] Implement the adapter behind pure domain types and authenticated M8 API.
- [ ] Run `pnpm check`, `eslint-plugin-jsx-a11y`, automated `axe-core` browser
  checks, keyboard/focus tests, bundle report and the pre-registered graph-size ladder.
- [ ] Commit `feat(canvas): integrate accessible creative canvas`.

### Task B4: Seal M8-B donor parity

**Files:** Create `docs/r2/evidence/R2_M8_B_CANVAS_PARITY.json`.

- [ ] Run complete selected donor and port tests plus ArcReel canvas regressions.
- [ ] Verify each behavior/dimension row, exact HEAD, resources and zero unknown/skips.
- [ ] Commit `test(r2): prove Creative Canvas donor parity` and stop for review.

### Task C1: Port spatial normalizers with differential fixtures

**Files:** Create spatial donor baseline/fixtures, `spatial.py` and unit tests.

**Interfaces:** Consume A1 `SpatialCandidate` and `SpatialPayload`; produce a
validated `SPATIAL` discriminated payload for `ExplorationRevision`.

- [ ] Build visible/inferred/gap/seam/direction/duplicate plus malformed/partial fixtures.
- [ ] Run exact pinned donor normalizer and R2 harness; expected RED is missing R2 module.
- [ ] Port schema validation/normalization while preserving evidence classes and warnings.
- [ ] Emit differential rows; expected deterministic parity or documented improvement.
- [ ] Commit `feat(spatial): port evidence-preserving normalization`.

### Task C2: Bind spatial inference to M7 and promotion

**Files:** Extend host service/router and add integration/recovery tests.

- [ ] Write provider failure/cancel/restart, fingerprint, malformed output and
  direct-production-write boundary tests.
- [ ] Run focused tests; expected RED is missing spatial execution path.
- [ ] Route inference through M7, append SpatialCandidate only after validation,
  and translate accepted assertions through A3 promotion without promoting gaps.
- [ ] Run M7 recovery/promotion regressions; expected GREEN has no direct write.
- [ ] Commit `feat(spatial): execute and promote bounded spatial candidates`.

### Task C3: Seal M8-C evidence

**Files:** Create `docs/r2/evidence/R2_M8_C_SPATIAL_PARITY.json`.

- [ ] Run donor differential, fault, deterministic replay and boundary suites.
- [ ] Verify exact HEAD, all selected rows, resources and zero unknown/skips.
- [ ] Commit `test(r2): prove spatial candidate parity` and stop for review.

### Task D1: Persist observations and corrections

**Files:** Create migration `8d8c4a0e0001_add_learning_evidence.py`, extend models,
repository and tests.

- [ ] Write source identity, exact replay, divergent duplicate, correction chain,
  late/delete/private/missing and foreign-scope tests.
- [ ] Run migration/repository tests; expected RED is absent tables.
- [ ] Implement append-only observations/corrections and cutoff-aware effective fold.
- [ ] Run PostgreSQL concurrency/migration tests; expected GREEN preserves originals.
- [ ] Commit `feat(learning): persist lineage-bound observations`.

### Task D2: Add internal and platform observation adapters

**Files:** Extend `learning.py`, host adapters and source fixture tests.

- [ ] Write fixtures for Usage/QA/approval/M7 and source-specific YouTube/TikTok
  semantics, cumulative/windowed measures, timezone and raw payload digest.
- [ ] Run focused tests; expected RED is missing adapters.
- [ ] Implement pure transforms retaining source names/versions and correction identity.
- [ ] Run adapter/idempotency tests; expected GREEN has no flattened engagement authority.
- [ ] Commit `feat(learning): normalize observations without erasing source semantics`.

### Task D3: Implement recommendations, replay and Human disposition

**Files:** Extend service/router; create learning frontend; add unit/integration/UI tests.

- [ ] Write cohort/profile leakage, project/time holdout, causal-language, expiry,
  evidence-currentness, repeat-rejection and unauthorized mutation tests.
- [ ] Run focused tests; expected RED is missing lifecycle.
- [ ] Implement transparent summaries/rules, offline replay, immutable recommendations
  and accept/reject/defer/request-experiment decisions with no authority write port.
- [ ] Run backend/frontend tests and `pnpm check`; expected GREEN preserves isolation.
- [ ] Commit `feat(learning): add scoped recommendation lifecycle`.

### Task D4: Seal M8-D evidence

**Files:** Create `docs/r2/evidence/R2_M8_D_LEARNING.json`.

- [ ] Run correction/idempotency/leakage/replay/authority/browser suites.
- [ ] Record profile-specific coverage, exact HEAD and zero required skips.
- [ ] Commit `test(r2): prove non-authoritative learning lifecycle` and stop for review.

### Task E1: Persist versioned format contracts

**Files:** Create migration `8e8c4a0e0001_add_format_projection.py`, extend models,
formats module/repository and tests.

**Interfaces:** Consume A1 `FormatCandidate`; produce candidates only from an
immutable plan, artifact, M7 execution and both matching report digests.

- [ ] Write malformed ratio, floating profile, changed source master, overlay version,
  reframe digest and append-only report tests.
- [ ] Run focused tests; expected RED is absent tables/module.
- [ ] Implement versioned profiles/constraints/plans/reports and fail-closed validation.
- [ ] Run migrations/concurrency tests; expected GREEN has one linear head.
- [ ] Commit `feat(format): persist governed format projections`.

### Task E2: Adapt OpenMontage composition and reframe mechanics

**Files:** Create render adapters, exact donor fixtures/harness and tests.

- [ ] Freeze selected OpenMontage surface and run pinned donor compose/crop/validator fixtures.
- [ ] Write same-fixture `16:9`, `9:16`, `1:1`, missing media/audio, cancellation,
  codec/fps/duration and content-identity idempotency cases.
- [ ] Adapt mechanics behind M7 RenderExecution with complete input digest.
- [ ] Run differential and fault tests; expected parity/improvement across all rows.
- [ ] Commit `feat(format): adapt parity-proven composition mechanics`.

### Task E3: Add technical and semantic review workflow

**Files:** Extend services/router; create format frontend and Playwright tests.

- [ ] Write technical failure, overlay/caption collision, material semantic change,
  reviewer disagreement, stale plan/report and promotion-block tests.
- [ ] Require qualified blind semantic reviewer assignments from the execution
  contract; missing assignments stop `M8_REQUIRED_EVIDENCE_MISSING`.
- [ ] Run focused tests; expected RED is missing review flow.
- [ ] Implement inspectors, overlay preview, blind review evidence and A3 promotion gate.
- [ ] Run actual local renders, probes, browser flow and `pnpm check`.
- [ ] Commit `feat(format): require technical and semantic projection parity`.

### Task E4: Seal M8-E evidence

**Files:** Create `docs/r2/evidence/R2_M8_E_FORMAT_PARITY.json`.

- [ ] Verify donor rows, actual media probes, exact HEAD, resources and zero skips/unknowns.
- [ ] Commit `test(r2): prove multi-format projection parity` and stop for review.

### Task F1: Pre-register integrated evaluation

**Files:** Create `docs/r2/evidence/R2_M8_EVALUATION_PROTOCOL.json` and schema tests.

- [ ] Lock fixture/corpus hashes, separate profile cohorts, baselines, smallest useful
  effect or confidence interval, windows, exclusions, `rubric_version`, reviewer
  language/cultural cohort, calibration criteria, role/conflict declaration and
  resource envelope.
- [ ] If any human-owned corpus, effect policy or reviewer input named by the
  execution contract is absent, stop `M8_EVALUATION_NOT_PREREGISTERED`.
- [ ] Validate before producing results; missing/late registration emits
  `M8_EVALUATION_NOT_PREREGISTERED`.
- [ ] Commit `test(r2): preregister M8 utility evaluation`.

### Task F2: Run profile-isolated end-to-end utility evidence

**Files:** Add integrated tests/fixtures and evidence artifacts only.

- [ ] Run Canvas-to-promotion, Spatial, Learning and Format workflows separately for
  generic Western and native-language `zh-shuang` fixtures.
- [ ] Obtain at least two blind qualified reviews per artifact; retain disagreement
  and adjudication without averaging away minority findings.
- [ ] Run crash/restart, concurrent promotion, correction replay and resource envelope.
- [ ] Record baseline deltas/confidence without causal claims beyond experiment design.
- [ ] Commit `test(r2): demonstrate profile-isolated M8 utility`.

### Task F3: Run final gates and seal M8 dossier

**Files:** Create `docs/r2/evidence/R2_M8_ACCEPTANCE.json` and update only approved
roadmap/status evidence.

- [ ] Run affected full backend/frontend gates from `CONTRIBUTING.md`, test audit,
  all six evidence validators, all donor parity verifiers and `git diff --check`.
- [ ] Prove zero bypasses, parity regressions, material unknowns, required skips,
  stale promotions, lost edits, profile leaks and untracked reframes.
- [ ] Bind exact clean HEAD, migration graph, dependency lock, test counts, artifacts,
  independent reviews and non-authorization statement.
- [ ] Commit `docs(r2): seal M8 acceptance dossier` and stop. Production remains unapproved.

## Self-review map

- Exploration/OCC/promotion: A1-A4.
- DramaClaw graph/save/recovery/accessibility/performance parity: B1-B4.
- Spatial evidence and execution: C1-C3.
- Observation corrections, source semantics, recommendations and profiles: D1-D4.
- Output profiles, OpenMontage parity, technical/semantic reports: E1-E4.
- Pre-registration, both creative cohorts, integrated recovery and final gates: F1-F3.
- `R2-DEC-031` exact-source completion: A0-A1 and each B/C/E evidence checkpoint.

No placeholder or implementation task remains outside the six packets.
