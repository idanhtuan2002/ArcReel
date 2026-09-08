# R2-M4 Implementation Seam Map

**Task 0 deliverable.** Produced before any M4 production code.
**Date:** 2026-09-07. **Plan:** R2-M4 Production Intelligence Implementation Plan v2.4 (APPROVED).

---

## 1. Baseline pin and SHA chain

`M4_STARTING_HEAD = 863ab4993b3dce725fb5f12b5d2f2a74a79031a3`
(`feat/r2-m4-c04-budget` tip == C04 clean `handoff_head`).

Worktree: `/home/anhtuan/content-production-os-m4`, branch `feat/r2-m4-production-intelligence`,
created from `M4_STARTING_HEAD`.

Chain proven from `r2/main` history (all five are ancestors of `r2/main`):

| Link | SHA | Check |
|---|---|---|
| Original R2 baseline | `1985b815d70dd600519839973b1da20472012d8f` | `remediation.starting_head` == this |
| Remediation `verified_head` | `e72cce2272e1e496a7c8a52df2d3513fd20e815d` | ancestor of `521aad2f`; diff to `521aad2f` = evidence docs only |
| Remediation `handoff_head` == C04 `starting_head` | `521aad2f83a19bdb03219923b6bd2268a338f617` | `c04.starting_head` == `c04.remediation_handoff_head` |
| C04 `verified_head` | `ef47f99c620029023a9f866bc8c505f13ccf0db8` | ancestor of `863ab499`; diff to `863ab499` = `R2_M4_C04_EVIDENCE.json` + `R2_M4_C04_FINAL_VERIFICATION.md` only |
| C04 `handoff_head` == `M4_STARTING_HEAD` | `863ab4993b3dce725fb5f12b5d2f2a74a79031a3` | C04 `c04_status = READY`, `h1_status = OPEN` |

### Topology deviation from plan Task 0 Step 1

The plan reads the two producer worktrees (`~/content-production-os-r2-ci`,
`~/content-production-os-m4-c04`) directly. In this session those worktrees and
their branches (`chore/r2-m4-baseline-ci-remediation`, `feat/r2-m4-c04-budget`)
were removed **after** C04 was merged (`--no-ff`) and pushed to `origin/r2/main`
(`9d5e6a39`). The SHA chain, the two evidence JSONs
(`R2_M4_BASELINE_CI_REMEDIATION.json`, `R2_M4_C04_EVIDENCE.json`), and all
`pyproject.toml` R2 coverage are preserved on `r2/main`, so every Task 0
assertion was re-run against `r2/main` history instead of the deleted worktrees.
Human Showrunner approved this adaptation and `M4_STARTING_HEAD = 863ab499`.
`863ab499` does **not** contain the merge commit or the two `r2/main` docs-only
commits, so the M4 change-scope diff stays pristine for the Task 11/12
architecture audit.

---

## 2. Preflight (run at `M4_STARTING_HEAD`)

| Check | Result |
|---|---|
| `ruff check .` | exit 0 |
| `ruff format --check .` | exit 0 (1654 files) |
| `basedpyright --warnings` | 0 errors / 0 warnings / 0 notes |
| `deptry lib server alembic scripts tests r2` | exit 0 |
| `lint-imports` | 3 kept / 0 broken |
| `alembic heads` | `c04b7d93e5a1 (head)` — single head, no extra migration |
| `git diff --name-only M4_STARTING_HEAD...HEAD` | empty |

R2 static-analysis coverage confirmed in `pyproject.toml`:
- `[tool.importlinter].root_packages = ["lib", "r2"]`
- `[tool.basedpyright].include` contains `r2`
- `[tool.deptry].known_first_party` contains `r2`

---

## 3. Contracts M4 Task 1 extends (current shape)

