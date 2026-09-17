# R2-M5C-1 Review — immutable Narrative lifecycle evidence (final M5C-1)

**Review type:** two-axis self-review (`/code-review`: parallel Standards + Spec
sub-agents), accepted as the review of record. Per the plan
(`docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md`, Task 14 Step 4) a
per-checkpoint Codex `APPROVED` was expected; the operator waived Codex for this
checkpoint in favour of the self-review, as was done for M5B and M5C-1A.

**Checkpoint frozen head:** `f0b27dcd95419aae6f5dbc6db856d1ab2a466f7c`
("refactor(r2): apply the M5C-1B self-review findings").
**Branch:** `feat/r2-m5c-narrative-lifecycle`.
**Base:** `32e10857f9ab8c8a316bab592d215fc4852c9e59` (the M5C-1A evidence-only handoff head).
**Diff:** `git diff 32e10857..f0b27dcd` — 24 files changed, ~+3550.

## Implementation commits (`32e10857..f0b27dcd`)

```
e1f8fced feat(r2): define immutable narrative lifecycle evidence contracts   (Task 10)
918d7c16 feat(r2): add pure narrative coverage and overlap rules             (Task 11)
f2dbf1b8 feat(db): add append-only narrative lifecycle evidence tables       (Task 12)
9b55ba97 feat(r2): add the narrative lifecycle evidence service              (Task 13)
92061dcf test(r2): fence the narrative evidence service boundary            (Task 14 fence)
37e76a92 test(r2): extend the M5C scope verifier for the M5C-1B blast radius (Task 14 tooling)
f0b27dcd refactor(r2): apply the M5C-1B self-review findings                 (self-review)
```

## What M5C-1B delivers

- **Immutable evidence contracts** (`r2/contracts/narrative_lifecycle.py`):
  `NarrativeWorkScope`; the closed, discriminated `NarrativeSemanticEffectKey` algebra
  (`CanonMutationEffectKey` | `ThreadPayoffEffectKey`, `THREAD_PAYOFF` →
  `canon_operation_count: Literal[0]`); `SourceSpan` (half-open, non-empty);
  `DraftCandidate`, `NarrativeRevision` (no `accepted` boolean; `predecessor` may not be
  self), `ExtractionAttempt` / `ExtractionResult` (`SUCCEEDED` ⇒ non-empty unique ordered
  `change_set_ids`; every other outcome ⇒ none), `NarrativeChangeItem`,
  `NarrativeChangeSet` (non-empty spans / effect keys / changes; each change's effect
  keys must be declared on the set; each change's evidence span must be contained by the
  declared source-span coverage). All frozen, `extra="forbid"`, timezone-aware UTC.
- **Versioned hash domains** (`r2/narrative_lifecycle/hashing.py`): `normalize_prose`
  reproduces the frozen M5B NFC + newline-collapse normalization byte-for-byte (locked by
  a regression test against `compute_source_content_hash`); `compute_prose_content_hash`
  (`pch:` prefix, digest over the normalized prose bytes only — a version tag in the
  digest would break that lock and violate design §4.2); `compute_evidence_semantic_fingerprint`
  (`esf:`, covers artifact kind, id, scope, exact bases, provenance — equal prose under
  different bases has a distinct fingerprint).
- **Pure coverage rules** (`r2/narrative_lifecycle/coverage.py`): `normalize_source_spans`,
  `normalize_effect_keys`, `spans_overlap`, `effect_keys_collide(policy=…)`,
  `coverage_contains`, `minimal_conflict_subject` → `ConflictSubject`. No import of
  `lib.db`, `server`, providers, clocks, or randomness.
- **Evidence persistence** (`lib/db/models/narrative_lifecycle.py`, migration
  `5c7c4a0e0001`, `lib/db/repositories/narrative_lifecycle.py`,
  `lib/db/narrative_lifecycle_uow.py`): six append-only tables
  (`narrative_draft_candidates`, `narrative_revisions`, `narrative_extraction_attempts`,
  `narrative_extraction_results`, `narrative_change_sets`, ordered association
  `narrative_extraction_result_change_sets`). `UNIQUE (attempt_id, generation)` on
  attempts and results; a composite FK from the result to that exact pair; composite
  `(user_id, project_name, id)` scope FKs; composite **basis** FKs so an attempt /
  change set can only bind to a revision whose exact bases match; non-negative
  generations; `RESTRICT` on every evidence-to-evidence reference (`user_id` ownership
  follows the repo-wide `UserOwnedMixin` `CASCADE`). The "a `SUCCEEDED` result owns ≥1
  ordered association row, a non-success result owns none" cross-row invariant is
  enforced inside the repository transaction.
