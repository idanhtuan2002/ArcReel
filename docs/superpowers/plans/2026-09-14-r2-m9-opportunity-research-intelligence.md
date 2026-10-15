# R2-M9 Opportunity and Research Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use `superpowers:test-driven-development` for every behavior change.

**Goal:** Deliver evidence-first opportunity discovery, policy-gated source acquisition, cohort-isolated candidate assessment and Human Greenlight into M8 Canvas without creating a second factual, learning or production authority.

**Architecture:** One M9 deep module inside ArcReel stores append-only metadata in PostgreSQL and retention-sensitive content behind an erasable evidence-store port. Provider-neutral acquisition, lossless normalization and policy-bound signal folds produce M9-owned candidate revisions; Human Greenlight and typed bridges are the only transitions into M8 Canvas and Factual Authority.

**Tech Stack:** Python 3.12+, Pydantic 2.12+, SQLAlchemy 2.0 async, Alembic, PostgreSQL, FastAPI 0.138+, React 19, TypeScript, Zustand 5, Vitest 4, Playwright, axe-core, pytest, ruff, basedpyright, import-linter and deptry.

**Spec:** `docs/superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md`

**ADR:** `docs/adr/0081-m9-evidence-first-opportunity-intelligence.md`

**Research:** `docs/research/2026-09-14-r2-m9-opportunity-research-intelligence.md`

**Design validation:** `docs/research/2026-09-15-r2-m9-design-validation.md`

**Execution contract:** `docs/r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json`

## Global Constraints

- Implementation starts only from the acceptance commit for `R2_M9_PREREQUISITE_ACCEPTANCE.json`; its parent is a clean descendant base binding the independently accepted M8 implementation, the accepted M9 design and one Alembic head. The M9-A **A0-preflight gate** exits before production-file writes with `M9_DESIGN_NOT_ACCEPTED`, `M9_M8_IMPLEMENTATION_NOT_ACCEPTED` or `M9_REQUIRED_EVIDENCE_MISSING` when that chain is absent. The durable Factual Authority (FA-1) is required at the M9-D release gate; M9-D stops with `M9_FACTUAL_AUTHORITY_UNAVAILABLE` without it (V2 revalidation 2026-10-15). **Task A0 implementation** begins only after that gate passes.
- ADR-0081 and the M9 design must be independently accepted with exact SHA-256 identities before M9-A. Proposed documents and this plan authorize planning only.
- ArcReel remains the runtime host; PostgreSQL remains the metadata authority store. `SnapshotEvidenceStore` is an erasable content seam, not a second metadata authority.
- Public contracts are frozen extra-field-forbid Pydantic v2 models and reuse the exact accepted M8 canonical JSON and digest implementation. Semantic seam drift stops `POST_M8_BASE_SEAM_CHANGED`.
- Every public read and mutation scopes by `(user_id, project_name)`; authenticated principal equals `actor_id`; foreign and unknown identities are indistinguishable.
- Every mutation uses `(user_id, actor_id, operation, command_id)`, exact request-digest replay and expected-version CAS. The normative lock order in spec §9 is unchanged.
- Custodian mutations use the spec §9 preflight/authorize/command-key-guard/finalize protocol. Authorization leases bind exact command/subject/policy, admit within 30 seconds and are replay-safe across concurrent first calls and crash recovery.
- Every committed mutation emits an outbox event in the same transaction. Logs/events contain IDs, versions and digests rather than provider payloads or tokens; metric labels are limited to source kind, operation, state and stop code.
- Provider credentials remain opaque host-owned references. Manual import is the only enabled initial source; network adapters stay dormant or unavailable until an exact capability grant permits their account, operation, purpose, data class, retention and deletion behavior.
- Retention-sensitive identities, values, results and assessments live behind opaque evidence-store refs. PostgreSQL keeps only immutable metadata and policy-permitted non-reversible proof digests.
- Western generic/factual and native-language `zh-shuang` use separate profile lineages, corpora, calibrations and qualified reviewers. Cross-cohort borrowing fails `M9_COHORT_LEAKAGE`.
- Donor functionality is accepted only through exact-pin same-fixture evidence. Every applicable correctness, determinism, failure-safety, integrity, observability, performance and resource row is `PARITY` or `IMPROVED`; required skips and material unknowns are empty.
- Tests use injected clocks/UUIDs, deterministic fixtures and real disposable PostgreSQL for migration, row locking, CAS and concurrency. A SQLite-only result cannot prove those properties.
- Every behavior task follows RED → minimum implementation → GREEN → affected regression → test audit → owned-path commit. A zero-test selection fails the task.
- Each packet ends at a clean candidate evidence HEAD and waits for independent Codex review. Claude Code does not begin the next packet while review is pending or rejected.
- M9 design acceptance additionally requires both sealed reviews to validate
  against `R2_M9_DESIGN_REVIEW.schema.json` and the cross-record verifier in
  `scripts/r2/verify_m9_design_acceptance.py` to return no errors. Acceptance
  schema validation alone is not sufficient.