| Contract | File · lines | Base | Notes for M4 |
|---|---|---|---|
| `MethodDecision` | `r2/contracts/execution.py:17-25` | `R2ContractModel` | `method: ProductionMethod`, `capability_requirements: list[str]`, `cost_class`, `quality_tier>=0`, `fallback_methods`. No provider/model fields. |
| `PromptPlan` | `execution.py:28-37` | `ContractIdentity` | `semantic_instruction`, positive/negative prompt, identity/style tokens, `reference_binding_ids`, `exclusions`, `compiler_version`. Neutral. |
| `ProviderRequest` | `execution.py:40-57` | `R2ContractModel` | **execution-side**: `provider`, `model`, `endpoint`, `payload: dict[str,JSONValue]`, `execution_options`, `adapter_version`. This is where provider identity is allowed. |
| `ProductionBinding` | `r2/contracts/preparation.py:15-28` | `ContractIdentity` | owner of `asset_refs` (sorted-unique), `role: ProductionBindingRole`, `variant_ref`, `state_ref`. |
| `VisualIdentityProfile` | `preparation.py:31-45` | `ContractIdentity` | `semantic_character_ref`, face/body/side masters, hairstyle/costume/accessory locks, `state_variants`, `approved_reference_refs`. |
| `ReadinessRequirement` | `preparation.py:48-60` | `R2ContractModel` | `required` READY ⇒ must carry `resolved_binding`. |
| `ProductionReadiness` | `preparation.py:85-113` | `R2ContractModel` | `state` is **derived** in a `model_validator(mode="before")` from requirements; supplying a contradicting `state` raises. Any required non-READY ⇒ `BLOCKED`. |
| `SceneSpec` / `ShotSpec` | `r2/contracts/production.py:12-33 / 36-60` | `R2ContractModel` | carry `content_basis`, `allowed_methods`, `approval_status`. No provider/model/endpoint/payload. |
| `GenerationCandidate` (R2) | `r2/contracts/results.py:11-34` | `R2ContractModel` | `content_fingerprint` + `execution_fingerprint` both required; FAILED cannot be SELECTED. |
| `ApprovedMaster` (R2) | `results.py:37-43` | `R2ContractModel` | `selected_candidate_id`, `approval_record`, `selected_at` (aware), `selected_by`. |
| `QualityReport` / `QualityFinding` | `results.py:46-68` | | blocking/advisory finding planes validated disjoint. |
| Enums | `r2/contracts/enums.py` | `StrEnum` | `ProductionMethod` = REUSE/STOCK/SCREEN_CAPTURE/DETERMINISTIC/GENERATED_IMAGE/GENERATED_VIDEO/COMPOSITE (matches 12-shot fixture). `ReadinessState` = READY/BLOCKED only. `ProductionBindingRole` has SOURCE_FOOTAGE/OPENING_FRAME/ENDING_FRAME/PREVIOUS_SHOT. |

`r2/contracts/__init__.py` re-exports every contract + `canonical_json_bytes`,
`compute_content_fingerprint`, `compute_execution_fingerprint` (Task 1 must keep
`__all__` and imports in sync when adding `director.py` / `capabilities.py` /
`observability.py`).

### Fingerprint seam

`r2/contracts/fingerprints.py`:
- `compute_content_fingerprint(*, shot_spec, bindings, visual_identity_refs, approved_source_asset_refs) -> str`
- `compute_execution_fingerprint(*, provider, model, endpoint, seed, resolution, generation_settings, prompt_compiler_version, provider_adapter_version) -> str`

Non-test callers today: `r2/m3/golden_a.py:237,284` (via `r2.m3.host_integration`
re-export). **Name collision:** `r2/m3/host_integration.py:54-74` defines its own
`compute_content_fingerprint` — M3-local, different signature. M4 must use the
`r2.contracts.fingerprints` one and not cross-wire.

---

## 4. Seams M4 consumes (reuse, do not reimplement)

