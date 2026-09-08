# R2-M5B-3 Review — NarrativeContextCompiler leakage, budget, determinism

**Review type:** two-axis self-review (`/code-review`: Standards + Spec sub-agents).
Codex was over its usage limit; this stands in for the per-checkpoint Codex
review the plan expected (`docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md:1161`).
The self-review ran once against the whole M5B branch (`698c34f6...HEAD`); this
document extracts the findings that fall in the M5B-3 scope, including the fix
and the deferral decided after the frozen head.

**Checkpoint frozen head:** `f848c085` ("feat(r2): compile visibility-safe narrative context").
**Branch:** `feat/r2-m5b-epistemic-plan-context`. **Base:** `698c34f6`.

## Scope

`r2/contracts/narrative_context.py`, `r2/narrative_context/` (`compiler.py`,
`ports.py`, `errors.py`, `__init__.py`); tests
`tests/unit/r2/contracts/test_narrative_context.py`,
`tests/unit/r2/narrative_context/test_compiler.py`,
`tests/unit/r2/test_m5b_architecture_boundaries.py`, and the compiler paths in
`tests/integration/r2/test_m5b_acceptance.py`.

## Spec axis

### Finding (1) — compiler version not pinned at the seam — FIXED

`NarrativeContextCompiler.compile` accepted any `compiler_version` string and
stamped it into the pack unchecked, so `"latest"` or an unknown selector produced
a deterministic-looking but unversioned pack. Design §10.1 (`:747`), §11 (`:941`
`NarrativeSchemaVersionError`), §16 (`:1136` "Compiler accepts exact versions
only").

Fixed at `47850876` ("fix(r2): pin compiler version at the narrative context
seam"): `SUPPORTED_COMPILER_VERSIONS = frozenset({"compiler-v1"})`; `compile()`
raises `NarrativeSchemaVersionError` (reused from `r2/narrative/errors.py`) for
`"latest"` or any unlisted value **before any authority read**. +3 unit tests.

### Finding (2) — AUTHOR_DRAFT omniscient-authoring POV gate absent — DEFERRED

Design §10.1: "`AUTHOR_DRAFT` may omit POV only for omniscient authoring
explicitly permitted by the SceneContract and policy." `compiler.py` returns no
POV view whenever `pov_subject_entity_id is None` and consults no permission.

Source research: `docs/research/2026-09-08-r2-m5b-author-draft-omniscient-gate.md`.
The mechanism is undocumented (§10.1 is the sole statement; the plan doc is
silent); the reuse research lists "whether author-only truth may be emitted at
all, and to whom" as an unresolved design question; the "and policy" half is
unimplementable in M5B (opaque `(source_ref, content)` policy read seam, no typed
`CreativePolicy`, CreativePolicy write authority out of scope, §17). Enforcing the
SceneContract half alone forces a `SceneContract` `semantic_hash_version` v1→v2
bump.

Deferred (operator decision) to the milestone that models `CreativePolicy`.
Recorded as `R2_M5B_FINAL_VERIFICATION.md` deviation #9. Risk is low: AUTHOR_DRAFT
already carries `AUTHOR_TRUTH` by design (§10.3); the gate is an explicit-opt-in
requirement for the no-POV author path, not a containment boundary, and no
downstream consumer of AUTHOR_DRAFT exists before M5C.

### Verified correct

- Filtering strictly precedes ranking and budgeting: a retrieval score can never
  recover a segment rejected by authority, scope, time, or visibility.
- A falsified secret descriptor (prose ≠ declared hash) is omitted
  `MISSING_SOURCE_METADATA`; a wrong/inactive KnowledgeState ref is
  `NOT_VISIBLE`; neither trace carries prose, content hash, or token count
  (MUT-07 / MUT-08).
- `EpistemicViewResolver` with >1 active state raises `EpistemicIntegrityError`;
  the compiler never falls back to the latest row (MUT-12 path).
- Dedupe on `(source_ref, content_hash)`; mandatory-tier overflow raises
  `NarrativeContextBudgetError` with no partial pack; `context_pack_id` /
  `content_hash` are deterministic and budget-sensitive.
- No write port, unit-of-work factory, provider, runtime, or donor-memory import
  in `r2.narrative_context` (import-linter + AST fitness).

## Standards axis (non-blocking judgement-calls; deferred)

- `_sha` in the compiler reimplements the canonical-JSON→sha256 helper rather than
  the exported `canonical_json_bytes` (part of the 4× duplication).
- Half-open predicate `_covers` duplicates the `_point_in` / `_active_at` family.
- EpistemicView's four buckets are re-enumerated as `_POV_CHANNEL` + `getattr`
  in the compiler and again in `validation.py` (Repeated Switches).
- `RetrievalCandidate.score` is never read by the compiler.

Disposition: deferred `/simplify` pass (`R2_M5B_FINAL_VERIFICATION.md` deviation #10).

## Gates

Recorded in `R2_M5B_FINAL_VERIFICATION.md` (Post-verified section), head
`62b07b4a`: all static gates green; `pytest -n 4` 12774 passed / 2 skipped;
single alembic head `5b7c4a0e0001`.

## Verdict

**APPROVED (self-review) after the finding-(1) fix at `47850876`.** Finding (2)
is a recorded deferral, not a blocker. The frozen head `f848c085` plus the
`47850876` version-pin delta are valid targets for a later Codex re-review.