- The acceptance custodian runs
  `uv run python scripts/r2/verify_m9_design_acceptance.py` from the proposed
  acceptance commit. The command must resolve all candidate/review evidence
  from Git objects and verify the exact four-path commit before acceptance.
- No packet authorizes live migration, network provider calls, real credentials, paid generation, worker activation, deployment, deletion of production data, publication or production approval.

---

## Fixed file and interface map

| File | Responsibility |
|---|---|
| `r2/contracts/opportunity.py` | frozen public and internal-seam contracts from spec §§4–7 |
| `r2/opportunity/digests.py` | versioned canonical digest domains from spec §8 |
| `r2/opportunity/errors.py` | stable stop-code exception mapping |
| `r2/opportunity/ports.py` | source, capability, custody, evidence-store, M8 and Factual ports |
| `r2/opportunity/parity.py` | pure donor manifest and verdict recomputation |
| `r2/opportunity/profiles.py` | profile publication, revision/CAS and reads |
| `r2/opportunity/acquisition.py` | query declaration, attempt lifecycle and page orchestration |
| `r2/opportunity/normalization.py` | source-native lossless normalization |
| `r2/opportunity/signals.py` | policy-gated signal derivation |
| `r2/opportunity/candidates.py` | candidate revisions, closures and validity projections |
| `r2/opportunity/greenlight.py` | Human Greenlight decisions and revalidation |
| `r2/opportunity/bridges.py` | Canvas and Factual prepare/call/reconcile bridges |
| `r2/opportunity/invalidation.py` | deletion jobs, indexed traversal and tombstones |
| `lib/db/models/opportunity.py` | M9 SQLAlchemy rows |
| `lib/db/repositories/opportunity.py` | scoped repositories and unit of work |
| `server/services/opportunity.py` | host composition and port adapters |
| `server/services/m9_custodian.py` | host custodian adapter over ADR-0103 showrunner grants (profile, Greenlight, invalidation) |
| `lib/db/models/host_custodian.py` | host-owned `host_custodian_leases` replay table |
| `server/routers/opportunity.py` | authenticated, migration-gated HTTP API |
| `frontend/src/features/opportunity-desk/` | projection-only Opportunity Desk UI |
| `scripts/r2/verify_m9_scope.py` | lineage, seam, scope and bypass verifier |
| `scripts/r2/verify_m9_parity.py` | donor parity/evidence recomputation |
| `scripts/r2/verify_m9_evidence.py` | packet evidence verifier |

Public names and signatures in spec §§2 and 4–7 are normative. Mechanical import-path adjustment is permitted only when recorded by A0; contract, digest, authority or lock-order differences stop with `POST_M8_BASE_SEAM_CHANGED` or `M9_SCHEMA_CHANGE_REQUIRED`.

## Migration sequence

Task A0 implementation records the exact singleton Alembic predecessor from the independently accepted prerequisite worktree. M9 revision IDs and ownership are fixed:

```text
accepted singleton predecessor
  -> 9a9c4a0e0001  profile, command and baseline evidence metadata, plus the host-owned host_custodian_leases
  -> 9b9c4a0e0001  capability, query, attempt, snapshot and observation metadata
  -> 9c9c4a0e0001  signal and opportunity candidate metadata
  -> 9d9c4a0e0001  Greenlight, bridge intents and bridge receipts
  -> 9e9c4a0e0001  invalidation jobs, edges and validity projections
```

Each migration uses the exact prior M9 revision as `down_revision`; `9a9c4a0e0001` uses the A0-recorded accepted singleton predecessor. Once a packet is independently accepted, its migration is immutable; a defect requiring schema change stops `M9_SCHEMA_CHANGE_REQUIRED` for an additive amendment.

## Packet sequence

