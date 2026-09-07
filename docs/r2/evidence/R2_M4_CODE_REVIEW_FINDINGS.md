# R2-M4 Code Review Findings (Codex adversarial review, 2026-09-07)

Adversarial review of the M4 implementation (branch `feat/r2-m4-production-intelligence`,
reviewed at `61eec783`) against the APPROVED plan and design spec D01–D12 / C01–C10.
Codex session `01a07c7a-870d-77b3-9022-fdd95d5ad643`. Findings verified against source
by Claude before triage.

## Status legend

- **FIXED** — addressed in this session.
- **DEFERRED** — real gap, scoped for a follow-up session with its own review.
- **NOT REPRODUCED** — could not confirm in this environment.

---

## FIXED this session

### Crit-1 — Gate D evidence tooling is fail-open; C08 schema incomplete
- **Where:** `scripts/r2/verify_m4.py`, `scripts/r2/run_m4_golden_12.py`,
  `docs/r2/evidence/r2_m4_evidence.json`, `docs/r2/evidence/R2_M4_FINAL_VERIFICATION.md`.
- **Spec:** design §18.11 (C08 schema), C09 (§1908 — required items PASS or gate not PASS),
  plan §1663–1674 (rerun after evidence commit, clean final gate).
- **Was:** `verify_m4.main()` returned 0 unconditionally; `run_m4_golden_12.main()`
  returned 0 for `INCOMPLETE_PENDING_WAIVER`; evidence recorded a stale `final_head`,
  `worktree_clean=false`, `approved_waivers=[]`; `fault_overlays` was a hard-coded
  `"8/8"` string; missing `implementation_plan_ref`, `environment_summary`,
  `gate_results`, structured per-shot golden rows, per-mutation observed outcomes,
  and artifact/attempt/cost refs.
- **Fix:** `verify_m4` now fails closed (non-zero) when the tree is dirty, HEAD ≠
  `--expected-head`, any frozen suite is not exactly `expected` with 0 fail / 0 skip,
  architecture blocking > 0, the golden baseline is not 12/12, or the real-evidence
  result is neither `PASS` nor covered by a recorded `approved_waivers` entry.
  `run_m4_golden_12` returns non-zero unless the result is exactly `PASS`. The
  evidence JSON now carries the C08 fields, structured `golden_baseline[]` /
  `fault_overlays[]` rows sourced from an actual pytest run, and
  `real_execution_evidence[]` with ref slots.

### Med-5 — MUT-05/06/07 oracles were circular or disconnected
- **Where:** `tests/integration/r2/m4/test_golden_12_mutations.py`.
- **Was:** MUT-06 computed `content_a` and `content_b` from identical arguments
  (tautology); MUT-05 invented an alternate descriptor absent from any resolution;
  MUT-07 asserted the double's own hard-coded cost string and hand-built the
  failure/telemetry objects instead of running `M4HostIntegration`.
- **Fix:** MUT-06 now proves `compute_content_fingerprint` structurally does not
  accept execution config and that only `execution_fingerprint` moves on a seed
  change. MUT-05 registers a real alternate descriptor, runs a second
  `CapabilityMatcher.resolve`, and builds the fallback ED from an actually
  eligible candidate. MUT-07 runs `M4HostIntegration.execute_admitted` with a
  `ControlledExecutionDouble(CHARGE_THEN_FAIL)` submitter and asserts the FAILED
  candidate plus `integration.cost_records`.

### Med-6 — frozen-regression recovery not fully recorded; verifier ignored skips
- **Where:** `scripts/r2/verify_m4.py`, `docs/r2/evidence/frozen_selections/`.
- **Fix:** verifier rejects a frozen suite with `skip_count > 0`;
  `frozen_selections/recovery_log.txt` records the exact `pytest --co` recovery
  commands, source commits, and the raw run tails at the M4 final head.

### Low-1 — architecture-audit "unit" test launched a subprocess
- **Where:** was `tests/unit/r2/production_intelligence/test_architecture_audit.py`.
- **Spec:** `CONTRIBUTING.md:87` — the `unit` tier forbids subprocesses.
- **Fix:** moved to `tests/integration/r2/m4/test_m4_architecture_audit.py`.

---

## DEFERRED — next session (own review + scope)

