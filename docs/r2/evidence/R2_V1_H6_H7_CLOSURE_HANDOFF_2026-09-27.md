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

## Independent review and fixes — 2026-09-27

The independent review of `1f287029` returned CHANGES_REQUIRED
(`R2_V1_H6_H7_INDEPENDENT_REVIEW_2026-09-27.md`). Fixes:

- `12324323`: log-content policy (ADR-0052 precedent), linear redaction (I3),
  and HMAC job references in backend logs with a static guard test (I5).
- `ae6b568d`: `api_calls.request_id` (Alembic `b8d4f0e2a300`, I6), a digest
  in `candidate_id` and opaque `X-Request-ID` values only (M2), and no
  OpenTelemetry private globals in production (M4).
- `237be5b0`: verify no longer changes set state (I1); Artifact Manifest,
  `current_version` and release checks plus Golden attestation (I4);
  passwords off argv (I2); sequence fence and mid-capture tests (M1);
  `.credentials.json` exclusion and a tighter setting-key pattern (M3);
  configuration stored in the manifest (M6).
- `075d84f2`: a structured CLI error for malformed Golden evidence.

Drill evidence was regenerated on `075d84f2`:

- verify `checks_passed`, 0 canaries;
- attest refused without passing Golden evidence;
- the set stays `COMPLETE`.

Verification on the fix commits:

- The unit, `integration/lib`, `integration/server/services` and
  `integration/server/agent_runtime` suites passed (12818 at `ae6b568d`).
- H6 PostgreSQL integration: `13 passed`.
- `tests/unit/r2`, `tests/integration/r2/host_hardening` and
  `tests/unit/scripts`: `1595 passed`.
- Static gates are clean.
- The only failure each time was the dirty-tree M7 scope check, which passes
  after commit. The full suite was not run.

Not changed, with reasons:

- **M5.** Migration tests stay SQLite per CONTRIBUTING. PostgreSQL
  upgrade/downgrade is covered by the CI command, and the reviewer ran it
  manually.
- **M6.** `BackupSetRepository`/`backup_sets` stay (unused outside tests). A
  schema removal needs its own migration decision.

Still open:

- **Golden A/B on a restored target.** The no-provider read/review/export on
  a restored target is not run, so no set is `VERIFIED` yet. This is the
  remaining V1-05 acceptance step and overlaps E2.
- **Fresh review.** A new independent review is needed on the fix HEAD.

## Re-review and fixes — 2026-09-27

The re-review of `8fdcfa13` returned CHANGES_REQUIRED
(`R2_V1_H6_H7_INDEPENDENT_REREVIEW_2026-09-27.md`). Fixes:

- `85a5e14f`:
  - N1: whole-identifier key matching restores masking of `--password=`,
    `_token=`, `self._api_key=`, `{"_secret": …}` and `2fa_token=`, and stays
    linear.
  - N2: provider job IDs learnt by a task are replaced by HMAC references
    in every rendered log line.
  - Log minors: redaction before truncation; declarative prompt keys; keyed
    candidate digest; PEM bound.
- `0f87a946`:
  - Attestation binds the target and requires distinct set projects; a
    VERIFIED state needs its attestation.
  - Verify gaps are closed.
  - A connection failure marks the set REJECTED, and the CLI reports errors
    as JSON.
  - `?password=` is handled; URL userinfo is stripped.

Accepted with reason:

- **Minor 9:** `reset_tracer_provider_for_tests` stays in `server/telemetry.py`.
  CONTRIBUTING prescribes public `reset_*_for_tests` hooks in production
  modules.

Drill evidence was regenerated on `0f87a946`:

- verify `checks_passed` with 6 references and 2 probed media;
- attest refused for insufficient Golden products;
- the set stays `COMPLETE`;
- 0 canaries.

Verification:

- The unit, `integration/lib`, `integration/server/services`,
  `integration/server/agent_runtime` and `integration/r2/host_hardening`
  suites: `12838 passed`. The only failure was the dirty-tree scope check.
- H6 PostgreSQL: `16 passed`.
- Static gates are clean.
- The full suite was not run.

Still open:

- **Golden A/B on a restored target (V1-05/E2).** The no-provider run on a
  restored target is not done, so no set is VERIFIED.
- **Final review.** A final independent review is needed on this HEAD.

## Final review and fixes — 2026-09-27

