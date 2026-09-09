# R2-M5B `validate_scene` plan-commit rule inventory

Research question: does `NarrativeInvariantValidator.validate_scene` in
`r2/narrative/validation.py` implement the SceneContract plan-commit validation
rules the M5B design requires? Produce an evidence-cited inventory of design/plan
requirements vs. current code so a follow-up TDD pass can close exactly the gaps.

All paths are relative to the worktree `/home/anhtuan/content-production-os-m5b`.
Line numbers are as of `git rev-parse HEAD` = `819ab679` on branch
`feat/r2-m5b-epistemic-plan-context`.

## 0. Verdict on the review's specific claims

| Review claim | Verdict | Evidence |
|---|---|---|
| `validate_scene` only checks: entry-state constraints, a forbidden-knowledge sweep, and event required/forbidden **selector** collision | **CONFIRMED** | `r2/narrative/validation.py:513-537` — the method body has exactly three `findings.extend(...)` blocks: entry-state (`:519-522`), forbidden-knowledge (`:523-526`), event selector collision (`:527-536`). Nothing else. |
| Does NOT check Character-reveal entry preconditions | **CONFIRMED** | `validate_scene` never reads `scene.required_reveals`. The only reveal handling is in `validate_scene_outcome` at `r2/narrative/validation.py:596-621`, keyed off the post-scene `before`/`after` views, not commit. |
| Does NOT check required-event static satisfiability against `canon_basis` | **CONFIRMED** | `scene.required_events` is consumed only to build the `required_keys` set for the collision test (`r2/narrative/validation.py:527`). No lookup of any selector against `canon.content` happens in `validate_scene`. |
| Does NOT check required-vs-forbidden collision for **state** constraints | **CONFIRMED** | The collision loop (`r2/narrative/validation.py:528-536`) iterates `scene.forbidden_events` against `required_keys` built from `scene.required_events` only. `entry_state_constraints` / `exit_state_targets` / `forbidden_knowledge` are never cross-compared. |
| The `plan` argument is discarded (`_ = plan`) | **CONFIRMED** | `r2/narrative/validation.py:516` — `_ = plan`. (Same pattern in `validate_scene_outcome` at `:548`.) |

All five claims are accurate. `docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md:122`
already records this as an open self-review finding, in nearly identical words:
"`NarrativeInvariantValidator.validate_scene` under-implements the §9-step-6
plan-commit rules (Character-reveal entry preconditions, required-event static
satisfiability, required/forbidden state-constraint collision)."

## 1. Design / plan requirements (quoted)

### Spec — `docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md`

Rule families (`:339-351`):

```
:348 | `SCENE_ENTRY_*` | typed Fact/Knowledge entry constraint fails at the exact entry instant |
:349 | `SCENE_KNOWLEDGE_*` | forbidden interval overlap, reveal precondition, false-belief mismatch |
:350 | `SCENE_EVENT_*` | unsatisfiable selector, required/forbidden collision, indeterminate forbidden Event time |
:351 | `SCENE_EXIT_*` | post-scene Fact/Knowledge target or reveal outcome is not satisfied |
```

`:337` — "Commit gates treat every `ERROR` as blocking. A required `SceneContract`
constraint cannot be downgraded to warning by a caller."

SceneContract constraint rules (`:517-535`):

- `:519` — "every `entry_state_constraints` item must match the exact Canon basis at entry;"
- `:520` — "every `exit_state_targets` item is a required post-scene target evaluated at exit by outcome validation;"
- `:521-522` — "a `forbidden_knowledge` item is violated if its state set, or absence when `include_absent=true`, matches at any instant in the scene window;"
- `:523-524` — "every `required_events` selector must match at least one Event in a post-scene candidate; every `forbidden_events` selector must match none;"
- `:525-528` — "an exact `event_ref` must resolve to that Event. A pattern requires `event_type`; all named participants must be present and a named location must equal the Event location. Outcome matching requires the Event's direct temporal anchor to fall inside the scene window; an unanchored candidate cannot satisfy a required selector ..."
- `:529-532` — "`PRESENT`/`ABSENT` inspect active Facts ... `EQUALS`/`NOT_EQUALS` compare canonical JSON values. `NOT_EQUALS` requires at least one active Fact ..."
- `:533-534` — "a Knowledge constraint matches one active state in `states`; zero active states match only when `include_absent=true`; multiple active states are an integrity error;"
- `:535` — "the same normalized constraint cannot appear in both a required and forbidden list."

