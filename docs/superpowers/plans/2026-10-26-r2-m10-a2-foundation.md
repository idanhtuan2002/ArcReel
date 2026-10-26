# M10 A2 pure foundation implementation plan

> **For agentic workers:** Use superpowers:executing-plans serially, with test-driven-development. Read the spec and exact packet; do not implement until two actual independent design PASS decisions and a separate pinned acceptance exist.

**Goal:** Supply safe typed errors, minimal frozen port data/Protocols and a reused parity adapter after reviewed A0/A1.

**Architecture:** Preserve all79 inherited pins. A new read-only scope guard reuses the immutable baseline Git reader, binds this packet's independent acceptance and prevents runtime expansion. Error/port/parity modules remain pure and uncomposed.

**Tech Stack:** Existing Python3.12+, Pydantic, typing.Protocol, M8 parity and pytest; no dependency/config changes.

**Spec:** docs/superpowers/specs/2026-10-26-r2-m10-a2-foundation.md

## Global constraints

- Exactly10product paths; four design paths before acceptance. Old A0/A1 files, schemas, domains, operations, namespace/config/lock and host files are immutable.
- No migration, DB, provider, subprocess probe, API/UI, live Factual/Human adapter or packaging/export.
- Original full-M10 gate remains closed; new success only M10_A2_SCOPE_OK.
- Unknown exception payloads and forged code attributes never cross error_payload.
- Source scope success/type constructors never prove actual currentness or Human authority.

## Review focus

- Lost scope in a typed descriptor must refuse; no actor=creator shortcut.
- Null/zero/uppercase/truncated HEADs cannot masquerade as integrated parity evidence.
- Reported PASS, all-excluded rows or missing dimensions cannot become measured parity.
- New source/schema/report types cannot silently replace protected predecessor data.
- Mutable history/provenance objects must be deep copies of immutable Git evidence.

## A2.0: custody guard

- [ ] RED real-Git cases for absent/wrong acceptance, changed baseline bytes/modes, staged/ignored/hidden protected work, unrelated scope delta, migration drift and forbidden imports/async implementation; assert repo snapshots unchanged.
- [ ] Implement only scripts/r2/verify_m10_a2_scope.py and its mirrored tests, pinned to the actual acceptance/ref/hash. Load verified baseline bootstrap bytes before executing its reader; validate real HEAD endpoints, bound evidence and exact source scope.
- [ ] Re-run these tests, static gates; commit only the three guard paths. No old guard modification.

## A2.1: errors, ports and parity

- [ ] RED tests in three unique test_quality_* files for the spec's errors, descriptors, interface surface, cold imports and parity differential matrix.
- [ ] Implement exactly r2/quality/errors.py, ports.py, parity.py. Reuse A1 model/scalars and M8 fold/report; no mutable Factual body or new domain/command/schema.
- [ ] Verify all typed Protocol signatures and source-only async stubs, scope/rule coherence, unknown-error canaries and every parity dimension, including the actual empty-HEAD gap.
- [ ] Run affected A2/A1/M8 tests, Ruff/format, full types, audit, import contracts and dependency gate. Commit only these six paths.

## Evidence and review

- [ ] Create only docs/r2/evidence/R2_M10_A2_CANDIDATE.json with exact source HEAD/hashes/acceptance, real commands/results, immutable history copies and explicit no-runtime limits.
- [ ] Run the clean actual scope guard; independently review the whole bounded implementation. Repair confirmed material issues, rerun relevant checks and obtain actual re-verification.
- [ ] Save durable next entry. Do not start A3 runtime, migrations or providers under this packet.