The final review of `d382f5fe` returned CHANGES_REQUIRED on F1 only
(`R2_V1_H6_H7_FINAL_REVIEW_2026-09-27.md`). H6 was judged acceptable pending
Golden A/B. Fixes:

- `869f1351`:
  - F1: bounded one-line separator whitespace; linear PEM pairing; masking
    of unterminated quoted credentials. Timing is linear across the sweep.
    Correction from the confirmation review: URL-dense text costs about
    86 ms at 20k characters (`httpx.URL` parsing), not under 30 ms.
  - F3: job IDs are bound outside queued tasks too.
- `e2463c61`:
  - F4: global, whitespace-safe userinfo stripping, including
    `system_setting`.
  - F5: per-target verdict files, attested-file cross-checks, and no
    re-verification of an attested target.
  - F6: query parameters are kept verbatim.
  - F7: redacted CLI errors.
  - F8: `.env` examples document the telemetry HMAC key, OTLP and the
    content opt-in.

Accepted without change:

- **F2 edges.** Only IDs bound in child tasks, and IDs of 6 characters or
  fewer, remain; no backend path spawns child tasks.

Drill evidence was regenerated on `e2463c61`:

- verify `checks_passed`;
- attest refused without passing Golden evidence;
- the set stays `COMPLETE`;
- 0 canaries.

Verification:

- The unit, `integration/lib`, `integration/server/services`,
  `integration/server/agent_runtime` and `integration/r2/host_hardening`
  suites: `12849 passed`. The only failure was the dirty-tree scope check.
- H6 PostgreSQL: `17 passed`.
- Static gates are clean.
- The full suite was not run.

Still open:

1. The Golden A/B no-provider read/review/export on a restored target, with
   attestation and measured RPO/RTO (V1-05/E2).
2. The full affected gates on the exact candidate HEAD, as V1-05 requires.
3. A confirmation review of these fixes.

## Confirmation review — 2026-09-27

The confirmation review of `8a8ea340` returned **APPROVED_WITH_FOLLOWUPS**
(`R2_V1_H6_H7_CONFIRMATION_REVIEW_2026-09-27.md`). H6/H7 are acceptable
pending only two steps:

- the Golden A/B restored-target run;
- the full affected gates on the exact candidate HEAD.

The follow-ups were applied in `7f145dd3`:

- N1: possessive, line-spanning key/value separators restore masking for
  YAML, next-line and multi-line values, and stay linear.
- N2: CLI help.
- N3: `?`/`#` end the userinfo match.
- N4: no re-attestation of a VERIFIED set.
- N5: case-insensitive target guard.
- N6: invalid JSON raises `BackupIntegrityError`.

Remaining accepted limit:

- An `Authorization:` header continued on a new line stays unmasked on its
  continuation line.

Drill evidence was regenerated on `7f145dd3`:

- verify `checks_passed`;
- attest refused without Golden evidence;
- the set stays `COMPLETE`;
- 0 canaries.

Verification:

- The unit, `integration/lib`, `integration/server/services`,
  `integration/server/agent_runtime` and `integration/r2/host_hardening`
  suites: `12856 passed`. The only failure was the dirty-tree scope check.
- H6 PostgreSQL plus CLI: `23 passed`.
- Static gates are clean.
- The full suite was not run.

Open for H6/H7 acceptance (V1-05):

1. **Golden A/B on a restored target.** Run the no-provider
   read/review/export for the two Golden products on a restored target,
   then `attest` with measured RPO/RTO.
2. **Full affected gates** on that exact candidate HEAD.

## Second confirmation review and fixes — 2026-09-27

The second confirmation review of `901b20a0` returned
**APPROVED_WITH_FOLLOWUPS** (`R2_V1_H6_H7_CONFIRMATION_REVIEW_2_2026-09-27.md`).
Its follow-ups were fixed in `c26c0fb5`:

- **Token counts.** Numeric token counts and JSON structure are no longer
  masked; numeric values under credential keys still are.
- **Header next lines.** `Authorization`/`cookie` values on the next line
  are masked.
- **Unterminated quotes.** An unterminated quoted credential masks only the
  rest of its line.
- **Corrupt verdict.** `attest` rejects a corrupt verdict with
  `AttestationRejected`.

The timing sweep stayed linear: 22 ms at 20k characters, 216 ms at 200k.

