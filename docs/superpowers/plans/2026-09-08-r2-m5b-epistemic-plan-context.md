# R2-M5B Epistemic State, Narrative Plan, and Context Compilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every behavior change and superpowers:verification-before-completion before each review gate. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the accepted M5A Canon authority with deterministic temporal/epistemic state, add a separately versioned NarrativePlan authority, and compile exact-version, visibility-safe narrative context without granting the compiler or donor systems any write authority.

**Architecture:** M5B-1 evolves the existing Canon JSON schema and replay pipeline from v1 to v2 while preserving all v1 hashes and the sole `CanonTransactionService` write boundary. M5B-2 adds an independent append-only NarrativePlan aggregate with its own repository/UoW/service and read-only exact Canon dependency. M5B-3 adds a pure-orchestrating context compiler whose dependencies are read ports only; descriptor metadata, never prose inference, controls scope, time, authority, and epistemic visibility.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async ORM, Alembic, PostgreSQL 16, SQLite focused migration tests, pytest/pytest-asyncio, ruff, basedpyright, import-linter, deptry.

**Spec:** `docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md`

## Global Constraints

- Execute only on a Codex-prepared M5B implementation worktree rooted at accepted M5A integration head `698c34f6b953bd6c7df3306da253e9827b6d94c0`. The accepted M5A chain is code-verified head `2d648546dc971af6cc8072a2765de27fa4e9472a` → evidence-only handoff `649bf01ad8db5e89efa9b7fa6e4e9171a061ce90` → merge-only integration head `698c34f6b953bd6c7df3306da253e9827b6d94c0`; Task 0 must prove each transition.
- Preserve all unrelated work. Do not rebase or implement in the M5B design worktree. Do not overwrite an existing worktree or branch.
- `CanonTransactionService` remains the sole Canon writer. M5B adds exactly `UPDATE_KNOWLEDGE` and `ADD_TEMPORAL_RELATION`; it does not add an Event mutation operation or a second proposition authority.
- V1 replay and hashes are immutable compatibility evidence. Schema-specific serialization must exclude v2 empty maps when verifying `r2-canon-schema-v1`.
- `NarrativePlanService` is the sole plan writer. It receives an exact-version Canon reader, never a Canon write repository/UoW, and validates every SceneContract on `canon_basis` before persistence.
- `NarrativeContextCompiler` receives only read protocols and a deterministic `TokenCounter`. It must not import authority write ports, UoW factories, SQLAlchemy, providers, runtimes, donor memory, or text-inspection visibility logic.
- Every authority/read/compiler operation includes `(user_id, project_name)`. Unknown and cross-scope identifiers collapse to the same public not-found result.
- All intervals are timezone-aware UTC half-open intervals. No wall clock supplies story time or semantic transition time.
- Tests use public interfaces and explicit fakes; do not patch private production symbols, add sleeps, use automatic retries, or add a latest-version fallback.
- Each task follows RED → GREEN → focused regression → test audit → commit. A command that collects zero tests is a failure and must be broadened.
- Before every `git add`, inspect `git status --short`; stage only paths owned by the current task. Directory-level staging commands below are valid only when the status contains no unrelated change.
- M5B-1, M5B-2, and M5B-3 stop at their named review gates. Claude Code does not cross a gate until Codex records approval.
- No passing test or review authorizes an operating migration, production data operation, provider/network call, worker start, push, publish, or UI/runtime integration.
- Prior design discovery used a pre-acceptance M5A graph generation and is not execution evidence. Task 0 must
  index the exact implementation worktree at accepted integration head ancestry, record the new generation and
  indexed HEAD, call coverage for every relied-on code path, and directly read every missed or stale range.

## File and Responsibility Map

| File | Responsibility |
|---|---|
| `docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md` | Human-approved M5B design bytes materialized over the accepted M5A integration head |
| `docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md` | Human-approved execution plan bytes |
| `docs/r2/evidence/R2_M5B_DOCUMENT_APPROVAL.json` | External manifest binding approved document hashes/source head without self-reference |
| `r2/contracts/narrative.py` | V2 proposition, knowledge, temporal values and exactly two new Canon operations |
| `r2/contracts/narrative_plan.py` | Canon basis, plan hierarchy, typed SceneContract constraints, plan revisions/approvals/snapshots |
| `r2/contracts/narrative_context.py` | Source descriptors, retrieval snapshots, compile requests, segments, traces, and packs |
| `r2/contracts/__init__.py` | Deliberate public contract exports |
| `r2/narrative/schema_upgrade.py` | Pure v1→v2 Canon content upgrade and legal schema-transition checks |
| `r2/narrative/hashing.py` | Schema-specific Canon serialization plus unchanged v1 hash domains |
| `r2/narrative/canon_state.py` | Ordered application of v1/v2 operations and explicit supersession |
| `r2/narrative/temporal.py` | Normalized temporal graph, equivalence classes, DAG and chronology proofs |
| `r2/narrative/epistemic.py` | Proposition identity and fail-closed `EpistemicViewResolver` |
| `r2/narrative/validation.py` | Pure `NarrativeInvariantValidator` Canon and SceneContract rule families |
| `r2/narrative/errors.py` | Stable schema, epistemic, temporal, and validation errors |
| `r2/narrative/canon_transaction.py` | Existing sole Canon transaction updated to dispatch schema selectors |
| `r2/narrative/canon_resolver.py` | Mixed v1/v2 exact replay and projection verification |
| `r2/narrative/integrity.py` | Mixed-schema authoritative replay/integrity checks |
| `r2/narrative/__init__.py` | Public pure/service exports; no persistence exports |
| `r2/narrative_plan/hashing.py` | Plan, revision, and SceneContract semantic hashes |
| `r2/narrative_plan/validation.py` | Pure hierarchy, scene constraint, scene-version, and outcome validation |
| `r2/narrative_plan/integrity.py` | Executable logical-head and immutable-lineage integrity checks |
| `r2/narrative_plan/ports.py` | Plan read/write/UoW protocols and exact Canon read protocol |
| `r2/narrative_plan/service.py` | Sole genesis/append `commit_revision` transaction orchestration |
| `r2/narrative_plan/errors.py` | Stable plan error taxonomy |
| `r2/narrative_plan/__init__.py` | Public plan service and validation API |
| `r2/narrative_context/ports.py` | Compiler-only exact read protocols and deterministic token counter |
| `r2/narrative_context/compiler.py` | Exact reads, descriptor proof, filtering, deduplication, budget, trace, hashes |
| `r2/narrative_context/errors.py` | Stable input, metadata, validation, and budget errors |
| `r2/narrative_context/__init__.py` | Public compiler API |
| `lib/db/models/narrative_plan.py` | Scoped plan head and immutable plan-version ORM tables |
| `lib/db/models/__init__.py` | Register plan models with SQLAlchemy metadata |
| `lib/db/repositories/narrative_plan.py` | Scoped transaction-bound plan persistence adapter |
| `lib/db/narrative_plan_uow.py` | Fresh AsyncSession transaction lifecycle for plan authority |
| `alembic/versions/5b7c4a0e0001_add_narrative_plans.py` | Additive plan tables from accepted M5A migration head |
| `pyproject.toml` | Import-fitness boundaries for pure narrative, plan, and compiler modules |
| `scripts/r2/verify_m5b_scope.py` | Implementation/evidence-only allowlists and verified-head handoff check |
| `tests/unit/r2/contracts/test_narrative_v2.py` | V2 contract, discriminator, normalization, and compatibility tests |
| `tests/unit/r2/narrative/test_schema_upgrade.py` | Pure schema transition and v1 hash preservation tests |
| `tests/unit/r2/narrative/test_temporal.py` | Normalization, DAG, anchor, path, and incomparable tests |
| `tests/unit/r2/narrative/test_epistemic.py` | Proposition identity and resolver cardinality tests |
| `tests/unit/r2/narrative/test_validation_m5b.py` | Truth interval, evidence, bootstrap, backlink, and same-delta repair tests |
| `tests/integration/r2/narrative/test_canon_v2_replay.py` | Transaction/replay/integrity across v1→v2 and projection loss |
| `tests/unit/r2/contracts/test_narrative_plan.py` | Strict plan and typed SceneContract contracts |
| `tests/unit/r2/narrative_plan/test_hashing.py` | Stable plan/scene semantic identities |
| `tests/unit/r2/narrative_plan/test_validation.py` | Hierarchy and exact constraint matrices |
| `tests/integration/r2/narrative_plan/test_integrity.py` | Logical head, parent lineage, and scoped integrity corruption tests |
| `tests/unit/lib/db/models/test_narrative_plan.py` | ORM shape and DB constraint metadata |
| `tests/integration/lib/db/migrations/test_alembic_narrative_plan.py` | SQLite upgrade/downgrade proof |
| `tests/integration/lib/db/repositories/test_narrative_plan.py` | Scoped repository/UoW/uniqueness/rollback behavior |
| `tests/integration/r2/narrative_plan/test_service.py` | Genesis commit, append, retry, stale head, approval, exact Canon basis, fault windows |
| `tests/integration/r2/narrative_plan/test_concurrency.py` | PostgreSQL same-plan serialization and different-plan concurrency |
| `tests/unit/r2/contracts/test_narrative_context.py` | Descriptor, snapshot, request, trace, and pack contracts |
| `tests/unit/r2/narrative_context/test_compiler.py` | Exact reads, visibility, filtering, deduplication, budget, determinism |
| `tests/unit/r2/test_m5b_architecture_boundaries.py` | AST/import authority and no-write compiler fitness tests |
| `tests/fixtures/r2/m5b_narrative_corpus.py` | Versioned 30-scene corpus built from public inputs |
| `tests/fixtures/r2/__init__.py` | Fixture package marker |
| `tests/integration/r2/test_m5b_acceptance.py` | Real public-path fixture and adversarial mutation acceptance |
| `tests/unit/scripts/r2/test_verify_m5b_scope.py` | Scope verifier allow/reject behavior |
| `docs/r2/evidence/R2_M5B_STARTING_STATE.json` | Accepted lineage, document hashes, graph coverage, migration reservation, baseline gates |
| `docs/r2/evidence/R2_M5B_1_REVIEW.md` | Canon v2 checkpoint evidence and Codex verdict |
| `docs/r2/evidence/R2_M5B_2_REVIEW.md` | Plan authority checkpoint evidence and Codex verdict |
| `docs/r2/evidence/R2_M5B_3_REVIEW.md` | Compiler leakage/budget checkpoint evidence and Codex verdict |
| `docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md` | Clean verified head, full commands, PostgreSQL identity, acceptance counters, handoff proof |

