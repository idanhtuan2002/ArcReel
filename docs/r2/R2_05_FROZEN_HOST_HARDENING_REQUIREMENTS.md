# R2.5 — Frozen Host Hardening Requirements

**Project:** Content & Narrative Production OS  
**Phase:** R2 — Architecture Freeze  
**Date:** 2026-09-06  
**Status:** **FROZEN v1**  
**Approval:** Human Showrunner approved R2.5 on 2026-09-06  
**Depends on:** R2.1–R2.4  
**Host baseline:** ArcReel v0.29.0 / `6ddedc775e7fe5f398b10081ab741985f7dceda7`

---

# 1. Purpose

R2.5 defines the hardening gates that turn the already-locked ArcReel-derived Host from an architecture choice into a production-capable R2 runtime.

These requirements do **not** reopen Host selection.

They define:
- execution identity safety;
- idempotency;
- artifact preservation;
- transaction boundaries;
- restart recovery;
- backup/restore;
- observability;
- upstream upgrade safety;
- R2 extension policy;
- maturity gates.

---

# 2. Host status

ArcReel-derived Host remains:

```text
LOCKED
```

R1.8 verified on target Ubuntu:
- PostgreSQL migration;
- restart health;
- Artifact/Workflow tests;
- current/stale/missing/blocked behavior;
- failed-regeneration preservation;
- restart/orphan recovery;
- idempotency/dedup;
- REST/MCP consistency;
- PostgreSQL/media backup and restore.

R2 fork changes require re-running the relevant gates.

---

# 3. Hardening gates

## H1 — Execution Identity

**Requirement ID:** `R2-HOST-001`  
**Severity:** production blocker

Every remotely submitted asynchronous generation must persist the actual execution identity used at submission.

Required identity:

```text
ExecutionIdentity
  provider
  model
  endpoint
  submitted_base_url
  provider_job_id
  adapter_version
  capability/version metadata where needed
```

Required order:

```text
ProviderRequest created
→ submit to provider
→ receive remote identity
→ persist ExecutionIdentity
→ mark task as remotely submitted
```

Recovery must use persisted identity:

```text
restart
→ load task
→ load ExecutionIdentity
→ resume exact original provider/endpoint
```

Forbidden:

```text
restart
→ resolve current provider defaults
→ poll old provider_job_id through new provider
```

### Preferred implementation

Persist real execution identity atomically at provider submission.

### Temporary mitigation

Until H1 is fully implemented:

```text
affected active I2V task exists
→ reject provider/base-url reconfiguration
```

### Acceptance tests

1. submit through provider A;
2. persist provider job ID + endpoint + submitted base URL;
3. restart backend;
4. change default provider to B;
5. recovered task still polls A;
6. no resubmission;
7. no duplicate authoritative charge;
8. artifact state remains consistent.

---

## H2 — Idempotency

Same authoritative submission basis must not create duplicate remote work.

Idempotency basis should include stable values such as:
- project/user scope;
- target resource;
- operation;
- content/request basis;
- client key/dedup identity as appropriate.

Required semantics:

```text
same request
+ same idempotency basis
→ same durable task/batch
```

Forbidden:

```text
double click
network retry
SSE disconnect/reconnect
agent retry
backend restart
→ duplicate provider submission
```

Acceptance:
- one remote submission;
- one authoritative cost record;
- repeated caller receives existing durable task/batch.

---

## H3 — Artifact Safety

New generation is staged until promotion.

Required:

```text
ApprovedMaster B
→ generate C
→ C fails
→ B stays CURRENT + APPROVED
```

Generation success also does not replace B automatically:

```text
C generated
→ QA
→ review
→ SELECT
→ PROMOTE
→ master becomes C
```

Forbidden:

```text
latest generated file = authoritative master
```

Acceptance:
- failed output cannot overwrite current file;
- failed forced regeneration preserves prior manifest entry/master;
- selection is explicit and auditable.

---

## H4 — Transaction Boundary

Formal production promotion must be atomic from the perspective of authoritative readers.

A promotion may involve:
- staged media file;
- version row;
- manifest entry;
- provenance;
- content fingerprint;
- candidate state;
- approval/master pointer.

Required invariant:

```text
either old authoritative state is intact
or new authoritative state is fully committed
```

No partial formal state.

Acceptance tests:
- failure before DB commit;
- failure after staging file;
- failure during manifest update;
- crash between candidate generation and promotion;
- concurrent promotion attempt.

---

## H5 — Recovery

ArcReel runtime owns recovery.

Required:
- RUNNING/CANCELLING/orphan tasks are classified deterministically;
- tasks with resumable provider identity resume without resubmit;
- unsupported recovery fails safely;
- active workflow plans continue to observe durable tasks after restart;
- local download failure may retry/resume without remote duplicate where supported.

Acceptance:
- process kill/restart;
- remote task still running;
- remote task completed while local process was down;
- cancellation across restart;
- provider timeout;
- endpoint rebound mismatch;
- SSE loss.

---

## H6 — Backup / Restore

Authoritative backup set includes:

```text
PostgreSQL
project/media data
Artifact Manifest / formal artifact files
required configuration metadata
```

Restore must produce a mutually consistent snapshot.

Required checks:
- Alembic head matches;
- project records resolve;
- manifests point to existing files;
- approved master pointers resolve;
- provider credentials/secrets follow secure backup policy;
- restore can occur to a clean target.

R1.8 baseline C8 already passed; repeat after R2 Host modifications.

---

## H7 — Observability

Every generation must be traceable:

