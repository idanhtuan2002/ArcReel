# R2-M4 Baseline CI Remediation — Task 2 Evidence Reconciliation Amendment

**Date:** 2026-09-07
**Status:** APPROVED / AUTHORITATIVE
**Parent plan:** `2026-09-07-r2-m4-baseline-ci-remediation-implementation-plan-APPROVED.md`
**Parent Task-1 handoff HEAD:** `ba5082f3310b6f1a64c3837386f5526cde9b5275`
**Change class:** evidence reconciliation only
**Architecture change:** NONE
**Production-contract change:** NONE
**C04/M4 scope change:** NONE

## 1. Trigger

Task 2A read-only discovery was executed on the clean remediation worktree at:

```text
branch = chore/r2-m4-baseline-ci-remediation
HEAD   = ba5082f3310b6f1a64c3837386f5526cde9b5275
```

Current basedpyright result remains:

```text
11 errors, 2 warnings, 0 notes
```

However, the approved plan's earlier G5 correction stated that
`tests/unit/r2/contracts/test_common.py` was formatter-only and should not be
included in the illegal-field basedpyright group.

Fresh execution evidence disproves that statement:

```text
tests/unit/r2/contracts/test_common.py:39:13
error: No parameter named "provider" (reportCallIssue)
```

## 2. Amendment

Replace the prior G5 assumption with:

```text
G5-RECONCILED

Illegal provider/model/endpoint field tests requiring runtime-validation style:

- tests/unit/r2/contracts/test_common.py
- tests/unit/r2/contracts/test_execution.py
- tests/unit/r2/contracts/test_production.py
```

`test_common.py` is therefore in Task 2 semantic test-remediation scope.

## 3. Required implementation behavior

The `test_common.py` negative test MUST preserve the production contract and test
the same runtime rejection semantics.

Do NOT:
- add `provider` to `ContractIdentity`;
- weaken `extra="forbid"` behavior;
- add `# type: ignore`, `pyright: ignore`, `noqa`, or configuration suppression.

Use runtime validation instead of an invalid statically typed constructor call,
equivalent to:

```python
with pytest.raises(ValidationError):
    ContractIdentity.model_validate(
        {
            "id": "SH042",
            "schema_version": "2.1",
            "version": 1,
            "provider": "seedance",
        }
    )
```

The same rule remains applicable to the already-approved negative-field tests in
`test_execution.py` and `test_production.py`.

## 4. Other Task 2 evidence confirmed

Task 2A currently reports:

```text
basedpyright: 11 errors, 2 warnings
test Ruff:    50 findings
```

Other approved correction strategies remain unchanged:

- missing derived `ProductionReadiness.state` constructor cases:
  use `ProductionReadiness.model_validate(...)`; do not add fake state;
- `test_roundtrip.py` missing state:
  use runtime validation path;
- `test_script.py` dynamic `type[Any]` iteration:
  use `CreativeApprovalStatus` directly;
- `test_artifact_metadata.py` missing `content_basis` negative test:
  use `R2ArtifactMetadata.model_validate(...)`; do not make `content_basis` optional;
- unused `versions`:
  rename to an underscore-prefixed binding;
- unused `Path`:
  remove the import;
- Ruff test debt:
  safe fixes/manual rewrites only; no unsafe fixes or suppressions.

## 5. Acceptance criteria for this amendment

After Task 2 implementation:

```text
uv run basedpyright --warnings      PASS: 0 errors, 0 warnings
test-scope Ruff                     PASS
affected tests                      PASS
production contracts               unchanged
architecture                        unchanged
```

The existing downstream execution order remains:

```text
Task 2
→ Task 3 exact formatter inventory
→ Task 4 static-analysis / CI alignment
→ Task 5 full/frozen gates
→ remediation verified_head / handoff_head
→ C04
→ M4
```

## 6. Approval consequence

Approval of this amendment authorizes Task 2B to modify
`tests/unit/r2/contracts/test_common.py` only in the behavior-preserving
runtime-validation manner described above.

All other approved remediation constraints remain in force.
