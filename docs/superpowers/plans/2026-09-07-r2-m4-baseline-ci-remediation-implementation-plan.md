# R2-M4 Baseline CI Remediation Implementation Plan v3

**Status:** APPROVED / AUTHORITATIVE

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the exact pinned R2 baseline pass the repository Python CI gates without changing production architecture or weakening frozen R2 contracts.

**Architecture:** Treat this as a behavior-preserving maintenance branch. Fix lint/type/format debt in small reviewable groups, preserve package exports and Pydantic runtime validation semantics, then expand static-analysis coverage to `r2` and rerun all frozen milestone regressions.

**Tech Stack:** Python, Ruff, Ruff formatter, basedpyright, deptry, import-linter, pytest, existing R2 verification scripts.

**Spec:** `docs/superpowers/specs/2026-09-07-r2-m4-baseline-ci-remediation-scope.md`

## Global Constraints

- Starting SHA is exactly `1985b815d70dd600519839973b1da20472012d8f`.
- Branch before worktree creation is `r2/main`; `HEAD == origin/r2/main`; primary worktree must be clean.
- Implement in an isolated worktree/branch `chore/r2-m4-baseline-ci-remediation`.
- Use codebase-memory-MCP first for API/export/impact discovery when available to the chosen implementation executor. If unavailable, use targeted `rg`/reads and record that limitation; no broad architecture redesign is allowed.
- Do not use `ruff --unsafe-fixes`.
- Do not add Ruff `noqa`, ignore, exclude, or baseline suppression merely to clear existing findings.
- Do not weaken contract fields/defaults/validators to satisfy basedpyright.
- No C04/M4 feature implementation in this branch.
- No DB migration.
- No Host runtime/queue behavior change.
- No M5 work and no H1 closure.
- Public exports from `r2.contracts`, `r2.m3`, and `r2.production` remain available.
- `.github/workflows/test.yml`, `CLAUDE.md`, and `pyproject.toml` must converge on deptry scanning `r2`.
- Do not bypass repository hooks with `--no-verify` or `SKIP=...`. The pre-commit Ruff hook may modify staged Python files; after any hook modification, inspect `git diff`, restage, and rerun the task gate before committing.
- Formatting-only changes to Markdown must be followed by frozen-registry verification.
- Commit after every independently reviewable task.
- Do not push until the remediation final gate is PASS and the Human Showrunner approves integration.

---

## Baseline Inventory

Ruff findings by code:

```text
C408     2
E401     1
E701     13
E702     3
F401     26
I001     30
PERF401  2
PT011    1
PT018    2
RUF022   1
RUF059   1
UP017    23
UP035    4
UP037    3
UP042    1
TOTAL    113
```

Reported Ruff source/script files:

- `r2/contracts/__init__.py` — F401×8, I001×1
- `r2/contracts/common.py` — I001×1
- `r2/contracts/factual.py` — I001×1, UP037×2, UP042×1
- `r2/contracts/script.py` — I001×1, UP037×1
- `r2/m3/__init__.py` — F401×17, I001×1
- `r2/m3/composition.py` — I001×1, UP035×1
- `r2/m3/director.py` — E701×2, I001×1
- `r2/m3/factual_fixture.py` — E701×7, E702×2, I001×1
- `r2/m3/golden_a.py` — I001×1, UP017×1, UP035×1
- `r2/m3/host_integration.py` — I001×1, UP035×1
- `r2/m3/local_production.py` — I001×1
- `r2/m3/preparation.py` — UP035×1
- `r2/production/__init__.py` — I001×1, RUF022×1
- `r2/production/artifact_bridge.py` — I001×1
- `scripts/r2/run_m3_golden_a.py` — I001×1
- `scripts/r2/verify_frozen_registries.py` — I001×1, PERF401×1

Reported Ruff test files:

- `tests/integration/r2/m3/test_golden_a_composition.py` — I001×1, UP017×1
- `tests/integration/r2/m3/test_golden_a_end_to_end.py` — I001×1
- `tests/integration/r2/m3/test_host_integration.py` — I001×1, UP017×3
- `tests/integration/r2/production/test_manifest_bridge_integration.py` — I001×1
- `tests/integration/r2/production/test_manifest_recovery_integration.py` — I001×1, RUF059×1, UP017×3
- `tests/integration/r2/production/test_master_promotion_integration.py` — UP017×6
- `tests/unit/r2/contracts/test_architecture_boundaries.py` — E401×1, I001×1, PERF401×1
- `tests/unit/r2/contracts/test_factual.py` — I001×1
- `tests/unit/r2/contracts/test_fingerprints.py` — I001×1
- `tests/unit/r2/contracts/test_provenance.py` — UP017×1
- `tests/unit/r2/contracts/test_results.py` — C408×1, UP017×2
- `tests/unit/r2/contracts/test_roundtrip.py` — UP017×3
- `tests/unit/r2/contracts/test_script.py` — I001×1
- `tests/unit/r2/m3/test_director.py` — E701×4, E702×1, I001×1, PT018×1
- `tests/unit/r2/m3/test_local_production.py` — I001×1, PT018×1
- `tests/unit/r2/production/test_approval_service.py` — C408×1, UP017×2
- `tests/unit/r2/production/test_artifact_metadata.py` — UP017×1
- `tests/unit/r2/production/test_dependency_resolver.py` — PT011×1
- `tests/unit/r2/production/test_host_manifest_r2_extension.py` — I001×1
- `tests/unit/r2/production/test_m2_artifact_bridge_architecture_boundaries.py` — I001×1
- `tests/unit/scripts/r2/test_verify_baseline.py` — I001×1
- `tests/unit/scripts/r2/test_verify_postgres_baseline_script.py` — F401×1, I001×1

