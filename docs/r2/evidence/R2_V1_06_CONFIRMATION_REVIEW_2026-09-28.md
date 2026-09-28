# R2 V1-06 — Confirmation review (2026-09-28)

> Saved verbatim from the read-only reviewer's report. How each new finding was closed is recorded at the end.

- **HEAD reviewed:** `7ed103f0` on branch `feat/r2-m7e-v1-lineage`, worktree `.worktrees/r2-m7e-v1-lineage`. The tree was clean before and after the review.
- **Range:** `86a2d692..HEAD`, 8 commits: `d6948976`, `14139f84`, `80e7d047`, `58bdd129`, `78b1111d`, `7a1d5817`, `9ef9e371`, `7ed103f0`.
- **Reviewer mode:** read-only. I made no edits or commits and spawned no subagents. I ran no full suite, no PG-dialect run, no real-media render and no real provider call. Every reproduction ran from the session scratchpad, outside the repo.
- **Date:** 2026-09-28.

## Verdict: CHANGES_REQUIRED (narrow)

- **Fixed or disclosed:** all fifteen earlier findings (F1–F15). I confirmed each one against the code, the tests and scratch reproductions at `7ed103f0`.
- **Blocker:** one new major finding, N1. It breaks the backlog's requirement to "exactly qualify each release route":
  - For a custom provider, a qualification recorded for model A opens model B. This happens when A is disabled or its endpoint is changed.
  - The canary can also record A while it actually exercises B.
  - Reproduced.
- **To reach ACCEPTED:**
  1. Close N1 and add a test for it.
  2. Either bind the custom model's endpoint or disclose N2.
  3. Correct amendment item 1 of ADR-0091. It currently says the binding "makes 'exact provider, endpoint, model and account route' concrete".
- The minor findings N3–N6 can be disclosed or fixed later.

## F1–F15 status

