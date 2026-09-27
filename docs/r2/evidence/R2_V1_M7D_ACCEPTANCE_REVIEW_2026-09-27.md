# R2 V1-05 — M7-D acceptance review (H6/H7), 2026-09-27

- **HEAD reviewed:** `836200bf817b6a12ade74b231816d8b9e4e0b310`, on branch
  `feat/r2-m7e-v1-lineage` in worktree `.worktrees/r2-m7e-v1-lineage`.
- **Tree:** tracked files were clean. One untracked file was present:
  `docs/research/2026-09-27-r2-v1-ci-real-media-test-budget.md`. It is out of
  scope and changes no code.
- **Reviewer:** an independent, read-only acceptance reviewer (a background
  agent). Nothing was edited, committed or pushed, and no subagents were
  used.
- **Date:** 2026-09-27.

## Verdict: **ACCEPTED_WITH_CONDITIONS**

The H6/H7 code at HEAD has no blocker and no major defect.

- **H6.** Credential exclusion, the offline fence, restore/verify path safety
  and attest integrity match ADR-0090 and its follow-up decisions.
- **H7.** Correlation from request to task to usage/version matches, and so
  do the span allowlist and the baggage handling. Log redaction is linear.
- **Prior findings.** The critical and important M7-D findings in
  `R2_M7_E1_INTEGRATION_STOP_2026-09-25.json` are resolved in code. This was
  checked in source, not taken from the handoff.

**Conditions before recording V1-05 as accepted:**

1. Correct the evidence overclaims and missing limits (F2–F5, F11). This is
   documentation only.
2. Record the V1 meaning of "export" (F12) as an accepted interpretation, not
   only as a research inference.

**Open before push, not a V1-05 acceptance blocker:** the CI job budget, plus
a check of the CI `postgresql-client` version (F10).

## Per-acceptance-item assessment

| V1-05 acceptance item | Status | Assessment |
|---|---|---|
| Correlation evidence | **Met at integration-test level.** | See below. |
| Canary evidence | **Met.** | See below. |
| Clean-target no-provider Golden review/export | **Met, with disclosure fixes.** | See below. |
| Measured RPO/RTO | **Met as drill timings, with a scope caveat.** | See below. |
| Full affected gates | **Sufficient for acceptance, not for push.** | See below. |
| Independent M7-D acceptance | **This review.** | See below. |

**Correlation evidence**

- `tests/integration/lib/test_generation_correlation_chain.py` drives the
  real `GenerationQueue`, `GenerationWorker`, `Ledger`, `VersionManager` and
  `persist_provider_job_id` with a stub executor.
- It asserts the durable joins: `tasks.request_id`, `api_calls.task_id` and
  `api_calls.request_id`, and the version `task_id`. It also asserts the span
  joins in one trace.
- The entry points are the HTTP middleware (`server/app.py:572`) and the
  per-tool Agent wrapper (`server/agent_runtime/sdk_tools/__init__.py:187`).
- Limits (F11): there is no Golden-corpus or restored-target join, the chain
  test does not cover the video `execution_id` lane, and the file was run on
  SQLite only.

**Canary evidence**

- **(a) H7 chain test.** It puts canaries through spans, public events and
  rendered logs, on both success and failure. The canaries are a prompt, a
  job ID, a credential, a signed URL, a header, a body and a path. The test
  was run and passed.
- **(b) H6 PG integration tests.** They put `SECRET_CANARY` into the
  credential tables, `.system_config.json`, `logs/` and `.credentials.json`.
  They assert it is absent from the backup set and the restored target.
  These tests are PG-only and were skipped in this run.
- **(c) Committed drill JSON on `06fa5a2d`.** It records 0 canary hits. The
  product code is identical to HEAD; only tests and docs changed after it.
  The drill script is not committed (F6).

**Clean-target no-provider Golden review/export**

- **Run.** `R2_V1_GOLDEN_RESTORE_DRILL_2026-09-27.json` ran on `b088f238`.
  Code is unchanged to HEAD except for one H6 test file.
- **Steps.**
  1. The drill materialized three real Host projects through the HTTP gate
     routes A/B/C/D.
  2. It took an offline backup, then destroyed the source database and data
     root.
  3. It restored the set into an empty database and root.
  4. Verify passed: 156 files, 33 references, 15 media.
- **Result.** The re-composed final cut hashes to the Gate D
  `deliverable_digest` for all three products. Attest succeeded (VERIFIED).