Reveal preconditions (`:537-542`):

- `:537-538` — "For a Character reveal, the recipient must not already have the requested resulting state at entry and must have it at exit in a post-scene candidate."
- `:538-542` — audience reveals are presentation intent for `STORY_AUDIENCE`, recorded by `AudienceRevealEvidence`; "it never creates a Canon entity or KnowledgeState."

Plan-commit scope statement (`:544-551`):

- `:544-546` — "A reveal and every required Event or exit target remain authorial obligations until an accepted narrative revision produces the separately approved Canon delta or accepted-narrative evidence needed to validate the outcome. Compiling or approving a SceneContract cannot create an Event, Fact, or KnowledgeState."
- `:548-551` — "Plan commit validation checks exact references, entry conditions, typed shapes, normalized duplicates, and static satisfiability against `canon_basis`. It does not claim that future exit obligations are already fulfilled. Pure post-scene outcome validation checks the required/forbidden Event selectors, reveal recipients, and exit targets against explicit exact pre-scene and post-scene inputs."

§9 step 6 — the commit sequence (`:702-709`):

- `:702-704` — "Resolve the exact scoped `canon_basis`; run `NarrativeInvariantValidator.validate_scene()` for every SceneContract and require zero blocking findings, then validate hierarchy, refs, scene identity/version rules, approval uniqueness, and content hash."
- `:708-709` — "The Canon read is exact and read-only. Plan approval cannot fall back to the Canon head. Outcome-only obligations are checked for static satisfiability at commit and are not misreported as already fulfilled."

Entry/exit evaluation instants (`:461-462`): "Entry is evaluated at
`effective_from`; exit is evaluated at `effective_until`."

Acceptance references: `:1041` — "exact Canon basis checked read-only by
`validate_scene()` before append, with no head fallback;"; `:1038` — "typed Fact,
Knowledge, Event, Reveal, and temporal-window constraint matrices;". Adversarial
mutation MUT-11 (`:1098`): "Make an entry constraint invalid only on the pinned
Canon basis while head remains valid | plan commit rejected; no head fallback".

### Plan — `docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md`

Task 7, Step 5 (`:782-784`) is the step that builds `validate_scene`:

`:784` — "Extend `NarrativeInvariantValidator` with the exact
`validate_scene(canon, plan, scene)` and
`validate_scene_outcome(before, after, plan, scene, audience_reveal_evidence)`
signatures from the spec. `validate_scene` evaluates entry at `effective_from`;
interval-forbidden Knowledge detects any overlap; Event selectors use exact event
refs and the required scene window; exit targets are evaluated at
`effective_until`; required reveals distinguish character state from
`AudienceRevealEvidence`. Indeterminate timing of a forbidden Event is blocking,
not silently absent. Return the shared sorted `NarrativeValidationReport` rule
families from the spec."

Task 7 acceptance test list (Step 2, `:761`): "Cover new scene version 1,
byte-identical scene retaining its version, changed semantic hash exactly +1,
removal preserving history, no ID/version reuse, hierarchy cycle/missing
child/illegal parent/child asymmetry, one parent per non-root, and duplicate
`sequence_index`." — note this list is entirely identity/hierarchy; it names **no**
`validate_scene` constraint cases. Step 3 RED command (`:766`) only runs
`tests/unit/r2/contracts/test_narrative_plan.py tests/unit/r2/narrative_plan`.

Plan §"File and Responsibility Map" (`:48`): `r2/narrative/validation.py` = "Pure
`NarrativeInvariantValidator` Canon and SceneContract rule families".
Plan global constraint (`:19`): `NarrativePlanService` "validates every
SceneContract on `canon_basis` before persistence."

## 2. What the code actually does

### `validate_scene` — `r2/narrative/validation.py:513-537`

```
513  def validate_scene(self, *, canon, plan, scene) -> NarrativeValidationReport:
516      _ = plan
518      window = scene.temporal_window
519-522  for item in scene.entry_state_constraints:
             _scene_state_finding(canon, item, at=window.effective_from, phase="ENTRY")
523-526  for item in scene.forbidden_knowledge:
             _forbidden_knowledge_finding(canon, item, window.effective_from, window.effective_until)
527      required_keys = {_event_selector_key(item) for item in scene.required_events}
528-536  for item in scene.forbidden_events if _event_selector_key(item) in required_keys:
             _mb_finding("SCENE_EVENT_REQUIRED_FORBIDDEN_COLLISION", ...)
537      return _sorted_report([f for f in findings if f is not None])
```

