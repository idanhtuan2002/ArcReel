# R2 V1-06 — paid outbound routes and E1 remediation

Date: 2026-09-28. Branch `feat/r2-m7e-v1-lineage` at `2d1ab1e1`. This note
is research: it states facts, inferences, options and recommendations. It
records no decisions. License is out of scope.

## Question

What does V1-06 require? Backlog V1-06 reads: "Remediate existing E1
compatibility/qualification findings, enumerate all paid outbound routes and
disable or exactly qualify each release route". Its acceptance criteria:
"executable provenance/mapping/evidence checks, correct test tiers,
exact-version route inventory; E1 independently accepted. Paid
canaries/credentials require separate authorization".

## Facts

### Policy already decided

1. **Unqualified routes are disabled.**
   - ADR-0089 decision 6 says "qualify or disable each paid provider path".
   - V1 strategy §5 P0.3 says "disable any unqualified paid route". It also
     says an "unqualified enabled provider … stops the V1 release candidate".
   - §6 adds that "enabled paid routes prove duplicate/restart and
     ambiguous-outcome behavior".
2. **Only QUALIFIED routes may run in production.**
   - Host-hardening spec §10: "Only `QUALIFIED` routes may be enabled in a
     production-candidate configuration. Paid canaries, … credential use and
     deployment require explicit operational approval".
   - §12: an "inability to enumerate all paid submit routes … stops that
     route fail-closed".

### Current route gate (`r2/host_hardening/route_inventory.py`, `provider_capabilities.py`)

3. **Inventory scope.** The inventory covers only paid **asynchronous video
   submits**: 11 families. All 11 are `UNQUALIFIED` in
   `r2/provider_capabilities/registry.json`.
4. **The gate never enforces qualification today.**
   - The only enforcement point is
     `lib/video_backends/execution_adapter.py:149`, which calls
     `require_submit_route(...)` with the default `ReleaseMode.DEV`.
   - DEV does not require `QUALIFIED`.
   - No configuration sets `PRODUCTION_CANDIDATE`.
5. **Video calls outside the worker skip the gate.** `submit_video_attempt`
   returns `await submit()` without any gate when `request.task_id is None`
   (`execution_adapter.py:144-145`).
6. **Built-in MiniMax video is unbound.**
   - `lib/backend_assembly/specs.py:148-176` builds a `DeclarativeVideoBackend`
     with `provider="minimax"`, so its key is
     `("minimax", "declarative-video-submit")`.
   - That key is not in the inventory. A probe raises
     `SubmitRouteUnboundError M7_SUBMIT_ROUTE_UNBOUND:minimax:declarative-video-submit:host-video-v1`.
     Worker MiniMax video tasks therefore fail even in DEV.
7. **The inventory test is tautological.**
   `test_every_paid_async_submit_family_is_inventoried` compares
   `discovered_submit_families()` with `registered_submit_families()`. Both
   come from the static `PAID_ASYNC_SUBMIT_FAMILIES` tuple. Nothing discovers
   a new route from source.

### All paid outbound routes (source-enumerated)

8. **One constructor for media and text.**
   `lib/backend_assembly/assembler.py::assemble_backend` builds every image,
   video, text and audio backend, both built-in and custom.
   - Its callers are `server/services/generation_context.py:103`,
     `lib/text_backends/factory.py:29` and
     `lib/custom_provider/endpoint_test/trial_run.py:594`.
   - `PROVIDER_SPEC_REGISTRY` holds 32 built-in (provider, media) pairs.
   - Custom providers add declarative image, video, text and audio routes.
9. **Paid routes outside `assemble_backend`.**
   - **Agent runtime.** The Claude Agent SDK talks to the configured Agent
     provider. There are 11 presets in `lib/agent_provider_catalog.py`,
     including `anthropic-official` and `arcreel`, plus custom Anthropic
     endpoints.
   - **Custom-provider trial runs.** `POST /endpoint-tests/trial-runs` makes
     real generation calls.
10. **Outbound calls that are not billed generation.** These are the
    connectivity checks in `server/routers/providers.py` (`_check_*`, which
    call `models.list`) and custom-provider discovery
    (`lib/custom_provider/discovery.py`).
11. **Asynchronous video only is attempt-bound** (M7-A). Image, text and
    audio are synchronous calls with no attempt or reconciliation layer.

### E1 status (`R2_M7_E1_INTEGRATION_STOP_2026-09-25.json`, reviewed code `404a5945`)

12. **Where the E1 code lives.** It is in `r2/host_hardening/compatibility.py`,
    `scripts/r2/verify_upstream_candidate.py`,
    `scripts/r2/verify_provider_qualification.py`, two schemas under
    `docs/r2/schemas/`, and tests under `tests/unit/scripts/r2/`. None of it
    changed after `404a5945`.
13. **Spec findings.**
    - (S1) `COMPATIBLE` is returned without proving that the upstream change
      was integrated. `integration_method` is never checked.
    - (S2) `OFFLINE_VERIFIED` accepts evidence whose contents report failure.
      Only the bytes and the self-described `evidence_kind` are checked.
    - (S3) A committed manifest can self-assert PASS with no gate logs, test
      counts or run identity.
    - (S4) `SANDBOX_VERIFIED`/`QUALIFIED` are refused. This is intentional;
      no qualification has happened.
