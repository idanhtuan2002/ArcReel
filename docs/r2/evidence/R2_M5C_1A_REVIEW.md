# R2-M5C-1A Review — versioned M5 compatibility, F9/R9/R10, scene omniscient gate, donor parity

**Review type:** independent Codex review (rounds 1–2) followed by a two-axis
self-review (`/code-review`: Standards + Spec sub-agents), accepted as the review of
record. Codex hit its account usage limit part-way through round 3; the operator
directed skipping Codex and completing the review as a self-review, as was done for
M5B (`docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md:797` expected a
per-checkpoint Codex `APPROVED`).

**Checkpoint frozen head:** `ba172725cb3564b1188844d41243c9eddad54ee0`
("refactor(r2): apply self-review findings to the M5C-1A blast radius").
**Branch:** `feat/r2-m5c-narrative-lifecycle`.
**Base:** `ab9cbae07d82b7d2b1283f8973593f093efc84a6` (M5C document-materialization head,
one commit above the accepted R2 integration base `origin/r2/main` `71a96bd6`).
**Diff:** `git diff ab9cbae0..ba172725` — 50 files changed, +4576 / −39.

## Implementation commits (`ab9cbae0..ba172725`)

```
59368dd5 docs(r2): pin M5C implementation starting state                  (Task 0)
c32a24f6 feat(r2): add v2 SceneContract relationship and thread semantics (Task 1)
69614be0 feat(r2): dispatch v1/v2 narrative plan hashing                  (Task 2)
fcec3579 feat(r2): add the versioned relationship fact-key mapping        (Task 3)
c799dc10 feat(r2): validate relationship constraints and exact references (Task 4)
d16cf190 feat(r2): validate plan-wide thread lifecycle in presentation order (Task 5)
3ecd8b0e style(r2): sort imports in test_relationship_facts
79c585f5 feat(r2): gate no-POV author draft on the scene contract         (Task 6)
7b683429 feat(r2): port the huohuo change-record parser with node parity  (Task 7)
b111804b feat(r2): port novel-studio hard rules with node parity          (Task 8)
30d880c6 test(r2): fence the M5C-1A compatibility blast radius            (Task 9)
fa20fc8b chore(r2): keep vendored donor sources byte-exact               (Task 9)
ba3b2b8c fix(r2): match ECMAScript whitespace and case-folding in the donor ports   (Codex R1 #2,#3)
731c621e feat(r2): commit v2 NarrativePlans through the real authority path          (Codex R1 #1)
fe8d0987 fix(r2): harden the v2 plan envelope discriminator and selector coherence   (Codex R2 #1,#2)
be04e4a0 fix(r2): full ECMAScript regex semantics in the Huohuo port                 (Codex R2 #3)
ba172725 refactor(r2): apply self-review findings to the M5C-1A blast radius         (self-review)
```

## Selectors / golden vectors (unchanged domains)

```
r2-scene-contract-content-v1 / -v2      r2-narrative-plan-v1 / -v2
r2-narrative-plan-content-v1 / -v2      r2-relationship-fact-key-v1      r2-canon-delta-v1 (reused)
```

- v1 scene semantic hash golden `sh:66c8077044977a3fa1245bb4db66a803c5ed0da5502f208e99feb0267acafd24`
  and v1 plan content hash golden `np:133bf9df6dd1fe175abe1967efa2f657a80bee184100d98c91d9ae26acf28af5`
  are preserved (`tests/unit/r2/narrative_plan/test_hashing_v2.py`,
  anchors now in `tests/unit/r2/narrative_plan/_helpers.py`).
- `NarrativePlanContent` JSON schema sha256
  `593f1aeae9678b5de7cb3eedeef34e7486b0df9382ec012dc8dc74e0f905cb57` is byte-stable
  after the `NarrativePlanContentValue` union widening
  (`tests/unit/r2/contracts/test_narrative_plan_v2.py::test_v1_narrative_plan_wrapper_bytes_are_stable_after_the_union_widening`).
- `relationship_fact_predicate("hero", "trust_level")` golden
  `r2rel:20ca2e58dc593e529822b294b398285d42a00fb92a5b10fa63eb157c96b1fa3b`.
- `SceneContract` / `NarrativePlanContent` v1 classes are byte-identical to `ab9cbae0`;
  `git diff --check` over the range is clean.

## Donor parity (R2-DEC-031)

`docs/r2/evidence/R2_M5C_DONOR_BASELINE.json` pins exactly two Python ports:

