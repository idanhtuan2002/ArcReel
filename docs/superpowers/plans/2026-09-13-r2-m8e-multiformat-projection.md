# R2-M8E Multi-format Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Produce governed `16:9`, `9:16`, and `1:1` projections whose selected OpenMontage mechanics meet or improve donor quality and whose meaning remains reviewable.

**Architecture:** Versioned output/overlay profiles and explicit reframe plans drive M7 render executions. Technical and semantic reports must both pass before a FormatCandidate can use M8-A promotion.

**Tech Stack:** Python 3.12+, PostgreSQL, Alembic, FFmpeg, Remotion, M7 execution, React/TypeScript, pytest, Vitest and Playwright.

**Spec:** `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`

## Global Constraints

- Execute E1-E4 only from accepted clean M8-D; use migration `8e8c4a0e0001`.
- Pin OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7` and verify selected hashes.
- Fail malformed output profiles closed. Independent aspect generation is new candidate lineage, not projection.
- Technical conformance never substitutes for semantic parity; stop at clean M8-E evidence HEAD.
- Require qualified blind semantic reviewer assignments named by the execution
  contract before E3; if absent, stop `M8_REQUIRED_EVIDENCE_MISSING`.

### Task E1: Persist projection evidence

**Files:** migration/model/repository, `formats.py` and tests.

**Interfaces:** Consume M8-A `FormatCandidate`; create it only from an immutable
plan, artifact, M7 execution and matching technical/semantic report digests.

- [ ] Execute E1 for malformed ratio, floating profile, changed master, overlay/reframe identity and append-only reports.
- [ ] Commit `feat(format): persist governed format projections`.

### Task E2: Adapt donor mechanics through M7

**Files:** OpenMontage baseline/fixtures/harness, render adapters and tests.

- [ ] Execute E2 with exact donor runs and same-fixture three-ratio, missing media/audio, cancel, codec/fps/duration and idempotency cases.
- [ ] Bind source bytes, plan/profile/overlay/reframe/runtime settings and adapter version into execution identity.
- [ ] Commit `feat(format): adapt parity-proven composition mechanics`.

### Task E3: Require both review planes

**Files:** service/router, format UI and backend/browser tests.

- [ ] Execute E3 for probe failure, collision, semantic change, disagreement, stale report and promotion blocking.
- [ ] Run actual local renders, media probes, blind-review flow and `pnpm check`.
- [ ] Commit `feat(format): require technical and semantic projection parity`.

### Task E4: Seal format parity

**Files:** `docs/r2/evidence/R2_M8_E_FORMAT_PARITY.json`.

- [ ] Verify every donor row, actual artifact, resource observation and exact HEAD with zero skips/unknowns.
- [ ] Commit `test(r2): prove multi-format projection parity`; stop for review.
