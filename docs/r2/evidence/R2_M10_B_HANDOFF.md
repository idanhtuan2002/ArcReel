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

## Next step

Write the M10-B design amendment (contracts, PackagingCandidate/PACKAGING_SLOT evolution, selection, export,
F1, pilots, UI), independent review, then packetized implementation.
