# R2-M5C Narrative Lifecycle, Acceptance Authority, and Canon Delta Compilation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Use superpowers:test-driven-development for every behavior change and superpowers:verification-before-completion before each review gate. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the smallest complete Narrative workflow above accepted M5A/M5B — immutable draft/revision/extraction/change-set/compilation evidence, a narrow three-family Human acceptance authority, a pure deterministic `CanonDeltaCompiler`, a durable M5A handoff-admission receipt, and a narrow versioned SceneContract/NarrativePlan v2 compatibility extension (F9/R9/R10 + scene-side omniscient gate) — without granting prose, extraction, compilation, orchestration, providers, or projections any Narrative or Canon authority.

**Architecture:** M5C-1A evolves SceneContract/NarrativePlan from v1 to v2 through selector-dispatched serializers that keep every accepted v1 byte and hash immutable, adds relationship/thread constraints as read-only selectors over existing Canon Facts and authorial plan state, and lands two `R2-DEC-031`-gated donor ports behind pure proposal-only interfaces. M5C-1B adds an append-only `NarrativeLifecycleEvidenceService` for immutable evidence. M5C-2 adds `NarrativeAcceptanceService` — three typed decision families over one internal authority kernel, with rebuildable logical heads and an opaque conflict-resolution lineage. M5C-3 adds the pure `CanonDeltaCompiler` wrapped by durable compilation attempt/result evidence. M5C-4 adds the atomic `NarrativeHandoffAdmission` receipt and an authenticated facade that calls the **existing** M5A `CanonTransactionService.commit()`; M5C adds no Canon repository, approval service, transaction, or table write.

**Tech Stack:** Python 3.12+, Pydantic v2, SQLAlchemy async ORM, Alembic, PostgreSQL 18, SQLite focused migration tests, pytest/pytest-asyncio, ruff, basedpyright, import-linter, deptry. Node 20+ (test-only donor-parity harnesses; never shipped, imported, or started by the runtime).

**Spec:** `docs/superpowers/specs/2026-09-09-r2-m5c-narrative-lifecycle-design.md`
**Authoritative decision:** `docs/adr/0076-narrative-lifecycle-evidence-and-acceptance-authority.md` (+ 2026-09-09 amendment)
**Research:** `docs/research/2026-09-09-r2-m5c-persistence-state-machine-validation.md`

## Global Constraints

- Execute only on a prepared M5C implementation worktree rooted at the accepted R2 integration base recorded in the document-approval manifest (`origin/r2/main`, the merge that integrated accepted M5B; short SHA `71a96bd6`). Do not implement in the design branch. Do not overwrite an existing worktree or branch. Task 0 pins the exact base and proves the M5B integration lineage.
- The existing M5A `CanonTransactionService` remains the **sole** Canon writer and `CanonCommitApproval` the sole Canon approval receipt. M5C adds **no** Canon repository, Canon approval service, Canon transaction, Canon ORM write, or second proposition/relationship/thread Canon authority. M5C ends at a `CanonDelta` proposal plus a `NarrativeHandoffAdmission` receipt.
- `NarrativeAcceptanceService` is the **only** module that may append a Narrative decision or mutate a Narrative head. `NarrativeLifecycleEvidenceService` is append-only evidence and cannot import or call any head-mutation method. The pure `CanonDeltaCompiler` imports no repository, UoW, clock, random source, provider, acceptance service, or Canon transaction service.
- Accepted v1 SceneContract / NarrativePlan bytes and hashes, and all accepted M5B commit history, are immutable compatibility evidence. v1 serializers keep their exact accepted field set and byte domain and must never begin serializing empty/default v2 fields. A logical scene or plan lineage that reaches v2 never downgrades to v1.
- Relationship Fact predicates are produced **only** by the shared versioned helper `relationship_fact_predicate(...)` (`r2-relationship-fact-key-v1`). No extractor, compiler, provider, orchestrator, or caller concatenates or invents a relationship predicate.
- F9 relationship/thread validators are clean-room R2 code. They import no donor source and are absent from every donor-parity runtime path; F9 does not activate the four `R2-DEC-031` donor-port gates.
- Every donor-derived M5C surface passes the project-wide `R2-DEC-031` gate: baseline manifest (exact revision + path + source SHA-256), branch-complete coverage, same-fixture parity against the unmodified pinned TypeScript source run through a test-only Node harness, and exact-HEAD evidence. M5C v1 selects exactly two Python ports (Huohuo `novel-change-record.ts`, Novel Studio `hardRules.ts`); any later donor-derived behavior expands the baseline and must pass all four gates before acceptance.
- M5C v1 decision authority is authenticated Human Showrunner only, resolved from an explicit project-scoped `HUMAN_SHOWRUNNER` grant via one injected `NarrativeShowrunnerAuthorityPort`. Generic administrator roles, `user_id`, API-key possession, authorship, Agents, providers, extractors, compilers, and orchestration confer none. Production adapters deny by default; a test fake supplies acceptance evidence but must never be wired into production. Production activation is a STOP condition until the Governance/Showrunner authority source exists.
- Every repository read and write carries `(user_id, project_name)` in its predicate. An unknown opaque ID and a cross-scope ID both return the same public not-found result. A caller-supplied database-global decision/admission ID that collides in any scope returns one generic identity-conflict shape that exposes no owning scope, family, subject, actor, or content.
- All timestamps are timezone-aware UTC; all intervals are half-open. No wall clock supplies story time, semantic transition time, compiler output identity, or an opaque ID during a pure transformation.
- Currentness is frozen at the atomic handoff-admission instant. A Narrative supersession that commits after the admission transaction does not retroactively invalidate the receipt or an already-admitted M5A action. There is no currentness-through-Canon-commit fence, lease, or cross-authority transaction.
- Tests use public interfaces and explicit fakes; do not patch private production symbols, add sleeps, use automatic retries, or add a latest-version / `allow_historical` fallback flag. Each task follows RED → GREEN → focused regression → `scripts/audit_tests.py --check` → commit. A command that collects zero tests is a failure and must be broadened.
- Before every `git add`, inspect `git status --short`; stage only paths owned by the current task. Directory-level staging commands below are valid only when the status contains no unrelated change.
- Checkpoints `M5C-1A`, `M5C-1B` (= final `M5C-1`), `M5C-2`, `M5C-3`, `M5C-4` each freeze a clean verified implementation HEAD, run their gates there, receive independent Codex review, and add **only** evidence/handoff material before the next checkpoint. Claude Code does not cross a gate until Codex records approval.
- No passing test or review authorizes an operating migration, production discovery/repair, worker start, provider/network call, push, publish, or deployment. `R2-DEC-031` material behavior/parity gaps have no waiver in this design.
- Prior design discovery used the `home-anhtuan-content-production-os-m5b` graph generation and is not execution evidence. Task 0 indexes the exact implementation worktree, records the new generation and indexed HEAD, calls `check_index_coverage` for every relied-on path, and directly reads every missed or stale range.

## Base Modules (accepted M5A/M5B — read-only dependencies)

| Module | What M5C consumes without changing its authority |
|---|---|
| `r2/contracts/narrative.py` | `CanonDelta`, `CanonDeltaPayload`, `CanonCommitApproval`, `CanonOperation` union, `operation_kinds_for`, `EpistemicState`, `Fact`, `Entity` |
| `r2/contracts/narrative_plan.py` | `SceneContract`, `SceneFactConstraint`, `SceneKnowledgeConstraint`, `SceneStateConstraint`, `NarrativePlanContent`, `NarrativePlan`, `CanonBasis`, `PLAN_SCHEMA_VERSION`, `SCENE_CONTRACT_CONTENT_HASH_VERSION` |
| `r2/contracts/narrative_context.py` | `ContextMode.AUTHOR_DRAFT` / `CHARACTER_SIMULATION`, `NarrativeContextRequest`, `NarrativeSourceDescriptor` |
| `r2/narrative/canon_transaction.py` | `CanonTransactionService.commit(*, delta, approval, project_name, user_id, now)` — unchanged |
| `r2/narrative/canon_state.py` | `ResolvedCanonView`, `apply_canon_delta` |
| `r2/narrative/hashing.py` | `compute_canon_delta_hash`, `verify_canon_delta_hash`, `seal_canon_delta` — the sole M5A payload-hash implementation |
| `r2/narrative/validation.py` | `NarrativeInvariantValidator.validate_scene(*, canon, plan, scene)` / `.validate_canon(...)` — extended by F9, entry point preserved |
| `r2/narrative/schema_upgrade.py` | `require_schema_transition` pattern for the SceneContract/plan ratchet |
| `r2/narrative_plan/service.py` | `NarrativePlanService.commit_revision` transaction/idempotency pattern (not acceptance storage) |
| `r2/narrative_plan/hashing.py` | `compute_scene_semantic_hash`, `compute_plan_content_hash` — extended by selector dispatch |
| `r2/narrative_plan/validation.py` | `validate_plan_hierarchy`, `validate_scene_version`; new `validate_plan_thread_lifecycle` lands beside them |
| `r2/narrative_context/ports.py` | `AcceptedNarrativeReader`, `AcceptedNarrativeRecord` protocols — M5C supplies the concrete adapter |
| `r2/narrative_context/compiler.py` | `NarrativeContextCompiler` — gains the scene-side omniscient `AUTHOR_DRAFT` gate |
| `lib/db/models/narrative_plan.py` | `UserOwnedMixin`, `Base`, append-only-head + immutable-version table shape |
| `lib/db/repositories/narrative_plan.py` | scoped adapter shape: `lock_plan` (`FOR UPDATE`), `insert_*`, `advance_head` with `rowcount(...) == 1`, `IntegrityError` → typed error mapping |
| `lib/db/narrative_plan_uow.py` | fresh `AsyncSession` per authority call, `BEGIN IMMEDIATE` (SQLite) / `session.begin()` + row lock (PostgreSQL) |
| `alembic/versions/5b7c4a0e0001_add_narrative_plans.py` | migration head M5C chains from (`down_revision = "5b7c4a0e0001"`) |

## File and Responsibility Map

| File | Responsibility | Checkpoint |
|---|---|---|
| `docs/superpowers/specs/2026-09-09-r2-m5c-narrative-lifecycle-design.md` | Human-approved M5C design bytes | — |
| `docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md` | Human-approved execution plan bytes | — |
| `docs/r2/evidence/R2_M5C_DOCUMENT_APPROVAL.json` | External manifest binding approved document hashes + accepted base without self-reference | Task 0 |
| `docs/r2/evidence/R2_M5C_STARTING_STATE.json` | Accepted M5B lineage, document hashes, graph coverage, migration reservation, baseline gates | Task 0 |
| `r2/contracts/narrative_plan.py` | v2 SceneContract/NarrativePlan selectors, `SceneRelationshipConstraint`, `SceneThreadConstraint`, `omniscient_authoring_allowed_by_scene`, v1/v2 SceneContract union | 1A |
| `r2/narrative_plan/hashing.py` | selector-dispatched byte-stable v1/v2 scene + plan hashes | 1A |
| `r2/narrative_plan/schema_upgrade.py` | legal SceneContract/plan schema-transition ratchets (genesis/v1/v2, no v2→v1, plan aggregate ratchet) | 1A |
| `r2/narrative_plan/validation.py` | `validate_plan_thread_lifecycle` (pure plan-wide presentation-order pass) beside `validate_plan_hierarchy` | 1A |
| `r2/narrative/relationship_facts.py` | sole versioned `relationship_fact_predicate` mapping (`r2-relationship-fact-key-v1`) | 1A |
| `r2/narrative/validation.py` | exact-instant relationship comparison + R9 exact-ref + R10 duplicate-constraint rules in `validate_scene` | 1A |
| `r2/narrative/errors.py` | `NarrativePlanSchemaVersionError`, `NarrativeRelationshipIntegrityError`, `NarrativeThreadLifecycleError` | 1A |
| `r2/narrative_context/compiler.py` | scene-side omniscient `AUTHOR_DRAFT` gate + `AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE` | 1A |
| `r2/narrative_context/errors.py` | stable `AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE` finding | 1A |
| `r2/narrative_lifecycle/changeset_parser.py` | Huohuo-derived pure change-record parser/normalizer; proposal output only | 1A |
| `r2/narrative_lifecycle/continuity_rules.py` | Novel Studio-derived pure deterministic continuity findings + stable report merge | 1A |
| `tests/donor_parity/huohuo_change_record_runner.mjs` | test-only exact-source Node runner (verifies revision + SHA-256) | 1A |
| `tests/donor_parity/test_huohuo_change_record.py` | same-fixture TS/Python comparison | 1A |
| `tests/donor_parity/fixtures/huohuo_change_record/` | canonical shared JSON/JSONL corpus (~25–35 branch/error cases + ≥10 prose fixtures) | 1A |
| `tests/donor_parity/novel_hard_rules_runner.mjs` | test-only exact-source Node runner | 1A |
| `tests/donor_parity/test_novel_hard_rules.py` | same-fixture TS/Python comparison | 1A |
| `tests/donor_parity/fixtures/novel_hard_rules/` | canonical shared JSON/JSONL corpus (~8–10 cases) | 1A |
| `r2/contracts/narrative_lifecycle.py` | immutable evidence, decision, head, lineage, receipt contracts; `NarrativeSemanticEffectKey` algebra | 1B/2/3/4 |
| `r2/narrative_lifecycle/hashing.py` | versioned prose / evidence / decision / approval-binding hash domains | 1B |
| `r2/narrative_lifecycle/errors.py` | stable public failure taxonomy (§13) | 1B |
| `r2/narrative_lifecycle/coverage.py` | pure source-span + semantic-effect-key normalization and overlap rules | 1B |
| `r2/narrative_lifecycle/ports.py` | exact evidence / authority / UoW / M5A-facade protocols | 1B/2/4 |
| `r2/narrative_lifecycle/evidence.py` | `NarrativeLifecycleEvidenceService` — deep immutable evidence append; no head write | 1B/3 |
| `r2/narrative_lifecycle/acceptance.py` | `NarrativeAcceptanceService` — three decision commands + handoff admission; sole head writer | 2/4 |
| `r2/narrative_lifecycle/compiler.py` | pure `CanonDeltaCompiler` | 3 |
| `r2/narrative_lifecycle/integrity.py` | `NarrativeLifecycleIntegrityChecker` — decision/head/result/receipt verification and rebuild | 2/4 |
| `r2/narrative_lifecycle/__init__.py` | public contract / pure-function / service exports; no ORM, repo, session, head-mutation, or repair export | 1B–4 |
| `lib/db/models/narrative_lifecycle.py` | typed immutable rows + logical heads + shared decision-identity registry | 1B/2/3/4 |
| `lib/db/repositories/narrative_lifecycle.py` | scoped transaction-bound adapter (canonical lock order, genesis `INSERT ... ON CONFLICT DO NOTHING` + `FOR UPDATE`) | 1B/2/3/4 |
| `lib/db/narrative_lifecycle_uow.py` | Narrative transaction lifecycle | 1B/2 |
| `alembic/versions/5c7c4a0e0001_add_narrative_lifecycle_evidence.py` | additive evidence tables from head `5b7c4a0e0001` | 1B |
| `alembic/versions/5c7c4a0e0002_add_narrative_decision_authority.py` | additive decision / identity-registry / head / lineage tables; chains from `5c7c4a0e0001` | 2 |
| `alembic/versions/5c7c4a0e0003_add_narrative_compilation.py` | additive compilation-attempt / compilation-result / compiled-delta tables; chains from `5c7c4a0e0002` | 3 |
| `alembic/versions/5c7c4a0e0004_add_narrative_handoff_admission.py` | additive handoff-admission table; chains from `5c7c4a0e0003`. **A migration inside a frozen checkpoint HEAD is never edited by a later checkpoint** | 4 |
| `server/services/narrative_canon_handoff.py` | authenticated admission → existing M5A `CanonTransactionService.commit()` facade | 4 |
| `pyproject.toml` | import-fitness contracts for pure F9 modules, evidence/acceptance/compiler boundaries, donor-import bans | 1A–4 |
| `scripts/r2/verify_m5c_scope.py` | implementation/evidence-only allowlists + verified-head handoff check | 1A |
| `tests/fixtures/r2/m5c_narrative_corpus.py` | combined M5 v1/v2 successor fixture | 4 |
| `tests/unit/r2/contracts/test_narrative_plan_v2.py` | v2 contract, discriminator, v1 byte/hash compatibility tests | 1A |
| `tests/unit/r2/narrative_plan/test_schema_upgrade_scene.py` | scene/plan ratchet + selector-below-minimum + v2→v1 rejection tests | 1A |
| `tests/unit/r2/narrative_plan/test_hashing_v2.py` | selector-dispatched hash + v1 golden vectors | 1A |
| `tests/unit/r2/narrative_plan/test_thread_lifecycle.py` | plan-wide presentation-order thread lifecycle matrix | 1A |
| `tests/unit/r2/narrative/test_relationship_facts.py` | direction/target/key-sensitive mapping + shared-helper vector | 1A |
| `tests/unit/r2/narrative/test_validation_f9.py` | relationship comparison matrix + R9 + R10 | 1A |
| `tests/unit/r2/narrative_context/test_omniscient_gate.py` | scene-side `AUTHOR_DRAFT` gate matrix | 1A |
| `tests/donor_parity/` (as above) | donor parity harness + comparison suites | 1A |
| `tests/unit/r2/contracts/test_narrative_lifecycle.py` | strict evidence/decision/receipt contracts + effect-key algebra | 1B–4 |
| `tests/unit/r2/narrative_lifecycle/test_hashing.py` | prose/evidence/decision/approval-binding hash domains | 1B |
| `tests/unit/r2/narrative_lifecycle/test_coverage.py` | span/effect normalization + overlap rules | 1B |
| `tests/unit/lib/db/models/test_narrative_lifecycle.py` | ORM shape + DB constraint metadata | 1B/2/3 |
| `tests/integration/lib/db/migrations/test_alembic_narrative_lifecycle_evidence.py` | SQLite upgrade/downgrade proof | 1B |
| `tests/integration/lib/db/migrations/test_alembic_narrative_decision_authority.py` | SQLite upgrade/downgrade proof | 2 |
| `tests/integration/lib/db/migrations/test_alembic_narrative_compilation.py` | SQLite upgrade/downgrade proof | 3 |
| `tests/integration/lib/db/migrations/test_alembic_narrative_handoff_admission.py` | SQLite upgrade/downgrade proof | 4 |
| `tests/integration/lib/db/repositories/test_narrative_lifecycle.py` | scoped repo/UoW/uniqueness/rollback/genesis behavior | 1B/2 |
| `tests/integration/r2/narrative_lifecycle/test_evidence_service.py` | attempt-before-work, atomic bundle, exact retry, fenced late result | 1B |
| `tests/integration/r2/narrative_lifecycle/test_acceptance_decisions.py` | three families, authority denial matrix, retry ordering, REJECT semantics | 2 |
| `tests/integration/r2/narrative_lifecycle/test_conflict_lineage.py` | genesis lineage, subject uniqueness, concurrent genesis, canonical lock order | 2 |
| `tests/integration/r2/narrative_lifecycle/test_concurrency.py` | PostgreSQL concurrent genesis, fault windows, rebuild equality | 2 |
| `tests/unit/r2/narrative_lifecycle/test_compiler.py` | permutation determinism, `NO_CANON_MUTATION`, conflict/abstain, M5A hash reuse | 3 |
| `tests/integration/r2/narrative_lifecycle/test_compilation_service.py` | admission currentness, atomic compiled-delta bundle, restart reload | 3 |
| `tests/integration/r2/narrative_lifecycle/test_thread_payoff_outcome.py` | `AcceptedThreadPayoffProof` + `validate_thread_payoff_outcome` | 3 |
| `tests/integration/r2/narrative_lifecycle/test_handoff_admission.py` | supersession races, approval-binding fingerprint, admission-vs-commit semantics | 4 |
| `tests/integration/r2/narrative_lifecycle/test_integrity.py` | full integrity checker + head rebuild | 4 |
| `tests/unit/r2/test_m5c_architecture_boundaries.py` | AST/import authority, no-donor-import F9, pure-compiler, sole-head-writer fitness | 1A–4 |
| `tests/integration/r2/test_m5c_acceptance.py` | combined M5 v1/v2 corpus through real public interfaces + adversarial mutations | 4 |
| `tests/unit/scripts/r2/test_verify_m5c_scope.py` | scope verifier allow/reject behavior | 1A |
| `docs/r2/evidence/R2_M5C_1A_REVIEW.md` | compatibility/hash/validator/donor blast-radius checkpoint evidence + Codex verdict | 1A |
| `docs/r2/evidence/R2_M5C_1_REVIEW.md` | evidence-lifecycle checkpoint (final M5C-1) evidence + Codex verdict | 1B |
| `docs/r2/evidence/R2_M5C_2_REVIEW.md` | acceptance-authority checkpoint evidence + Codex verdict | 2 |
| `docs/r2/evidence/R2_M5C_3_REVIEW.md` | compilation checkpoint evidence + Codex verdict | 3 |
| `docs/r2/evidence/R2_M5C_FINAL_VERIFICATION.md` | clean verified head, full commands, PostgreSQL identity, acceptance counters, `R2-DEC-031` bundle, handoff proof | 4 |

---

### Task 0: Pin the accepted M5B handoff and the M5C implementation boundary

