# R2-M4 Baseline CI Remediation Evidence

**Status:** VERIFIED / PASS

## Authority

- Task-5 selector reconciliation amendment SHA-256:
  `11d248e50e42a7236f56d9d9527a92f9cf69e7526a6cef8fcc3ff44c73beaa93`
- Task-5 M3 frozen node-ID reconciliation amendment SHA-256:
  `64713e5d5b5531bd301da43ff091e0e778510060110415142c6246808b061096`
- Historical M3 Task-9 package SHA-256:
  `0dc3aa4cfbbd21deb4ffe7479539115dda36670972e5d982f574d4920c09ba82`
- Historical M3 Task-9 runner SHA-256:
  `f41e4cf2fdd3ddd1c1b0d5ca7f71a70a3a271be7da29dce129162600238882a6`

## Baseline and Tested Commit

- Starting head: `1985b815d70dd600519839973b1da20472012d8f`
- Verified head: `e72cce2272e1e496a7c8a52df2d3513fd20e815d`
- Branch: `chore/r2-m4-baseline-ci-remediation`
- Frozen M2 corpus commit: `9cc04edd`
- Frozen M1 corpus commit: `9330bcf3`

`verified_head` is the pre-evidence commit that passed every Task-5 gate.

## Current vs Frozen M3

Current integrated M3 corpus:

```text
123 PASS
```

The one current-only node compared with pinned M3 baseline is:

`tests/unit/r2/contracts/test_factual.py::test_claim_status_wire_semantics_are_stable`

This remediation characterization test remains active in both the current M3
integrated run and the full repository suite.

Frozen M3 corpus:

```text
122 node IDs recovered from pinned baseline 1985b815d70dd600519839973b1da20472012d8f
122 PASS on current implementation
0 frozen node IDs missing
```

The frozen count was **not** rebaselined to 123.

## Other Frozen Regressions

```text
M2 frozen   53 PASS
M1 frozen   41 PASS
Host frozen 349 PASS
```

M2 and M1 corpora were reconstructed from their historical commits. Host 349 was
asserted only after pinned-lineage eligibility was revalidated.

## Task-5 Gate Results

```text
ruff check                              PASS
ruff format --check                     PASS
basedpyright --warnings                 PASS
deptry lib server alembic scripts tests r2
                                        PASS
lint-imports                            PASS
full current repository pytest          PASS
current integrated M3                   123 PASS
frozen M3                               122 PASS
frozen M2                                53 PASS
frozen M1                                41 PASS
frozen Host                             349 PASS
frozen registries                       PASS
primary pinned baseline verifier        PASS
architecture blocking violations        0
DB migrations added/changed             0
C04 implementation changes              0
M4 implementation changes               0
M5 implementation changes               0
provider/runtime feature changes        0
```

## Handoff Semantics

```text
verified_head = e72cce2272e1e496a7c8a52df2d3513fd20e815d
```

Task 6 must compute the actual clean `handoff_head` after evidence/handoff-only
commits and prove that every path after `verified_head` is evidence/handoff-only
before C04 starts.

No push or merge is authorized by this evidence.
