# R2-M7D Backup and Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close H6-H7 and earn `RECOVERY_VERIFIED` through clean-target
PostgreSQL/media restore plus complete secret-safe generation correlation.

**Architecture:** A write/GC-fenced BackupSet binds one database recovery point to
an immutable media inventory. OpenTelemetry supplies runtime correlation while
durable domain IDs preserve joins across restart; source-side allowlists prevent
secret entry before collector defenses.

**Tech Stack:** PostgreSQL backup tooling, Python filesystem/media probes,
OpenTelemetry API/SDK/OTLP, pytest and existing Golden fixtures.

**Spec:** `docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md`

## Global Constraints

- Start only from accepted clean M7-C at Alembic head `7b7c4a0e0001`.
- Execute umbrella Tasks 17-19 only, against explicit disposable targets.
- Never infer or touch production DB/media paths; no credentials enter manifests.
- Stop after M7-D evidence for Codex review.

---

### Task D1: Create and verify consistent backup sets

**Files:** `r2/host_hardening/backup.py`, `server/services/backup_sets.py`, explicit
create/verify scripts, backup unit/integration tests.

**Interfaces:** Produce deterministic `BackupSetManifest`, `BackupVerdict`,
`create_backup_set(...)` and `verify_restored_backup_set(...)` from the spec.

- [ ] Write failures for split recovery point, missing/corrupt media, changed
  release/schema, incomplete copy, GC race, secret/path leakage, source-target
  alias and non-empty restore target.
- [ ] Run focused tests; expected RED is missing services/scripts.
- [ ] Implement mutation/promote/GC fencing, sorted exact-version media inventory,
  checksums and 100% DB/master/manifest closure. Commands require explicit roots.
- [ ] Run disposable PostgreSQL/media integration; expected GREEN produces
  deterministic manifest bytes and rejects every incomplete set.
- [ ] Commit `feat(host): define consistent database media backup sets`.

### Task D2: Add secret-safe telemetry joins

**Files:** `r2/host_hardening/telemetry.py`, `server/telemetry.py`, all
scope-verifier-enumerated attempt/provider/candidate/promotion/usage/event seams,
policy and correlation tests.

**Interfaces:** Produce allowlisted attributes,
`public_provider_job_ref(raw_id, key, key_version) -> str` and restart span links.

- [ ] Place a unique canary in credentials, prompt, URL, headers, provider body
  and filesystem path; assert absence from logs, in-memory OTLP export, baggage and
  public event rows while the durable ID join is complete.
- [ ] Run focused tests; expected RED is missing common policy or leaked canary.
- [ ] Implement source minimization, keyed HMAC job refs, baggage clearing and
  low-cardinality metric labels. Collector redaction is defense in depth only.
- [ ] Run focused/static/dependency gates; expected GREEN has zero canary matches
  and request-to-usage/master closure.
- [ ] Commit `feat(host): correlate generation without leaking secrets`.

### Task D3: Restore to a clean disposable target

**Files:** clean-target integration test,
`docs/r2/runbooks/m7-backup-restore.md`,
`docs/r2/evidence/R2_M7_D_RECOVERY_VERIFIED.json`.

**Interfaces:** Produce a current machine verdict `RECOVERY_VERIFIED | REJECTED`
with measured, not assumed, RPO/RTO.

- [ ] Seed Golden A/B DB/master/version/event/usage and media into disposable
  sources, create the set, destroy those sources and restore into empty targets.
- [ ] Run database verification, 100% media/master probes and no-provider
  review/export; record recovery point and measured RPO/RTO.
- [ ] Run all H1-H7, migrations, provider regressions, frontend, scope/static and
  test-audit gates at the exact candidate HEAD.
- [ ] Commit accepted evidence as `docs(r2): record M7-D recovery verification`
  or record `REJECTED`; stop for Codex review.
