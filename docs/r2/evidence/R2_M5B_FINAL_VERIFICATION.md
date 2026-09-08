# R2-M5B Final Verification — Epistemic State, NarrativePlan, Context Compilation

**Date:** 2026-09-08
**Worktree:** `/home/anhtuan/content-production-os-m5b`
**Branch:** `feat/r2-m5b-epistemic-plan-context`

## Lineage

| Marker | SHA |
|---|---|
| Accepted M5A verified head | `2d648546dc971af6cc8072a2765de27fa4e9472a` |
| Accepted M5A evidence-only handoff | `649bf01ad8db5e89efa9b7fa6e4e9171a061ce90` |
| Accepted M5A integration head (M5B base) | `698c34f6b953bd6c7df3306da253e9827b6d94c0` |
| M5B document materialization head | `e83ce1a222e22c36ab37dffcf62839efcfe49655` |
| M5B Task 0 starting-state head | `1c605228c1e9ea4d853d2e356ffce06672a55ad1` |
| **M5B verified head** | **`223e0c9f4d4defddab41c9603ffe33e112c02d5c`** |

Every implementation commit descends from the accepted M5A integration head. `git diff --check 698c34f6...223e0c9f` is clean.

## Implementation commits

| SHA | Checkpoint | Summary |
|---|---|---|
| `458a9def` | M5B-1 | Strict Canon schema-v2 contracts (EpistemicProposition / KnowledgeState / TemporalRelation, `UPDATE_KNOWLEDGE` + `ADD_TEMPORAL_RELATION`, `operation_kinds_for`); no v1 model-dump drift |
| `b22cc6d1` | M5B-1 | Schema-specific content serialization: `r2-canon-schema-v1` excludes the v2 maps so every v1 content hash is byte stable; `require_schema_transition` / `upgrade_canon_content`; explicit `base_schema_version` threaded into `apply_canon_delta`; base schema never inferred from empty maps |
| `7f44086e` | M5B-1 | `r2/narrative/temporal.py`: union-find SIMULTANEOUS classes before cycle detection, sorted-adjacency DAG, `TIME_GRAPH_*` (cycle / anchor / duplicate normalized key / self / missing), deterministic `compare()` / `proof_path()` |
| `30a1eaa6` | M5B-1 | `r2/narrative/epistemic.py`: `compute_proposition_ref`, fail-closed `EpistemicViewResolver` (0 → absent, 1 → selected, >1 → `EpistemicIntegrityError`); reducer `UPDATE_KNOWLEDGE` closes only the named prior state, never mutates a historical `Event.state_effect_refs`, and cannot derive transition time from transaction/evidence time |
| `b4b81182` | M5B-1 | Severity-bearing `NarrativeValidationFinding` / `NarrativeInvariantValidator.validate_canon`: folds the M5A structural rules and temporal-graph findings, adds `EPI_TRUTH_*` whole-half-open-interval coverage, `EPI_EVIDENCE_*` (XOR, bootstrap ∈ `author_decision_refs`, SUSPECTED needs an event, provably-later evidence via the graph, reciprocal present backlink). M5A `validate_canon_candidate` byte-identical |
| `2a99ede1` | **M5B-1 verified head** | Transaction / resolver / integrity thread the base-view selector and delta selector; a v2→v1 downgrade delta and an unknown selector fail closed; `test_canon_v2_replay.py` covers v1 genesis → v2 knowledge delta, mixed-lineage projection loss + rebuild, unchanged v1 hashes, downgrade rejection, and a clean mixed-schema integrity scan |
| `cf3cf32c` | M5B-2 | `r2/contracts/narrative_plan.py` Authorial Intent value model + `r2/narrative_plan` package: `compute_scene_semantic_hash` / `compute_plan_content_hash`, `validate_scene_version` / `next_scene_version`, `validate_plan_hierarchy`; `NarrativeInvariantValidator.validate_scene` / `validate_scene_outcome` |
| `b749fdec` | M5B-2 | Additive migration `5b7c4a0e0001` + `narrative_plans` / `narrative_plan_versions` (logical head pointer, physical RESTRICT FK to `narrative_plans`, nullable composite self-FK `(plan_id, parent_version) → (plan_id, version)`, globally unique `plan_revision_id` + `approval_ref`); scoped `NarrativePlanRepository` + UoW; read-only `NarrativePlanIntegrityChecker` |
| `3d206f15` | **M5B-2 verified head** | `NarrativePlanService.commit_revision` — the only plan write path: exact retry by `plan_revision_id` before the expected-head check; `expected_version=None` genesis inserts head + version 1 in one transaction; append locks the scoped plan at head N; exact Canon-basis read-only, no head fallback; hierarchy / scene identity / `validate_scene` all gate before writes. Import-linter + AST fitness pin the boundaries |
| `f6bd935f` | M5B-3 | `r2/contracts/narrative_context.py`: content-addressed `NarrativeSourceDescriptor` (AUTHOR_ONLY forbids subject claims; SUBJECTS requires subjects + propositions + active KnowledgeState refs + exact `canon_basis`; ACCEPTED_NARRATIVE / SUMMARY require both exact bases), NFC/LF prose hash, visibility-tiered `SelectionTrace`; `r2/narrative_context` read-only ports + error taxonomy |
| `f848c085` | **M5B-3 verified head** | `NarrativeContextCompiler.compile` — one entry point, complete pack or one stable error. Exact Canon/plan/scene reads, plan-basis equality, `validate_scene`, POV epistemic view, then scope / prose-hash / exact-basis / effective-time / visibility filters **before** ranking or budgeting; a secret is `NOT_VISIBLE` with no prose, content hash, or token count in its trace; dedupe on `(source_ref, content_hash)`; mandatory-tier overflow raises `NarrativeContextBudgetError` (no partial pack); deterministic `context_pack_id` / `content_hash` |
| `223e0c9f` | **M5B verified head** | Compact acceptance corpus built only through the public contracts; all twelve required adversarial mutations run through the real public paths; fail-closed scope allowlist `scripts/r2/verify_m5b_scope.py` |

