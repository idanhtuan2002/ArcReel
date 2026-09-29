# R2 M8 — Architecture options and recommendation

**Status:** `ACCEPTED ARCHITECTURE DIRECTION` — sponsor accepted Alternative A on 2026-09-13; this acceptance authorizes ADR/specification/planning, not implementation or production activity.
**Research basis:** [`2026-09-13-r2-m8-reuse-first-comprehensive-research.md`](2026-09-13-r2-m8-reuse-first-comprehensive-research.md), status `RESEARCH COMPLETE / DECISION INPUT`.
**Decision policy:** licensing is excluded by sponsor direction. Scores measure verified useful reuse rather than copied line count.

## 1. Decision to make

Choose the M8 system shape that delivers Creative Canvas, explicit promotion, spatial experiments, lineage-bound analytics/recommendations, and semantic multi-format projection while preserving frozen R2 authority and reusing the maximum proven behavior.

Locked constraints eliminate designs that silently change the decision:

- ArcReel remains the primary host and authority integration point.
- Canvas state, spatial/model inference, observations, and recommendations remain non-authoritative.
- Promotion is explicit, preview-bound, currentness-checked, idempotent, and auditable.
- M7 owns durable long-running execution, receipts, recovery, and resource control.
- Generic Western and `zh-shuang` evidence are sibling, isolated profiles over shared mechanics.
- Technical format conformance is not semantic parity.

## 2. Weighted criteria

Scores use `1` (poor) through `5` (strong). A high reuse score requires transferable behavior, tests, and compatible seams; wholesale import with large replacement burden does not earn full reuse credit.

| Criterion | Weight | What earns a high score |
|---|---:|---|
| Authority and data integrity | 20 | One fail-closed server authority; exact lineage/currentness; no donor bypass |
| Verified useful reuse | 20 | Preserves inspected donor/host behavior and adversarial tests with little dead coupling |
| Workflow and quality leverage | 15 | Covers the complete M8 user loop and supports measurable utility |
| Delivery efficiency | 15 | Smallest amount of integration/replacement work for accepted behavior |
| Failure containment and recovery | 10 | Capability failures are bounded, resumable, and cannot corrupt authority |
| Operational simplicity | 10 | Reuses host, PostgreSQL, and M7 execution rather than adding runtimes/services |
| Reversibility | 5 | Replaceable UI/provider/render adapters; durable contracts do not depend on one donor |
| Evidence confidence | 5 | Claims are backed by inspected code/tests/probes; remaining unknowns have explicit gates |

## 3. Alternatives

### A — Port-accelerated integrated capability kernel (recommended)

Keep one ArcReel application boundary and add only the missing M8 contracts. Port proven DramaClaw behavior and tests into bounded frontend/domain modules; adapt OpenMontage mechanics behind R2 output/spatial ports; persist authority-bearing state in PostgreSQL; execute expensive work through M7.

```text
ArcReel React shell
  -> Creative Canvas UI (React Flow adapter + Zustand + donor parity behavior)
  -> recovery cache / save coordinator
  -> R2 exploration API
       -> PostgreSQL candidate revisions + history + OCC
       -> preview-bound promotion adapter -> existing Production Authority
       -> M7 executions -> spatial / render / evaluation adapters
       -> observation ledger -> recommendation lifecycle -> human disposition
```

Reuse allocation:

- **Direct host reuse:** React shell, Zustand, API/i18n conventions, provenance, aspect/media mechanics, QA planes, usage/cost records, Production Approval pattern, profile identities, M7 execution.
- **Port with parity:** DramaClaw graph/history/group/bookmark/save-decision/payload-limit logic; save coordinator and recovery behavior; selective React Flow interactions; spatial pure normalizers and fixtures.
- **Adapt behind ports:** OpenMontage FFmpeg/Remotion composition, crop mechanics, validation and replay scaffolds.
- **Build only gaps:** typed candidate/revision protocol, preview/authorization binding, observation identity/corrections, recommendation lifecycle, output/reframe/safe-area contracts, semantic evaluation.
- **Do not transplant:** donor filesystem authority, parallel API/provider/billing/project shells, auto-commit/push authority, or a second job runtime.

The graph renderer, platform metric adapters, spatial provider, and render backend remain replaceable. Candidate identity, lineage, promotion, observation semantics, and evaluation evidence remain stable R2 contracts.

### B — Wholesale donor enclave plus bridge

Embed most of DramaClaw as a separate workbench and run OpenMontage as a sidecar, then bridge outputs into ArcReel.

This preserves the largest raw amount of donor code, but imports roughly 102k lines across the inspected canvas/freezone trees, 86 heavily coupled files, donor APIs/storage/provider/billing assumptions, and a second operational boundary. The bridge still must replace donor promotion, authority, persistence, execution, identity, and audit semantics. Apparent reuse is therefore much larger than effective reuse.

### C — Minimal native M8 rewrite

