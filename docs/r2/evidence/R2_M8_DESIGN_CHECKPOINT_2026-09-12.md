# R2-M8 design-session checkpoint — 2026-09-12

Status: `SUPERSEDED_AS_LIVE_HANDOFF / HISTORICAL_CHECKPOINT`

Current continuation:

- completed reuse-first research:
  `docs/research/2026-09-13-r2-m8-reuse-first-comprehensive-research.md`;
- architecture comparison awaiting sponsor decision:
  `docs/research/2026-09-13-r2-m8-architecture-options.md`;
- research closed at commit `7d6f4f18`; no ADR, specification, implementation
  plan, implementation, migration, or activation has been started;
- sponsor direction now excludes licensing from selection, rejection, scoring,
  and sequencing. License-related blockers below are retained only as the
  historical state of this 2026-09-12 checkpoint and are not current M8 gates.

This checkpoint is a durable handoff only. It is not an ADR, architecture
approval, implementation specification, implementation plan, M8 starting-state
approval, or permission to implement/deploy/migrate/publish.

## Live repository state at session start

- Repository: `/home/anhtuan/content-production-os`
- Branch: `design/r2-m5b-narrative-context`
- Exact HEAD: `5d81d8339042c18c0284d50945b3b8b1914709df`
- HEAD subject: `docs(r2): remediate and split M7 execution plans`
- Preserved pre-existing dirty files (outside M8 scope):
  - `AGENTS.md`
  - `docs/superpowers/plans/2026-09-09-r2-m5c-narrative-lifecycle.md`
  - `docs/superpowers/specs/2026-09-09-r2-m5c-narrative-lifecycle-design.md`
- Disk headroom observed: approximately 52 GiB on the workspace filesystem and
  12 GiB on `/tmp`.
- No M8 implementation, migration, runtime activation, deployment, or publish
  operation was started.

## Graph verification state

- Project: `home-anhtuan-content-production-os`
- Tier: Tier 2 verification
- Index mode: `full`
- Generation/index timestamp: `2026-09-12T15:26:05Z`
- Graph status: `ready`
- Graph Git context matched the branch and exact HEAD above.
- `check_index_coverage` reported `no_recorded_issue` and `metadata_match` for
  the frozen roadmap/architecture/contracts/decision documents and the current
  host seams listed below. This is a best-effort signal, not proof of complete
  indexing.

Verified current-host seams:

- `frontend/src/components/canvas/StudioCanvasRouter.tsx::StudioCanvasRouter`
  - graph trace (both directions, depth 2) reported 179 callees and 2 callers;
  - it currently coordinates direct ArcReel API CRUD/generation plus existing
    Overview/Timeline/Grid/Reference/Lorebook views;
  - therefore the existing ArcReel UI term `canvas` must not be conflated with
    the new non-authoritative R2 Creative Canvas exploration plane.
- `r2/contracts/results.py::ApprovedMaster`
- `r2/contracts/results.py::QualityReport`
- `r2/contracts/production.py::ShotSpec`
- `r2/production/approval_service.py::ProductionApprovalService`
  - current inbound graph path is `GoldenARunner.run ->
    GoldenAHostIntegration.approve -> ProductionApprovalService`;
  - promotion checks generated/non-rejected state, target identity and content
    fingerprint, preserves idempotence, and commits host version plus R2 master
    metadata together.
- `lib/db/repositories/usage_repo.py::UsageRepository`
- `server/services/workflow_planner.py::WorkflowPlanner`

## Frozen M8 boundary confirmed

Primary evidence:

- `docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:241-257`
- `docs/r2/R2_01_FROZEN_ARCHITECTURE.md:256-283,745-768,881-947`
- `docs/r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md:110-138,595-618,724-735`
- `docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:1451-1515`
- `docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:466-498`
- `docs/r2/evidence/PROJECT_DECISIONS_2026-09-09.md:205-224,299-310`
- `docs/research/2026-09-07-r2-reuse-map-and-completion-gates.md:13-64`

Confirmed constraints:

1. M8 depends on accepted M7; the current design branch contains M7 design and
   execution packets, not an accepted M7 implementation lineage. An M8 plan
   must therefore begin with an exact post-M7 starting-state gate.
2. Creative Canvas is an exploration plane. `CanvasCandidate -> impact preview
   -> explicit audited PROMOTE -> R2 production artifact`; Canvas state never
   becomes Production or Canon truth directly.
3. Learning consumes distribution/performance/cost/QA/method-provider evidence
   and emits recommendations/experiments/routing suggestions/hypotheses only.
   It cannot mutate Canon, NarrativePlan, CreativePolicy, Claim truth, or
   governance without a separate explicit Human review/transaction path.
4. Multi-format composition starts from approved production artifacts and a
   lineage-bearing edit timeline. No renderer owns upstream truth.
5. DramaClaw working state/project DB/task runtime and OpenMontage checkpoints
   or duplicate production queue remain excluded donor authority.
6. Product coverage must include sibling cohorts for generic Western drama and
   Chinese short-drama `爽文`; profile-specific craft policy must remain scoped
   and versioned rather than becoming universal authority truth.

## Research performed so far

### DramaClaw exact pinned source

Pinned revision from the repository source manifest:
`b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`.

Directly fetched and inspected from `raw.githubusercontent.com`:

- `frontend/src/features/freezone/commit/promoteToAsset.ts`
  - SPDX `Elastic-2.0` at the pinned revision;
  - validates target-specific identity requirements;
  - separates impact preview from push/promotion;
  - still delegates to donor `/freezone/push`, so it is not an R2 authority
    implementation.
- `frontend/src/features/canvas/application/canvasServices.ts`
  - composition root for an in-memory event bus, node factory/catalog,
    resolvers, tool processor and AI gateway;
  - useful seam vocabulary, not a persistence/authority proof.