| Seam | File | Surface | Consumer task | Current runtime fan-in |
|---|---|---|---|---|
| C04 budget port | `r2/production/budget_port.py` | `BudgetAuthorizationPort` Protocol (`reserve`, `release_pre_submit`); `HostBudgetAuthority` Protocol; `ArcReelBudgetAuthorizationAdapter` (injects clock) | Task 6 admission, Task 10 host integ | 0 — M4 admission is first consumer |
| Paid-submission guard | `server/services/paid_submission_guard.py` | `submit_with_budget_guard[T](*, reservation_service, reservation_ref, execution_decision_ref, submit, now)` — claim-then-`submit()`, **never releases after `submit()` starts**; `SupportsClaimForSubmission.claim_for_submission` | Task 10 | 0 — M4 Task 10 is first runtime caller |
| Approved-master promotion | `r2/production/approval_service.py` | `ProductionApprovalService.promote(*, artifact_key, candidate, host_version_ref, approval_record, selected_by, selected_at) -> PromotionResult`; validates candidate GENERATED, not REJECTED, `target_ref` + `content_fingerprint` match current metadata; idempotent on same candidate+version | Task 10 (no master store) | 8 |
| Artifact manifest bridge | `r2/production/artifact_bridge.py` | `ArtifactManifestPort` Protocol (`load_artifact`, `write_r2_metadata`, `promote_version_with_r2_metadata`); `ArcReelArtifactManifestPort`; `R2ArtifactBridge.evaluate_currency`; `ArcReelVersionRestorePromoter` (host_version_ref = canonical positive decimal) | Task 10 currency/fingerprint | 6 |
| M3 Director adapter | `r2/m3/director.py` | `GoldenAOpenMontageAdapter.direct(script: ScriptArtifact) -> GoldenADirectionResult`; `GoldenAOpenMontageBackend` / `FixtureOpenMontageBackend` Protocols | Task 2 Step 3 — **wrap behind generic `DirectorAdapter`, do not modify M3** | 8 |
| M3 preparation | `r2/m3/preparation.py` | `GoldenAProductionPreparation` (`39-120`) | Task 3 regression target | 7 |
| Host task executor | `server/services/generation_tasks.py` | `execute_generation_task` (`~3537-3599`, fan-in/out 12) | Task 10 — modify **only** to route M4-marked paid submissions through the C04 guard; no queue/state-machine redesign | 12 |

---

## 5. Blast radius / regression targets

- **Task 1** extends `MethodDecision`, `PromptPlan`, `ProductionReadiness` and adds
  `r2/contracts/{director,capabilities,observability}.py` → regress
  `tests/unit/r2/contracts`, `tests/unit/r2/m3/test_director.py`,
  `tests/unit/r2/m3/test_preparation.py` and keep M1/M2/M3 round-trip behaviour.
  If an approved M4 field forces a breaking reinterpretation of a frozen M1
  contract (not additive/default-compatible) → **STOP** with contract evidence.
- **`GenerationCandidate` collision**: R2 contract `r2.contracts.results.GenerationCandidate`
  vs Host `lib.generation_result.GenerationCandidate` (`lib/generation_result.py:374-379`,
  fan-in 19). Task 10 `M4HostIntegration.execute_admitted(...) -> GenerationCandidate`
  must state which type crosses the boundary.
- **Frozen-count drift to resolve at Gate C (Task 12), not now:** plan Global
  Constraints freeze `M3 122 / M2 53 / M1 41 / Host 349`. Post-remediation C04
  evidence already records `frozen_m1_contracts_dir: 50 PASS` and
  `frozen_m3_r2_suite_subset: 125 PASS` for directory-level runs. The frozen
  numbers are **node-id selections**, not directory globs — Task 12 Step 4 must
  recover the exact per-milestone selection commands from the committed
  M1/M2/M3 plans and `R2_M3_FINAL_VERIFICATION.md`, then run those, not
  approximate directory runs.
- **Host baseline ancestry:** `verify_baseline.py` PASS at
  `tag=v0.29.0 sha=6ddedc77…`. The C04 merge combined two branches both rooted at
  that pin and did **not** pull `upstream/main`; Host baseline lineage unchanged.

---

## 6. Invariants carried into M4 (unchanged)

- H1 / `R2-HOST-001` remains **OPEN**.
- C04 is the only approved Host runtime/DB extension. Any further Host runtime
  change or migration is a STOP condition.
- Method before provider/model/tool. `SceneSpec`/`ShotSpec`/`MethodDecision`/
  `PromptPlan`/VisualIdentity stay provider-neutral. Provider identity only in
  `ExecutionDecision`/`ProviderRequest` and execution-side descriptors.
- No second artifact registry, queue, currency engine, cost ledger, or master store.
- `GenerationCandidate != ApprovedMaster`; failed regeneration preserves the master.