| Checkpoint | Packet | Independently testable deliverable |
|---|---|---|
| M9-A | `2026-09-14-r2-m9a-foundation-cohort-profiles.md` | authored for review; execution blocked pending design and prerequisite acceptance |
| M9-B | released after M9-A acceptance | manual-import acquisition, capability policy, erasable store and lossless observations |
| M9-C | released after M9-B acceptance | policy-bound signals, donor fixtures and opportunity candidates |
| M9-D | released after M9-C acceptance | Human Greenlight, M8 Canvas seed and Factual Authority bridge |
| M9-E | released after M9-D acceptance | deletion/invalidation traversal and post-erasure read semantics |
| M9-F | released after M9-E acceptance | Opportunity Desk, accessibility, benchmarks and final utility dossier |

Only M9-A is authored for review now; it is not released for implementation.
Its read-only A0-preflight gate may report prerequisite failures, but production-file
creation remains blocked. B–F remain sequence-locked so their exact integration
paths are derived from independently accepted predecessor code rather than
guessed from proposed modules.

## Stop-code routing

| Packet | Required stop codes |
|---|---|
| A | `M9_DESIGN_NOT_ACCEPTED`, `M9_M8_IMPLEMENTATION_NOT_ACCEPTED`, `M9_REQUIRED_EVIDENCE_MISSING`, `POST_M8_BASE_SEAM_CHANGED`, `M9_SCHEMA_CHANGE_REQUIRED`, `M9_COMMAND_REPLAY_CONFLICT`, `M9_STALE_HEAD`, `M9_COHORT_LEAKAGE`, `M9_PROFILE_PUBLICATION_UNAUTHORIZED`, `M9_DONOR_PARITY_INCOMPLETE` |
| B | `M9_SOURCE_CAPABILITY_UNAVAILABLE`, `M9_SOURCE_POLICY_FORBIDDEN`, `M9_CREDENTIAL_REFERENCE_INVALID`, `M9_ACQUISITION_OUTCOME_UNKNOWN`, `M9_RAW_DIGEST_MISMATCH`, `M9_NORMALIZATION_LOSSY`, `M9_EVIDENCE_RETENTION_EXPIRED`, `M9_OPERATIONAL_ENVELOPE_EXCEEDED` |
| C | `M9_DERIVATION_POLICY_UNPROVEN`, `M9_COHORT_LEAKAGE`, `M9_EVIDENCE_STALE`, `M9_DONOR_PARITY_INCOMPLETE`, `M9_OPERATIONAL_ENVELOPE_EXCEEDED` |
| D | `M9_FACTUAL_AUTHORITY_UNAVAILABLE` (release gate: FA-1 acceptance absent), `M9_GREENLIGHT_UNAUTHORIZED`, `M9_GREENLIGHT_EXPIRED`, `M9_COHORT_LEAKAGE`, `M9_EVIDENCE_STALE`, `M9_STALE_HEAD`, `M9_ACQUISITION_OUTCOME_UNKNOWN`, `POST_M8_BASE_SEAM_CHANGED` |
| E | `M9_INVALIDATION_INCOMPLETE`, `M9_INVALIDATION_UNAUTHORIZED`, `M9_EVIDENCE_RETENTION_EXPIRED`, `M9_EVIDENCE_STALE`, `M9_REQUIRED_EVIDENCE_MISSING`, `M9_OPERATIONAL_ENVELOPE_EXCEEDED` |
| F | every upstream code plus `M9_REQUIRED_EVIDENCE_MISSING` when evaluation, reviewer or production-envelope evidence is absent |

Later packet authors copy only the applicable stable codes from this table and the design; they do not invent aliases.

## Task P0: Combined-base acceptance

**Files:** `docs/r2/evidence/schemas/R2_M9_PREREQUISITE_ACCEPTANCE.schema.json`, `scripts/r2/verify_m9_prerequisites.py`, its unit test and `R2_M9_PREREQUISITE_ACCEPTANCE.json`.

**Consumes:** `R2_M8_IMPLEMENTATION_ACCEPTANCE.json` (`M8_IMPLEMENTATION_ACCEPTED`) and `R2_M9_DESIGN_ACCEPTANCE.json` (`M9_DESIGN_ACCEPTED`) on one clean base that descends from both acceptance commits and has one Alembic head.

- [ ] Write the schema and the Git-backed verifier with RED tests: absent or wrong-status acceptances, a base that does not descend from both acceptance commits, a dirty tree, several Alembic heads, and hash drift.
- [ ] Write the record binding both acceptance artifacts by path and SHA-256, the base HEAD and the Alembic head. Commit it as the sole child of that base, then run an independent review before M9-A starts.

