# R2-M8D Learning Recommendations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Persist source-faithful observations and produce profile-isolated, non-authoritative recommendations with inspectable evidence and Human disposition.

**Architecture:** Append-only corrections feed cutoff-aware pure folds, transparent cohort summaries and offline replay. Recommendation services have no authority write ports; acceptance produces only a separately governed proposal reference.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL 18, FastAPI, React/TypeScript, pytest and Vitest.

**Spec:** `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`

## Global Constraints

- Execute D1-D4 only from accepted clean M8-C; use migration `8d8c4a0e0001`.
- Preserve source metric name/version/window/timezone/API scope/raw digest and correction lineage.
- Scope every observation and recommendation read/write explicitly by
  `(user_id, project_name)`; foreign and unknown identities remain indistinguishable.
- Isolate `generic-western` and `zh-shuang`; holdout is project-disjoint then future-time.
- Causal language is allowed only for concurrent randomized/platform-managed evidence within its surface.
- Stop at clean M8-D evidence HEAD.

### Task D1: Persist observations and corrections

**Files:** migration/model/repository extensions and PostgreSQL tests.

- [ ] Execute D1 for exact replay, divergent duplicate, correction chain, late/delete/private/missing and scope behavior.
- [ ] Commit `feat(learning): persist lineage-bound observations`.

### Task D2: Preserve source semantics through adapters

**Files:** learning folds, internal/platform adapters and fixtures.

- [ ] Execute D2 against Usage/QA/approval/M7 plus YouTube/TikTok fixture semantics.
- [ ] Prove derived features retain all source IDs and transformation versions.
- [ ] Commit `feat(learning): normalize observations without erasing source semantics`.

### Task D3: Add recommendation lifecycle

**Files:** services/router, learning UI and backend/frontend tests.

- [ ] Execute D3 leakage, holdout, causal-language, expiry/currentness, repeat-rejection and authority-boundary tests.
- [ ] Implement summaries/rules, replay and immutable Human dispositions; run `pnpm check`.
- [ ] Commit `feat(learning): add scoped recommendation lifecycle`.

### Task D4: Seal learning evidence

**Files:** `docs/r2/evidence/R2_M8_D_LEARNING.json`.

- [ ] Run correction/idempotency/leakage/replay/authority/browser suites at exact HEAD with zero skips.
- [ ] Commit `test(r2): prove non-authoritative learning lifecycle`; stop for review.