Formatter reports exactly 43 files; the complete list is in Appendix A.

Basedpyright reports:

```text
11 errors
2 warnings
```

All reported basedpyright diagnostics are in tests. Current deptry and import-linter gates already pass, but their declared R2 coverage is incomplete.

---

# Task 0: Pin the Remediation Branch and Preserve Evidence

**Files:**
- Create: `docs/r2/evidence/R2_M4_BASELINE_CI_PRE_REMEDIATION.md`
- Create from approved artifact: `docs/superpowers/specs/2026-09-07-r2-m4-baseline-ci-remediation-scope.md`
- Create from approved artifact: `docs/superpowers/plans/2026-09-07-r2-m4-baseline-ci-remediation-implementation-plan.md`

**Interfaces:**
- Produces a clean isolated worktree.
- Records the exact 113/43/11+2 starting failure state.

- [ ] **Step 1: Verify the pinned primary worktree**

```bash
cd ~/content-production-os
git fetch origin r2/main
test "$(git branch --show-current)" = "r2/main"
test "$(git rev-parse HEAD)" = "1985b815d70dd600519839973b1da20472012d8f"
test "$(git rev-parse origin/r2/main)" = "1985b815d70dd600519839973b1da20472012d8f"
test -z "$(git status --short)"
```

Expected: all commands exit 0.

- [ ] **Step 2: Create the isolated worktree**

```bash
git worktree add ../content-production-os-r2-ci \
  -b chore/r2-m4-baseline-ci-remediation \
  1985b815d70dd600519839973b1da20472012d8f
cd ../content-production-os-r2-ci
```

- [ ] **Step 3: Materialize the approved scope and plan**

Copy the Human-approved scope/plan into the exact repository paths listed above. Record their SHA-256 in `R2_M4_BASELINE_CI_PRE_REMEDIATION.md`.

- [ ] **Step 4: Reproduce the failure inventory**

```bash
uv run ruff check . > /tmp/r2-ci-ruff-before.txt 2>&1 || true
uv run ruff format --check . > /tmp/r2-ci-format-before.txt 2>&1 || true
uv run basedpyright --warnings > /tmp/r2-ci-pyright-before.txt 2>&1 || true
uv run deptry lib server alembic scripts tests r2 > /tmp/r2-ci-deptry-before.txt 2>&1
uv run lint-imports > /tmp/r2-ci-imports-before.txt 2>&1
```

Verify the report still represents the same baseline:

```bash
grep -F "Found 113 errors." /tmp/r2-ci-ruff-before.txt
grep -F "43 files would be reformatted" /tmp/r2-ci-format-before.txt
grep -F "11 errors, 2 warnings, 0 notes" /tmp/r2-ci-pyright-before.txt
```

If counts differ on the same SHA, STOP and investigate environment/tool-version drift.

- [ ] **Step 5: Commit evidence only**

```bash
git add \
  docs/superpowers/specs/2026-09-07-r2-m4-baseline-ci-remediation-scope.md \
  docs/superpowers/plans/2026-09-07-r2-m4-baseline-ci-remediation-implementation-plan.md \
  docs/r2/evidence/R2_M4_BASELINE_CI_PRE_REMEDIATION.md
git commit -m "docs(r2): pin baseline CI remediation scope"
```

---

# Task 1: Preserve Public Exports and Clean R2 Production-Source Ruff Findings

**Files:**
- Modify: `r2/contracts/__init__.py`
- Modify: `r2/contracts/common.py`
- Modify: `r2/contracts/factual.py`
- Modify: `r2/contracts/script.py`
- Modify: `r2/m3/__init__.py`
- Modify: `r2/m3/composition.py`
- Modify: `r2/m3/director.py`
- Modify: `r2/m3/factual_fixture.py`
- Modify: `r2/m3/golden_a.py`
- Modify: `r2/m3/host_integration.py`
- Modify: `r2/m3/local_production.py`
- Modify: `r2/m3/preparation.py`
- Modify: `r2/production/__init__.py`
- Modify: `r2/production/artifact_bridge.py`
- Modify: `scripts/r2/run_m3_golden_a.py`
- Modify: `scripts/r2/verify_frozen_registries.py`
- Test: existing `tests/unit/r2/contracts`, `tests/unit/r2/m3`, `tests/unit/r2/production`

**Interfaces:**
- Produces Ruff-clean R2 source/scripts without changing frozen semantics.
- Preserves every existing top-level re-export.

- [ ] **Step 1: Characterize package exports before edits**