### Crit-2 — Gate 2 can admit an unavailable or wrong-type capability
- **Where:** `r2/production_intelligence/capability_registry.py` (`CapabilityMatcher.resolve`),
  `r2/production_intelligence/admission.py` (`GenerationAdmissionService.evaluate`).
- **Spec:** C03 (§754–779) — credentials / endpoint health / runtime deps / local
  resource fit / applicable quota are HARD_DYNAMIC; Gate 2 MUST synchronously
  revalidate the selected candidate's hard-dynamic predicates immediately before
  `ADMITTED`, or take an equivalent freshness proof.
- **Gap:** the matcher never reads `credentials_ready`, `endpoint_healthy`,
  `runtime_dependencies_ready`; never checks `CapabilityRequirements.required_execution_types`
  against `descriptor.execution_type`; resource-fit / quota observations are
  optional. `admission.evaluate` has no revalidation step and trusts the caller
  booleans `readiness_is_current=True` / `policy_ok=True`.
- **Direction:** make credentials/endpoint/runtime hard predicates mandatory for a
  hard requirement; enforce `required_execution_types`; add a synchronous
  revalidation hook (or required freshness-proof argument) to admission for the
  selected candidate before `ADMITTED`.
- **FIXED (next-session batch):** `CapabilityMatcher.resolve` now treats
  `credentials_ready` / `endpoint_healthy` / `runtime_dependencies_ready` on the
  availability observation as hard predicates — `False` rejects with a specific
  reason, unobserved (`None`) is UNKNOWN and ineligible — and rejects a candidate
  whose `descriptor.execution_type` is outside a non-empty
  `requirements.required_execution_types` (`EXECUTION_TYPE_DISALLOWED`).
  `GenerationAdmissionService.evaluate` gains a required `revalidate:
  HardDynamicRevalidator` awaited on the top-ranked eligible candidate
  immediately before the reservation; a non-`ok` result is
  `DENIED_UNAVAILABLE` / `HARD_DYNAMIC_REVALIDATION_FAILED` and reserves nothing.
  The golden runner supplies a real re-`resolve` revalidator; the golden
  observation now carries the three predicates.

### High-1 — ExecutionDecision does not lock the selected capability/provider
- **Where:** `r2/production_intelligence/execution.py` (`ExecutionDecisionService.create`),
  `r2/production_intelligence/host_integration.py`.
- **Spec:** §947–949 (attempt choice is locked), §1075–1084 (same-method provider
  fallback requires fresh capability + admission evaluation).
- **Gap:** `create()` does not require `selected_capability_id ∈
  capability_resolution.eligible_candidates`, nor `descriptor.capability_id ==
  selected_capability_id`, nor coherence of `admission` / `capability_resolution` /
  `prompt_plan` refs and targets. `M4HostIntegration` accepts a `ProviderRequest`
  whose provider/model differs from the `ExecutionDecision` without checking.
- **Direction:** validate candidate membership + descriptor identity + ref/target
  coherence in `create()`; in host integration assert `request.provider ==
  decision.provider_id` and `request.model == decision.model_or_tool_id`.
- **FIXED (next-session batch):** `ExecutionDecisionService.create` now rejects
  (`ValueError`) a `selected_capability_id` outside
  `capability_resolution.eligible_candidates`, a `descriptor.capability_id` that
  is not the selected one, and an `admission` whose `capability_resolution_ref` /
  `prompt_plan_ref` / `target_ref` disagree with the resolution / plan it is
  handed. `M4HostIntegration.execute_admitted` asserts `request.provider ==
  decision.provider_id` and `request.model == decision.model_or_tool_id` before
  any submit. 5 + 2 new tests.

### High-3 — a pre-built DirectorSuccess bypasses D03 validation
- **Where:** `r2/production_intelligence/director.py` (`DirectorValidator.normalize`).
- **Spec:** §322–330 — every success needs contract + semantic validation; malformed
  output must not masquerade as normalized contracts.
- **Gap:** `normalize()` returns any `DirectorSuccess`/`DirectorFailure` immediately
  without re-checking routing ref, actual director, non-empty shots, or shot→scene
  linkage.
- **Direction:** always re-run the semantic checks; for an incoming `DirectorSuccess`
  re-validate its scenes/shots and refs; only pass a `DirectorFailure` through.
