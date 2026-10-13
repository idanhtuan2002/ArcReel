# M8-C startup attestor implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Obtain current archive evidence on every activated startup.
**Architecture:** Host attestor reuses archive preflight; a credential-checked Unix channel binds its answer to a fresh application nonce and exact four-file snapshot. Existing grant reader and review/V2 services remain the runtime authority checks.
**Tech Stack:** Python asyncio, Linux Unix sockets, PostgreSQL, existing Governance contracts.
**Spec:** `docs/superpowers/specs/2026-10-13-r2-m8c-startup-attestor-design.md`.

## Global constraints

- No live host operation, migration, provider call or new dependency.
- Socket directory `0700`, socket `0600`, production UID/GID `0:0`; no-follow descriptor custody.
- Canonical messages at most 4096 bytes plus newline; 256-bit nonce; 30-second exchange deadline.
- Reuse archive preflight, public validator, schema/scanner and transaction grant reader.
- No repeated full suite during implementation; no production READY claim from local tests.

## Review focus

- An old proof reused after process restart must deny against the new nonce.
- A socket replaced or a path symlinked during connect must deny.
- Client-supplied state must never choose a host path or alter archive verification.
- Concurrent/slow/malformed requests must release connection, lock and descriptor resources.
- A grant revoked after startup must still deny in the existing service transaction.

### Task 1: Repeat checkpoint custody for transaction reads

**Files:** `server/services/governance_checkpoint_file.py`, its mirrored unit test.
- [x] Reproduce wrong owner/directory mode/file mode/hardlink acceptance after a successful load.
- [x] Reuse the public-custody checks on every `load`; include UID/GID in stable read metadata.
- [x] Run the focused file, Ruff and test audit.
- [x] Run affected startup/PG cases and record exact committed evidence.

### Task 2: Host challenge channel and CLI

**Files:** create `server/services/governance_attestation.py`, `scripts/r2/governance_preflight.py`, mirrored integration tests.
**Interfaces:** `GovernanceArchiveAttestor.handle(reader, writer)` calls fixed-root preflight; `serve_governance_attestor(...)` yields an asyncio server; `require_governance_archive_freshness(socket_directory, copies, expected_uid=0, expected_gid=0)` authenticates peer and compares response.
- [x] Write and run failing real Unix-socket tests for matching archive, old public, wrong nonce, peer/custody, malformed and trailing response.
- [x] Implement bounded canonical request/response, anchored socket directory, per-request preflight and scoped inode cleanup.
- [x] Add explicit-root environment-DSN operator `preflight`/`serve` CLI; run focused tests, static checks and audit.

### Task 3: Activated startup and service composition

**Files:** `server/services/governance_startup.py`, `server/app.py`, existing startup and archive integration tests.
**Interfaces:** `verify_governance_activated_startup(...) -> CheckpointedShowrunnerGrantReader`; app state contains three existing services constructed with that reader.
- [x] Reproduce missing attestor and coherent-old-pair denial; test positive current archive/DB startup and revoked transaction use.
- [x] Share local verification code, call authenticated freshness after scan and before final public reread, require both environment inputs, skip activated auto migration.
- [x] Verify normal mode, lifespan quarantine ordering and cleanup with focused tests.

### Task 4: Real restore and final review

**Files:** versioned `tests/integration/r2/governance/` restore drill and existing durable handoff.
- [x] Run a same-major PostgreSQL dump/restore of ISSUE before REVOKE, keeping newer archive independent; compare before/after schema and rows and assert actual lifespan denial.
- [x] Run post-REVOKE positive lifespan and existing service denial, then full affected Governance/static gates once.
- [ ] Commit exact scope; obtain independent review and repair concrete findings with selected tests.
- [x] Record remaining host/full-suite/READY gates without treating local fixtures as host custody.

## Pause checkpoint: sponsor requested session handoff

The affected-domain run completed with **387 passed, 4 skipped, 1 warning** in
98.69 seconds on disposable PostgreSQL 18. Repository Ruff/format, full
basedpyright (0 errors, 0 warnings), import contracts (22 kept), deptry and test
audit (0 violations) passed. No full backend suite was run in this session.
Production root/socket ownership is represented by injected disposable UID/GID
in integration fixtures; actual-host custody and independent review remain open.
The real socket tests cover successful peer credentials and negative pathname
custody, not a separately forced wrong SO_PEERCRED response or connect-time
inode replacement. Timeout/malformed request and importer/scan interleaving
coverage should be assessed during the pending review; do not claim the entire
spec matrix is accepted.

Resume from `docs/r2/evidence/R2_M8C_STARTUP_ATTESTOR_CHECKPOINT_20261013.json`
and the newest section of `R2_M8C_FRAME_CUSTODY_HANDOFF.md`. Review the exact
committed diff before any activation claim. The PostgreSQL container has been
removed; a new disposable instance is required for any additional PG test.