A drill re-run while fixing these was rejected by the fence ("the database
was written while capturing"). The cause was verified: autovacuum/ANALYZE
catalog writes move the `pg_stat_database` counters; a manual ANALYZE +
VACUUM moved them by 579. Fixed in `c9776606`:

- The fence now uses `pg_stat_user_tables` row counters.
- It adds a relation fingerprint (relfilenode plus column definitions), so
  TRUNCATE, rewrites and DDL are still rejected.
- Tests cover TRUNCATE and ALTER (rejected) and ANALYZE + VACUUM
  (accepted).

Drill on `c9776606`, run 3 times: all `COMPLETE` with verify
`checks_passed` and 0 canaries. The committed evidence is the third run.

Verification:

- The unit, `integration/lib`, `integration/server/services`,
  `integration/server/agent_runtime` and `integration/r2/host_hardening`
  suites: `12865 passed`. The only failure was the dirty-tree scope check.
- H6 PostgreSQL: `21 passed`.
- Static gates are clean.
- The full suite was not run.

Still open (V1-05):

1. **Golden A/B.** The no-provider Golden A/B read/review/export on a
   restored target, plus `attest`.
2. **Full gates.** The full affected gates on the exact candidate HEAD.
3. **Fence fix not independently reviewed.** The `c9776606` fence change
   has not been independently reviewed.

## Third confirmation review and fixes — 2026-09-27

The third confirmation review of `a0fe0291` (`R2_V1_H6_H7_CONFIRMATION_REVIEW_3_2026-09-27.md`)
approved the `c9776606` fence and blocked H7 on R1. Fixes in `7eadb05f`:

- **R1.** Unquoted credentials keep inner brackets.
- **R2.** The token-count exemption applies only to unquoted numbers under
  plural `*_tokens` keys.
- **camelCase `secretKey`.** Now masked.
- **M1.** The runbook lists fence coverage and its limits.
- **M2.** The manifest schema is at v2; other versions are
  `BackupSetNotRestorable`.
- **M3.** Undecodable files are handled.

Verification:

- The unit, `integration/lib`, `integration/server/services`,
  `integration/server/agent_runtime` and `integration/r2/host_hardening`
  suites: `12872 passed`. The only failure was the dirty-tree scope check.
- H6 PostgreSQL, CLI and redaction tests: `109 passed`.
- The timing sweep stays linear (200k characters: 223 ms).
- Drill on `7eadb05f`: verify `checks_passed`, attest refused without Golden
  evidence, `COMPLETE`, 0 canaries.

Still open (V1-05):

1. **Golden A/B.** The no-provider read/review/export on a restored target,
   plus `attest`.
2. **Full gates.** The full affected gates on the exact candidate HEAD.
3. **Confirmation review.** `7eadb05f` needs a confirmation review.

## Fourth confirmation review and fixes — 2026-09-27

The fourth confirmation review of `ea16418b` (`R2_V1_H6_H7_CONFIRMATION_REVIEW_4_2026-09-27.md`)
found H6 acceptable and blocked H7 on N1. Fixes in `06fa5a2d`:

- **N1.** Unquoted values may start with closing brackets.
- **N2.** `secret_key`/`secretKey` are sensitive on the structured and text
  paths.
- **N3.** An unreadable `state.json` raises `BackupIntegrityError`.

Self-run differential against the accepted bar `901b20a0` (harness in the
session scratchpad):

- 4704 grid cases × 2 functions: 0 regressions; leaks at HEAD 0 (base 1064).
- 20k random-password fuzz: 0 regressions.
- Common non-secret text is equal or less masked.
- The timing sweep stays linear (200k characters: 217 ms).

Verification:

- The unit, `integration/lib`, `integration/server/services`,
  `integration/server/agent_runtime` and `integration/r2/host_hardening`
  suites: `12878 passed`. The only failure was the dirty-tree scope check.
- H6 PostgreSQL, CLI and redaction tests: `116 passed`.
- Static gates are clean.
- Drill on `06fa5a2d`: verify `checks_passed`, attest refused without
  Golden evidence, `COMPLETE`, 0 canaries.

Next: the restore-derived Golden A/B drill
(`docs/research/2026-09-27-r2-v1-restore-derived-golden-drill.md`), then the
full gates on the candidate HEAD, then the independent M7-D acceptance
review.

## Restore-derived Golden A/B drill — 2026-09-27

Evidence: `R2_V1_GOLDEN_RESTORE_DRILL_2026-09-27.json` (HEAD `b088f238`,
drill `tests/drills/r2/golden_restore_drill.py`, research
`docs/research/2026-09-27-r2-v1-restore-derived-golden-drill.md`).

The run used a disposable PostgreSQL 18 server. No provider credentials were
configured, and the fixture pipelines make no provider calls. The drill does
not observe this: it does not check provider env vars or new `api_calls` rows
(M7-D review F4).

1. **Materialize.** The drill created three real Host projects through the
   HTTP API with a real JWT: `golden-a-h264`, `golden-b-western` and
   `golden-b-shuangwen`. They were rendered with the no-provider fixture
   pipelines and Remotion (967 s), and went through Gates A, B (Golden B),
   C (per shot) and D.
2. **Backup.** An offline backup was taken, then the source database and
   data root were destroyed.
3. **Restore and verify.** The set was restored to a clean target. `verify`
   passed: 156 files, 33 references, 15 media probed.
4. **Check.** On the restored target, each project and its gate history
   were read through the API, and the approved masters and Gate C receipts
   were resolved. The stored deliverable passes an ffprobe stream probe;
   this is not a full frame decode (review F3). The final cut
   re-composed from the restored masters hashes to the Gate D
   `deliverable_digest` for all three products. "Reviewed" means this
   automated consistency check; no human reviewed anything, and the gate
   receipts were made by the drill's own operator JWT (review F5).
5. **Attest.** `attest` succeeded and the set is **VERIFIED**, with drill
   timings of RPO 0 s and RTO 8 s on a single machine (review F2):
   - **RPO is 0 by construction.** The incident was placed right after a
     fenced capture, and the value is floored. Operational RPO equals the
     backup interval, and V1 sets no schedule or target.
   - **RTO is rounded up.** It spans restore, verify, the Golden check and
     the re-export only. It excludes app start (the check uses in-process
     ASGI without lifespan), backup retrieval, provisioning and credential
     re-entry.
6. **Correlation is not shown here** (review F11). The Golden products come
   from the fixture producer and Gate C, not the generation queue. So there
   are no tasks, `api_calls` or provider jobs to join. H7 correlation
   evidence is the integration chain test
   (`tests/integration/lib/test_generation_correlation_chain.py`), which
   covers the image lane on SQLite. The video `execution_id` lane is not in
   its end-to-end assertion.

Remaining for V1-05:

1. **Full gates.** The full affected gates on the exact candidate HEAD:
   - the backend full suite;
   - frontend and website `pnpm check`;
   - the migration round trip.
2. **Independent review.** An independent M7-D acceptance review on that
   HEAD.
3. **Out of scope here.** Browser/operator workflow checks stay in V1-07
   (E2).

## Full affected gates — 2026-09-27

Evidence: `R2_V1_FULL_GATE_2026-09-27.md`.

- **Gate HEAD:** `78479432`.
- **Candidate:** `9fd43948`. It fixes one test: the H6 argv check was false
  when the username equals the password.
- **Results:**
  - static gates, frontend, website and migrations all pass;
  - the backend's one timeout passed on an isolated rerun (806 s);
  - the H6 PG16 failures were client-version skew; the file passes 23 of 23
    with PG16 client tools.

Open before push: the CI job budget (25 min) against the real-media M3/M6
test durations (about 90 min for the M6 file). This is a CI policy decision
and needs research first.

Next:

1. Run the independent M7-D acceptance review on `9fd43948` or its
   evidence-only successor.
2. Research and decide the CI real-media budget before any push.

## Independent M7-D acceptance review — 2026-09-27

Evidence: `R2_V1_M7D_ACCEPTANCE_REVIEW_2026-09-27.md` (HEAD `836200bf`).

- **Verdict:** **ACCEPTED_WITH_CONDITIONS**, with no blocker or major
  finding.
- **Condition 1 (F2–F5, F11): wording.** Fix the evidence wording. Done
  above and in `R2_V1_FULL_GATE_2026-09-27.md`.
- **Condition 2 (F12): "export".** Record the V1 meaning of "export". This
  is pending a sponsor decision; it is not recorded yet.
- **Other minor findings, left open:**
  - F1: attest does not bind `export_digest` to captured file digests;
  - F6: no committed H6 drill script;
  - F7: log lines carry no request or task ID;
  - F8: credential shapes missed by the redactor;
  - F9: operator configuration is stored verbatim;
  - F13: the runbook ordering and restored-app startup.
- **Before push:** the CI budget, plus F10 (the CI `postgresql-client`
  version).
