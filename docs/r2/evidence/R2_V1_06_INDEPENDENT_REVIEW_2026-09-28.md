# R2 V1-06 — Independent review (2026-09-28)

**HEAD reviewed:** `86a2d6922694762d0e21e98aa71d2e9473343ecb` (branch `feat/r2-m7e-v1-lineage`, worktree `.worktrees/r2-m7e-v1-lineage`), clean tree.

**Range:** `20a030d8..86a2d692`, 30 commits.

**Reviewer mode:** read-only. No edits, commits, subagents, full suites or renders; every scratch reproduction ran from the session scratchpad, outside the repo.

## Verdict: CHANGES_REQUIRED

The P1/P2 security backports close the defects they claim to close. The release-mode gate reaches every construction path found. The ambiguity predicate is correct for the httpx, OpenAI, Ark and google-genai exception shapes, and the S1 integration check reproduces on the committed inventory.

Seven major findings block acceptance:

1. **Custom-provider qualification is not bound to the provider.** One canary qualifies every custom provider that uses the same model name. Reproduced.
2. **The budget guard permanently leaks the hold of every failed or resume-failed call in a non-USD scope.** Reproduced for CNY; the scope eventually refuses legitimate calls.
3. **The xAI (Grok) SDK still retries paid gRPC submits on `UNAVAILABLE`** inside the SDK, although the new predicate classes `UNAVAILABLE` as ambiguous.
4. **Qualification is checked only at backend construction.** The in-process backend cache keeps using a route after its qualification expires or is removed.
5. **The gate-log parser lets output lines override the runner header, and required skips are never enforced.**
6. **The Agent route can be qualified in `PRODUCTION_CANDIDATE` without budget-before-submit** (ADR-0091 invariant 1).
7. **The ADR "implementation notes" change the decision while stating the decision is unchanged.** They redefine the synchronous-route adapter level as "generic invariants the suite proves for every adapter", which is not proven per adapter, and they place storage outside the single CapabilityRegistry API.

E1 cannot be independently accepted yet:

- the inventory records `full_report_status: PENDING_GATES`;
- no runner-written gate manifest exists;
- finding 5 affects S3.

## Findings

### Major

**1. Custom-provider route qualification is not bound to the provider, endpoint, base URL or account.** CONFIRMED, reproduced.

- **Where:** `r2/host_hardening/paid_routes.py:123-129` (`media_route` returns `PaidRoute("custom_media", media_type=…)` with no provider); `r2/host_hardening/route_qualifications.py:171-186` (records are keyed by `(route_ref, model_id)`).
- **Failure:** qualify `custom-7` with `gpt-image-1`, then add `custom-9` pointing at any relay with the same model name. `is_route_qualified(media_route('custom-9','image'), 'gpt-image-1')` returns True, so `custom-9` makes paid calls with no canary.
- **Same gap on other routes:** built-in `media:{provider}:{type}` and `agent:{preset}` are not bound to a base URL or credential. A new key or base URL, or a restore into another deployment, keeps the route QUALIFIED.
- **Requirement:** ADR-0091 F1 says "exact provider, endpoint, model and account route".

**2. Every failed or resume-failed call in a non-USD scope leaks its hold permanently.** CONFIRMED, reproduced.

- **Chain:**
  1. `usage_repo.py:421` settles failed rows with `base_currency=row.currency or "USD"`, and the row currency defaults to USD.
  2. `budget_guard.py:151` passes that currency to `reconcile`, which raises "cost evidence currency does not match its budget scope".
  3. `reconcile_call` swallows the error, so the reservation stays CLAIMED.
- **Reproduced:** an Ark Seedance call failing on `release:CNY` leaves `reserved_total=6.9`. The same happens through `resume_failed`.
- **Test gaps:** no failure-path test and no non-USD test.

**3. Grok paid submits are still resent inside the xAI SDK.** CONFIRMED.

- **Where:** `lib/grok_shared.py:50-54` builds `xai_sdk.AsyncClient` without `channel_options`.
- **What the SDK does:** xai_sdk's default channel options set `grpc.enable_retries=1` and a service config that retries `UNAVAILABLE` up to 5 attempts (`xai_sdk/client.py:13-35`).
- **Affected paths:** Grok image, text and video submissions.

**4. Qualification expiry, revocation and adapter-level loss are not enforced on a cached backend.** CONFIRMED.

- **Where:** `server/services/generation_context.py:45-82,111`.
- **Why:** `_BackendCache` reuses a built backend until a provider config change or a restart, while `require_paid_route` runs only inside `assemble_backend`.