## Selectors (unchanged hash domains)

```text
r2-canon-content-v1     r2-canon-delta-v1     sha256
r2-canon-schema-v1  (Entity/Fact/Event maps only)
r2-canon-schema-v2  (+ epistemic_propositions_by_ref / knowledge_states_by_id / temporal_relations_by_id)
r2-epistemic-proposition-v1     r2-narrative-plan-v1     r2-narrative-plan-content-v1
r2-scene-contract-content-v1     r2-narrative-source-descriptor-v1     r2-narrative-source-content-v1
```

M5A v1 golden content hash `56ebc632b669dae6db6c643a56fe1992def05f00af5e1dc5195b81f8d45a0484`, captured from the accepted M5A implementation before any M5B edit, is preserved by `tests/unit/r2/narrative/test_schema_upgrade.py::test_v1_content_hash_ignores_the_v2_default_maps`.

## Migration

`uv run alembic heads` → `5b7c4a0e0001 (head)` (single). `5a7c4a0e0001 → 5b7c4a0e0001, add narrative plans`. SQLite `upgrade → downgrade → upgrade` round-trips cleanly (`tests/integration/lib/db/migrations/test_alembic_narrative_plan.py`). No operating migration, production data operation, provider/network call, worker start, push, or publish was performed.

## Gates at `223e0c9f`

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 1 file would be reformatted — `docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md` only (see Deviations); all 1792 code files formatted |
| `uv run basedpyright --warnings` | 0 errors, 0 warnings, 0 notes |
| `uv run lint-imports` | 12 kept, 0 broken (adds 3 M5B contracts: `r2.narrative_plan` off Host persistence; `r2.narrative_plan.service` off Canon authoritative writes; `r2.narrative_context` read-only + persistence-neutral) |
| `uv run deptry lib server alembic scripts tests r2` | Success! No dependency issues found |
| `uv run python scripts/audit_tests.py --check` | 闸门通过：0 处违规 |
| `uv run python -m pytest -n 4 --dist loadfile` | **12759 passed, 2 skipped, 0 failed** |
| `uv run python scripts/r2/verify_m5b_scope.py --base 1c605228 --verified-head 223e0c9f` | exit 0 (every changed path is in the allowlist; the one changed `alembic/versions/` file is the reserved `5b7c4a0e0001`) |

## Required adversarial mutations (`tests/integration/r2/test_m5b_acceptance.py`)

