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

## Next step

Triage the B2 Codex review. Then B3: preview + Human selection into `PACKAGING_SLOT` (§4 global lock order,
custodian lease like A6, `m10_package_previews`/`m10_package_selections`/`m10_packaging_heads`, writer-pair PG
tests), then B4 export, B5 routes+UI, B6 parity, B7 pilots (Human gates), B8 seal.