## Task A: Foundation and cohort profiles

**Files:** Follow the M9-A packet only when its A0 verifier derives
`IMPLEMENTATION_ELIGIBLE` from every valid design and prerequisite acceptance
artifact; the normative execution contract itself does not change state.

**Consumes:** Independently accepted M8 implementation and M9 design acceptance (combined base, Task P0). M9-A imports only the existing factual contracts; the durable Factual Authority is the M9-D release gate.

**Produces:** Frozen opportunity contracts, canonical digests, stop codes, donor parity fold, append-only cohort-profile repository/service/routes and `M9_A_CANDIDATE` evidence.

- [ ] Execute `2026-09-14-r2-m9a-foundation-cohort-profiles.md` A0–A4 sequentially.
- [ ] Stop at its clean evidence HEAD for independent Codex review.

## Task B: Capability-gated acquisition and observations

**Files:** Create/modify only `acquisition.py`, source/evidence-store adapters, the M9-B migration/ORM/repository slice, router endpoints, fixtures and M9-B evidence.

**Consumes:** Accepted M9-A contracts, `SourceCapabilityPort`, `SnapshotEvidenceStore`, profile/query contracts and lock ranks 1–7.

**Produces:** `declare_query`, `acquire`, attempt recovery, manual-import adapter, immutable snapshots/observations and current/historical snapshot reads.

- [ ] Freeze M9-B owned paths, exact accepted M9-A HEAD, migration predecessor, manual-import data classes and capability fixtures in the released packet.
- [ ] RED-test grant state/condition/account/purpose mismatch, credential token leakage, pagination loops, page duplication/order drift, quota and byte ceilings, partial results, timeout/outcome-unknown, revoke-between-pages and exact retry.
- [ ] Implement prepare → external I/O → finalize without holding a database transaction across evidence-store or provider I/O.
- [ ] Register manual-import behavior and no-network capability descriptors for YouTube Data, Google Trends alpha, TikTok Research and TikTok Commercial Content; dormant/unavailable descriptors reject execution before credential or network access.
- [ ] RED/GREEN-test lossless native field/definition/value/unit/window mapping and prohibited derivation during normalization.
- [ ] Prove upgrade/downgrade/upgrade, concurrent attempts, restart reconciliation, foreign/unknown equivalence and policy-permitted erasure refs on disposable PostgreSQL.
- [ ] Seal `M9_B_CANDIDATE` evidence at a clean HEAD and stop.

## Task C: Signals, candidates and donor parity

**Files:** Create/modify only `normalization.py`, `signals.py`, `candidates.py`, M9-C persistence, donor fixtures/manifests and evidence.

**Consumes:** Accepted M9-B snapshots/observations, exact profile revision/digest, effective capability evaluations and M8 learning read bundle.

**Produces:** Policy-bound `DerivedOpportunitySignal`, dimension assessments, append-only `OpportunityCandidateRevision` and candidate validity reads.

- [ ] Freeze composite-signal policy basis for every dimension and both cohorts before writing transforms.
- [ ] RED-test expired/forbidden/mixed-purpose input, correction-head drift, missing-as-zero, cross-cohort leakage, duplicate dimensions, retained-digest policy and candidate closure mismatch.
- [ ] Implement pure deterministic transforms whose output refs and uncertainty remain erasable; no universal score is introduced.
- [ ] Port OpenMontage vocabulary and Huohuo `爽型` vocabulary only through typed fixtures; use Kalinga malformed, duplicate and prior-topic collisions as adversarial cases.
- [ ] Run exact-pin donor and R2 fixtures; independently recompute every parity verdict and require all applicable rows `PARITY` or `IMPROVED`.
- [ ] Prove candidate genesis/append/CAS/replay, 250-revision ceiling and superseding-new-ID behavior on PostgreSQL.
- [ ] Seal `M9_C_CANDIDATE` evidence at a clean HEAD and stop.

## Task D: Greenlight and authority bridges

**Files:** Create/modify only `greenlight.py`, `bridges.py`, M9-D persistence, host M8/Factual adapters, routes and evidence.

**Release gate:** `R2_FACTUAL_AUTHORITY_IMPLEMENTATION_ACCEPTANCE.json` with `FACTUAL_AUTHORITY_IMPLEMENTATION_ACCEPTED` (FA-1), or stop `M9_FACTUAL_AUTHORITY_UNAVAILABLE`. The packet also adds the ADR-0109 resolver as an additive M8 evolution under M8 tests.