---

### Task 0: Pin the accepted M5A handoff and implementation boundary

**Files:**
- Create: `docs/r2/evidence/R2_M5B_STARTING_STATE.json`

**Interfaces:**
- Consumes the accepted M5A evidence, exact M5A handoff, approved M5B spec/plan, current migration graph, current source graph, and baseline gates.
- Produces one machine-readable checkpoint on a clean `feat/r2-m5b-epistemic-plan-context` implementation worktree.

- [ ] **Step 1: Verify the current accepted M5A lineage**

The implementation base is the integrated R2 head, not the retired pre-review M5A handoff:

```text
M5A_VERIFIED_HEAD   = 2d648546dc971af6cc8072a2765de27fa4e9472a
M5A_HANDOFF_HEAD    = 649bf01ad8db5e89efa9b7fa6e4e9171a061ce90
M5A_INTEGRATION_HEAD = 698c34f6b953bd6c7df3306da253e9827b6d94c0
```

Run:

```bash
git merge-base --is-ancestor 2d648546dc971af6cc8072a2765de27fa4e9472a 649bf01ad8db5e89efa9b7fa6e4e9171a061ce90
git diff --name-only 2d648546dc971af6cc8072a2765de27fa4e9472a...649bf01ad8db5e89efa9b7fa6e4e9171a061ce90
git show -s --format='%P' 698c34f6b953bd6c7df3306da253e9827b6d94c0
git diff --check 2173463e88218248d8805e4f20df2102d1d6743a...2d648546dc971af6cc8072a2765de27fa4e9472a
```

Expected: both ancestry/diff checks exit 0; the verified→handoff diff is exactly
`docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md`; integration-head parents are exactly
`2173463e88218248d8805e4f20df2102d1d6743a` and
`649bf01ad8db5e89efa9b7fa6e4e9171a061ce90`.

- [ ] **Step 2: Parse exact M5A evidence values**

```bash
uv run python -c 'import re; from pathlib import Path; p=Path("docs/r2/evidence/R2_M5A_FINAL_VERIFICATION.md").read_text(); patterns=(r"^- Verified head .*: `2d648546dc971af6cc8072a2765de27fa4e9472a`$",r"^- Result: \*\*144 passed\*\*, 0 failed, exit 0 \(SQLite\)\.$",r"^- Result: \*\*12595 passed, 2 skipped\*\*, 0 failed, 0 errors, exit 0 \(SQLite\)\.$",r"^  → \*\*607 passed\*\*, 0 failed, exit 0\.",r"^  → \*\*70 passed\*\*, 0 failed, exit 0\.$",r"^\| `uv run alembic heads` \| `5a7c4a0e0001 \(head\)` \| `5a7c4a0e0001 \(head\)` \|$"); missing=[pattern for pattern in patterns if re.search(pattern,p,re.MULTILINE) is None]; assert not missing,missing'
```

Expected: exit 0 with the verified head and every exact focused/full/PostgreSQL count present. Treat these as prerequisite evidence, not current M5B validation.

- [ ] **Step 3: Verify the external document-approval manifest**

After Human approval, Codex creates `docs/r2/evidence/R2_M5B_DOCUMENT_APPROVAL.json` on the design
branch. It records `schema_version="r2-m5b-document-approval-v1"`, `status="APPROVED"`,
`m5a_integration_head`, `approved_docs_source_head`, both document paths and SHA-256 values,
`approved_by`, and a timezone-aware `approved_at`. The manifest's source head is the plan-revision
commit immediately before the manifest commit, avoiding any self-referential hash.

In the Codex-prepared implementation worktree, run:

```bash
uv run python -c 'import hashlib,json,re; from datetime import datetime; from pathlib import Path; m=json.loads(Path("docs/r2/evidence/R2_M5B_DOCUMENT_APPROVAL.json").read_text()); assert m["schema_version"]=="r2-m5b-document-approval-v1"; assert m["status"]=="APPROVED"; assert m["m5a_integration_head"]=="698c34f6b953bd6c7df3306da253e9827b6d94c0"; assert re.fullmatch(r"[0-9a-f]{40}",m["approved_docs_source_head"]); assert m["approved_by"].strip(); assert datetime.fromisoformat(m["approved_at"]).utcoffset() is not None; pairs=((m["design_path"],m["design_sha256"]),(m["plan_path"],m["plan_sha256"])); assert [p for p,_ in pairs]==["docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md","docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md"]; bad=[path for path,want in pairs if not re.fullmatch(r"[0-9a-f]{64}",want) or hashlib.sha256(Path(path).read_bytes()).hexdigest()!=want]; assert not bad,bad'
git branch --show-current
git merge-base --is-ancestor 698c34f6b953bd6c7df3306da253e9827b6d94c0 HEAD
git diff --name-only 698c34f6b953bd6c7df3306da253e9827b6d94c0...HEAD
git log --format='%H %P %s' --name-only 698c34f6b953bd6c7df3306da253e9827b6d94c0..HEAD
git status --short
M5B_DOCUMENT_MATERIALIZATION_HEAD="$(git rev-parse HEAD)"
```

Expected: branch is `feat/r2-m5b-epistemic-plan-context`; status is empty; the net diff contains
exactly the design spec, this plan, and `R2_M5B_DOCUMENT_APPROVAL.json`. Inspect every commit in the
range and require every changed path to be one of those three. Define the observed clean HEAD as
`M5B_DOCUMENT_MATERIALIZATION_HEAD`; no implementation file may precede the Task 0 checkpoint.

- [ ] **Step 4: Reserve the migration and verify baseline selectors**

```bash
uv run alembic heads
rg -n '5b7c4a0e0001' alembic/versions
rg -n 'r2-canon-schema-v1|r2-canon-content-v1|r2-canon-delta-v1' r2/narrative r2/contracts tests/unit/r2 tests/integration/r2
```

Expected: exactly `5a7c4a0e0001 (head)`; no existing `5b7c4a0e0001`; v1 selectors are present and become explicit compatibility fixtures rather than being replaced.

- [ ] **Step 5: Refresh graph and baseline gates**

Index the exact implementation worktree, run task-directed graph queries for `CanonTransactionService`, `apply_canon_delta`, `validate_canon_candidate`, `CanonResolver`, `CanonIntegrityChecker`, repository/UoW implementations and their callers, then call `check_index_coverage` for every file in the responsibility map that already exists. Directly read every missed/stale range.

```bash
uv run ruff check r2 lib/db tests/unit/r2 tests/integration/r2
uv run basedpyright --warnings
uv run lint-imports
uv run python -m pytest tests/unit/r2/narrative tests/integration/r2/narrative -q
uv run python scripts/audit_tests.py --check
```

Expected: all commands exit 0 and pytest collects tests.

- [ ] **Step 6: Record and commit the checkpoint**

Record all three M5A SHAs, the exact verified→handoff evidence-only diff, approval-manifest fields,
`M5B_DOCUMENT_MATERIALIZATION_HEAD`, its exact three-path materialization diff, recomputed document
hashes, clean status, Alembic head/reservation, graph project/generation/indexed HEAD/coverage/fallbacks,
and every command/exit code.

```bash
sha256sum docs/superpowers/specs/2026-09-08-r2-m5b-epistemic-plan-context-design.md docs/superpowers/plans/2026-09-08-r2-m5b-epistemic-plan-context.md
git add docs/r2/evidence/R2_M5B_STARTING_STATE.json
git commit -m "docs(r2): pin M5B starting state"
M5B_TASK0_HEAD="$(git rev-parse HEAD)"
git diff --name-only "$M5B_DOCUMENT_MATERIALIZATION_HEAD"..."$M5B_TASK0_HEAD"
git status --short
```

Expected: checkpoint committed; materialization→Task-0 diff is exactly
`docs/r2/evidence/R2_M5B_STARTING_STATE.json`; status is empty. Task 1 starts only from
`M5B_TASK0_HEAD` after this gate.