- **FIXED (next-session batch):** `normalize` now passes only a `DirectorFailure`
  through verbatim. A `DirectorSuccess` (adapter-built or raw-payload-derived)
  goes through the shared `_validate_success`: routing-ref match, `actual_director`
  == attempted, non-empty shots, every `shot.scene_id` present in `scenes`. 4 new
  rejection tests + a coherent-passthrough + a `DirectorFailure`-passthrough guard.

### High-4 — Golden-12 is answer-fed; no Quality Ladder
- **Where:** `r2/production_intelligence/fixtures/m4_golden_12_shots.json`,
  `r2/production_intelligence/fixture_loader.py`.
- **Spec:** D09 §17.2 (each shot's architecture purpose), C05 §17.3.1 (SH05/06/07
  local / cheap-cloud / premium-cloud escalation with cost / latency / availability
  / identity-stability / retry dimensions).
- **Gap:** the loader sets `allowed_methods=(expected_method,)` on the scene, shot
  and router context, and synthesizes exactly one descriptor supporting only that
  method — no competing route exists, so `12/12` only proves deterministic
  plumbing. No tier comparison, no C05 dimensions.
- **Direction:** give each shot multiple `allowed_methods` plus the conditions that
  make the *expected* one win (e.g. SH02 with a synthetic alternative it must
  outrank); add SH05/06/07 tier doubles and assert MethodDecision stable while
  ExecutionDecision + execution_fingerprint move.

### High-5 — architecture fitness sensors are name-based, not semantic
- **Where:** `scripts/r2/audit_m4_architecture.py`,
  `tests/unit/r2/production_intelligence/test_architecture_boundaries.py`.
- **Spec:** D12 §1618–1668.
- **Gaps:** `paid_submission_guard.py` is "approved" by filename alone (a semantic
  rewrite still yields 0 violations); the AST scan globs `production_intelligence/*.py`
  non-recursively; the forbidden-field set is 7 literal names (`backend_id`,
  `vendor_options`, nested provider config pass); the mutation-word list is 6 words
  (`persist()` passes); the second-subsystem scan is a class-name substring match
  (`DispatchBuffer` passes).
- **Direction:** hash/AST-diff the approved C04 host files instead of trusting the
  path; recurse the AST scan; check field *values* and nested models for provider
  syntax; assert telemetry/​projector classes expose no method that writes to an
  authority port (by import + call-graph, not name); detect a second queue/ledger
  by structural role, not name.

### High-6 — persistence/restart evidence uses in-memory fakes
- **Where:** `tests/integration/r2/m4/conftest.py`,
  `tests/integration/r2/m4/test_approved_master_semantics.py`.
- **Spec:** D11 §1477–1482 ("Do not mock the Host API boundary that production M4
  actually consumes"), plan §1600–1609 (restart/reopen evidence for master,
  reservation, currency, failed later candidate).
- **Gap:** the reservation service, submitter and Host are fakes; "restart" builds a
  new service around the same in-memory dict — no DB/process restart, no persisted
  reservation reload, no artifact reload.
- **Direction:** drive `ProductionApprovalService` and the C04 reservation service
  against a real (SQLite) session, close and reopen it, and re-assert master /
  reservation / currency across the reopen.

### Med-1 — identity resolver applies profiles unrelated to the target
- **Where:** `r2/production_intelligence/identity.py` (`VisualIdentityResolver.resolve`).
- **Spec:** D05 §432–445, §503–515 — collect the *applicable* scopes for the target's
  hierarchy.
- **Gap:** `resolve()` receives only `target_ref` + a flat profile list and applies
  every profile; a SHOT-scoped profile for a different shot still contributes;
  FORMAT/EPISODE siblings tie-break on profile id.
- **Direction:** pass the target's scope ancestry (project / format / episode /
  sequence / scene / shot refs) and filter profiles whose `scope_ref` is on that
  path; define a deterministic FORMAT-vs-EPISODE precedence.
- **FIXED (next-session batch):** `VisualIdentityResolver.resolve` now takes a
  required `scope_ancestry: Mapping[IdentityScopeType, str]`. `_is_on_ancestry`
  keeps an unscoped profile (broad base) and a scoped profile only when
  `scope_ancestry[scope_type] == scope_ref`; off-path siblings are dropped from
  `contributing_profile_refs` / `observed_profile_versions`, never id-tie-broken.
  `_SCOPE_RANK` is now a total order with EPISODE (3) more specific than FORMAT
  (2). `M4ShotCase.scope_ancestry` supplies the golden path; new `test_identity`
  cases cover exclusion, EPISODE-over-FORMAT, sibling drop and the unscoped base.