**Files:**
- Create: `docs/r2/evidence/R2_M5C_STARTING_STATE.json`
- Verify only (do **not** create): `docs/r2/evidence/R2_M5C_DOCUMENT_APPROVAL.json` — a **precondition**. The Human Showrunner (or, on their explicit direction, whoever records their approval) materializes this manifest during design/plan approval, **before** any execution worktree is prepared. An implementation agent never authors Human approval evidence; Task 0 only checks its exact bytes and hashes.

**Interfaces:**
- Consumes: the pre-existing Human-approved `R2_M5C_DOCUMENT_APPROVAL.json`, the accepted M5B integration head on `origin/r2/main`, the approved M5C spec + this plan, the current Alembic graph, the current source graph, and baseline gates.
- Produces: one machine-readable checkpoint on a clean `feat/r2-m5c-narrative-lifecycle` implementation worktree; no implementation file precedes this checkpoint.

- [ ] **Step 1: Prove the integration-base authority is unambiguous — fail closed on any disagreement**

```bash
git rev-parse origin/r2/main
git show -s --format='%P %s' origin/r2/main
git merge-base --is-ancestor a2dc1c141c77ce1365eea8360a3593b55567c5af origin/r2/main
rg -n 'integration|accepted base|71a96bd6|r2/main' docs/r2/evidence/PROJECT_DECISIONS_2026-09-09.md docs/r2/evidence/PROJECT_STATUS_REVIEW_2026-09-09.md
```

The accepted base must satisfy this invariant exactly:

```text
R2_M5C_DOCUMENT_APPROVAL.json:m5c_integration_base
  == the resolved origin/r2/main SHA (the merge that integrated accepted M5B; a2dc1c14 is an ancestor)
  == the accepted M5B integration SHA recorded in the 2026-09-09 project decision/status docs
  == the base the implementation worktree is rooted at
```

Expected: all four agree on one 40-hex SHA; record it as `M5C_INTEGRATION_BASE`. **Any mismatch — the manifest, `origin/r2/main`, the project-decision record, or the worktree base disagreeing — is a STOP condition.** Do not pick one value and continue; halt and raise the discrepancy for the operator to reconcile before execution.

- [ ] **Step 2: Verify the pre-existing external document-approval manifest**

`docs/r2/evidence/R2_M5C_DOCUMENT_APPROVAL.json` (materialized before execution — see **Files**) records:

```json
{
  "schema_version": "r2-m5c-document-approval-v1",
  "status": "APPROVED",
  "m5c_integration_base": "<M5C_INTEGRATION_BASE 40-hex>",
  "approved_docs_source_head": "<plan-revision commit immediately before the manifest commit, 40-hex>",
  "design_path": "docs/superpowers/specs/2026-09-09-r2-m5c-narrative-lifecycle-design.md",
  "design_sha256": "3145c0c37948f7ada94dafe6f91f54fb9d89ce7c69812b4464b6f36967e8daa2",
  "plan_path": "docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md",
  "plan_sha256": "<sha256 of this plan file as approved>",
  "adr_path": "docs/adr/0076-narrative-lifecycle-evidence-and-acceptance-authority.md",
  "adr_sha256": "f94d692c3f5a83fa0b0b749a0212f619f89270d4d8f24985d597586d45bc1f22",
  "research_path": "docs/research/2026-09-09-r2-m5c-persistence-state-machine-validation.md",
  "research_sha256": "1cb8a68f6116740db4d84a75c86cf2a51b15578d00c5878f80b2fc3d55ed27e8",
  "approved_by": "human:anhtuan",
  "approved_at": "<timezone-aware ISO-8601>"
}
```

```bash
uv run python -c 'import hashlib,json,re; from datetime import datetime; from pathlib import Path; m=json.loads(Path("docs/r2/evidence/R2_M5C_DOCUMENT_APPROVAL.json").read_text()); assert m["schema_version"]=="r2-m5c-document-approval-v1"; assert m["status"]=="APPROVED"; assert re.fullmatch(r"[0-9a-f]{40}",m["m5c_integration_base"]); assert re.fullmatch(r"[0-9a-f]{40}",m["approved_docs_source_head"]); assert m["approved_by"].strip(); assert datetime.fromisoformat(m["approved_at"]).utcoffset() is not None; pairs=[(m["design_path"],m["design_sha256"]),(m["plan_path"],m["plan_sha256"]),(m["adr_path"],m["adr_sha256"]),(m["research_path"],m["research_sha256"])]; bad=[p for p,w in pairs if not re.fullmatch(r"[0-9a-f]{64}",w) or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=w]; assert not bad,bad'
git branch --show-current
git merge-base --is-ancestor "$(uv run python -c 'import json;print(json.load(open("docs/r2/evidence/R2_M5C_DOCUMENT_APPROVAL.json"))["m5c_integration_base"])')" HEAD
git diff --name-only "$(uv run python -c 'import json;print(json.load(open("docs/r2/evidence/R2_M5C_DOCUMENT_APPROVAL.json"))["m5c_integration_base"])')...HEAD"
git status --short
```

Expected: branch is `feat/r2-m5c-narrative-lifecycle`; status is empty; the manifest `m5c_integration_base` equals `M5C_INTEGRATION_BASE` from Step 1 (else STOP); the net diff over the accepted base contains **only** the design spec, this plan, the ADR (with its accepted amendment), the research note, and `R2_M5C_DOCUMENT_APPROVAL.json`. Inspect every commit in the range; reject any other changed path. Define the observed clean HEAD as `M5C_DOCUMENT_MATERIALIZATION_HEAD`.

- [ ] **Step 3: Reserve the migration chain and confirm v1 selectors are frozen**

```bash
uv run alembic heads
rg -n '5b7c4a0e0001|5c7c4a0e000[1234]' alembic/versions
rg -n 'r2-scene-contract-content-v1|r2-narrative-plan-v1|r2-narrative-plan-content-v1' r2/contracts r2/narrative_plan tests/unit/r2 tests/integration/r2
rg -n 'r2-canon-delta-v1' r2/narrative/hashing.py
```

Expected: exactly `5b7c4a0e0001 (head)`; no existing `5c7c4a0e0001..0004`; v1 scene/plan selectors present and slated to become explicit compatibility fixtures rather than being replaced; `r2-canon-delta-v1` is the sole M5A payload-hash version M5C reuses. Record `"m5c_alembic_base": "5b7c4a0e0001"` in `R2_M5C_STARTING_STATE.json` — the downgrade target for every migration round-trip in this plan.

- [ ] **Step 4: Provision and pin the isolated PostgreSQL 18 test instance**

Concurrency tests (Tasks 21/28) and the final gate (Task 32) require a real PostgreSQL 18 database that is **not** the developer DB and **not** the implicit Alembic default. Stand one up (container or dedicated instance), then pin its identity:

```bash
export POSTGRES_TEST_URL="postgresql+asyncpg://<user>:<pw>@<host>:<port>/<isolated_db>"
uv run python -c 'import asyncio,asyncpg,os; from urllib.parse import urlparse; u=urlparse(os.environ["POSTGRES_TEST_URL"].replace("+asyncpg","")); print(asyncio.run(asyncpg.connect(host=u.hostname,port=u.port,user=u.username,password=u.password,database=u.path[1:]).fetchval("SELECT version()")) if False else "resolve manually")'
psql "$(printf %s "$POSTGRES_TEST_URL" | sed 's#+asyncpg##')" -c "SELECT version();"
psql "$(printf %s "$POSTGRES_TEST_URL" | sed 's#+asyncpg##')" -c "SELECT current_database(), current_user;"
DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head
DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic downgrade "$M5C_ALEMBIC_BASE"
```