---

### Task 1: Add strict Canon schema-v2 contracts without changing v1 bytes

**Files:**
- Modify: `r2/contracts/narrative.py`
- Modify: `r2/contracts/__init__.py`
- Modify: `r2/narrative/errors.py`
- Create: `tests/unit/r2/contracts/test_narrative_v2.py`

**Interfaces:**
- Produces `EpistemicProposition`, `KnowledgeState`, `TemporalRelation`, `UpdateKnowledgeOperation`, `AddTemporalRelationOperation`, expanded `CanonOperation`, and v2-capable `CanonContent`/delta/approval selectors.
- Preserves every existing v1 model dump accepted by M5A.

- [ ] **Step 1: Write RED tests for strict values and exactly two new operation tags**

```python
def test_schema_v2_adds_exactly_two_operation_kinds() -> None:
    assert operation_kinds_for("r2-canon-schema-v1") == {
        "ADD_ENTITY", "UPDATE_ENTITY", "ADD_FACT", "RETIRE_FACT", "ADD_EVENT"
    }
    assert operation_kinds_for("r2-canon-schema-v2") == {
        "ADD_ENTITY", "UPDATE_ENTITY", "ADD_FACT", "RETIRE_FACT", "ADD_EVENT",
        "UPDATE_KNOWLEDGE", "ADD_TEMPORAL_RELATION",
    }


def test_update_knowledge_keeps_bootstrap_binding_operation_local() -> None:
    operation = UpdateKnowledgeOperation(
        operation_id="op-k-1", target_id="k-1", subject_entity_id="character-a",
        proposition=proposition("ring", "owner", "character-b"), epistemic_state="KNOWN",
        effective_from=AT_10, evidence_event_refs=[],
        bootstrap_author_decision_ref="decision-7",
    )
    assert operation.bootstrap_author_decision_ref == "decision-7"
```

Also test UTC awareness, half-open non-empty finite intervals, sorted duplicate-free set fields, proposition subject versus knowledge holder, normalized simultaneous endpoints, target/contained ID equality, extra rejection, and provider/runtime field rejection.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_v2.py -q
```

Expected: import/attribute failures for the new types.

- [ ] **Step 3: Implement the exact v2 contracts**

Use these discriminated shapes:

```python
class EpistemicState(StrEnum):
    KNOWN = "KNOWN"
    SUSPECTED = "SUSPECTED"
    FALSE_BELIEF = "FALSE_BELIEF"
    UNKNOWN = "UNKNOWN"


class UpdateKnowledgeOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["UPDATE_KNOWLEDGE"] = "UPDATE_KNOWLEDGE"
    target_id: NonEmptyStr
    subject_entity_id: NonEmptyStr
    proposition: EpistemicProposition
    epistemic_state: EpistemicState
    effective_from: datetime
    effective_until: datetime | None = None
    evidence_event_refs: list[NonEmptyStr] = Field(default_factory=list)
    bootstrap_author_decision_ref: NonEmptyStr | None = None
    supersedes_knowledge_state_id: NonEmptyStr | None = None


class AddTemporalRelationOperation(R2ContractModel):
    operation_id: NonEmptyStr
    kind: Literal["ADD_TEMPORAL_RELATION"] = "ADD_TEMPORAL_RELATION"
    target_id: NonEmptyStr
    temporal_relation: TemporalRelation
```

Add the three v2 maps to `CanonContent` with empty default factories so old serialized projections parse, but do not yet change hashing. Let `CanonDeltaPayload.content_schema_version` and `CanonCommitApproval.content_schema_version` accept the literal union of v1/v2. Contract validation rejects v2 operations in v1 payloads.

- [ ] **Step 4: Run GREEN and existing contract regression**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative.py tests/unit/r2/contracts/test_narrative_v2.py -q
uv run python scripts/audit_tests.py --check
git add r2/contracts r2/narrative/errors.py tests/unit/r2/contracts
git commit -m "feat(r2): define M5B Canon contracts"
```

Expected: both test files pass; audit exits 0; commit contains contracts/errors/tests only.

---

### Task 2: Implement schema-specific hashing and pure v1→v2 upgrade

**Files:**
- Create: `r2/narrative/schema_upgrade.py`
- Modify: `r2/narrative/hashing.py`
- Modify: `r2/narrative/canon_state.py`
- Test: `tests/unit/r2/narrative/test_schema_upgrade.py`
- Test: `tests/unit/r2/narrative/test_hashing.py`

**Interfaces:**
- Produces `upgrade_canon_content`, `require_schema_transition`, and schema-specific canonical content payloads.
- Changes `apply_canon_delta` to accept the base schema selector explicitly and return content under the delta selector.

- [ ] **Step 1: Freeze v1 hash vectors and write RED transition tests**

```python
def test_v1_hash_ignores_v2_default_maps() -> None:
    parsed = CanonContent.model_validate(V1_CONTENT_JSON)
    assert compute_canon_content_hash(parsed, schema_version=SCHEMA_V1) == M5A_V1_GOLDEN_HASH


def test_upgrade_is_pure_and_downgrade_is_rejected() -> None:
    upgraded = upgrade_canon_content(v1_content(), from_schema=SCHEMA_V1, to_schema=SCHEMA_V2)
    assert upgraded.entities_by_id == v1_content().entities_by_id
    assert upgraded.knowledge_states_by_id == {}
    with pytest.raises(NarrativeSchemaVersionError):
        require_schema_transition(from_schema=SCHEMA_V2, to_schema=SCHEMA_V1)
```

Derive `M5A_V1_GOLDEN_HASH` once from the accepted M5A implementation before modifying hashing and commit the literal into the test.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_schema_upgrade.py tests/unit/r2/narrative/test_hashing.py -q
```

Expected: new module/API failures.

- [ ] **Step 3: Implement explicit selector dispatch**

```python
def canonical_canon_content_payload(content: CanonContent, *, schema_version: str) -> JSONValue:
    common = {
        "entities_by_id": content.entities_by_id,
        "facts_by_id": content.facts_by_id,
        "events_by_id": content.events_by_id,
    }
    if schema_version == SCHEMA_V1:
        return ensure_json_value(common)
    if schema_version == SCHEMA_V2:
        return ensure_json_value({
            **common,
            "epistemic_propositions_by_ref": content.epistemic_propositions_by_ref,
            "knowledge_states_by_id": content.knowledge_states_by_id,
            "temporal_relations_by_id": content.temporal_relations_by_id,
        })
    raise NarrativeSchemaVersionError(schema_version)
```

Keep `sha256`, `r2-canon-delta-v1`, and `r2-canon-content-v1`. Legal transitions are genesis→v1/v2, v1→v1/v2, and v2→v2. Reject v2→v1 and unknown selectors. Never infer the base schema from whether new maps are empty.

- [ ] **Step 4: Integrate the reducer boundary and run GREEN**

Change the reducer signature to:

```python
def apply_canon_delta(
    base: CanonContent,
    delta: CanonDelta,
    *,
    base_schema_version: str | None,
) -> CanonContent:
```

Upgrade before applying operations; assert operation legality against the target selector. Update all direct callers in later Task 5, but adapt existing pure tests here.

```bash
uv run python -m pytest tests/unit/r2/narrative/test_hashing.py tests/unit/r2/narrative/test_schema_upgrade.py tests/unit/r2/narrative/test_canon_state.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative/schema_upgrade.py r2/narrative/hashing.py r2/narrative/canon_state.py tests/unit/r2/narrative
git commit -m "feat(r2): preserve Canon v1 hashes across schema v2"
```

---

### Task 3: Build the deterministic temporal graph

**Files:**
- Create: `r2/narrative/temporal.py`
- Modify: `r2/narrative/canon_state.py`
- Test: `tests/unit/r2/narrative/test_temporal.py`

**Interfaces:**
- Produces `normalized_relation_key`, `TemporalGraph`, `TemporalOrder`, and deterministic validation findings/path evidence.
- Reducer stores immutable temporal relations and rejects target/ID reuse before semantic validation.

- [ ] **Step 1: Write RED graph tests**

```python
def test_simultaneous_classes_are_collapsed_before_cycle_detection() -> None:
    graph = TemporalGraph.from_canon(canon_with(
        simultaneous("e-a", "e-b"), before("e-b", "e-c"), before("e-c", "e-a")
    ))
    assert [f.rule_id for f in graph.findings] == ["TIME_GRAPH_CYCLE"]


def test_duplicate_normalized_relation_ids_fail() -> None:
    report = validate_relations([simultaneous("e-b", "e-a", id="r-1"), simultaneous("e-a", "e-b", id="r-2")])
    assert [f.rule_id for f in report.findings] == ["TIME_GRAPH_DUPLICATE_NORMALIZED_KEY"]
```

Cover self edges, missing events, direct/transitive cycles, BEFORE inside one simultaneous class, anchor contradictions, reachable paths, endpoint canonicalization, and stable incomparable results.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_temporal.py -q
```

- [ ] **Step 3: Implement one normalized graph representation**

