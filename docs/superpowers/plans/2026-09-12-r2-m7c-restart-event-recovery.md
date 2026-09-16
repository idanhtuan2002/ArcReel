# R2-M7C Restart and Event Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close H5 by proving exact-route execution, cancellation and project
event recovery across real process death and SSE loss.

**Architecture:** Expired attempt leases drive deterministic poll/reconciliation;
operator-paused attempts require immutable resolution receipts. PostgreSQL project
events already committed by M7-A provide cursor replay; the existing in-memory
channel is only a wake-up hint.

**Tech Stack:** Python/FastAPI/PostgreSQL/SSE, React/TypeScript, subprocess
SIGKILL tests, pytest and pnpm.

**Spec:** `docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md`

## Global Constraints

- Start only from accepted clean M7-B with head `7b7c4a0e0001`; M7-C adds no
  migration.
- Execute umbrella Tasks 13-16 only. No webhook receiver; poll/reconcile only.
- SSE is at least once and never changes task/attempt authority.
- Stop after M7-C evidence for Codex review.

---

### Task C1: Expose durable project-event replay

**Files:** hardening event repository, project-event service/router, SSE channel
and backend tests.

**Interfaces:** Implement `ProjectEventRepository.replay_after/high_watermark` and
typed `EVENT_CURSOR_EXPIRED` over the M7-A event table.

- [ ] Write failures for commit-before-publish crash, duplicate wake-up,
  subscribe/catch-up race, reconnect, expired/foreign cursor and server restart.
- [ ] Run focused tests; expected RED is inability to replay memory-only events.
- [ ] Subscribe wake-up first, capture watermark, drain durable rows and then
  wait/re-drain. Authorize every cursor by user/project and never use notification
  delivery as durability.
- [ ] Run existing and new project-event/SSE tests; expected GREEN allows
  duplicates but no gaps.
- [ ] Commit `feat(host): make project event streams durable`.

### Task C2: Make frontend cursor resync deterministic

**Files:** SSE utility, project-events hook, API client, every supported locale,
utility/hook tests.

**Interfaces:** Deduplicate event IDs per project and replace projection from an
authoritative snapshot after `EVENT_CURSOR_EXPIRED`.

- [ ] Write failures for duplicate event, visibility reconnect, project switch,
  expired cursor, stale snapshot response and localized snapshot failure.
- [ ] Run focused pnpm tests; expected RED is duplicate application or generic
  expiry failure.
- [ ] Implement snapshot replacement, cursor reset to returned watermark and
  reconnect; discard stale responses from a prior project/generation.
- [ ] Run focused tests, i18n consistency and `(cd frontend && pnpm check)`;
  expected GREEN.
- [ ] Commit `feat(frontend): recover project events from durable cursor`.

### Task C3: Prove process, cancel and operator recovery

**Files:** generation worker, resume/attempt services, provider subprocess
fixture, process and cancel integration tests.

**Interfaces:** Expired-attempt scanner uses exact route and lease token;
`resolve_operator_review` is the only exit from `NEEDS_OPERATOR`.

- [ ] Add deterministic barriers and SIGKILL tests before submit, after provider
  acceptance, after local acceptance, mid-poll, after download and after cancel
  intent. Complete the remote job while the application is absent.
- [ ] Run focused tests; expected RED covers unknown acceptance and stale fence.
- [ ] Implement exact-route poll/download/cancel, qualified lookup and immutable
  operator resolution. Provider observation may commit while a dead worker lease
  exists; old worker tokens cannot write.
- [ ] Run worker/orphan/checkpoint/cancel regressions; expected GREEN has one
  remote submit, candidate and usage finality.
- [ ] Commit `feat(host): recover attempts across real process restart`.

### Task C4: Produce M7-C acceptance evidence

**Files:** `docs/r2/evidence/R2_M7_C_RESTART_STREAM_RECOVERY.json`.

- [ ] Run H5 subprocess matrix, durable SSE/backend/frontend gates, scope verifier
  and static/test-audit gates at a clean candidate head.
- [ ] Record PIDs/barriers, attempt versions/lease tokens, event ranges, submit
  counts, exact SHA and evidence hashes.
- [ ] Commit accepted evidence as `docs(r2): record M7-C recovery acceptance` or
  record `REJECTED`; stop for Codex review.