**Consumes:** Accepted M9-C candidate closure, `GreenlightCustodianPort`, accepted M8 Canvas seed seam (server-side seed under the ADR-0105 project profile; never the client append route, ADR-0107) and the durable Factual Authority port accepted by FA-1 (release gate).

**Produces:** append-only Greenlight decisions, current head, bounded TTL, exact Canvas seed receipts and unverified Factual submissions.

- [ ] RED-test non-Human/model/provider/donor issuance, scope/actor mismatch, stale candidate/profile/evidence/grant, TTL beyond 24 hours/input expiry, CAS races and supersession rules.
- [ ] Implement decision append and receipt atomically under the normative lock order.
- [ ] Verify accepted M8 accepts registered `M9_OPPORTUNITY_SEED`; otherwise stop `POST_M8_BASE_SEAM_CHANGED` without modifying M8.
- [ ] RED/GREEN-test Canvas prepare/outbox/call/reconcile, exact replay after unknown outcome and prohibition on promotion, Canon, Narrative or Production writes.
- [ ] RED/GREEN-test Factual selection mapping; Greenlight never elevates Claim status and M9 never writes factual tables.
- [ ] Seal `M9_D_CANDIDATE` evidence at a clean HEAD and stop.

## Task E: Deletion and invalidation

**Files:** Create/modify only `invalidation.py`, M9-E persistence/indexes, evidence-store deletion adapter, read projections, fault fixtures and evidence.

**Consumes:** Accepted M9-D closure (dependency columns of snapshots, observations, signals, candidates, decisions and bridge intents), M8 correction reads and Factual invalidation receipts. M9-E creates `m9_invalidation_edges` and builds the edges from those recorded dependencies.

**Produces:** idempotent `InvalidationJob`, deadline-bound traversal, append-only tombstones, `INVALIDATED` historical reads and fail-closed operational use.

- [ ] RED-test every transition, retry, crash cut and operator receipt from spec §13.
- [ ] Implement indexed traversal across raw refs → snapshots → observations → signals → candidates → Greenlight → bridge receipts, plus upstream M8 learning refs.
- [ ] Delete exact governed payload/identity/integrity refs, retain only permitted proofs and append correction/expiry records without rewriting history.
- [ ] Fail dependent reads with `M9_INVALIDATION_INCOMPLETE` during propagation; after completion return historical projection and fail operational use with `M9_EVIDENCE_STALE`.
- [ ] Prove idempotent replay, deadline evidence, no residual forbidden data and Factual invalidation receipt closure.
- [ ] Seal `M9_E_CANDIDATE` evidence at a clean HEAD and stop.

## Task F: Opportunity Desk and final utility

**Files:** Create/modify only `frontend/src/features/opportunity-desk/`, route composition, all supported i18n catalogs, browser tests, benchmark/evaluation protocols and M9-F evidence.

**Consumes:** Accepted M9-E read/command API.

**Produces:** accessible Opportunity Desk, manual-import Western/`zh-shuang` workflows, resource evidence and final M9 acceptance candidate.

- [ ] Preregister corpus, reviewer qualification schema, rubric version, conflict declarations, smallest useful effect and operational envelope before results.
- [ ] Implement source capability, query-bound, snapshot, candidate comparison, evidence drill-down, uncertainty and Greenlight confirmation projections without client-authoritative digests or permissions.
- [ ] Add English, Vietnamese and Chinese keys for every user-facing string; run i18n consistency.
- [ ] Run Vitest and Playwright/axe-core for empty, loaded, partial, unavailable, conflict, stale and invalidated states with keyboard/focus/reduced-motion checks.
- [ ] Run two blind qualified reviews per cohort and record disagreement/correction time against preregistered baselines.
- [ ] Benchmark exact graph/data sizes and record p50/p95, peak RSS, database/evidence-store growth, query count and invalidation traversal time.
- [ ] Run all repository-required backend/frontend gates; seal `M9_F_CANDIDATE` with zero required skips/material unknowns and stop for independent acceptance.

## Final completion boundary

M9 is complete only when A–F each have independently accepted evidence chained by exact parent HEAD, all migrations form one reversible lineage, donor parity and two-cohort utility pass, and final acceptance is recorded separately from the M9-F candidate commit. Completion does not authorize provider activation, credentials, publication, deployment or production operations.