Expected: `SELECT version()` reports PostgreSQL 18.x; `current_database` is the isolated DB, not a dev/prod name; the round-trip against **that URL** exits 0. Record `POSTGRES_TEST_URL` host/db/user (not the password), the reported `version()`, a clean-ownership marker (the DB is empty apart from Alembic's own bookkeeping before `upgrade`), and `M5C_ALEMBIC_BASE` in `R2_M5C_STARTING_STATE.json`. Every later `alembic upgrade head` / round-trip in this plan runs with `DATABASE_URL="$POSTGRES_TEST_URL"` (SQLite migration *tests* under `tests/integration/lib/db/migrations/` keep their own `alembic_cfg` per `CONTRIBUTING.md`).

- [ ] **Step 5: Refresh the graph and baseline gates**

Index the exact implementation worktree. Run task-directed graph queries for `NarrativeInvariantValidator.validate_scene`, `validate_plan_hierarchy`, `compute_scene_semantic_hash`, `compute_plan_content_hash`, `NarrativePlanService.commit_revision`, `NarrativeContextCompiler`, `CanonTransactionService.commit`, `AcceptedNarrativeReader`, and their callers. Call `check_index_coverage` for every file in the responsibility map that already exists. Directly read every missed/stale range. Record the graph generation timestamp and indexed HEAD in `R2_M5C_STARTING_STATE.json`.

```bash
uv run ruff check . && uv run ruff format --check .
uv run basedpyright --warnings
uv run lint-imports
uv run deptry lib server alembic scripts tests r2
uv run python -m pytest -n 4 --dist loadfile -q tests/unit/r2 tests/integration/r2/narrative tests/integration/r2/narrative_plan
uv run python scripts/audit_tests.py --check
```

Expected: all exit 0. Record the exact pass/skip counts and the four static-gate results in `R2_M5C_STARTING_STATE.json` as prerequisite baseline — not M5C validation.

- [ ] **Step 6: Commit the Task 0 checkpoint**

```bash
git add docs/r2/evidence/R2_M5C_STARTING_STATE.json
git commit -m "docs(r2): pin M5C implementation starting state"
git status --short
```

Expected: empty status. `git diff --name-only "$M5C_DOCUMENT_MATERIALIZATION_HEAD"..HEAD` returns exactly `docs/r2/evidence/R2_M5C_STARTING_STATE.json`.

---

## Checkpoint M5C-1A — versioned M5 compatibility, F9/R9/R10, scene omniscient gate, donor parity

*Frozen, independently reviewed blast radius before any lifecycle persistence exists. Donor ports land here behind pure proposal-only interfaces; M5C-1B consumes their output only through immutable evidence contracts.*

### Task 1: Add v2 SceneContract / NarrativePlan selectors and the relationship / thread / omniscient semantics

**Files:**
- Modify: `r2/contracts/narrative_plan.py`
- Modify: `r2/contracts/__init__.py`
- Modify: `r2/narrative/errors.py`
- Test: `tests/unit/r2/contracts/test_narrative_plan_v2.py`
- Test: `tests/unit/r2/contracts/test_narrative_plan.py`

**Interfaces:**
- Consumes: `SceneContract`, `SceneFactConstraint`, `SceneKnowledgeConstraint`, `SceneStateConstraint`, `NarrativePlanContent`, `EpistemicState` from the accepted contracts.
- Produces:
  - selectors `SCENE_CONTRACT_CONTENT_HASH_VERSION_V2 = "r2-scene-contract-content-v2"`, `PLAN_SCHEMA_VERSION_V2 = "r2-narrative-plan-v2"`, `PLAN_CONTENT_HASH_VERSION_V2 = "r2-narrative-plan-content-v2"`;
  - `class SceneRelationshipConstraint` (`constraint_kind: Literal["RELATIONSHIP"]`, `source_character_ref`, `target_character_ref`, `relationship_key`, `comparison: Literal["PRESENT","ABSENT","EQUALS","NOT_EQUALS"]`, `expected_state: NonEmptyStr | None`), validating `expected_state` required for `EQUALS`/`NOT_EQUALS` and forbidden for `PRESENT`/`ABSENT`, and `source_character_ref != target_character_ref`;
  - `class SceneThreadConstraint` (`constraint_kind: Literal["THREAD"]`, `thread_ref`, `required_state: Literal["OPEN","RESOLVED"]`, `payoff_ref: NonEmptyStr | None`), validating `payoff_ref` forbidden for `OPEN` and required for `RESOLVED`;
  - `SceneStateConstraintV2 = Annotated[SceneFactConstraint | SceneKnowledgeConstraint | SceneRelationshipConstraint | SceneThreadConstraint, Field(discriminator="constraint_kind")]`;
  - `class SceneContractV2` adding `semantic_hash_version: Literal["r2-scene-contract-content-v2"]`, `omniscient_authoring_allowed_by_scene: bool = False`, and v2 constraint lists in `entry_state_constraints` / `exit_state_targets`;
  - `SceneContractValue = SceneContract | SceneContractV2` discriminated by `semantic_hash_version`; `NarrativePlanContentV2` whose `scene_contracts: list[SceneContractValue]` may mix v1 and v2 members and whose `schema_version: Literal["r2-narrative-plan-v2"]`.
- Adds `NarrativePlanSchemaVersionError` to `r2/narrative/errors.py`.

- [ ] **Step 1: Write RED contract tests**

```python
def test_relationship_constraint_requires_expected_state_only_for_equality() -> None:
    with pytest.raises(ValidationError):
        SceneRelationshipConstraint(constraint_id="c1", source_character_ref="a", target_character_ref="b",
                                    relationship_key="trust_level", comparison="PRESENT", expected_state="TRUSTED")
    ok = SceneRelationshipConstraint(constraint_id="c1", source_character_ref="a", target_character_ref="b",
                                     relationship_key="trust_level", comparison="EQUALS", expected_state="TRUSTED")
    assert ok.comparison == "EQUALS"


def test_thread_constraint_payoff_ref_presence_is_state_dependent() -> None:
    with pytest.raises(ValidationError):
        SceneThreadConstraint(constraint_id="c2", thread_ref="t1", required_state="OPEN", payoff_ref="p1")
    with pytest.raises(ValidationError):
        SceneThreadConstraint(constraint_id="c3", thread_ref="t1", required_state="RESOLVED")


def test_v2_plan_content_may_hold_both_v1_and_v2_scene_members() -> None:
    content = NarrativePlanContentV2(canon_basis=BASIS, story_frame="f",
                                    scene_contracts=[v1_scene(), v2_scene_with_relationship()])
    kinds = {s.semantic_hash_version for s in content.scene_contracts}
    assert kinds == {"r2-scene-contract-content-v1", "r2-scene-contract-content-v2"}
```

Also cover: `extra="forbid"` on both new constraints; `source_character_ref == target_character_ref` rejected; v1 `SceneContract` still rejects a `RELATIONSHIP`/`THREAD` member; `SceneContractV2` defaults `omniscient_authoring_allowed_by_scene` to `False`; the discriminated `SceneContractValue` selects the right class from `semantic_hash_version`; `NarrativePlanContentV2.schema_version` is fixed to `r2-narrative-plan-v2`.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_plan_v2.py -q
```

Expected: FAIL (names not defined).

- [ ] **Step 3: Implement the v2 contracts**

Add the selectors, `SceneRelationshipConstraint`, `SceneThreadConstraint`, `SceneStateConstraintV2`, `SceneContractV2`, `SceneContractValue`, `NarrativePlanContentV2`. Keep every existing v1 class byte-identical: do **not** add v2 fields to `SceneContract` or `NarrativePlanContent`. Export the new names from `r2/contracts/__init__.py`. Add `NarrativePlanSchemaVersionError(NarrativeError)` to `r2/narrative/errors.py`.

- [ ] **Step 4: Run GREEN + v1 compatibility regression + commit**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_plan_v2.py tests/unit/r2/contracts/test_narrative_plan.py tests/unit/r2/contracts/test_narrative.py -q
uv run basedpyright --warnings
uv run python scripts/audit_tests.py --check
git add r2/contracts/narrative_plan.py r2/contracts/__init__.py r2/narrative/errors.py tests/unit/r2/contracts
git commit -m "feat(r2): add v2 SceneContract relationship and thread semantics"
```

Expected: existing `test_narrative_plan.py` unchanged and green; v1 model JSON schema unchanged.

---

### Task 2: Selector-dispatched v1/v2 hashing and the schema-transition ratchet

**Files:**
- Modify: `r2/narrative_plan/hashing.py`
- Create: `r2/narrative_plan/schema_upgrade.py`
- Modify: `r2/narrative_plan/__init__.py`
- Test: `tests/unit/r2/narrative_plan/test_hashing_v2.py`
- Test: `tests/unit/r2/narrative_plan/test_schema_upgrade_scene.py`
- Test: `tests/unit/r2/narrative_plan/test_hashing.py`

**Interfaces:**
- Produces:
  - `compute_scene_semantic_hash_v2(scene: SceneContractV2) -> str` (prefix `sh:`, schema `r2-scene-contract-content-v2`, excludes `version` + the three hash fields, covers every executable field including `omniscient_authoring_allowed_by_scene` and v2 constraints);
  - `compute_scene_semantic_hash_dispatch(scene: SceneContractValue) -> str` selecting by `semantic_hash_version`;
  - `compute_plan_content_hash_v2(content: NarrativePlanContentV2) -> str` (prefix `np:`, schema `r2-narrative-plan-content-v2`, scene identities carry `semantic_hash_version`);
  - `minimum_scene_selector(scene: SceneContractValue) -> str` returning `r2-scene-contract-content-v2` when any v2-only semantic (`RELATIONSHIP`/`THREAD` constraint, or `omniscient_authoring_allowed_by_scene is True`) is present, else `r2-scene-contract-content-v1`;
  - `require_scene_schema_transition(*, from_selector: str | None, to_selector: str, content_minimum: str) -> None` and `require_plan_schema_transition(*, from_selector: str | None, to_selector: str, contains_v2_scene: bool) -> None`, both raising `NarrativePlanSchemaVersionError` for an unknown selector, a selector below the content minimum, a v2→v1 downgrade, or a supplied hash that does not match the selected byte domain.
- Legal transitions: `genesis→v1` (only when no v2-only semantics), `genesis→v2`, `v1→v1` (only when no v2-only semantics), `v1→v2`, `v2→v2` (including after v2-only lists later become empty). `v2→v1` is illegal. The plan aggregate follows the same ratchet.

- [ ] **Step 1: Write RED tests**

```python
def test_v1_golden_scene_hash_is_unchanged_by_v2_code() -> None:
    assert compute_scene_semantic_hash(V1_GOLDEN_SCENE) == V1_GOLDEN_SCENE_HASH
    assert compute_scene_semantic_hash_dispatch(V1_GOLDEN_SCENE) == V1_GOLDEN_SCENE_HASH


def test_scene_with_relationship_semantic_must_select_v2() -> None:
    assert minimum_scene_selector(v2_scene_with_relationship()) == "r2-scene-contract-content-v2"
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_scene_schema_transition(from_selector="r2-scene-contract-content-v1",
                                        to_selector="r2-scene-contract-content-v1",
                                        content_minimum="r2-scene-contract-content-v2")


def test_v2_scene_lineage_cannot_downgrade_even_when_v2_lists_empty() -> None:
    with pytest.raises(NarrativePlanSchemaVersionError):
        require_scene_schema_transition(from_selector="r2-scene-contract-content-v2",
                                        to_selector="r2-scene-contract-content-v1",
                                        content_minimum="r2-scene-contract-content-v1")


def test_each_v2_executable_field_mutation_changes_the_semantic_hash() -> None:
    base = v2_scene_with_relationship()
    assert compute_scene_semantic_hash_v2(base) != compute_scene_semantic_hash_v2(
        base.model_copy(update={"omniscient_authoring_allowed_by_scene": True}))
```

Also cover: `genesis→v1` legal without v2 semantics and illegal with them; `v1→v2` legal; `v2→v2` legal after v2-only lists empty; unknown selector rejected; a v2 plan containing a v2 scene must be `r2-narrative-plan-v2`; a v2 plan may retain unchanged v1 scene members byte-for-byte (their `semantic_hash` and `version` unchanged inside the new plan version); commit-only metadata does not change the semantic hash.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/narrative_plan/test_hashing_v2.py tests/unit/r2/narrative_plan/test_schema_upgrade_scene.py -q
```

- [ ] **Step 3: Implement selector dispatch and the ratchet**

```python
_SCENE_V2 = "r2-scene-contract-content-v2"
_SCENE_V1 = "r2-scene-contract-content-v1"
_LEGAL_SCENE = frozenset({(None, _SCENE_V1), (None, _SCENE_V2), (_SCENE_V1, _SCENE_V1),
                          (_SCENE_V1, _SCENE_V2), (_SCENE_V2, _SCENE_V2)})

def require_scene_schema_transition(*, from_selector, to_selector, content_minimum):
    for s in (from_selector, to_selector, content_minimum):
        if s is not None and s not in (_SCENE_V1, _SCENE_V2):
            raise NarrativePlanSchemaVersionError(f"unknown scene selector {s!r}")
    if (from_selector, to_selector) not in _LEGAL_SCENE:
        raise NarrativePlanSchemaVersionError(f"illegal scene transition {from_selector!r} -> {to_selector!r}")
    if to_selector == _SCENE_V1 and content_minimum == _SCENE_V2:
        raise NarrativePlanSchemaVersionError("scene content requires the v2 selector")
```

`compute_scene_semantic_hash_v2` mirrors the v1 body-dump exclusion set. `compute_scene_semantic_hash_dispatch` and `compute_plan_content_hash_v2` route by selector. The v1 functions keep their exact current implementations.

- [ ] **Step 4: Run GREEN + v1 golden regression + commit**

```bash
uv run python -m pytest tests/unit/r2/narrative_plan/test_hashing_v2.py tests/unit/r2/narrative_plan/test_hashing.py tests/unit/r2/narrative_plan/test_schema_upgrade_scene.py tests/unit/r2/narrative_plan/test_validation.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_plan/hashing.py r2/narrative_plan/schema_upgrade.py r2/narrative_plan/__init__.py tests/unit/r2/narrative_plan
git commit -m "feat(r2): dispatch v1/v2 narrative plan hashing"
```

---

### Task 3: The sole versioned relationship Fact-key mapping

**Files:**
- Create: `r2/narrative/relationship_facts.py`
- Modify: `r2/narrative/__init__.py`
- Test: `tests/unit/r2/narrative/test_relationship_facts.py`

**Interfaces:**
- Produces `RELATIONSHIP_FACT_KEY_VERSION = "r2-relationship-fact-key-v1"` and:

```python
def relationship_fact_predicate(
    target_character_ref: str, relationship_key: str, *,
    mapping_version: str = RELATIONSHIP_FACT_KEY_VERSION,
) -> str:
    if mapping_version != RELATIONSHIP_FACT_KEY_VERSION:
        raise NarrativeRelationshipIntegrityError(f"unknown relationship-key mapping {mapping_version!r}")
    payload = {"schema": RELATIONSHIP_FACT_KEY_VERSION,
               "target_character_ref": target_character_ref, "relationship_key": relationship_key}
    return "r2rel:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(payload))).hexdigest()
```

- The Fact collision key for a directional relationship is `(subject_ref=source_character_ref, predicate=relationship_fact_predicate(target_character_ref, relationship_key))`, value = the relationship state string.
- Adds `NarrativeRelationshipIntegrityError(NarrativeError)` to `r2/narrative/errors.py`.

- [ ] **Step 1: Write RED tests**

```python
def test_predicate_is_direction_target_and_key_sensitive() -> None:
    ab = relationship_fact_predicate("b", "trust_level")
    ba = relationship_fact_predicate("a", "trust_level")
    ak = relationship_fact_predicate("b", "rivalry")
    assert len({ab, ba, ak}) == 3
    assert ab == relationship_fact_predicate("b", "trust_level")  # deterministic


def test_unknown_mapping_version_fails_closed() -> None:
    with pytest.raises(NarrativeRelationshipIntegrityError):
        relationship_fact_predicate("b", "trust_level", mapping_version="r2-relationship-fact-key-v2")
```

Also cover: the vector `relationship_fact_predicate("hero", "trust_level")` equals a committed golden string (regression anchor); the returned prefix is exactly `r2rel:`.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_relationship_facts.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative/relationship_facts.py r2/narrative/__init__.py r2/narrative/errors.py tests/unit/r2/narrative/test_relationship_facts.py
git commit -m "feat(r2): add the versioned relationship fact-key mapping"
```

---

### Task 4: Relationship comparison + R9 exact-reference + R10 duplicate-constraint validation

**Files:**
- Modify: `r2/narrative/validation.py`
- Modify: `r2/narrative/errors.py`
- Test: `tests/unit/r2/narrative/test_validation_f9.py`
- Test: `tests/unit/r2/narrative/test_validation.py`

**Interfaces:**
- Extends `NarrativeInvariantValidator.validate_scene(*, canon, plan, scene)` to accept a `SceneContractValue`. For each `SceneRelationshipConstraint` it:
  - resolves `source_character_ref` and `target_character_ref` to distinct `CHARACTER` entities in the exact `canon` basis (else `NarrativeRelationshipIntegrityError`);
  - selects active Facts by `(source_character_ref, relationship_fact_predicate(target, key))` at the list-defined exact instant (`temporal_window.effective_from` for `entry_state_constraints`, `effective_until` for `exit_state_targets`);
  - emits `SCENE_ENTRY_RELATIONSHIP_UNMET` / `SCENE_EXIT_RELATIONSHIP_UNMET` per the `PRESENT` / `ABSENT` / `EQUALS` / `NOT_EQUALS` table; `> 1` active Fact for the exact key, or a non-string state, is the distinct `RELATIONSHIP_INTEGRITY` finding (never coerced, never "one is chosen").
- R9: every Fact/Knowledge/Relationship entity or proposition reference describing present Canon state resolves against the exact plan Canon basis; a future exact `event_ref` may be absent at plan commit but an existing incompatible ref fails at plan commit (`SCENE_PRESENT_REF_UNRESOLVED`).
- R10: every `constraint_id` is unique within one SceneContract, and two normalized semantically identical constraints in the same list are rejected even under different IDs (`SCENE_CONSTRAINT_DUPLICATE_ID`, `SCENE_CONSTRAINT_DUPLICATE_SEMANTIC`); required/forbidden and entry/exit collisions keep their dedicated findings.
- These rules run as current new-work eligibility validation on v1 and v2 scenes; they add no field and are not hash-version triggers, and do not rewrite historical persisted-v1 integrity.
- Adds `NarrativeThreadLifecycleError(NarrativeError)` placeholder for Task 5.

- [ ] **Step 1: Write RED matrices**

```python
@pytest.mark.parametrize(("comparison", "expected_state", "facts", "phase", "rule"), [
    ("PRESENT", None, [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)], "entry", None),
    ("ABSENT", None, [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)], "entry",
     "SCENE_ENTRY_RELATIONSHIP_UNMET"),
    ("EQUALS", "BROKEN", [rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)], "exit",
     "SCENE_EXIT_RELATIONSHIP_UNMET"),
    ("NOT_EQUALS", "TRUSTED", [], "entry", "SCENE_ENTRY_RELATIONSHIP_UNMET"),  # absence is not inequality
])
def test_relationship_comparison_matrix(comparison, expected_state, facts, phase, rule) -> None:
    report = validate_scene_relationship(canon=canon_with_characters("hero", "mentor", facts=facts),
                                         constraint=rel_constraint(comparison, expected_state), phase=phase)
    observed = report.findings[0].rule_id if report.findings else None
    assert observed == rule


def test_two_active_relationship_facts_for_the_same_key_is_an_integrity_finding() -> None:
    report = validate_scene_relationship(
        canon=canon_with_characters("hero", "mentor",
            facts=[rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None),
                   rel_fact("hero", "mentor", "trust_level", "TRUSTED", AT_09, None)]),
        constraint=rel_constraint("PRESENT", None), phase="entry")
    assert [f.rule_id for f in report.findings] == ["RELATIONSHIP_INTEGRITY"]


def test_r10_rejects_normalized_semantic_duplicate_under_a_different_id() -> None:
    report = NarrativeInvariantValidator().validate_scene(canon=CANON, plan=PLAN, scene=scene_with(
        entry_state_constraints=[fact_constraint("c1", "hero", "role", "PRESENT"),
                                 fact_constraint("c2", "hero", "role", "PRESENT")]))
    assert "SCENE_CONSTRAINT_DUPLICATE_SEMANTIC" in [f.rule_id for f in report.findings]
```

Also cover: reversed direction / wrong target / wrong key / effective-interval boundary; `source`/`target` missing, non-`CHARACTER`, or equal; malformed (non-string) relationship state; R9 present-state proposition ref absent from the basis fails at plan commit while a future `event_ref` remains an obligation; R10 duplicate `constraint_id`; entry/exit collisions keep their dedicated findings, not duplicate-ID errors.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_validation_f9.py -q
```

- [ ] **Step 3: Implement the pure rules**

Add a `_validate_scene_relationships`, `_validate_present_state_refs` (R9), and `_validate_constraint_uniqueness` (R10) family to the existing pure validator. Relationship truth uses active Facts at the exact instant; `> 1` active Fact never selects one. Normalize a constraint for R10 by `model_dump(mode="json", exclude={"constraint_id"})`. Findings sort by the existing `(severity, rule_id, affected_refs, story_time)` key. The `validate_canon` entry point and every M5A rule ID stay stable for v1 inputs.

- [ ] **Step 4: Run GREEN + regression + commit**

```bash
uv run python -m pytest tests/unit/r2/narrative/test_validation_f9.py tests/unit/r2/narrative/test_validation.py tests/unit/r2/narrative/test_validation_m5b.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative/validation.py r2/narrative/errors.py tests/unit/r2/narrative
git commit -m "feat(r2): validate relationship constraints and exact references"
```

---

### Task 5: Plan-wide presentation-order thread lifecycle validation

**Files:**
- Modify: `r2/narrative_plan/validation.py`
- Modify: `r2/narrative_plan/service.py`
- Modify: `r2/narrative_plan/__init__.py`
- Test: `tests/unit/r2/narrative_plan/test_thread_lifecycle.py`
- Test: `tests/integration/r2/narrative_plan/test_service.py`

**Interfaces:**
- Produces `validate_plan_thread_lifecycle(plan_content: NarrativePlanContentV2) -> NarrativeValidationReport`, a pure function that lives beside — not folded into — `validate_plan_hierarchy`. `NarrativePlanService.commit_revision` runs both plan-wide passes **before** its existing per-scene validation loop.
- Rule set, applied after sorting by the already-unique `sequence_index` (presentation order, not story time):
  1. first appearance in `active_threads` establishes the thread open at that scene entry; later omissions do not implicitly resolve it;
  2. entry `OPEN` requires the thread open and present in `active_threads`; entry `RESOLVED` requires an earlier resolution, the thread absent from `active_threads`, and `payoff_ref` equal to the payoff that performed that earlier resolution;
  3. exit `OPEN` requires the thread still open with no resolution in that scene;
  4. exit `RESOLVED` requires the thread open at entry, its exact `payoff_ref` in that scene's `promise_payoff_refs`, and marks it resolved after that scene;
  5. resolution without a prior/open thread, orphan payoff binding, two resolutions, and any later reappearance/re-open of the same resolved `thread_ref` fail closed;
  6. no per-scene `validate_scene()` call may claim these cross-scene invariants.
- Findings use `SCENE_THREAD_LIFECYCLE_*`. They prove plan internal consistency, not that accepted prose delivered a payoff.

- [ ] **Step 1: Write RED matrix**

```python
def test_thread_may_be_omitted_from_an_intermediate_scene_without_resolving() -> None:
    report = validate_plan_thread_lifecycle(plan_content_with_scenes([
        scene(seq=0, active_threads=["t1"], exit_targets=[thread_target("t1", "OPEN")]),
        scene(seq=1, active_threads=[]),  # unrelated scene
        scene(seq=2, active_threads=["t1"], promise_payoff_refs=["p1"],
              exit_targets=[thread_target("t1", "RESOLVED", payoff_ref="p1")]),
    ]))
    assert report.ok


def test_double_resolution_fails_closed() -> None:
    report = validate_plan_thread_lifecycle(plan_content_with_scenes([
        scene(seq=0, active_threads=["t1"], promise_payoff_refs=["p1"],
              exit_targets=[thread_target("t1", "RESOLVED", payoff_ref="p1")]),
        scene(seq=1, active_threads=["t1"], promise_payoff_refs=["p2"],
              exit_targets=[thread_target("t1", "RESOLVED", payoff_ref="p2")]),
    ]))
    assert "SCENE_THREAD_LIFECYCLE_DOUBLE_RESOLUTION" in [f.rule_id for f in report.findings]
```

Also cover: orphan resolution (resolve before open); orphan payoff binding (entry `RESOLVED` naming a `payoff_ref` that never resolved it); post-resolution reappearance in `active_threads`; missing active membership for an entry `OPEN`; presentation-order vs story-time confusion (a later `sequence_index` scene with an earlier `temporal_window` still follows presentation order); an exit `RESOLVED` whose `payoff_ref` is absent from `promise_payoff_refs`.

- [ ] **Step 2: Run RED**

```bash
uv run python -m pytest tests/unit/r2/narrative_plan/test_thread_lifecycle.py -q
```

- [ ] **Step 3: Implement the pure pass and wire it in**

Sort scenes by `sequence_index`. Maintain `open_threads: dict[str, str | None]` (thread → resolving payoff or `None`) and `resolved: dict[str, str]`. Apply rules 1–5 deterministically; sort findings by `(rule_id, affected_refs, sequence_index)`. In `NarrativePlanService._validate_content`, call `validate_plan_hierarchy` then `validate_plan_thread_lifecycle` (v2 content only) before the scene loop; raise `NarrativePlanValidationError([finding.rule_id ...])` on any error finding.

- [ ] **Step 4: Run GREEN + service regression + commit**

```bash
uv run python -m pytest tests/unit/r2/narrative_plan/test_thread_lifecycle.py tests/unit/r2/narrative_plan/test_validation.py tests/integration/r2/narrative_plan/test_service.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_plan/validation.py r2/narrative_plan/service.py r2/narrative_plan/__init__.py tests/unit/r2/narrative_plan tests/integration/r2/narrative_plan
git commit -m "feat(r2): validate plan-wide thread lifecycle"
```

---

### Task 6: Scene-side omniscient AUTHOR_DRAFT gate

**Files:**
- Modify: `r2/narrative_context/compiler.py`
- Modify: `r2/narrative_context/errors.py`
- Test: `tests/unit/r2/narrative_context/test_omniscient_gate.py`
- Test: `tests/unit/r2/narrative_context/test_compiler.py`

**Interfaces:**
- Adds a gate to `NarrativeContextCompiler` before any author-only material is read: an `AUTHOR_DRAFT` request with no POV passes the SceneContract half **only** when the selected scene is v2, `scene.pov is None`, and `omniscient_authoring_allowed_by_scene is True`. A v1 scene is treated as `False`. Passing this half is not overall admission.
- A `CHARACTER_SIMULATION` request still always requires its exact POV subject (unchanged).
- Until typed CreativePolicy authority exists, every no-POV `AUTHOR_DRAFT` request that passes the scene half terminates with the stable `AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE` finding and remains blocked overall. A request that fails the scene half raises the same class of `NarrativeContextValidationError` with rule `SCENE_OMNISCIENT_AUTHORING_FORBIDDEN`. No policy prose can enable omniscient authoring.
- Produces `AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE` and `SCENE_OMNISCIENT_AUTHORING_FORBIDDEN` in `r2/narrative_context/errors.py`.

- [ ] **Step 1: Write RED matrix**

```python
@pytest.mark.parametrize(("scene_kind", "pov", "omni", "expected"), [
    ("v1", None, None, "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"),
    ("v2", None, False, "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"),
    ("v2", "hero", True, "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"),  # fixed POV: no-POV request rejected
    ("v2", None, True, "AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE"),
])
async def test_no_pov_author_draft_gate(scene_kind, pov, omni, expected) -> None:
    with pytest.raises(NarrativeContextValidationError) as exc:
        await compile_author_draft_no_pov(scene=make_scene(scene_kind, pov=pov, omniscient=omni))
    assert expected in str(exc.value)
```

Also cover: a `CHARACTER_SIMULATION` request with a POV subject is unaffected; the gate runs before AUTHOR_TRUTH segments are assembled (assert no `AUTHOR_TRUTH` channel content on the failure path); `creative_policy` prose containing "omniscient allowed" does not change the outcome.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + regression + commit**

```bash
uv run python -m pytest tests/unit/r2/narrative_context/test_omniscient_gate.py tests/unit/r2/narrative_context/test_compiler.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_context/compiler.py r2/narrative_context/errors.py tests/unit/r2/narrative_context
git commit -m "feat(r2): gate no-POV author draft on the scene contract"
```

---

### Task 7: Huohuo change-record parser port + Node parity harness

**Files:**
- Create: `r2/narrative_lifecycle/__init__.py`, `r2/narrative_lifecycle/changeset_parser.py`
- Create: `tests/donor_parity/__init__.py`, `tests/donor_parity/huohuo_change_record_runner.mjs`, `tests/donor_parity/test_huohuo_change_record.py`
- Create: `tests/donor_parity/fixtures/huohuo_change_record/` (canonical JSON/JSONL corpus)
- Create: `docs/r2/evidence/R2_M5C_DONOR_BASELINE.json` (manifest)
- Modify: `pyproject.toml` (deptry dev-dep note; import-fitness)

**Interfaces:**
- `changeset_parser.py` is a **pure** module: parse/normalize a raw change-record string into structured proposal evidence. No authority, persistence, provider, clock, or random import. Public exports mirror the seven selected Huohuo pure exports: header canonicalization, structured/trailing split, structured detection, orphan peeling, artifact normalization, prose/change-record split, and length-adjust echo removal. Output is a frozen `ParsedChangeRecord` value (or a typed parse error) — it is not a `NarrativeChangeSet` and carries no lineage, decision, or Canon identity.
- Donor pin (verbatim from spec §2.4): Huohuo `workbench-server/src/common/novel/novel-change-record.ts` at `appolloqin/huohuo-drama@f104b853b3563e124d9cde25f9331d323fb483b9`, source SHA-256 `dd3a310e1d83f80fca132a6ea64380c3d953c780054d0ea93e9f865c09fb5088`. The Node runner verifies revision + SHA-256 before executing and runs the module in its pinned source-tree context so its relative `novel-memory-parser.js` dependency resolves. The harness is test-only: never shipped, imported, or started by the runtime.

- [ ] **Step 1: Write the baseline manifest + RED parity test**

`R2_M5C_DONOR_BASELINE.json` records both ports' exact repo revision, path, source SHA-256, plus an inventory of every **selected** and every **explicitly excluded** donor behavior (spec §2.4 table). RED test:

```python
def test_huohuo_baseline_manifest_matches_the_pinned_source() -> None:
    m = json.loads(Path("docs/r2/evidence/R2_M5C_DONOR_BASELINE.json").read_text())
    entry = m["ports"]["huohuo_change_record"]
    assert entry["revision"] == "f104b853b3563e124d9cde25f9331d323fb483b9"
    assert entry["source_sha256"] == "dd3a310e1d83f80fca132a6ea64380c3d953c780054d0ea93e9f865c09fb5088"


@pytest.mark.parametrize("case", load_jsonl("tests/donor_parity/fixtures/huohuo_change_record/cases.jsonl"))
def test_python_port_matches_node_baseline(case, huohuo_node_baseline) -> None:
    py = run_python_port(case["input"])
    node = huohuo_node_baseline[case["id"]]
    assert normalize(py) == normalize(node)
```

Corpus target: ~25–35 branch/error cases + ≥10 prose fixtures covering every selected pure parser/normalizer branch — malformed headers, orphan blocks, empty input, prose shaped like a false structured record, deterministic-repeat output.

- [ ] **Step 2: Run RED**

```bash
node --version
uv run python -m pytest tests/donor_parity/test_huohuo_change_record.py -q
```

Expected: FAIL (port + runner missing).

- [ ] **Step 3: Implement the Node runner and the Python port**

`huohuo_change_record_runner.mjs`: read the pinned checkout path from an env var the pytest fixture sets, assert `git rev-parse HEAD` and `sha256sum` of the target file match the manifest, `import()` the module in its source-tree context, run each fixture record, emit one normalized JSON output/error record per case to stdout. `changeset_parser.py`: a clean-room Python re-implementation of the seven selected pure exports, matched branch-for-branch to the donor. Any intentional improvement over donor behavior is recorded in the manifest and backed by an explicit regression fixture.

- [ ] **Step 4: Run GREEN + fitness + commit**

```bash
uv run python -m pytest tests/donor_parity/test_huohuo_change_record.py tests/unit/r2/test_m5c_architecture_boundaries.py -q
uv run ruff check r2/narrative_lifecycle tests/donor_parity
uv run basedpyright --warnings
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/__init__.py r2/narrative_lifecycle/changeset_parser.py tests/donor_parity docs/r2/evidence/R2_M5C_DONOR_BASELINE.json pyproject.toml
git commit -m "feat(r2): port the huohuo change-record parser with node parity"
```

---

### Task 8: Novel Studio hard-rules port + Node parity harness

**Files:**
- Create: `r2/narrative_lifecycle/continuity_rules.py`
- Create: `tests/donor_parity/novel_hard_rules_runner.mjs`, `tests/donor_parity/test_novel_hard_rules.py`, `tests/donor_parity/fixtures/novel_hard_rules/`
- Modify: `docs/r2/evidence/R2_M5C_DONOR_BASELINE.json`

**Interfaces:**
- `continuity_rules.py` is a **pure** module: deterministic continuity findings + stable rule-ID report merge over an explicit input snapshot. No authority, persistence, provider, clock, or random import. Output is a frozen ordered `ContinuityReport` value; it never becomes a `NarrativeChangeSet` or Canon state.
- Donor pin (verbatim from spec §2.4): Novel Studio `src/lib/continuity/hardRules.ts` at `YfengJ/novel-studio-ai@9b690ae2e2f6921f9bd2782b42cef53c1662ad3b`, source SHA-256 `7756c4093b52e11e3f591c58af1719887428fd5e437f4ade0828533ac3663954`.

- [ ] **Step 1: Write RED parity test** — ~8–10 cases covering rule hit/miss, and empty / hard-only / soft-only / combined / severity / stable rule-ID merge ordering.

```python
@pytest.mark.parametrize("case", load_jsonl("tests/donor_parity/fixtures/novel_hard_rules/cases.jsonl"))
def test_novel_port_matches_node_baseline(case, novel_node_baseline) -> None:
    assert normalize(run_python_rules(case["input"])) == normalize(novel_node_baseline[case["id"]])
```

- [ ] **Step 2: Run RED → Step 3: Implement runner + port → Step 4: GREEN + fitness + commit**

```bash
uv run python -m pytest tests/donor_parity/test_novel_hard_rules.py tests/unit/r2/test_m5c_architecture_boundaries.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/continuity_rules.py tests/donor_parity docs/r2/evidence/R2_M5C_DONOR_BASELINE.json
git commit -m "feat(r2): port novel-studio hard rules with node parity"
```

---

### Task 9: M5C-1A architecture fitness, scope verifier, and checkpoint freeze

**Files:**
- Create: `tests/unit/r2/test_m5c_architecture_boundaries.py` (complete it)
- Create: `scripts/r2/verify_m5c_scope.py`, `tests/unit/scripts/r2/test_verify_m5c_scope.py`
- Modify: `pyproject.toml` (import-linter contracts)
- Create after Codex review: `docs/r2/evidence/R2_M5C_1A_REVIEW.md`

**Interfaces:**
- Import-linter contracts: `r2.contracts` and the pure `r2.narrative_lifecycle.changeset_parser` / `continuity_rules` / `coverage` modules do not import `lib.db`, `server`, providers, Agent runtime, or production runtime; F9 modules (`relationship_facts`, `narrative_plan.schema_upgrade`, `narrative_plan.validation`, `narrative.validation`) import no donor code and appear in no donor-parity runtime path; the compiler (added later) imports no authority write port, repository, UoW, clock, random, or provider.
- AST fitness: relationship Fact predicates are produced only by `relationship_fact_predicate`; cross-scene thread lifecycle exists only in `validate_plan_thread_lifecycle`, not in `validate_scene` or the context compiler; no `r2/**` runtime module imports `tests/donor_parity/**`.
- `verify_m5c_scope.py`: given a base ref and a HEAD, assert the diff touches only implementation-allowlisted paths, and that an evidence-only handoff commit touches only its named `docs/r2/evidence/` file.

- [ ] **Step 1: Write RED fitness tests** — cover each contract above plus: adding `omniscient_authoring_allowed_by_scene` to v1 `SceneContract` fails; serializing empty v2 maps into a v1 scene fails; recomputing a v1 golden hash with v2 code fails.

- [ ] **Step 2: Run RED → Step 3: Implement contracts + verifier → Step 4: GREEN**

```bash
uv run python -m pytest tests/unit/r2/test_m5c_architecture_boundaries.py tests/unit/scripts/r2/test_verify_m5c_scope.py -q
uv run lint-imports
```

- [ ] **Step 5: Freeze the M5C-1A implementation head**

```bash
git status --short
git add tests/unit/r2/test_m5c_architecture_boundaries.py scripts/r2/verify_m5c_scope.py tests/unit/scripts/r2/test_verify_m5c_scope.py pyproject.toml
git commit -m "test(r2): fence the M5C-1A compatibility blast radius"
M5C_1A_VERIFIED_HEAD="$(git rev-parse HEAD)"
git status --short
```

- [ ] **Step 6: Run fresh M5C-1A gates at the frozen head**

```bash
uv run python -m pytest -n 4 --dist loadfile tests/unit/r2/contracts tests/unit/r2/narrative tests/unit/r2/narrative_plan tests/unit/r2/narrative_context tests/integration/r2/narrative tests/integration/r2/narrative_plan tests/donor_parity -q
uv run ruff check . && uv run ruff format --check .
uv run basedpyright --warnings
uv run lint-imports
uv run deptry lib server alembic scripts tests r2
uv run python scripts/audit_tests.py --check
uv run python scripts/r2/verify_m5c_scope.py --base "$(git rev-parse "$M5C_DOCUMENT_MATERIALIZATION_HEAD")" --head "$M5C_1A_VERIFIED_HEAD" --phase impl
git diff --check "$M5C_DOCUMENT_MATERIALIZATION_HEAD".."$M5C_1A_VERIFIED_HEAD"
git status --short
```

Expected: all exit 0 while `git rev-parse HEAD` stays `M5C_1A_VERIFIED_HEAD` and status is empty. Record every command + count for the review doc.

- [ ] **Step 7: Obtain Codex review and create an evidence-only handoff**

Codex reviews the exact frozen head for contract/domain correctness: v1 golden hash preservation, ratchet legality table, relationship comparison matrix, thread lifecycle rules, omniscient gate, and `R2-DEC-031` donor parity (branch-complete coverage + Node baseline execution). Only after an `APPROVED` verdict, Codex writes `R2_M5C_1A_REVIEW.md` (verified SHA, commands/counts, v1/v2 selectors + golden vectors, donor baseline manifest + parity result, graph coverage, findings, verdict).

```bash
git add docs/r2/evidence/R2_M5C_1A_REVIEW.md
git commit -m "docs(r2): approve M5C-1A verified head"
M5C_1A_HANDOFF_HEAD="$(git rev-parse HEAD)"
git status --short
```

Expected: `git diff --name-only "$M5C_1A_VERIFIED_HEAD".."$M5C_1A_HANDOFF_HEAD"` returns exactly `docs/r2/evidence/R2_M5C_1A_REVIEW.md`. Task 10 starts from this handoff only.

---

## Checkpoint M5C-1B — immutable Narrative lifecycle evidence (final M5C-1)

*Integrates the Task 7/8 donor proposal output only through the immutable evidence contracts. `M5C-1` is not complete until this checkpoint passes.*

### Task 10: Immutable evidence contracts + semantic-effect-key algebra

**Files:**
- Create: `r2/contracts/narrative_lifecycle.py`
- Create: `r2/narrative_lifecycle/hashing.py`, `r2/narrative_lifecycle/errors.py`
- Modify: `r2/contracts/__init__.py`, `r2/narrative_lifecycle/__init__.py`
- Test: `tests/unit/r2/contracts/test_narrative_lifecycle.py`
- Test: `tests/unit/r2/narrative_lifecycle/test_hashing.py`

**Interfaces:**
- All contracts `frozen=True`, `extra="forbid"`, timezone-aware UTC, explicitly versioned canonical hash domains. Produces:
  - `NarrativeWorkScope` (`user_id`, `project_name`, `plan_id`, `scene_contract_id`, `canon_branch_id`) — the stable workflow scope; immutable bindings (`canon_version_id`, `plan_version`, `scene_contract_version`, `context_pack_id`, `creative_policy_ref` + `_version`, `compiler_version`, extractor identifiers) are separate fields, never scope-key fields, and never replaced by a "latest" value;
  - `DraftCandidate`, `NarrativeRevision` (fields per spec §5.1/§5.2; `NarrativeRevision.predecessor_revision_id` is immutable evidence lineage, not acceptance; no `accepted` boolean anywhere);
  - `ExtractionAttempt`, `ExtractionResult` (`outcome: Literal["SUCCEEDED","ABSTAINED","CONFLICT","FAILED","OUTCOME_UNKNOWN"]`; §5.3);
  - `NarrativeChangeSet` (§5.4) with `change_set_lineage_id`, `source_spans`, `semantic_effect_keys`, `changes`, provenance;
  - `NarrativeSemanticEffectKey = CanonMutationEffectKey | NarrativeOutcomeEffectKey` (closed, versioned algebra); `THREAD_PAYOFF(thread_ref, payoff_ref)` is a `NarrativeOutcomeEffectKey` mapping to zero Canon operations;
  - `content_hash = sha256(normalized UTF-8 prose bytes)` reusing the frozen M5B normalization; a separate `semantic_fingerprint` over artifact kind, opaque ID, stable scope, exact bases, provenance, and relevant schema/policy versions. Neither hash selects an artifact or grants authority.
- `r2/narrative_lifecycle/hashing.py`: `compute_prose_content_hash`, `compute_evidence_semantic_fingerprint`, `compute_decision_canonical_identity_hash` (Task 15), `compute_canon_approval_binding_fingerprint` (Task 27) — each with a `r2-m5c-*` version tag.
- `r2/narrative_lifecycle/errors.py`: the full §13 taxonomy (`NarrativeEvidenceNotFoundError`, `NarrativeEvidenceIdentityConflictError`, `NarrativeEvidenceIntegrityError`, `NarrativeDecisionNotFoundError`, `NarrativeDecisionAuthorizationError`, `NarrativeDecisionIdentityConflictError`, `NarrativeDecisionPredecessorConflict`, `NarrativeDecisionApplicabilityError`, `NarrativeAuthorityIntegrityError`, `NarrativeConflictCoverageError`, `NarrativeConflictLineageConflict`, `NarrativeAttemptGenerationConflict`, `CanonDeltaCompilationError`, `NarrativeHandoffConflict`, `NarrativeThreadPayoffApplicabilityError`).

- [ ] **Step 1: Write RED contract + hashing tests**

```python
def test_effect_key_algebra_is_closed_and_typed() -> None:
    outcome = ThreadPayoffEffectKey(thread_ref="t1", payoff_ref="p1")
    assert outcome.canon_operation_count == 0
    with pytest.raises(ValidationError):
        CanonMutationEffectKey.model_validate({"kind": "THREAD_PAYOFF"})  # outcome key is not a mutation key


def test_equal_prose_under_different_bases_has_distinct_semantic_fingerprint() -> None:
    a = revision(base_canon_version_id="cv-1")
    b = revision(base_canon_version_id="cv-2")
    assert a.content_hash == b.content_hash
    assert compute_evidence_semantic_fingerprint(a) != compute_evidence_semantic_fingerprint(b)


def test_successful_extraction_result_declares_a_non_empty_ordered_change_set_id_list() -> None:
    with pytest.raises(ValidationError):
        ExtractionResult(result_id="r1", attempt_id="a1", generation=0, outcome="SUCCEEDED",
                         change_set_ids=[], completed_at=NOW, output_fingerprint="f")
```

Also cover: `extra="forbid"` on every contract; aware-UTC enforcement; a non-success `ExtractionResult` must have empty `change_set_ids`; `NarrativeChangeSet.source_spans` and `.semantic_effect_keys` non-empty when it proposes an effect; opaque ID reuse with one changed tuple field is caught by the hash helper (distinct `canonical_identity_hash`); prose normalization under Unicode/line-ending fixtures matches the frozen M5B bytes.

- [ ] **Step 2: Run RED → Step 3: Implement contracts + hashing → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_lifecycle.py tests/unit/r2/narrative_lifecycle/test_hashing.py -q
uv run basedpyright --warnings
uv run python scripts/audit_tests.py --check
git add r2/contracts/narrative_lifecycle.py r2/contracts/__init__.py r2/narrative_lifecycle tests/unit/r2/contracts tests/unit/r2/narrative_lifecycle
git commit -m "feat(r2): define immutable narrative lifecycle evidence contracts"
```

---

### Task 11: Pure source-span and semantic-effect-key coverage rules

**Files:**
- Create: `r2/narrative_lifecycle/coverage.py`
- Modify: `r2/narrative_lifecycle/__init__.py`
- Test: `tests/unit/r2/narrative_lifecycle/test_coverage.py`

**Interfaces:**
- Pure module. Produces:
  - `normalize_source_spans(spans) -> tuple[SourceSpan, ...]` — one normalized coordinate system, canonical sort order, adjacent-span merge;
  - `normalize_effect_keys(keys) -> tuple[NarrativeSemanticEffectKey, ...]` — canonical ordering across both key families;
  - `spans_overlap(a, b) -> bool`, `effect_keys_collide(a, b, *, policy) -> bool`;
  - `coverage_contains(change_evidence_span, declared_coverage) -> bool` — each change's evidence span must be contained by declared coverage;
  - `minimal_conflict_subject(change_sets) -> ConflictSubject` — the minimal canonical intersection of competing reviewed change sets (used by the Task 19 lineage genesis; caller-widened/partial/reordered coverage is rejected there).
- No import of `lib.db`, `server`, providers, clocks, or randomness.

- [ ] **Step 1: Write RED tests** — canonical ordering is stable under input permutation; adjacent spans merge; a `CanonMutationEffectKey` and a `NarrativeOutcomeEffectKey` never "collide" across families unless their normalized subjects match under policy; a change whose evidence span is not contained by declared coverage fails; `minimal_conflict_subject` is order-independent and rejects a widened subject.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/r2/narrative_lifecycle/test_coverage.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/coverage.py r2/narrative_lifecycle/__init__.py tests/unit/r2/narrative_lifecycle/test_coverage.py
git commit -m "feat(r2): add pure narrative coverage and overlap rules"
```

---

### Task 12: Evidence ORM tables, migration, repository, and UoW scaffolding

**Files:**
- Create: `lib/db/models/narrative_lifecycle.py`
- Modify: `lib/db/models/__init__.py`
- Create: `lib/db/repositories/narrative_lifecycle.py`
- Create: `lib/db/narrative_lifecycle_uow.py`
- Create: `alembic/versions/5c7c4a0e0001_add_narrative_lifecycle_evidence.py`
- Test: `tests/unit/lib/db/models/test_narrative_lifecycle.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_narrative_lifecycle_evidence.py`
- Test: `tests/integration/lib/db/repositories/test_narrative_lifecycle.py`

**Interfaces:**
- Tables (all `UserOwnedMixin`, `RESTRICT` deletion, no cascade from evidence): `narrative_draft_candidates`, `narrative_revisions`, `narrative_extraction_attempts`, `narrative_extraction_results`, `narrative_change_sets`, plus an ordered association table proving exact successful-result → change-set membership.
- Constraints: PK per identity; `UNIQUE (attempt_id, generation)`; a unique FK from one result to that exact `(attempt_id, generation)`; composite scope/basis FKs where a bare opaque-ID FK could otherwise join tenants or incompatible revisions; non-negative generations; `CHECK` that a `SUCCEEDED` result has ≥1 association row and a non-success result has none (enforced in the repository transaction where a cross-row `CHECK` is unsound — see research §3.1).
- `alembic` chains from `down_revision = "5b7c4a0e0001"`; additive only; SQLite upgrade/downgrade proven.
- `NarrativeLifecycleRepository`: scoped reads (`get_exact_draft_candidate`, `get_exact_revision`, `get_exact_extraction_attempt`, `get_exact_extraction_result`, `get_exact_change_set`), append methods (`insert_draft_candidate`, `insert_revision`, `insert_extraction_attempt`, `insert_successful_extraction(result, change_sets)`, `insert_non_successful_extraction(result)`), and `flush()`. `IntegrityError` maps to `NarrativeEvidenceIdentityConflictError` / `NarrativeAttemptGenerationConflict` via a `_mentions` needle check. It never commits, rolls back, or constructs a session.
- `SqlAlchemyNarrativeLifecycleUnitOfWork`: fresh `AsyncSession`, `BEGIN IMMEDIATE` (SQLite) / `session.begin()` (PostgreSQL), exposes `.repository`, owns commit/rollback lifecycle only.

- [ ] **Step 1: Write RED ORM + migration + repository tests**

```python
async def test_result_is_uniquely_bound_to_one_attempt_generation(narrative_lifecycle_repo) -> None:
    await narrative_lifecycle_repo.insert_extraction_attempt(attempt(generation=0))
    await narrative_lifecycle_repo.insert_non_successful_extraction(result(generation=0, outcome="FAILED"))
    with pytest.raises(NarrativeAttemptGenerationConflict):
        await narrative_lifecycle_repo.insert_non_successful_extraction(result(generation=0, outcome="ABSTAINED"))


async def test_alembic_round_trip_is_additive(alembic_cfg) -> None:
    await upgrade(alembic_cfg, "5c7c4a0e0001")
    assert "narrative_change_sets" in await table_names()
    await downgrade(alembic_cfg, "5b7c4a0e0001")
    assert "narrative_change_sets" not in await table_names()
```

Also cover: cross-scope read returns `None`; composite basis FK rejects an incompatible revision link; a successful-extraction insert with a missing/extra/reordered/foreign-scope change set writes nothing.

- [ ] **Step 2: Run RED → Step 3: Implement models + migration + repo + uow → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/lib/db/models/test_narrative_lifecycle.py tests/integration/lib/db/migrations/test_alembic_narrative_lifecycle_evidence.py tests/integration/lib/db/repositories/test_narrative_lifecycle.py -q
DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic downgrade "$M5C_ALEMBIC_BASE" && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head
uv run python scripts/audit_tests.py --check
git add lib/db/models/narrative_lifecycle.py lib/db/models/__init__.py lib/db/repositories/narrative_lifecycle.py lib/db/narrative_lifecycle_uow.py alembic/versions/5c7c4a0e0001_add_narrative_lifecycle_evidence.py tests/unit/lib/db/models tests/integration/lib/db
git commit -m "feat(db): add append-only narrative lifecycle evidence tables"
```

---

### Task 13: NarrativeLifecycleEvidenceService (evidence recording; `admit_extraction` fails closed until M5C-2)

**Files:**
- Create: `r2/narrative_lifecycle/ports.py`, `r2/narrative_lifecycle/evidence.py`
- Modify: `r2/narrative_lifecycle/__init__.py`, `r2/narrative_lifecycle/errors.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_evidence_service.py`

**Interfaces:**
- `ports.py`: `NarrativeLifecycleEvidenceRepositoryPort`, `NarrativeLifecycleUnitOfWork`, `NarrativeLifecycleUnitOfWorkFactory` protocols — exact reads + appends only; no head-mutation method exists on any evidence port.
- `evidence.py` exposes exactly: `record_draft_candidate(candidate)`, `record_revision(revision)`, `admit_extraction(command) -> ExtractionAttempt`, `record_successful_extraction(result, change_sets)`, `record_non_successful_extraction(result)`, `admit_compilation(command) -> CompilationAttempt` (Task 24), `record_successful_compilation(result, canon_delta)` (Task 24), `record_compilation_without_delta(result)` (Task 24), `get_exact_*(scope, exact_id)`.
- **No temporary weaker semantics at this checkpoint.** `admit_extraction()` and `admit_compilation()` require the current-effective decision guard, which needs the M5C-2 authority layer. Until that layer is wired (Task 20 for extraction, Task 24 for compilation), both **fail closed** with `NarrativeAuthorityUnavailableError` — they never run an "exists-only" or otherwise relaxed check. Task 20 replaces the fail-closed body with the real transaction-bound selection guard; the public signature is unchanged.
- What M5C-1B actually delivers and reviews: immutable `record_draft_candidate` / `record_revision`, the immutable extraction result + `NarrativeChangeSet` evidence writes (`record_successful_extraction` / `record_non_successful_extraction`), and all `get_exact_*` reads. These are tested against an `ExtractionAttempt` row inserted directly through the repository by a test-only fixture (the real admission path is exercised in Task 20).
- `record_revision` verifies candidate, predecessor, scope, and exact bases agree; a cycle, cross-scope reference, missing predecessor, or ID reuse with different bytes fails before any insert.
- `record_successful_extraction` verifies exact attempt/generation, requires `SUCCEEDED`, compares the complete ordered ID set, inserts the result and every declared change set, flushes, commits once. Exact retry compares the result and all change-set tuples and writes nothing; any partial/mismatched retry fails with no write. There is no public result-then-change-set append sequence.
- `record_non_successful_extraction` rejects `SUCCEEDED` and any non-empty `change_set_ids`. `OUTCOME_UNKNOWN` is terminal for its exact attempt generation; a late provider success is rejected and attaches no change set; continuation requires a newly admitted generation naming the ambiguous predecessor.
- Adds `NarrativeAuthorityUnavailableError(NarrativeError)` to `r2/narrative_lifecycle/errors.py` (distinct from `NarrativeDecisionAuthorizationError`: the authority layer is not yet present, versus an authenticated actor lacking a grant).

- [ ] **Step 1: Write RED integration tests**

```python
async def test_admit_extraction_fails_closed_before_the_authority_layer_exists(evidence_service) -> None:
    with pytest.raises(NarrativeAuthorityUnavailableError):
        await evidence_service.admit_extraction(extraction_command(generation=0))


async def test_outcome_unknown_is_terminal_and_late_success_is_rejected(evidence_service, seed_attempt) -> None:
    attempt = await seed_attempt(generation=0)  # fixture inserts the ExtractionAttempt row directly
    await evidence_service.record_non_successful_extraction(result(attempt.attempt_id, 0, "OUTCOME_UNKNOWN"))
    with pytest.raises(NarrativeAttemptGenerationConflict):
        await evidence_service.record_successful_extraction(
            result(attempt.attempt_id, 0, "SUCCEEDED", change_set_ids=["cs-1"]), [change_set("cs-1")])


async def test_successful_bundle_is_atomic(evidence_service, seed_attempt, fault) -> None:
    attempt = await seed_attempt(generation=0)
    with fault.before_commit():
        with pytest.raises(InjectedFault):
            await evidence_service.record_successful_extraction(
                result(attempt.attempt_id, 0, "SUCCEEDED", ["cs-1"]), [change_set("cs-1")])
    assert await evidence_service.get_exact_extraction_result(scope, attempt.attempt_id, 0) is None
    assert await evidence_service.get_exact_change_set(scope, "cs-1") is None
```

Also cover: a fixture-seeded attempt row is durable when a crash follows with no result recorded; exact result retry returns the original and writes nothing; a `SUCCEEDED` result with a missing/extra/reordered/wrong-generation/foreign-scope change set writes nothing; a late terminal result for a superseded generation with no prior result is retained but fenced from workflow advancement; continuation from `OUTCOME_UNKNOWN` requires a newly admitted generation (asserted in Task 20 once `admit_extraction` is live).

- [ ] **Step 2: Run RED → Step 3: Implement the service → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_evidence_service.py tests/unit/r2/test_m5c_architecture_boundaries.py -q
uv run lint-imports
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/ports.py r2/narrative_lifecycle/evidence.py r2/narrative_lifecycle/errors.py r2/narrative_lifecycle/__init__.py tests/integration/r2/narrative_lifecycle/test_evidence_service.py
git commit -m "feat(r2): add the narrative lifecycle evidence service"
```

---

### Task 14: Freeze the M5C-1 checkpoint (M5C-1B)

**Files:**
- Modify: `pyproject.toml` (evidence-service import contracts)
- Create after Codex review: `docs/r2/evidence/R2_M5C_1_REVIEW.md`

- [ ] **Step 1: Add + verify the evidence-service import contracts**

Import-linter: `r2.narrative_lifecycle.evidence` may not import `r2.narrative_lifecycle.acceptance` (Task 18) or any head-mutation symbol; `r2.narrative_lifecycle.changeset_parser` / `continuity_rules` / `coverage` / `compiler` do not import `lib.db`, `server`, providers, or Agent runtime.

```bash
uv run lint-imports
uv run python -m pytest tests/unit/r2/test_m5c_architecture_boundaries.py -q
```

- [ ] **Step 2: Freeze the head**

```bash
git status --short
git add pyproject.toml
git commit -m "test(r2): fence the narrative evidence service boundary"
M5C_1_VERIFIED_HEAD="$(git rev-parse HEAD)"
```

- [ ] **Step 3: Run fresh M5C-1 gates at the frozen head**

```bash
uv run python -m pytest -n 4 --dist loadfile tests/unit/r2 tests/unit/lib/db tests/integration/r2/narrative tests/integration/r2/narrative_plan tests/integration/r2/narrative_lifecycle tests/integration/lib/db tests/donor_parity -q
uv run ruff check . && uv run ruff format --check .
uv run basedpyright --warnings
uv run lint-imports
uv run deptry lib server alembic scripts tests r2
uv run python scripts/audit_tests.py --check
uv run python scripts/r2/verify_m5c_scope.py --base "$M5C_1A_HANDOFF_HEAD" --head "$M5C_1_VERIFIED_HEAD" --phase impl
git diff --check "$M5C_1A_HANDOFF_HEAD".."$M5C_1_VERIFIED_HEAD"
git status --short
```

Expected: all exit 0; HEAD unchanged; status empty.

- [ ] **Step 4: Codex review + evidence-only handoff**

Codex reviews evidence immutability, atomic-bundle behavior, `OUTCOME_UNKNOWN` fencing, and the no-head-write boundary. After `APPROVED`, Codex writes `R2_M5C_1_REVIEW.md`.

```bash
git add docs/r2/evidence/R2_M5C_1_REVIEW.md
git commit -m "docs(r2): approve M5C-1 verified head"
M5C_1_HANDOFF_HEAD="$(git rev-parse HEAD)"
```

Expected: the handoff diff is exactly `docs/r2/evidence/R2_M5C_1_REVIEW.md`. Task 15 starts from this handoff only.

---

## Checkpoint M5C-2 — Narrative acceptance authority

*Three typed decision families over one internal authority kernel; rebuildable logical heads; opaque conflict-resolution lineage. Sole Narrative head writer.*

### Task 15: Decision, authorization, head, and lineage contracts

**Files:**
- Modify: `r2/contracts/narrative_lifecycle.py`
- Modify: `r2/narrative_lifecycle/hashing.py`, `r2/narrative_lifecycle/ports.py`
- Test: `tests/unit/r2/contracts/test_narrative_lifecycle.py`

**Interfaces:**
- Produces:
  - `RevisionDecisionAction = Literal["ACCEPT","REJECT","SUPERSEDE"]`, `ChangeSetReviewAction = Literal["ACCEPT","REJECT","SUPERSEDE"]`, `ConflictResolutionAction = Literal["RESOLVE","REJECT","SUPERSEDE"]`;
  - `NarrativeDecisionAuthorization` (§6.2: `authorization_ref`, scope, `actor_id`, `authority_role: Literal["HUMAN_SHOWRUNNER"]`, `decision_family`, `action`, `decision_id`, `stable_subject_fingerprint`, `decision_command_fingerprint`, `authenticated_at`, `authenticated_via`) — immutable original Human approval evidence, scoped to one exact canonical command;
  - `NarrativeDecisionRetryAuthentication` (§6.2: `retry_authentication_ref`, scope, `actor_id`, role, `decision_id`, `authenticated_at`, `authenticated_via`) — proves only that the same original `actor_id` is currently authenticated; never persisted as decision identity;
  - `NarrativeDecisionReceipt` (returned by all three commands; names exact decision + generations; `currently_effective` is deliberately absent);
  - command models carrying `decision_id`, `decision_family`, `action`, stable subject key, selected evidence IDs, `expected_latest_decision_id: str | None`, `expected_effective_decision_id: str | None`, exact Canon/Plan/Scene/Context bindings, Human actor identity, family-specific semantic inputs;
  - `RevisionAcceptanceHead` key `(user_id, project_name, plan_id, scene_contract_id, canon_branch_id)`; `ChangeSetReviewHead` key `(revision_acceptance_decision_id, change_set_lineage_id)`; `ConflictResolutionHead` key `(revision_acceptance_decision_id, conflict_resolution_lineage_id)`; every head carries `latest_decision_id?`, `decision_generation`, `effective_decision_id?`, `effective_generation`;
  - `ConflictResolutionLineage` (§6.7: `conflict_resolution_lineage_id`, `revision_acceptance_decision_id`, `conflict_subject` (canonical span coverage + semantic-effect keys), `conflict_subject_fingerprint`, `created_at`, `created_by`);
  - `NarrativeShowrunnerAuthorityPort` protocol with `authorize_initial_decision(authenticated_principal, canonical_command) -> NarrativeDecisionAuthorization` and `authenticate_exact_retry(authenticated_principal, decision_id, exact_scope) -> NarrativeDecisionRetryAuthentication`.
- `compute_decision_canonical_identity_hash(command, authorization)` covers decision family, action, stable scope, selected IDs, both expected predecessors, exact bases, actor identity, conflict coverage, chosen resolution, referenced resolution decisions, **and** the exact original `NarrativeDecisionAuthorization` including its receipt time; it excludes fresh `NarrativeDecisionRetryAuthentication` and server `stored_at`.

- [ ] **Step 1: Write RED contract tests**

```python
def test_retry_authentication_is_not_part_of_decision_identity() -> None:
    cmd, auth = revision_command(), authorization()
    h1 = compute_decision_canonical_identity_hash(cmd, auth)
    h2 = compute_decision_canonical_identity_hash(cmd.model_copy(update={"retry_authentication": other_retry_auth()}), auth)
    assert h1 == h2


def test_changed_actor_or_basis_is_a_different_identity() -> None:
    base = compute_decision_canonical_identity_hash(revision_command(), authorization())
    assert base != compute_decision_canonical_identity_hash(
        revision_command(actor_id="other"), authorization(actor_id="other"))
    assert base != compute_decision_canonical_identity_hash(
        revision_command(canon_version_id="cv-2"), authorization())
```

Also cover: genesis expects both predecessors `None`; `ACCEPT` forbids an existing effective selection; `SUPERSEDE` requires an exact current effective decision; `REJECT` names a candidate and preserves the effective pointer; `authority_role` fixed to `HUMAN_SHOWRUNNER`; `extra="forbid"` on every model.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_lifecycle.py tests/unit/r2/narrative_lifecycle/test_hashing.py -q
uv run python scripts/audit_tests.py --check
git add r2/contracts/narrative_lifecycle.py r2/narrative_lifecycle/hashing.py r2/narrative_lifecycle/ports.py tests/unit/r2
git commit -m "feat(r2): define narrative decision authority contracts"
```

---

### Task 16: Decision, identity-registry, head, and lineage ORM + migration

**Files:**
- Modify: `lib/db/models/narrative_lifecycle.py`, `lib/db/repositories/narrative_lifecycle.py`, `lib/db/narrative_lifecycle_uow.py`
- Create: `alembic/versions/5c7c4a0e0002_add_narrative_decision_authority.py`
- Test: `tests/unit/lib/db/models/test_narrative_lifecycle.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_narrative_decision_authority.py`
- Test: `tests/integration/lib/db/repositories/test_narrative_lifecycle.py`

**Interfaces:**
- Tables: `narrative_decision_identities` (`decision_id` PK, `user_id`, `project_name`, `decision_family`, `canonical_identity_hash`; `UNIQUE (decision_id, decision_family)`); `revision_acceptance_decisions`, `change_set_review_decisions`, `conflict_resolution_decisions` (three typed tables, each with a family `CHECK` and a composite FK to the identity registry); `conflict_resolution_lineages` with `UNIQUE (revision_acceptance_decision_id, conflict_subject_fingerprint)`; `revision_acceptance_heads`, `change_set_review_heads`, `conflict_resolution_heads` (one unique complete stable key per family; composite FKs from head pointers back to decisions for that same subject); ordered association tables for competing reviews / selected change sets / resolutions / admission head observations.
- Constraints per spec §7.1: composite self-FKs from expected latest/effective decisions to the same typed logical subject; non-negative generations + null-pointer/zero-generation genesis checks; no cascading delete from authority evidence; head rows are the only mutable Narrative acceptance rows.
- Repository additions: `get_decision_by_id(decision_id, *, user_id, project_name)` — a plain scoped `SELECT`, **no lock, no INSERT** (the kernel calls this first, per Task 17 step 2); `lock_or_insert_head(family, key)` = `INSERT ... ON CONFLICT DO NOTHING` then `SELECT ... FOR UPDATE` by full key (research §3.1 first-head strategy — the kernel calls it only after retry resolution, for a genuinely new ID); `insert_identity_and_decision(...)` (one transaction); `advance_head_pointers(...)` with `rowcount(...) == 1` on the expected pointer/generation predicate, incrementing `effective_generation` only in the same update that changes `effective_decision_id`; `insert_conflict_lineage(...)`; canonical multi-head lock ordering `(head_family_rank, user_id, project_name, serialized_logical_key)` with family rank revision < change-set < conflict-resolution.

- [ ] **Step 1: Write RED ORM + migration tests**

```python
async def test_global_decision_id_cannot_collide_across_typed_tables(repo) -> None:
    await repo.insert_identity_and_decision(revision_identity("d-1"), revision_decision("d-1"))
    with pytest.raises(NarrativeDecisionIdentityConflictError):
        await repo.insert_identity_and_decision(review_identity("d-1"), review_decision("d-1"))


async def test_head_pointer_fk_rejects_a_decision_from_another_subject(repo) -> None:
    with pytest.raises(IntegrityError):
        await repo.force_head_pointer("revision", key_a, effective_decision_id="decision-of-key-b")
```

Also cover: `UNIQUE (revision_acceptance_decision_id, conflict_subject_fingerprint)`; genesis zero-generation / null-pointer checks; additive SQLite upgrade/downgrade; `advance_head_pointers` affecting zero or multiple rows raises a deterministic predecessor/integrity error.

- [ ] **Step 2: Run RED → Step 3: Implement models + migration + repo → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/lib/db/models/test_narrative_lifecycle.py tests/integration/lib/db/migrations/test_alembic_narrative_decision_authority.py tests/integration/lib/db/repositories/test_narrative_lifecycle.py -q
DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic downgrade "$M5C_ALEMBIC_BASE" && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head
uv run python scripts/audit_tests.py --check
git add lib/db/models/narrative_lifecycle.py lib/db/repositories/narrative_lifecycle.py lib/db/narrative_lifecycle_uow.py alembic/versions/5c7c4a0e0002_add_narrative_decision_authority.py tests/unit/lib/db tests/integration/lib/db
git commit -m "feat(db): add narrative decision authority tables"
```

---

### Task 17: The internal authority kernel — retry ordering, predecessors, REJECT semantics

**Files:**
- Create: `r2/narrative_lifecycle/authority_kernel.py`
- Modify: `r2/narrative_lifecycle/ports.py`, `r2/narrative_lifecycle/__init__.py`
- Test: `tests/unit/r2/narrative_lifecycle/test_authority_kernel.py`

**Interfaces:**
- `authority_kernel.py` holds the shared per-command transaction body used by all three families (contracts + DB tables stay typed): canonical identity computation, exact-retry resolution, locking, OCC, append, commit. Not public API — only `NarrativeAcceptanceService` calls it.
- **Isolation precondition (spec §7.2).** Every kernel transaction must run at `READ COMMITTED`. The step-2/step-5 double `get_decision_by_id` lookup is correct only under a fresh per-statement snapshot; the kernel must not open its transaction through any session/engine configuration that raises the isolation level. This is asserted in Task 21, not re-derived here.
- **Retry before any head write.** Per-command order, matching spec §7.2 exactly:
  1. begin one fresh short authority transaction;
  2. `get_decision_by_id(decision_id, exact_scope)` — **before any head INSERT or `FOR UPDATE`**;
  3. **if the ID already exists in the exact scope:** require a fresh `NarrativeDecisionRetryAuthentication`, reload and verify the original stored `NarrativeDecisionAuthorization`, compare the full canonical business tuple (excluding the fresh retry authentication and server `stored_at`); return the original immutable receipt with **zero head/identity/decision writes**. Same ID / different tuple → `NarrativeDecisionIdentityConflictError`, zero writes. A missing or corrupt head does **not** get created or repaired on this path;
  4. **only for a genuinely new ID:** `INSERT ... ON CONFLICT DO NOTHING` the typed head by its complete stable key (null pointers, zero generations), then `SELECT ... FOR UPDATE` by full key and verify the row matches the requested scope/subject;
  5. under the serialized transaction, `get_decision_by_id` **again** and resolve a concurrently-landed exact retry before any stale-predecessor rejection (a retry that raced in between still performs zero writes);
  6. compare **both** `expected_latest_decision_id` and `expected_effective_decision_id`;
  7. resolve every referenced evidence/decision by exact ID and verify tenant, basis, current-effectiveness, action, and mutual applicability;
  8. insert identity-registry + typed decision rows;
  9. advance the latest pointer and, when applicable, the effective pointer (`effective_generation` bumps only in the same update that changes `effective_decision_id`);
  10. flush once, commit once.
  Steps 1–3 are the shared §7.2 bucket for all three families; Task 19's conflict-lineage genesis composes on top of it (its lineage `INSERT ... ON CONFLICT DO NOTHING` and subject-row read happen after step 3's retry resolution, never before).
- `REJECT`: appends a typed decision, advances `latest_decision_id` + `decision_generation`, leaves `effective_decision_id` + `effective_generation` unchanged, cannot clear/replace an unrelated effective selection, and cannot be consumed downstream as an accepted selection.
- A current-selection guard never trusts a head pointer alone: under the head lock it loads the referenced typed decisions, validates subject/action/predecessor consistency, and proves latest + folded effective pointers agree with the authoritative chain; any mismatch is `NarrativeAuthorityIntegrityError`.

- [ ] **Step 1: Write RED tests** (against a fake repo implementing the port):

```python
async def test_exact_retry_writes_nothing_and_never_touches_a_head(kernel, fake_repo) -> None:
    fake_repo.seed_decision("d-1", generation=1)
    fake_repo.advance_latest("d-2")           # head moved on after d-1
    fake_repo.drop_head("revision", KEY)      # head is missing entirely
    receipt = await kernel.run(retry_command("d-1"))  # same id + full tuple, stale latest
    assert receipt.decision_id == "d-1"
    assert fake_repo.writes == []             # no head INSERT, no head reconstruction, no decision write
    assert fake_repo.head("revision", KEY) is None


async def test_reject_preserves_the_effective_pointer(kernel, fake_repo) -> None:
    await kernel.run(accept_command("d-1"))
    await kernel.run(reject_command("d-2", expected_effective="d-1"))
    head = fake_repo.head("revision", KEY)
    assert head.effective_decision_id == "d-1" and head.latest_decision_id == "d-2"
    assert head.effective_generation == 1 and head.decision_generation == 2
```

Also cover: same ID / different tuple → `NarrativeDecisionIdentityConflictError` with zero writes; a retry whose `decision_id` only becomes visible under the serialized transaction (step 5) is still resolved to the original receipt with zero writes; stale `expected_latest_decision_id` fails even when the effective pointer is unchanged; stale `expected_effective_decision_id` fails even when latest matches; a head pointing at a wrong-scope/wrong-family decision → `NarrativeAuthorityIntegrityError` (never "choose another/latest"); a genuinely new ID with a missing head triggers exactly one `ON CONFLICT DO NOTHING` head INSERT (genesis), a retry never does; crash after decision insert but before head advance rolls back both.

- [ ] **Step 2: Run RED → Step 3: Implement the kernel → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/r2/narrative_lifecycle/test_authority_kernel.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/authority_kernel.py r2/narrative_lifecycle/ports.py r2/narrative_lifecycle/__init__.py tests/unit/r2/narrative_lifecycle/test_authority_kernel.py
git commit -m "feat(r2): add the narrative authority kernel"
```

---

### Task 18: NarrativeAcceptanceService — decide_revision + review_change_set

**Files:**
- Create: `r2/narrative_lifecycle/acceptance.py`
- Modify: `r2/narrative_lifecycle/__init__.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_acceptance_decisions.py`

**Interfaces:**
- `acceptance.py` exposes exactly: `decide_revision(command, *, authenticated_principal)`, `review_change_set(command, *, authenticated_principal)`, `resolve_change_set_conflict(command, *, authenticated_principal)` (Task 19), `admit_canon_handoff(command, *, authenticated_principal, canon_commit_approval)` (Task 28), `get_current_revision_selection(exact_scope)`, `get_current_change_set_selection(exact_revision_decision, exact_lineage)`, `get_current_conflict_resolution(exact_revision_decision, exact_resolution_lineage)`, `verify_exact_current_selection(exact_decision_refs)`. No generic `save_decision`, `set_head`, `approve`, `latest`, or raw repository method is public.
- **The public decision surface never accepts a caller-supplied `NarrativeDecisionAuthorization`.** Every decision command takes only `command` + `authenticated_principal`. The service itself calls the injected `NarrativeShowrunnerAuthorityPort`: `authorize_initial_decision(authenticated_principal, canonical_command)` for a genuinely new `decision_id`, or `authenticate_exact_retry(authenticated_principal, decision_id, exact_scope)` for an already-stored same-scope ID. The kernel verifies the returned authorization's binding and stores it atomically with the decision; for a retry it reloads the original stored authorization and compares the canonical business command without substituting the fresh authentication value. There is no `authorization=` keyword on any production method — a caller cannot hand the service an authorization object.
- Authority policy (§6.2 table): only an authenticated Human Showrunner capability is `ALLOW`; delegated Narrative Reviewer, Human author without the capability, extractor, compiler, Agent, provider, orchestrator, and generic host administrator are all `DENY`. A missing/unavailable authority adapter denies by default. A Human Showrunner who authored an input must still perform a separate explicit authenticated decision action.
- Tests drive denial and wrong-family cases through a **fake `NarrativeShowrunnerAuthorityPort`**: it returns `DENY` / raises for non-Showrunner principals, and for a wrong-family request it returns a `NarrativeDecisionAuthorization` bound to a different `decision_family` / `action` / scope so the service (not the caller) rejects it as a binding mismatch.
- `ChangeSetReviewHead` key is `(revision_acceptance_decision_id, change_set_lineage_id)`; many non-overlapping lineage heads may coexist under one revision acceptance; a replacement advances only the named lineage head; a new revision acceptance does not inherit prior revision change-set heads.

- [ ] **Step 1: Write RED integration tests**

```python
@pytest.mark.parametrize("actor", ["delegated_reviewer", "human_author_no_capability", "agent",
                                    "extractor", "compiler", "provider", "orchestrator", "host_admin"])
async def test_only_human_showrunner_may_decide(acceptance_service, actor) -> None:
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await acceptance_service.decide_revision(revision_command(action="ACCEPT"),
                                                 authenticated_principal=principal(actor))


async def test_authorization_bound_to_another_family_is_rejected_by_the_service(acceptance_service, fake_showrunner):
    # the fake port issues a receipt bound to revision_acceptance; the call is a change-set review
    fake_showrunner.next_authorization = authorization(family="revision_acceptance", decision_id="d-1", action="ACCEPT")
    with pytest.raises(NarrativeDecisionAuthorizationError):
        await acceptance_service.review_change_set(review_command(decision_id="d-1"),
                                                   authenticated_principal=showrunner_principal())
```

Also cover: `ACCEPT` with an existing effective selection fails; `SUPERSEDE` replaces only its exact expected effective predecessor; one lineage supersession does not alter another non-overlapping lineage; a new revision acceptance does not inherit prior change-set heads; exact retry after later head movement returns the original decision without making it effective again; a `NarrativeAcceptanceService` constructed with no authority adapter denies every decision by default; the public methods expose no `authorization=` parameter (architecture-fitness assertion in Task 21).

- [ ] **Step 2: Run RED → Step 3: Implement the two commands over the kernel → Step 4: GREEN + fitness + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_acceptance_decisions.py tests/unit/r2/test_m5c_architecture_boundaries.py -q
uv run lint-imports
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/acceptance.py r2/narrative_lifecycle/__init__.py tests/integration/r2/narrative_lifecycle/test_acceptance_decisions.py
git commit -m "feat(r2): add revision and change-set acceptance decisions"
```

---

### Task 19: resolve_change_set_conflict and conflict-lineage genesis

**Files:**
- Modify: `r2/narrative_lifecycle/acceptance.py`, `r2/narrative_lifecycle/authority_kernel.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_conflict_lineage.py`

**Interfaces:**
- `resolve_change_set_conflict(...)` is the **only** conflict-lineage creation interface. Its genesis form atomically: creates the lineage, creates its zero-generation head, appends the first `RESOLVE` or `REJECT` decision, and advances that head as required. There is no public `open_change_set_conflict()` and no evidence/compiler path that can allocate a lineage.
- The caller proposes an opaque `conflict_resolution_lineage_id`, but the service derives the versioned `conflict_subject_fingerprint` from the **minimal canonical intersection** of the exact currently effective competing reviewed change sets (`coverage.minimal_conflict_subject`). Caller-supplied widened, partial, reordered, or free-form coverage is rejected before writes.
- DB enforces `UNIQUE (revision_acceptance_decision_id, conflict_subject_fingerprint)`: the same accepted revision + same canonical conflict subject = one lineage. Concurrent genesis with different opaque IDs → one wins; the loser gets `NarrativeConflictLineageConflict` with no writes and may resolve/retry against the winning lineage within the already-authorized scope.
- A resolution decision names competing `change_set_ids`, competing `review_decision_ids`, exact overlapping spans/effect keys, the chosen typed resolution, Human actor + approval receipt, and expected latest/effective predecessors. A resolution is currently applicable only while it is the effective resolution for its head **and** every named review decision remains effective. The compiler never creates a lineage, merges lineages, widens coverage, infers a choice, or picks "the latest resolution".
- Genesis transaction order (spec §7.2, conflict-genesis half), built on the Task 17 kernel: begin one fresh short transaction → **`get_decision_by_id` and resolve an exact retry first** (fresh `NarrativeDecisionRetryAuthentication` + original stored authorization + full-tuple compare; a retry returns the original receipt with **zero lineage/head/decision writes**) → only for a genuinely new ID: lock the revision + competing change-set review heads in canonical order and verify current/effective → derive the minimal canonical subject + fingerprint → `INSERT ... ON CONFLICT DO NOTHING` the lineage by the subject-unique constraint → read the unique subject row (a different stored opaque ID → `NarrativeConflictLineageConflict`, no losing writes) → `INSERT ... ON CONFLICT DO NOTHING` the zero-generation conflict head, then lock + validate it → `get_decision_by_id` again under serialization and resolve a concurrently-landed exact retry before predecessor checks → verify null genesis predecessors + exact authorization/decision tuple → insert identity + first typed decision + advance pointers per `REJECT`/`RESOLVE` → flush once, commit once.

- [ ] **Step 1: Write RED integration tests**

```python
async def test_same_revision_and_canonical_subject_cannot_create_two_lineages(acceptance_service) -> None:
    await acceptance_service.resolve_change_set_conflict(genesis_command(lineage_id="L-1", subject=SUBJECT))
    with pytest.raises(NarrativeConflictLineageConflict):
        await acceptance_service.resolve_change_set_conflict(genesis_command(lineage_id="L-2", subject=SUBJECT))


async def test_widened_conflict_subject_is_rejected_before_writes(acceptance_service) -> None:
    with pytest.raises(NarrativeConflictCoverageError):
        await acceptance_service.resolve_change_set_conflict(genesis_command(subject=widen(SUBJECT)))
    assert acceptance_service_repo_writes() == []


async def test_superseding_a_named_review_makes_the_resolution_inapplicable(acceptance_service) -> None:
    res = await acceptance_service.resolve_change_set_conflict(genesis_command(lineage_id="L-1"))
    await acceptance_service.review_change_set(supersede_command(review_decision_id=res.named_reviews[0]))
    assert (await acceptance_service.get_current_conflict_resolution(REV_DECISION, "L-1")).applicable is False
```

Also cover: concurrent genesis with different opaque IDs on the same subject — one accepted, one `NarrativeConflictLineageConflict`, zero losing writes; reverse-order multi-head lock requests follow canonical order and do not deadlock (PostgreSQL); `REJECT` in a conflict lineage advances latest, preserves effective; a resolution naming a change set outside the selection fails closed.

- [ ] **Step 2: Run RED → Step 3: Implement genesis + resolution → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_conflict_lineage.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/acceptance.py r2/narrative_lifecycle/authority_kernel.py tests/integration/r2/narrative_lifecycle/test_conflict_lineage.py
git commit -m "feat(r2): add conflict-resolution lineage and decisions"
```

---

### Task 20: Current-selection reads, integrity rebuild, and extraction-admission currentness

**Files:**
- Create: `r2/narrative_lifecycle/integrity.py`
- Modify: `r2/narrative_lifecycle/acceptance.py`, `r2/narrative_lifecycle/evidence.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_integrity.py` (partial — completed in Task 30)
- Test: `tests/integration/r2/narrative_lifecycle/test_evidence_service.py` (extend)

**Interfaces:**
- `get_current_*` reads and `verify_exact_current_selection(exact_decision_refs)` return observations naming exact decisions + generations — never durable authority tokens. Only a decision transaction changes a selection.
- `NarrativeLifecycleIntegrityChecker` (partial here — rebuild only): computes candidate head rows from the append-only typed decision chains into a **separate** projection and compares before any replacement. `decision_generation` rebuilds from all decisions; `effective_generation` rebuilds under action semantics (`REJECT` never advances it). A mismatch is `NarrativeAuthorityIntegrityError`, not permission to trust the mutable head.
- `NarrativeLifecycleEvidenceService.admit_extraction` — the Task 13 fail-closed body is now **replaced** by the real guard: it requires the named `revision_acceptance_decision_id` to be the **exact current effective revision selection** (a transaction-bound guard that locks the required heads in canonical order, verifies effective pointers, and inserts the immutable attempt before commit — the attempt's admission instant is atomic with its currentness proof). The public signature is unchanged from Task 13; `NarrativeAuthorityUnavailableError` is no longer raised on this path. A later supersession does not delete the attempt/result but blocks new work. This task also adds the RED case proving continuation from an `OUTCOME_UNKNOWN` result requires a newly admitted generation naming the ambiguous predecessor (deferred from Task 13).

- [ ] **Step 1: Write RED tests**

```python
async def test_admit_extraction_is_live_after_this_task(evidence_service, acceptance_service) -> None:
    d1 = await acceptance_service.decide_revision(accept_command("d-1", revision_id="rev-1"))
    attempt = await evidence_service.admit_extraction(
        extraction_command(revision_acceptance_decision_id=d1.decision_id, generation=0))
    assert attempt.generation == 0  # no longer NarrativeAuthorityUnavailableError


async def test_head_rebuild_reproduces_latest_and_effective_pointers_exactly(integrity_checker, seeded_authority) -> None:
    rebuilt = await integrity_checker.rebuild_heads(scope=SCOPE)
    assert rebuilt == await seeded_authority.snapshot_heads(scope=SCOPE)


async def test_reject_does_not_advance_effective_generation_on_rebuild(integrity_checker, seeded_authority) -> None:
    await seeded_authority.decide_revision(accept_command("d-1"))
    await seeded_authority.decide_revision(reject_command("d-2", expected_effective="d-1"))
    rebuilt = (await integrity_checker.rebuild_heads(scope=SCOPE)).revision_head
    assert rebuilt.effective_generation == 1 and rebuilt.decision_generation == 2


async def test_extraction_admission_requires_the_current_effective_revision(evidence_service, acceptance_service) -> None:
    d1 = await acceptance_service.decide_revision(accept_command("d-1", revision_id="rev-1"))
    await acceptance_service.decide_revision(supersede_command("d-2", old_effective="d-1", revision_id="rev-2"))
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await evidence_service.admit_extraction(extraction_command(revision_acceptance_decision_id=d1.decision_id))
```

Also cover: a head row pointing at a missing decision → integrity error; deleting + rebuilding head tables yields identical logical heads/cardinalities; `verify_exact_current_selection` returns `False` (not raises) for a superseded ref; after an `OUTCOME_UNKNOWN` extraction result, `admit_extraction` for the same generation is rejected and continuation requires a newly admitted generation that names the ambiguous predecessor.

- [ ] **Step 2: Run RED → Step 3: Implement rebuild + admission currentness → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_integrity.py tests/integration/r2/narrative_lifecycle/test_evidence_service.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/integrity.py r2/narrative_lifecycle/acceptance.py r2/narrative_lifecycle/evidence.py tests/integration/r2/narrative_lifecycle
git commit -m "feat(r2): rebuild narrative heads and gate extraction on currentness"
```

---

### Task 21: Freeze the M5C-2 checkpoint

**Files:**
- Modify: `pyproject.toml` (sole-head-writer + no-decision-write-from-extractor contracts)
- Modify: `tests/unit/r2/test_m5c_architecture_boundaries.py`
- Create: `tests/integration/r2/narrative_lifecycle/test_concurrency.py`
- Create after Codex review: `docs/r2/evidence/R2_M5C_2_REVIEW.md`

- [ ] **Step 1: Write RED PostgreSQL concurrency tests**

Use two independent sessions from `concurrent_session_factory` and an explicit `asyncio.Barrier(2)` so both commands reach the head-serialization point before either proceeds — no `time.sleep`, no implicit ordering:

```python
@pytest.mark.uses_db
async def test_two_concurrent_genesis_decisions_yield_one_accepted_and_one_conflict(concurrent_session_factory):
    barrier = asyncio.Barrier(2)

    async def run(decision_id: str) -> object:
        svc = acceptance_service(concurrent_session_factory())
        cmd = revision_command(decision_id=decision_id, action="ACCEPT",
                               expected_latest=None, expected_effective=None)  # both are genesis
        async with instrument_before_head_lock(svc, barrier):  # awaits barrier inside the txn, before lock_or_insert_head's FOR UPDATE
            return await capture(svc.decide_revision(cmd, authenticated_principal=showrunner_principal()))

    a, b = await asyncio.gather(run("d-a"), run("d-b"), return_exceptions=True)
    outcomes = sorted(type(x).__name__ for x in (a, b))
    # exactly one commits; the loser sees the serialized head already advanced
    assert "NarrativeDecisionReceipt" in outcomes
    assert "NarrativeDecisionPredecessorConflict" in outcomes
```

`instrument_before_head_lock` is a production seam-free test helper: it wraps the repository's `lock_or_insert_head` via a constructor-injected `on_head_serialization` async hook (default no-op in production) that awaits the barrier. Cover each head family (revision / change-set review / conflict-lineage genesis): two concurrent genesis → one `NarrativeDecisionReceipt` + one deterministic `NarrativeDecisionPredecessorConflict` (or `NarrativeConflictLineageConflict` for lineage genesis); fault injected after identity insert / after decision insert / after head update but before commit each rolls back all authority writes (assert row counts unchanged); response loss after commit reconciles through exact ID / full tuple with zero new writes; two commands locking the same lineage set in reverse caller order both follow the canonical `(head_family_rank, user_id, project_name, serialized_logical_key)` order and neither deadlocks (bounded `asyncio.wait_for`); stale `expected_latest_decision_id` and stale `expected_effective_decision_id` each fail closed independently.

- [ ] **Step 2: Add the authority-surface fitness assertions**

In `tests/unit/r2/test_m5c_architecture_boundaries.py`, add: (a) `inspect.signature` of every public `NarrativeAcceptanceService` decision method has parameters `{command, authenticated_principal}` (plus `canon_commit_approval` for `admit_canon_handoff`) and **no `authorization` parameter**; (b) `NarrativeAcceptanceService.__init__` requires a `NarrativeShowrunnerAuthorityPort` and, constructed without one, raises rather than defaulting to a permissive stub; (c) import-linter: only `r2.narrative_lifecycle.acceptance` appends decisions or mutates heads; `r2.narrative_lifecycle.evidence`, `.compiler`, `.changeset_parser`, `.continuity_rules`, and extractor/provider/orchestration modules cannot import the acceptance repository or head-mutation symbols; (d) spec §7.2 isolation precondition — against `concurrent_session_factory`, assert the authority kernel's transaction reports `READ COMMITTED` (e.g. `SHOW TRANSACTION ISOLATION LEVEL` / driver equivalent) and that no engine/session/pool default in the wiring path raises it for these sessions.

- [ ] **Step 3: Run RED → Step 4: Implement remaining guards → Step 5: GREEN**

```bash
DATABASE_URL="$POSTGRES_TEST_URL" uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_concurrency.py tests/unit/r2/test_m5c_architecture_boundaries.py -q
uv run lint-imports
```

- [ ] **Step 6: Freeze the head + run fresh M5C-2 gates**

```bash
git status --short
git add pyproject.toml tests/unit/r2/test_m5c_architecture_boundaries.py tests/integration/r2/narrative_lifecycle/test_lifecycle_concurrency.py tests/integration/r2/test_m5c_architecture_boundaries_db.py
git commit -m "test(r2): fence and stress the narrative acceptance authority"
M5C_2_VERIFIED_HEAD="$(git rev-parse HEAD)"
uv run python -m pytest -n 4 --dist loadfile tests/unit/r2 tests/unit/lib/db tests/integration/r2 tests/integration/lib/db tests/integration/donor_parity -q
DATABASE_URL="$POSTGRES_TEST_URL" uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_lifecycle_concurrency.py tests/integration/r2/test_m5c_architecture_boundaries_db.py -q
uv run ruff check . && uv run ruff format --check . && uv run basedpyright --warnings && uv run lint-imports && uv run deptry lib server alembic scripts tests r2
uv run python scripts/audit_tests.py --check
uv run python scripts/r2/verify_m5c_scope.py --base "$M5C_1_HANDOFF_HEAD" --head "$M5C_2_VERIFIED_HEAD" --phase impl
git diff --check "$M5C_1_HANDOFF_HEAD".."$M5C_2_VERIFIED_HEAD"
git status --short
```

- [ ] **Step 7: Codex review + evidence-only handoff**

Codex reviews the three decision families, the public authorization surface (no caller-supplied authorization), the authority denial matrix, retry-before-head ordering, `REJECT` semantics, conflict-lineage uniqueness, and head rebuild equality. After `APPROVED`, Codex writes `R2_M5C_2_REVIEW.md`.

```bash
git add docs/r2/evidence/R2_M5C_2_REVIEW.md
git commit -m "docs(r2): approve M5C-2 verified head"
M5C_2_HANDOFF_HEAD="$(git rev-parse HEAD)"
```

Expected: handoff diff is exactly `docs/r2/evidence/R2_M5C_2_REVIEW.md`. Task 22 starts from this handoff only.

---

## Checkpoint M5C-3 — CanonDelta compilation

*Compilation attempt/result evidence + a pure exact-input compiler + exact accepted thread-payoff proof binding.*

### Task 22: Compilation contracts + compiled-delta ORM + migration

**Files:**
- Modify: `r2/contracts/narrative_lifecycle.py`, `r2/narrative_lifecycle/hashing.py`
- Modify: `lib/db/models/narrative_lifecycle.py`, `lib/db/repositories/narrative_lifecycle.py`
- Create: `alembic/versions/5c7c4a0e0003_add_narrative_compilation.py` (compilation tables **only** — no handoff-admission table; that is `5c7c4a0e0004`, created fresh in Task 27, so no later checkpoint edits a migration inside an already-frozen HEAD)
- Test: `tests/unit/r2/contracts/test_narrative_lifecycle.py`, `tests/unit/lib/db/models/test_narrative_lifecycle.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_narrative_compilation.py`

**Interfaces:**
- Contracts (§5.5): `CompilationAttempt` (`attempt_id`, `generation`, `work_scope`, `revision_id`, `revision_acceptance_decision_id`, `selected_change_sets[]: {change_set_id, review_decision_id}`, `conflict_resolution_decision_ids[]`, `observed_effective_heads[]`, exact bases, `creative_policy_ref` + `_version`, `compiler_version`, `requested_canon_delta_id`, `delta_created_at`, `delta_created_by`, `admitted_at`, `admitted_by`, `input_fingerprint`); `CompilationResult` (`outcome: Literal["SUCCEEDED","NO_CANON_MUTATION","ABSTAINED","CONFLICT","FAILED"]`, `canon_delta_id?`, `canon_delta_payload_hash?`, `diagnostics[]`, `completed_at`, `output_fingerprint`); `CompiledCanonDeltaEvidence` (`compilation_result_id`, `compilation_attempt_id` + `generation`, `canon_delta: CanonDelta` (the exact immutable M5A payload, inline lossless), `canon_delta_payload_hash`, `stored_at`).
- Tables: `narrative_compilation_attempts`, `narrative_compilation_results`, `narrative_compiled_canon_deltas` (one-to-one by `compilation_result_id`), plus ordered association rows for `selected_change_sets`. `UNIQUE (attempt_id, generation)`; a `SUCCEEDED` result has exactly one one-to-one compiled-delta row inserted in the same transaction; `NO_CANON_MUTATION` and non-success results have none (repository-enforced). The compiled-delta row stores the lossless canonical M5A payload inline with its payload-hash algorithm/version and content-schema version; JSONB acceptable only when a strict contract round-trip reproduces the same canonical M5A bytes and hash.
- `hashing.py`: `compute_compilation_input_fingerprint(attempt)` covering every exact semantic input.
- Migration `5c7c4a0e0003` `down_revision = "5c7c4a0e0002"`, additive, compilation tables only. The `NarrativeHandoffAdmission` contract + table land entirely in Task 27 / migration `5c7c4a0e0004`.

- [ ] **Step 1: Write RED tests** — a `SUCCEEDED` `CompilationResult` requires non-null `canon_delta_id` + `canon_delta_payload_hash`; `NO_CANON_MUTATION` / `ABSTAINED` / `CONFLICT` / `FAILED` require null delta fields; a `SUCCEEDED` result without exactly one matching compiled-delta row is rejected by the repository; additive SQLite upgrade/downgrade; the compiled-delta payload round-trips to the same canonical M5A bytes + hash.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_lifecycle.py tests/unit/lib/db/models/test_narrative_lifecycle.py tests/integration/lib/db/migrations/test_alembic_narrative_compilation.py -q
DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic downgrade "$M5C_ALEMBIC_BASE" && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head
uv run python scripts/audit_tests.py --check
git add r2/contracts/narrative_lifecycle.py r2/narrative_lifecycle/hashing.py lib/db/models/narrative_lifecycle.py lib/db/repositories/narrative_lifecycle.py alembic/versions/5c7c4a0e0003_add_narrative_compilation.py tests/unit tests/integration/lib/db
git commit -m "feat(r2): add compilation attempt/result contracts and tables"
```

---

### Task 23: The pure CanonDeltaCompiler

**Files:**
- Create: `r2/narrative_lifecycle/compiler.py`
- Modify: `r2/narrative_lifecycle/__init__.py`
- Test: `tests/unit/r2/narrative_lifecycle/test_compiler.py`

**Interfaces:**
- `CanonDeltaCompiler.compile(output_identity, revision, reviewed_change_sets, conflict_resolutions, exact_canon_base, compiler_policy) -> CanonDeltaCompilation` where `CanonDeltaCompilation = SUCCEEDED(CanonDelta) | NO_CANON_MUTATION(findings) | ABSTAINED(findings) | CONFLICT(findings) | FAILED(findings)`.
- The compiler object has **no** async dependency, clock, random source, provider, database, repository, UoW, writer, acceptance service, or Canon transaction service. `output_identity` carries the attempt-bound `canon_delta_id`, `created_at`, `created_by`; the compiler never reads a clock or generates an opaque ID.
- Validation order (§9.2): (1) supported compiler/policy/change-set/Canon schema versions; (2) exact work scope + revision identity equality; (3) exact Canon base + branch equality; (4) accepted decision/evidence pair equality from the admitted attempt; (5) lineage uniqueness + canonical ordering; (6) source-span + both semantic-effect-key-family coverage validity; (7) pairwise overlap analysis across `CanonMutationEffectKey` and `NarrativeOutcomeEffectKey`; (8) complete applicable Human resolution coverage for every overlap; (9) deterministic mapping of `CanonMutationEffectKey` values only to existing M5A Canon operation contracts; (10) `NO_CANON_MUTATION` when the complete valid resolved selection is outcome-only; (11) recomputed M5A `CanonDelta.payload_hash` for a non-empty mapped operation set.
- The compiler never queries whether decisions are current. It consumes the exact immutable snapshot named by its attempt.
- Conflict rules (§9.3): two selected change sets conflict when normalized source spans overlap or either typed effect-key family collides under the selected policy; a conflict without one exact applicable resolution → `CONFLICT`, no delta. A resolution may choose one input, combine typed non-conflicting effects, or provide a typed replacement effect supported by the policy. Unknown resolution kinds, partial conflict coverage, references outside the selection, or two applicable resolutions for the same conflict fail closed.
- `CanonDelta` construction (§9.4): only operation variants legal for the exact M5A Canon schema (`operation_kinds_for`); every operation derived from a selected `CanonMutationEffectKey` + an explicit policy rule; `NarrativeOutcomeEffectKey` (incl. `THREAD_PAYOFF`) emits zero Canon operations; never an empty `CanonDelta`. Fields: `target_branch_id = NarrativeWorkScope.canon_branch_id`, `base_canon_version_id = exact compilation base`, `source_change_set_refs = canonical selected change_set_ids`, `author_decision_refs = canonical revision/review/resolution decision IDs`, `validation_report_refs = exact compiler finding/report refs`, `created_by = admitted actor`. `payload_hash` is recomputed with the **existing M5A** `compute_canon_delta_hash`; a caller-supplied hash mismatch fails.
- Determinism (§9.5): same input bytes + version selectors → same terminal outcome, ordered findings, ordered operations + operation IDs, source/author decision refs, and payload hash. Wall-clock time, DB order, locale, process hash seed, provider output, or latest state cannot influence compilation. Purely content-addressed subordinate IDs may be derived only under an explicit versioned rule.

- [ ] **Step 1: Write RED tests**

```python
def test_input_permutation_produces_identical_output_and_payload_hash() -> None:
    a = compiler.compile(IDENTITY, REVISION, [cs1, cs2], [], BASE, POLICY)
    b = compiler.compile(IDENTITY, REVISION, [cs2, cs1], [], BASE, POLICY)
    assert a == b


def test_outcome_only_selection_returns_no_canon_mutation_not_empty_delta() -> None:
    result = compiler.compile(IDENTITY, REVISION, [thread_payoff_only_change_set()], [], BASE, POLICY)
    assert isinstance(result, NoCanonMutation)


def test_overlap_without_resolution_is_conflict() -> None:
    result = compiler.compile(IDENTITY, REVISION, [cs_a, cs_a_overlapping], [], BASE, POLICY)
    assert isinstance(result, Conflict) and result.canon_delta is None
```

Also cover: process hash seed / locale / wall-clock changes do not affect output (`PYTHONHASHSEED` sweep); unsupported effect or policy version → deterministic `ABSTAINED`/`FAILED`, never mislabeled `NO_CANON_MUTATION`; partial/stale/foreign/duplicate/unknown resolution fails closed; non-overlapping accepted lineages coexist and compile in canonical order; the delta payload hash equals `compute_canon_delta_hash` output; `source_change_set_refs` / `author_decision_refs` are inside the hashed payload domain (removing either changes the hash); an unsupported `CanonMutationEffectKey` never "best-effort" converts.

- [ ] **Step 2: Run RED → Step 3: Implement the pure compiler → Step 4: GREEN + fitness + commit**

```bash
PYTHONHASHSEED=0 uv run python -m pytest tests/unit/r2/narrative_lifecycle/test_compiler.py tests/unit/r2/test_m5c_architecture_boundaries.py -q
PYTHONHASHSEED=1 uv run python -m pytest tests/unit/r2/narrative_lifecycle/test_compiler.py -q
uv run lint-imports
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/compiler.py r2/narrative_lifecycle/__init__.py tests/unit/r2/narrative_lifecycle/test_compiler.py
git commit -m "feat(r2): add the pure canon delta compiler"
```

---

### Task 24: Compilation admission + atomic compiled-delta recording

**Files:**
- Modify: `r2/narrative_lifecycle/evidence.py`, `r2/narrative_lifecycle/ports.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_compilation_service.py`

**Interfaces:**
- `admit_compilation(command) -> CompilationAttempt`: the Task 13 fail-closed body (`NarrativeAuthorityUnavailableError`) is now **replaced** by the real guard. It admits and persists the attempt while all named decisions are currently effective (§10.1) — the exact current revision acceptance; every named review decision current + effective for its lineage; every selected change set matching that review decision; every required conflict-resolution decision current, effective, and applicable; no unresolved overlap; exact mutual scope + basis equality. The public signature is unchanged from Task 13. The attempt records effective decision IDs + generations observed during the admission transaction. Compilation then runs **outside** the authority transaction over exact immutable inputs.
- `record_successful_compilation(result, canon_delta)`: requires `SUCCEEDED`, recomputes the existing M5A payload hash, inserts the result **and** the exact `CompiledCanonDeltaEvidence` payload atomically (one transaction, keyed one-to-one by `compilation_result_id`), returns an immutable deep copy. The service requires exact hash equality with both the result and the embedded delta. Exact retry compares both complete tuples and writes nothing.
- `record_compilation_without_delta(result)`: accepts exactly `NO_CANON_MUTATION`, `ABSTAINED`, `CONFLICT`, or `FAILED`; rejects populated delta fields or any compiled-delta payload. No public interface records `SUCCEEDED` without its exact durable proposal or attaches a delta to an outcome-only result.
- The pure local compiler has no `OUTCOME_UNKNOWN` result. A crash before result recording leaves a durable attempt with no result; the same exact generation may be recomputed and recorded idempotently. Handoff + recovery reload the persisted payload; rerunning the compiler is an integrity check, not the normative recovery path.

- [ ] **Step 1: Write RED integration tests**

```python
async def test_compilation_admission_fails_when_a_named_review_is_superseded(evidence_service, acceptance_service):
    review = await acceptance_service.review_change_set(accept_command("rv-1", lineage="L"))
    await acceptance_service.review_change_set(supersede_command("rv-2", old_effective="rv-1", lineage="L"))
    with pytest.raises(NarrativeDecisionApplicabilityError):
        await evidence_service.admit_compilation(compilation_command(selected=[("cs-1", review.decision_id)]))


async def test_successful_compilation_bundle_is_atomic_and_restart_reloads_the_payload(evidence_service, fault):
    with fault.before_commit():
        with pytest.raises(InjectedFault):
            await evidence_service.record_successful_compilation(success_result(), CANON_DELTA)
    assert await evidence_service.get_exact_compilation_result(...) is None
    await evidence_service.record_successful_compilation(success_result(), CANON_DELTA)
    reloaded = await evidence_service.get_exact_compiled_delta(result_id="...")
    assert reloaded.canon_delta == CANON_DELTA  # reloaded, not recompiled
```

Also cover: a stale/failed compilation result cannot later be admitted for handoff; a `SUCCEEDED` record with a delta hash mismatching `compute_canon_delta_hash` is rejected; compiler crash leaves the attempt without `OUTCOME_UNKNOWN`; repeated exact computation records one identical result.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_compilation_service.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/evidence.py r2/narrative_lifecycle/ports.py tests/integration/r2/narrative_lifecycle/test_compilation_service.py
git commit -m "feat(r2): admit compilation and record compiled deltas atomically"
```

---

### Task 25: Accepted thread-payoff proof + the M5B accepted-narrative read adapter

**Files:**
- Modify: `r2/contracts/narrative_lifecycle.py`, `r2/narrative/validation.py`
- Create: `r2/narrative_lifecycle/accepted_narrative_adapter.py`
- Modify: `r2/narrative_lifecycle/__init__.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_thread_payoff_outcome.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_accepted_narrative_adapter.py`

**Interfaces:**
- `AcceptedThreadPayoffProof` (§4.3.4: `thread_ref`, `payoff_ref`, `revision_id`, `revision_acceptance_decision_id`, `change_set_id`, `review_decision_id`, `conflict_resolution_decision_ids[]`, `source_spans[]`) — a typed read view, not a new write authority or mutable payoff row.
- `validate_thread_payoff_outcome(proof, *, change_set, effective_decisions) -> NarrativeValidationReport` — a pure exact-input validator introduced only after the M5C-2 decision layer exists. The named `NarrativeChangeSet` must contain the exact typed `THREAD_PAYOFF(thread_ref, payoff_ref)` effect key; every source span must be covered by that immutable change set; all named revision/review/resolution decisions must be applicable and currently effective when new outcome work is admitted. A `promise_payoff_refs` entry, active-thread tag, model claim, or prose substring without this accepted proof yields `SCENE_EXIT_THREAD_UNMET`. Historical replay may resolve the same exact proof without treating it as current authority. F9 creates no second extractor or acceptance path.
- `accepted_narrative_adapter.py` supplies the concrete reader behind M5B's `AcceptedNarrativeReader` protocol. An `accepted_narrative_ref` is a **revision-acceptance decision ID**, not a revision ID, prose hash, or mutable head ID. For a normal M5B context compilation it resolves the exact decision + revision, verifies the decision is the current effective acceptance for its stable work scope, and returns prose plus an authority descriptor binding the exact Canon/Plan/SceneContract/ContextPack bases. Missing/rejected/superseded/corrupt/cross-scope references return the existing indistinguishable not-found result (M5B raises `NarrativeSourceMetadataError`). An exact current record whose descriptor is incompatible with the requested basis reaches M5B's existing visibility filter and is recorded as an omission. Neither path emits `RECENT_ACCEPTED` content. Historical audit uses the separate replay port (§10.2) and is not injectable as M5B's live reader.

- [ ] **Step 1: Write RED tests**

```python
async def test_structural_payoff_without_effective_decisions_fails_outcome_validation() -> None:
    report = validate_thread_payoff_outcome(proof_without_accepted_decisions(), change_set=CS, effective_decisions=set())
    assert "SCENE_EXIT_THREAD_UNMET" in [f.rule_id for f in report.findings]


async def test_adapter_returns_not_found_for_a_superseded_acceptance(adapter, acceptance_service) -> None:
    d1 = await acceptance_service.decide_revision(accept_command("d-1"))
    await acceptance_service.decide_revision(supersede_command("d-2", old_effective="d-1"))
    assert await adapter.get_exact(accepted_narrative_ref=d1.decision_id, project_name=P, user_id=U) is None
```

Also cover: a proof whose `change_set` lacks the exact `THREAD_PAYOFF` key fails; an uncovered source span fails; a wrong-thread/wrong-payoff proof fails; historical replay resolves the same proof but yields no current-authority token; the adapter rejects a prose-hash or head-ID `accepted_narrative_ref`.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + M5B regression + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_thread_payoff_outcome.py tests/integration/r2/narrative_lifecycle/test_accepted_narrative_adapter.py tests/unit/r2/narrative_context/test_compiler.py -q
uv run python scripts/audit_tests.py --check
git add r2/contracts/narrative_lifecycle.py r2/narrative/validation.py r2/narrative_lifecycle/accepted_narrative_adapter.py r2/narrative_lifecycle/__init__.py tests/integration/r2/narrative_lifecycle
git commit -m "feat(r2): validate accepted thread payoffs and serve M5B narrative reads"
```

---

### Task 26: Freeze the M5C-3 checkpoint

**Files:**
- Modify: `pyproject.toml` (compiler purity + no-Canon-repo-from-M5C contracts)
- Create after Codex review: `docs/r2/evidence/R2_M5C_3_REVIEW.md`

- [ ] **Step 1: Verify contracts + freeze**

Import-linter: `r2.narrative_lifecycle.compiler` imports no authority write port, repository, UoW, clock, random, or provider; M5C repositories cannot import or write M5A Canon ORM models; `r2.narrative_lifecycle` does not import `r2.narrative.canon_transaction`.

```bash
git status --short
git add pyproject.toml
git commit -m "test(r2): fence compiler purity and the Canon write boundary"
M5C_3_VERIFIED_HEAD="$(git rev-parse HEAD)"
```

- [ ] **Step 2: Run fresh M5C-3 gates**

```bash
PYTHONHASHSEED=0 uv run python -m pytest -n 4 --dist loadfile tests/unit/r2 tests/unit/lib/db tests/integration/r2/narrative_lifecycle tests/integration/lib/db tests/integration/donor_parity -q
uv run ruff check . && uv run ruff format --check . && uv run basedpyright --warnings && uv run lint-imports && uv run deptry lib server alembic scripts tests r2
uv run python scripts/audit_tests.py --check
uv run python scripts/r2/verify_m5c_scope.py --base "$M5C_2_HANDOFF_HEAD" --head "$M5C_3_VERIFIED_HEAD" --phase impl --checkpoint m5c3
git diff --check "$M5C_2_HANDOFF_HEAD".."$M5C_3_VERIFIED_HEAD"
git status --short
```

`$M5C_2_HANDOFF_HEAD` here means the practical M5C-2/M5C-3 code boundary (`3970f024`, Task 21's last commit — M5C-2's own Codex-review handoff never happened, so no `R2_M5C_2_REVIEW.md` commit exists to name instead; see the M5C-2 status note in checkpoint M5C-2's header). `tests/donor_parity` was renamed `tests/integration/donor_parity` before Task 21; this step never picked up that rename until Task 26. `verify_m5c_scope.py` needed a fresh `m5c3` checkpoint entry (mirroring `m5c2`'s) before this step could run at all — added in Task 26 alongside the `pyproject.toml` contracts, both amendments on the same amendable-tooling basis as Task 21's.

- [ ] **Step 3: Codex review + evidence-only handoff**

Codex reviews compiler determinism, `NO_CANON_MUTATION` vs abstain/fail discipline, M5A payload-hash reuse, atomic compiled-delta recording, and the thread-payoff proof binding. After `APPROVED`, Codex writes `R2_M5C_3_REVIEW.md`.

```bash
git add docs/r2/evidence/R2_M5C_3_REVIEW.md
git commit -m "docs(r2): approve M5C-3 verified head"
M5C_3_HANDOFF_HEAD="$(git rev-parse HEAD)"
```

Expected: handoff diff is exactly `docs/r2/evidence/R2_M5C_3_REVIEW.md`. Task 27 starts from this handoff only.

---

## Checkpoint M5C-4 — M5A handoff admission and acceptance corpus

*Atomic currentness receipt + authenticated existing-M5A path + combined M5 v2 exit fixture. M5C adds no second Canon approval service.*

### Task 27: NarrativeHandoffAdmission contract + ORM + approval-binding fingerprint

**Files:**
- Modify: `r2/contracts/narrative_lifecycle.py`, `r2/narrative_lifecycle/hashing.py`
- Modify: `lib/db/models/narrative_lifecycle.py`, `lib/db/repositories/narrative_lifecycle.py`
- Create: `alembic/versions/5c7c4a0e0004_add_narrative_handoff_admission.py` (`down_revision = "5c7c4a0e0003"`, additive; `narrative_handoff_admissions` + its `observed_heads` association table). **Migration `5c7c4a0e0003` is inside the frozen M5C-3 HEAD and is not touched here.**
- Test: `tests/unit/r2/contracts/test_narrative_lifecycle.py`, `tests/unit/r2/narrative_lifecycle/test_hashing.py`
- Test: `tests/integration/lib/db/migrations/test_alembic_narrative_handoff_admission.py`
- Test: `tests/integration/lib/db/repositories/test_narrative_lifecycle.py`

**Interfaces:**
- `NarrativeHandoffAdmission` (§11.1): `admission_id`, `work_scope`, `compilation_attempt_id` + `generation`, `compilation_result_id`, `canon_delta_id`, `canon_delta_payload_hash`, `canon_commit_approval_ref`, `canon_commit_approval: CanonCommitApproval` (exact immutable inline lossless copy), `canon_commit_approval_fingerprint`, `canon_commit_approval_fingerprint_algorithm: Literal["sha256"]`, `canon_commit_approval_fingerprint_version: Literal["r2-m5c-canon-approval-binding-v1"]`, `revision_acceptance_decision_id`, `review_decision_ids[]`, `conflict_resolution_decision_ids[]`, `observed_heads[]: {head_family, logical_key, effective_decision_id, effective_generation, decision_generation}`, `base_canon_version_id`, `actor_id`, `admitted_at`, `canonical_identity_hash`.
- `compute_canon_approval_binding_fingerprint(approval: CanonCommitApproval) -> str` — the declared versioned canonical hash, aware timestamps normalized to UTC, over **every** existing M5A approval field: `approval_ref`, `canon_delta_id`, `payload_hash`, payload-hash algorithm/version, content-schema version, `project_name`, `user_id`, `approved_by`, `approved_at`, `status`. Changing the algorithm/version fails closed.
- Table `narrative_handoff_admissions`: `admission_id` PK, opaque + idempotent (same ID/full tuple → original receipt even after later supersession; same ID/different tuple → identity conflict via `NarrativeDecisionIdentityConflictError`); the exact M5A `CanonCommitApproval` payload + recomputable fingerprint stored in the same immutable row/aggregate; unique ordered association rows for `observed_heads`; no cascading delete. JSONB acceptable only when a strict M5A contract round-trip reproduces the same canonical approval bytes + fingerprint.

- [ ] **Step 1: Write RED tests**

```python
def test_approval_binding_fingerprint_covers_every_m5a_field() -> None:
    base = compute_canon_approval_binding_fingerprint(APPROVAL)
    for field in ("approval_ref", "canon_delta_id", "payload_hash", "content_schema_version",
                  "project_name", "user_id", "approved_by", "status"):
        assert base != compute_canon_approval_binding_fingerprint(APPROVAL.model_copy(update={field: MUTATED[field]}))
    assert base != compute_canon_approval_binding_fingerprint(
        APPROVAL.model_copy(update={"approved_at": APPROVAL.approved_at + timedelta(seconds=1)}))


async def test_same_admission_id_with_a_changed_approval_field_is_an_identity_conflict(repo) -> None:
    await repo.insert_handoff_admission(admission("adm-1", approval=APPROVAL))
    with pytest.raises(NarrativeDecisionIdentityConflictError):
        await repo.insert_handoff_admission(admission("adm-1", approval=APPROVAL.model_copy(update={"approved_by": "x"})))
```

Also cover: the fingerprint version literal is fixed; the inline approval round-trips to identical canonical bytes; `extra="forbid"`; aware-UTC on `admitted_at` and `approved_at`.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/unit/r2/contracts/test_narrative_lifecycle.py tests/unit/r2/narrative_lifecycle/test_hashing.py tests/integration/lib/db/migrations/test_alembic_narrative_handoff_admission.py tests/integration/lib/db/repositories/test_narrative_lifecycle.py -q
DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic downgrade "$M5C_ALEMBIC_BASE" && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head
uv run python scripts/audit_tests.py --check
git add r2/contracts/narrative_lifecycle.py r2/narrative_lifecycle/hashing.py lib/db/models/narrative_lifecycle.py lib/db/repositories/narrative_lifecycle.py alembic/versions/5c7c4a0e0004_add_narrative_handoff_admission.py tests/unit tests/integration/lib/db
git commit -m "feat(r2): add the narrative handoff admission contract"
```

---

### Task 28: NarrativeAcceptanceService.admit_canon_handoff

**Files:**
- Modify: `r2/narrative_lifecycle/acceptance.py`, `r2/narrative_lifecycle/ports.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_handoff_admission.py`

**Interfaces:**
- `admit_canon_handoff(command, *, authenticated_principal, canon_commit_approval: CanonCommitApproval) -> AdmittedNarrativeHandoff`. The service resolves authorization for the admission via the injected `NarrativeShowrunnerAuthorityPort` (`authorize_initial_decision` / `authenticate_exact_retry`) — no caller-supplied authorization object. Transaction order (§11.2): (1) validate + deep-copy the exact existing M5A `CanonCommitApproval` input; (2) begin one fresh short Narrative transaction; (3) resolve exact admission retry **before** testing currentness; (4) lock the revision, selected change-set, and required conflict heads in canonical order; (5) load the exact persisted `CompiledCanonDeltaEvidence` and verify it against the successful compilation result, attempt, scope, exact bases, and all effective decisions; (6) recompute the delta payload hash **and** the complete approval fingerprint and require the approval to bind that exact delta, scope, hash/schema versions, actor, status, and timestamp; (7) verify each locked projection against its typed authoritative chain, prove every recorded effective pointer still equals the named decision, and prove every resolution remains applicable; (8) append the immutable admission receipt + exact approval payload atomically; (9) commit once. **No Canon row is locked or written in this transaction.**
- `AdmittedNarrativeHandoff` contains the immutable admission receipt plus exact deep copies of the persisted `CanonDelta` and persisted `CanonCommitApproval` — a convenience result, not another durable authority contract. The facade never substitutes a caller-held, recompiled, reconstructed, or freshly issued tuple after admission.
- Frozen currentness (§11.3): a Narrative decision committing **before** receipt insertion is observed under the locked heads and blocks admission; a supersession committing **after** the admission transaction does not retroactively invalidate the receipt or an already-admitted M5A action. Not currentness-through-Canon-commit; no cross-authority fence/lease/distributed transaction. An admission is reusable only for the exact bound `CanonDelta` and the exact existing M5A approval/retry lineage; it cannot authorize another delta, recompilation result, Canon base, M5A approval tuple, or fresh approval action.

- [ ] **Step 1: Write RED integration tests**

```python
async def test_supersession_before_admission_blocks_receipt_creation(acceptance_service):
    await acceptance_service.review_change_set(supersede_command("rv-2", old_effective="rv-1", lineage="L"))
    with pytest.raises(NarrativeHandoffConflict):
        await acceptance_service.admit_canon_handoff(handoff_command(review_decision_id="rv-1"),
                                                     authenticated_principal=showrunner_principal(),
                                                     canon_commit_approval=APPROVAL)


async def test_supersession_after_committed_admission_does_not_invalidate_the_receipt(acceptance_service):
    admitted = await acceptance_service.admit_canon_handoff(
        handoff_command(), authenticated_principal=showrunner_principal(), canon_commit_approval=APPROVAL)
    await acceptance_service.decide_revision(supersede_command("d-2", old_effective=admitted.revision_acceptance_decision_id))
    again = await acceptance_service.admit_canon_handoff(
        handoff_command(admission_id=admitted.admission_id),
        authenticated_principal=showrunner_principal(), canon_commit_approval=APPROVAL)
    assert again.admission_id == admitted.admission_id  # exact retry returns the original immutable receipt
```

Also cover: same admission ID with another delta/decision tuple fails; same admission ID or receipt with another M5A approval ref or any changed approval field fails; changing the approval-binding hash algorithm/version fails closed; a stale or failed compilation result cannot be admitted; a Canon delta hash mismatch blocks admission; supersession concurrent with validation cannot land invisibly between a naked read and receipt insertion (PostgreSQL, `uses_db`).

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_handoff_admission.py -q
DATABASE_URL="$POSTGRES_TEST_URL" uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_handoff_admission.py -q -k concurrent
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/acceptance.py r2/narrative_lifecycle/ports.py tests/integration/r2/narrative_lifecycle/test_handoff_admission.py
git commit -m "feat(r2): admit the atomic narrative-to-canon handoff"
```

---

### Task 29: Authenticated M5A handoff facade

**Files:**
- Create: `server/services/narrative_canon_handoff.py`
- Test: `tests/integration/server/services/test_narrative_canon_handoff.py`

**Interfaces:**
- The authenticated facade requires an authenticated principal, the exact caller-supplied `NarrativeWorkScope`, one project-scoped Human Showrunner capability proven through the existing `NarrativeShowrunnerAuthorityPort`, one exact scoped `NarrativeHandoffAdmission`, the exact `CanonDelta` bound by that receipt, and the exact persisted `CanonCommitApproval` whose complete payload, reference, and fingerprint are bound by that receipt. It never drives a commit from the repository's global ID-only collision lookup. It then calls the **existing** `CanonTransactionService.commit(*, delta, approval, project_name, user_id, now)`. It constructs the M5A approval **before** Narrative admission and passes it to the admission transaction; on the initial request or after process restart it reloads the exact durable delta + approval from the committed admission before calling or retrying M5A.
- M5A independently verifies the approval, recomputes the delta hash, locks the Canon branch, resolves exact Canon retry, checks the base, validates the candidate Canon view, appends the accepted delta + version, advances the branch head, and updates its projection atomically. If Canon advanced before commit, M5A returns its existing base conflict; the Narrative admission stays immutable but a new delta + admission are required. Narrative supersession after admission is not substituted for M5A base OCC.
- The facade does **not** create a second Canon approval service and constructs/receives only the existing M5A `CanonCommitApproval`.

- [ ] **Step 1: Write RED integration tests**

```python
async def test_facade_reloads_the_durable_delta_and_approval_after_restart(facade, admitted_handoff):
    result = await facade.commit_from_admission(
        admission_id=admitted_handoff.admission_id,
        scope=admitted_handoff.admission.work_scope,
        authenticated_principal=SHOWRUNNER,
        now=NOW,
    )
    assert result.version.committed_delta_id == admitted_handoff.canon_delta_id


async def test_canon_head_movement_after_admission_is_rejected_by_existing_m5a_occ(facade, admitted_handoff, canon):
    await canon.commit(unrelated_delta())  # advances the branch head
    with pytest.raises(CanonBaseVersionConflict):
        await facade.commit_from_admission(
            admission_id=admitted_handoff.admission_id,
            scope=admitted_handoff.admission.work_scope,
            authenticated_principal=SHOWRUNNER,
            now=NOW,
        )
```

Also cover: an admission receipt is not accepted as a Canon approval (M5A approval validation still runs); reusing an admission with another M5A approval tuple fails the admission fingerprint check before Canon commit; M5A exact retry remains governed by its existing delta/approval identity; a response-lost M5A call retries only with the exact persisted `AdmittedNarrativeHandoff` delta + approval tuple.

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + fitness + commit**

```bash
uv run python -m pytest tests/integration/server/services/test_narrative_canon_handoff.py tests/integration/r2/narrative/test_canon_transaction.py tests/unit/r2/test_m5c_architecture_boundaries.py -q
uv run lint-imports
uv run python scripts/audit_tests.py --check
git add server/services/narrative_canon_handoff.py tests/integration/server/services/test_narrative_canon_handoff.py
git commit -m "feat(server): connect approved narrative admissions to the M5A commit path"
```

---

### Task 30: Complete the NarrativeLifecycleIntegrityChecker

**Files:**
- Modify: `r2/narrative_lifecycle/integrity.py`, `r2/narrative_lifecycle/__init__.py`
- Test: `tests/integration/r2/narrative_lifecycle/test_integrity.py` (complete)

**Interfaces:**
- Extend the checker to verify without mutating authority (§12): each evidence ID maps to one full immutable tuple; prose + semantic hashes recompute; attempt/result generation + unique-result constraints hold; every change set belongs to its exact successful extraction result; identity-registry rows match exactly one typed decision family; typed decision predecessor chains are acyclic + scope-consistent; latest pointers + decision generations rebuild from all decisions; effective pointers + generations rebuild under action semantics; change-set + conflict head keys match their revision/lineage decisions; every historical conflict-resolution decision validates against the immutable evidence, decision predecessors, and effective reviewed inputs that existed at its append point (only **current** applicability additionally requires the resolution to be the effective conflict head with every named review currently effective); every successful compilation result owns one exact durable compiled-delta payload and every non-success result owns none; compilation results recompute from their exact attempts + compiler version, with the recomputed output compared to — not substituted for — the persisted delta; `NO_CANON_MUTATION` results prove a complete valid outcome-only effect set and own no compiled-delta row; each original decision authorization still binds the stored actor/scope/family/action/decision-ID/subject/command-fingerprint (retry-authentication timestamps are not historical decision evidence); handoff admissions bind successful results, exact persisted delta hashes, and the exact lossless M5A approval payload/reference/fingerprint; no head or receipt points to missing or cross-scope evidence.
- Repair requires an explicit offline procedure + evidence; M5C implementation does **not** authorize running it in production.

- [ ] **Step 1: Write RED tests** — one adversarial corruption per bullet above; each yields a specific integrity finding and no mutation. Include: head deleted + rebuilt yields identical logical heads/cardinalities; a corrupt cached projection is not trusted; a recomputed compilation output that differs from the persisted delta is an integrity failure (neither proceeds automatically).

- [ ] **Step 2: Run RED → Step 3: Implement → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/integration/r2/narrative_lifecycle/test_integrity.py -q
uv run python scripts/audit_tests.py --check
git add r2/narrative_lifecycle/integrity.py r2/narrative_lifecycle/__init__.py tests/integration/r2/narrative_lifecycle/test_integrity.py
git commit -m "feat(r2): verify and rebuild narrative lifecycle integrity"
```

---

### Task 31: Combined M5 v1/v2 acceptance corpus + adversarial mutation matrix

**Files:**
- Create: `tests/fixtures/r2/m5c_narrative_corpus.py`
- Modify: `tests/fixtures/r2/__init__.py`
- Create: `tests/integration/r2/test_m5c_acceptance.py`
- Modify: `tests/unit/r2/test_m5c_architecture_boundaries.py`

**Interfaces:**
- `m5c_narrative_corpus.py` extends the existing combined M5 narrative corpus (§16.9) with at least: the accepted M5B v1 corpus replayed byte-for-byte under its original selectors; one v2 NarrativePlan containing both unchanged v1 scenes and upgraded v2 scenes; one directional relationship Fact + entry/exit relationship constraints over exact effective instants; one thread opened in presentation order, omitted from an intermediate unrelated scene, carried across a story-time jump, resolved once by an exact payoff ref; one exact accepted revision/change-set proof for that payoff **and** one structurally valid but unaccepted payoff that fails outcome validation; one no-POV `AUTHOR_DRAFT` scene passing only the SceneContract half (blocked overall) and one otherwise-identical scene denied by that half; R9 exact-reference + R10 normalized-duplicate regression cases; one accepted revision producing multiple non-overlapping change-set lineages; one rejected alternative leaving an existing effective selection intact; one overlap resolved explicitly by a Human resolution lineage; one unresolved ambiguity producing no delta; one historical replay of a superseded revision + decision; one extraction `OUTCOME_UNKNOWN` case proving late-success rejection + continuation only through a new generation; one compilation crash/recompute case; one supersession-before-admission race + one supersession-after-admission case; one Canon-base race rejected by M5A.
- `test_m5c_acceptance.py` drives the corpus through the **real public interfaces** (`NarrativeLifecycleEvidenceService`, `NarrativeAcceptanceService`, `CanonDeltaCompiler`, `server/services/narrative_canon_handoff.py`, existing M5A `CanonTransactionService`) and asserts the §16.8 adversarial-mutation table row by row.
- Each `AdversarialMutation` entry declares **one** typed expectation, not just an exception — because many §16.8 rows are proven by an outcome or a finding, not a raise:
  - `expected_error: type[Exception]` — e.g. "Reuse decision ID with changed receipt" → `NarrativeDecisionIdentityConflictError`; "Compile a superseded decision by ID" → `NarrativeDecisionApplicabilityError`;
  - `expected_outcome: str` — e.g. "Resolve overlap from model prose without Human decision" → compiler returns `CONFLICT` (no delta); an outcome-only selection → `NO_CANON_MUTATION`;
  - `expected_finding: str` — e.g. "Serialize empty/default v2 fields into a v1 scene" / "recompute a v1 golden hash" → the byte/hash compatibility gate reports a specific finding id; "Head row points to a missing decision" → `NarrativeLifecycleIntegrityChecker` finding, no mutation;
  - `expected_no_write: bool` — asserts row counts are unchanged after the mutation is applied.
  The harness dispatches on which field is set. Every §16.8 row maps to exactly one entry.

- [ ] **Step 1: Write the corpus + RED acceptance test**

```python
@pytest.mark.parametrize("mutation", ADVERSARIAL_MUTATIONS, ids=lambda m: m.id)  # the full §16.8 table
async def test_each_adversarial_mutation_produces_its_required_result(m5c_pipeline, mutation) -> None:
    if mutation.expected_error is not None:
        with pytest.raises(mutation.expected_error):
            await mutation.apply_and_run(m5c_pipeline)
        return
    result = await mutation.apply_and_run(m5c_pipeline)
    if mutation.expected_outcome is not None:
        assert result.outcome == mutation.expected_outcome
    if mutation.expected_finding is not None:
        assert mutation.expected_finding in {f.rule_id for f in result.findings}
    if mutation.expected_no_write:
        assert m5c_pipeline.row_counts_unchanged()
```

- [ ] **Step 2: Run RED → Step 3: Build the corpus + wire the real pipeline → Step 4: GREEN + commit**

```bash
uv run python -m pytest tests/integration/r2/test_m5c_acceptance.py -q
uv run python scripts/audit_tests.py --check
git add tests/fixtures/r2/m5c_narrative_corpus.py tests/fixtures/r2/__init__.py tests/integration/r2/test_m5c_acceptance.py tests/unit/r2/test_m5c_architecture_boundaries.py
git commit -m "test(r2): accept the combined M5 v1/v2 narrative corpus"
```

---

### Task 32: Final verification, R2-DEC-031 evidence bundle, and clean handoff

**Files:**
- Create after Codex review: `docs/r2/evidence/R2_M5C_FINAL_VERIFICATION.md`

- [ ] **Step 1: Freeze the final implementation head + re-resolve the pinned preflight values**

```bash
git status --short
M5C_FINAL_VERIFIED_HEAD="$(git rev-parse HEAD)"
# from R2_M5C_STARTING_STATE.json, pinned in Task 0:
M5C_ALEMBIC_BASE="$(uv run python -c 'import json;print(json.load(open("docs/r2/evidence/R2_M5C_STARTING_STATE.json"))["m5c_alembic_base"])')"   # == 5b7c4a0e0001
: "${POSTGRES_TEST_URL:?set POSTGRES_TEST_URL to the isolated PostgreSQL 18 test DB pinned in Task 0}"
psql "$(printf %s "$POSTGRES_TEST_URL" | sed 's#+asyncpg##')" -c "SELECT version(); SELECT current_database(), current_user;"
```

Expected: `POSTGRES_TEST_URL` is set and still resolves to the same PostgreSQL 18 isolated DB/identity recorded in `R2_M5C_STARTING_STATE.json`; `M5C_ALEMBIC_BASE` is `5b7c4a0e0001`.

- [ ] **Step 2: Regenerate all evidence from the exact clean final head**

```bash
uv run ruff check . && uv run ruff format --check .
uv run basedpyright --warnings
uv run lint-imports
uv run deptry lib server alembic scripts tests r2
PYTHONHASHSEED=0 uv run python -m pytest -n 4 --dist loadfile
uv run python scripts/audit_tests.py --check
DATABASE_URL="$POSTGRES_TEST_URL" uv run python -m pytest -m "uses_db and not sqlite_only" -q
DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head \
  && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic downgrade "$M5C_ALEMBIC_BASE" \
  && DATABASE_URL="$POSTGRES_TEST_URL" uv run alembic upgrade head
uv run python scripts/r2/verify_m5c_scope.py --base "$M5C_3_HANDOFF_HEAD" --head "$M5C_FINAL_VERIFIED_HEAD" --phase impl
git diff --check "$M5C_DOCUMENT_MATERIALIZATION_HEAD".."$M5C_FINAL_VERIFIED_HEAD"
```

Expected: all exit 0. The migration round-trip runs against the isolated `POSTGRES_TEST_URL`, never the implicit default. Record exact pass/skip counts, the `SELECT version()` string + DB/user identity, per-checkpoint head lineage, v1/v2 schema/hash selectors + golden vectors, mixed-version plan fixtures, scope allowlist, and graph generation/coverage.

- [ ] **Step 3: Assemble the acceptance-counter block (§16.9)**

Prove, from fresh evidence at `M5C_FINAL_VERIFIED_HEAD`, every counter is `0`:

```text
v1 Scene/Plan hash regressions           0
relationship constraint violations       0
thread lifecycle violations              0
unproven thread payoff acceptance        0
unauthorized omniscient authoring        0
unauthorized Narrative decisions         0
stale decision consumption               0
unresolved overlap compilation           0
compiler nondeterminism                  0
Narrative-to-Canon authority bypass      0
failed transaction corruption            0
cross-scope evidence leakage             0
donor parity regressions                 0
unverified material donor behavior       0
required skips                           0
```

- [ ] **Step 4: Assemble the R2-DEC-031 donor evidence bundle (§16.9)**

- baseline manifest entries reproduce the exact revisions/paths/source SHA-256 from spec §2.4 + an inventory of every selected and explicitly excluded donor behavior;
- Huohuo port: ~25–35 branch/error cases + ≥10 prose fixtures covering every selected pure parser/normalizer branch (malformed headers, orphan blocks, empty input, prose shaped like a false structured record); test-only Node harness runs the unmodified pinned source in its source-tree context after verifying revision + SHA-256, exercising the seven selected pure exports on every applicable case;
- Novel Studio port: ~8–10 cases covering rule hit/miss + empty/hard-only/soft-only/combined/severity/stable rule-ID merge ordering; its Node harness runs the pinned TS source on the same fixtures;
- Node baseline and Python port consume the same canonical JSON/JSONL fixture records and emit normalized per-case output/error records; verification compares exact structured/string output, error-vs-success behavior, deterministic repeat output, and every applicable `R2-DEC-031` dimension; any intentional improvement is recorded + backed by an explicit regression fixture;
- the ports also pass M5C proposal-only, determinism, failure-safety, provider-neutrality, and no-authority-import fitness tests.

Missing Node baseline execution, uncovered material behavior, unexplained mismatched output, or evidence not bound to `M5C_FINAL_VERIFIED_HEAD` blocks M5C acceptance. `R2-DEC-031` material behavior/parity gaps have no waiver.

- [ ] **Step 5: Codex review + final evidence-only handoff**

Codex reviews the whole M5C surface at the frozen head against the spec's review gates (§17) and out-of-scope list (§19). After `APPROVED`, Codex writes `R2_M5C_FINAL_VERIFICATION.md` (clean verified head, full commands + counts, PostgreSQL identity, acceptance counters, `R2-DEC-031` bundle, combined-corpus result, per-mutation outcomes, and a clean verified-head → evidence-only handoff).

```bash
git add docs/r2/evidence/R2_M5C_FINAL_VERIFICATION.md
git commit -m "docs(r2): record the M5C final verification"
M5C_FINAL_HANDOFF_HEAD="$(git rev-parse HEAD)"
git status --short
```

Expected: `git diff --name-only "$M5C_FINAL_VERIFIED_HEAD".."$M5C_FINAL_HANDOFF_HEAD"` returns exactly `docs/r2/evidence/R2_M5C_FINAL_VERIFICATION.md`. No push, merge, migration, or production step follows without separate explicit Human approval (spec §17.8).

---

## Self-Review

Checked against the spec with fresh eyes:

**1. Spec coverage.** §1 goal → Tasks 10–32. §2.2 frozen decisions 1–25 → decisions 1–3/5/6 (Tasks 15–19), 4 (Task 15 canonical identity), 7 (Task 16 genesis + Task 21), 8/11 (Task 19), 9/15/22 (Tasks 27–28), 10 (Tasks 13/24), 12 (Task 18 authority table), 13 (Global Constraints + Task 16), 14 (Task 13), 16 (Tasks 7–9/32), 17 (Tasks 1–2), 18–19 (Tasks 4–5/25), 20/25 (Task 6), 21 (Tasks 7–9), 23 (Task 15), 24 (Tasks 10/23). §3 four checkpoints + 1A/1B subgates → checkpoint headers. §4.1–4.2 scope/bindings → Task 10. §4.3 F9 → Tasks 1–6. §5 evidence contracts → Tasks 10/22/27. §6 decision authority → Tasks 15–19. §7 persistence/transactions → Tasks 12/16 + §7.2 genesis in Task 16/19. §8 services/ports → Tasks 13/18/25. §9 pure compiler → Task 23. §10 currentness/replay → Tasks 20/24/25. §11 handoff admission → Tasks 27–29. §12 integrity → Tasks 20/30. §13 error taxonomy → Task 10. §14 security/scope → Global Constraints + per-task predicates. §15 module boundaries → File Map + Tasks 9/14/21/26. §16 acceptance strategy → Tasks 31–32. §17 review gates → checkpoint freezes + Codex handoffs. §18 risks → covered by the fitness tasks. §19 out of scope → no task adds a Canon approval service, CreativePolicy authority, second extractor, event-sourcing framework, or migration/push step. Gaps: none identified.

**2. Placeholder scan.** No "TBD"/"handle edge cases"/"similar to Task N"/"add validation" left. Every code step carries a code block or an exact command; test-matrix enumerations are explicit ("Also cover: …"). Representative-snippet density matches the accepted M5B plan house style.

**3. Type consistency.** `NarrativeWorkScope`, `NarrativeDecisionAuthorization`, `NarrativeDecisionRetryAuthentication`, `NarrativeDecisionReceipt`, `ConflictResolutionLineage`, `CanonDeltaCompilation`, `CompiledCanonDeltaEvidence`, `NarrativeHandoffAdmission`, `AdmittedNarrativeHandoff`, `AcceptedThreadPayoffProof`, `NarrativeAuthorityUnavailableError` are each defined once (Tasks 10/13/15/22/25/27) and referenced consistently afterward. `relationship_fact_predicate`, `validate_plan_thread_lifecycle`, `validate_thread_payoff_outcome`, `compute_canon_approval_binding_fingerprint`, `compute_decision_canonical_identity_hash`, `get_decision_by_id` keep one name throughout. Public `NarrativeAcceptanceService` decision methods take `(command, *, authenticated_principal[, canon_commit_approval])` everywhere — no `authorization=` anywhere. Selector strings (`r2-scene-contract-content-v2`, `r2-narrative-plan-v2`, `r2-relationship-fact-key-v1`, `r2-m5c-canon-approval-binding-v1`) match the spec verbatim. Migration chain `5b7c4a0e0001 → 5c7c4a0e0001 → 0002 → 0003 → 0004` is linear and additive; each migration is created in exactly one task and never edited by a later checkpoint.

**4. Review-round-1 fixes (2026-09-09).** Six `M5C_IMPLEMENTATION_PLAN_REVIEW_CHANGES_REQUIRED` blockers resolved: (1) Task 17 — retry resolution (`get_decision_by_id`) is now step 2, strictly before any head INSERT / `FOR UPDATE`; a retry performs zero head/identity/decision writes even when the head is missing. (2) Task 13 — `admit_extraction()` / `admit_compilation()` **fail closed** with `NarrativeAuthorityUnavailableError` until the M5C-2 authority layer wires the real current-effective guard (Task 20 / Task 24); no interim "exists-only" semantics at a reviewed checkpoint. (3) Migration split — `5c7c4a0e0003` = compilation only, `5c7c4a0e0004` = handoff admission, created fresh in Task 27; no later checkpoint edits a migration inside a frozen HEAD. (4) Task 0 — integration-base disagreement (`origin/r2/main` / manifest / project-decision / worktree) is a **STOP**, not a silent pick; `R2_M5C_DOCUMENT_APPROVAL.json` is a Human-materialized **precondition** the plan only verifies. (5) Task 18 — the public decision surface takes `authenticated_principal` only; the service calls `NarrativeShowrunnerAuthorityPort` itself; no caller-supplied `NarrativeDecisionAuthorization`; Task 21 asserts this via `inspect.signature`. (6) Task 0 — `M5C_ALEMBIC_BASE=5b7c4a0e0001` and an isolated PostgreSQL 18 `POSTGRES_TEST_URL` (with `SELECT version()` + DB/user identity + clean-ownership marker) are pinned in `R2_M5C_STARTING_STATE.json`; every `alembic` round-trip in the plan runs against that URL, and Task 32's downgrade target is `$M5C_ALEMBIC_BASE`. Plus three HIGH: Task 31 mutation entries carry a typed `expected_error | expected_outcome | expected_finding | expected_no_write`; per-task `alembic` commands pinned to `$POSTGRES_TEST_URL`; Task 21's concurrency test spells out an `asyncio.Barrier(2)` + injected `on_head_serialization` hook instead of a `...` body.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`; fresh subagent per task + two-stage review.

**2. Inline Execution** — execute tasks in this session with checkpoints for review. REQUIRED SUB-SKILL: `superpowers:executing-plans`; batch execution with checkpoints.

Before either: complete Task 0's document-approval manifest and prepare the `feat/r2-m5c-narrative-lifecycle` worktree over the accepted `origin/r2/main` base. Do not cross a checkpoint gate (M5C-1A → 1B → 2 → 3 → 4) until Codex records an `APPROVED` verdict.