```bash
uv run python - <<'PY'
import r2.contracts as c
import r2.m3 as m3
import r2.production as p

required_contracts = {
    "Claim", "ClaimLedger", "ClaimStatus", "EvidenceRecord", "ResearchPack",
    "ScriptArtifact", "ScriptSection", "SceneSpec", "ShotSpec",
}
required_m3 = {
    "GoldenAFactualBundle", "load_golden_a_factual_bundle",
    "FixtureOpenMontageBackend", "GoldenADirectionResult", "GoldenAOpenMontageAdapter",
    "GoldenAMethodAssignment", "GoldenAPreparedShot", "GoldenAProductionPreparation",
    "GoldenALocalProducer", "LocalProducedAsset",
    "GoldenAHostIntegration", "RegisteredGoldenACandidate",
    "GoldenAComposer", "GoldenACompositeAsset", "GoldenARunResult", "GoldenARunner",
}
required_production = {
    "ArcReelArtifactManifestPort", "ProductionApprovalService",
    "ArcReelVersionRestorePromoter",
}
assert all(hasattr(c, name) for name in required_contracts)
assert all(hasattr(m3, name) for name in required_m3)
assert all(hasattr(p, name) for name in required_production)
PY
```

Expected: PASS. Save the required-name sets in the Task-1 commit message/evidence.

- [ ] **Step 2: Fix F401 in package exports without deleting the API**

For `r2/contracts/__init__.py`:
- include the existing imports from `.factual` and `.script` in sorted `__all__`;
- keep those imports;
- sort imports with Ruff.

For `r2/m3/__init__.py`:
- create a sorted explicit `__all__` containing every currently re-exported imported symbol;
- keep every current re-export.

For `r2/production/__init__.py`:
- keep every current export and sort both imports and `__all__`.

Run:

```bash
uv run ruff check   r2/contracts/__init__.py   r2/m3/__init__.py   r2/production/__init__.py
```

Expected: no F401/I001/RUF022 findings.

- [ ] **Step 3: Apply only deterministic non-semantic Ruff modernizations**

Use targeted Ruff fixes, excluding F401 and UP042:

```bash
uv run ruff check --fix   --select I001,E401,UP017,UP035,UP037   r2 scripts/r2
```

Then manually split the reported E701/E702 one-line statements in:
- `r2/m3/director.py`
- `r2/m3/factual_fixture.py`

Convert `PERF401` in `scripts/r2/verify_frozen_registries.py` only if the generated error-list ordering remains identical.

Do not run `--unsafe-fixes`.

- [ ] **Step 4: Resolve `ClaimStatus` UP042 with impact proof**

Before changing `ClaimStatus(str, Enum)`:

```bash
rg -n "str\(ClaimStatus|f["'].*ClaimStatus|format\(.*ClaimStatus" r2 lib server scripts tests || true
```

Also query codebase-memory-MCP for `ClaimStatus` callers when available.

Required result: no production caller depends on legacy enum stringification.

Then change:

```python
from enum import StrEnum


class ClaimStatus(StrEnum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
```

Add/retain tests proving the frozen wire semantics:

```python
assert ClaimStatus.VERIFIED.value == "VERIFIED"
assert ClaimStatus("VERIFIED") is ClaimStatus.VERIFIED
assert Claim(..., status=ClaimStatus.VERIFIED, ...).model_dump(mode="json")["status"] == "VERIFIED"
```

If impact discovery finds a caller that depends on old `str(ClaimStatus.VERIFIED)` output, STOP rather than adding a lint suppression.

- [ ] **Step 5: Run focused source regressions**

```bash
uv run ruff check r2 scripts/r2
uv run python -m pytest -q   tests/unit/r2/contracts   tests/unit/r2/m3   tests/unit/r2/production
```

Expected: Ruff source/scripts clean; tests PASS.

- [ ] **Step 6: Re-run the export characterization**

