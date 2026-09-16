# R2-M7E Production Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close H8 and assemble a reproducible `PRODUCTION_CANDIDATE` dossier
without granting production activation.

**Architecture:** Pinned upstream candidates and exact provider/API versions pass
schema-first compatibility and qualification gates. Restore-derived Golden A/B,
browser workflow and operator runbooks bind all evidence to one clean release
identity.

**Tech Stack:** Python/JSON Schema/Git, backend and frontend gates, browser E2E,
Golden fixtures and evidence hashing.

**Spec:** `docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md`

## Global Constraints

- Start only from independently accepted clean M7-D/`RECOVERY_VERIFIED`.
- Execute umbrella Tasks 20-22 only.
- Paid canary execution, credentials and deployment remain separately approved
  operations; implementation only creates refusal gates and offline fixtures.
- The dossier may claim `PRODUCTION_CANDIDATE`, never `PRODUCTION_APPROVED`.

---

### Task E1: Verify upstream and provider candidates

**Files:** `r2/host_hardening/compatibility.py`, upstream/provider verifier
scripts, both JSON schemas and unit tests.

**Interfaces:** Produce `COMPATIBLE | INCOMPATIBLE` and provider status
`UNQUALIFIED | OFFLINE_VERIFIED | SANDBOX_VERIFIED | QUALIFIED`.

- [ ] Write failures for missing provenance/pin, incomplete range inventory,
  absent disposition, migration failure, dirty/stale SHA, required skip,
  mock-only provider proof, expired version and absent rollback target.
- [ ] Run focused tests; expected RED is missing verifiers.
- [ ] Implement deterministic schema-first verification. `git range-diff` is
  review evidence, never the sole gate; enabled release routes require exact
  QUALIFIED evidence and `supports_webhook=false` for M7 v1.
- [ ] Run tests and JSON/schema checks; expected GREEN accepts complete fixtures
  and fail-closes every incomplete report.
- [ ] Commit `feat(r2): gate upstream and provider compatibility`.

### Task E2: Prove restore-derived Golden and browser behavior

**Files:** M7 E2E test, Golden runner, provider-reconciliation, incident/rollback
and production-candidate runbooks, candidate dossier.

**Interfaces:** Produce a redacted workflow chain from request through dual-profile
Golden B, attempt/candidate/master/usage, reconnect and export.

- [ ] Write offline browser failures for create/generate/review, failed
  regeneration preserving master, approval, SSE resync, export and foreign-scope
  denial. Run Western-generic and CN-short-drama siblings from the same Canon.
- [ ] Execute against a restore-derived disposable environment; expected GREEN
  before any paid canary can be considered.
- [ ] Implement canary CLI refusal unless exact provider qualification, credential
  authority and bounded budget evidence are supplied; test refusal only.
- [ ] Complete explicit-target deploy/config/secret/reconcile/cancel/backup/
  restore/incident/rollback/cost-cap runbooks.
- [ ] Commit `test(r2): prove M7 production candidate workflow`.

### Task E3: Run final gates and seal the dossier

**Files:** final immutable fields in
`docs/r2/evidence/R2_M7_E_PRODUCTION_CANDIDATE.json` only.

- [ ] Run full backend gates from `AGENTS.md`, test audit, frontend/website checks,
  migration round trips, H1-H8, both verifiers and browser/Golden workflows.
- [ ] Confirm non-zero selections, no required skip, complete migration-graph
  digest, one expected head, clean tree and evidence SHA equal to candidate HEAD.
- [ ] Refresh graph coverage for every claimed path and read every reported missed
  range before an exhaustive claim.
- [ ] Set `PRODUCTION_CANDIDATE` only when M7-A…E are independently accepted;
  otherwise record `REJECTED` with exact stop codes.
- [ ] Commit `docs(r2): finalize M7 production candidate` and stop without push,
  deployment, migration, provider call, live restore or production approval.