**5. The S3 gate-log parser can be overridden by gate output, and required skips are never enforced.** CONFIRMED.

- **Header override:** the header comes from `dict(re.findall(... MULTILINE))`, so the last `# exit_code:` line anywhere in the log wins.
- **Skips:** `skipped` is parsed but never used, and `run_gates.py:45` hard-codes `required_skips: 0`.
- **Trust limit to disclose:** a hand-written log is indistinguishable from a runner log.

**6. The Agent route can be qualified in `PRODUCTION_CANDIDATE` without budget-before-submit.** CONFIRMED.

- Agent spend is backfilled after the fact, and `run_agent_canary` records `cost_record_ref=None`.
- **To close:** keep the Agent route refused in `PRODUCTION_CANDIDATE`, or record a sponsor-accepted exception or per-session reservation decision (an ADR amendment).

**7. ADR-0091 "Implementation notes" change the decision.** CONFIRMED.

- **Adapter level:** the notes redefine it for image, text and audio. No per-adapter proof exists, and finding 3 is a live counterexample.
- **Storage:** records live in a separate file store with its own API, not inside the single CapabilityRegistry, and the handoff still says "inside the single CapabilityRegistry".
- **Canary surface:** the canary is CLI-only; plan P5 says "through the API and the CLI".

### Minor

8. **T1 remediation is incomplete.** `tests/unit/scripts/r2/test_verify_m7_scope.py:22-50` still runs git subprocesses in the unit tier. CONFIRMED.
9. **No committed exact-version paid-route inventory evidence** listing each route class, its adapter version and its release disposition. CONFIRMED.
10. **Stale or inconsistent evidence.** CONFIRMED.
    - The handoff still shows P3.5 in progress and P4/P5 to do.
    - The backport record labels 9 commits "UNCHANGED (pick)". The inventory proves only 4; the other five (`9317ae46`, `c1cf1c62`, `e6e60d0c`, `eec3c21e`, `39fe7611`) are ADAPTED by marker.
    - `3ff6127f` is recorded as plain ADAPTED, although it is only partly adapted.
11. **Residual unguarded outbound paths.** CONFIRMED.
    - Vertex video download uses `urllib.request.urlretrieve(video_ref.uri)` (`lib/video_backends/gemini.py:417`), with no guard or cap, and it also accepts `file:` URIs.
    - SDK transports are not destination-guarded.
    - The scan test matches only `httpx.AsyncClient(` (it misses `httpx.Client(`, e.g. `lib/vidu_shared.py:220`).
12. **Store integrity and concurrency.** CONFIRMED by reading.
    - The evidence file is written non-atomically.
    - The records read-modify-write takes no lock.
    - The digest is unkeyed.
    - A malformed `qualifications.json` raises a raw `JSONDecodeError`.
13. **A crash or claim failure between reserve and claim leaves a permanent ACTIVE hold,** because `expires_at=None` (`budget_guard.py:103-123`). PLAUSIBLE.
14. **Adapter-version invalidation depends on convention:** `ROUTE_ADAPTER_VERSIONS` is maintained by hand. PLAUSIBLE.
15. **Two resend and overspend risks.** PLAUSIBLE.
    - The predicate resends on any 5xx, and 502/504/524 from gateways can be ambiguous. This is inherited from `should_retry_submit`.
    - The 0.01 floor on token-priced text bounds overspend only by concurrency. This is disclosed.

## Commands (at HEAD 86a2d692)

| What | Result |
|---|---|
| `git log`, `git show` of every P1–P5 commit, upstream object greps | inspected |
| Targeted pytest over the budget guard, route qualifications, inventory, predicate, guard, host_hardening integration, `scripts/r2`, auth, execution adapter and options assembler | 175 passed, 22 skipped (PG-only) |
| `_verify_integration` on the committed inventory | passes; the DEFERRED and UNCHANGED mutations are rejected |
| Scratch reproductions | findings 1, 2 and 5 reproduced |
| SDK source inspection | xai_sdk default channel options; google-genai 2.18.1 retry args; volcengine `DEFAULT_MAX_RETRIES=2` and its `from err` chaining |
| Cost probes | Ark and DashScope price in CNY; OpenAI text estimates 0.0 |

## Coverage limits

- **Not run:** the full backend, PG-dialect, frontend and website suites; the static gates; any real provider call.
- **Verified by identity only:** the cherry-picked upstream fixes were checked by commit identity, not re-audited line by line.
- **Not exhaustive:** the retry paths of every backend. Discovery used grep and Read, not the codebase-memory graph.
- **E1:** no `COMPATIBLE` verdict could be exercised.