Run the exact Step-1 script again. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add r2 scripts/r2 tests/unit/r2/contracts/test_factual.py
git commit -m "chore(r2): clear source lint debt without changing contracts"
```

---

# Task 2: Clean Test Ruff Findings and basedpyright Constructor Mismatches

**Files:**
- Modify: `tests/integration/r2/m3/test_golden_a_composition.py`
- Modify: `tests/integration/r2/m3/test_golden_a_end_to_end.py`
- Modify: `tests/integration/r2/m3/test_host_integration.py`
- Modify: `tests/integration/r2/production/test_manifest_bridge_integration.py`
- Modify: `tests/integration/r2/production/test_manifest_recovery_integration.py`
- Modify: `tests/integration/r2/production/test_master_promotion_integration.py`
- Modify: `tests/unit/r2/contracts/test_architecture_boundaries.py`
- Modify: `tests/unit/r2/contracts/test_factual.py`
- Modify: `tests/unit/r2/contracts/test_fingerprints.py`
- Modify: `tests/unit/r2/contracts/test_provenance.py`
- Modify: `tests/unit/r2/contracts/test_results.py`
- Modify: `tests/unit/r2/contracts/test_roundtrip.py`
- Modify: `tests/unit/r2/contracts/test_script.py`
- Modify: `tests/unit/r2/m3/test_director.py`
- Modify: `tests/unit/r2/m3/test_local_production.py`
- Modify: `tests/unit/r2/production/test_approval_service.py`
- Modify: `tests/unit/r2/production/test_artifact_metadata.py`
- Modify: `tests/unit/r2/production/test_dependency_resolver.py`
- Modify: `tests/unit/r2/production/test_host_manifest_r2_extension.py`
- Modify: `tests/unit/r2/production/test_m2_artifact_bridge_architecture_boundaries.py`
- Modify: `tests/unit/scripts/r2/test_verify_baseline.py`
- Modify: `tests/unit/scripts/r2/test_verify_postgres_baseline_script.py`
- No production contract loosening.

**Interfaces:**
- Produces Ruff-clean tests.
- Produces basedpyright-clean tests while preserving the runtime-validation purpose of negative contract tests.

- [ ] **Step 1: Apply deterministic test-only Ruff fixes**

```bash
uv run ruff check --fix   --select I001,E401,UP017,UP035,UP037,C408,RUF022,RUF059   tests/integration/r2 tests/unit/r2 tests/unit/scripts/r2
```

Manually:
- split E701/E702 statements in `tests/unit/r2/m3/test_director.py`;
- split PT018 compound assertions into separate asserts;
- change the PT011 broad `pytest.raises(ValueError)` in `tests/unit/r2/production/test_dependency_resolver.py` to include the exact current message substring produced by `DependencyResolverRegistry.resolve(...)`;
- convert the two reported PERF401 loops only if assertion/list ordering remains unchanged;
- remove the unused `Path` import in `tests/unit/scripts/r2/test_verify_postgres_baseline_script.py`;
- rename the unused `versions` local in `test_manifest_recovery_integration.py` to `_versions` or remove the assignment if only the call side effect is required.

- [ ] **Step 2: Fix negative-field tests using runtime validation, not weaker contracts**

For the basedpyright errors reporting illegal keyword fields (`provider`, `model`, `endpoint`) in:

```text
tests/unit/r2/contracts/test_execution.py
tests/unit/r2/contracts/test_production.py
```

keep the test invalid and replace direct constructor syntax of the form:

```python
with pytest.raises(ValidationError):
    ContractType(..., provider="x")
```

with:

```python
payload = {...existing valid fields..., "provider": "x"}
with pytest.raises(ValidationError):
    ContractType.model_validate(payload)
```

Apply the same transformation for `model` and `endpoint`.

Do not add provider/model/endpoint fields to any stable contract.

- [ ] **Step 3: Preserve before-validator/default-derivation tests**

For basedpyright "Argument missing for parameter `state`" in:

```text
tests/unit/r2/contracts/test_preparation.py
tests/unit/r2/contracts/test_roundtrip.py
```

do not add a fake `state` merely to satisfy the generated constructor signature.

Replace those affected direct constructors with:

```python
ProductionReadiness.model_validate({...the same existing input keys, intentionally omitting "state"...})
```

so the test continues to exercise the runtime derivation/validator path.

- [ ] **Step 4: Fix the dynamic approval enum helper**

In `tests/unit/r2/contracts/test_script.py`, stop iterating over a dynamic `type[Any]` annotation.

Import `CreativeApprovalStatus` directly from `r2.contracts` and make the helper return:

```python
def approval_value() -> CreativeApprovalStatus:
    return CreativeApprovalStatus.APPROVED
```

Keep all existing ScriptArtifact validation assertions unchanged.

- [ ] **Step 5: Preserve artifact-metadata validation semantics**

For the basedpyright missing `content_basis` error in `tests/unit/r2/production/test_artifact_metadata.py`, use:

```python
R2ArtifactMetadata.model_validate({...the exact existing payload keys...})
```

when the test intentionally exercises pre-validation/default/backward-compatible loading.

Do not add a production default or make `content_basis` optional.

- [ ] **Step 6: Run the exact basedpyright target**

```bash
uv run basedpyright --warnings
```

Expected:

```text
0 errors, 0 warnings, 0 notes
```

- [ ] **Step 7: Run test lint + focused tests**

```bash
uv run ruff check tests/integration/r2 tests/unit/r2 tests/unit/scripts/r2
uv run python -m pytest -q   tests/unit/r2   tests/integration/r2
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/integration/r2 tests/unit/r2 tests/unit/scripts/r2
git commit -m "test(r2): make frozen contract tests lint and type clean"
```

---

# Task 3: Format the Exact 43 Reported Files

**Files:**
- Modify: exactly the 43 paths in Appendix A.

**Interfaces:**
- Produces formatter-clean files only.
- No semantic code/document change is accepted in this task.

- [ ] **Step 1: Save pre-format hashes of the four Markdown documents**

```bash
sha256sum \
  docs/r2/R2_07_M0_HOST_FORK_IMPLEMENTATION_PLAN.md \
  docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md \
  docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md \
  docs/superpowers/plans/2026-09-06-r2-m3-golden-a-general-content-implementation-plan.md \
  > /tmp/r2-doc-hashes-before.txt
```bash
sha256sum   docs/r2/R2_07_M0_HOST_FORK_IMPLEMENTATION_PLAN.md   docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md   docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md   docs/superpowers/plans/2026-09-06-r2-m3-golden-a-general-content-implementation-plan.md   > /tmp/r2-doc-hashes-before.txt
```