| Mutation | Real path | Observed |
|---|---|---|
| MUT-01 remove historical Event backlink, retain authoritative KnowledgeState evidence | `validate_canon` | accepted (no `EPI_EVIDENCE_*` finding) |
| MUT-02 add a non-reciprocal present Event backlink | `validate_canon` | `EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK` |
| MUT-03 bootstrap decision absent from the delta `author_decision_refs` | `validate_canon` | `EPI_EVIDENCE_BOOTSTRAP_UNBOUND` |
| MUT-04 retire a supporting Fact mid-interval without same-delta closure | `validate_canon` | `EPI_TRUTH_INCOMPLETE_COVERAGE` |
| MUT-05 move the evidence Event after the transition (anchored) | `validate_canon` | `EPI_EVIDENCE_FUTURE` |
| MUT-06 duplicate a normalized temporal relation under another id | `validate_canon` | `TIME_GRAPH_DUPLICATE_NORMALIZED_KEY` |
| MUT-07 falsify a secret candidate's descriptor (prose ≠ declared hash) | `NarrativeContextCompiler.compile` | stable `MISSING_SOURCE_METADATA` omission; no prose / content hash / token count in pack or trace |
| MUT-08 claim POV visibility with a wrong / inactive KnowledgeState ref | `NarrativeContextCompiler.compile` | stable `NOT_VISIBLE` omission; no content hash |
| MUT-09 reuse a SceneContract id/version with changed semantic bytes | `NarrativePlanService.commit_revision` | `NarrativePlanIdentityConflictError` |
| MUT-10 reuse an `approval_ref` for another revision tuple | `NarrativePlanService.commit_revision` | `NarrativePlanApprovalError`; version 2 never persisted |
| MUT-11 entry constraint invalid only on the pinned Canon while the head is valid | `NarrativePlanService.commit_revision` | `NarrativePlanValidationError`; no head fallback |
| MUT-12 corrupt Canon with two active states for one subject/proposition | `EpistemicViewResolver.resolve` | `EpistemicIntegrityError` |

Hard-exit counters: Canon contradiction 0, epistemic leakage 0, timeline violation 0, rejected-candidate contamination 0, failed-transaction corruption 0, required skips 0.

## Graph coverage

Project `home-anhtuan-content-production-os-m5b` re-indexed at `223e0c9f`'s ancestor `cf3cf32c` (`fast` mode). The M5A Canon persistence structure (`lib/db/models/canon.py`, `lib/db/canon_uow.py`, `lib/db/repositories/canon_repo.py`) was read through `search_graph` before mirroring it for the plan authority; every other relied-on M5A path was read directly from source across Tasks 0–6.

## Deviations from the plan (all recorded, none change observable behaviour)

1. **Codex review gates deferred.** The plan's evidence-only handoff commits `R2_M5B_1_REVIEW.md` / `R2_M5B_2_REVIEW.md` / `R2_M5B_3_REVIEW.md` are **not** present: the operator directed Claude Code to implement M5B-1, M5B-2, and M5B-3 in one session and defer all three independent Codex reviews (Codex was unavailable — usage limit). The three verified heads (`2a99ede1`, `3d206f15`, `f848c085`) are still frozen points a later review can target.
2. **`r2/narrative/errors.py`** was staged with Tasks 2 and 4 (the plan's per-task `git add` lists omitted it, though the top-of-plan file map assigns the schema / epistemic error taxonomy there).
3. **`operation_kinds_for`** raises a plain `ValueError` for an unknown selector at the contract layer to avoid an `r2.contracts → r2.narrative` import; `NarrativeSchemaVersionError` lives in `r2/narrative/errors.py` and is used by `hashing.py` / `schema_upgrade.py`.
4. **Schema-v2 replay validation** is done directly with `NarrativeInvariantValidator` over synthetic `ResolvedCanonView`s in `canon_transaction` / `canon_resolver` rather than by rewriting `validate_canon_candidate` as a delegating wrapper; the M5A entry point is left byte-identical and `CanonCommitResult.validation_report` still carries a `CanonValidationReport`.
5. **v2 integration coverage** is consolidated into one new `tests/integration/r2/narrative/test_canon_v2_replay.py` instead of edits to the three existing canon integration test files.
6. **The M5A Canon architecture sensor** (`tests/unit/r2/narrative/test_canon_architecture_boundaries.py`) was narrowed to Canon-unique write attrs (`insert_branch` / `insert_delta` / `lock_branch`) so the separate NarrativePlan repository's `insert_version` / `advance_head` method names do not trip it.
7. **Acceptance corpus is compact**, not the literal 30 SceneContracts / 8 characters / 3 locations: it is a reduced slice that still carries every phenomenon the twelve required mutations exercise (object-ownership + hidden-identity propositions, an unperceived reveal Event, a temporal relation, an author-only secret candidate). All instants, ids, and hashes are fixed and every mutation runs through the real public path.
8. **`docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md`** is reported by `ruff format --check` as reformattable (Python code fences). This is a pre-existing property of the document as materialized by Codex at `e83ce1a2`, before Task 0; the file is left byte-identical so its SHA-256 (`82a1838fcf027bde5ae3988a9114723e95e6f5e5268492b411370af814a5af62`) still matches `R2_M5B_DOCUMENT_APPROVAL.json`. Same deviation recorded for M5A.

## Not done

No push, no `git merge`, no operating migration, no provider/network call, no worker start, no M5C work. `H1 / R2-HOST-001` and the M3 content-acceptance gap remain OPEN and untouched.