| # | Status | Evidence (at 7ed103f0) |
|---|---|---|
| F1 custom-provider and credential crossover | **FIXED**, but see N1 and N2 on the same axis | `paid_routes.py`: `media_route` names the custom `provider_id`; `route_binding` digest; `is_route_qualified` matches `(route_ref, model_id, binding)`; `assembler.py:38-78`. **Reproduced (scratch):** qualifying `custom-A` does not qualify `custom-B`, even with an identical relay config. A rotated `api_key` or a changed `base_url` gives a new binding and the route becomes unqualified. Built-in key rotation is covered by `test_a_new_api_key_needs_a_new_canary`. CONFIRMED |
| F2 CNY failed-call hold leak | **FIXED** | `budget_guard.py:148-158`: a zero-cost row reconciles in the reservation's currency. **Reproduced (scratch):** 10 failed Ark Seedance calls in a `release:CNY` scope with limit 20 leave `reserved_total=0` and `committed_total=0`; a later success still settles in CNY with reserved 0. The committed tests also cover `resume_failed`. CONFIRMED |
| F3 xAI SDK gRPC auto-retry | **FIXED** | `grok_shared.py:52-64`. I spied on `grpc.aio.secure_channel` through the real xai-sdk 1.18.0 option merge (`client.py:91-93`: user keys replace defaults). Effective options: `grpc.enable_retries=0` and `service_config` `{"methodConfig":[{"name":[{}]}]}`, with no `retryPolicy` and no duplicate keys. All three Grok backends use `create_grok_client`. CONFIRMED |
| F4 cached backend not re-gated | **FIXED** | `generation_context.py:103-107`: in release mode the gate runs again on every fetch, before the cache lookup. DEV computes no binding and makes no DB read. `test_generation_context` passes. Text backends go through `assemble_backend` on every call. CONFIRMED |
| F5 header override and unenforced skips | **FIXED** | `compatibility.py:173-214`. **Probes:** a later `# exit_code: 0` line cannot override the header's `exit_code: 1`; a header that is not first yields `exit_code=None`; CRLF parses correctly. `allowed_skips` is enforced, and an undeclared skip fails ("golden_b log skips 40 tests; the run allows 0"). `deselected` and `xfailed` are not counted as skips (N6). CONFIRMED |
| F6 Agent qualifiable without a budget | **FIXED** | `UNQUALIFIABLE_ROUTE_KINDS={"agent","trial_run"}`. `record_qualification` raises for these kinds, and `is_route_qualified` returns False. The `--agent` canary is removed. `options_assembler.py:105` still gates the session start. **Product consequence (disclosed):** the Agent cannot run in `PRODUCTION_CANDIDATE` until a per-session reservation exists. CONFIRMED |
| F7 ADR notes changed the decision | **FIXED**, with one new overclaim in amendment item 1 (see N1 and N2) | The amendment now names the synchronous adapter-level redefinition, the two-store registry read through one function, and the CLI-only canary as sponsor-delegated amendments. CONFIRMED |
| F8 git tests in the unit tier | **FIXED** for scope | `test_verify_m7_scope` git tests moved to `tests/integration/scripts/r2/test_verify_m7_scope_git.py`. Four other unit-tier files still run git (`test_donor_baseline`, `test_m2_artifact_bridge_architecture_boundaries`, `test_verify_baseline`, `test_canon_delta_compiler`). All four predate `20a030d8`, so they are outside V1-06. CONFIRMED |
| F9 no exact-version route inventory | **FIXED** (see N5) | `R2_V1_06_PAID_ROUTE_INVENTORY_2026-09-28.json`: 38 routes; 24 REFUSED_UNTIL_QUALIFIED, 12 DISABLED_IN_RELEASE (video), 2 REFUSED_IN_RELEASE (agent, trial_run); 12 async video families, all UNQUALIFIED. I regenerated it from `paid_route_inventory()` and `adapter_version_for` at HEAD: 38/38 routes, no extra refs, no version mismatch. CONFIRMED |
| F10 stale evidence | **FIXED** | The backport record now shows 4 UNCHANGED and 12 ADAPTED, matching the inventory's counts (4/12/278 DEFERRED). `3ff6127f` is marked "ADAPTED only in part". The handoff shows the closing gate IN PROGRESS. **Residual:** the backport record's "Verification" section is still historical text ("produced in packet P4"); not misleading. CONFIRMED |
| F11 unguarded Vertex and Vidu fetches | **FIXED**; SDK transports **DISCLOSED** | `gemini.py:398-411`: a Vertex URI goes through the guarded `download_video` (scheme check, destination check, byte cap, retry budget); `urlretrieve` is removed. `vidu_shared.py:220`: `guarded_sync_client`. The new scan covers `httpx.Client(`, `urlretrieve(` and `urlopen(`. `gs://` and `file:` are rejected with `ArtifactDestinationRejectedError` (NonRetryable); before the fix, `urlretrieve` failed on `gs://` too, so there is no regression. The sync and async guards apply the same rules: only link-local and metadata addresses are blocked, while loopback and private addresses are allowed by the upstream policy. A grep of `lib/` finds no other `urllib`, `requests`, `aiohttp` or bare httpx client outside `httpx_shared.py`, which is not a provider path. CONFIRMED |
| F12 store integrity and concurrency | **FIXED**; unkeyed digest **DISCLOSED** | Evidence is written with `atomic_write_bytes`. The records read-modify-write runs under an `O_EXCL` lock. A malformed records file fails closed (tested). See N3 on the stale lock. CONFIRMED |
| F13 unclaimed-hold leak | **FIXED** | `expires_at = now + CLAIM_WINDOW` (10 minutes); `_expire_eligible_locked` expires ACTIVE holds only. **Reproduced (scratch):** a stale ACTIVE 9-CNY hold in a 10-CNY scope is reclaimed by the next ledgered call. A CLAIMED hold older than two hours is not expired, so long-running submits are unaffected, because the claim happens immediately after reserve (`budget_guard.py:103-126`). CONFIRMED |
| F14 hand-bumped adapter versions | **DISCLOSED** (ADR-0091 amendment, "Known limits") | CONFIRMED |
| F15 gateway 5xx resend; 0.01 floor | **DISCLOSED** (amendment item 7 and "Known limits") | CONFIRMED |

## New findings

### Major

**N1. For custom providers, the gated model and the constructed model can differ, so a qualification of one model opens another. The canary can also record a model it never called.** CONFIRMED, reproduced.

- **Where:**
  - `lib/custom_provider/loader.py:57-88`: a requested model that is missing, disabled or of the wrong media type falls back to the provider's default enabled model.
  - `lib/backend_assembly/assembler.py:77-78`: the gate checks the requested `model_id`.
  - `server/services/generation_context.py:103-107` with `352-356`: the image lane passes `resolved.model_id`, and identity convergence exists only for video (`resolver.py:1399`).
  - `scripts/r2/qualify_route.py:94-112`: the canary records `args.model` and never checks `backend.model`.
- **Scenario 1 (gate).** In `PRODUCTION_CANDIDATE`, the operator qualifies `custom-N` / `img-a` and later disables `img-a`. The project still selects `img-a`, so the gate passes on `img-a` while the backend is built for the default `img-b`, which has no canary.
  - My scratch test showed `require_paid_route(img-b)` raising while `assemble_backend(model_id="img-a")` returned `backend.model == "img-b"`.
- **Scenario 2 (canary).** The operator runs the canary for a disabled `img-a`. It exercises `img-b` but records a qualification for `img-a`. Re-enabling `img-a` then makes it qualified without it ever having been called.
  - The ledger also records `model=args.model`, not the model actually billed.
