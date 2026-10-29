# M10-B handoff (live)

Rewrite in place; this is the resume entry for M10-B.

## State

- Worktree `.worktrees/r2-m10-b`, branch `design/r2-m10-b`, base `0af66db9e`.
- M10-A accepted with conditions: `docs/r2/evidence/R2_M10_A_ACCEPTANCE.json` (source `b904bc000`).
  Reviewer was a separate Claude subagent by sponsor instruction (Codex quota out until 2026-11-02 15:12).
- Sponsor instruction 2026-10-28: continue until M10 is complete, do not stop. Agent still never approves Human gates.
- Carried from M10-A: `M10-A-F1` durable failure ResourceEvidence (append-only table + migration) before any
  operator UI/readiness/audit relies on failure accounting; duration window and SEO lint (A7 exclusions);
  OpenMontage export/layout parity.

## Governing documents

- Plan Task B: `docs/superpowers/plans/2026-09-16-r2-m10-quality-packaging.md` (lines 104-127).
- Design §4.2 (B minimum obligations), §5.2 (reserved domains), §10: `docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md`.
- V2 rebase boundary: `docs/superpowers/specs/2026-10-25-r2-m10-v2-rebase.md`.
- ADR-0080 (M10 extends the M8 candidate kernel through an accepted schema evolution, closed `PACKAGING_SLOT`), ADR-0082.
- Research: `docs/research/2026-09-16-r2-m10-quality-evidence-packaging.md` §5 (donors), §7 (packaging inference).

## Research facts so far

- M8 kernel: closed union `CanvasCandidate | SpatialCandidate | FormatCandidate` (`r2/contracts/advanced_creative.py`),
  SQL `ck_m8_candidate_revisions_kind IN ('CANVAS','SPATIAL','FORMAT')`; targets `ARTIFACT_SLOT`, `PRODUCTION_BINDING`.
  FORMAT existed from the first M8 migration `8a8c4a0e0001`: no precedent for a post-release kind addition and no
  programmatic extension seam. Evolution path = additive union member + CHECK broadening migration + differential
  predecessor tests (R2_03 §33 rule 1; ADR-0080). Requires a reviewed contract amendment.
- M8 revision/head/CAS: `ExplorationRepository.append_revision` (`lib/db/repositories/advanced_creative.py:232`) with
  command receipts; promotion `r2/advanced_creative/promotion.py` (lock order: command key, candidate head, preview,
  slot row; ADR-0097). M10 selection must not call promotion/Production Authority.
- Download tokens: `server.auth.create_download_token/verify_download_token` (`server/routers/projects.py:396-431`).
- Donors: Kalinga `e4b5a217…` local at `~/Kalinga-Shorts-Factory` (dirty tree; use `git show <pin>:path`):
  `pipeline/src/validate.py:112 seo_lint`, `pipeline/src/seo.py`. OpenMontage
  `https://github.com/calesthio/OpenMontage` @ `08e2151fa02de28a5d6a312b3d575692bf147ad7`
  (`tools/publishers/export_bundle.py`) is NOT cloned locally.
- Pilots need Human PASS/REWORK/WAIVE dispositions: the agent cannot issue them; the sponsor must act as Human.

## Progress

- `1751a23bc` design r1 → independent review REWORK (`docs/r2/evidence/m10-b-reviews/design-b0-review.json`;
  H1 finalize lock order, H2 second job truth, M1–M8, L1–L7; B0 accepted with condition C4).
- `d59be1e11` B0/F1: `m10_quality_probe_failures` + migration `4c1f0e2a9b10`; `1a93a16e5` C4 tests.
  Verified on PG16 (disposable container `m10b-test-pg` :55491): `tests/integration/server/services/test_quality_probes.py`
  27 passed (+ `tests/integration/lib/db/repositories/test_quality_probes.py`); SQLite `tests/integration/lib/db/migrations`
  218 passed; ruff/basedpyright/lint-imports/deptry/audit_tests clean.
- `4d76003d5` design r2 (§11 resolution table). Delta re-review pending:
  `docs/r2/evidence/m10-b-reviews/design-r2-delta-review.json`.
- Review substitute: separate Claude Opus subagent (Codex quota out until 2026-11-02 15:12); condition C5 = Codex
  re-review when quota returns.
