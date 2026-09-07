# R2-M4 Baseline CI Pre-Remediation Evidence

**Generated:** 2026-09-07T09:35:40+07:00
**Branch:** chore/r2-m4-baseline-ci-remediation
**Starting HEAD:** 1985b815d70dd600519839973b1da20472012d8f
**Primary branch:** r2/main
**Primary local/remote equality:** PASS
**Primary worktree clean:** PASS
**Baseline measurement checkout:** primary pinned checkout /home/anhtuan/content-production-os

## Approved artifacts

```text
scope_original_approved_sha256 = 107ba5ebe5d8efd779b4e1432130b82f1972c4f273305ae53a8020d6c1d6ec1f
scope_normalized_approved_sha256 = e63608ec6c3ef1235f91538b446956a29b8aa7d7bcfba54d7fc4177ae6acdb23
plan_sha256                      = 72248b01ca76e9b809ef8297e68fb443474ee12939a53ef1144cce2531986334
```

## Reproduced baseline

```text
ruff check .                  FAIL — 113 findings
ruff format --check .         FAIL — 43 files
basedpyright --warnings       FAIL — 11 errors, 2 warnings
deptry ... r2                 PASS
lint-imports                  PASS — 2 kept, 0 broken
```

## Raw reports

```text
/tmp/r2-ci-ruff-before.txt
/tmp/r2-ci-format-before.txt
/tmp/r2-ci-pyright-before.txt
/tmp/r2-ci-deptry-before.txt
/tmp/r2-ci-imports-before.txt
```

## Scope

Evidence only. No remediation source/config/test changes have been made.