- [ ] **Step 2: Run Ruff formatter on the exact 43 paths**

```bash
uv run ruff format \
  docs/r2/R2_07_M0_HOST_FORK_IMPLEMENTATION_PLAN.md \
  docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md \
  docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md \
  docs/superpowers/plans/2026-09-06-r2-m3-golden-a-general-content-implementation-plan.md \
  lib/artifact_manifest.py \
  r2/contracts/__init__.py \
  r2/contracts/execution.py \
  r2/contracts/fingerprints.py \
  r2/contracts/preparation.py \
  r2/contracts/script.py \
  r2/m3/composition.py \
  r2/m3/director.py \
  r2/m3/factual_fixture.py \
  r2/m3/golden_a.py \
  r2/m3/host_integration.py \
  r2/m3/local_production.py \
  r2/m3/preparation.py \
  r2/production/approval_service.py \
  r2/production/artifact_bridge.py \
  r2/production/artifact_metadata.py \
  r2/production/dependency_resolver.py \
  scripts/r2/run_m3_golden_a.py \
  scripts/r2/verify_baseline.py \
  scripts/r2/verify_frozen_registries.py \
  tests/integration/r2/m3/test_golden_a_composition.py \
  tests/integration/r2/m3/test_golden_a_end_to_end.py \
  tests/integration/r2/m3/test_host_integration.py \
  tests/integration/r2/production/test_manifest_recovery_integration.py \
  tests/unit/r2/contracts/test_architecture_boundaries.py \
  tests/unit/r2/contracts/test_common.py \
  tests/unit/r2/contracts/test_factual.py \
  tests/unit/r2/contracts/test_fingerprints.py \
  tests/unit/r2/contracts/test_json_value_schema.py \
  tests/unit/r2/contracts/test_results.py \
  tests/unit/r2/contracts/test_script.py \
  tests/unit/r2/m3/test_director.py \
  tests/unit/r2/m3/test_golden_a_preparation.py \
  tests/unit/r2/m3/test_local_production.py \
  tests/unit/r2/production/test_artifact_bridge.py \
  tests/unit/r2/production/test_m2_artifact_bridge_architecture_boundaries.py \
  tests/unit/r2/test_bootstrap.py \
  tests/unit/scripts/r2/test_known_blockers.py \
  tests/unit/scripts/r2/test_verify_frozen_registries.py
```

Do not format unrelated repository files.

- [ ] **Step 3: Verify formatting gate**

```bash
uv run ruff format --check .
```

Expected:

```text
all files already formatted
```

- [ ] **Step 4: Review Markdown-only diffs**

```bash
git diff --   docs/r2/R2_07_M0_HOST_FORK_IMPLEMENTATION_PLAN.md   docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md   docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md   docs/superpowers/plans/2026-09-06-r2-m3-golden-a-general-content-implementation-plan.md
```

Accept only code-block/layout formatting. If prose, decision semantics, hashes, identifiers, commands, or acceptance criteria change, restore that file and STOP to resolve the formatter conflict explicitly.

- [ ] **Step 5: Run frozen registry/baseline verification after doc formatting**

```bash
uv run python scripts/r2/verify_frozen_registries.py
uv run python scripts/r2/verify_baseline.py
```

Expected: both PASS.

- [ ] **Step 6: Run full Ruff gates**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add -- \
  docs/r2/R2_07_M0_HOST_FORK_IMPLEMENTATION_PLAN.md \
  docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md \
  docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md \
  docs/superpowers/plans/2026-09-06-r2-m3-golden-a-general-content-implementation-plan.md \
  lib/artifact_manifest.py \
  r2/contracts/__init__.py \
  r2/contracts/execution.py \
  r2/contracts/fingerprints.py \
  r2/contracts/preparation.py \
  r2/contracts/script.py \
  r2/m3/composition.py \
  r2/m3/director.py \
  r2/m3/factual_fixture.py \
  r2/m3/golden_a.py \
  r2/m3/host_integration.py \
  r2/m3/local_production.py \
  r2/m3/preparation.py \
  r2/production/approval_service.py \
  r2/production/artifact_bridge.py \
  r2/production/artifact_metadata.py \
  r2/production/dependency_resolver.py \
  scripts/r2/run_m3_golden_a.py \
  scripts/r2/verify_baseline.py \
  scripts/r2/verify_frozen_registries.py \
  tests/integration/r2/m3/test_golden_a_composition.py \
  tests/integration/r2/m3/test_golden_a_end_to_end.py \
  tests/integration/r2/m3/test_host_integration.py \
  tests/integration/r2/production/test_manifest_recovery_integration.py \
  tests/unit/r2/contracts/test_architecture_boundaries.py \
  tests/unit/r2/contracts/test_common.py \
  tests/unit/r2/contracts/test_factual.py \
  tests/unit/r2/contracts/test_fingerprints.py \
  tests/unit/r2/contracts/test_json_value_schema.py \
  tests/unit/r2/contracts/test_results.py \
  tests/unit/r2/contracts/test_script.py \
  tests/unit/r2/m3/test_director.py \
  tests/unit/r2/m3/test_golden_a_preparation.py \
  tests/unit/r2/m3/test_local_production.py \
  tests/unit/r2/production/test_artifact_bridge.py \
  tests/unit/r2/production/test_m2_artifact_bridge_architecture_boundaries.py \
  tests/unit/r2/test_bootstrap.py \
  tests/unit/scripts/r2/test_known_blockers.py \
  tests/unit/scripts/r2/test_verify_frozen_registries.py