Use union-find for `SIMULTANEOUS`, then a sorted adjacency DAG of equivalence-class IDs. Topological traversal and finding output must sort IDs so insertion/dict order cannot change evidence. `compare(left, right)` returns `BEFORE`, `AFTER`, `SIMULTANEOUS`, or `INCOMPARABLE`; `proof_path` returns the stable lexicographically first shortest path.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_temporal.py tests/unit/r2/narrative/test_canon_state.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative/temporal.py r2/narrative/canon_state.py tests/unit/r2/narrative
git commit -m "feat(r2): validate Canon temporal relations"
```

---

### Task 4: Implement epistemic identity, reducer transitions, and fail-closed views

**Files:**
- Create: `r2/narrative/epistemic.py`
- Modify: `r2/narrative/canon_state.py`
- Modify: `r2/narrative/__init__.py`
- Test: `tests/unit/r2/narrative/test_epistemic.py`
- Test: `tests/unit/r2/narrative/test_canon_state.py`

**Interfaces:**
- Produces content-addressed `proposition_ref`, `EpistemicViewResolver`, and immutable `EpistemicView`/item values.
- Applies explicit knowledge supersession without mutating historical Events.

- [ ] **Step 1: Write RED identity, transition, and cardinality tests**

```python
def test_historical_evidence_event_needs_no_backlink() -> None:
    candidate = apply_update(base_with_event("seen-ring", state_effect_refs=[]), known_op(evidence=["seen-ring"]))
    assert candidate.knowledge_states_by_id["k-1"].evidence_event_refs == ["seen-ring"]


def test_resolver_raises_instead_of_picking_latest_corrupt_state() -> None:
    with pytest.raises(EpistemicIntegrityError):
        EpistemicViewResolver().resolve(canon=corrupt_overlap(), subject_entity_id="char-a", at=AT_12)
```

Also cover hash mismatch, ref reuse with different proposition bytes, exact supersession ID/key/activity, prior interval closure at the new boundary, backdated transitions, absent/one/>1 resolver cardinality, stable category sorting, evidence union, and deterministic view hash.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_epistemic.py tests/unit/r2/narrative/test_canon_state.py -q
```

- [ ] **Step 3: Implement identity and reducer behavior**

```python
def compute_proposition_ref(value: EpistemicPropositionValue) -> str:
    payload = {"schema": "r2-epistemic-proposition-v1", **value.model_dump(mode="json")}
    return "ep:" + sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()
```

The operation inserts/deduplicates the proposition by ref, closes only the explicitly named prior state with `model_copy`, and appends the new immutable state. It never adds to an old `Event.state_effect_refs`. Present Event backlinks are checked later over the final candidate.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_epistemic.py tests/unit/r2/narrative/test_canon_state.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative/epistemic.py r2/narrative/canon_state.py r2/narrative/__init__.py tests/unit/r2/narrative
git commit -m "feat(r2): apply and resolve epistemic state"
```

---

### Task 5: Enforce whole-interval truth, evidence, and same-delta repair

**Files:**
- Modify: `r2/narrative/validation.py`
- Modify: `r2/contracts/narrative.py`
- Test: `tests/unit/r2/narrative/test_validation_m5b.py`
- Test: `tests/unit/r2/narrative/test_validation.py`

**Interfaces:**
- Produces severity-bearing `NarrativeValidationFinding`, `NarrativeValidationReport`, and `NarrativeInvariantValidator.validate_canon` while preserving the M5A validation entry point as a compatibility wrapper.

- [ ] **Step 1: Write RED validation matrices**

```python
@pytest.mark.parametrize(
    ("state", "facts", "expected_rule"),
    [
        ("KNOWN", [fact("owner", "b", AT_09, AT_12)], "EPI_TRUTH_INCOMPLETE_COVERAGE"),
        ("FALSE_BELIEF", [fact("owner", "c", AT_09, None)], None),
        ("FALSE_BELIEF", [], "EPI_TRUTH_CONTRADICTION_UNPROVEN"),
    ],
)
def test_truth_is_classified_over_the_complete_state_interval(state, facts, expected_rule) -> None:
    report = validate_knowledge_interval(state=knowledge(state), supporting_facts=facts)
    observed = report.findings[0].rule_id if report.findings else None
    assert observed == expected_rule
```

Add cases for adjacent Fact union coverage, open-ended knowledge requiring open-ended support, suspected evidence, unknown rules, exact bootstrap membership, event/bootstrap XOR, participant-without-evidence, optional historical backlink, non-reciprocal present backlink, direct and relation-proven future evidence, incomparable event acceptance, and Fact retirement/change with versus without same-delta closure.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_validation.py tests/unit/r2/narrative/test_validation_m5b.py -q
```

- [ ] **Step 3: Implement a pure deep validator**

```python
class NarrativeInvariantValidator:
    def validate_canon(
        self, *, base: ResolvedCanonView, delta: CanonDelta, candidate: ResolvedCanonView
    ) -> NarrativeValidationReport:
        return _validate_canon_invariants(base=base, delta=delta, candidate=candidate)
```

Use base+delta+candidate to prove operation-local bootstrap binding and same-delta repair. Compute interval union coverage by normalized boundaries; never sample only `effective_from`. For chronology, reject only when a direct anchor, simultaneous anchored class, or reachable anchored predecessor proves evidence is later. Findings sort by `(severity, rule_id, affected_refs, story_time)` and retain evidence refs/path.

- [ ] **Step 4: Preserve M5A compatibility and run GREEN**

`validate_canon_candidate(base, delta, candidate)` remains callable and delegates through synthetic resolved views with explicit selectors; existing M5A rule IDs/output remain stable for v1 inputs.

```bash
uv run python -m pytest tests/unit/r2/narrative/test_validation.py tests/unit/r2/narrative/test_validation_m5b.py tests/unit/r2/narrative/test_temporal.py -q
uv run python scripts/audit_tests.py --check
git add r2/contracts/narrative.py r2/narrative/validation.py tests/unit/r2/narrative
git commit -m "feat(r2): enforce temporal epistemic invariants"
```

---

### Task 6: Integrate schema v2 through Canon transaction, replay, and integrity

**Files:**
- Modify: `r2/narrative/canon_transaction.py`
- Modify: `r2/narrative/canon_resolver.py`
- Modify: `r2/narrative/integrity.py`
- Modify: `tests/integration/r2/narrative/_canon_authority.py`
- Create: `tests/integration/r2/narrative/test_canon_v2_replay.py`
- Modify: `tests/integration/r2/narrative/test_canon_transaction.py`
- Modify: `tests/integration/r2/narrative/test_canon_resolver.py`
- Modify: `tests/integration/r2/narrative/test_canon_integrity.py`
- Create after Codex review: `docs/r2/evidence/R2_M5B_1_REVIEW.md`

**Interfaces:**
- Makes the existing Canon authority accept legal v2 deltas, persist existing selector columns unchanged, replay mixed v1/v2 ancestry, and fail closed on selector/hash/invariant corruption.

- [ ] **Step 1: Write RED integration tests**

Cover v1 genesis→v2 transition, v2→v2, rejected v2→v1, exact retry before base conflict, projection loss/rebuild, corrupt cached projection fallback, authoritative replay failure, and failed commit leaving delta/version/head/projection counts unchanged.

```python
async def test_projection_loss_rebuilds_mixed_v1_v2_lineage(authority) -> None:
    v1 = await authority.commit(v1_genesis())
    v2 = await authority.commit(v2_knowledge_delta(base=v1.version.canon_version_id))
    await authority.delete_projection(v2.version.canon_version_id)
    rebuilt = await authority.resolve(v2.version.canon_version_id)
    assert rebuilt.content_schema_version == "r2-canon-schema-v2"
    assert rebuilt.content_hash == v2.version.content_hash
```

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/integration/r2/narrative/test_canon_v2_replay.py -q
```

- [ ] **Step 3: Thread selectors through every replay caller**

`CanonTransactionService.commit` uses the locked base view selector and the proposed delta selector, validates the candidate as resolved views, and records the target selector on version/projection. `CanonResolver._resolve_semantic_base` returns content, exact base ID, and base schema selector. `CanonIntegrityChecker` replays each version with the prior selector rather than constants. Unknown selectors remain integrity failures.

- [ ] **Step 4: Commit and freeze the M5B-1 implementation head**

```bash
git status --short
git add r2/contracts r2/narrative tests/unit/r2/contracts tests/unit/r2/narrative tests/integration/r2/narrative
git commit -m "feat(r2): complete M5B Canon schema v2"
git status --short
M5B_1_VERIFIED_HEAD="$(git rev-parse HEAD)"
```

Expected: empty status. Review the staged path list before commit and reject any path outside Task 1-6 ownership.

- [ ] **Step 5: Run fresh M5B-1 gates at the frozen head**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative.py tests/unit/r2/contracts/test_narrative_v2.py tests/unit/r2/narrative tests/integration/r2/narrative -q
uv run ruff check r2/contracts r2/narrative tests/unit/r2 tests/integration/r2/narrative
uv run basedpyright --warnings
uv run lint-imports
uv run python scripts/audit_tests.py --check
git diff --check 698c34f6b953bd6c7df3306da253e9827b6d94c0..."$M5B_1_VERIFIED_HEAD"
git status --short
```

Expected: all exit 0 while `git rev-parse HEAD` remains `M5B_1_VERIFIED_HEAD` and status remains empty.

- [ ] **Step 6: Obtain Codex review and create an evidence-only handoff**

