# R2 V1 H6/H7 closure — handoff

Branch `feat/r2-m7e-v1-lineage`. Decisions: ADR-0090 (offline fence, credential
exclusion, OTLP via env, durable correlation columns). Research:
`docs/research/2026-09-27-r2-v1-h7-correlation-chain-mapping.md`.
Test policy: targeted tests plus static gates. The full backend suite runs only
on request.

Live Git state is authoritative. Read `git log` and `git status` on resume.

## H7 work packets

- [x] Job-ID log leak in persistence/retry (`f19fc77a`)
- [x] Provider-boundary baggage clearing and legacy job-ID leaks (`5c85ddb7`)
- [x] H7-1 Alembic: `tasks.request_id`, `api_calls.task_id` (nullable)
- [x] H7-2 request_id minting (HTTP middleware + agent entry) → enqueue → task row
- [x] H7-3 `api_calls.task_id` from ledger start; version metadata `task_id`
- [x] H7-4 production tracer from env (OTLP/HTTP), wired at app/worker startup
- [x] H7-5 spans at enqueue / execution / provider-job / version / usage seams
- [x] H7-6 end-to-end secret-canary + chain-closure test

## H6 work packets (offline fence, ADR-0090)

- [x] H6-1 fence probe: no other DB sessions; no queued/running/cancelling tasks; before and after
- [x] H6-2 deployment-wide capture: every data root file tree (projects, global assets), not only candidate_objects
- [x] H6-3 credential exclusion: exclude pure-credential table data; sanitized copy for mixed tables; exclude credential files
- [x] H6-4 restore + closure verify: DB-driven reference closure, digests, media playability probe
- [x] H6-5 persisted VERIFIED/REJECTED transition + measured RPO/RTO
- [x] H6-6 operator CLI scripts + runbook rewrite
- [x] H6-7 disposable clean-target drill evidence

## Progress log

- `f19fc77a`, `5c85ddb7`: H7 job-ID log leaks and provider-boundary baggage.
- `9fce33a5`: ADR-0090 and chain-mapping research.
- `66d0cf5a`: H7-1..3 correlation columns (Alembic `a7c3e9d1f200`), request binding, usage/version task attribution.
- `08102ffd`: H7-4 OTLP/HTTP tracer from the environment.
- `0e37b517`: H7-5/6 correlation spans, message-free failure logs, end-to-end canary test.
- `5b99f85d`: H7 residuals (propagator, lib boundaries, log redaction).
- `4c68f449`: H6-1..6 deployment backup, CLI and runbook; the project-scoped helper was removed.
- H6-7 drill evidence: `docs/r2/evidence/R2_V1_H6_OFFLINE_BACKUP_DRILL_2026-09-27.json` (VERIFIED on `4c68f449`, disposable postgres:18 container).

## Verification (targeted, per the sponsor's test policy)

These are the targeted runs recorded at each commit. The full backend suite was
not run.

- H7: unit, `integration/lib`, `integration/server/services` and
  `integration/server/agent_runtime` suites: `12760 passed` before `0e37b517`.
  The only failure was the dirty-tree M7 scope check, which passed after commit.
- H6: PostgreSQL backup integration `6 passed`; `tests/unit/r2`,
  `tests/integration/r2/host_hardening` and `tests/unit/scripts` suites:
  `1595 passed`; M7 scope `18 passed` after commit.
- Static gates at each commit: ruff, basedpyright (0/0), lint-imports (20 kept),
  deptry and audit_tests.

## Still open (not claimed)

- Independent exact-HEAD M7-D review of H6/H7. `RECOVERY_VERIFIED` is not
  claimed by this handoff.
- E2: no-provider Golden A/B review/export and browser checks on a restored
  target.
- H7 residuals closed in `5b99f85d`:
  - The propagator is trace-context only. Baggage is cleared at every lib
    provider boundary: text, media, trial run and discovery.
  - `RedactingFormatter` masks credentials, signed URL parameters and URL
    userinfo in all console and file log output, tracebacks included.
  - Verification: unit, `integration/lib`, `integration/server/services` and
    `integration/server/agent_runtime` suites: `12755 passed`. The only
    failure was the dirty-tree scope check, which passed after commit.
  - Static gates are clean.
- Pending sponsor confirmation: application logs still carry non-credential
  content by design. This covers prompt excerpts (at most 120 characters in
  request-body logs), local file paths and truncated raw model output in
  structured-output fallback warnings. Exported spans carry none of these; the
  allowlist is enforced. Removing content from logs would reduce provider
  debugging ability, so it is left as a sponsor decision.
- The Agent runtime's own Anthropic calls run in the Claude SDK subprocess.
  Process-level OpenTelemetry context, including baggage, is not propagated
  into that subprocess.
- The production Compose image tag `postgres:18-alpine` is not digest-pinned.
