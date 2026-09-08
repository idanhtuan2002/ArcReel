# R2-M5B-2 Review — NarrativePlan authority and SceneContract validation

**Review type:** two-axis self-review (`/code-review`: Standards + Spec sub-agents).
Codex was over its usage limit; this stands in for the per-checkpoint Codex
review the plan expected (`docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md:995`).
The self-review ran once against the whole M5B branch (`698c34f6...HEAD`); this
document extracts the findings that fall in the M5B-2 scope, including the fix
committed after the frozen head.

**Checkpoint frozen head:** `3d206f15` ("feat(r2): complete NarrativePlan authority").
**Branch:** `feat/r2-m5b-epistemic-plan-context`. **Base:** `698c34f6`.

## Scope

`r2/contracts/narrative_plan.py`, `r2/narrative_plan/` (`hashing.py`,
`validation.py`, `integrity.py`, `ports.py`, `service.py`, `errors.py`,
`__init__.py`), the SceneContract rule surface in `r2/narrative/validation.py`
(`validate_scene` / `validate_scene_outcome`), `lib/db/models/narrative_plan.py`,
`lib/db/repositories/narrative_plan.py`, `lib/db/narrative_plan_uow.py`, the
additive migration `alembic/versions/5b7c4a0e0001_add_narrative_plans.py`; tests
`tests/unit/r2/contracts/test_narrative_plan.py`,
`tests/unit/r2/narrative_plan/`, `tests/unit/lib/db/models/test_narrative_plan.py`,
`tests/integration/r2/narrative_plan/`,
`tests/integration/lib/db/migrations/test_alembic_narrative_plan.py`,
`tests/integration/lib/db/repositories/test_narrative_plan.py`.

## Migration

`uv run alembic heads` → `5b7c4a0e0001 (head)` (single).
`5a7c4a0e0001 → 5b7c4a0e0001, add narrative plans`. SQLite
`upgrade → downgrade → upgrade` round-trips cleanly. Append-only: DB constraints
enforce one accepted `(plan_id, version)`, globally unique `plan_revision_id` and
`approval_ref`, positive version, physical `RESTRICT` FK to `narrative_plans`, and
the nullable composite self-FK `(plan_id, parent_version) → (plan_id, version)`.

## Spec axis

### Finding (3) — `validate_scene` under-implements the §8.2 / §9-step-6 plan-commit rules — FIXED

At the frozen head, `NarrativeInvariantValidator.validate_scene` checked only
entry-state constraints, the forbidden-knowledge window sweep, and event
required/forbidden **selector** collision, and discarded its `plan` argument
(`_ = plan`). Design §8.2 (`:517-542`) and §9 step 6 (`:702-709`) require more.

Source inventory: `docs/research/2026-09-08-r2-m5b-validate-scene-plan-commit-rules.md`.

Fixed at `62b07b4a` ("feat(r2): enforce the skipped SceneContract plan-commit
rules in validate_scene"). Added, all blocking (`severity=ERROR`, design §337):

| rule_id | Requirement | Spec |
|---|---|---|
| `SCENE_BASIS_MISMATCH` | `plan.content.canon_basis` must equal the resolved Canon branch/version; replaces `_ = plan` | `:1041` ("no head fallback" attributed to `validate_scene()`) |
| `SCENE_KNOWLEDGE_REVEAL_PRESTATE` | a `CharacterRevealRecipient` must not already hold `resulting_state` at `effective_from` | `:537` |
| `SCENE_EVENT_SELECTOR_UNSATISFIABLE` | a required-event pattern naming an entity absent from `canon_basis`, or an exact `event_ref` that contradicts an existing Event; an absent `event_ref` stays a future obligation | `:350`, `:544-546`, `:548-549` |
| `SCENE_STATE_REQUIRED_FORBIDDEN_COLLISION` | the same normalized `SceneKnowledgeConstraint` in `entry_state_constraints` and `forbidden_knowledge` | `:535` |

No contract change; no `SceneContract` `semantic_hash_version` bump. +7 unit tests
in `tests/unit/r2/narrative_plan/test_plan_validation.py`.

Left open (not review-flagged, more spec ambiguity; recorded):
- **R9** exact-reference integrity for `event_ref` / `proposition_ref` — a typo'd
  ref currently degrades to an ordinary `_UNMET` rather than a distinct reference
  finding.
- **R10** intra-list normalized-duplicate / typed-shape rejection.

### Verified correct

- `NarrativePlanService.commit_revision` is the only plan write path: exact retry
  by `plan_revision_id` before the expected-head check; genesis inserts head +
  version 1 in one transaction; append locks the scoped plan at head N; the Canon
  basis is an exact read-only `get_exact` with identity re-check and no head
  fallback (design §9, MUT-11).
- Plan versions are append-only — insert + `advance_head` only; an `approval_ref`
  reused for another revision tuple is rejected (`NarrativePlanApprovalError`,
  MUT-10) with nothing persisted.
- Reusing `(scene_contract_id, version)` with changed semantic bytes →
  `NarrativePlanIdentityConflictError` (MUT-09).
- Import-linter + AST fitness pin the authority boundary: only the plan service
  reaches the plan write port; no Canon authoritative write symbol is referenced
  from the plan-authority files.

## Standards axis (non-blocking judgement-calls; deferred)

- `_aware` / `_aware_optional` / `_sorted_unique` re-pasted into
  `contracts/narrative_context.py` and `contracts/narrative_plan.py`.
- `NarrativePlanRepository.flush` and `SqlAlchemyNarrativePlanUnitOfWork.commit`
  are pure pass-throughs (Middle Man); mirrors the existing canon UoW.
- `plan_id, project_name, user_id` travel together through nearly every new
  signature (Data Clumps); `(effective_from, effective_until)` likewise.
- `next_scene_version` has no production caller; `SceneVersionCheck.ok` is always
  `True`; `NarrativePlanNodeKind` StrEnum is exported but `NarrativePlanNode.node_kind`
  uses a bare `Literal` (Speculative Generality).

Disposition: deferred `/simplify` pass (`R2_M5B_FINAL_VERIFICATION.md` deviation #10).

## Gates

Recorded in `R2_M5B_FINAL_VERIFICATION.md` (Post-verified section), head
`62b07b4a`: all static gates green; `pytest -n 4` 12774 passed / 2 skipped;
single alembic head `5b7c4a0e0001`.

## Verdict

**APPROVED (self-review) after the finding-(3) fix at `62b07b4a`.** The frozen
head `3d206f15` plus the `62b07b4a` `validate_scene` delta are valid targets for
a later Codex re-review. R9 / R10 remain open follow-ups.