Codex reviews the exact frozen head for contract/domain correctness. Only after an `APPROVED` verdict, Codex writes `R2_M5B_1_REVIEW.md` with the verified SHA, commands/counts, selectors, v1 golden hash, graph coverage, findings, and verdict.

```bash
git add docs/r2/evidence/R2_M5B_1_REVIEW.md
git commit -m "docs(r2): approve M5B-1 verified head"
M5B_1_HANDOFF_HEAD="$(git rev-parse HEAD)"
git status --short
```

Expected: `git diff --name-only "$M5B_1_VERIFIED_HEAD"..."$M5B_1_HANDOFF_HEAD"` returns exactly `docs/r2/evidence/R2_M5B_1_REVIEW.md`; status is empty. Task 7 starts from this handoff only.

---

### Task 7: Define and validate the NarrativePlan aggregate and typed SceneContract

**Files:**
- Create: `r2/contracts/narrative_plan.py`
- Modify: `r2/contracts/__init__.py`
- Create: `r2/narrative_plan/hashing.py`
- Create: `r2/narrative_plan/validation.py`
- Modify: `r2/narrative/validation.py`
- Create: `r2/narrative_plan/errors.py`
- Create: `r2/narrative_plan/__init__.py`
- Create: `tests/unit/r2/contracts/test_narrative_plan.py`
- Create: `tests/unit/r2/narrative_plan/test_hashing.py`
- Create: `tests/unit/r2/narrative_plan/test_validation.py`

**Interfaces:**
- Produces the complete Authorial Intent value model, deterministic identity/hash functions, hierarchy validation, pre-commit scene validation, and post-scene outcome validation.
- Reads immutable `ResolvedCanonView` values only; contains no repositories, clocks, providers, or write methods.

- [ ] **Step 1: Write RED strict-contract tests for every executable SceneContract field**

Freeze these shapes in tests and contracts:

```python
class CanonBasis(R2ContractModel):
    branch_id: NonEmptyStr
    canon_version_id: NonEmptyStr


class SceneTemporalWindow(R2ContractModel):
    effective_from: datetime
    effective_until: datetime


class SceneFactConstraint(R2ContractModel):
    constraint_id: NonEmptyStr
    constraint_kind: Literal["FACT"] = "FACT"
    subject_ref: NonEmptyStr
    predicate: NonEmptyStr
    comparison: Literal["PRESENT", "ABSENT", "EQUALS", "NOT_EQUALS"]
    expected_value: JSONValue | None = None


class SceneKnowledgeConstraint(R2ContractModel):
    constraint_id: NonEmptyStr
    constraint_kind: Literal["KNOWLEDGE"] = "KNOWLEDGE"
    subject_entity_id: NonEmptyStr
    proposition_ref: NonEmptyStr
    states: list[EpistemicState]
    include_absent: bool = False


class SceneEventConstraint(R2ContractModel):
    constraint_id: NonEmptyStr
    event_ref: NonEmptyStr | None = None
    event_type: NonEmptyStr | None = None
    participant_refs_all: list[NonEmptyStr] = Field(default_factory=list)
    location_ref: NonEmptyStr | None = None


class SceneRevealConstraint(R2ContractModel):
    constraint_id: NonEmptyStr
    proposition_ref: NonEmptyStr
    recipients: list[CharacterRevealRecipient | AudienceRevealRecipient]
```

`CharacterRevealRecipient` is discriminated by `recipient_kind="CHARACTER"`, carries `subject_entity_id`, and requires a resulting KNOWN/SUSPECTED/FALSE_BELIEF state. `AudienceRevealRecipient` is `recipient_kind="AUDIENCE"` plus `audience_scope="STORY_AUDIENCE"`. List placement supplies polarity: entry and exit state lists are required; `forbidden_knowledge` forbids any match during the window; required/forbidden Event lists have opposite polarity. Reveal constraints are outcomes and use explicit `AudienceRevealEvidence` for story audience rather than manufacturing a KnowledgeState.

Freeze the aggregate containers as well:

```python
class NarrativePlanNode(R2ContractModel):
    node_id: NonEmptyStr
    node_kind: Literal["VOLUME", "EPISODE", "ARC", "CHAPTER"]
    version: Annotated[int, Field(ge=1)]
    parent_id: NonEmptyStr | None
    sequence_index: Annotated[int, Field(ge=0)]
    intent: NonEmptyStr
    expected_progression: list[NonEmptyStr]
    child_refs: list[NonEmptyStr]
    constraints: list[NonEmptyStr]
    approval_refs: list[NonEmptyStr]


class SceneContract(R2ContractModel):
    scene_contract_id: NonEmptyStr
    version: Annotated[int, Field(ge=1)]
    semantic_hash: NonEmptyStr
    semantic_hash_algorithm: Literal["sha256"] = "sha256"
    semantic_hash_version: Literal["r2-scene-contract-content-v1"] = "r2-scene-contract-content-v1"
    sequence_index: Annotated[int, Field(ge=0)]
    purpose: NonEmptyStr
    pov: NonEmptyStr | None
    location_ref: NonEmptyStr | None
    temporal_window: SceneTemporalWindow
    participants: list[NonEmptyStr]
    required_events: list[SceneEventConstraint]
    forbidden_events: list[SceneEventConstraint]
    required_reveals: list[SceneRevealConstraint]
    forbidden_knowledge: list[SceneKnowledgeConstraint]
    entry_state_constraints: list[SceneFactConstraint | SceneKnowledgeConstraint]
    exit_state_targets: list[SceneFactConstraint | SceneKnowledgeConstraint]
    active_threads: list[NonEmptyStr]
    promise_payoff_refs: list[NonEmptyStr]
    creative_constraints: list[NonEmptyStr]
```

- [ ] **Step 2: Write RED identity and hierarchy tests**

```python
def test_changed_scene_semantics_require_exactly_next_version() -> None:
    previous = scene_contract(version=3, purpose="discover ring")
    changed = scene_contract(version=3, purpose="hide ring")
    with pytest.raises(NarrativePlanIdentityConflictError):
        validate_scene_version(previous=previous, proposed=changed)
    assert validate_scene_version(previous=previous, proposed=changed.model_copy(update={"version": 4})).ok


def test_reintroduced_scene_id_continues_last_historical_version() -> None:
    history = (scene_contract(version=1), scene_contract(version=2))
    assert next_scene_version(history=history, semantic_hash="new-hash") == 3
```

Cover new scene version 1, byte-identical scene retaining its version, changed semantic hash exactly +1, removal preserving history, no ID/version reuse, hierarchy cycle/missing child/illegal parent/child asymmetry, one parent per non-root, and duplicate `sequence_index`.

- [ ] **Step 3: Run RED**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_plan.py tests/unit/r2/narrative_plan -q
```

- [ ] **Step 4: Implement immutable plan values and hashes**

Use `NarrativePlanContent` for semantic bytes and keep commit receipt fields outside it. `NarrativePlanRevisionProposal` contains `plan_revision_id`, `plan_id`, `expected_version`, complete `proposed_content` (including exact `canon_basis`), `content_hash`, `created_at`, and `created_by`. `NarrativePlanApproval` binds `(user_id, project_name, plan_id, plan_revision_id, expected_version, content_hash)` plus one exact approval receipt.

Scene semantic hashing excludes `version`, `semantic_hash`, and commit metadata, but includes all executable fields. Plan content hashing includes scene IDs, versions, semantic hashes, hierarchy, story frame, and exact Canon basis. Use existing strict canonical JSON/NFC rules and these unchanged selectors:

```text
r2-narrative-plan-v1
r2-narrative-plan-content-v1
r2-scene-contract-content-v1
sha256
```

- [ ] **Step 5: Implement deterministic pure validation**

Extend `NarrativeInvariantValidator` with the exact `validate_scene(canon, plan, scene)` and `validate_scene_outcome(before, after, plan, scene, audience_reveal_evidence)` signatures from the spec. `validate_scene` evaluates entry at `effective_from`; interval-forbidden Knowledge detects any overlap; Event selectors use exact event refs and the required scene window; exit targets are evaluated at `effective_until`; required reveals distinguish character state from `AudienceRevealEvidence`. Indeterminate timing of a forbidden Event is blocking, not silently absent. Return the shared sorted `NarrativeValidationReport` rule families from the spec.

- [ ] **Step 6: Run GREEN and commit**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_plan.py tests/unit/r2/narrative_plan -q
uv run python scripts/audit_tests.py --check
git add r2/contracts r2/narrative_plan tests/unit/r2/contracts/test_narrative_plan.py tests/unit/r2/narrative_plan
git commit -m "feat(r2): define NarrativePlan authority contracts"
```

---

### Task 8: Add append-only plan persistence, migration, repository, and UoW

**Files:**
- Create: `lib/db/models/narrative_plan.py`
- Modify: `lib/db/models/__init__.py`
- Create: `lib/db/repositories/narrative_plan.py`
- Create: `lib/db/narrative_plan_uow.py`
- Create: `r2/narrative_plan/ports.py`
- Create: `r2/narrative_plan/integrity.py`
- Create: `alembic/versions/5b7c4a0e0001_add_narrative_plans.py`
- Create: `tests/unit/lib/db/models/test_narrative_plan.py`
- Create: `tests/integration/lib/db/migrations/test_alembic_narrative_plan.py`
- Create: `tests/integration/lib/db/repositories/test_narrative_plan.py`
- Create: `tests/integration/r2/narrative_plan/test_integrity.py`