| Port | Donor pin | Source SHA-256 |
|---|---|---|
| `r2/narrative_lifecycle/changeset_parser.py` (7 selected exports) | `appolloqin/huohuo-drama@f104b853b3563e124d9cde25f9331d323fb483b9` `workbench-server/src/common/novel/novel-change-record.ts` | `dd3a310e1d83f80fca132a6ea64380c3d953c780054d0ea93e9f865c09fb5088` |
| `r2/narrative_lifecycle/continuity_rules.py` (`runHardRuleChecks`, `mergeContinuityReports`) | `YfengJ/novel-studio-ai@9b690ae2e2f6921f9bd2782b42cef53c1662ad3b` `src/lib/continuity/hardRules.ts` | `7756c4093b52e11e3f591c58af1719887428fd5e437f4ade0828533ac3663954` |

The vendored `.ts` files (plus Huohuo's transitive `novel-memory-parser.ts`, present only
so the change-record module `import()`s in its source-tree context — sha256
`245ac53336abc14bb65e0f861675d57a7223b28a10ade72cbfc0d9fd7cd4e88c`) live under
`tests/integration/donor_parity/vendor/`, kept byte-exact by `.gitattributes`.
`tests/integration/donor_parity/{huohuo_change_record,novel_hard_rules}_runner.mjs` verify
each source SHA-256 before `import()`, execute the **unmodified** donor through a
test-only `tsx` Node loader, and the Python port is asserted equal on a canonical corpus:
**56 Huohuo cases** (12 realistic prose fixtures + header/fake/orphan/echo/CRLF branches +
`ws_*` BOM/U+001C/NBSP + `u16_*` astral-`因果` + `lone_surrogate_*` + `header_after_*`
CR/LS/PS vectors) and **17 Novel Studio cases** (rule hit/miss, resurrection gate,
empty/hard-only/soft-only/combined, severity, stable merge ordering, missing-field skips,
`casefold_*` İ/ı/ſ vectors). `stripNovelChangeRecord` is the one excluded Huohuo export
(it needs the unselected chapter-end-meta module). The harness is never imported by any
`r2/**` runtime module (AST fitness `tests/unit/r2/test_m5c_architecture_boundaries.py`).

## Review trail

### Codex round 1 (`fa20fc8b`) — CHANGES REQUIRED, 3 HIGH — all RESOLVED

1. **v2 SceneContract/thread work had no operational path** — `NarrativePlanRevisionProposal`
   / `NarrativePlan` / `NarrativePlanVersionSnapshot` only accepted v1 content, and an
   `isinstance(scene, SceneContract)` guard skipped version-lineage validation for v2.
   → `731c621e`: `NarrativePlanContentValue` union; `compute_plan_content_hash_dispatch`;
   `require_plan_schema_transition` + per-scene `require_scene_schema_transition` run in
   `NarrativePlanService._validate_content` against ordered committed history before any
   write; `validate_scene_version` accepts `SceneContract | SceneContractV2`;
   `_build_plan` / `_version_snapshot` derive the persisted selectors from the content;
   Task 5 integration tests added (clean v2 plan commits + round-trips as v2, broken
   thread lineage rejected with zero writes, v2→v1 downgrade rejected).
2. **Huohuo port not byte-parity outside the corpus** — Python `str.strip()`/`\s`
   include U+001C–U+001F and NEL and exclude U+FEFF; ECMAScript is the opposite.
   → `ba3b2b8c`: explicit JS whitespace class `_W` for every `\s`, `_js_trim` over the
   exact ECMAScript WhiteSpace+LineTerminator set, `_utf16_length` for the `< 360`
   echo-marker offset; +8 `ws_*` adversarial vectors.
3. **Novel Studio port Unicode case folding** — Python `re.IGNORECASE` folds U+0130 /
   U+0131 / U+017F; ECMAScript `/i` (no `u`) does not. → `ba3b2b8c`:
   `re.IGNORECASE | re.ASCII`; +3 `casefold_*` vectors.

### Codex round 2 (`731c621e`) — CHANGES REQUIRED, 3 NEW HIGH — all RESOLVED

1. **Widened discriminator tightened v1 input** — a `proposed_content` dict without
   `schema_version` was accepted at `fa20fc8b` but rejected `union_tag_not_found` at
   `731c621e`. → `fe8d0987`: callable `Discriminator` (`_selector_tag`) — a genuinely
   absent selector falls back to the v1 `Tag`; an explicit unknown tag still fails
   closed (no matching member).
