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
| M5B pre-review verified head | `223e0c9f4d4defddab41c9603ffe33e112c02d5c` |
| M5B verified head (Codex review fixes applied) | `3085d14e` |
| **M5B self-review head (Codex unavailable; see Post-verified section)** | **`62b07b4a`** |

Every implementation commit descends from the accepted M5A integration head. `git diff --check 698c34f6...62b07b4a` is clean. The `3085d14e → 62b07b4a` range is the post-verified self-review; the scope gate for it is `uv run python scripts/r2/verify_m5b_scope.py --base 1c605228 --verified-head 62b07b4a` (exit 0).

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
| `223e0c9f` | M5B pre-review head | Acceptance corpus built only through the public contracts; all twelve required adversarial mutations run through the real public paths; fail-closed scope allowlist `scripts/r2/verify_m5b_scope.py` |
| `3085d14e` | **M5B verified head** | All Codex full-review findings resolved across the three checkpoints and acceptance: schema-shape replay guard, evidence-path findings, parent_version / exact-basis service checks, per-version integrity check, compiler exact-identity + SUBJECTS proof-matrix + recent-accepted path, `full_corpus()` (30 scenes / 8 characters / 3 locations / 2 hidden identities / 2 false beliefs / injury supersession / ownership hand-off / presentation-order time jump / unperceived reveal / BEFORE relation) compiled deterministically in both modes, and a hard-exit counter test derived from actual mutation results |

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

## Gates at `3085d14e`