**Interfaces:**
- Produces `NarrativePlanReadPort`, `NarrativePlanWritePort`, `NarrativePlanUnitOfWork`, their factories, scoped SQLAlchemy adapters, and read-only `NarrativePlanIntegrityChecker.check_plan(...)`.
- Adds exactly two tables; repositories never commit, rollback, or open a session.

- [ ] **Step 1: Write RED ORM and migration tests**

Assert exact table/constraint shape:

```text
narrative_plans
  plan_id primary key with user_id/project_name scope envelope
  head_version nullable
  created_at, created_by

narrative_plan_versions
  plan_id + version immutable lineage
  plan_revision_id
  parent_version nullable
  canon_branch_id + canon_version_id
  content_json + content_hash selectors
  approval_ref + approved_by + approved_at
  committed_at + committed_by
```

DB constraints must enforce one accepted `(plan_id, version)`, globally unique `plan_revision_id`, globally unique `approval_ref`, and positive version. `narrative_plan_versions.plan_id` has a physical `RESTRICT` FK to `narrative_plans.plan_id`; `(plan_id, parent_version)` has a physical nullable composite self-FK to `(plan_id, version)` with `RESTRICT`. `narrative_plans.head_version` is deliberately a logical pointer to avoid a create-time cycle. Scoped repository reads and an executable head-integrity check must reject a null head with versions, a missing head version, a head owned by another plan, a non-latest head, a parent gap, or a parent owned by another plan. User ownership uses the existing users FK/mixin convention. JSON holds the aggregate; there are no per-scene mutable tables.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/lib/db/models/test_narrative_plan.py tests/integration/lib/db/migrations/test_alembic_narrative_plan.py -q
```

- [ ] **Step 3: Implement migration and ORM**

Set:

```python
revision: str = "5b7c4a0e0001"
down_revision: str | Sequence[str] | None = "5a7c4a0e0001"
```

Upgrade creates `narrative_plans` then `narrative_plan_versions`; downgrade removes versions then plans. Test upgrade from the M5A parent, all constraints/indexes, downgrade, and upgrade again on disposable SQLite.

- [ ] **Step 4: Write RED repository/UoW tests**

Cover scoped get returning `None` for unknown and cross-scope IDs, lock-head behavior, physical plan/version and composite-parent FK enforcement, logical-head integrity failures, insert version, compare-and-set head, exact lookup by revision/approval, ordered history, no adapter commit, UoW commit/rollback, SQLite `BEGIN IMMEDIATE`, and injected flush failures leaving no rows.

- [ ] **Step 5: Implement narrow adapters**

```python
class NarrativePlanWritePort(NarrativePlanReadPort, Protocol):
    async def lock_plan(self, *, plan_id: str, project_name: str, user_id: str) -> NarrativePlanHeadSnapshot:
        pass
    async def insert_plan(self, head: NarrativePlanHeadSnapshot) -> None:
        pass
    async def insert_version(self, version: NarrativePlanVersionSnapshot) -> None:
        pass
    async def advance_head(self, *, plan_id: str, expected_version: int | None,
                           new_version: int, project_name: str, user_id: str) -> None:
        pass
    async def flush(self) -> None:
        pass
```

PostgreSQL locking uses SQLAlchemy `with_for_update()`; SQLite follows the accepted M5A UoW transaction startup.

- [ ] **Step 6: Run GREEN and commit**

```bash
uv run python -m pytest tests/unit/lib/db/models/test_narrative_plan.py tests/integration/lib/db/migrations/test_alembic_narrative_plan.py tests/integration/lib/db/repositories/test_narrative_plan.py tests/integration/r2/narrative_plan/test_integrity.py -q
uv run python scripts/audit_tests.py --check
uv run alembic heads
git add lib/db r2/narrative_plan/ports.py r2/narrative_plan/integrity.py alembic/versions/5b7c4a0e0001_add_narrative_plans.py tests/unit/lib/db/models/test_narrative_plan.py tests/integration/lib/db tests/integration/r2/narrative_plan/test_integrity.py
git commit -m "feat(r2): persist append-only NarrativePlan versions"
```

Expected: one Alembic head `5b7c4a0e0001`.

---

### Task 9: Implement the sole NarrativePlan commit service and authority gate

**Files:**
- Create: `r2/narrative_plan/service.py`
- Modify: `r2/narrative_plan/__init__.py`
- Create: `tests/integration/r2/narrative_plan/test_service.py`
- Create: `tests/integration/r2/narrative_plan/test_concurrency.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/r2/test_m5b_architecture_boundaries.py`
- Create after Codex review: `docs/r2/evidence/R2_M5B_2_REVIEW.md`

**Interfaces:**
- Produces `NarrativePlanService.commit_revision` as the only plan write orchestration; `expected_version=None` is genesis and `expected_version=N` appends version `N + 1`.
- Consumes `NarrativePlanUnitOfWorkFactory`, exact read-only `CanonVersionReader`, pure hashing/validation, injected ID factory and clock.

```python
async def commit_revision(
    self, *, proposal: NarrativePlanRevisionProposal, approval: NarrativePlanApproval,
    project_name: str, user_id: str, now: datetime,
) -> NarrativePlanCommitResult:
    pass
```

- [ ] **Step 1: Write RED service behavior tests**

```python
async def test_exact_retry_precedes_stale_head_check(service) -> None:
    first = await service.commit_revision(proposal=PROPOSAL, approval=APPROVAL, project_name=PROJECT, user_id=USER, now=NOW)
    retry = await service.commit_revision(proposal=PROPOSAL, approval=APPROVAL, project_name=PROJECT, user_id=USER, now=NOW)
    assert retry == first
    assert service.uow.write_count_after_first_commit == 0


async def test_plan_commit_validates_only_exact_canon_basis(service) -> None:
    service.canon_reader.set_versions(pinned=invalid_for_scene(), head=valid_for_scene())
    with pytest.raises(NarrativePlanValidationError):
        await service.commit_revision(proposal=PROPOSAL, approval=APPROVAL, project_name=PROJECT, user_id=USER, now=NOW)
    assert service.canon_reader.requested_ids == [PROPOSAL.canon_basis.canon_version_id]
```

Cover genesis through `commit_revision(expected_version=None)`, append, exact retry, genesis against an existing plan, append against a missing plan, revision/content/scope mismatch, stale head zero writes, approval tuple mismatch, approval reuse across another tuple zero writes, scene identity/version history, all flush/commit fault stages, and no Canon write calls.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/integration/r2/narrative_plan/test_service.py -q
```

- [ ] **Step 3: Implement transaction order**

Inside one fresh plan UoW: look up exact retry by revision ID before expected-head comparison and verify its complete tuple. For `expected_version=None`, require no scoped plan row, resolve and validate the exact Canon basis, insert the plan head and immutable version 1 in the same transaction, then advance the head. For `expected_version=N`, require and lock the scoped plan at head `N`, then append version `N + 1`. Both paths verify branch, hierarchy, every scene, scene history, approval, and content hash before writes; flush and commit once. No public `create()` exists, and no empty or unapproved plan row can persist.

- [ ] **Step 4: Add PostgreSQL concurrency proof**

Use the repository's disposable PostgreSQL fixture. Two same-plan proposals with one expected head produce exactly one accepted next version and one `NarrativePlanVersionConflict`. Two different plans can commit independently. After disposing engines and recreating services, both accepted heads and histories resolve identically.

```bash
uv run python -m pytest tests/integration/r2/narrative_plan/test_concurrency.py -q -m postgres
```

- [ ] **Step 5: Add import/authority fitness rules**

Tests and import-linter enforce:

```text
r2.contracts and pure r2.narrative modules -> forbid lib.db, server, providers, runtime
r2.narrative_plan.service -> forbid Canon write ports and Canon UoW factories
r2.narrative_context -> forbid all authority write ports/UoWs, lib.db, providers, runtime
only CanonTransactionService references CanonWriteRepositoryPort
only NarrativePlanService references NarrativePlanWritePort
```

Use AST/import inspection like the accepted M5A architecture tests; do not create a baseline ignore for a new violation.

- [ ] **Step 6: Commit and freeze the M5B-2 implementation head**

```bash
git status --short
git add r2/narrative_plan r2/contracts r2/narrative/validation.py lib/db alembic/versions/5b7c4a0e0001_add_narrative_plans.py pyproject.toml tests/unit/r2 tests/unit/lib/db/models/test_narrative_plan.py tests/integration/lib/db tests/integration/r2/narrative_plan
git commit -m "feat(r2): complete NarrativePlan authority"
git status --short
M5B_2_VERIFIED_HEAD="$(git rev-parse HEAD)"
```

Expected: status is empty and the head descends from `M5B_1_HANDOFF_HEAD`.

