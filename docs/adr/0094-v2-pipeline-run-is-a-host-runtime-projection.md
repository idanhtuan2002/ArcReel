---
status: accepted
---

# V2 treats a pipeline run as a host runtime projection; portfolio pause and capacity are admission filters

The strategy (§5 item 13) and the V1 research require the first V2 design review to decide whether
`PipelineRun` is a host runtime projection or a new authoritative aggregate. The research is
`docs/research/2026-09-29-r2-v2-start-research.md`, and the sponsor delegated the decision.

**Decision: projection (option P1).**

V2 adds no `PipelineRun` table or authority. A run's state is read from the owners that already
hold it:

- the project and its gate receipts;
- tasks and batches;
- execution attempts;
- masters.

This follows R2.1 §4.5 and §16 (the host owns runtime and workflow status), the hard invariant
`Runtime State ≠ Artifact Truth`, ADR-0080 (no second orchestrator or workflow authority) and the
donor model (OpenMontage derives pipeline progress from its stage checkpoints).

**Portfolio controls are queue admission, owned by the host's existing settings store.**

- **Pause.** A paused project's queued tasks are not claimed. The pause list is the system
  setting `project_admission.paused`, a JSON array of project names. Pausing only stops new
  claims: running tasks finish, and their queued tasks stay queued and resume on unpause. Cancel
  stays the existing task and bulk cancel.
- **Capacity.** The system setting `project_admission.max_running_per_project` caps the running
  tasks per project, per media lane. `0` or unset means unlimited. The count is derived from
  `tasks`, so it is a projection with no counter to drift.
- **Enforcement point.** Both filters live in `TaskRepository.claim_next`, next to the existing
  provider-pool and dependency filters. A project at its ceiling does not block other projects'
  tasks behind it.

**Validation** (the spike, required before acceptance):

- a paused project's tasks stay queued while other projects' tasks are claimed, and they are
  claimed after unpause;
- a project at its ceiling does not block a later-queued task of another project;
- dependencies are still honoured;
- after a restart the ceiling holds, because it is computed from persisted `running` rows.

## Considered options

- **A new `PipelineRun` aggregate (P2).** Rejected: it creates a second workflow authority that
  can disagree with tasks and gates. It needs superseding R2.1 §16 and ADR-0080, and no evidence
  requires it.
- **No run concept at all (P3).** Pause and capacity would need per-project loops in every
  caller. Admission filters give the same result with one enforcement point.
- **A dedicated admission table.** Not needed: the system settings store already holds operator
  runtime configuration, such as the provider pool limits.

## Consequences

- **Surfaces.** V2 portfolio views and commands are read models plus the two admission settings.
  A later packet adds the operator UI and API.
- **Evidence gate.** Any future request for run-scoped state must first show a gap this
  projection cannot represent.
