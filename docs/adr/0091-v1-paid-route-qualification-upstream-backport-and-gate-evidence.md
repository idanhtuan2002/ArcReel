---
status: accepted
---

# V1 qualifies paid routes in two levels, backports selected upstream fixes, and gates on runner-generated evidence

On 2026-09-28 the sponsor stated a production requirement for V1-06. Real
products must be able to use local rendering and paid cloud providers, and the
operator must be able to change cloud providers freely. The sponsor then
delegated the choice of mechanism to research. The research is in:

- `docs/research/2026-09-28-r2-v1-06-paid-routes-and-e1-remediation.md`,
  including its addenda and corrections;
- the document audit `docs/research/2026-09-28-r2-v1-decision-audit.md`.

This ADR works inside ADR-0078 and ADR-0089. It does not change V1 policy:
each paid route is either qualified or disabled, and V1 makes no
provider-agnostic claim.

**Generic safety invariants for every paid route.** In a release deployment,
every paid outbound route obeys the following. This covers built-in and
custom image, video, text and audio routes, the Agent runtime and
custom-provider trial runs.

1. **Budget before submit.** An operator-set budget scope is reserved and
   claimed before the first paid side effect. Over-limit requests are refused
   before they are sent. This wires the existing budget reservation and
   `submit_with_budget_guard`.
2. **No automatic resubmission after an ambiguous outcome.** This is already
   an ADR-0078 decision.
   - Synchronous routes do not retry once the request may have been sent.
   - Async video keeps the M7 attempt layer.
   - The current timeout retries on paid synchronous calls are a conformance
     gap against ADR-0078 and must be closed.
3. **Outbound destination and byte-cap checks** on provider requests and
   artifact downloads.
4. **Correlated usage records.** H7 already provides them.
5. **A route inventory derived from source.** A paid route that is not
   listed fails the build, and fails closed at runtime (M7 spec §12).

**Two-level qualification (F1).** A route is `QUALIFIED` only when both
levels hold for the running adapter version.

- **Adapter level (offline, shipped with the release).**
  - Controllable fakes show the frozen qualification profile
    (`R2_05` §7): submit, status/poll, restart resume, cancellation, rate
    limiting, cost capture, error redaction, timeout/retry and capability
    metadata.
  - The result is at most `OFFLINE_VERIFIED`, versioned per adapter.
- **Route level (live, at runtime).**
  - The operator runs one bounded canary from the product for an exact
    provider, endpoint, model and account route. Running it is the
    operator's authorization and spend.
  - The evidence shows exact-version submit, poll, result retrieval and cost
    capture.
  - The route becomes `QUALIFIED` with an expiry. A change of adapter
    version invalidates it.

**Storage.** Route qualifications are deployment records inside the single
CapabilityRegistry (R2-OPEN-004). Static adapter profiles and runtime route
qualifications are read through one registry API.

**Release mode.** A release deployment (`PRODUCTION_CANDIDATE`) refuses every
paid route that lacks a current qualification. `DEV` keeps today's behaviour.
Any provider can be enabled by qualifying its route. The V1 tag records the
routes qualified at tagging time. Later qualifications are operational
records.

**Evidence trust (T1).**

- **Gate evidence is produced by a runner.** The runner executes each gate
  command and commits the raw log with its digest, exit code, parsed test
  counts and tool versions.
- **Verifiers trust only the logs.** They re-parse the logs instead of
  trusting manifest fields. A zero-test selection, a required skip, a dirty
  evidence HEAD or a historical run is a failure (M7 spec §11).
- **Attestation.** Canary evidence has the same shape. The operator attests,
  under the ADR-0090 trust model; there is no signing in V1-06.
- **Deferred.** Signing the release tag is decided at V1-08. CI artifact
  attestation (SLSA Build L2) is the upgrade path once CI is enabled.

**Upstream (U3).**

- **What V1 contains.** V1 stays on its current upstream base and backports
  a selected set:
  - every confirmed security or scope fix;
  - every paid-route cost or correctness fix for the route classes V1
    enables;
  - every data-integrity fix for export or versions.
- **Recording.** The E1 upstream report inventories the whole upstream range.
  Selected commits are `UNCHANGED` (clean cherry-pick, stable patch-id) or
  `ADAPTED` (re-implemented, with upstream tests ported). All others are
  `DEFERRED`. The verifier must prove that each `UNCHANGED` or `ADAPTED`
  commit is present in the host range.
- **Later merge.** A full upstream merge is a post-V1 packet that re-runs the
  H6 and M7 acceptances.

## Considered options

- **All paid routes disabled in the release (R2a).** Rejected: it does not
  meet the sponsor's production requirement.
- **Operator opt-in without a canary (F2).** Rejected: it would enable
  unverified routes, contrary to ADR-0078, strategy §5/§6 and the V1
  non-promise of "provider-agnostic production claims".
- **A static repository registry qualified per provider (F3).** Rejected:
  every provider change would need a release, and custom providers could not
  be covered.
- **Signing gate evidence on the operator workstation (T2).** Not adopted
  for V1-06. It stays at SLSA Build L1 and does not show that the gates ran.
- **CI-attested evidence (T3).** Deferred. Fork CI is not enabled, and paid
  canaries would need provider secrets in CI.
- **Integrating upstream `v0.31.0` (U2).** Rejected for V1. It would re-open
  the M7-A/B/C/D acceptances:
  - the Vertex credential move into the data root breaks ADR-0090's
    credential exclusion;
  - the data-root layout changes;
  - the Alembic graph forks (an M7 spec §12 stop condition);
  - the `cancelling` status is retired;
  - the executor is re-architected.
- **Staying on the base with no backport (U1).** Rejected: it leaves the
  confirmed defects that upstream has fixed.

## Consequences

- **What V1-06 implements:**
  - the invariants;
  - the source-derived inventory and release-mode refusal at
    `assemble_backend`, Agent session start, trial-run start and the video
    submit seam, including taskless submits;
  - adapter-level offline qualification;
  - the runtime qualification store and canary runner;
  - the E1 fixes S1–S3 and T1–T3;
  - the U3 backport set.
- **Separate authorization.** Paid canaries run only when the operator
  starts them. The agent never starts them.
- **Qualification is renewed.** Changing an adapter version during an upgrade
  requires routes to be qualified again.