| Command | Result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check r2 tests scripts lib server alembic` | 1297 code files already formatted (the approved plan document is excluded from the code paths and left byte-identical; see Deviations) |
| `uv run basedpyright --warnings` | 0 errors, 0 warnings, 0 notes |
| `uv run lint-imports` | 12 kept, 0 broken (adds 3 M5B contracts: `r2.narrative_plan` off Host persistence; `r2.narrative_plan.service` off Canon authoritative writes; `r2.narrative_context` read-only + persistence-neutral) |
| `uv run deptry lib server alembic scripts tests r2` | Success! No dependency issues found |
| `uv run python scripts/audit_tests.py --check` | 闸门通过：0 处违规 |
| `uv run python -m pytest -n 4 --dist loadfile` | **12764 passed, 2 skipped, 0 failed** |
| `uv run python scripts/r2/verify_m5b_scope.py --base 1c605228 --verified-head 3085d14e` | exit 0 (every changed path is in the allowlist; the one changed `alembic/versions/` file is the reserved `5b7c4a0e0001`) |

## Required adversarial mutations (`tests/integration/r2/test_m5b_acceptance.py`)

| Mutation | Real path | Observed |
|---|---|---|
| MUT-01 remove historical Event backlink, retain authoritative KnowledgeState evidence | `validate_canon` | accepted — `report.ok` (no ERROR finding) |
| MUT-02 add a non-reciprocal present Event backlink | `validate_canon` | `EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK` asserted against the mutated candidate |
| MUT-03 bootstrap decision absent from the delta `author_decision_refs` | `validate_canon` | `EPI_EVIDENCE_BOOTSTRAP_UNBOUND` |
| MUT-03 inverse: a delta-level author decision with no operation-local evidence or bootstrap | `validate_canon` | `EPI_EVIDENCE_MISSING` (never inferred as a bootstrap) |
| MUT-04 retire a supporting Fact mid-interval without same-delta closure | `validate_canon` | `EPI_TRUTH_INCOMPLETE_COVERAGE` |
| MUT-05 move the evidence Event after the transition (anchored) | `validate_canon` | `EPI_EVIDENCE_FUTURE` |
| MUT-06 duplicate a normalized temporal relation under another id | `validate_canon` | `TIME_GRAPH_DUPLICATE_NORMALIZED_KEY` |
| MUT-07 falsify a secret candidate's descriptor (prose ≠ declared hash) | `NarrativeContextCompiler.compile` | stable `MISSING_SOURCE_METADATA` omission; no prose / content hash / token count in pack or trace |
| MUT-08 claim POV visibility with a wrong / inactive KnowledgeState ref | `NarrativeContextCompiler.compile` | stable `NOT_VISIBLE` omission; no content hash |
| MUT-09 reuse a SceneContract id/version with changed semantic bytes | `NarrativePlanService.commit_revision` | `NarrativePlanIdentityConflictError` |
| MUT-10 reuse an `approval_ref` for another revision tuple | `NarrativePlanService.commit_revision` | `NarrativePlanApprovalError`; version 2 never persisted |
| MUT-11 entry constraint invalid only on the pinned Canon while the head is valid | `NarrativePlanService.commit_revision` | `NarrativePlanValidationError`; no head fallback |
| MUT-12 corrupt Canon with two active states for one subject/proposition | `EpistemicViewResolver.resolve` | `EpistemicIntegrityError` |

`test_every_mutation_leaves_all_hard_exit_counters_at_zero` re-runs every mutation above and derives the six counters from the actual validator findings, compiled-pack contents, `SelectionTrace` fields, and persisted plan-version lists (a rejected write must leave the head untouched; a rejected genesis must persist no row). Result: Canon contradiction 0, epistemic leakage 0, timeline violation 0, rejected-candidate contamination 0, failed-transaction corruption 0, required skips 0.

## Full acceptance corpus (`tests/fixtures/r2/m5b_narrative_corpus.py::full_corpus`)

30 SceneContracts, 8 CHARACTER + 3 LOCATION entities, 2 hidden-identity propositions (`true_name`), 2 FALSE_BELIEF KnowledgeStates, an injury Fact supersession (`healthy` → `injured`, no gap or overlap, `source_event_refs=[ev-fight]`), an object-ownership hand-off (`obj-crown` owner `char-1` → `char-2` via `ev-handover`), a presentation-order time jump (`scene-11.sequence_index < scene-12.sequence_index` while `scene-11` occurs later in story time), an unperceived reveal Event (`ev-reveal`, named by no KnowledgeState evidence), and a `BEFORE` temporal relation. Every instant, id, hash, and token count is fixed. `test_full_corpus_compiles_deterministically_in_both_modes_without_leak` compiles it through `NarrativeContextCompiler.compile` twice per mode: identical `context_pack_id` / `content_hash`; the AUTHOR_ONLY secret is admitted for the author and withheld from the `char-6` simulation (`NOT_VISIBLE`, no hash or token count), while `char-6`'s legitimately KNOWN heir fact still reaches the simulation pack.

## Graph coverage

Project `home-anhtuan-content-production-os-m5b` re-indexed at `223e0c9f`'s ancestor `cf3cf32c` (`fast` mode). The M5A Canon persistence structure (`lib/db/models/canon.py`, `lib/db/canon_uow.py`, `lib/db/repositories/canon_repo.py`) was read through `search_graph` before mirroring it for the plan authority; every other relied-on M5A path was read directly from source across Tasks 0–6.

## Deviations from the plan (all recorded, none change observable behaviour)

1. **Codex review gates deferred.** The plan's evidence-only handoff commits `R2_M5B_1_REVIEW.md` / `R2_M5B_2_REVIEW.md` / `R2_M5B_3_REVIEW.md` are **not** present: the operator directed Claude Code to implement M5B-1, M5B-2, and M5B-3 in one session and defer all three independent Codex reviews (Codex was unavailable — usage limit). The three verified heads (`2a99ede1`, `3d206f15`, `f848c085`) are still frozen points a later review can target.
2. **`r2/narrative/errors.py`** was staged with Tasks 2 and 4 (the plan's per-task `git add` lists omitted it, though the top-of-plan file map assigns the schema / epistemic error taxonomy there).
3. **`operation_kinds_for`** raises a plain `ValueError` for an unknown selector at the contract layer to avoid an `r2.contracts → r2.narrative` import; `NarrativeSchemaVersionError` lives in `r2/narrative/errors.py` and is used by `hashing.py` / `schema_upgrade.py`.
4. **Schema-v2 replay validation** is done directly with `NarrativeInvariantValidator` over synthetic `ResolvedCanonView`s in `canon_transaction` / `canon_resolver` rather than by rewriting `validate_canon_candidate` as a delegating wrapper; the M5A entry point is left byte-identical and `CanonCommitResult.validation_report` still carries a `CanonValidationReport`. A self-review cross-note asked whether `canon_transaction.py` passing `CanonValidationReport(findings=())` on the successful-commit path (rather than the `report` it computed) is an audit regression. It is not: at M5A `CanonValidationReport.ok` is `not findings`, so a commit that passed the `report.ok` gate always carried an empty report anyway, and `_resolve_exact_retry` has returned an empty report since M5A. M5B's `validate_canon` now returns a `NarrativeValidationReport` whose non-blocking `WARNING` findings have no field on the M5A `CanonValidationReport` / `CanonCommitResult` contract; surfacing them would be a contract change this deviation deliberately avoids. No caller reads `CanonCommitResult.validation_report` and no test or ADR-0075 clause requires it to be non-empty.
5. **v2 integration coverage** is consolidated into one new `tests/integration/r2/narrative/test_canon_v2_replay.py` instead of edits to the three existing canon integration test files.
6. ~~The M5A Canon architecture sensor was narrowed to Canon-unique write attrs.~~ **Resolved at `3085d14e`.** `tests/unit/r2/narrative/test_canon_architecture_boundaries.py` now asserts the full authority-write attribute set (`insert_branch` / `insert_delta` / `insert_version` / `advance_head` / `lock_branch`), the Canon write callers plus the plan-authority files are the only referencing sites, and a new test asserts the plan-authority files carry no Canon-authority symbol. Mirrored in `tests/unit/r2/test_m5b_architecture_boundaries.py`.
7. ~~Acceptance corpus is compact.~~ **Resolved at `3085d14e`.** `tests/fixtures/r2/m5b_narrative_corpus.py::full_corpus` builds the literal 30 SceneContracts / 8 characters / 3 locations / 2 hidden identities / 2 false beliefs plus the injury supersession, ownership hand-off, presentation-order time jump, unperceived reveal Event, and `BEFORE` relation, and is compiled through the public compiler in both modes (see Full acceptance corpus above). The original compact corpus helpers are retained for the twelve MUT-* tests.
8. **`docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md`** is reported by `ruff format --check` as reformattable (Python code fences). This is a pre-existing property of the document as materialized by Codex at `e83ce1a2`, before Task 0; the file is left byte-identical so its SHA-256 (`82a1838fcf027bde5ae3988a9114723e95e6f5e5268492b411370af814a5af62`) still matches `R2_M5B_DOCUMENT_APPROVAL.json`. Same deviation recorded for M5A.

## Post-verified self-review (Codex unavailable)

Codex reached its usage limit before the re-review of `3085d14e`, so a two-axis self-review (Standards + Spec) was run against `698c34f6...HEAD` instead. Resulting changes on `feat/r2-m5b-epistemic-plan-context` after `3085d14e`:

| SHA | Summary |
|---|---|
| `47850876` | `fix(r2)`: pin compiler version at the narrative-context seam. `SUPPORTED_COMPILER_VERSIONS = frozenset({"compiler-v1"})` in `r2/narrative_context/compiler.py`; `compile()` raises `NarrativeSchemaVersionError` (reused from `r2/narrative/errors.py`) for `"latest"` or any unlisted `compiler_version` before any authority read. Closes design §10.1 / §11 / §16 ("compiler accepts exact versions only"). +3 unit tests in `tests/unit/r2/narrative_context/test_compiler.py`. |
| `3ae9b990` | `chore(r2)`: pin `ruff>=0.15.0,<0.16` in `pyproject.toml` + `uv.lock` (0.16.5 → 0.15.22). ruff 0.16 reformats Python code fences inside Markdown, which would rewrite the sha256-pinned plan doc (deviation #8). With ruff pinned, `ruff format --check .` is clean (no `.md` scan) — deviation #8 stands as a pre-existing property, no longer a live gate divergence. |
| `bd59ed5a` | `refactor(r2)`: reword the `verify_m5b_scope.py` allowlist comment to state the constraint, not the review history (Standards-axis finding). |
| `819ab679` | `docs(r2)`: cross-note dismissed — `canon_transaction.py` passing `CanonValidationReport(findings=())` on the successful commit path matches M5A (deviation #4). |
| _pending commit_ | `feat(r2)`: close self-review finding (3) — `NarrativeInvariantValidator.validate_scene` now also enforces §8.2 / §9-step-6 rules it had skipped: `SCENE_BASIS_MISMATCH` (`plan.content.canon_basis` must equal the resolved Canon — the `plan` arg was previously `_ = plan`), `SCENE_KNOWLEDGE_REVEAL_PRESTATE` (a `CharacterRevealRecipient` may not already hold `resulting_state` at entry, spec `:537`), `SCENE_EVENT_SELECTOR_UNSATISFIABLE` (a required-event pattern naming a non-entity, or an exact `event_ref` that contradicts an existing Event; an absent `event_ref` stays a future obligation, spec `:544-546`), `SCENE_STATE_REQUIRED_FORBIDDEN_COLLISION` (a `SceneKnowledgeConstraint` in both `entry_state_constraints` and `forbidden_knowledge`, spec `:535`). No contract change / no `semantic_hash_version` bump. +7 unit tests in `tests/unit/r2/narrative_plan/test_plan_validation.py`. Research: `docs/research/2026-09-08-r2-m5b-validate-scene-plan-commit-rules.md`. Lower-priority gaps left open: exact-reference integrity for `event_ref`/`proposition_ref` (R9) and intra-list normalized-duplicate rejection (R10) — neither is review-flagged and both carry more spec ambiguity. |

Gates re-run at the pending head: `ruff check .`, `ruff format --check .`, `basedpyright --warnings` 0/0/0, `lint-imports` 12 kept, `deptry` clean, `audit_tests --check` 0, `pytest -n 4 --dist loadfile` **12774 passed / 2 skipped**. Single alembic head `5b7c4a0e0001`.

9. **AUTHOR_DRAFT omniscient-authoring POV gate is not enforced (deferred).** Design §10.1 states "`AUTHOR_DRAFT` may omit POV only for omniscient authoring explicitly permitted by the SceneContract and policy." The compiler currently returns no POV view whenever `pov_subject_entity_id is None` and consults no permission. Source research (`docs/research/2026-09-08-r2-m5b-author-draft-omniscient-gate.md`) establishes: (a) the mechanism is undocumented — §10.1 is the sole statement, the plan doc is silent, "omniscient" appears nowhere else; (b) the reuse research (`...-reuse-and-boundary-research.md:187`) lists "whether author-only truth may be emitted at all, and to whom" as an unresolved design question; (c) the "and policy" half is unimplementable in M5B — the policy read seam is opaque `(source_ref, content)` prose, no typed `CreativePolicy` model exists, and CreativePolicy write authority is out of scope (design §17). Enforcing the SceneContract half alone would force a `SceneContract` `semantic_hash_version` v1→v2 bump and recompute every historical scene hash. Deferred to the milestone that gives `CreativePolicy` a typed contract. Risk is low: `AUTHOR_DRAFT` already includes `AUTHOR_TRUTH` by design (§10.3); this gate is an explicit-opt-in requirement for the no-POV author path, not a containment boundary, and no downstream consumer of `AUTHOR_DRAFT` exists before M5C. (GitHub Issues are disabled on this repo; recorded here per the deviation-#1 precedent.)

## Not done

No push, no `git merge`, no operating migration, no provider/network call, no worker start, no M5C work. `H1 / R2-HOST-001` and the M3 content-acceptance gap remain OPEN and untouched. All three self-review findings and the cross-note are now addressed: the Standards comment is reworded, the `canon_transaction.py` empty-report cross-note is dismissed (deviation #4), the compiler version pin is enforced, and `validate_scene` closes its §8.2 / §9-step-6 gaps (see the post-verified table). Deferred and recorded: the AUTHOR_DRAFT omniscient-authoring gate (deviation #9), and the lower-priority `validate_scene` R9/R10 gaps. `R2_M5B_{1,2,3}_REVIEW.md` handoff files still not written.