git commit -m "style(r2): format pinned R2 baseline"
```

---

# Task 4: Expand Static-Analysis Coverage to R2 and Align Real CI

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/test.yml`
- Modify: `CLAUDE.md`

**Interfaces:**
- Produces static-analysis coverage for `r2` in configuration, real CI, and documented local gates.
- Does not add architecture exceptions or suppressions.

- [ ] **Step 1: Pin the existing deptry commands/comment before editing**

```bash
rg -n "deptry|扫描范围与 basedpyright 对齐" \
  pyproject.toml \
  .github/workflows/test.yml \
  CLAUDE.md
```

Record the current lines in the task review note. The expected defect is that CI/CLAUDE.md invoke deptry without `r2`.

- [ ] **Step 2: Expand the declared roots/includes additively**

Preserve all existing config and set:

```toml
[tool.importlinter]
root_packages = ["lib", "r2"]

[tool.basedpyright]
include = ["lib", "server", "alembic", "tests", "scripts", "r2"]

[tool.deptry]
known_first_party = ["lib", "server", "alembic", "scripts", "tests", "r2"]
```

Update the adjacent deptry scan-scope comment so it explicitly states:

```text
扫描范围与 basedpyright 对齐：lib server alembic scripts tests r2
```

Do not alter unrelated tool configuration.

- [ ] **Step 3: Update the actual CI deptry invocation**

In `.github/workflows/test.yml`, replace the existing deptry command with exactly:

```bash
uv run deptry lib server alembic scripts tests r2
```

Do not alter unrelated jobs/steps.

- [ ] **Step 4: Update the documented local gate**

In `CLAUDE.md`, replace the documented deptry command with exactly:

```bash
uv run deptry lib server alembic scripts tests r2
```

Do not change unrelated policy text.

- [ ] **Step 5: Prove all three sources agree**

```bash
rg -n "uv run deptry lib server alembic scripts tests r2|扫描范围与 basedpyright 对齐" \
  pyproject.toml \
  .github/workflows/test.yml \
  CLAUDE.md
```

Expected:
- `test.yml` contains the exact deptry command with `r2`;
- `CLAUDE.md` contains the same command;
- `pyproject.toml` comment includes `r2`.

- [ ] **Step 6: Run all static-analysis gates with R2 visible**

```bash
uv run lint-imports
uv run basedpyright --warnings
uv run deptry lib server alembic scripts tests r2
uv run ruff check .
uv run ruff format --check .
```

Expected: all PASS.

If adding `r2` to basedpyright/import-linter exposes a new diagnostic not present in the captured probe, STOP and record the exact diagnostic before editing additional files.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .github/workflows/test.yml CLAUDE.md
git commit -m "test(r2): align static analysis and CI coverage"
```

After the commit hook returns, run:

```bash
git status --short
git diff HEAD^..HEAD --check
```

Expected: clean worktree and no whitespace errors.

---

# Task 5: Frozen Regression Gate and Remediation Evidence

**Files:**
- Create: `docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.json`
- Create: `docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.md`

**Interfaces:**
- Produces `BASELINE_CI_REMEDIATION = PASS`.
- Produces a committed `verified_head`; C04 later consumes the remediation worktree current `handoff_head` after proving it only adds evidence/handoff documents on top of `verified_head`.

- [ ] **Step 1: Run repo-wide Python quality gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright --warnings
uv run deptry lib server alembic scripts tests r2
uv run lint-imports
```

Required: all exit 0.

- [ ] **Step 2: Run the full repository test suite once**

Because this remediation formats `lib/artifact_manifest.py`, run the repository-wide test gate from `CLAUDE.md`:

```bash
uv run pytest -n 4 --dist loadfile
```

Required: PASS.

Do not replace this with only R2-focused selections.

- [ ] **Step 3: Recover the exact frozen regression selections**

```bash
rg -n "122 PASS|53 PASS|41 PASS|349 PASS|pytest -q|python -m pytest"   docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md   docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md   docs/superpowers/plans/2026-09-06-r2-m3-golden-a-general-content-implementation-plan.md   docs/r2/evidence/R2_M3_FINAL_VERIFICATION.md
```

Copy the exact selections into the remediation Markdown evidence before executing them.

- [ ] **Step 4: Run frozen regressions**

Required exact outcomes:

```text
M3 focused = 122 PASS
M2 frozen  = 53 PASS
M1 frozen  = 41 PASS
Host frozen = 349 PASS
```

If the Host baseline ancestry differs from the pinned lineage, do not assert 349; STOP for explicit re-baselining.

- [ ] **Step 5: Run architecture verification**

```bash
uv run python scripts/audit_tests.py
uv run lint-imports
```

Required: 0 blocking architecture issues.