```text
user/agent request
→ MethodDecision
→ ProviderRequest
→ durable task/batch
→ ExecutionIdentity
→ provider job
→ GenerationCandidate
→ QA/review
→ ApprovedMaster
→ cost/usage
```

Minimum correlation fields:
- operation/request ID;
- project/user;
- target ref;
- task/batch IDs;
- provider job ID;
- candidate ID;
- selected master ID;
- cost record;
- failure/recovery reason.

Secrets must be redacted.

---

## H8 — Upgrade Safety

ArcReel upstream updates are not merged directly into R2 Host.

Every upstream integration runs:

```text
1. DB migration checks
2. upstream focused regression
3. R2 architecture/contract tests
4. Golden A smoke
5. Golden B smoke once available
```

Reject or adapt an upstream change if it:
- creates a second authority;
- leaks provider/model into stable R2 contracts;
- changes artifact currency semantics incompatibly;
- weakens execution identity;
- breaks direct dependency invalidation;
- changes task/idempotency behavior without migration;
- bypasses R2 adapter boundaries.

---

# 4. R2 Host extension policy

The initial Host fork may add R2 only through declared seams.

Allowed initial extension areas:

```text
ContentBasis integration
direct dependency/fingerprint basis
R2 ProductionBinding references
ApprovedMaster semantics
R2 adapter interfaces
architecture permission tests
R2-HOST-001 hardening
R2 metadata/provenance bridges
```

Do not rewrite without executable blocker evidence:

```text
generation queue
task state machine
provider backend abstraction
Artifact Manifest core
artifact currency engine
restart/recovery machinery
cost accounting
existing version history
```

---

# 5. Database policy

Production-development baseline:

```text
PostgreSQL
```

SQLite remains useful for upstream/local tests where ArcReel uses it, but the R2 Host development/runtime baseline is PostgreSQL.

R2 domain contracts do not automatically become one table per contract.

Physical persistence design happens in implementation planning and must preserve:
- R2 authority boundaries;
- transaction semantics;
- lineage;
- direct-edge invalidation;
- migrations.

---

# 6. Runtime / artifact / approval separation

The following state machines remain orthogonal:

```text
Runtime:
QUEUED/RUNNING/.../FAILED

Artifact currency:
CURRENT/STALE/MISSING/BLOCKED

Creative approval:
DRAFT/.../APPROVED/REJECTED

Candidate selection:
UNREVIEWED/REJECTED/SELECTED
```

A failed task may coexist with an APPROVED + CURRENT old master.

This is expected behavior, not inconsistency.

---

# 7. Provider qualification

A real cloud-provider E2E is no longer a Host architecture gate.

It belongs to provider qualification.

Each provider later receives a qualification profile covering:
- submit;
- status/poll;
- restart resume;
- cancellation;
- rate limiting;
- cost capture;
- reference semantics;
- first/last frame support;
- error redaction;
- timeout/retry;
- capability metadata.

Provider failure does not reopen Host architecture unless it exposes a Host abstraction blocker.

---

# 8. Maturity states

R2 Host maturity:

```text
DEV
→ INTEGRATION_READY
→ RECOVERY_VERIFIED
→ PRODUCTION_CANDIDATE
→ PRODUCTION_APPROVED
```

## DEV
Core extensions compile and focused tests pass.

## INTEGRATION_READY
R2 contracts/adapters integrate with Host and Golden A can run.

## RECOVERY_VERIFIED
H1–H6 fault/recovery gates pass after R2 extensions.

## PRODUCTION_CANDIDATE
Golden A and Golden B pass with production-like configuration, observability and backup/restore.

## PRODUCTION_APPROVED
Human/operations approval after security, provider qualification, restore drill and launch checklist.

R1.8 baseline ArcReel reached approximately `RECOVERY_VERIFIED`; the R2 fork must earn the state again.

---

# 9. Architecture tests required in Host fork

R2 should mechanically test:

1. `SceneSpec`/`ShotSpec` contain no provider/model/endpoint fields.
2. one commit authority per authoritative contract.
3. runtime worker cannot import/use Canon commit APIs.
4. Canvas/Simulation adapters have no production/Canon direct commit permission.
5. ContentBasis exists for production-boundary artifacts.
6. content fingerprint excludes execution-only fields.
7. failed generation preserves selected master.
8. provider resume uses persisted execution identity.
9. no second artifact registry/queue authority is introduced.

---

# 10. Security baseline

At minimum:
- localhost/private deployment by default during development;
- credentials not stored in project artifacts;
- provider secrets redacted from logs/errors;
- backup secret policy explicit;
- user/project scope preserved in dedup/recovery queries;
- destructive migration requires backup/restore check.

Security hardening may add requirements later without reopening R2.1 ownership boundaries.

---

# 11. R2.5 frozen requirements

The following are frozen:

1. H1 Execution Identity is a production blocker.
2. H2 Idempotency must prevent duplicate authoritative remote submissions.
3. H3 failed regeneration preserves prior usable master.
4. H4 promotion is transactionally safe.
5. H5 recovery is deterministic and Host-owned.
6. H6 PostgreSQL + media backup/restore is mandatory.
7. H7 end-to-end generation correlation is mandatory.
8. H8 upstream merge uses layered compatibility gates.
9. R2 extends ArcReel seams before rewriting Host internals.
10. PostgreSQL is the R2 production-development baseline.
11. external provider E2E is provider qualification, not Host-selection gate.
12. R2 fork must re-earn recovery/production maturity after extensions.

**Status: COMPLETE / FROZEN v1**
