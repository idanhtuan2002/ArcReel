# R2-M7B Atomic Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close H3-H4 with immutable candidates and one transactionally
authoritative master head while preserving ArcReel's Production authority.

**Architecture:** Candidate bytes become immutable and verified before authority
commit. Existing `ProductionApprovalService` delegates one expected-version CAS;
all authoritative reads use a resolver that detects compatibility-projection
divergence. Existing cleanup routes share one retention guard.

**Tech Stack:** Python 3.12+, SQLAlchemy/Alembic/PostgreSQL, filesystem safety,
pytest, ruff, basedpyright and Codebase Memory.

**Spec:** `docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md`

## Global Constraints

- Start only at an independently accepted clean M7-A head
  `7a7c4a0e0001`; otherwise stop.
- Execute umbrella Tasks 9-12 only. Do not add a second approval or GC authority.
- Candidate bytes are immutable; promotion event uses the M7-A project-event table.
- Stop after M7-B evidence for Codex review.

---

### Task B1: Add immutable candidate storage and retention guard

**Files:** `lib/candidate_store.py`, `r2/host_hardening/retention.py` and
unit/fault tests.

**Interfaces:** Produce `prepare_candidate`, `verify_candidate`, `quarantine` and
exact `CandidateRetentionPolicy.can_delete` from the spec.

- [ ] Write failures for disk full, hash/probe mismatch, cross-mount rename,
  symlink escape, duplicate unequal bytes and kill after rename. Test the
  injected guard with repository fakes for each protected reference kind.
- [ ] Run focused tests; expected RED is missing store/guard.
- [ ] Implement same-filesystem temp-write/flush/fsync/verify/immutable rename and
  deny deletion for master, active-attempt, retained-receipt or incomplete-backup
  references.
- [ ] Run focused and project-path security tests; expected GREEN preserves the
  old master at every fault.
- [ ] Commit `feat(host): add immutable candidate retention boundary`.

### Task B2: Persist append-only master authority

**Files:** extend hardening models/repository,
`alembic/versions/7b7c4a0e0001_add_atomic_master_promotion.py`, every
graph-inventoried candidate deletion route, migration/repo/architecture tests.

**Interfaces:** Create candidate objects, master heads/versions, promotion
receipts and backup sets with `down_revision = "7a7c4a0e0001"`.

- [ ] Write failures for immutable digest, one scoped head, exact command replay,
  conflicting receipt, approval/usage refs, backup-set state/reference retention
  and concurrent expected-version CAS.
- [ ] Run tests; expected RED is missing revision/tables.
- [ ] Implement reversible migration and append-only repository operations.
  Inventory and wire every existing deletion route through the shared retention
  guard after all backup-reference tables exist; reject bypasses architecturally.
- [ ] Run SQLite mechanics and real-PostgreSQL concurrency; expected GREEN is one
  winner and complete history.
- [ ] Commit `feat(db): add atomic master head persistence`.

### Task B3: Route approval and reads through the atomic authority

**Files:** `r2/host_hardening/{promotion,master_resolver}.py`, existing Production
approval/artifact bridge, promotion and master-reader boundary tests.

**Interfaces:** Produce exact `AtomicPromotionService.promote` and
`MasterResolver.get_exact`; retain one public Production approval entrypoint.

- [ ] Inventory every master/current-version reader with graph+coverage. Add
  failures for direct legacy authority, candidate/lock/commit/projector cuts,
  projector crash/replay, divergence and concurrent promotion.
- [ ] Run focused/architecture tests; expected RED exposes unguarded readers or
  missing DB authority.
- [ ] Delegate existing approval validation to atomic promotion; append head,
  receipt, usage link and event together, then project manifest/version
  idempotently. Resolver fails closed on mismatch.
- [ ] Run all M4/M7 production and manifest/version regressions; expected GREEN
  shows complete old or complete new authority at every cut.
- [ ] Commit `feat(r2): make master promotion transactionally authoritative`.

### Task B4: Produce M7-B acceptance evidence

**Files:** `docs/r2/evidence/R2_M7_B_ATOMIC_PROMOTION.json`.

- [ ] Run H3/H4 fault matrix, PostgreSQL CAS, candidate security/retention,
  master-reader boundary, legacy projections, scope verifier and static gates.
- [ ] Record exact head, fault cuts, pre/post master versions/digests, reader and
  deletion inventories, commands/exits and evidence hashes.
- [ ] Commit accepted evidence as `docs(r2): record M7-B promotion acceptance` or
  record `REJECTED`; stop for Codex review.
