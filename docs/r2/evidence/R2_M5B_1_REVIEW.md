# R2-M5B-1 Review — Canon schema v2, epistemic state, temporal validation

**Review type:** two-axis self-review (`/code-review`: Standards + Spec sub-agents).
Codex was over its usage limit; this stands in for the per-checkpoint Codex
review the plan expected (`docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md:626`).
The self-review ran once against the whole M5B branch (`698c34f6...HEAD`); this
document extracts the findings that fall in the M5B-1 scope.

**Checkpoint frozen head:** `2a99ede1` ("feat(r2): complete M5B Canon schema v2").
**Branch:** `feat/r2-m5b-epistemic-plan-context`. **Base:** `698c34f6` (accepted M5A integration head).

## Scope

`r2/contracts/narrative.py` (+ `r2/contracts/__init__.py`), `r2/narrative/`:
`schema_upgrade.py`, `hashing.py`, `canon_state.py`, `temporal.py`, `epistemic.py`,
`validation.py` (Canon rules), `canon_transaction.py`, `canon_resolver.py`,
`integrity.py`, `errors.py`, `__init__.py`; tests
`tests/unit/r2/contracts/test_narrative_v2.py`,
`tests/unit/r2/narrative/test_schema_upgrade.py`, `test_hashing.py`,
`test_canon_state.py`, `test_temporal.py`, `test_epistemic.py`,
`test_validation_m5b.py`, `test_canon_architecture_boundaries.py`,
`tests/integration/r2/narrative/test_canon_v2_replay.py`.

## Selectors / golden hashes (unchanged domains)

```
r2-canon-content-v1   r2-canon-delta-v1   sha256
r2-canon-schema-v1  (Entity/Fact/Event maps only)
r2-canon-schema-v2  (+ epistemic_propositions_by_ref / knowledge_states_by_id / temporal_relations_by_id)
r2-epistemic-proposition-v1
```

M5A v1 golden content hash `56ebc632b669dae6db6c643a56fe1992def05f00af5e1dc5195b81f8d45a0484`
is preserved by `test_schema_upgrade.py::test_v1_content_hash_ignores_the_v2_default_maps`.
`git diff --check 698c34f6...2a99ede1` is clean.

## Spec axis

No blocking finding in the M5B-1 scope.

Verified correct against the design:
- Canon v1 content hash is byte-stable across schema v2 — the v1 selector emits
  only the Entity/Fact/Event maps (`r2/narrative/hashing.py`, design §5.1).
- Temporal validation covers cycle / anchor contradiction / duplicate normalized
  key / self / missing relation (`r2/narrative/temporal.py`, design §5.3).
- `EpistemicViewResolver` is fail-closed: 0 active → absent, 1 → selected, >1 →
  `EpistemicIntegrityError`; it never falls back to the latest row
  (`r2/narrative/epistemic.py`, design §5.4).
- `UPDATE_KNOWLEDGE` closes only the named prior state and cannot derive the
  transition instant from transaction or evidence time; provably-future evidence
  is rejected (`EPI_EVIDENCE_FUTURE`).
- A v2→v1 downgrade delta and an unknown schema selector fail closed.

## Cross-note (raised by the Standards axis, investigated here)

`r2/narrative/canon_transaction.py` passes `CanonValidationReport(findings=())` on
the successful-commit path instead of the `report` it computes. **Not a
regression.** At M5A `CanonValidationReport.ok` is `not findings`, so a commit
that passed the `report.ok` gate always carried an empty report, and
`_resolve_exact_retry` has returned an empty report since M5A. M5B's
`validate_canon` now returns a `NarrativeValidationReport` whose non-blocking
`WARNING` findings have no field on the M5A `CanonValidationReport` /
`CanonCommitResult` contract (kept byte-identical per `R2_M5B_FINAL_VERIFICATION.md`
deviation #4). No caller reads `CanonCommitResult.validation_report`; ADR-0075
does not require it. Recorded in deviation #4. Fixed range: n/a (no change).

## Standards axis (all non-blocking judgement-calls; deferred)

- "Known Canon schema selectors" set redefined as bare literals in `hashing.py`,
  `integrity.py`, `schema_upgrade.py`, `canon_resolver.py` — adding a future
  schema edits 4+ files (Shotgun Surgery).
- Canonical-JSON→sha256 helper reimplemented (`_sha` in the compiler,
  `_canonical_json_bytes` in `contracts/narrative.py`, and siblings) rather than
  the exported `canonical_json_bytes` (Duplicated Code).
- Half-open-interval predicate repeated (`_active_at` vs `_is_active` vs
  `_point_in` vs `_covers`).
- `r2/narrative/validation.py` carries M5A-compat, M5B epistemic/temporal, and
  SceneContract rules in one file (Divergent Change, +585 in the M5B range).
- `_mb_finding` mysterious name; `_view_for` builds a `branch_id="scene-eval"`
  sentinel `ResolvedCanonView` to reuse the resolver.

Disposition: deferred as one `/simplify` pass (`R2_M5B_FINAL_VERIFICATION.md`
deviation #10). None is a documented-standard breach; tooling-enforced items
excluded.

## Gates

Full gates at the post-self-review head `62b07b4a` are recorded in
`R2_M5B_FINAL_VERIFICATION.md` (Post-verified section): ruff / ruff format /
basedpyright 0/0/0 / lint-imports 12 kept / deptry / audit_tests / `pytest -n 4`
12774 passed / 2 skipped; single alembic head `5b7c4a0e0001`.

## Verdict

**APPROVED (self-review).** No blocking Spec finding in M5B-1; the Standards
cross-note is dismissed with analysis; Standards smells are deferred cleanup.
The frozen head `2a99ede1` remains a valid target for a later Codex re-review.
