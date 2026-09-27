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

## Addendum (2026-09-28): deeper research on R2, R3 and R4

The sponsor asked for R2 to be explained more clearly, and for R3 and R4 to be
researched until the best option is found.

### R2 — what "no paid route in the release" means in practice

- **Two separate modes.**
  - `DEV` keeps every route usable, as today. Development and experiments
    are unchanged.
  - The release deployment (`PRODUCTION_CANDIDATE`) refuses every
    unqualified route when it is constructed.
- **In a release deployment under R2a, the operator can still:**
  - create projects and upload or supply source;
  - edit scripts by hand;
  - render deterministic local media (Remotion/ffmpeg) and compose;
  - run Gates A–D, export, back up and restore.

  This is exactly the path the two Golden products and the restore drill
  proved.
- **What the operator cannot do in a release deployment:**
  - the Agent chat (every Agent provider is a paid LLM);
  - AI image, video, text or TTS generation through any built-in or custom
    provider;
  - custom-provider trial runs.
- **What stays available:** connectivity checks (`models.list`) and
  discovery, which are not billed. They still pass the outbound destination
  guard.
- **Precedent.** The earlier primary-source synthesis
  (`2026-09-25-r2-m7-h6-h8-primary-source-notes.md` §8) reached the same
  recommendation independently. It is a provider-free V1 profile for the two
  corpus products, and it keeps every paid path disabled until a specific
  path is qualified.
- **Moving to R2b later.** Any route can be enabled later without redesign.
  The sponsor authorizes a bounded paid canary for one exact
  provider/API/profile, the evidence is recorded and verified, and the
  registry entry becomes `QUALIFIED`.
  - For a synchronous route (image, text, audio), duplicate/restart and
    ambiguous-outcome handling must be designed first, because only async
    video has the attempt layer (fact 11).
- **Consequence to accept:** a first V1 release whose AI generation is off by
  default in release mode.

### R3 — trust model: facts

