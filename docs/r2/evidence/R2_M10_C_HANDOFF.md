# M10-C handoff (live)

Rewrite in place; resume entry for the quality operator surface.

## State
- Worktree `.worktrees/r2-m10-c`, branch `design/r2-m10-c-operator-surface`, base `5256a9d72` (M10 accepted with
  conditions, `R2_M10_ACCEPTANCE.json`). `design/r2-m10-b` is pushed to origin by the sponsor.
- Why: M10-A has no router/UI, so deploying M10 ships a Packaging page whose prerequisites (published V2 profile,
  sealed run, PASS disposition) no operator can create. Sponsor order 2026-10-29: do step 1 (put M10 into the
  release) then step 2 (M9-B); do not stop to ask.
- Design: `docs/superpowers/specs/2026-10-29-r2-m10-c-operator-surface-design.md` (subject resolver, host probe
  catalog, quality router, Quality page, Packaging prefill).

## Reviews
- Design r1 **REWORK** (`m10-c-reviews/design-codex-review.json`): H1 one TECHNICAL requirement with two probe slots
  can never PASS (shared independence group → INDETERMINATE); H2 closure follows only `master:` refs; H3 a host
  catalog must be code-embedded, source-reviewed and qualified (A4), not generated JSON; H4 stable command
  reconstruction / receipt-first replay for every POST; H5 A3/A6 custodians re-verify startup per issuance (no
  supplied-reader API); M1 profile revision/CAS, disposition head/expiry inputs; M2 Human rubric/segment/evidence
  derivations; M3 reloadable probe/observation states and authenticated reads.

- Design r2 delta1 REWORK (N1 notes file = new custody, N2 unregistered digest domain, N3 busy not
  distinguishable, N4 HMAC protocol underspecified) → r3 (`613caa59e`) delta2 **ACCEPT_WITH_CONDITIONS**
  (`design-delta2-codex-review.json`; implementation conditions I1 subject/template tests, I2 transport security, …).

## Next step
Implement in order, TDD, each with related tests: C1 subject resolver (`server/services/quality_subjects.py`), C2
embedded host catalog (`r2/quality/host_catalog.py`) + requalification, C3 prepare/submit seal + quality router
(`server/routers/quality.py`), C4 Quality page + Packaging prefill; then Codex review, local Chrome acceptance, sponsor
activated-host qualification + deploy (sudo), then M9-B.