2. **Persisted selector tuples not cross-validated** — `NarrativePlan(content=V2,
   content_hash_version=V1)` and `NarrativePlanVersionSnapshot(schema_version=V1,
   content=V2, …)` both constructed, so a corrupt v2 row could be read as a v1
   predecessor and defeat the aggregate downgrade ratchet. → `fe8d0987`:
   `model_validator`s on both aggregates enforce the one allowed
   `(outer schema_version, content schema, content-hash selector)` tuple; the
   repository already maps the resulting `ValidationError` to a corrupt-row error.
3. **Huohuo port still not byte-exact** — `\S{4,}` counts code points not UTF-16 units
   (`因果:😀😀`); `_utf16_length` raised on a lone surrogate; Python `re.MULTILINE`
   ≠ ECMAScript `/m` boundaries (CR / U+2028 / U+2029). → `be04e4a0`: the `因果` value
   run is captured and re-measured with `_utf16_length` (UTF-16 units);
   `errors="surrogatepass"`; `_BOL = (?:\A|(?<=[\n\r  ]))` replaces the five
   `re.MULTILINE` regexes; +8 `u16_*` / `lone_surrogate_*` / `header_after_*` vectors;
   corpus switched to `ensure_ascii=True` so lone surrogates round-trip.

### Codex round 3 (`be04e4a0`) — aborted

Codex hit its account usage limit after reading the delta and running one probe; no
verdict. Operator directed skipping Codex.

### Self-review (`/code-review`, base `ab9cbae0`) — findings applied in `ba172725`

**Spec axis** — no blocking finding. Applied:

- **Dispatch fail-closed** — design §4.3.1 "Version-dispatched hash functions reject an
  unknown selector"; `compute_scene_semantic_hash_dispatch` /
  `compute_plan_content_hash_dispatch` now raise `NarrativePlanSchemaVersionError` on an
  unknown or type-mismatched selector rather than falling back to v1.
- **Thread-lifecycle finding sort** — plan Task 5 Step 3 "sort findings by
  `(rule_id, affected_refs, sequence_index)`"; the custom `THREAD_LIFECYCLE_RULE_ORDER`
  enum + index were removed, sort is now lexical `(rule_id, affected_refs)`
  (`affected_refs` already carries scene id + constraint id + thread ref, so the tuple
  is unique and the `sequence_index` tiebreak is unreachable).
- **`NarrativeThreadLifecycleError`** — design §13 lists it as the failure for
  "plan-wide presentation-order thread invariants fail". The service now raises it
  (exported from `r2/narrative/__init__.py`) instead of the generic
  `NarrativePlanValidationError`, which also removes the dead placeholder class the
  Standards axis flagged. Deviation from plan Task 5 Step 3's literal
  "`raise NarrativePlanValidationError`" in favour of the design's error taxonomy.
- **v1 byte-stability tests** added for `NarrativePlanContent` JSON schema and a v1
  `NarrativePlan` / version-snapshot round-trip after the union widening.

Not applied (documented):

- `require_scene/plan_schema_transition` have no hash parameter, so the plan Task 2
  Interface clause "or a supplied hash that does not match the selected byte domain" is
  not enforced *in the named function*. It was implemented per the plan's own Step 3
  code sketch and signatures, and is enforced end-to-end at the service seam
  (`commit_revision` recomputes via `compute_*_hash_dispatch` and rejects a mismatch
  before any write). Low severity.
- `validate_scene_relationship` emits a `RELATIONSHIP_INTEGRITY` **finding** for
  non-character / unknown endpoints. Plan Task 4 bullet says "(else
  `NarrativeRelationshipIntegrityError`)", but design §4.3.2 says "finding" and the
  plan's own RED test snippet asserts a finding. The plan bullet is internally
  inconsistent; the implementation follows the design and the plan's tests.

**Standards axis** — applied:

- Reworded the two temporal phrasings ("does not exist yet" / "until … exists") in the
  omniscient-gate docstring and the finding-id comment.
- `.gitattributes` comment describes the mechanism, not the gate id.
- `V1_GOLDEN_SCENE` / `V1_GOLDEN_SCENE_HASH` / `V1_GOLDEN_PLAN_HASH` moved to
  `tests/unit/r2/narrative_plan/_helpers.py`; no test module imports another test
  module.