- **`NarrativeLifecycleEvidenceService`** (`r2/narrative_lifecycle/evidence.py`):
  `record_draft_candidate`, `record_revision` (verifies candidate / predecessor / scope /
  matching bases before any insert), `record_successful_extraction` /
  `record_non_successful_extraction` (exact-retry compares the full stored tuple and
  writes nothing; any different result for the same `(attempt_id, generation)` —
  including a late success after an `OUTCOME_UNKNOWN` — is `NarrativeAttemptGenerationConflict`
  with no write), `get_exact_*`. It holds no head-mutation port. `admit_extraction`
  **fails closed** with `NarrativeAuthorityUnavailableError` — the transaction-bound
  current-decision guard it needs is not implemented; no "exists-only" or relaxed check
  runs.
- **Ports** (`r2/narrative_lifecycle/ports.py`): pure `Protocol` seams
  (`NarrativeLifecycleEvidenceRepositoryPort`, `NarrativeLifecycleUnitOfWork`,
  `…Factory`) that import only the evidence contracts.

## Review trail

### Standards axis (5 findings)

1. **Spec/plan section + task references and time-phrasing in code / config comments**
   (hard; `CLAUDE.md` 注释规范). Applied in `f0b27dcd`: dropped `(design Section …)`,
   `(research Section …)`, `M5C-2 / Task 20 / Task 18`, "arrives in", "until … wired",
   "才落地", "届时" from `errors.py`, `contracts/narrative_lifecycle.py`, `coverage.py`,
   `evidence.py`, `models/narrative_lifecycle.py`, and the `pyproject.toml` import-linter
   comment, and from the two integration test file docstrings.
2. **Speculative Generality / Duplicated Code — effect-key version.** Applied: the
   `mapping_version` field defaults now read `SEMANTIC_EFFECT_KEY_VERSION` (one source of
   truth); `NarrativeOutcomeEffectKey` (unused alias) removed from the export set.
3. **Middle Man — `flush()`.** Not changed: the plan Task 12 interface lists `flush()`
   as a repository / port method, so it is a documented interface point.
4. **Duplicated Code — test input builders.** Applied: `make_narrative_work_scope`,
   `make_narrative_provenance`, `make_draft_candidate`, `make_narrative_revision`,
   `make_extraction_attempt`, `make_extraction_result`, `make_canon_mutation_effect_key`,
   `make_narrative_change_set` promoted to `tests/factories.py` (the documented home) and
   used by the repo and evidence-service integration suites. `test_coverage_rules.py`
   keeps its distinct positional `_change_set` (different shape, two uses); the
   contracts-unit test keeps its minimal subject-under-test builders.
5. **Divergent Change — stringly-keyed `_get`.** Applied: replaced with a single typed
   `_scalar(stmt)` and explicit `select(Model).where(…)` per read method, matching the
   sibling `NarrativePlanRepository`.

### Spec axis (5 findings + 1 minor)