- **Scope:** custom image, text and audio. Video is unaffected because all video routes are unqualifiable.
- **Fix:**
  - In release mode, either refuse the fallback or re-run the gate on `backend.model` after construction.
  - In the canary, fail when `backend.model != args.model`.

### Minor

**N2. The custom-provider binding omits the model's `endpoint` and the user-defined endpoint definition.** CONFIRMED, reproduced.

- **Where:** `assembler.py:47-55` binds only `base_url`, `api_key` and `discovery_format`.
- **Effect:** changing a model's endpoint (for example `openai-images` to `dashscope-image`, a different wire protocol and adapter) or editing a `CustomEndpoint` definition leaves the binding unchanged, and the qualification stays valid. In the scratch reproduction, the binding was identical and `is_route_qualified` stayed True.
- **Why it matters:** ADR-0091 F1 names "endpoint", and amendment item 1 claims to make it concrete.
- **Fix:** bind the model endpoint and the endpoint definition digest, or narrow the ADR wording.

**N3. A stale lock file blocks every later qualification write, after the canary has already spent money.** CONFIRMED, demonstrated.

- **Where:** `route_qualifications.py:116-132`.
- **Trigger:** a writer killed (SIGKILL or power loss) between `os.open(O_EXCL)` and `unlink` leaves `.route_qualifications/.lock`. The critical section is very short, so this is rare.
- **Effect:** every later `record_qualification` waits 30 s and raises `TimeoutError`, with no stale-lock detection. Because the canary's paid call runs before the record, the operator pays and then gets no record.
- **Not affected:** reads do not take the lock.
- **Fix:** clear the lock manually (document the step), or add a PID or age check.

**N4. The built-in binding digests the whole provider config, not only "base URL and credentials".** CONFIRMED by reading.

- **Where:** `assembler.py:56-57` digests `resolver.provider_config(...)`, which includes `image_rpm`, `video_rpm`, `request_gap`, `*_max_workers` and `gcs_bucket` (`registry.py:381,465,541,669`).
- **Effect:** tuning concurrency or rate limits silently invalidates every qualification of that provider. This fails closed, so it is an operability issue.
- **Related:** amendment item 1 describes the binding inaccurately.

**N5. The route-inventory evidence is not pinned to a commit or a test.** CONFIRMED.

- The JSON records no `host_sha`, and no test compares it with `paid_route_inventory()`. It matches HEAD today, but it can drift silently.

**N6. The gate-log parser ignores `deselected` and `xfailed`.** PLAUSIBLE.

- **Where:** `compatibility.py` `_SKIPPED_RE` counts only `N skipped`.
- **Effect:** a gate command that narrows its selection with `-m` or `-k` passes the skip rule. The command string is in the reviewed manifest, so a reviewer could still catch this.
- **Fix:** disclose it, or count deselections.

### Observations (not findings)

- **Environment-variable keys.** `create_openai_client` and `genai.Client` fall back to `OPENAI_API_KEY` / `GOOGLE_API_KEY` when the DB has no key. Such a key is outside the binding. This is an edge case. PLAUSIBLE.
- **Performance.** The re-gate adds, on every backend fetch in release mode, two DB reads plus a synchronous read and digest of the qualification file and its evidence file. This is acceptable at V1 scale.
- **Call sites.** Every `QualificationLookup` / `is_route_qualified` call site uses the new three-argument signature. basedpyright is clean.

## Honesty of the ADR amendment and evidence (task 3)

- **Accurate:**
  - Amendment items 2–8 match the code.
  - "Known limits" discloses F11 (SDK transports), F12 (unkeyed digests, operator-attested logs), F14 and F15.
  - The claim that SDK retries are disabled for OpenAI, Ark and xAI is true for every paid backend client (`max_retries=0`, and the verified xAI options).
  - The handoff's release-state section is accurate: video is disabled, the Agent and trial runs are refused, and a budget scope is required per currency.
- **Overclaims:**
  - Item 1's "exact provider, endpoint, model and account" is not met: see N1 (model) and N2 (endpoint).
  - Item 1's "digest of … base URL and credentials" understates the binding: see N4.
- **Backlog row V1-06:**
  - **Executable provenance, mapping and evidence checks:** MET.
    - `_verify_integration` passes at the recorded `host_sha` `1a5a7c8f` and at HEAD `7ed103f0`.
    - The runner and header checks pass.
    - The route-inventory scans pass.
  - **Correct test tiers:** MET for V1-06 scope. `audit_tests` reports 0 violations.
  - **Exact-version route inventory:** MET, with the N5 caveat.
  - **Disable or exactly qualify each release route:** NOT MET until N1 is fixed.
  - **E1 independently accepted:** the E1 remediation is accepted:
    - S1 integration is re-verified at HEAD.
    - The S3 and T1 log-evidence defects are fixed.
    - The full `COMPATIBLE` verdict stays `PENDING_GATES`: no runner-written 12-gate manifest exists in `docs/r2/evidence/`, and the browser gate belongs to V1-07. The inventory's `full_report_status` says so honestly.

