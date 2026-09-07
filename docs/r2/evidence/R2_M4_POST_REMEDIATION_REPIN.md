# R2-M4 Post-Remediation SHA Re-Pin Handoff

**Status:** HANDOFF SEMANTICS DEFINED / READY FOR CLEAN-HEAD CONSUMPTION

## Authority

- Task-6 authority/path reconciliation amendment SHA-256:
  `98a567508e5474b5c8a3ed11d9e731ca139031ae0d44340f6bb7011432b67b6f`
- Original pinned baseline:
  `1985b815d70dd600519839973b1da20472012d8f`
- Baseline-CI remediation verified head:
  `e72cce2272e1e496a7c8a52df2d3513fd20e815d`
- Task-5 evidence commit observed before this handoff document:
  `06119c22471b3fd6f77344abee251f8ec58c8d25`

External approved authorities verified before this handoff:

```text
2026-09-06-r2-m4-production-intelligence-design-APPROVED.md
SHA-256 7fda57922ea24e4253968818c90995271f86068a22007d4e6d102aeb3f8d3f09

2026-09-07-r2-m4-c04-host-budget-reservation-design-amendment-APPROVED-normalized.md
SHA-256 dc59109c08dc6899a0f9b932acfb14722c787e19fe391a821d688e7b5484b813

2026-09-07-r2-m4-c04-host-budget-reservation-implementation-plan-APPROVED.md
SHA-256 4fa757f1c7e62de3e64cdc8fb81d9372b78d11e52d46a23c9163a70c7a1a9517

2026-09-07-r2-m4-production-intelligence-implementation-plan-APPROVED.md
SHA-256 042a07358d5ef67d3f0e0a34de1787e58b57946f0b7672af978c476a856850a8

R2_M4_VERIFIED_HANDOFF_SHA_SEQUENCE_APPROVED_2026-09-07.md
SHA-256 c566e87eec8bf4276c088ee16ef6a8611b1540341baae6faeb16f39ce1c72178
```

These approved source artifacts were **verified but not materialized into the
remediation worktree**. C04 owns materialization of its design authorities into
its newly pinned implementation worktree.

## Evidence-Driven Pin Semantics

```text
original baseline = 1985b815d70dd600519839973b1da20472012d8f
remediation verified_head = e72cce2272e1e496a7c8a52df2d3513fd20e815d
remediation handoff_head = clean current remediation HEAD read after this document is committed
C04 starting_head = remediation handoff_head
M4 starting_head = clean C04 handoff_head after C04 evidence-only commits
early merge/push required = false
```

The remediation `handoff_head` is intentionally not stored as a self-referential
SHA inside this document before commit.

## Required Lineage

```text
original baseline
  -> remediation verified_head
  -> Task-5 evidence-only commit
  -> Task-6 handoff-semantics-only commit
  -> clean remediation handoff_head
  -> C04 starting_head
  -> C04 implementation / verification
  -> C04 evidence-only handoff_head
  -> M4 starting_head
```

## Post-Verified Allowlist

After this handoff commit, the only paths allowed after
`remediation verified_head` are:

```text
docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.json
docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.md
docs/r2/evidence/R2_M4_POST_REMEDIATION_REPIN.md
```

Any code, config, test, migration, provider-runtime, C04, M4, or M5
implementation change after the remediation verified head invalidates this
handoff and requires a fresh Task-5 verification/evidence cycle.

## Transition Rules

- Do not merge/push merely to start C04.
- C04 reads the clean remediation worktree HEAD directly.
- C04 pins a new implementation worktree to that exact SHA.
- C04 then materializes and verifies its approved design authorities.
- M4 remains blocked until C04 produces a clean evidence-only handoff head.
- R2-HOST-001 / H1 remains OPEN.
- M5 remains out of scope.