- [ ] **Step 6: Verify no forbidden scope entered the diff**

```bash
git diff --name-status 1985b815d70dd600519839973b1da20472012d8f...HEAD
git diff --check
```

Required:

```text
no alembic migration
no C04 implementation
no M4 implementation
no provider/runtime feature change
no M5
```

- [ ] **Step 7: Generate deterministic evidence for the tested commit**

Capture the commit that has just passed Steps 1–6:

```bash
REMEDIATION_VERIFIED_HEAD="$(git rev-parse HEAD)"
```

`R2_M4_BASELINE_CI_REMEDIATION.json` minimum structure:

```json
{
  "schema_version": "1",
  "starting_head": "1985b815d70dd600519839973b1da20472012d8f",
  "verified_head": "<REMEDIATION_VERIFIED_HEAD>",
  "ruff_check": "PASS",
  "ruff_format": "PASS",
  "basedpyright": "PASS",
  "deptry": "PASS",
  "import_linter": "PASS",
  "full_pytest": "PASS",
  "m3_pass_count": 122,
  "m2_pass_count": 53,
  "m1_pass_count": 41,
  "host_pass_count": 349,
  "architecture_blocking_violations": 0,
  "db_migrations_added": 0,
  "feature_changes": 0
}
```

`verified_head` is intentionally the already-tested pre-evidence commit. Do **not** attempt to put the SHA of the evidence commit inside the file that creates that commit.

- [ ] **Step 8: Commit evidence**

```bash
git add \
  docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.json \
  docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.md
git commit -m "test(r2): record baseline CI remediation"
```

- [ ] **Step 9: Fresh evidence-commit gate**

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright --warnings
uv run deptry lib server alembic scripts tests r2
uv run lint-imports
git status --short
git rev-parse HEAD
```

Expected: all tools PASS and worktree clean.

Verify the recorded tested commit is an ancestor of the current evidence commit:

```bash
REMEDIATION_VERIFIED_HEAD="$(
  uv run python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.json").read_text())["verified_head"])
PY
)"
git merge-base --is-ancestor "$REMEDIATION_VERIFIED_HEAD" HEAD
```

Expected: exit 0.

Do not push until Human Showrunner reviews the evidence.

---

# Task 6: Post-Remediation SHA Re-Pin Handoff to C04 and M4

**Files:**
- Create: `docs/r2/evidence/R2_M4_POST_REMEDIATION_REPIN.md`
- Read: `docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.json`
- Read/verify approved parent: `docs/superpowers/specs/2026-09-06-r2-m4-production-intelligence-design.md`
- Read/verify review-plan artifacts:
  - `2026-09-07-r2-m4-c04-host-budget-reservation-implementation-plan-v2.3-review.md`
  - `2026-09-07-r2-m4-production-intelligence-implementation-plan-v2.3-review.md`

**Interfaces:**
- Defines `remediation verified_head -> remediation handoff_head -> C04 starting_head`.
- Confirms M4 will later use `C04 handoff_head -> M4 starting_head`.
- Does not require merge/push into `r2/main`.
- Avoids impossible self-referential commit-SHA fields.

- [ ] **Step 1: Read and verify the tested remediation commit**

```bash
REMEDIATION_VERIFIED_HEAD="$(
  uv run python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.json").read_text())
for key in ("ruff_check", "ruff_format", "basedpyright", "deptry", "import_linter", "full_pytest"):
    assert data[key] == "PASS", (key, data[key])
assert data["starting_head"] == "1985b815d70dd600519839973b1da20472012d8f"
print(data["verified_head"])
PY
)"