## Commands run (at 7ed103f0)

| Command | Result |
|---|---|
| `git log --oneline 86a2d692..HEAD`; `git diff 86a2d692..HEAD` over lib, r2, scripts, server and tests | inspected |
| `uv run python -m pytest tests/integration/lib/test_budget_guard.py tests/unit/r2/host_hardening tests/integration/r2/host_hardening/test_compatibility_upstream.py tests/integration/r2/host_hardening/test_compatibility_provider.py tests/integration/scripts/r2 tests/integration/server/services/test_generation_context.py tests/unit/lib/test_artifact_download_guard.py tests/unit/lib/test_grok_shared.py tests/unit/lib/video_backends/test_paid_sdk_submit_retry.py tests/unit/lib/video_backends/test_video_backend_gemini.py tests/unit/scripts/r2 tests/integration/lib/db/repositories/test_budget_reservation_repo.py tests/unit/lib/test_budget_reservation.py -q -p no:cacheprovider --timeout 120` | **618 passed** |
| Scratch `test_repro_f1.py`, run with `-p tests.conftest` and in-memory SQLite (it asserts the defect exists) | 4 passed: F1 crossover blocked; F1 key and base-URL rotation blocked; N2 endpoint change keeps the qualification; N1 fallback gate and canary mismatch reproduced |
| Scratch `test_repro_f2.py` | 3 passed: F2 repeated CNY failures leave no residue; F13 stale ACTIVE hold reclaimed; CLAIMED hold not expired |
| `parse_gate_log` probes | the override attempt stays at `exit_code=1`; a non-leading header yields None; CRLF is OK; `deselected` and `xfailed` are not counted |
| Spy on `grpc.aio.secure_channel` through `create_grok_client` (xai-sdk 1.18.0) | `enable_retries=0`, no `retryPolicy`, no duplicate keys |
| `_verify_integration` on the upstream inventory, at the recorded `host_sha` and with `host_sha=HEAD` | both pass |
| Route inventory JSON compared with `paid_route_inventory()` / `adapter_version_for` | 38/38, no mismatch |
| `check_destination_sync` probes | `gs://`, `file:` and IPv4-mapped metadata addresses are rejected; loopback and private addresses are allowed (the policy is the same as the async guard) |
| `_exclusive(timeout=0.3)` with a pre-existing `.lock` | `TimeoutError`; the lock persists |
| `ruff check`, `ruff format --check`, `basedpyright --warnings` on the 24 changed `.py` files | clean; formatted; 0 errors, 0 warnings, 0 notes |
| `lint-imports` | 20 kept, 0 broken |
| `scripts/audit_tests.py --check` | 0 violations |

## Coverage limits

- **Not run:** the full backend, PG-dialect, frontend and website suites; `deptry`; pre-commit; any real provider call; any real-media render. A full suite was already running on the machine.
- **Instructor reask:** `instructor_support.py`, `max_retries=2`, resends paid text calls after a validation failure. I did not check whether this counts as a resend under ADR-0078 or how it is accounted.
- **Not re-audited:** the google-genai retry defaults were covered by the previous review and not checked again.
- **Discovery method:** I used grep and Read rather than the codebase-memory graph, so negative claims ("no other unguarded fetch", "all call sites updated") rest on grep over `lib/`, `server/`, `r2/` and `scripts/`.
- **E1:** no `COMPATIBLE` verdict could be exercised, because no runner manifest exists.
- **Windows:** lock behaviour was reasoned from `os.open(O_EXCL)` semantics, not tested on Windows.

## Resolution (after the review)

| Finding | Closed by |
|---|---|
| N1 | `4b137f64`: the release gate runs after construction on the model the backend actually calls, in `assemble_backend` and on every cache fetch; the canary refuses when the built backend's model differs from `--model`. Test: `tests/integration/lib/backend_assembly/test_release_gate_binding.py`. |
| N2 | `4b137f64`: a custom binding includes the model endpoint and, for a user-defined endpoint, its definition. |
| N4 | `4b137f64`: built-in bindings exclude rate and concurrency tuning keys; a key rotation still changes the binding. |
| N3 | `fe472726`: a lock older than 300 s is treated as left by a killed writer and cleared. |
| N5 | `9bac8e94`: `tests/unit/r2/host_hardening/test_paid_route_inventory_evidence.py` pins the evidence to the source inventory. |
| N6 | `9bac8e94`: `deselected`, `xfailed` and vitest `todo` count toward the skip budget. |
| Amendment item 1 | corrected in ADR-0091. |

