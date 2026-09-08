# R2-M5B AUTHOR_DRAFT omniscient-authoring POV gate — source research

**Date:** 2026-09-08

**Question:** design §10.1 says "`AUTHOR_DRAFT` may omit POV only for omniscient authoring
explicitly permitted by the SceneContract and policy." Today `r2/narrative_context/compiler.py`
`_pov_view` returns `None` whenever `request.pov_subject_entity_id is None` and consults no
SceneContract or policy permission. This document collects, from primary sources only, what the
frozen decisions, the M5B design, the M5B plan, the reuse research, and the current code say about
the intended mechanism. It picks nothing; the final section lays out the options each source supports.

**Worktree / revision inspected:** `/home/anhtuan/content-production-os-m5b`, branch
`feat/r2-m5b-epistemic-plan-context`, HEAD `3ae9b990`.

**Note on one cited path:** `docs/research/2026-09-08-r2-m5b-reuse-and-boundary-research.md` is not
present in this worktree's HEAD tree; it was added in `74714922` and currently lives on branch
`design/r2-m5b-narrative-context` (checked out in the sibling worktree `content-production-os`). Its
bytes on that branch are identical to `74714922:docs/research/2026-09-08-r2-m5b-reuse-and-boundary-research.md`
(verified by `git diff`), which is an ancestor of this HEAD. Line citations below use that file at
`74714922` and are quoted as `2026-09-08-r2-m5b-reuse-and-boundary-research.md:<line>`.

---

## 1. Is the mechanism specified anywhere? — No.

### 1.1 The only statement of the rule

`docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md:747`:

> All versions are exact. "Latest" is not accepted at the compiler seam. `CHARACTER_SIMULATION`
> requires a POV subject. `AUTHOR_DRAFT` may omit POV only for omniscient authoring explicitly
> permitted by the SceneContract and policy.

This sentence is byte-identical in every design revision since the first draft
(`git show 74714922:docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md`
line 538; unchanged through `94858b68`, `a13f5b1c`, `080f9c1e`, `17848e29`, `e83ce1a2` at line
731/747). No revision ever expanded it. The word "omniscient" appears exactly once in the design
doc (line 747) and **zero times** in the plan doc, the contracts, the compiler, the errors module,
and the reuse research.

### 1.2 No dedicated field / token / policy shape is defined

- **Design §10.1 request shape** (`...-design.md:724-745`) lists `mode`, `pov_subject_entity_id?`,
  `creative_policy_ref`, `creative_policy_version` and nothing that expresses an omniscient-authoring
  permission.
- **Design §10.2** explicitly forbids input metadata from carrying a channel permission:
  `...-design.md:811-813`:
  > Descriptor metadata is a claim, not a new authority. The compiler resolves its basis refs against
  > exact Canon/plan reads, checks the descriptor and prose hashes, and only then assigns an output
  > visibility channel. An input descriptor never supplies an `allowed_channel` field.
- **Design §10.3** `...-design.md:863`:
  > `AUTHOR_DRAFT` may include `AUTHOR_TRUTH`, but POV-forbidden propositions are separately and
  > explicitly labelled.
  (no gate on whether AUTHOR_DRAFT is allowed to run without a POV.)
- **Design §10.4 compilation order** `...-design.md:874`: "6. Resolve the POV epistemic view **when
  required**." — "when required" is never defined for AUTHOR_DRAFT.
- **Design §8.2 SceneContract** (`...-design.md:426-450`) enumerates the whole SceneContract field
  list; it has `pov?` (line 437), `active_threads[]` (447), `creative_constraints[]` (449) and no
  permission/mode field.
