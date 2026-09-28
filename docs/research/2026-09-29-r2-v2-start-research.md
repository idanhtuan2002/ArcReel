# R2 V2 — start research (2026-09-29)

This is research, not a decision. The V2 start gate (strategy §7) is not yet met. The operator
cycle 1 is in progress, so no V2 code, schema or authority starts from this note. License is out
of scope.

## Question

1. What must hold before V2 starts, and what is still open?
2. The strategy requires this before any portfolio control plane: is `PipelineRun` a host runtime
   projection or a new authoritative aggregate (strategy §5 item 13)?
3. In what order should V2 packets enter? Where do the sponsor's wishes (autonomous research,
   story writing) belong?

## Facts

1. **V2 start gate** (strategy §7):
   1. the V1 release gate is complete and the tag exists;
   2. the V1 baseline is restored and verified;
   3. one stable operator release cycle has been observed;
   4. there is an evidence-backed gap that existing project, task, artifact or asset owners
      cannot safely represent.
2. **Its state on 2026-09-29.**
   - (1) holds: `r2-v1.0.0`, with the sponsor's migration-gate exception.
   - (2) holds for the drill, and the V2 staging restore is item 12.
   - (3) is in progress in `~/arcreel-v1-trial`. Gates A, B and the shot Cs are recorded; the
     final, Gate D, backup and restore check are pending.
   - (4) needs the cycle-1 journal. The sponsor has stated a wish for autonomous research and
     story writing.
3. **The first V2 packet** addresses portfolio identity, resource isolation, pause/resume/cancel
   semantics and repository projections (strategy §7). Its first design review must decide
   `PipelineRun`, which "may not be smuggled in as a UI or scheduler convenience" (V1 research,
   2026-09-17, §6).
4. **Frozen architecture** (R2.1).
   - **Runtime Authority is host-owned** (§4.5): tasks, batches, provider jobs, checkpoints,
     retry and recovery, cancellation, queue, SSE.
   - **The host also owns "Workflow Status / Plan"** (§16).
   - **The hard invariant is `Runtime State ≠ Artifact Truth`** (§5).
   - **The frozen architecture and roadmap never define a pipeline, run or scheduler** (R2.1,
     R2.6).
5. **ADR-0080** (design branch `design/r2-m5b-narrative-context`) places M9–M12 inside the host.
   They "shall not become a second application, orchestrator, workflow authority, database, queue
   or truth store". Its order is: M8 (Canvas/Learning/Multi-format) → M9 (Opportunity and
   Research) → M10 (Quality and Packaging) → M11 (Governed Distribution) → M12 (Portfolio
   Learning).
6. **M8 stopped** on 2026-09-14 with `M8_PREREQUISITE_NOT_ACCEPTED`, because no accepted M7
   candidate existed (`R2_M8_STOP.json`). V1 now supplies an M7-E production-candidate dossier,
   `R2_V1_PRODUCTION_CANDIDATE_2026-09-28.md`, under a different name than the one M8-A0
   expects: `R2_M7_E_PRODUCTION_CANDIDATE.json`.
7. **Where the sponsor's wishes sit.**
   - **Autonomous research is M9.** It turns source queries into snapshots, observations,
     opportunity candidates and a Human Greenlight. M9 does not own factual truth. M9-A is
     `PACKET_EXECUTION_BLOCKED` until M8 and a durable Factual Authority are accepted.
   - **Story writing spans three parts:**
     - the accepted M5/M5C Canon and Narrative kernel;
     - M8 Canvas exploration and promotion;
     - the host creation Agent, which V1 refuses in `PRODUCTION_CANDIDATE` for lack of a
       per-session budget reservation (ADR-0091).
   - **Commercial long-form narrative is a V1 non-promise.**
8. **Host runtime data that already exists.**
   - Tables: `tasks` (with `dependency_task_id`/`dependency_group`, `status`, `cancelled_by`),
     `batches` and `batch_tasks`, `execution_attempts`, `project_events`, `command_receipts`,
     `master_head_versions`, the gate decision tables and `gate_final_cut_receipts`.
   - Per-project stage status from `ProjectManager.get_project_status`.
9. **Donor** (OpenMontage `08e2151f`, `lib/checkpoint.py`). A pipeline's state is the set of
   per-project stage checkpoints. `get_completed_stages` and `get_next_stage` derive progress.
   There is no separate run entity; resume reads the checkpoints.

## Options for `PipelineRun`

| Option | Shape | Assessment |
|---|---|---|
| **P1: host runtime projection.** | A read model derived from the existing owners: project, gate receipts, tasks and batches, attempts, masters. Pause, resume and cancel are commands on those owners (task cancel, queue admission), not a new state holder. | Fits R2.1 §4.5 and §16, ADR-0080's "no second orchestrator/workflow authority", `Runtime State ≠ Artifact Truth`, and the donor's model. Risk: a portfolio-level resource limit (concurrency across projects) needs somewhere to live. The existing `worker_lease` and queue admission may hold it, but that is unverified. |
| P2: new authoritative aggregate | A `PipelineRun` table owns stage state, pause state and resource allotment. | This is what ADR-0080 and the V1 research warn against: a second workflow authority that can disagree with tasks and gates. It needs a new ADR that supersedes R2.1 §16. |
| P3: no run concept; the project is the pipeline | Portfolio = a list of projects; operations act on project tasks. | Simplest. It may not express "one idea → several formats or episodes", or a portfolio-level pause, without per-project loops. |

## Inferences (not decided)

- **Recommendation for the first design review: P1.** It is the only option consistent with every
  accepted architecture constraint, and the donor shows it is sufficient for resume and progress.
- **What to prove first.** The open part is the portfolio resource limit. The first V2 spike should
  show whether the existing queue admission and `worker_lease` can enforce a cross-project ceiling
  and a portfolio pause without a new state holder. Only a proven failure justifies P2.
- **The sponsor's wishes, in dependency order:**
  1. **V1.x:** the Agent per-session budget reservation. It unlocks story and script writing with
     the host Agent in release mode, is independent of V2 and closes a V1 open item.
  2. **V2-01:** the staging restore and the portfolio projection (P1 spike).
  3. **M8:** re-run A0 against the V1 candidate. Its evidence names need mapping (fact 6).
  4. **M9:** autonomous research, after M8 and a durable Factual Authority.

## Unknowns

- **Resource ceilings.** Whether `worker_lease` and the queue can express a portfolio-level
  ceiling and a pause without new state.
- **M8's prerequisite check.** Whether M8-A0 accepts the V1 dossier as its "accepted M7"
  prerequisite, or needs a mapping record.
- **Durable Factual Authority.** Whether an accepted durable Factual Authority service exists for
  M9. The M9 spec says it did not on 2026-09-14.
- **The cycle-1 gap.** What cycle 1's journal records as the evidence-backed gap (gate
  condition 4).

## Next steps (research only until the gate holds)

1. Plan the V2 staging restore:
   - branch `v2/main` from `r2-v1.0.0`;
   - keep `v1/maintenance` at the tag;
   - restore the cycle-1 backup set into an isolated database and data root;
   - verify it.
2. **Spike plan (read-only first):** inventory queue admission, `worker_lease` and task
   cancellation for portfolio ceilings and pause.
3. **After the cycle-1 journal:** fill gate condition 4 and draft the V2-01 ADR for `PipelineRun`,
   based on the spike evidence.