- [ ] **Step 7: Run fresh M5B-2 gates at the frozen head**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_plan.py tests/unit/r2/narrative_plan tests/unit/lib/db/models/test_narrative_plan.py tests/integration/lib/db/migrations/test_alembic_narrative_plan.py tests/integration/lib/db/repositories/test_narrative_plan.py tests/integration/r2/narrative_plan tests/unit/r2/test_m5b_architecture_boundaries.py -q
uv run python -m pytest tests/integration/r2/narrative_plan/test_concurrency.py -q -m postgres
uv run ruff check r2/narrative_plan r2/contracts/narrative_plan.py lib/db tests/unit/r2 tests/integration/r2/narrative_plan
uv run basedpyright --warnings
uv run lint-imports
uv run python scripts/audit_tests.py --check
git diff --check "$M5B_1_HANDOFF_HEAD"..."$M5B_2_VERIFIED_HEAD"
git status --short
```

Expected: all commands exit 0 while HEAD remains `M5B_2_VERIFIED_HEAD` and status remains empty.

- [ ] **Step 8: Obtain Codex review and create an evidence-only handoff**

Codex reviews the exact frozen head for authority, approval, FK/integrity, rollback, and PostgreSQL concurrency behavior. Only after an `APPROVED` verdict, Codex writes `R2_M5B_2_REVIEW.md` with the verified SHA, migration head, commands/counts, PostgreSQL identity, concurrency outcomes, failure-window row counts, approval uniqueness, graph coverage, findings, and verdict.

```bash
git add docs/r2/evidence/R2_M5B_2_REVIEW.md
git commit -m "docs(r2): approve M5B-2 verified head"
M5B_2_HANDOFF_HEAD="$(git rev-parse HEAD)"
git status --short
```

Expected: `git diff --name-only "$M5B_2_VERIFIED_HEAD"..."$M5B_2_HANDOFF_HEAD"` returns exactly `docs/r2/evidence/R2_M5B_2_REVIEW.md`; status is empty. Task 10 starts from this handoff only.

---

### Task 10: Define context contracts, immutable source descriptors, and read-only ports

**Files:**
- Create: `r2/contracts/narrative_context.py`
- Modify: `r2/contracts/__init__.py`
- Create: `r2/narrative_context/ports.py`
- Create: `r2/narrative_context/errors.py`
- Create: `r2/narrative_context/__init__.py`
- Create: `tests/unit/r2/contracts/test_narrative_context.py`
- Modify: `tests/unit/r2/test_m5b_architecture_boundaries.py`

**Interfaces:**
- Produces strict immutable descriptors/snapshots/requests/packs and only the six read dependencies specified by the design.

- [ ] **Step 1: Write RED descriptor and request tests**

```python
def test_subject_visibility_requires_explicit_exact_basis_and_proofs() -> None:
    with pytest.raises(ValidationError):
        descriptor(visibility_policy="SUBJECTS", visibility_subjects=["char-a"], proposition_refs=[])


def test_author_only_descriptor_has_no_subject_claims() -> None:
    with pytest.raises(ValidationError):
        descriptor(visibility_policy="AUTHOR_ONLY", visibility_subjects=["char-a"])
```

Cover mandatory nullable interval fields, finite ordering, duplicate-free sorted refs, authority class requirements, exact basis requirements, descriptor-ref hash mismatch, prose content hash mismatch, snapshot scope and immutable inline descriptors, strict modes, UTC story time, positive token budget, exact version IDs, and provider/runtime field rejection.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_context.py -q
```

- [ ] **Step 3: Implement complete values and hashes**

`NarrativeSourceDescriptor` contains every field from spec Section 10.2. Its `descriptor_ref` excludes itself but includes explicit null interval endpoints; content hash is SHA-256 over NFC-normalized UTF-8 with LF line endings. `RetrievalSnapshot` contains the scope envelope and inline descriptor per candidate. `NarrativeContextRequest` pins Canon version, plan version, SceneContract ID/version, policy ref, mode, POV, story time, snapshot ref, and budget.

Selection traces are visibility-tiered. A source rejected by scope, authority, time, metadata, or epistemic visibility contains only `candidate_id`, non-secret `source_ref`, status, and omission reason—no prose, content/descriptor hash, hidden token count, proposition refs, or visibility proof refs. Only `INCLUDED`, or a source that passed all visibility gates and was then omitted as `DUPLICATE`/`BUDGET`, may carry content hash and token count. Enums include all ten channels and the stable reasons `WRONG_SCOPE`, `MISSING_SOURCE_METADATA`, `UNRESOLVED_VISIBILITY_BASIS`, `OUT_OF_TIME`, `NOT_VISIBLE`, `DUPLICATE`, and `BUDGET`.

- [ ] **Step 4: Define read-only protocols and prove absence of writes**

```python
class CanonVersionReader(Protocol):
    async def get_exact(self, *, branch_id: str, canon_version_id: str,
                        project_name: str, user_id: str) -> ResolvedCanonView | None:
        pass


class TokenCounter(Protocol):
    @property
    def version(self) -> str:
        pass
    def count(self, content: str) -> int:
        pass
```

Add analogous exact `NarrativePlanReader`, `CreativePolicyReader`, `AcceptedNarrativeReader`, and `RetrievalSnapshotReader`. None exposes list-latest, search-live, insert, update, delete, flush, commit, session, or repository properties.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_context.py tests/unit/r2/test_m5b_architecture_boundaries.py -q
uv run python scripts/audit_tests.py --check
git add r2/contracts r2/narrative_context tests/unit/r2/contracts/test_narrative_context.py tests/unit/r2/test_m5b_architecture_boundaries.py
git commit -m "feat(r2): define narrative context contracts"
```

---

### Task 11: Implement deterministic visibility-safe context compilation

**Files:**
- Create: `r2/narrative_context/compiler.py`
- Modify: `r2/narrative_context/__init__.py`
- Create: `tests/unit/r2/narrative_context/test_compiler.py`
- Modify: `tests/unit/r2/test_m5b_architecture_boundaries.py`
- Create after Codex review: `docs/r2/evidence/R2_M5B_3_REVIEW.md`

**Interfaces:**
- Produces one `NarrativeContextCompiler.compile(request)` entry point returning a complete immutable pack or one stable error; never a partial pack.

- [ ] **Step 1: Write RED exact-version and filter-before-rank tests**

```python
async def test_secret_candidate_is_rejected_before_score_and_budget(compiler) -> None:
    snapshot = retrieval_snapshot([
        candidate("secret", score=1_000_000, descriptor=author_only_secret()),
        candidate("visible", score=1, descriptor=visible_to("char-a")),
    ])
    pack = await compiler.compile(simulation_request(snapshot=snapshot, pov="char-a"))
    assert [item.source_ref for item in pack.retrieved_context] == ["visible"]
    secret_trace = trace_for(pack, "secret")
    assert secret_trace.reason == "NOT_VISIBLE"
    assert not hasattr(secret_trace, "content")
    assert secret_trace.content_hash is None
    assert secret_trace.token_count is None
```

Also cover exact Canon/plan/scene versions, plan basis equality, no head fallback, advancement during compile, mode/channel matrix, secrets in Canon/recent prose/summary/retrieval, missing/stale/wrong-scope/unprovable metadata, content/ref hash mismatch, inactive/wrong-subject knowledge proof, mixed-visibility segmentation, false belief without Fact promotion, and future plan Event absent from Canon.

- [ ] **Step 2: Write RED budget/determinism tests**

Cover mandatory overflow with no pack, deterministic optional ordering `(priority, source_ref, content_hash)`, deduplication, exact token counts, stable omissions, identical pack/input/content hashes, and different dependency/version/counter/compiler inputs changing the input fingerprint.

```bash
uv run python -m pytest tests/unit/r2/narrative_context/test_compiler.py -q
```

Expected: module/API failures.

- [ ] **Step 3: Implement the fixed 12-stage pipeline**

Implement one private method per spec Section 10.4 stage, but expose only `compile`. The stage order is immutable: validate request → exact Canon → exact plan/scene → basis equality → hard validation → POV view → exact auxiliary reads → descriptor/hash proof → scope/time/visibility filters → dedupe → budget → pack/trace.

Descriptor validation occurs before reading or storing its prose in an intermediate eligible segment. Optional invalid items append an ID-only omission; mandatory invalid items raise `NarrativeSourceMetadataError`. `SUBJECTS` requires every named subject/proposition pair to be proven by the descriptor's exact active KnowledgeState refs in KNOWN/SUSPECTED/FALSE_BELIEF; UNKNOWN and absence deny visibility.

- [ ] **Step 4: Implement channel and budget policy exactly**

`AUTHOR_DRAFT` may include `AUTHOR_TRUTH` but preserves POV-forbidden labels. `CHARACTER_SIMULATION` excludes `AUTHOR_TRUTH`, `EXPLICIT_UNKNOWN`, and every segment not visible to its subject. Mandatory tiers are SceneContract/hard forbiddens, required Canon/POV, and creative policy. Optional tiers follow the spec. Never truncate structured content.

- [ ] **Step 5: Prove no prose inspection or write seam**

Architecture tests reject regular expressions, keyword/LLM classifiers, provider imports, live retriever calls, latest reads, authority repositories/UoWs, and mutation methods inside `r2.narrative_context`. Tests pass opaque text whose words contradict its metadata and assert metadata alone decides eligibility.

- [ ] **Step 6: Commit and freeze the M5B-3 implementation head**

```bash
git add r2/narrative_context r2/contracts tests/unit/r2
git commit -m "feat(r2): compile visibility-safe narrative context"
git status --short
M5B_3_VERIFIED_HEAD="$(git rev-parse HEAD)"
```

Expected: status is empty and the head descends from `M5B_2_HANDOFF_HEAD`.

- [ ] **Step 7: Run fresh M5B-3 gates at the frozen head**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_context.py tests/unit/r2/narrative_context/test_compiler.py tests/unit/r2/test_m5b_architecture_boundaries.py -q
uv run ruff check r2/narrative_context r2/contracts/narrative_context.py tests/unit/r2
uv run basedpyright --warnings
uv run lint-imports
uv run python scripts/audit_tests.py --check
git diff --check "$M5B_2_HANDOFF_HEAD"..."$M5B_3_VERIFIED_HEAD"
git status --short
```