- `_selector_tag(value, field, default)` extracted, shared by `_scene_contract_tag`
  and `_plan_content_tag`.
- `import hashlib` hoisted to module top in `test_huohuo_change_record.py`.

Not applied (repo convention overrides the baseline): `ADR` / decision-id / milestone
references in comments — `pyproject.toml` uses `# M4-D12：` / `# M5A：` / `# M5B：`
prefixes on every import-linter contract; `lib/db/models/canon.py` docstring names
`ADR-0075`; `scripts/r2/verify_m5b_scope.py` names its checkpoint. The one duplicated
hash payload block (`compute_plan_content_hash` vs `_v2`) is deliberate — it keeps the
v1 byte domain frozen.

## Deviations from the plan (all recorded; none change accepted v1 behaviour)

1. Test file names follow the real repo files (`test_plan_hashing.py`,
   `test_plan_validation.py`) rather than the plan's literal `test_hashing.py` /
   `test_validation.py`.
2. Donor parity lives at `tests/integration/donor_parity/`, not `tests/donor_parity/`
   — a repo invariant (`tests/conftest.py`) requires tests under
   `tests/{unit,integration,e2e}/`.
3. **Operator-approved:** `tests/integration/r2/test_m5b_acceptance.py` — 4 no-POV
   `AUTHOR_DRAFT` compile calls became POV'd `AUTHOR_DRAFT`. The omniscient gate makes
   every no-POV `AUTHOR_DRAFT` terminal; the retrieval / visibility / leak paths those
   tests exercise are unchanged by the POV. That path's dedicated coverage is
   `tests/unit/r2/narrative_context/test_omniscient_gate.py`.
4. **Operator-approved:** the two donor `.ts` files (+ transitive dependency) were
   fetched from the pinned GitHub revisions and vendored with SHA-256 pins and a
   `.gitattributes` entry.
5. `NarrativeError` base class introduced in `r2/narrative/errors.py` (the plan wrote
   `(NarrativeError)` for three new errors without defining it).
6. **Operator-approved (chose "build the v2 commit path"):** the full v2 NarrativePlan
   commit path — `NarrativePlanContentValue` union on
   proposal/plan/snapshot, two-member `schema_version` / `content_hash_version`
   Literals, schema-ratchet wiring in `NarrativePlanService`, selector-coherence
   validators, and a Task 5 `test_service.py` integration test. Plan Task 1 "Produces"
   named only `NarrativePlanContentV2`; the plan's own Task 5 said the service runs the
   pass "for v2 content only" but no task made v2 content reachable through the
   proposal. v1 serialized bytes are preserved by construction.
7. `r2/narrative_context/ports.py` `get_exact_scene` and the internal compiler scene
   params widened to `SceneContractValue` so the v2 omniscient gate is reachable
   (plan Task 6 named only `compiler.py` + `errors.py`).

## Gates at `ba172725`

```
uv run ruff check .                                    All checks passed!
uv run ruff format --check .                           1319 files already formatted
uv run basedpyright --warnings                         0 errors, 0 warnings, 0 notes
uv run lint-imports                                    13 kept, 0 broken
uv run deptry lib server alembic scripts tests r2      Success! No dependency issues found.
uv run python scripts/audit_tests.py --check           0 violations
uv run python scripts/r2/verify_m5c_scope.py --base ab9cbae0 --head ba172725 --phase impl   exit 0
git diff --check ab9cbae0..ba172725                    clean
uv run python -m pytest -n 4 --dist loadfile           12944 passed, 2 skipped
```

Baseline on `origin/r2/main` was 12774 passed / 2 skipped; M5C-1A adds 170 tests. No
Alembic migration in this checkpoint (migrations begin in M5C-1B).

## Not done / out of scope

- The v2 SceneContract / relationship / thread feature is wired end-to-end through
  `NarrativePlanService.commit_revision` but no other layer consumes a v2 plan yet;
  the combined M5 v1/v2 acceptance corpus lands in M5C-4 Task 31.
- No push, no merge, no operating migration, no worker / provider / network call.

## Verdict

**ACCEPTED.** All 6 findings across Codex rounds 1–2 are resolved and re-verified;
the two-axis self-review's actionable findings are applied in `ba172725`; every gate is
green at the frozen head. Codex round 3 was waived by the operator (usage limit). This
document and the Codex round 1–2 transcripts are the review of record for M5C-1A.
Task 10 (M5C-1B) starts from the evidence-only handoff commit that adds only this file.