### Med-2 — frozen VisualIdentity locks silently disappear; conflict emits no signal
- **Where:** `r2/production_intelligence/identity.py` (`_flat_constraints`), pipeline.
- **Spec:** D05 §10.4 / §10.7 (costume / accessory / state locks are part of the
  model and compile to typed capability requirements), C01 §10.6 (conflict →
  `HUMAN_ACTION_REQUIRED` + correlated production event / review signal).
- **Gap:** only `hairstyle_lock` and `face_master_ref` are flattened;
  `full_body_master_ref`, `side_profile_ref`, `costume_locks`, `accessory_locks`,
  `state_variants` never reach the resolver / requirements / prompt plan. On
  `CONFLICTED` the pipeline just returns — no `FailureRecord`, no `ProductionEvent`.
- **Direction:** flatten every frozen lock to a typed constraint; on identity
  conflict emit a `FailureRecord(HUMAN_ACTION_REQUIRED)` + `ProductionEvent`.
- **FIXED (next-session batch):** `_flat_constraints` now flattens
  `full_body_master_ref`, `side_profile_ref`, `costume_locks`, `accessory_locks`
  (LOCKED, per-value keys) and `state_variants` (PREFERRED envelope) — these
  reach the resolved view, the generic `IDENTITY_LOCK:` / `IDENTITY_PREF:`
  capability requirements and the PromptPlan. The golden-12 `run_pipeline` no
  longer bare-returns on a non-READY Gate 1: it builds a
  `FailureNormalizer.normalize_outcome(READINESS, reason_code=blocked_reason or
  "NOT_READY")` (→ `HUMAN_ACTION_REQUIRED`, explicit in
  `_EXPECTED_OUTCOME_DISPOSITION`) and a projected `ProductionEvent`, both on
  `M4PipelineResult.{failure,events}`. New `test_identity_conflict_signal.py` +
  `test_every_frozen_flat_lock_reaches_the_resolved_view`.

### Med-3 — provider-neutrality enforced by field names, not values
- **Where:** `r2/contracts/preparation.py` (`IdentityConstraint`),
  `r2/production_intelligence/prompting.py`.
- **Spec:** D05 §552–565, D08 §817–848.
- **Gap:** `semantic_key` / `semantic_value` are unvalidated `NonEmptyStr`;
  `"midjourney--cref"` / `"--cw 100"` validate and are copied verbatim into
  `PromptPlan.visual_identity_constraints`. Architecture tests only inspect
  top-level field names.
- **Direction:** validate identity/prompt semantic strings against a provider-syntax
  denylist (or an allowed semantic-key vocabulary); add an architecture check on
  values, not just names.
- **FIXED (next-session batch):** new `r2/contracts/provider_syntax.py` denylist
  (`detect_provider_syntax` / `reject_provider_syntax`) — structural patterns
  (`--flag`, `::weight`, `<lora:…>`, `(term:1.3)`) plus a brand/payload-key token
  set. Wired as `field_validator`s on `IdentityConstraint.{semantic_key,
  semantic_value}`, `ResolvedIdentityConstraint.{semantic_key, effective_value}`,
  and `PromptPlan.{visual_identity_constraints, reference_requirements}`.
  `test_provider_syntax_guard.py` covers the guard + each wiring;
  `test_architecture_boundaries.py` gains a value-level neutrality assertion.

### Med-4 — DefaultPromptCompiler is a generic request builder
- **Where:** `r2/production_intelligence/prompting.py` (`DefaultPromptCompiler`).
- **Spec:** D08 §951–987 — a provider-specific compiler that tests representability
  for the *selected* candidate.
- **Gap:** every provider gets the same whitelist / payload shape /
  `generate/{execution_type}` endpoint; descriptor features and adapter syntax are
  ignored, so candidate-specific `COMPILATION_INCOMPATIBLE` cannot be detected.
- **Direction:** make the compiler a per-adapter strategy keyed off
  `ExecutionDecision.adapter_id` / descriptor features; keep the fail-closed
  contract but drive it from the candidate's real capability surface.

---

## NOT REPRODUCED

### Nit-1 — `git diff --check` extra blank line at EOF
- `git diff --check` is clean on this checkout; likely an artifact of the reviewer's
  read-only environment. Left as-is; re-check at next Gate D run.
