---
status: proposed
---

# M10 separates quality evidence, Human Final Cut, packaging selection and export materialization

M10 shall be one host-integrated quality and packaging module with four distinct
responsibilities: versioned `QualityProfile` policy, immutable multi-assessor
`QualityRun` evidence, append-only Human `QualityDisposition`, and immutable
`PackagingCandidate` selection followed by deterministic local export. Probe,
model and donor adapters may observe; none may issue `PASS`, `REWORK` or `WAIVE`.
Packaging Authority may select an exact package revision only after revalidating
the current disposition, but cannot replace the ApprovedMaster, write an M8
artifact slot, invoke Production Authority or perform a network side effect.

This specializes ADR-0080 rather than widening it. M10 first establishes the
quality-evidence foundation, then adds packaging candidates and export bundles.
It may deepen the host's secure FFmpeg/ffprobe subprocess behavior, M7 execution
receipts and the accepted M8 candidate mechanics, but it must stop if the live
accepted predecessor does not expose the required seam. A proposed M8/M9 type or
historical green test is not an implementation dependency.

## Decision

- `QualityProfile` revisions are immutable and cohort/product-surface specific.
  A versioned typed policy—not an opaque JSON bag—owns stable rule IDs, probe
  configurations, assessment slots/counts/independence/escalation, reference
  eligibility, accessibility, freshness, disposition and waiver bounds. These
  are never hidden adapter defaults.
- A `QualityRun` binds one exact ApprovedMaster/artifact digest, profile revision
  and digest, assessed-subject closure, probe executions and observation digests.
  Technical, factual, narrative, continuity, perceptual-regression,
  perceptual-review and accessibility observations form a closed discriminated
  union; completeness is evaluated from typed assessment requirements/slots,
  not one row per broad assessor kind. Missing required evidence is not a zero
  score or a pass.
- `QualityDispositionAuthority` is a Human custodian. Every append-only decision
  binds the complete run and subject closure. `WAIVE` is reasoned, scoped and
  time-bounded. Artifact, profile, run, subject or selected-package drift, expiry,
  revocation or supersession makes readiness stale.
- `PackagingCandidate` is an accepted schema evolution of the M8 candidate
  kernel with the closed target `PACKAGING_SLOT`. Its revision binds the exact
  ApprovedMaster, content and presentation payload digests, profile identity and
  required package assets. Promotion is preview-bound and CAS-protected; it does
  not create an ApprovedMaster.
- An export bundle is a deterministic projection of the selected package. Its
  manifest lists relative paths, media types, byte sizes and content digests and
  binds the source package, disposition and tool/config identities. Export writes
  no upload, publish, schedule, public-visibility or provider-success state.

## Considered options

- A single automated quality score was rejected because unlike observations
  become falsely interchangeable and an adapter would acquire Final Cut authority.
- Packaging and quality in one first implementation packet was rejected because
  it prevents the evidence authority from being tested independently.
- A vertical-Short-only kernel was rejected because one fixture or cohort would
  become accidental universal policy. Vertical factual Short remains the second
  pilot after a Western explainer foundation.
- Reusing M8 planned contracts without checking accepted implementation was
  rejected because milestone plans are not executable authority.

## Consequences

- M10 implementation is blocked until M9 and all earlier prerequisite evidence
  required by ADR-0080 are independently accepted and the actual M8/M7 seams are
  verified on the implementation base.
- The M10 design acceptance owns and hash-binds a repository-read-only bootstrap
  verifier. M10-A creates its implementation-time scope verifier only after that
  bootstrap proves eligibility; failures write diagnostics outside the repo.
- M10 is delivered in independently accepted packets: M10-A completes the
  profile/probe/run/disposition foundation; M10-B adds packaging, deterministic
  export and the three product-surface pilots; M10-C, only if repository
  convention requires it, binds integration evidence without adding authority.
- M11 remains the sole owner of provider credentials, upload/publish commands,
  reconciliation and public release. An M10 export is never publication evidence.
- This ADR authorizes design and implementation planning only. It does not
  authorize code, migrations, provider calls, credentials, deployment,
  publication or production operations.