Helpers reached from `validate_scene`:

| Helper | Lines | Role |
|---|---|---|
| `_scene_state_finding` | `:718-746` | dispatch on `SceneFactConstraint` / `SceneKnowledgeConstraint`; emits `SCENE_ENTRY_FACT_UNMET` / `SCENE_ENTRY_KNOWLEDGE_UNMET` (or `_EXIT_` when `phase="EXIT"`), and `SCENE_KNOWLEDGE_INTEGRITY` when the resolver reports >1 active state |
| `_fact_constraint_met` | `:675-685` | `PRESENT`/`ABSENT`/`EQUALS`/`NOT_EQUALS` over `_active_facts_for` |
| `_active_facts_for` | `:665-672` | active `(subject_ref, predicate)` facts at `at` via `_point_in` (`:230-231`) |
| `_knowledge_constraint_met` | `:688-705` | resolves an `EpistemicViewResolver().resolve(...)` view via `_view_for`; returns `True`/`False`/`None`; `None` = `EpistemicIntegrityError` (>1 active state); falls back to `item.include_absent` at `:705` when the proposition is absent from every bucket |
| `_view_for` | `:708-715` | wraps a bare `CanonContent` in a synthetic `ResolvedCanonView` (`branch_id="scene-eval"`) so the resolver can run |
| `_forbidden_knowledge_finding` | `:749-770` | boundary-set sweep across the window; emits `SCENE_KNOWLEDGE_FORBIDDEN_MATCH` if `_knowledge_constraint_met(...) is True` at any probe midpoint |
| `_event_selector_key` | `:646-652` | normalized tuple `(event_ref, event_type, sorted participant_refs_all, location_ref)` |
| `_mb_finding` | `:208-223` | builds a `NarrativeValidationFinding` with `severity = NarrativeValidationSeverity.ERROR` (`:205`, `:214`) |
| `_sorted_report` | `:634-643` | sorts on `(severity, rule_id, affected_refs, story_time)` |

`_event_matches_selector` (`:655-662`) and `_character_has_state` (`:773-782`) are
defined but **only** called from `validate_scene_outcome`, never from
`validate_scene`.

### `validate_scene_outcome` — `r2/narrative/validation.py:539-631` (for contrast)

Outcome validation, which `commit_revision` never calls, does implement:
required-event window match → `SCENE_EVENT_REQUIRED_UNMET` (`:553-568`);
forbidden-event present/indeterminate → `SCENE_EVENT_FORBIDDEN_PRESENT` /
`SCENE_EVENT_FORBIDDEN_INDETERMINATE` (`:569-588`); exit targets →
`_scene_state_finding(... phase="EXIT")` (`:590-593`); and reveal recipients →
`SCENE_EXIT_REVEAL_UNMET` (`:596-629`). The reveal branch at `:613` tests
`if had or not has` — the `had` term is the "already had the resulting state at
entry" precondition, but it is only evaluated here, against an explicit post-scene
`before`/`after` pair, not at plan commit.

## 3. Rule inventory table

Requirement column cites the spec. "Implemented?" cites `r2/narrative/validation.py`
unless noted. "Tested?" covers only tests that exercise the rule **through
`validate_scene`** (identity/hierarchy tests and `validate_scene_outcome` tests do
not count).