- **"Export".** The term is justifiable. P1 (`R2_P1_GATE_SURFACE.json`)
  records that no distinct export mechanism exists, and the drill goes beyond
  that bar by re-composing from the restored masters. The definition is still
  a research inference, not a recorded decision (F12).
- **Wording limits.** "Review" is automated, "decodes" means an ffprobe
  stream probe, and "no provider" is asserted, not observed (F3–F5).

**Measured RPO/RTO**

- RPO 0 s and RTO 8 s agree with the timestamps: recovery point 13:25:10.93,
  `verified_at` 13:25:19.39.
- RPO is about 0 by construction: the incident is placed right after a fenced
  capture, and the value is floored.
- RTO excludes app start, credential re-entry, retrieval and provisioning.
- No RPO/RTO targets exist to judge against. The evidence should say so (F2).

**Full affected gates**

- **What ran.** On `78479432`: static checks, frontend, website, the
  migration round trip, the full backend suite (SQLite) and the PG16
  dialect suite. Only one H6 test file and docs differ from HEAD.
- **Failures.** All are accounted for:
  - one timeout under CPU contention passed on an isolated rerun (806 s);
  - ten PG16 failures came from `pg_restore` 18 against a PG16 server, and
    passed 23/23 with PG16 client tools;
  - one test defect was fixed in `9fd43948`.
- **Rerun.** The reviewer re-ran the static gates on HEAD; they pass.
- **What is left.** The CI runtime limit (25-minute jobs against about 90
  minutes of real-media tests) blocks push only. The CI PG-client version
  risk (F10) has the same scope.

**Independent M7-D acceptance**

- The draft recovery-closure design §7 asks for "two fresh independent
  reviews" on the same HEAD. The backlog asks for one independent M7-D
  acceptance.
- This is one review, on `836200bf`. The six earlier reviews were on earlier
  HEADs.

**V1-04 and V1-07 are not overclaimed.**

- The evidence and the runbook state that there is no encrypted custody or
  signing, and that attestation trusts the operator.
- They state that the browser and operator checks remain in V1-07.
- Neither `RECOVERY_VERIFIED` nor `PRODUCTION_CANDIDATE` is claimed anywhere.

## Findings

**F1 (minor). Attest accepts self-declared Golden evidence and any non-negative RPO/RTO. CONFIRMED.**

- **Where:** `r2/host_hardening/deployment_backup.py:1009-1075`;
  `r2/contracts/host_hardening.py:467-468, 493-494`.
- **Defect:** `export_digest` is a `NonEmptyStr` and is never compared with
  any captured file digest. The measured seconds are taken as given.
- **Scenario:** a hand-written `golden-evidence.json` that names two captured
  projects with `passed: true` moves a set to VERIFIED.
