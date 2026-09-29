# R2-M8C Spatial Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Add evidence-preserving spatial experiments whose selected normalization behavior meets or improves the pinned DramaClaw source.

**Architecture:** Pure schema validation/normalization consumes model output only after M7 execution. SpatialCandidate retains visible, inferred and gap evidence; explicit M8-A promotion is the only production bridge.

**Tech Stack:** Python 3.12+, Pydantic v2, M7 execution, pytest and PostgreSQL-backed M8-A revisions.

**Spec:** `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`

## Global Constraints

- Execute umbrella C1-C3 only from accepted clean M8-B.
- Use the exact DramaClaw pin and source/fixture hashes from the verified baseline.
- Model temperature never proves determinism; inference remains evidence, and gaps never become facts.
- No direct ProductionBinding or master write; stop at clean M8-C evidence HEAD.

### Task C1: Port deterministic spatial normalization

**Files:** spatial baseline/fixtures, `r2/advanced_creative/spatial.py` and tests.

**Interfaces:** Consume M8-A `SpatialCandidate`/`SpatialPayload`; return a
validated `SPATIAL` discriminated payload for `ExplorationRevision`.

- [ ] Execute C1 with visible/inferred/gap/seam/direction/duplicate and malformed/partial same-fixture cases.
- [ ] Document donor defect corrections with failing donor fixtures and stronger R2 outcomes.
- [ ] Commit `feat(spatial): port evidence-preserving normalization`.

### Task C2: Execute and promote bounded candidates

**Files:** host service/router extensions and execution/recovery/promotion tests.

- [ ] Execute C2 for failure/cancel/restart/fingerprint/schema/currentness paths.
- [ ] Prove only validated SpatialCandidate revisions exist and promotion cannot translate gaps into facts.
- [ ] Commit `feat(spatial): execute and promote bounded spatial candidates`.

### Task C3: Seal parity

**Files:** `docs/r2/evidence/R2_M8_C_SPATIAL_PARITY.json`.

- [ ] Run donor differential, fault, replay and authority-boundary suites with zero unknown/skips.
- [ ] Commit `test(r2): prove spatial candidate parity`; stop for review.