- **Plan doc is entirely silent.** `docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md`
  never restates the §10.1 sentence, never adds a request validator for it, and its SceneContract
  freeze (`...-plan...md:718-743`) reproduces `pov: NonEmptyStr | None` with no companion flag. The
  only AUTHOR_DRAFT/POV text in the plan is `...-plan...md:1128` ("`AUTHOR_DRAFT` may include
  `AUTHOR_TRUTH` but preserves POV-forbidden labels…"), which does not mention POV omission.

**Conclusion for Q1:** the design asserts the rule in one sentence and never specifies a mechanism —
no dedicated field, no reserved constraint/permission token, no policy-segment shape. The plan doc
does not implement or even mention it. The docs are silent on mechanism.

---

## 2. Exact shapes of the carriers that §10.1 names

### 2.1 `SceneContract` — `r2/contracts/narrative_plan.py:163-189`

```
class SceneContract(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")     # narrative_plan.py:164
    scene_contract_id: NonEmptyStr                             # :165
    version: Annotated[int, Field(ge=1)]                       # :166
    semantic_hash: NonEmptyStr                                 # :167
    semantic_hash_algorithm: Literal["sha256"] = "sha256"      # :168
    semantic_hash_version: Literal["r2-scene-contract-content-v1"] = ...   # :169
    sequence_index: Annotated[int, Field(ge=0)]               # :170
    purpose: NonEmptyStr                                       # :171
    pov: NonEmptyStr | None                                    # :172
    location_ref: NonEmptyStr | None                           # :173
    temporal_window: SceneTemporalWindow                       # :174
    participants: list[NonEmptyStr]                            # :175
    required_events / forbidden_events: list[SceneEventConstraint]        # :176-177
    required_reveals: list[SceneRevealConstraint]              # :178
    forbidden_knowledge: list[SceneKnowledgeConstraint]        # :179
    entry_state_constraints / exit_state_targets: list[SceneStateConstraint]  # :180-181
    active_threads: list[NonEmptyStr]                          # :182
    promise_payoff_refs: list[NonEmptyStr]                     # :183
    creative_constraints: list[NonEmptyStr]                    # :184
    # field_validators sort + dedupe the NonEmptyStr lists      # :185-188
```

- `pov` is `NonEmptyStr | None` (`narrative_plan.py:172`) — POV is already optional on the scene
  itself, with **no** companion boolean/enum expressing "omniscient authoring permitted".
- The only free-form token lists are `active_threads`, `promise_payoff_refs`,
  `creative_constraints`, `participants` (`narrative_plan.py:175,182-184`), each `list[NonEmptyStr]`
  passed through `_sorted_unique` (`narrative_plan.py:30-31, 185-188`).
- Boolean opt-in flags are already idiomatic in this same file:
  `SceneKnowledgeConstraint.include_absent: bool = False` (`narrative_plan.py:81`).
- `model_config` is `extra="forbid"` (`narrative_plan.py:164`) — a new signal cannot be smuggled in
  as an extra key; it needs a real field or an existing list token.
- Frozen shape agrees: `docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:454-480` lists `pov?`,
  `active_threads[]`, `creative_constraints[]` and no permission field; `:482` "SceneContract
  describes authorial intent, not committed narrative truth."

### 2.2 Creative-policy read contract — `r2/narrative_context/ports.py:40-51`

```
class CreativePolicySegment(Protocol):
    @property
    def source_ref(self) -> str: ...        # ports.py:41-42
    @property
    def content(self) -> str: ...           # ports.py:44-45

class CreativePolicyReader(Protocol):
    async def get_exact(
        self, *, policy_ref: str, policy_version: str, project_name: str, user_id: str
    ) -> tuple[CreativePolicySegment, ...] | None: ...   # ports.py:48-51
```

The compiler consumes each segment as opaque prose and emits it on the `CREATIVE_POLICY` channel
verbatim — `r2/narrative_context/compiler.py:339-356` (`_policy_segments`: reads
`item.source_ref` / `item.content`, no structured field access). There is **no machine-readable
field** on the policy contract that the compiler could read for a permission bit.

### 2.3 There is no richer `CreativePolicy*` contract in `r2/contracts/`

`grep -rn "CreativePolicy" r2/ --include="*.py"` returns only `CreativePolicyReader` /
`CreativePolicySegment` in `r2/narrative_context/` and the two request strings
`creative_policy_ref: NonEmptyStr` / `creative_policy_version: NonEmptyStr`
(`r2/contracts/narrative_context.py:200-201`, and `creative_policy_ref` on the pack at
`:278`). No `CreativePolicy` Pydantic model exists in the codebase.

The **frozen** `CreativePolicy` (not yet modeled in code) does define a POV sub-field:
`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:486-504`:

```
CreativePolicy
  creative_policy_id
  version
  genre
  tone
  style_constraints[]
  pov_policy?
  pacing_policy?
  ...
  format_constraints[]
```

`docs/r2/R2_01_FROZEN_ARCHITECTURE.md:206-209` separately lists `CreativePolicy`, `GenrePolicy`,
`POVPolicy`, `PacingPolicy` as plan-side contracts. `docs/r2/R2_03_CONTRACT_REGISTRY.json:126-131`
gives `CreativePolicy` `family=AUTHORIAL_INTENT`, `commit_authority=CreativePolicyService`. But M5B
explicitly puts "CreativePolicy write authority" **out of scope**
(`...-design.md:1152`), and the M5B read seam is only `(source_ref, content)` prose
(`ports.py:40-46`).

### 2.4 `NarrativeContextRequest` — `r2/contracts/narrative_context.py:190-216`

```
mode: ContextMode                              # narrative_context.py:202
pov_subject_entity_id: NonEmptyStr | None = None   # :203

@model_validator(mode="after")
def _mode_requires_pov(self) -> NarrativeContextRequest:      # :212-216
    if self.mode is ContextMode.CHARACTER_SIMULATION and self.pov_subject_entity_id is None:
        raise ValueError("CHARACTER_SIMULATION requires a POV subject")
    return self
```

The **first half** of §10.1 ("`CHARACTER_SIMULATION` requires a POV subject") is enforced here as a
`pydantic.ValidationError`. The **second half** (AUTHOR_DRAFT omission gate) has no counterpart —
`AUTHOR_DRAFT` + `pov_subject_entity_id=None` validates cleanly today.

### 2.5 Which existing fields could carry an "omniscient authoring permitted" signal without a schema change

| Carrier | Where | Change needed |
|---|---|---|
| `SceneContract.creative_constraints` reserved token (e.g. `omniscient-pov:permitted`) | `narrative_plan.py:184` (`list[NonEmptyStr]`) | none to the schema; a **new parsing convention** in the compiler — today no code reads individual `creative_constraints` tokens (see §3.3). Already inside the scene semantic hash (§7). |
| `SceneContract.active_threads` token | `narrative_plan.py:182` | same as above; semantically wrong home ("threads", not permissions). |
| `SceneContract.pov is None` itself as the signal | `narrative_plan.py:172` | none — but circular: `pov is None` is the condition being gated, so on its own it permits nothing. |
| Free text inside a `CreativePolicySegment.content` string | `ports.py:44-45` | none to the contract; requires the compiler to **parse policy prose**, which §10.2/§10.4 forbid ("prose is never a visibility input", `...-design.md:834`; compilation order step 9, `:877`). |

Every option that adds a **typed** field (`SceneContract.pov_mode`, `omniscient_authoring_permitted:
bool`, a structured `CreativePolicy` model) is a schema change — see §7.

---

## 3. Codebase precedent for permission / enablement signals

### 3.1 M4 `r2/production_intelligence/` — versioned policy + explicit enablement boolean

`r2/production_intelligence/director.py:80-124` — `DirectorRoutingPolicy.route(...)`:

- takes `override_allows_fallback: bool = False` (`director.py:94`);
- computes `fallback_enabled: bool` (`director.py:105, 108`);
- stamps `routing_policy_version=ROUTING_POLICY_VERSION` and returns
  `RoutingDecision(..., fallback_enabled=fallback_enabled)` (`director.py:115-124`);
- module docstring: "Routing is a hybrid authority model: a deterministic versioned policy decides
  the …" (`director.py:3`).

This is the closest structural precedent for "explicitly permitted by … policy": a deterministic,
version-stamped policy object yields a boolean enablement flag that a downstream decision reads.

`r2/production_intelligence/method_router.py`:

- `allowed_methods: tuple[ProductionMethod, ...]` (`method_router.py:61`);
- `raise MethodRoutingBlocked("no allowed method satisfies the hard policy")` (`method_router.py:81`);
- iterates `for method in context.allowed_methods` (`method_router.py:104`).

Allow-list + explicit block error — the same shape a "may omit POV only when permitted" gate implies.

`r2/production_intelligence/execution.py:144` — `allowed: bool` on an execution-decision contract.

M4 does **not** consume a `CreativePolicy` contract (`grep` in `r2/production_intelligence/` finds
only capability/routing/freshness policies, `capability_registry.py:19,73-79`,
`director.py:70-124`, `readiness.py:99`). So there is precedent for *policy → permission flag*, but
none for reading an authorial `CreativePolicy`.

### 3.2 The compiler's own "claim, then prove" model (in-module precedent)

`r2/narrative_context/compiler.py:425-500` (`_reject_reason` / `_visibility_reason`) plus
`...-design.md:811-813`: a `NarrativeSourceDescriptor` **claims** a visibility, and the compiler
grants a channel only after proving the claim against exact Canon/plan reads and hashes; "metadata
is a claim, not a new authority" and descriptors carry no `allowed_channel`. By analogy, an
"omniscient permitted" marker on SceneContract/policy would be a *claim the compiler checks*, never
something the compiler infers.

### 3.3 `creative_constraints` / `active_threads` token lists are opaque today

`r2/narrative_context/compiler.py:114-131` (`_scene_constraint_digest`) copies
`list(scene.creative_constraints)` and `list(scene.active_threads)` straight into a JSON digest;
`r2/contracts/narrative_plan.py:185-188` only sorts/dedupes them. The design assigns them **no
executable semantics** — `...-design.md` mentions `creative_constraints[]` / `active_threads[]` only
in the field list (`:447, :449`), never as parsed tokens. So using a reserved token here would
introduce a new convention, not follow an existing one.

### 3.4 Boolean opt-in flags already exist in the plan contract file

`r2/contracts/narrative_plan.py:81` — `SceneKnowledgeConstraint.include_absent: bool = False`.
`r2/contracts/narrative_context.py` uses `Literal[...]` discriminators and defaulted bools
throughout. A `bool = False` / `Literal[...]` field on `SceneContract` would be idiomatic in-repo.

### 3.5 The frozen decisions on "permitted / cannot"

`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:143-158` (R2-DEC-007): "Authoritative context selection
and epistemic filtering belong to the R2-owned NarrativeContextCompiler." — the *compiler* is where
an omniscient-vs-POV decision is enforced. `:126-140` (R2-DEC-006): who "does not know a proposition
is explicit authoritative state." No frozen decision defines an omniscient-authoring permission
token.

---

## 4. What `2026-09-08-r2-m5b-reuse-and-boundary-research.md` says

The reuse research **never uses the word "omniscient"** and never describes a POV-omission
permission. Its relevant passages:

- `:142`:
  > `NarrativeContextRequest` should require `(user_id, project_name)`, exact branch/version, exact
  > plan and scene-contract versions, mode (`AUTHOR_DRAFT` or `CHARACTER_SIMULATION`), **POV subject
  > where applicable**, story-time coordinate, creative-policy ref/version, retrieval query/snapshot,
  > token budget, and compiler version.
  ("where applicable" is the only hint that AUTHOR_DRAFT may run without POV; no mechanism given.)
- `:144`:
  > Character simulation receives only character-visible content. **Author drafting may receive
  > global truth only in a separately labelled author channel, together with explicit
  > forbidden-knowledge constraints; it must not flatten author truth into POV beliefs.**
- `:152` (edge-case corpus):
  > Secret true globally; POV has a false cover story until scene 7 | Before reveal: character-visible
  > pack includes cover proposition as `FALSE_BELIEF`, excludes secret truth; **author channel may
  > include truth labelled forbidden.** …
- `:187` (explicit unresolved question handed to the design spec):
  > 6. Define context modes and **whether author-only truth may be emitted at all for each
  > writer/simulator consumer.** Every output segment needs a visibility label and source ref.

Donor patterns cited for the author-vs-character channel split (`:86-92`, `:95`): Novel Studio
`contextPack.ts` / `hardRules.ts`, Shenbi `shenbi-context-composing` / `shenbi-state-settling`,
StoryBox `perceive.py`, and `R1_05_NARRATIVE_STACK_REALITY_CHECK.md:795-880` — "the compiler must
separate author context, character-visible context, and forbidden knowledge." **None** of these is
cited for "omniscient authoring", POV omission, or a permission to skip POV in author-draft mode.

**Conclusion for Q4:** the reuse research treats "may author-only truth be emitted, and to whom" as
an open design question (`:187`), establishes that author drafting is a *separately labelled channel*
(`:144`), and offers no donor precedent and no mechanism for a POV-omission permission.

---

## 5. What §11's failure taxonomy implies

`docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md:939-953` (table), relevant
rows verbatim:

> | `NarrativeContextInputError` | inconsistent exact versions, mode, POV, time, or retrieval snapshot |
> | `NarrativeContextValidationError` | hard Canon/scene constraint blocks compilation |

`r2/narrative_context/errors.py:8-9`:

> `class NarrativeContextInputError(NarrativeContextError):`
> `    """Inconsistent exact versions, mode, POV, story time, or retrieval snapshot."""`

`r2/narrative_context/errors.py:16-17`:

> `class NarrativeContextValidationError(NarrativeContextError):`
> `    """A hard Canon or SceneContract constraint blocks compilation."""`

"AUTHOR_DRAFT without POV but not permitted" is an inconsistency between `mode` and `POV`, which the
taxonomy places squarely inside **`NarrativeContextInputError`** ("inconsistent … mode, POV …",
`...-design.md:950`; same wording in `errors.py:9`). It is caller-correctable, not an integrity
failure, so it does **not** need a new error.

Caveat: if the mechanism is modeled as a *SceneContract constraint* the compiler validates in
`_run_hard_validation` (`compiler.py:270-273`), the `NarrativeContextValidationError` row ("hard …
SceneContract constraint blocks compilation", `...-design.md:952`) would also fit. The existing
first-half gate lives at yet a third layer — `pydantic.ValidationError` from
`NarrativeContextRequest._mode_requires_pov` (`r2/contracts/narrative_context.py:212-216`) — which
is neither taxonomy error. No source resolves which layer owns the second half.

---

## 6. Blast radius — tests that compile `AUTHOR_DRAFT` with `pov=None`

A gate that rejects `AUTHOR_DRAFT` + `pov is None` by default (whether at the request contract, the
compiler seam, or hard validation) breaks or requires a fixture edit for every call site below.

### 6.1 `tests/unit/r2/narrative_context/test_compiler.py`

- `_request(mode="AUTHOR_DRAFT", pov=None, ...)` helper — `test_compiler.py:242-267`.
- `_scene()` fixture sets `pov=None` and no `creative_constraints` — `test_compiler.py:163-174`.
- Direct `compile(...)` call sites with `mode="AUTHOR_DRAFT", pov=None`:
  - `test_compiler.py:302` — `test_author_draft_includes_author_truth_but_simulation_does_not`
  - `test_compiler.py:323` — `test_wrong_scope_and_hash_and_time_are_pre_visibility_rejections`
  - `test_compiler.py:338` — `test_duplicate_is_omitted_after_visibility_with_a_hash`
  - `test_compiler.py:362` — `test_plan_basis_must_equal_the_requested_canon_version`

### 6.2 `tests/integration/r2/test_m5b_acceptance.py`

- `_acc_request(*, mode, pov)` helper — `test_m5b_acceptance.py:68-86`.
- `_corpus_request(...)` helper — `test_m5b_acceptance.py:416-434`.
- Direct `compile(...)` call sites with `mode="AUTHOR_DRAFT", pov=None`:
  - `test_m5b_acceptance.py:264` — `test_mut07_falsified_secret_descriptor_leaks_nothing`
  - `test_m5b_acceptance.py:477-479` and `:484` — `test_full_corpus_compiles_deterministically_in_both_modes_without_leak`
  - `test_m5b_acceptance.py:566` — the hard-exit aggregate (MUT-07 block, `:563-574`)

### 6.3 Shared fixtures — `tests/fixtures/r2/m5b_narrative_corpus.py`

- `entry_scene(...)` sets `pov=None` — `m5b_narrative_corpus.py:157-177` (esp. `:164`). This is the
  SceneContract every `_acc_request` AUTHOR_DRAFT compile resolves.
- The 30-scene corpus builder sets `pov="char-6" if index % 2 == 0 else None`
  (`m5b_narrative_corpus.py:488`) — ~15 corpus scenes have `pov=None`.

### 6.4 `tests/unit/r2/contracts/test_narrative_context.py`

- `test_context_request_strict_modes_and_positive_budget` — `test_narrative_context.py:141-165`.
  Line `:161` builds `{**base, "mode": "AUTHOR_DRAFT", "token_budget": 0}` and asserts
  `ValidationError`; today it fails only for `token_budget=0` (`gt=0`). A contract-level POV gate
  would add a second rejection cause to that request and blur the test's intent (it isolates the
  budget failure), though the assertion would still pass.

**Count:** 4 unit compiler tests + 3 acceptance test functions (one is the hard-exit aggregate) + the
shared `entry_scene` fixture + the corpus builder + 1 contract test. Each would need a
`creative_constraints` token / policy marker / typed field added to its fixture, or would start to
fail.

---

## 7. §2 / ADR scope for changing `SceneContract`

### 7.1 Design §2 and §17

`docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md:22-42` — §2 "Authority and
prior decisions":

> | NarrativePlan and SceneContract | Authorial Intent | `NarrativePlanService` | Add a separate
> append-only plan aggregate and transaction. |  (`:29`)

`...-design.md:42`:

> No new ADR is required for this baseline. R2-DEC-003, R2-DEC-005, R2-DEC-006, and R2-DEC-007
> already fix the durable boundaries. **A separately writable proposition store, a Canon/plan
> cross-authority transaction, or another visibility authority would require a new decision and is
> excluded.**

Adding a descriptive field to `SceneContract` is none of those three triggers.

`...-design.md:1145-1155` — §17 "Out of scope" excludes "normalized standalone proposition tables or
proposition commit service" (`:1148`), "cross-authority Canon/plan atomic commits" (`:1149`), and
"CreativePolicy write authority" (`:1152`). It does **not** exclude evolving `SceneContract`. §5 is
titled "Canon schema evolution" (`...-design.md:85`) and freely revises the *Canon* v2 schema; the
plan/scene schema versions are separate literals — `PLAN_SCHEMA_VERSION = "r2-narrative-plan-v1"`,
`SCENE_CONTRACT_CONTENT_HASH_VERSION = "r2-scene-contract-content-v1"`
(`r2/contracts/narrative_plan.py:19-21`).

### 7.2 The reuse research's ADR test

`2026-09-08-r2-m5b-reuse-and-boundary-research.md:22`:

> Therefore the baseline M5B design **does not need a new ADR**. A new ADR is warranted only if the
> design proposes a new durable boundary not already frozen…

`:166-178` — the five reopen triggers: (1) independently writable/persisted proposition authority,
(2) `NarrativePlanService` mutating Canon or one atomic Canon+Intent transaction, (3) making a
context pack / retrieval index / donor memory / accepted prose authoritative, (4) another service
besides `CanonTransactionService` committing `KnowledgeState`, (5) merging `SceneContract` with
production `SceneSpec`. A new SceneContract field for "omniscient authoring permitted" hits **none**
of the five, so by the research's own test, "no new ADR" holds.

### 7.3 …but a semantic-hash version bump is implied

`docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md:556`:

> Its semantic hash covers **every normalized semantic field** except ID, version, and the hash
> fields themselves.

`r2/narrative_plan/hashing.py:22-25` — `compute_scene_semantic_hash` does
`scene.model_dump(mode="json", exclude={"version","semantic_hash","semantic_hash_algorithm",
"semantic_hash_version"})`, so **any** new SceneContract field automatically enters the semantic
hash. `r2/contracts/narrative_plan.py:169` pins
`semantic_hash_version: Literal["r2-scene-contract-content-v1"]`. Design §8.2 identity rules
(`...-design.md:553-565`, esp. `:560` "Reusing `(scene_contract_id, version)` with a different
semantic hash … is `NarrativePlanIdentityConflictError`") mean the covered-field-set change would
force a `semantic_hash_version` `v1 → v2` and recompute every historical scene hash — the
"semantic_hash v2" the review flagged. No ADR under `docs/adr/` (`0001`–`0075`) concerns R2
narrative at all; the R2 decision records live under `docs/r2/R2_04_*`. So: no *new decision record*
is required to add a SceneContract field per §2 and the research's ADR test, but it is a versioned
schema change to a frozen contract, not a free edit.

### 7.4 Frozen references for `SceneContract` / `CreativePolicy`

- `docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:450-482` — frozen `SceneContract` shape (`pov?` at
  `:460`), "authorial intent, not committed narrative truth" (`:482`).
- `docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:486-506` — frozen `CreativePolicy` with
  `pov_policy?` (`:497`), "Analytics cannot directly mutate CreativePolicy" (`:506`).
- `docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:109-124` (R2-DEC-005): "Future authorial intent is
  stored in NarrativePlan/SceneContract … Affected contracts: … SceneContract …"; reopen condition
  "contract contradiction discovered".

---

## 8. Present behavior (for completeness)

Nothing enforces §10.1's second half today:

- `r2/contracts/narrative_context.py:212-216` (`_mode_requires_pov`) gates only
  `CHARACTER_SIMULATION`.
- `r2/narrative_context/compiler.py:275-277` — `_pov_view` returns `None` as soon as
  `request.pov_subject_entity_id is None`, with no SceneContract/policy read.
- `r2/narrative_context/compiler.py:308-317` — for `mode is ContextMode.AUTHOR_DRAFT` the compiler
  unconditionally appends an `AUTHOR_TRUTH` segment built from all Canon facts.
- `r2/narrative_context/compiler.py:318-337` — POV channels are added only `if pov_view is not None
  and pov is not None`, so an AUTHOR_DRAFT pack with `pov=None` simply carries `AUTHOR_TRUTH` and no
  POV lanes.

So `AUTHOR_DRAFT` + `pov=None` currently compiles a full omniscient pack with **no** "explicitly
permitted" check — exactly the gap the review flagged.

---

## 9. Options implied by the sources

Each option is listed with the concrete evidence for and against it. No option is selected here.

### Option A — reserved token in `SceneContract.creative_constraints`
- **For:** no schema field added; `creative_constraints: list[NonEmptyStr]` already exists
  (`narrative_plan.py:184`) and is already inside the scene semantic hash / identity
  (`hashing.py:22-25`), so versioning is automatic; §10.1 names "the SceneContract"
  (`...-design.md:747`).
- **Against:** no code parses individual `creative_constraints` tokens today — the list is an opaque
  digest (`compiler.py:114-131`, `narrative_plan.py:185-188`) — so this invents a parsing
  convention; a typo in the token fails open unless separately validated; neither design nor plan
  ever defines such a token.

### Option B — new typed field on `SceneContract` (`bool = False` or `Literal[...]` pov-mode)
- **For:** idiomatic in the same file (`SceneKnowledgeConstraint.include_absent: bool = False`,
  `narrative_plan.py:81`); unambiguous and machine-checkable; §10.1 names "the SceneContract";
  passes the reuse research's ADR test (§7.2) and design §2's exclusion list (§7.1) — no new
  decision record required.
- **Against:** schema change to a frozen contract (`R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:450-482`);
  forces `semantic_hash_version` `v1 → v2` (`narrative_plan.py:169`; design §8.2 identity rules
  `...-design.md:553-565`) and recomputes every historical scene hash; design §5 scoped schema
  evolution to *Canon* only (`...-design.md:85`), not the plan aggregate; blast radius across the
  M5B test corpus (§6).

### Option C — machine-readable marker in the CreativePolicy channel
- **For:** §10.1 says "and policy" (`...-design.md:747`); frozen `CreativePolicy` already defines
  `pov_policy?` (`R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:497`) and `R2_01_FROZEN_ARCHITECTURE.md:209`
  lists a `POVPolicy` contract; strong M4 precedent for versioned-policy → enablement boolean
  (`DirectorRoutingPolicy` → `fallback_enabled`, `director.py:80-124`; `method_router.py:61,81`).
- **Against:** the M5B read seam `CreativePolicySegment` is only `{source_ref: str, content: str}`
  (`ports.py:40-46`) with no structured field, and no typed `CreativePolicy` model exists in
  `r2/contracts/` (§2.3); "CreativePolicy write authority" is out of scope for M5B
  (`...-design.md:1152`); reading a permission out of `content` prose would violate "prose is never
  a visibility input" (`...-design.md:834`, compilation order step 9 `:877`); the reuse research
  lists "whether author-only truth may be emitted … for each … consumer" as still unresolved
  (`2026-09-08-r2-m5b-reuse-and-boundary-research.md:187`).

### Option D — require BOTH the SceneContract signal AND a policy signal
- **For:** §10.1 reads "permitted by the SceneContract **and** policy" as a conjunction
  (`...-design.md:747`); mirrors the compiler's "claim proven against authority" discipline
  (`...-design.md:811-813`; `compiler.py:425-500`).
- **Against:** inherits Option C's blocker (policy side has no structured field in the M5B seam,
  `ports.py:40-46`); doubles the fixture surface for §6's test corpus.

### Option E — gate only at the request/contract layer
- **For:** co-locates with the existing first half of the rule
  (`NarrativeContextRequest._mode_requires_pov`, `narrative_context.py:212-216`); the §11 taxonomy
  already covers "inconsistent … mode, POV" (`...-design.md:950`; `errors.py:9`).
- **Against:** a flag on `NarrativeContextRequest` is self-asserted by the caller — it is **not**
  "permitted by the SceneContract and policy" (`...-design.md:747`), so this alone cannot satisfy
  the rule; it still needs A/B/C/D as the source of the permission. Also: the request contract
  raises `pydantic.ValidationError`, which is neither `NarrativeContextInputError` nor
  `NarrativeContextValidationError` (seam inconsistency noted in §5).

### Option F — enforce in the compiler's hard-validation stage
- **For:** keeps enforcement in the R2-owned compiler (R2-DEC-007,
  `R2_04_CONSOLIDATED_DECISION_LOG.md:143-158`); §11 has a row for "hard … SceneContract constraint
  blocks compilation" → `NarrativeContextValidationError` (`...-design.md:952`); the compiler
  already runs `_run_hard_validation` via `NarrativeInvariantValidator.validate_scene`
  (`compiler.py:270-273`; design §6 `...-design.md:288-311`).
- **Against:** still needs A/B/C/D to define *what* the validator reads for the permission; the §11
  taxonomy's "inconsistent … mode, POV" wording points at `NarrativeContextInputError`
  (caller-correctable) rather than an integrity-class `NarrativeContextValidationError` (§5); adds a
  mode/POV concern to a validator whose design signature is `(canon, plan, scene)` with no `mode`
  argument (`...-design.md:301-311`).

### Cross-cutting facts every option must accommodate
- The mechanism is undocumented: §10.1 (`...-design.md:747`) is the sole statement; the plan doc is
  silent; "omniscient" appears nowhere else (§1).
- The reuse research frames "may author-only truth be emitted, and to whom" as an **open** design
  question (`2026-09-08-r2-m5b-reuse-and-boundary-research.md:187`) and gives no donor precedent
  (§4).
- Whatever is chosen, `NarrativeContextInputError` is the taxonomy-consistent error for
  "AUTHOR_DRAFT without POV, not permitted" (`...-design.md:950`; `errors.py:8-9`); no new error
  type is implied (§5).
- Any typed field on `SceneContract` implies a `semantic_hash_version` v1→v2 bump and touches the
  §6 fixture corpus, but needs **no new ADR / decision record** per design §2 and the research's ADR
  test (§7).