- `frontend/src/stores/canvasStore.ts`
  - a very large Zustand/XYFlow UI store with nodes/edges, undo/redo, groups,
    viewport bookmarks, mutations, hydration and autosave-safety state;
  - inappropriate to import wholesale as the R2 domain/authority model.
- `src/novelvideo/director_world/scene_spatial_contract.py`
  - generates an LLM-derived spatial contract from master/reverse images,
    overlap analysis and explicit direction/seam/duplication locks;
  - writes prompt/raw/JSON artifacts and directly calls an OpenRouter-compatible
    vision model;
  - useful as a bounded spatial experiment/reference, not authoritative R2
    geometry or a generic canvas contract.

The current DramaClaw documentation now identifies CE as Elastic License 2.0
source-available. Integration must still bind licensing conclusions to the
exact selected revision and preserved notices; this checkpoint makes no legal
approval.

### OpenMontage exact local checkout

- Checkout: `/home/anhtuan/content-os-r1-8/work/OpenMontage`
- Exact HEAD: `08e2151fa02de28a5d6a312b3d575692bf147ad7`
- Remote: `https://github.com/calesthio/OpenMontage.git`
- License inspected: AGPL-3.0.
- Relevant source inspected:
  - `schemas/artifacts/review.schema.json`
  - `schemas/artifacts/final_review.schema.json`
  - `schemas/artifacts/asset_manifest.schema.json`
  - `pipeline_defs/cinematic.yaml`
  - `pipeline_defs/clip-factory.yaml`
  - `pipeline_defs/localization-dub.yaml`
  - `backlot/state.py`
  - `lib/checkpoint.py`
  - `tools/cost_tracker.py`
  - `tests/backlot/test_gate_scenarios.py`
  - `tests/eval/bench_runner.py`
- Fresh bounded probe:
  - `python -m tests.eval.bench_runner`: 12? no — exact observed result was
    **13/13 scenarios passed**, covering synthetic quality validators.
  -ливо `pytest tests/backlot/test_gate_scenarios.py` was not executed because
    the donor environment lacked `pytest`; do not report it as a failed donor
    test or as passing evidence.
- Source-derived conclusion: OpenMontage offers strong artifact/review/checkpoint,
  cost, eval and multi-output precedents, but not a persistent cross-project R2
  Learning Engine. Its filesystem checkpoints cannot become R2 workflow truth.

### Dual-profile evidence already carried forward

- `docs/research/2026-09-12-r2-m6-dual-profile-adaptation-research.md` already
  distinguishes generic Western drama from Huohuo's narrower Chinese
  short-drama `恨/爽/急/盼` and six-`爽型` policy source.
- No inspected source proves those Chinese chapter rules are universal or maps
  them directly to every 60–120 second output.
- M8 analytics/recommendations therefore need explicit `creative_profile`
  identity/version and cohort scope; Western and Chinese evidence must not be
  pooled silently.

## Provisional architecture options (not yet presented or approved)

1. **Recommended candidate — staged R2-owned substrate with donor adapters.**
   Build one provider-neutral evidence/promotion substrate, then separate
   vertical packets for Creative Canvas, learning recommendations,
   multi-format projections, and optional spatial experiments. Reuse donor
   semantics/tests where legally and technically allowed, but keep the existing
   FastAPI/React host and R2 authority.
2. **Thin canvas-only M8.** Ship canvas/promotion first and defer learning,
   distribution and spatial/multi-format depth. Lower initial risk but does not
   satisfy the frozen full M8 scope without explicit milestone decomposition.
3. **Whole-donor/service integration.** Run or vendor large DramaClaw and/or
   OpenMontage surfaces. Highest apparent feature reuse, but creates authority,
   operational, license, second-runtime and parity risks; currently not
   recommended.

The central unresolved choice is whether M8 may add persistent donor services
or must remain one ArcReel/FastAPI host with only bounded deterministic
subprocesses. Prior decisions favor the latter; no user approval has yet been
requested or received in this session.

## Files and work products

- This durable checkpoint:
  `docs/r2/evidence/R2_M8_DESIGN_CHECKPOINT_2026-09-12.md`
- Background research agent ownership (may still be partial when the session
  ends):
  `docs/research/2026-09-12-r2-m8-canvas-learning-multiformat-research.md`

## Exact resume sequence

1. Run `git branch --show-current`, `git rev-parse HEAD`, `git status --short`,
   `git worktree list --porcelain`, disk/process checks, and compare to this
   checkpoint. Preserve the three pre-existing dirty files.
2. Confirm whether the background research file exists and inspect its diff;
   label incomplete sections rather than inventing missing findings.
3. Re-run `list_projects`/`index_status`; if generation/HEAD changed, refresh
   graph evidence and repeat `check_index_coverage` for every relied-on path.
4. Finish donor research at exact pins, including tests/license/runtime and
   bounded gaps. Do not silently substitute current donor `main` for pinned
   source.
5. Present 2–3 architecture approaches and the recommended staged substrate to
   the user. Ask one question at a time; first resolve the persistent
   donor-service/one-host boundary.
6. Stop for explicit user approval. Do not write ADR/spec/implementation plan
   before that approval.
7. After approval, write ADR and design spec, self-review them, request written
   spec approval, then invoke `writing-plans` and create Claude Code execution
   packets. No implementation belongs to this branch/session unless separately
   authorized.

## Explicit non-claims

- M8 architecture is not approved.
- M8 criteria and packet split are not final.
- No ADR/spec/implementation plan has been written.
- No M8 code or tests have been implemented.
- No production, migration, deployment, provider call, publish, or cleanup was
  authorized or performed.
