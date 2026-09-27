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
- [ ] H7-4 production tracer from env (OTLP/HTTP), wired at app/worker startup
- [ ] H7-5 spans at enqueue / execution / provider-job / version / usage seams
- [ ] H7-6 end-to-end secret-canary + chain-closure test

## H6 work packets (offline fence, ADR-0090)

- [ ] H6-1 fence probe: no other DB sessions; no queued/running/cancelling tasks; before and after
- [ ] H6-2 deployment-wide capture: every data root file tree (projects, global assets), not only candidate_objects
- [ ] H6-3 credential exclusion: exclude pure-credential table data; sanitized copy for mixed tables; exclude credential files
- [ ] H6-4 restore + closure verify: DB-driven reference closure, digests, media playability probe
- [ ] H6-5 persisted VERIFIED/REJECTED transition + measured RPO/RTO
- [ ] H6-6 operator CLI scripts + runbook rewrite
- [ ] H6-7 disposable clean-target drill evidence

## Progress log