14. **Standards findings.**
    - (T1) Unit tests launch git and Python subprocesses; they belong in the
      integration tier.
    - (T2) Core compatibility tests sit under the `scripts` mirror mixed
      with CLI tests.
    - (T3) Comments contain task and temporal wording.

### Upstream position

15. **Upstream position.**
    - The V1 lineage branched from upstream `6ddedc77` ("release 0.29.0",
      2026-09-05). This branch is 460 commits ahead.
    - The fetched `upstream/main` has 23 more commits. The remote now carries
      `v0.30.0` and `v0.31.0`, with head `317a7d0d`.
    - No upstream range has been integrated into the V1 lineage since the
      merge base, so no upstream candidate report exists.

## Inferences

- **Scope.** "All paid outbound routes" is wider than the M7-A inventory. It
  covers every `assemble_backend` pair, custom-provider media, the Agent
  runtime and trial runs. The spec §12 stop condition applies to the video
  routes that are not enumerated (facts 6 and 7).
- **Where to enforce.** Enforcement fits at three existing points, with no
  new layer:
  - `assemble_backend`, for all media and text;
  - Agent session start;
  - trial-run start.
  The video attempt gate stays as it is. It must also cover submits outside
  the worker, or those must be disabled (fact 5).
- **What PRODUCTION_CANDIDATE means today.** With every profile
  `UNQUALIFIED`, a `PRODUCTION_CANDIDATE` release enables **no** paid route,
  unless the sponsor authorizes paid canaries for chosen routes.
  - The V1 products must then run no-provider, as the Golden corpus already
    does.
  - The Agent is disabled. This is the largest product consequence: script
    development would be manual editing, with no Agent assistance.
- **S1–S3 can be fixed with primary-source git and evidence checks:**
  - integration proof through ancestry for `MERGE`, and through
    `git patch-id --stable` equality for `CHERRY_PICK`/`REBASE`/`PATCH`;
  - evidence content parsed and bound to the exact profile;
  - gate logs committed with their digests and parsed pytest/vitest
    summaries.
- **Trust.** Run identity on a single operator machine has the same trust
  model as the ADR-0090 backup attestation: operator-attested and
  consistency-checked, not signed.

## Options and recommendations

**R1. Route inventory and enforcement.** Engineering; it follows decided
policy.

- **Inventory.** Extend it to every paid route class:
  - media and text by `(provider_id, media_type, endpoint)`, one profile each;
  - custom-provider families;
  - the Agent runtime;
  - trial runs.
- **Discovery test.** Replace the tautological test with a source-derived
  check. It must enumerate `PROVIDER_SPEC_REGISTRY` and every
  `submit_video_attempt` call site, then fail on any unlisted route.
- **Release mode.** Add a deployment setting, for example
  `ARCREEL_RELEASE_MODE=PRODUCTION_CANDIDATE`. In that mode every
  unqualified route fails closed at construction, with a machine-readable
  reason and a disabled-capability indication in the UI (V1 strategy §4
  disclosure).
- **Bugs.** Fix the MiniMax binding (fact 6) and the gate bypass outside the
  worker (fact 5).

**R2. Which routes V1 enables.** This is the sponsor's decision.

- **R2a — none (recommended default until canaries are authorized).**
  - V1 releases no-provider: operator-supplied source and script, and local
    deterministic media.
  - The Agent is disabled in release mode. DEV keeps everything, for
    development.
  - Fits the evidence already accepted.
- **R2b — qualify a named minimal set.** For example, one Agent text
  provider, plus optionally one image, one video and one TTS route.
  - Each needs authorized paid canaries with a budget.
  - Each also needs duplicate/restart and ambiguous-outcome proof. Image,
    text and audio have no attempt layer today (fact 11), so this is new
    work.
- **R2c — enable unqualified routes with a disclosure.** Rejected: it
  contradicts strategy §5/§6 and spec §10.

**R3. Qualification trust model.**

- **Recommended:** operator attestation that is consistency-checked, the same
  model as ADR-0090 (no signing in V1).
- **Alternative:** signed attestation. Consistent with ADR-0090's V1-04
  deferral, it is not needed for V1.

**R4. Upstream.**

- **Recommended:** pin V1 to its current upstream base. No upstream range
  goes into V1. The upstream verifier is fixed (S1–S3) and exercised on
  fixtures now, and used for the first post-V1 upstream integration.
- **Alternative:** integrate upstream v0.31.0 before V1. That enlarges V1's
  lineage and re-opens every gate.

**R5. E1 remediation.** Engineering.

- Fix S1–S3 as described in the inferences. S4 stays by design.
- Move the subprocess tests to `tests/integration/r2/host_hardening/`.
- Split the tests by tested object.
- Remove the temporal wording.
- Then run an independent E1 review.

## Unknowns

- Whether the sponsor accepts a V1 with the Agent disabled (R2a), or wants
  canaries authorized (R2b), and for which routes.
- The exact UI surface for disabled capabilities. It should reuse existing
  provider settings and error surfaces; this needs checking during design.