- **SLSA v1.0 build levels** (<https://slsa.dev/spec/v1.0/levels>).
  - **L1:** provenance exists, and "may be incomplete and/or unsigned at L1".
  - **L2:** "Build platform runs on dedicated infrastructure, not an
    individual's workstation, and the provenance is tied to that
    infrastructure through a digital signature".
  - **L3:** adds isolation, and keeps the signing secret away from build
    steps.
- **GitHub artifact attestations.** They sign provenance bound to the
  workflow, repository, commit and trigger. They must be verified, and they
  "are not a guarantee that the artifact itself is secure" (cited in the
  earlier notes §3).
- **Git.** `git patch-id --stable` supports a content-equivalence
  observation, not provenance. `range-diff` output is human porcelain and is
  not machine-stable (earlier notes §3).
- **Local environment.**
  - No git signing key is configured (`user.signingkey` is unset).
  - `gpg` and `ssh-keygen` exist; `cosign` does not.
  - Fork Actions have never run (`total_count 0`), and CI enablement is
    deferred by the sponsor.
- **ADR-0090 precedent.** V1 already chose "no signed custody receipt". The
  backup attestation is operator-supplied and consistency-checked.

### R3 — analysis

The threat that E1 finding S3 names is **self-asserted PASS**: a manifest that
states results no process produced. In this project, a manifest written by an
agent is a real instance of it.

- A signature by the same operator on the same workstation proves only who
  asserted and that nothing changed afterwards. By SLSA's definition it stays
  at L1, so it does not prove that the gates ran.
- Independent execution identity needs hosted infrastructure (L2), meaning
  CI. That is blocked twice: fork CI is not enabled, and the CI real-media
  budget is deferred.
- **Paid canaries cannot move to CI without putting provider credentials into
  CI secrets.** That is a new credential-exposure surface, which ADR-0090 and
  the V1 strategy avoid.

### R3 — options

- **T1: operator attestation plus runner-generated evidence (recommended).**
  1. A gate runner executes each gate command itself.
  2. It commits the raw logs with their digests, exit codes, parsed test
     counts (`N passed`, `0 failed`, `0 required skips`) and the tool
     versions.
  3. The verifier re-parses the committed logs instead of trusting manifest
     fields. That closes S3's "self-assert PASS without logs or counts".
  4. Provider qualification uses the same shape: the canary runner records
     the request and response summary, exit status and the profile digest,
     and the operator attests.
  - Trust is equal to ADR-0090.
  - What remains: an operator can still fabricate logs. This is disclosed,
    in line with "attestation trusts the operator".
- **T2: T1 plus git signing of evidence commits and the V1 tag.** This adds
  tamper-evidence after the fact and an attester identity. It is still L1,
  and it needs key custody decisions (V1-04 territory).
  - Better placed at V1-08, where the annotated release tag is created.
    Signing that tag is a cheap, standard step to decide there.
- **T3: CI-executed gates with GitHub artifact attestations (L2).**
  - Pros: gives independent execution identity.
  - Cons: it requires enabling fork CI, resolving the deferred real-media
    budget, and CI secrets for any provider canary.
  - Suitable for V2 or after the CI decision, not for V1-06.

**Recommendation: T1 for V1-06.** Decide tag signing (T2) at V1-08. Keep T3
as the upgrade path once CI is enabled.

### R4 — upstream: facts (upstream fetched 2026-09-28)

- **Size of the upstream range.**
  - From the merge base `6ddedc77` ("release 0.29.0") to `v0.31.0` there
    are 213 non-merge commits: 65 fix, 60 feat, 48 chore, 17 refactor and
    17 docs.
  - They touch 1661 files (+98,604 / −36,798 lines).
  - `upstream/main` is 294 commits ahead.
- **Largest changes.**
  - The ComfyUI backends.
  - `fe1e15e2`, "执行器改由应用装配处注入，拆出重启自愈与续跑" (the executor is now
    injected at app assembly; restart recovery and resumption are split
    out). This overlaps the M7-A/C execution, restart and resume domain.
  - The provider package move to `lib/backends/`.
- **Overlap with V1.** 35 files overlap with this branch's changes, 27 of
  them outside tests and docs. The overlap includes the generation worker,
  the ledger, the task and api_call models and repos, `server/app.py`, and
  the declarative backend.
  - Upstream added 6 Alembic revisions; this branch added 16.
- **Security defects confirmed present in the V1 lineage**, all fixed
  upstream:
  - `108d1680` (#2597): `server/auth.py::verify_token` accepts a
    `purpose: "download"` token as a session token.
    - Download tokens appear in URLs and live for 5 minutes, so any leaked
      download URL grants a full session.
  - `2c4ca6d6` (#2606): provider artifact downloads have no outbound
    destination check (link-local and cloud-metadata addresses) and no byte
    cap. The V1 lineage has no `artifact_download_guard`.
  - `8faf1450` (#2621): probes and model discovery skip the destination
    check.
    - A cross-origin 307/308 in `request_with_scoped_credentials` also
      forwards the request body to the redirect host.
  - `3ff6127f` (#2699): built-in provider requests go through the
    destination check. It also includes video-resume fixes, such as Gemini
    no longer mislabelling a paid, finished job as expired.
  - `d3d0c454` (#2599): `GET /custom-providers/{id}/credentials` exists in
    the V1 lineage (`server/routers/custom_providers.py:800`). It returns
    the provider key to the browser.
  - `9317ae46`: `cancel_task`/`get_cancel_preview` look tasks up by id
    without `_scope_query`.
  - `eec3c21e` (#2600): version snapshot paths are not validated
    (`resolve_snapshot_path` is absent).
- **Dry-run cherry-pick onto HEAD** (`git merge-tree --write-tree`), counting
  conflicts per commit:

  | Commit | Conflicts |
  |---|---|
  | `108d1680` | 0 |
  | `9317ae46` | 1 (test only) |
  | `eec3c21e` | 5 |
  | `8faf1450` | 7 |
  | `d3d0c454` | 8 |
  | `2c4ca6d6` | 17 |
  | `3ff6127f` | 36 |

  The last two depend on the upstream `lib/backends/` restructure.

### R4 — options

- **U1: pin V1 at the current base, with no upstream change.**
  - Rejected: V1 would ship with seven confirmed security defects that
    upstream has already fixed.
- **U2: integrate v0.31.0 (or `upstream/main`) before V1.**
  - It brings every fix, plus about 1600 files of feature work V1 does not
    need, such as ComfyUI.
  - It re-architects the executor that M7-A/B/C just accepted, which
    re-opens M7 and every gate.
  - Rejected for bounded V1 (ADR-0089).
- **U3: pin the base and backport the security fixes (recommended).**
  - Backport the seven fixes above, each with an E1 disposition:
    - `CHERRY_PICK` where the diff applies (verified by `git patch-id
      --stable` equality);
    - `ADAPTED` where the upstream restructure prevents a clean pick.
      These are re-implemented against V1's layout, with the upstream tests
      ported.
  - The E1 upstream verifier then has a real, bounded use: its inventory is
    the seven selected commits and their dispositions.
  - All other upstream commits are recorded as `DEFERRED` to the first
    post-V1 upstream integration.
  - This needs one schema change. The verifier currently demands the full
    ordered range `old_sha..new_sha` (fact 12). A selective backport needs
    an explicit "selected commits" inventory, and the unselected commits must
    each carry a `DEFERRED` disposition.

**Recommendation: U3.** It removes known vulnerabilities, keeps M7's accepted
execution design, and gives E1 a concrete, reviewable use. The full upstream
merge becomes a post-V1 packet, verified with the same tool.

## Addendum 2 (2026-09-28): the sponsor's production requirement and a second upstream pass

**Sponsor requirement (R2):** "khi sản xuất sản phẩm thật, sẽ có thể vừa chạy
local vừa chạy cloud trả phí". When real products are made, the release must
be able to run both local rendering and paid cloud generation. R2a (no
enabled route) therefore does not meet the requirement.

The V1 policy still applies: an enabled paid route must be `QUALIFIED`
(strategy §5/§6, spec §10). V1-06 therefore has to deliver three things:

1. a working **qualification path**;
2. the routes the operator will actually use, **qualified**;
3. every other route **disabled** in release mode.

### New facts

- **Synchronous paid routes auto-retry on ambiguous outcomes.**
  - `lib/retry.py` retries on `TimeoutError` and on messages that contain
    "timeout" or "gateway timeout". It is applied to paid image submits:
    Gemini (5 attempts), OpenAI, Ark, DashScope, MiniMax and Agnes. It is
    also applied to Grok text.
  - A timeout after the request was sent is an ambiguous outcome: the
    provider may have processed and billed the request. A blind retry can
    charge twice.
  - Only async video has the M7 attempt layer, with submit receipts and
    reconciliation.
- **Anonymous project file read.** Probe run on the V1 lineage with the real
  ASGI app and no credentials:
  - `GET /api/v1/files/demo/project.json` returned 200 with its content;
  - `GET /api/v1/files/demo/source/novel.txt` returned 200 with the source
    text.
  - `files.public_router` is mounted without authentication
    (`server/app.py:710`) and serves any file under the project directory.
  - Upstream `c1cf1c62` (#2601) restricts it to media directories and media
    extensions, and adds `nosniff`. This is the **eighth** confirmed security
    defect. It also bears on the O2a export route: the export copy must sit
    in an allow-listed media location.
- **Second pass over upstream fixes.** There are 100 fix/revert commits since
  the merge base (up to `upstream/main`). V1-relevant candidates beyond the
  eight security fixes:
  - **paid-route cost correctness:**
    - `3ff6127f`: a Gemini paid job misjudged as expired;
    - `7e994e5f`: reuse a manual upload instead of a paid regeneration;
    - `0f8a4e1f`, `39fe7611`: price estimates;
    - `70e1db92`, `d42226d5`, `7f3dfa14`: request facts;
    - `6676f109`: telling an interrupted task from a user-cancelled one;
    - `1cf17bfa`: cascading cancel of `cancelling`;
    - `91b50681`;
  - **scope and authorization:**
    - `5839ef3b`: retry-download lookup through `_scope_query`;
    - `31c5e985`;
    - `e6e60d0c`: project-name validation on routes;
  - **data integrity:**
    - `29c778f0`: a current-scope archive export leaves no orphan
      snapshots;
    - `6a3e6cd8`: source symlink handling;
    - `11f77f8f`: migrating old video version records.

  The remaining fixes are ComfyUI, market, the data-root relocation
  (a large layout change), UX and i18n, and development skills. Those are not
  V1 needs.

### R3: decision by research

The sponsor delegated this choice to research. **T1 is selected**, for the
reasons in Addendum 1, which the sponsor's R2 requirement strengthens:

- Paid canaries run on the operator machine with the operator's
  credentials, so a hosted-CI identity (T3) cannot cover them without
  moving provider secrets into CI.
- Signing on the same workstation (T2) stays at SLSA L1 and does not prove
  that the gates ran.
- T1's runner-generated, log-parsed evidence directly closes E1 finding S3,
  within the ADR-0090 trust model.
- Tag signing is decided at V1-08. CI attestation (T3) is the upgrade path
  once CI is enabled.

### R2: what qualifying a route requires (per route)

1. **An exact profile.** Provider id, API version, adapter version and
   endpoint, in the registry with its `entry_digest`.
2. **Safe execution.**
   - *Async video:* the existing M7 attempt layer. It still needs a test
     that proves duplicate submission, restart and an ambiguous outcome
     against the qualified adapter version.
   - *Synchronous image, text or audio:* no automatic retry after an
     ambiguous outcome, and the ambiguity recorded as a failed attempt for
     the operator to decide on. A provider-documented idempotency key is the
     exception, and it must be cited per provider.
3. **A paid canary.** Authorized by the sponsor with a spend bound, run by
   the T1 runner, and its evidence content-verified by the fixed E1
   verifier.
4. **An expiry.** Evidence carries `expires_at`, so an upgraded provider or
   adapter needs requalification.

**Open input from the sponsor:** which exact providers and models the
operator will use in production, per modality (Agent/text, image, video,
TTS). Only those are qualified; all others are disabled in release mode.

### R4: options restated with the new evidence

- **U1: pin with no backport.** Rejected: eight confirmed security defects,
  including an anonymous source/script read.
- **U2: integrate `v0.31.0`.** Brings every fix, with about 1600 files of
  unneeded feature work. It also re-architects the executor that M7-A/B/C
  accepted, and brings the data-root layout relocation.
- **U3: pin and backport a selected set (recommended).**
  - All eight security fixes.
  - The paid-route cost-correctness fixes for the routes that will be
    qualified.
  - The scope and data-integrity fixes listed above.
  - Each commit carries an E1 disposition: `CHERRY_PICK`, verified by
    stable patch-id, or `ADAPTED`, re-implemented with the upstream tests
    ported. Everything else is `DEFERRED` to a post-V1 upstream merge.
  - Cost is roughly 20–25 commits. Several conflict with the upstream
    `lib/backends/` restructure; the dry run showed 0–36 conflicts per
    commit.
- **U3 versus U2.** U3 keeps M7's accepted execution design and a bounded
  review surface. U2 is simpler to describe but re-opens every accepted
  gate. With paid cloud in scope, U3's paid-route fixes must be chosen per
  qualified route, so the route list also shapes the backport set.