- **Why minor:** this is documented ("Attestation trusts the operator" in the
  runbook's limits) and consistent with ADR-0090 dropping signing.
- **Cheap hardening:** require each `export_digest` to equal the manifest
  digest of a captured file under that project.

**F2 (minor, evidence wording). RPO 0 is by construction, and the rounding is asymmetric. CONFIRMED.**

- **Where:** `tests/drills/r2/golden_restore_drill.py`, `orchestrate`. RPO is
  `max(0, int(incident_at - recovery_point))` (floored); RTO is `int(...) + 1`.
- **Why:** the incident is recorded right after `create` returns on a stopped
  app, so RPO is just the capture time, floored.
- **Fix:** the evidence should state the following.
  - Operational RPO equals the backup interval, and V1 has no schedule or
    target.
  - RTO excludes app start, credential re-entry and backup retrieval.
- **Current wording:** the handoff says "Measured RPO 0 s and RTO 8 s on a
  single machine". The coverage limits say only "single-machine drill
  timings".

**F3 (minor, overclaim). "Decodes" is an ffprobe stream-header probe. CONFIRMED.**

- **Where:** `deployment_backup.py:763-786` (`ffprobe_media`) and the drill's
  `_decodes`. Both run `ffprobe -show_entries stream=codec_type` and check
  that streams exist.
- **Gap:** no frames are decoded, but the handoff says "The stored
  deliverable decodes". Design §7 asks for a full-stream decode; that design
  is a draft.
- **Fix:** reword the evidence as "probed".

**F4 (minor). "No provider" is asserted, not observed. CONFIRMED by reading.**

- **Where:** `_phase_env` copies the operator's whole `os.environ`, minus
  `OTEL_*` and `ARCREEL_TELEMETRY*`, into the materialize and check phases.
  In the evidence, `environment.provider_credentials` is a hard-coded string.
- **Gap:** the drill does not check for provider env variables, or for new
  `api_calls` rows on the target. The research procedure listed "no provider
  call occurs" as a check.
- **Impact:** low. The fixture pipelines make no provider calls, and the
  sanitized tables are restored blank.

**F5 (minor, overclaim). Golden "review" is an automated consistency check. CONFIRMED.**

- **Where:** `check()` sets `reviewed=not problems`.
- **Gap:** no human reviewed anything. The gate receipts were created by the
  drill's own JWT (`golden-drill-operator`). The coverage limits do not say
  so.

**F6 (minor, reproducibility). The H6 offline drill has no committed script. CONFIRMED.**

- **Where:** `R2_V1_H6_OFFLINE_BACKUP_DRILL_2026-09-27.json` holds the
  `secret_canary` counters and the negative fence check. No script in the
  repo produces them (a grep for its keys finds nothing).
- **Also:** the review-4 differential harness is "in the session scratchpad"
  (handoff line ~368).
- **Mitigation:** the PG integration tests cover the same canary assertions
  reproducibly.

**F7 (minor, diagnosability). Log lines carry no `request_id` or `task_id`. CONFIRMED.**

- **Where:** `lib/logging_config.py:117` sets
  `_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"`.
- **Why:** in `server/app.py:572-613`, `request_logging_middleware` is
  registered after `request_id_middleware`. With Starlette ordering it is
  the outer middleware, so it logs outside the request binding.
- **Scenario:** a user reports the echoed `X-Request-ID`. It joins to
  `tasks`, `api_calls` and spans, but to no log line, including the 500 or
  unhandled access log.
- **Why minor:** spec §9 says IDs *may* appear in logs, so this is not a
  breach. It weakens the "diagnosable" purpose when OTLP is off, which is
  the default.

**F8 (minor). The redaction heuristic misses several credential shapes. CONFIRMED by probing `redact_provider_text`.**

- **Leaked verbatim:**
  - `credential=X`, `credentials: X`, `passphrase=X`, `jwt=X`;
  - `--api-key X`, `--password X`, `PGPASSWORD=X`;
  - `ApiKey X`, `<apiKey>X</apiKey>`, `password%3DX`;
  - `The API key X is invalid`;
  - `hmac_key=X`, `ARCREEL_TELEMETRY_HMAC_KEY=X`.
- **Inconsistency:** the backup's `system_setting` pattern treats
  `credential(s)` as secret; the log redactor does not.
- **Impact:** no current code path is known to log these shapes (PLAUSIBLE).
- **Linear time holds:** 19 adversarial generators scaled about 10× for 10×
  more input (20k to 200k characters), and PEM is linear from 100k to 800k.

**F9 (minor). The manifest stores operator `configuration` verbatim. CONFIRMED.**

- **Where:** `deployment_backup.py:603-604`.
- **Gap:** only the CLI help says "non-secret". There is no screen for
  credential-shaped keys or values. The runbook example path
  (`/srv/arcreel/non-secret-config.json`) relies on operator discipline.
- **Operator risk (PLAUSIBLE):** naming a wider root captures a
  service-account file, for example the parent that holds `vertex_keys/`.
  `EXCLUDED_FILE_NAMES` covers only `.credentials.json`, and verify does not
  scan files for residue. The runbook warns against this.

**F10 (minor for V1-05, push risk). The CI PG-client version is unverified. PLAUSIBLE.**

- **Where:** `.github/workflows/test.yml:195-230`. `postgres-compat` runs on
  `ubuntu-latest` with `postgres:16` and
  `apt-get install postgresql-client`.
- **Gap:** the full-gate evidence concludes that the skew does not affect CI.
  But the local failure was on an Ubuntu 26.04 host whose archive client is
  18.6, and the fix used local PATH shims.
- **Scenario:** if `ubuntu-latest` resolves to 26.04, the ten H6 tests fail
  in CI in exactly the same way.
- **Fix:** check this together with the CI budget decision before push.

**F11 (minor, scope disclosure). The correlation evidence is not a "Golden join".**

- **What the design asks:** host-hardening §11 row H7 asks for a "Golden join
  from request through usage/master".
- **Why the Golden drill has none:** its products come from the fixture
  producer and Gate C, not the generation queue. So it has no tasks,
  api_calls or provider jobs. Gate C versions carry no `task_id` or
  `request_id`, because `task_attribution()` covers queued tasks only.
- **Chain test coverage:** it covers the image lane only;
  `execution_id`/`execution.attempt_submitted` are not in the end-to-end
  assertion.
- **Fix:** the chain itself is correct as far as it was read. The evidence
  should state these limits instead of implying a Golden-level join.

**F12 (minor, decision record). The V1 meaning of "export" is still a research inference.**

- **Where:** `docs/research/2026-09-27-r2-v1-restore-derived-golden-drill.md`
  (Inferences).
- **Definition in use:** the re-composed final cut equals the Gate D
  `deliverable_digest`, with no packaging mechanism.
- **Why it matters:** V1-07 also needs "export digests".
- **Fix:** record the definition, for example as a backlog note or an
  ADR-0090 follow-up, so V1-07 does not redefine it.

**F13 (minor, runbook/drill fidelity). The Golden step conflicts with "start only after VERIFIED". CONFIRMED.**

- **Conflict:** the runbook says "Only after `VERIFIED` should you start the
  restored application", but step 4 runs the Golden read/review against the
  restored application.
- **Gap:** the drill uses an in-process `httpx.ASGITransport` without the
  lifespan. So restored-target startup (lifespan, in-process worker, config
  migration) is not exercised.
- **Gap:** there is no operator tool that produces `GoldenRestoreEvidence`
  on a real restore. The drill's `check` needs the drill's own
  `materialized.json`.
- **Scope:** mostly V1-07; the gap should be disclosed.

## Verified resolved at HEAD (source read)

**Integration-stop findings.**

- **Critical:**
  - deployment-wide capture, plus reference, current-version and media
    checks;
  - a production OTLP tracer configured from env, with chain spans;
  - the Golden flow, gates and a persisted VERIFIED transition, with no
    `RECOVERY_VERIFIED` claim.
- **Important:**
  - `_safe_relative` is applied to every manifest path, and payload digests
    are checked before restore;
  - the PREPARING/GC fence is replaced by the offline fence under ADR-0090;
  - credential data is excluded and restored sanitized, with a
    `SECRET_RESIDUE` check;
  - baggage is cleared through `clears_baggage_at_provider_boundary`, with a
    trace-context-only propagator;
  - logs use HMAC job refs.

**Findings from the six 2026-09-27 reviews:**

- I2: passwords reach the tools through `PGPASSWORD`, not argv;
- I1: verify writes only the verdict file;
- M2: the request-ID regex is opaque;
- M4: no private OTel globals are touched outside
  `reset_tracer_provider_for_tests`;
- N4/N5: no re-attest, and the target guard is case-insensitive;
- review-4 N1–N3: leading-bracket values, `secret_key`/`secretKey`, and
  `read_state` raising `BackupIntegrityError`.

## Commands run (at HEAD 836200bf)

| Command | Result |
|---|---|
| `git rev-parse HEAD` | `836200bf` |
| `git diff --stat` for `b088f238..HEAD`, `78479432..HEAD` and `06fa5a2d..HEAD -- . ':!docs'` | Since the drill and gate HEADs, only docs, the drill script and `test_deployment_backup.py` changed. Product code is identical. |
| `uv run python -m pytest -q -p no:cacheprovider` on the chain, logging, request-context, telemetry, backup-CLI, middleware and H6 test files | 158 passed, 22 skipped (the PG-only H6 tests) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 1536 files already formatted |
| `uv run lint-imports` | 20 kept, 0 broken |
| `uv run python scripts/audit_tests.py --check` | 0 violations |
| `uv run basedpyright --warnings` on the 9 H6/H7 files | 0 errors, 0 warnings |
| `uv run alembic heads` | `b8d4f0e2a300 (head)` |
| Adversarial redaction timing (scratchpad script; 19 generators at 20k and 200k characters; PEM up to 800k) | Linear; worst case 216 ms at 200k characters |
| Credential-shape leak probe (about 50 shapes) | The leaks listed in F8 |

## Coverage limits

- **Accepted from evidence, not re-run:** the full backend, PG16 dialect,
  frontend and website suites, the migration round trip, and both drills.
  The HEAD deltas and the evidence's internal consistency (timestamps,
  counts, digests) were checked instead.
- **H6 PG integration tests:** skipped in this run because no database
  container was started. Their canary, fence, argv and attest assertions were
  read, not executed.
- **Fence:** PostgreSQL cumulative-statistics flush semantics were reasoned
  about, not probed.
- **Redaction:** checked with targeted probes, not an exhaustive grammar.
- **Correlation seams:** not every enqueue and generation seam was
  enumerated. Context propagation through `to_thread` was checked and is
  safe. The sync wrappers on `ThreadPoolExecutor` lose context, but they
  have no production callers.
- **CI:** the contents of the `ubuntu-latest` image were not verified.
- **License:** out of scope (sponsor decision).