| # | Rule (family / name) | Spec `path:line` | One-line requirement | Implemented? | Tested? |
|---|---|---|---|---|---|
| R1 | `SCENE_ENTRY_FACT_UNMET` | spec `:348`, `:519`, `:529-532`, `:461` | every `entry_state_constraints` Fact item matches the exact Canon basis at `effective_from` | YES — `validation.py:519-522` → `_scene_state_finding` `:721-727`, `_fact_constraint_met` `:675-685` | YES — `tests/unit/r2/narrative_plan/test_plan_validation.py:183-195`; integration `tests/integration/r2/test_m5b_acceptance.py:345-354` (MUT-11) and `:607-626` |
| R2 | `SCENE_ENTRY_KNOWLEDGE_UNMET` | spec `:348`, `:519`, `:533` | every `entry_state_constraints` Knowledge item matches one active state in `states` (or absence when `include_absent`) at `effective_from` | YES — `validation.py:519-522` → `_scene_state_finding` `:728-745`, `_knowledge_constraint_met` `:688-705` | **no** |
| R3 | `SCENE_KNOWLEDGE_INTEGRITY` | spec `:534` | >1 active state for one subject/proposition at the entry instant is a blocking integrity error | YES — `_knowledge_constraint_met` returns `None` `:693-694` → `_scene_state_finding` `:733-738` | **no** (MUT-12 at `test_m5b_acceptance.py:357+` exercises `EpistemicViewResolver` directly, not via `validate_scene`) |
| R4 | `SCENE_KNOWLEDGE_FORBIDDEN_MATCH` | spec `:349`, `:521-522` | a `forbidden_knowledge` item that matches at any instant in `[effective_from, effective_until)` is blocking | YES — `validation.py:523-526` → `_forbidden_knowledge_finding` `:749-770` | YES — `tests/unit/r2/narrative_plan/test_plan_validation.py:198-212` |
| R5 | `SCENE_EVENT_REQUIRED_FORBIDDEN_COLLISION` (events) | spec `:350`, `:535` | the same normalized Event selector cannot be in both `required_events` and `forbidden_events` | YES — `validation.py:527-536`, `_event_selector_key` `:646-652` | **no** |
| R6 | required/forbidden collision for **state** constraints | spec `:535` (applies to "a required and forbidden list", not only events); family `SCENE_KNOWLEDGE_*` `:349` | the same normalized `SceneKnowledgeConstraint` / `SceneFactConstraint` cannot be in a required list (`entry_state_constraints` / `exit_state_targets`) and in `forbidden_knowledge` | **MISSING** — no code compares state-constraint lists; `validation.py:527` only builds keys from `scene.required_events` | **no** |
| R7 | Character-reveal entry precondition | spec `:537` ("recipient must not already have the requested resulting state at entry"); family `SCENE_KNOWLEDGE_*` "reveal precondition" `:349` | for each `required_reveals` recipient that is a `CharacterRevealRecipient`, the subject must **not** already hold `resulting_state` for `proposition_ref` at `effective_from` on `canon_basis` | **MISSING** in `validate_scene` — `scene.required_reveals` is never read; the `had` check lives only in `validate_scene_outcome:613` | **no** |
| R8 | required-Event selector static satisfiability | spec `:350` ("unsatisfiable selector"), `:523-528`, `:548-549` ("static satisfiability against `canon_basis`"), `:709` | a `required_events` selector that can never be satisfied on the pinned basis (e.g. exact `event_ref` that names a non-Event, or a pattern whose `participant_refs_all` / `location_ref` are not entities in `canon_basis`) is blocking at commit | **MISSING** — `scene.required_events` feeds only the collision key set (`validation.py:527`); no lookup against `canon.content` | **no** |
| R9 | exact-reference integrity | spec `:548` ("checks exact references"), `:525` ("an exact `event_ref` must resolve to that Event") | `SceneEventConstraint.event_ref`, `SceneKnowledgeConstraint.proposition_ref`, `SceneFactConstraint.subject_ref`/`predicate` resolve against `canon_basis` (or fail with a reference finding, not a silent UNMET) | **PARTIAL / IMPLICIT** — unknown `proposition_ref` falls through to `include_absent`/`_UNMET` at `validation.py:705`; unknown `event_ref` is not checked at all | **no** |
| R10 | typed shapes / normalized duplicates within a list | spec `:548` ("typed shapes, normalized duplicates") | duplicate `constraint_id` or byte-identical duplicate constraints inside one list are rejected | **MISSING** — pydantic (`r2/contracts/narrative_plan.py`) enforces field types and per-field `_sorted_unique` on string lists only, not constraint-object uniqueness | **no** |
| R11 | validate on `canon_basis`, no head fallback | spec `:1041`, `:1098` (MUT-11), plan `:19` | `validate_scene` must be given / must assert the exact pinned basis | Enforced **upstream**, not in `validate_scene`: service `_resolve_canon_basis` `r2/narrative_plan/service.py:212-234`; compiler `_require_basis_equality` `r2/narrative_context/compiler.py:265-268`. `validate_scene` itself does not look at `plan.content.canon_basis` (`_ = plan`) | Integration only — `test_m5b_acceptance.py:345-354` via the service |
| R12 | exit obligations not claimed fulfilled at commit | spec `:549-550`, `:709` | `validate_scene` must not evaluate `exit_state_targets` or reveal *outcome* | YES — by omission; `validate_scene` never touches `exit_state_targets` | implicit (no negative test) |