- `9a16ddf91` design r3: r2 delta review ACCEPT_WITH_CONDITIONS (`design-r2-delta-review.json`), N1–N7 resolved in §12.
- `eb70e4c3f` B1: `PackagingCandidate` in M8 kernel + migration `5d2a7c3e8b11` (CHECK broadening, refusing downgrade),
  `QualityPolicyFields`/V1/V2 (non-waivable rule classes), `r2/contracts/packaging.py`, digest domains + frozen vectors
  (`tests/unit/r2/contracts/test_packaging.py`). Verified: unit r2 + scripts/r2 + SQLite migrations 3146 passed;
  PG16 M8 repo/profile/run/disposition 110 passed, profile repo 16 passed; static gates clean.
  Codex review pending: `docs/r2/evidence/m10-b-reviews/b1-codex-review.json`.

- `83e1f3c2c` B1 fix after Codex REWORK (`b1-codex-review.json`, H1 relabel/downgrade of safety rules, M1–M4):
  server-owned `check_id` semantics, Kalinga-parity constraint fields, per-variant provenance, manifest
  `chosen_variants`, `ExportExecutionIdentity`, vectors for every domain; PG round trip
  `b1-pg-migration-roundtrip.json`. Codex delta re-review running (`b1-codex-delta-review.json`).
  Codex is available again (user instruction 2026-10-28: call Codex review when needed, don't stop to ask).
- `df9ada5df` B2 part 1: pure `r2/quality/packaging_check.py` + `tests/unit/r2/quality/test_packaging_check.py` (28 passed).

- `652540024` B1 C5 (promotion/preview refusal of PACKAGING); B1 Codex delta review ACCEPT_WITH_CONDITIONS
  (`b1-codex-delta-review.json`, no new findings; carried C3 PG repro limit, C4/C6 to later packets).
- `bc47ac5a6` B2 part 2: `m10_packaging_observations` (migration `6e3b8d4f9c22`), `PackagingObservationRepository`,
  `PackagingCheckService` (`server/services/quality_packaging.py`), `PackageCheckRequest` + frozen vector.
  Verified: PG16 `tests/integration/server/services/test_quality_packaging.py` 10 passed; unit r2/scripts/server +
  SQLite migrations 5526 passed; static gates clean. Codex B2 review running (`b2-codex-review.json`).

- B2 Codex review REWORK (`b2-codex-review.json`: H1 ancestor-symlink/resolve-open race, M1 variant lint, M2 FIFO,
  M3 UTF-8 prefix, M4 lineage binding) → fixed in `7484328bf`; PG `test_quality_packaging.py` 20 passed, unit
  r2/scripts/server + SQLite migrations 5555 passed, gates clean. Codex delta re-review running
  (`b2-codex-delta-review.json`).

- B2 Codex delta reviews: delta1 REWORK → `509a13f02`; delta2 REWORK (M2 worker) → `b4c88db6a`; delta3
  ACCEPT_WITH_CONDITIONS (`b2-codex-delta3-review.json`) → `8089ed056` closes N4, records LOCAL_REGULAR_FILE_IO,
  adds PG probe-tamper/FK/unique/status/JSON-ceiling tests. PG `test_quality_packaging.py` 27 passed;
  `test_quality_packaging_measure.py` 18 passed. **B2 accepted with conditions.** Carried: C4 authenticated
  server-derived provenance at the B5 append boundary; C6 closure+lineage verification in every B3/B4 consumer;
  D5 B4 must materialize and re-verify private snapshots.

- B3 (preview + Human selection): `673b2deae` readiness_in refactor (A6 tests 22 passed), `80871276a` schema
  (migration `7f4c9e5a0d33`), `982bbf504` repository + shared `require_packaging_lineage`, `27073a10e` services
  (`server/services/quality_package_selection.py`). PG: `test_quality_package_selection.py` 8 passed,
  packaging + dispositions 49 passed; unit/scripts/migrations 5573 passed; gates clean. Codex B3 review running
  (`b3-codex-review.json`). Selection lease refusals reuse frozen `M10_DISPOSITION_UNAUTHORIZED`.

- B3 Codex review REWORK (`b3-codex-review.json`: H1 selector/assessor grant order, M1 selection re-verification,
  M2 barrier tests, M3 refusals) → `3d96e7dd3`; delta1 REWORK on test evidence (`b3-codex-delta-review.json`) →
  `84f6e32f4` (pg_blocking_pids-identified waiters, more refusals, design §4 serialization points) + `89d23439f`
  (preview duration seam; note `| tail -1` hid an audit failure once — check gate exit codes directly).
  PG `test_quality_package_selection.py` 37 passed. Codex delta2 running (`b3-codex-delta2-review.json`).

- B3 Codex delta2 ACCEPT_WITH_CONDITIONS (`b3-codex-delta2-review.json`); N1/N2 + polling wording fixed.
  **B3 accepted with conditions.** Carried named conditions: REVOCATION_AFTER_LEASE and CRASH_AFTER_LEASE tests
  before B5 route activation; serialization evidence boundary as stated in design §4.

- `8a28db334` B4 part 1: `server/services/package_export_worker.py` (deterministic ZIP builder, golden
  `sha256:99ff4053…`), `tests/unit/server/services/test_package_export_worker.py` 12 passed.

- B4 part 2: `a9fe10524` schema (migration `8a5d0f6b1e44`), `989715c68` ExportRepository + shared `open_beneath`,
  `795d6a399` `PackageExportService` (`server/services/package_export.py`), route family + registry entry
  `local-zip-package-export@host-export-v1` with `export-route-qualification.json`. PG `test_package_export.py`
  10 passed; related M10 PG suites 139 passed; unit/scripts/migrations 5588 passed; all gates clean (exit codes
  checked). Codex B4 review running (`b4-codex-review.json`). Finalize refuses a receipt when a disposition or
  selection lands after PLANNED (attempt stays ACCEPTED, no receipt) — tested.

- B4 Codex review REWORK (`b4-codex-review.json`: H1 missing D7 confinement, M1 exports symlink, M2 locale
  collisions, M3 partial cleanup, M4 unsafe sweep, M5 envelope preflight, M6 captions layout, M7 finalize binding,
  L1 worker grammar) → `76559a862` (worker), `e2fc6d908` (A4 launcher parametrized, probe unchanged),
  `a971ecb4c` (service rework; real confined worker). PG export 22 passed; related M10 PG 124 passed;
  unit/scripts/migrations 5599 passed; gates clean. Codex delta running (`b4-codex-delta-review.json`).

- B4 delta1 REWORK (`b4-codex-delta-review.json`: N1 path-based worker authority, N2 ctime, N3 classification,
  N4 config path count, N5 work-dir init leaks, M3/M4/M5/M7 partial) → `fdb666848` (inode-pinned worker I/O,
  report/digest checks, owned work-dir publication, envelope-first planning, full archive verification).
  PG export 26 passed (real confined worker); related M10 PG 101 passed; unit/scripts/migrations 5608 passed;
  gates clean. Codex delta2 running (`b4-codex-delta2-review.json`).

- B4 delta2 REWORK → `ebd28007d`; delta3 **ACCEPT_WITH_CONDITIONS** (`b4-codex-delta3-review.json`, no H/M).
  **B4 accepted with conditions.** Carried to B8 integrated acceptance: disk-full/write/fsync/rename crash cuts,
  before/after-publication interruption, unknown recovery against an already-published object, finalize × run-seal
  writer pair; LOCAL_REGULAR_FILE_IO / trusted project root.

- B5: `821978d23` routes (`server/routers/packaging.py`, `server/services/packaging_candidates.py`), Codex review
  NOT ACCEPTED (`b5-codex-review.json`: H1 embedded-agent JWT passed Human checks, H2/H3 download currentness and
  integrity, M1 replay, M2 500s, M3 crash coverage) → `ccc4bb4da` (embedded-agent token carries `via`, refused by
  `get_current_interactive_user` everywhere; verified-snapshot download under the lock order; semantic replay).
  Route tests 12 passed; related PG 103 passed; unit 5630 passed. Codex delta running (`b5-codex-delta-review.json`).
- `27f90c235` UI: `frontend/src/features/packaging/` (route `packaging`, sidebar entry, en/vi/zh copy, axe-core
  test); `pnpm check` exit 0 (235 files / 2637 tests).

- B5 delta → `73022b4f6`; delta2 **ACCEPTED WITH VERIFICATION LIMITS** (`b5-codex-delta2-review.json`).
  The embedded-agent token now carries `via` and is refused by every interactive Human check (A3/A6 too).
- B6: baseline frozen `988321186` → measured `f4509c145` → `R2_M10_B6_DONOR_PARITY.json` (`109279660`):
  Kalinga PASS, OpenMontage PASS (17 same-fixture tests; real confined export performance measured).
- B7: preregistration + runbook frozen `59576994e` (`R2_M10_B7_PILOT_PREREGISTRATION.json`,
  `R2_M10_B7_PILOT_RUNBOOK.md`). **Pilots need the sponsor as Human** (profile publication, disposition,
  selection in an interactive session).
- `8df2456ac` finalize × run-seal writer pair (carried B4 condition). Codex pre-seal review running
  (`preseal-codex-review.json`: UI, B6, B7 prereg).

- Pre-seal review CHANGES_REQUESTED (`preseal-codex-review.json`, committed `9c385bf94`: H1 UI could not author
  chapters/localizations/groups/audience/disclosure, H2 weak OpenMontage parity, M1 local ladder flags, M2 stale
  preview selectable, M3 builder dispositions, M4 undisclosed schema stub, M5 recall, M6 determinism/EPERM) →
  `07e69875c` (one-case byte/value parity, pinned real schema validator, equal-size timing; parity 18 passed),
  `023543d2b` (parity report rebuilt at `07e69875c`, B7 preregistration rev 2), `2e3997b74`
  (`GET /projects/{p}/packaging/slot`; route 16 passed, export+parity 49 passed), `dc75cbcc7` (UI editors,
  input-signature preview invalidation, unsaved-draft lock, server-driven ladder/export/history; `pnpm check`
  exit 0, 2641 tests). Static gates clean at `9c385bf94`. Codex delta1 running (`preseal-delta1-codex-review.json`).
  Parity `integrated_head` predates the `package_export.py` signature refactor in `2e3997b74`; rebuild at the seal HEAD.

- Pre-seal delta1 CHANGES_REQUESTED (N1 UI refresh scope, N2 parity head binding, N3 slot race, M1 partial) →
  `29168da35`, parity rebound `6f92db859`; delta2 CHANGES_REQUESTED (N3 partial: earlier refusal masked a moved head)
  → `975584c87` (verified failing without the fix), parity rebound `19f0842de`; **delta3 ACCEPTED_WITH_CONDITIONS**
  (`preseal-delta3-codex-review.json`). Seal candidate: `R2_M10_B_CANDIDATE.json`.

- B7 pilots run 2026-10-29 by the agent under the sponsor's chat delegation (all steps, Chrome via Playwright on a
  local non-production host): `R2_M10_B7_PILOT_SUMMARY.json` + three dossiers + `m10-b7-pilot/` (scripts, shots,
  network experiment). Recall 7/7 x3, 0 FP, export <= 1.9 s, peak <= 23 MB, EPERM; **not passed as preregistered**:
  cross-root determinism fails (manifest provenance), reviewer identity deviated. Findings F1 (High: V2 finals
  yuvj420p refused by the CONTAINER_STREAM probe), F2, F3, F4.

- B7 findings decided by the agent after research (sponsor rule: decide, don't ask): F1 probe admits full-range
  `yuvj420p` + A4 route requalified (`0299b0a11`, 180 tests); F3 custody owner from `PackagingDeps` (`55edfa11c`);
  F2 determinism defined by same-selection re-export + content members, provenance stays in the manifest
  (`7609bceac`, post-run amendment recorded); F4 was a pilot-harness artifact (uvicorn re-raises SIGTERM). Run 2 on
  the original finals: all thresholds met under the amended definition (`R2_M10_B7_PILOT_SUMMARY.json` v2).
  B6 parity rebound to `7609bceac`.

- Codex review of the B7 fixes **ACCEPTED_WITH_CONDITIONS** (`b7-fixes-codex-review.json`, no H/M); L1-L3
  (utility-effect computation, member comparator, candidate wording) fixed; conditions C1-C3 carried in the candidate.

## Next step

B8 seal: assemble M10-B acceptance from `R2_M10_B_CANDIDATE.json` (packets, reviews, carried conditions) and run the
B8 integrated checks the candidate lists (crash cuts, slot contention, accessibility). Then M10 integrated acceptance.
Nothing pushed; merge/tag/deploy are Human gates.