git merge-base --is-ancestor 1985b815d70dd600519839973b1da20472012d8f "$REMEDIATION_VERIFIED_HEAD"
git merge-base --is-ancestor "$REMEDIATION_VERIFIED_HEAD" HEAD
```

Expected: both exit 0.

- [ ] **Step 2: Prove post-verification commits are evidence/handoff-only**

```bash
git diff --name-only "$REMEDIATION_VERIFIED_HEAD"..HEAD
```

Allowed after `verified_head`:

```text
docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.json
docs/r2/evidence/R2_M4_BASELINE_CI_REMEDIATION.md
docs/r2/evidence/R2_M4_POST_REMEDIATION_REPIN.md
```

If any code/config/test path appears, rerun the full Task-5 gate and create new evidence before handoff.

- [ ] **Step 3: Verify the parent M4 approved artifact**

```bash
echo "7fda57922ea24e4253968818c90995271f86068a22007d4e6d102aeb3f8d3f09  docs/superpowers/specs/2026-09-06-r2-m4-production-intelligence-design.md" | sha256sum -c -
```

Expected: PASS.

- [ ] **Step 4: Document evidence-driven pin semantics**

Write `R2_M4_POST_REMEDIATION_REPIN.md` stating:

```text
original baseline = 1985b815d70dd600519839973b1da20472012d8f
remediation verified_head = value from R2_M4_BASELINE_CI_REMEDIATION.json
remediation handoff_head = clean current HEAD read by C04 consumer
C04 starting_head = remediation handoff_head
M4 starting_head = clean C04 handoff_head after C04 evidence-only commits
early merge/push required = false
```

Do not write a supposed `handoff_head` SHA into the file before committing it.

- [ ] **Step 5: Commit the handoff semantics document**

```bash
git add docs/r2/evidence/R2_M4_POST_REMEDIATION_REPIN.md
git commit -m "docs(r2): define post-remediation SHA handoff"
```

- [ ] **Step 6: Final clean handoff gate**

```bash
test -z "$(git status --short)"
REMEDIATION_HANDOFF_HEAD="$(git rev-parse HEAD)"
git merge-base --is-ancestor "$REMEDIATION_VERIFIED_HEAD" "$REMEDIATION_HANDOFF_HEAD"
printf 'REMEDIATION_HANDOFF_HEAD=%s
' "$REMEDIATION_HANDOFF_HEAD"
```

Expected: PASS.

C04 v2.3 reads `REMEDIATION_HANDOFF_HEAD` directly from this clean remediation worktree and pins its new worktree to that exact SHA.

---

## Stop Conditions

STOP immediately if any cleanup:

```text
changes a provider-neutral contract meaning
changes a frozen field/default/validator to satisfy basedpyright
removes an existing public R2/M3 export
changes content_fingerprint/execution_fingerprint semantics
changes ApprovedMaster promotion behavior
changes Artifact Manifest authority/currency behavior
changes Host queue/runtime behavior
adds a DB migration
adds C04/M4 feature code
requires Ruff ignore/noqa/unsafe-fix to proceed
causes any frozen regression count to drift
changes unrelated CI workflow/CLAUDE.md policy while aligning deptry
reveals new basedpyright errors only after r2 becomes a declared include root
cannot prove remediation verified_head -> remediation handoff_head -> C04 starting_head -> C04 handoff_head -> M4 starting_head sequencing
```

Preserve the worktree and evidence; do not reset/clean destructively.

---

## Acceptance Gate

```text
Ruff findings                  113 -> 0
Formatter debt                 43 files -> 0
basedpyright                   11 errors + 2 warnings -> 0/0
deptry                         PASS and CI/CLAUDE.md scan r2
import-linter                  PASS with r2 declared root
full pytest                    PASS
full pytest -n 4 --dist loadfile PASS

M3                             122 PASS
M2                             53 PASS
M1                             41 PASS
Host                           349 PASS
Architecture blockers         0

DB migrations                  0
C04/M4 feature implementation 0
M5 leakage                     0
H1 change                      0
worktree                       CLEAN
```

When this gate passes, `BLOCKED_BASELINE_CI` is cleared and the workflow returns to approval/execution of the C04 Implementation Plan v2.1.

---

## Appendix A — Exact 43 Ruff-Formatter Paths

- `docs/r2/R2_07_M0_HOST_FORK_IMPLEMENTATION_PLAN.md`
- `docs/superpowers/plans/2026-09-06-r2-m1-contract-kernel-implementation-plan.md`
- `docs/superpowers/plans/2026-09-06-r2-m2-artifact-bridge-implementation-plan.md`
- `docs/superpowers/plans/2026-09-06-r2-m3-golden-a-general-content-implementation-plan.md`
- `lib/artifact_manifest.py`
- `r2/contracts/__init__.py`
- `r2/contracts/execution.py`
- `r2/contracts/fingerprints.py`
- `r2/contracts/preparation.py`
- `r2/contracts/script.py`
- `r2/m3/composition.py`
- `r2/m3/director.py`
- `r2/m3/factual_fixture.py`
- `r2/m3/golden_a.py`
- `r2/m3/host_integration.py`
- `r2/m3/local_production.py`
- `r2/m3/preparation.py`
- `r2/production/approval_service.py`
- `r2/production/artifact_bridge.py`
- `r2/production/artifact_metadata.py`
- `r2/production/dependency_resolver.py`
- `scripts/r2/run_m3_golden_a.py`
- `scripts/r2/verify_baseline.py`
- `scripts/r2/verify_frozen_registries.py`
- `tests/integration/r2/m3/test_golden_a_composition.py`
- `tests/integration/r2/m3/test_golden_a_end_to_end.py`
- `tests/integration/r2/m3/test_host_integration.py`
- `tests/integration/r2/production/test_manifest_recovery_integration.py`
- `tests/unit/r2/contracts/test_architecture_boundaries.py`
- `tests/unit/r2/contracts/test_common.py`
- `tests/unit/r2/contracts/test_factual.py`
- `tests/unit/r2/contracts/test_fingerprints.py`
- `tests/unit/r2/contracts/test_json_value_schema.py`
- `tests/unit/r2/contracts/test_results.py`
- `tests/unit/r2/contracts/test_script.py`
- `tests/unit/r2/m3/test_director.py`
- `tests/unit/r2/m3/test_golden_a_preparation.py`
- `tests/unit/r2/m3/test_local_production.py`
- `tests/unit/r2/production/test_artifact_bridge.py`
- `tests/unit/r2/production/test_m2_artifact_bridge_architecture_boundaries.py`
- `tests/unit/r2/test_bootstrap.py`
- `tests/unit/scripts/r2/test_known_blockers.py`
- `tests/unit/scripts/r2/test_verify_frozen_registries.py`