## 4. The `plan` argument

`plan` is genuinely unused: `r2/narrative/validation.py:516` — `_ = plan` — and it
appears nowhere else in the method body (`:513-537`).

What a spec-correct `validate_scene` would need it for:

- **Nothing that is not already reachable from `canon` + `scene`.** Every missing
  check in §3 (R6, R7, R8, R9) is computable from `scene` (the constraint lists)
  and `canon` (the resolved `canon_basis` view). Closing the gaps does **not**
  require un-discarding `plan`.
- The only spec-anchored use of `plan` is a **defense-in-depth basis assertion**
  (R11): the spec requires validation against the exact `canon_basis`
  (`spec:548-549`, `:1041`, `:1098`). `plan.content.canon_basis`
  (`r2/contracts/narrative_plan.py:197`, a `CanonBasis` with `branch_id` +
  `canon_version_id`, `:34-37`) could be cross-checked against
  `canon.branch_id` / `canon.canon_version_id` inside `validate_scene` so the
  validator fails closed if a caller ever resolves the wrong view. Both current
  callers already assert this before the call — service at
  `r2/narrative_plan/service.py:227-233`, compiler at
  `r2/narrative_context/compiler.py:265-268` — and the `plan` handed in by the
  service is literally `proposal.proposed_content` wrapped by `_build_plan`
  (`r2/narrative_plan/service.py:237-252`), so today the assertion would be
  tautological.