Expected: all commands exit 0 while HEAD remains `M5B_3_VERIFIED_HEAD`; status is empty.

- [ ] **Step 8: Obtain Codex leakage/budget review and create an evidence-only handoff**

Codex reviews the exact frozen head for scope/time/epistemic filtering, hash-oracle resistance, no prose inspection, exact-version reads, deterministic deduplication/budgeting, full omission trace, and absence of write ports. Only after an `APPROVED` verdict, Codex writes `R2_M5B_3_REVIEW.md`.

```bash
git add docs/r2/evidence/R2_M5B_3_REVIEW.md
git commit -m "docs(r2): approve M5B-3 verified head"
M5B_3_HANDOFF_HEAD="$(git rev-parse HEAD)"
git diff --name-only "$M5B_3_VERIFIED_HEAD"..."$M5B_3_HANDOFF_HEAD"
git status --short
```

Expected: the post-verified diff is exactly `docs/r2/evidence/R2_M5B_3_REVIEW.md`; status is empty. Task 12 starts from this handoff only.

---

### Task 12: Prove the 30-scene corpus, adversarial mutations, and clean handoff

**Files:**
- Create: `tests/fixtures/r2/__init__.py`
- Create: `tests/fixtures/r2/m5b_narrative_corpus.py`
- Create: `tests/integration/r2/test_m5b_acceptance.py`
- Create: `scripts/r2/verify_m5b_scope.py`
- Create: `tests/unit/scripts/r2/test_verify_m5b_scope.py`
- Create: `docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md`

**Interfaces:**
- Produces fixture evidence through real public M5B contracts/services/compiler, machine-checkable scope/handoff enforcement, and final exact-HEAD verification.
- Consumes only the approved `M5B_3_HANDOFF_HEAD`; Task 12 must not run on an unreviewed compiler commit.

- [ ] **Step 1: Build the versioned public-path corpus**

The fixture constructs and commits, rather than directly fabricating final views/reports:

```text
30 SceneContracts
8 CHARACTER entities
3 LOCATION entities
2 hidden-identity propositions
2 false beliefs
1 injury transition
1 object ownership/state transition
1 presentation-order time jump
relationship and plot-thread constraints
1 unperceived reveal event
1 author-only secret retrieval candidate
```

Use fixed UTC instants, IDs, hashes, token counts, approvals, and snapshots. The baseline must compile both author and character modes deterministically.

- [ ] **Step 2: Write the twelve required adversarial mutations**

Each mutation changes an upstream operation, plan proposal, descriptor, or stored corrupt fixture, then invokes the same public validator/service/compiler path. Parameterize the exact expected rule/error from spec Section 14.6. Explicitly assert filtered prose is absent from both pack and trace.

Use these fixed mutation IDs and outcomes:

| Mutation ID | Input mutation | Expected outcome |
|---|---|---|
| `MUT-01` | Remove historical Event backlink but retain authoritative knowledge evidence | accepted |
| `MUT-02` | Add a non-reciprocal Event backlink | `EPI_EVIDENCE_*` error |
| `MUT-03` | Use a delta-level decision without operation-local binding | contract or `EPI_EVIDENCE_*` error |
| `MUT-04` | Retire supporting Fact midway without closing/superseding knowledge | `EPI_TRUTH_*` error |
| `MUT-05` | Move evidence after transition directly or through a proven path | `EPI_EVIDENCE_*` error |
| `MUT-06` | Duplicate a normalized temporal relation under another ID | `TIME_GRAPH_*` error |
| `MUT-07` | Remove or falsify a secret candidate descriptor | stable omission; no prose or hidden fingerprint in trace |
| `MUT-08` | Claim POV visibility with inactive/wrong-subject knowledge ref | stable omission, or metadata error when mandatory |
| `MUT-09` | Reuse SceneContract ID/version with changed semantic bytes | `NarrativePlanIdentityConflictError` |
| `MUT-10` | Reuse approval ref for another revision tuple | `NarrativePlanApprovalError`; zero writes |
| `MUT-11` | Make entry invalid only on pinned Canon while latest head is valid | plan commit rejected; no latest fallback |
| `MUT-12` | Corrupt Canon with two active states for one subject/proposition | `EpistemicIntegrityError` |

```python
@pytest.mark.parametrize("mutation", REQUIRED_M5B_MUTATIONS, ids=lambda item: item.mutation_id)
async def test_required_mutation_is_detected(mutation, accepted_corpus) -> None:
    result = await mutation.run(accepted_corpus)
    assert result.observed == mutation.expected
```

- [ ] **Step 3: Run focused acceptance and record counters**

```bash
uv run python -m pytest tests/integration/r2/test_m5b_acceptance.py -q
```

Expected counters:

```text
Canon contradiction              0
epistemic leakage                0
timeline violation               0
rejected candidate contamination 0
failed transaction corruption    0
required skips                   0
```

- [ ] **Step 4: Add and test the scope verifier**

The verifier uses M5A integration head `698c34f6b953bd6c7df3306da253e9827b6d94c0` as its base. Before `M5B_VERIFIED_HEAD`, its allowlist includes every implementation/test path in the file map plus the approved design, plan, document-approval manifest, starting-state checkpoint, and all three checkpoint review documents. It separately proves each checkpoint's verified→handoff diff is exactly its single review document and that final implementation descends from `M5B_3_HANDOFF_HEAD`. After `M5B_VERIFIED_HEAD`, it accepts only `docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md`. It rejects any other path, changed/deleted earlier evidence, untracked files, dirty status, wrong ancestry, extra Alembic heads, malformed 12/12 mutation identities, and missing required evidence fields.

```bash
uv run python -m pytest tests/unit/scripts/r2/test_verify_m5b_scope.py -q
uv run python scripts/audit_tests.py --check
```

- [ ] **Step 5: Run affected PostgreSQL and full backend gates**

Run each separately and retain complete logs/exit codes:

```bash
uv run python -m pytest tests/integration/r2/narrative/test_canon_concurrency.py tests/integration/r2/narrative_plan/test_concurrency.py -q -m postgres
uv run python -m pytest tests/integration/lib/db/repositories/test_canon_repo.py tests/integration/lib/db/repositories/test_narrative_plan.py -q -m postgres
uv run ruff check .
uv run ruff format --check .
uv run basedpyright --warnings
uv run lint-imports
uv run deptry lib server alembic scripts tests r2
uv run python -m pytest -n 4 --dist loadfile
uv run python scripts/audit_tests.py --check
git diff --check
```

Every final command is read-only. Record the disposable PostgreSQL server/database identity and prove zero required skips; do not run against production.

- [ ] **Step 6: Freeze the implementation verified head**

Commit all implementation and test/evidence-generator files except the final verification document:

```bash
git add tests/fixtures/r2 tests/integration/r2/test_m5b_acceptance.py scripts/r2/verify_m5b_scope.py tests/unit/scripts/r2/test_verify_m5b_scope.py
git commit -m "test(r2): prove M5B narrative acceptance"
git status --short
M5B_VERIFIED_HEAD="$(git rev-parse HEAD)"
```

Expected: empty status. Rerun Step 5 and the acceptance test at exactly this head. Any subsequent code/test/config/migration change invalidates the head and requires a new verified head.

- [ ] **Step 7: Write the final evidence-only handoff**

Record accepted M5A base/handoff, M5B verified head, migration head, schema/hash selectors, graph project/generation/coverage/fallbacks, complete command lines/counts/exit codes, PostgreSQL identity, 12 mutation results, compiler omission reasons without prose, hard-exit counters, file allowlist result, and clean status.

```bash
git add docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md
git commit -m "docs(r2): record M5B final verification"
M5B_HANDOFF_HEAD="$(git rev-parse HEAD)"
uv run python scripts/r2/verify_m5b_scope.py --base 698c34f6b953bd6c7df3306da253e9827b6d94c0 --verified-head "$M5B_VERIFIED_HEAD" --handoff-head "$M5B_HANDOFF_HEAD"
git diff --name-only "$M5B_VERIFIED_HEAD"..."$M5B_HANDOFF_HEAD"
git status --short
```

Expected: verifier exits 0; the only post-verified path is `docs/r2/evidence/R2_M5B_FINAL_VERIFICATION.md`; status is empty.

- [ ] **Step 8: Stop for final Codex review**

Codex independently reviews exact lineage, v1 compatibility, all three authority boundaries, database concurrency/rollback evidence, descriptor fail-closed behavior, deterministic budget/trace, required mutations, full regression, graph coverage, and verified-head→evidence-only handoff. Claude Code does not push, publish, run an operating migration, activate a worker, or begin M5C.