1. **Composite basis FKs absent** (design §7.1: "composite scope/basis FKs where a bare
   opaque-ID FK could otherwise … [bind] incompatible revisions"). Applied in `f0b27dcd`
   (migration `5c7c4a0e0001` amended — still pre-handoff, within M5C-1B): the revision
   table gains `UNIQUE (revision_id, base_canon_version_id, plan_version,
   scene_contract_version, context_pack_id)` and `UNIQUE (revision_id,
   base_canon_version_id)`; `narrative_extraction_attempts` gains
   `fk_narrative_extraction_attempts_revision_basis` and `narrative_change_sets` gains
   `fk_narrative_change_sets_revision_basis`, both `RESTRICT`. Structural coverage in
   `test_narrative_lifecycle.py` (models); PostgreSQL enforcement in
   `test_composite_basis_fk_rejects_an_incompatible_revision_link` (skipped on the
   SQLite test engine, which runs with foreign keys disabled).
2. **Atomic-bundle fault test missing** (design §7.4). Applied: `test_successful_bundle_is_atomic_when_the_commit_faults`
   uses a `_FaultOnCommitUnitOfWork` test double (no production symbol patched) — after
   the fault, neither the result nor its change set is observable, and the
   independently-committed attempt row is still durable.
3. **Prose hash not version-tagged.** Verified — not a defect. Design §4.2 defines
   `content_hash = sha256(normalized UTF-8 prose bytes)` with no version in the digest,
   and the regression lock against `compute_source_content_hash` requires the digest to
   stay bytes-only. `PROSE_CONTENT_HASH_VERSION` + the `pch:` prefix are the domain tag;
   a future normalization change takes a new tag and prefix.
4. **Unscoped `get_extraction_attempt_by_id`.** Verified — precedented. Mirrors
   `NarrativePlanRepository.get_version_by_revision`, which does an unscoped lookup on a
   globally-unique id so the service can resolve the owning tenant of a scopeless result
   / change set before any write; the returned contract carries the `work_scope`.
5. **Per-change coverage containment not enforced** (design §5.4). Applied: the
   `NarrativeChangeSet` validator now rejects any change whose evidence span is not
   contained by the union of the declared `source_spans` (inline sweep, no import — the
   pure `coverage_contains` lives in `r2.narrative_lifecycle.coverage`, which would be a
   cycle). Covered by `test_change_evidence_span_must_be_contained_by_declared_coverage`.
- **Minor** — "all authority references use RESTRICT" docstring vs `user_id` `CASCADE`:
  reworded to "evidence-to-evidence references use RESTRICT; user ownership follows the
  repo-wide `UserOwnedMixin` CASCADE".

Not defects (verified): `admit_extraction` fail-closed with
`NarrativeAuthorityUnavailableError`; `UNIQUE (attempt_id, generation)` + result→pair FK;
closed discriminated effect-key union; M5B prose normalization regression lock; the
evidence-service import-linter fence; the deferred compilation evidence-service methods
(their contracts land with the compilation checkpoint).

## Deviations from the plan (all recorded; none weaken a reviewed invariant)

1. `r2/narrative_lifecycle/ports.py` was created in Task 12, not Task 13 — the
   SQLAlchemy unit of work needs the protocol seam. Task 13 extended the same file.
2. Two test files renamed: `tests/unit/r2/narrative_lifecycle/test_lifecycle_hashing.py`
   (plan: `test_hashing.py`) to avoid a pytest prepend-import basename collision with
   `tests/unit/r2/narrative/test_hashing.py` (same precedent as M5C-1A's
   `test_plan_hashing.py`); `tests/unit/r2/narrative_lifecycle/test_coverage_rules.py`
   (plan: `test_coverage.py`) because `scripts/audit_tests.py` rule 4 flags a `_coverage`
   filename suffix.
3. `server` could not be added to an import-linter `forbidden_modules` list —
   `root_packages = ["lib", "r2"]` makes `server` external, which needs a global
   `include_external_packages` toggle. The `lib.db` bans already fence persistence.
4. `admit_compilation` / `record_successful_compilation` / `record_compilation_without_delta`
   are not on `NarrativeLifecycleEvidenceService` yet: their contracts
   (`CompilationAttempt` / `CompilationResult`) do not exist until the compilation
   checkpoint. The plan lists them under Task 13's interface with "(Task 24)".
5. `scripts/r2/verify_m5c_scope.py` and its unit test were extended for the M5C-1B blast
   radius (allowlist + the one evidence migration + the `R2_M5C_1_REVIEW.md` handoff
   doc). Task 14 Step 3 invokes the verifier but the plan File Map only assigned the
   script to checkpoint 1A. The operator chose to make it checkpoint-aware rather than
   skip the gate.

## Gates at `f0b27dcd`

```
uv run ruff check .                                    All checks passed!
uv run ruff format --check .                           1336 files already formatted
uv run basedpyright --warnings                         0 errors, 0 warnings, 0 notes
uv run lint-imports                                    14 kept, 0 broken
uv run deptry lib server alembic scripts tests r2      Success! No dependency issues found.
uv run python scripts/audit_tests.py --check           0 violations
uv run python scripts/r2/verify_m5c_scope.py --base 32e10857 --head f0b27dcd --phase impl   exit 0
git diff --check 32e10857..f0b27dcd                    clean

uv run python -m pytest -n4 --dist loadfile \
  tests/unit/r2 tests/unit/lib/db tests/integration/r2/narrative \
  tests/integration/r2/narrative_plan tests/integration/r2/narrative_lifecycle \
  tests/integration/lib/db tests/integration/donor_parity
                                                       1183 passed, 1 skipped
```

The one skip is the PostgreSQL-only basis-FK enforcement test on the SQLite engine
(foreign keys disabled there per `tests/conftest.py`). The same suites run green against
the isolated PostgreSQL 18 instance (`DATABASE_URL="$POSTGRES_TEST_URL"`), where the
migration up → down → up round-trip also exits 0.

Baseline on `origin/r2/main` was 12774 passed / 2 skipped; M5C-1A added 170 tests; M5C-1B
adds the evidence contract / coverage / hashing / model / migration / repository /
evidence-service / scope-verifier suites on top.

## Not done / out of scope

- `admit_extraction` fails closed; the real currentness guard is a later checkpoint.
- Compilation evidence-service methods and their contracts are a later checkpoint.
- No push, no merge, no operating migration run, no worker / provider / network call.
  The isolated Docker PostgreSQL 18 (`m5c-pg18-test`) is used for migration round-trip
  and dialect-sensitive tests only.

## Verdict

**ACCEPTED.** Both self-review axes' actionable findings are applied in `f0b27dcd` and
re-verified; the two "verified — not a defect" findings are recorded above. Every gate is
green at the frozen head. This document and the two `/code-review` sub-agent reports are
the review of record for M5C-1 (final). Task 15 (M5C-2) starts from the evidence-only
handoff commit that adds only this file.
