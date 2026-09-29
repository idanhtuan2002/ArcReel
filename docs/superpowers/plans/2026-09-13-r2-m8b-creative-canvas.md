# R2-M8B Creative Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Port the best verified DramaClaw Canvas behavior into an accessible ArcReel Creative Canvas with quality at least equal to the selected donor surface.

**Architecture:** Pure graph/history behavior is ported first, save/recovery second, and React Flow UI last. The browser holds only a recovery cache; M8-A owns server revisions and promotion.

**Tech Stack:** React 19, TypeScript, Zustand 5, React Flow 12, Vitest, Playwright and the M8-A API.

**Spec:** `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`

## Global Constraints

- Read ADR/spec/umbrella and execute B1-B4 only from independently accepted clean M8-A.
- Pin DramaClaw `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`; verify selected path hashes before porting.
- Every selected reachable behavior and donor test maps to a parity row. Unverified material behavior blocks the packet.
- Require the sponsor-approved production graph envelope named by
  `R2_M8_EXECUTION_CONTRACT_2026-09-13.json`; if absent, stop
  `M8_REQUIRED_EVIDENCE_MISSING` without asking Claude to choose it.
- Add keys to the exact supported `en`, `vi`, and `zh` catalogs; keep local
  storage recovery-only and require explicit user clear intent.
- Stop at clean M8-B evidence HEAD; do not start Spatial.

### Task B1: Port pure behavior

**Files:** Canvas donor baseline/fixtures,
`docs/r2/evidence/R2_M8_B_CANVAS_BENCHMARK_PROTOCOL.json`, and
`frontend/src/features/creative-canvas/domain/` with tests.

- [ ] Execute umbrella B1: freeze reachable surface, run donor tests, create same-fixture RED tests, then port graph/group/history/bookmark/payload behavior.
- [ ] Before results, freeze exact node/edge ladder, operations,
  browser/build/hardware, repetitions, latency/memory/bundle thresholds.
- [ ] Emit differential rows with no selected branch omitted.
- [ ] Commit `feat(canvas): port parity-proven graph behavior`.

### Task B2: Preserve save and recovery semantics

**Files:** `saveCoordinator.ts`, `draftRecovery.ts`, Zustand slice and tests.

- [ ] Execute umbrella B2; include in-flight coalescing, waiters, switching, corrupt/oversized/expired drafts, shedding and empty-clear races.
- [ ] Prove reload/conflict never silently overwrites the server revision.
- [ ] Commit `feat(canvas): preserve saves and recover drafts safely`.

### Task B3: Integrate accessible Canvas UI

**Files:** Canvas components/API/route, host navigation, `en`/`vi`/`zh` i18n,
Vitest/browser tests, pinned React Flow, direct `axe-core@4.13.0`, dependency lock.

- [ ] Execute umbrella B3 RED/GREEN flow for operations, preview, keyboard, screen reader, focus and conflict UI.
- [ ] Run `pnpm check`, `eslint-plugin-jsx-a11y`, automated `axe-core`,
  keyboard/focus browser suites, bundle report and pre-registered graph ladder.
- [ ] Commit `feat(canvas): integrate accessible creative canvas`.

### Task B4: Seal donor parity

**Files:** `docs/r2/evidence/R2_M8_B_CANVAS_PARITY.json`.

- [ ] Run every selected donor/port/host test and verify every quality/resource dimension at exact HEAD.
- [ ] Commit `test(r2): prove Creative Canvas donor parity`; stop for review.