- `plan.content.scene_contracts` (sibling scenes) and the hierarchy node lists
  (`r2/contracts/narrative_plan.py:199-203`) are the other data `plan` carries.
  The spec assigns cross-scene / hierarchy / ref checks to
  `validate_plan_hierarchy` and the service's `_validate_content`
  (`r2/narrative_plan/service.py:281-312`, `spec:702-704`: "then validate
  hierarchy, refs, scene identity/version rules"), not to `validate_scene`, so no
  requirement pulls them into this method.

Conclusion: the `plan` parameter exists for signature symmetry with
`validate_scene_outcome` (`spec:302-318`, plan `:784`). It is defensible to keep
it and add the R11 basis assertion; it is not the blocker for R6/R7/R8/R9.

## 5. Gaps to close, ranked

### Gap 1 — Character-reveal entry precondition (R7)

- Spec text: `spec:537` — "For a Character reveal, the recipient must not already
  have the requested resulting state at entry and must have it at exit in a
  post-scene candidate." Family: `spec:349` `SCENE_KNOWLEDGE_*` — "reveal
  precondition".
- Missing check: in `validate_scene`, iterate `scene.required_reveals`
  (`r2/contracts/narrative_plan.py:178`); for each `recipient` that
  `isinstance(recipient, CharacterRevealRecipient)` (`:108-113`), evaluate whether
  the subject already holds `recipient.resulting_state` for
  `reveal.proposition_ref` at `window.effective_from` on `canon`. If it already
  holds, emit a blocking finding.
- Reuse: `_character_has_state(canon, subject_entity_id, proposition_ref,
  resulting_state, at)` already exists at `r2/narrative/validation.py:773-782` and
  does exactly this probe (builds a `SceneKnowledgeConstraint` and calls
  `_knowledge_constraint_met`). `resulting_state` is
  `Literal["KNOWN","SUSPECTED","FALSE_BELIEF"]` so `EpistemicState(resulting_state)`
  at `:780` is total.
- rule_id: the spec names only the family. A TDD pass must coin the id — proposed
  `SCENE_KNOWLEDGE_REVEAL_PRESTATE` (blocking, `severity=ERROR` per `spec:337`).
  `affected_refs` shape should follow the outcome analogue at
  `validation.py:617`: `(scene.scene_contract_id, reveal.constraint_id,
  recipient.subject_entity_id)`.
- Where it belongs: a new `findings.extend(...)` block in `validate_scene` between
  the forbidden-knowledge sweep (`:523-526`) and the event-collision block
  (`:527-536`). `AudienceRevealRecipient` recipients (`:115-118`) are skipped — the
  spec gives them no entry precondition (`spec:538-542`).

### Gap 2 — required-Event selector static satisfiability (R8)

- Spec text: `spec:350` — "unsatisfiable selector"; `spec:548-549` — "Plan commit
  validation checks ... static satisfiability against `canon_basis`. It does not
  claim that future exit obligations are already fulfilled"; `spec:709` —
  "Outcome-only obligations are checked for static satisfiability at commit and are
  not misreported as already fulfilled."
- Missing check: `scene.required_events` (`r2/contracts/narrative_plan.py:176`) is
  only read at `validation.py:527` to build collision keys. Add a satisfiability
  probe against `canon.content` for each selector: a pattern selector
  (`event_type` set, `:92-105`) whose `participant_refs_all` or `location_ref`
  name an id absent from `canon.content.entities_by_id` can never match; an exact
  `event_ref` selector that resolves to an id already present in
  `canon.content.events_by_id` but with a conflicting `event_type` /
  participants / `location_ref` is contradictory. It must **not** require the
  Event to already exist (`spec:544-546`, `:1057` — a future SceneContract Event
  stays absent from Canon).
- rule_id: family `SCENE_EVENT_*`; proposed `SCENE_EVENT_SELECTOR_UNSATISFIABLE`
  (blocking). `affected_refs`: `(scene.scene_contract_id, item.constraint_id)`,
  matching `validation.py:565`.
- Where it belongs: fold into / beside the `required_keys` comprehension at
  `validation.py:527` — iterate `scene.required_events` once, emit satisfiability
  findings, and reuse the same loop to build the collision key set.

### Gap 3 — required/forbidden collision for state constraints (R6)

- Spec text: `spec:535` — "the same normalized constraint cannot appear in both a
  required and forbidden list." The sentence is not scoped to events; the state
  lists are `entry_state_constraints` / `exit_state_targets` (required) and
  `forbidden_knowledge` (forbidden) (`r2/contracts/narrative_plan.py:179-181`).
- Missing check: no code normalizes or compares `SceneKnowledgeConstraint` /
  `SceneFactConstraint` objects across lists. A `SceneKnowledgeConstraint` that is
  semantically identical (same `subject_entity_id`, `proposition_ref`, `states`,
  `include_absent`) in both `entry_state_constraints` and `forbidden_knowledge` is
  a self-contradiction that commit should reject.
- rule_id: family `SCENE_KNOWLEDGE_*` (`spec:349`); proposed
  `SCENE_STATE_REQUIRED_FORBIDDEN_COLLISION` (blocking). `affected_refs`:
  `(scene.scene_contract_id, item.constraint_id)`, matching the event analogue at
  `validation.py:531`.
- Where it belongs: a new block adjacent to the event-collision block
  (`validation.py:527-536`). Needs a normalization key for state constraints
  analogous to `_event_selector_key` (`:646-652`) — a new
  `_state_constraint_key(item)` helper.

### Gap 4 — exact-reference integrity for `event_ref` / `proposition_ref` (R9)

- Spec text: `spec:548` — "Plan commit validation checks exact references ...";
  `spec:525` — "an exact `event_ref` must resolve to that Event."
- Missing check: an exact `event_ref` selector in `required_events` /
  `forbidden_events` that names an id present in neither
  `canon.content.events_by_id` nor the plan's own future obligations is currently
  silent for `required_events` (only reaches the collision key) and, for
  `forbidden_events`, is only surfaced by `validate_scene_outcome`. An unknown
  `SceneKnowledgeConstraint.proposition_ref` currently degrades to
  `include_absent`/`_UNMET` at `validation.py:705` rather than a distinct
  reference finding.
- rule_id: reuse `SCENE_EVENT_SELECTOR_UNSATISFIABLE` for the event case (Gap 2),
  or a dedicated `SCENE_REF_MISSING`; for `proposition_ref`, a dedicated
  `SCENE_KNOWLEDGE_PROPOSITION_MISSING` mirroring the Canon-side
  `EPI_IDENTITY_PROPOSITION_MISSING` at `validation.py:387`.
- Where it belongs: with Gap 2 for events; for propositions, inside
  `_knowledge_constraint_met` (`:688-705`) or `_scene_state_finding` (`:728-745`)
  — the resolver already distinguishes "absent from every bucket" at `:701-705`.
- Priority note: lower than Gaps 1–3 because the current fall-through still
  produces a blocking finding in most cases; this is about a precise rule_id and
  not masking a typo'd ref as an ordinary UNMET.

### Gap 5 — `canon_basis` self-assertion using `plan` (R11)

- Spec text: `spec:548-549`, `:1041` ("exact Canon basis checked read-only by
  `validate_scene()` ... with no head fallback"), `:1098` (MUT-11).
- Missing check: `validate_scene` does not compare `plan.content.canon_basis`
  (`r2/contracts/narrative_plan.py:197`) to `canon.branch_id` /
  `canon.canon_version_id`. `_ = plan` at `validation.py:516`.
- rule_id: proposed `SCENE_BASIS_MISMATCH` (blocking). Defense-in-depth only —
  both callers already assert this (`service.py:227-233`, `compiler.py:265-268`).
- Where it belongs: top of `validate_scene`, replacing `_ = plan` at `:516`.

### Gap 6 — normalized-duplicate / typed-shape intra-list checks (R10)

- Spec text: `spec:548` — "typed shapes, normalized duplicates".
- Missing check: duplicate `constraint_id` or byte-identical constraint objects
  within a single list. Lowest priority: no adversarial mutation targets it and
  pydantic already blocks malformed shapes.
- rule_id: proposed `SCENE_CONSTRAINT_DUPLICATE` (blocking).

## 6. Blast radius

- **`r2/narrative/validation.py`** — `validate_scene` (`:513-537`) is the single
  edit site; add rule-id constants near the existing `SCENE_*` string literals
  (there is no central constant table — they are inline strings, e.g. `:530`,
  `:724`, `:739`, `:765`). New helpers `_state_constraint_key`, and possibly a
  reveal-precondition loop reusing `_character_has_state` (`:773-782`).
  `_sorted_report` (`:634-643`) already orders any new findings deterministically;
  no change needed. **No contract change** — `required_reveals`,
  `CharacterRevealRecipient.resulting_state`, `SceneEventConstraint` fields all
  already exist (`r2/contracts/narrative_plan.py:178`, `:112`, `:92-105`), so
  unlike deviation #9 (`R2_M5B_FINAL_VERIFICATION.md:118-119`) this needs **no**
  `semantic_hash_version` v1→v2 bump.

- **`tests/unit/r2/narrative_plan/test_plan_validation.py`** — today holds only two
  `validate_scene` cases (`:183-195` entry Fact, `:198-212` forbidden Knowledge)
  under the `# --- validate_scene / validate_scene_outcome` banner at `:123`.
  Needs RED cases for R2, R3, R5, R6, R7, R8 (and R9). The local `_scene` helper
  (`:167-177`) only sets `entry_state_constraints` / `forbidden_knowledge` and
  will need `required_events` / `forbidden_events` / `required_reveals`
  parameters; `_plan` (`:152-165`) and `_canon` (`:132-151`) are reusable.

- **`tests/unit/r2/narrative/test_validation_m5b.py`** — currently has **zero**
  `validate_scene` / `validate_scene_outcome` tests (it covers `validate_canon`
  and `validate_knowledge_interval` only). Could host pure reveal-precondition and
  selector-satisfiability cases; `audit_tests.py --check` (plan `:790`) will want
  the new cases attributed.

- **`tests/fixtures/r2/m5b_narrative_corpus.py`** — `entry_scene` (`:157-177`)
  builds only a single `SceneFactConstraint`. `full_corpus`'s 30 SceneContracts
  (`:471-495`) set `participants` / `active_threads` / `promise_payoff_refs` but
  **no** `required_events`, `forbidden_events`, `required_reveals`,
  `forbidden_knowledge`, `entry_state_constraints`, or `exit_state_targets` — so
  the acceptance corpus exercises `validate_scene` only trivially (empty lists →
  empty report). Proving R7/R8 through the public path needs a scene fixture that
  actually populates `required_reveals` / `required_events`, plus canon content
  with a matching KnowledgeState / entities.

- **`tests/integration/r2/test_m5b_acceptance.py`** — MUT-11 (`:345-354`, and the
  counter probe at `:607-626`) drives only the entry-Fact path
  (`SCENE_ENTRY_FACT_UNMET` → `NarrativePlanValidationError`). A new adversarial
  mutation ("scene requires a Character reveal whose recipient already holds the
  state at entry" → `NarrativePlanValidationError`, zero writes) would exercise R7
  through `NarrativePlanService.commit_revision` (`r2/narrative_plan/service.py:310`).
  Adding it touches the plan's MUT table too (`plan:1219-1237` area).

- **`docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md`** — the open-finding sentence
  at `:122` and the deviations list (`:96-119`) must be updated once the gaps
  close; the MUT table (`:81-84`) gains a row if a MUT is added. The "hard exit"
  counters (`spec:1101-1114`) are unaffected (all currently 0).

- **Callers need no change** — `r2/narrative_plan/service.py:310-312` and
  `r2/narrative_context/compiler.py:270-273` both already treat a non-`ok`
  `NarrativeValidationReport` as a hard failure; new blocking findings flow
  through unchanged.

## 7. Open ambiguities for the TDD pass

1. **Definition of "static satisfiability" for a required Event (Gap 2).** The
   spec (`:525-528`, `:548-549`) does not enumerate what makes a selector
   statically unsatisfiable at commit. Candidates: (a) pattern selector names a
   `participant_refs_all` / `location_ref` id absent from
   `canon.content.entities_by_id`; (b) exact `event_ref` already present in
   `canon.content.events_by_id` contradicts the selector's `event_type` /
   participants / `location_ref`; (c) exact `event_ref` absent from Canon — must
   **not** be an error (future Event, `spec:544-546`, `:1057`). The pass must pick
   the set and pin it in tests.

2. **Which list pairs collide for state constraints (Gap 3).** `spec:535` says "a
   required and forbidden list" without naming them. Minimum reading:
   `forbidden_knowledge` vs `entry_state_constraints`. Open: does
   `exit_state_targets` also count as a "required list" for this purpose? Does a
   `SceneFactConstraint` with contradictory `comparison` values across
   `entry_state_constraints` and `exit_state_targets` (e.g. `PRESENT` vs `ABSENT`)
   count, or only exact normalized duplicates?

3. **Normalization key for state constraints.** `_event_selector_key`
   (`validation.py:646-652`) excludes `constraint_id`. The state analogue must
   decide whether `constraint_id` and `constraint_kind` are excluded, and how
   `SceneFactConstraint.expected_value` (a `JSONValue`) is canonicalized — reuse
   `_canonical_value` (`:226-227`).

4. **Concrete rule_ids.** The spec names only families (`SCENE_KNOWLEDGE_*`,
   `SCENE_EVENT_*`, `SCENE_ENTRY_*`, `SCENE_EXIT_*`, `:348-351`). Every id in §5 is
   proposed here, not spec-mandated; the pass owns the naming and must keep it
   consistent with the existing inline literals (`SCENE_ENTRY_FACT_UNMET`,
   `SCENE_KNOWLEDGE_FORBIDDEN_MATCH`, `SCENE_EVENT_REQUIRED_FORBIDDEN_COLLISION`,
   etc.) and with `RULES` ordering conventions (`validation.py:40-47` for the M5A
   set — there is no M5B equivalent constant tuple).

5. **Severity.** `_mb_finding` hard-codes `severity=ERROR` (`validation.py:205`,
   `:214`) and `spec:337` says commit gates treat every ERROR as blocking and a
   caller cannot downgrade a required SceneContract constraint. Assumed: all new
   findings are ERROR. Confirm no WARNING-tier intent for, e.g., R10 duplicates.

6. **Does R7 read `AudienceRevealRecipient` at all at commit?** `spec:538-542`
   says an audience reveal "never creates a Canon entity or KnowledgeState" and is
   validated by `AudienceRevealEvidence` at outcome. Assumed: `validate_scene`
   skips `AudienceRevealRecipient` entirely, matching
   `validate_scene_outcome:598` `isinstance(recipient, CharacterRevealRecipient)`.

7. **Unknown `proposition_ref` on a reveal at entry.** If a Character reveal's
   `proposition_ref` is not yet in `canon_basis` (the reveal will introduce that
   knowledge later), is that a well-formed input (subject simply does not hold the
   state → precondition satisfied) or a reference error (Gap 4)? The precondition
   reading is the more permissive and matches `spec:544-546`.

8. **`plan` parameter fate (Gap 5).** Keep it and add the tautological-today
   `SCENE_BASIS_MISMATCH` assertion, or leave `_ = plan` and document that the
   basis guarantee is a caller contract? The spec (`:1041`) attributes the "no
   head fallback" guarantee to `validate_scene()` by name, which argues for the
   in-method assertion.