Implement a small ArcReel-native canvas, analytics table, recommendation view, and format exporter without porting donor code or tests.

This produces a clean host-shaped codebase and strong authority alignment, but discards the donor's 199 relevant test files and hard-won save/recovery/history behavior. It risks rebuilding concurrency, local recovery, graph editing, spatial normalization, and format mechanics from first principles, with lower functional depth and slower evidence accumulation.

### D — Capability microservices and event bus

Create separate Canvas, Learning, Spatial, and Format services connected by events and a shared promotion gateway.

This isolates compute and permits independent scaling, but M8 has no evidence that service-level scaling is needed. It duplicates M7 execution/recovery and ArcReel authority integration, adds distributed ordering/idempotency/schema-evolution problems, and weakens end-to-end currentness proofs. It can be revisited only if measured host/M7 limits cannot satisfy the locked workload envelope.

## 4. Scorecard

| Alternative | Authority 20 | Reuse 20 | Quality 15 | Delivery 15 | Containment 10 | Ops 10 | Reverse 5 | Evidence 5 | Weighted / 100 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **A. Integrated port-accelerated kernel** | 5 | 5 | 5 | 4 | 5 | 5 | 5 | 4 | **96** |
| B. Wholesale donor enclave | 2 | 3 | 4 | 2 | 2 | 1 | 1 | 3 | **48** |
| C. Minimal native rewrite | 5 | 1 | 3 | 2 | 4 | 5 | 4 | 3 | **64** |
| D. Capability microservices | 3 | 2 | 4 | 1 | 4 | 1 | 3 | 2 | **50** |

Score sensitivity does not change the ranking under reasonable priorities. Alternative A remains first if delivery and reuse weights are halved or if authority weight is doubled. Alternative C becomes the fallback if selective port parity proves substantially more expensive than rebuilding, while B and D require evidence for duplicated application or service boundaries that research did not find.

## 5. Recommended architecture boundary

Accept Alternative A as the architecture direction, subject to the following explicit boundaries:

1. **Exploration kernel:** one server-owned revision/history/OCC envelope for typed `CanvasCandidate`, `SpatialCandidate`, and `FormatCandidate`; canvas browser storage is recovery-only.
2. **Promotion kernel:** one preview-bound promotion protocol with candidate revision, target identity, expected current parent/master, lineage digest, expiry, authorization scope, idempotency identity, and durable receipt. Typed adapters translate a successful promotion into existing R2 authority operations.
3. **Learning kernel:** immutable source-specific observations and correction lineage feed scoped recommendations. Recommendation disposition may create a governed proposal; it never shares the artifact promotion shortcut or mutates policy/routing/content authority.
4. **Execution kernel:** spatial inference, render, ingestion, replay, and evaluation are M7 execution types with bounded resources and recovery. No M8-local queue.
5. **Format projection:** `ApprovedMaster -> FormatProjectionPlan -> RenderExecution -> TechnicalValidationReport + SemanticParityReport -> FormatCandidate -> PROMOTE`.
6. **Profile isolation:** every relevant candidate, observation, recommendation, evaluation, and report binds exact profile/policy/content lineage. Cross-profile aggregation is explicit and cannot silently train or score either sibling.
7. **Replaceable adapters:** React Flow, model/provider, platform analytics, Remotion, and FFmpeg details sit behind ports. Their packet-level probes can block or replace one adapter without reopening authority contracts.

## 6. Proposed delivery slices after acceptance

This is sequencing input, not an implementation plan:

1. **M8-A — Shared exploration and promotion contracts:** revisions, OCC, preview/authorization, receipts, typed persistence, no UI dependency.
2. **M8-B — Canvas behavior port:** pure domain/history first, save/recovery protocol, then React Flow adapter and accessibility/performance gates.
3. **M8-C — Spatial candidates:** deterministic normalizers/fixtures, M7 inference execution, evidence and promotion adapter.
4. **M8-D — Observation and recommendation lifecycle:** internal instrumentation first, source adapters/corrections, offline replay, human disposition and profile-isolated evaluation.
5. **M8-E — Multi-format projection:** versioned output/overlay profiles, reframe plan, M7 render, technical and semantic parity, explicit promotion.
6. **M8-F — Integrated utility evidence:** end-to-end Western-generic and `zh-shuang` workflows, non-regression, resource/recovery evidence, and independent review.

Each slice must carry exact donor pins/paths, behavior parity rows, targeted and adversarial tests, machine-readable evidence, exact implementation HEAD, scope allowlist, and independent review. Acceptance of this architecture does not accept any donor implementation or authorize production activation.

## 7. Sponsor decision

The sponsor accepted **Alternative A: Port-accelerated integrated capability kernel** on 2026-09-13 and directed the design to proceed immediately. The ADR, design specification, and Claude Code execution packets must instantiate `R2-DEC-031` as a machine-readable `DonorParityContract`; acceptance of the direction does not accept implementation, waive parity, or authorize production activity.
