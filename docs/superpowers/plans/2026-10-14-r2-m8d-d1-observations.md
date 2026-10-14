# R2-M8D D1: persist lineage-bound observations

**Parent plan:** [`2026-09-13-r2-m8d-learning-recommendations.md`](2026-09-13-r2-m8d-learning-recommendations.md), Task D1.
**Spec:** [`2026-09-13-r2-m8-canvas-learning-multiformat-design.md`](../specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md), §3 invariant 6, §5, §6 and §9.
**Base:** `r2-v2/main` `5dc0eec1` (M8-C closed, `R2_M8C_CLOSURE_2026-10-14.md`).

## Current state (facts)

- **The contracts and ports already exist** from A0:
  - in `r2/contracts/advanced_creative.py`: `LearningObservation`, `MetricWindow`, `ExperimentDesign`, `LearningRecommendation`, `RecommendationDecision`;
  - in `r2/advanced_creative/ports.py`: `ObservationRepository` and `RecommendationService`.
- **No persistence, service, route or fold exists** for them.
- **M8-A command receipts (`m8_command_receipts`, `ExplorationRepository.lock_command_key` / `record_command`) are reusable** for idempotent commands scoped by `(user, project, actor_scope, operation)`.
- **The parent plan names migration `8d8c4a0e0001`, but that id is taken** by `add_production_binding_authority`. The head is `913c4a0e0001`, so D1 uses `914c4a0e0001`.
- **The internal sources for D2 are:**
  - `api_calls` (usage, now bound to `execution_id`);
  - `execution_attempts` (M7);
  - `gate_publish_approval_decisions`;
  - `adaptation_evaluation_reports`.
- **Platform sources (YouTube/TikTok) are fixture-only.** No packet authorizes live platform calls.

## Decisions (agent-chosen under sponsor delegation)

1. **Observation identity** is the scope `(user_id, project_name)` together with:
   - `source_family`, `source_record_id`;
   - `metric_name`, `metric_definition_version`;
   - `window.starts_at`, `window.ends_at`, `window.timezone_name`, `window.aggregation`.

   Exactly one original (`correction_of IS NULL`) exists per identity.
2. **Observation digest** is the canonical digest of the observation without `ingested_at`, which the server stamps. Ingesting with the same identity:
   - with the same digest, returns the stored observation (replay);
   - with a different digest and no `correction_of`, is refused (`ObservationConflict`). A change must be a correction.
3. **Corrections are a linear chain.**
   - A correction names the current tip of its identity (`correction_of`) and carries the same identity.
   - The tip is locked, and the repository enforces one direct successor per record (a unique `correction_of`). Two concurrent corrections of the same tip therefore produce one winner. The loser is refused, and the caller re-reads before retrying.
   - A correction never rewrites its predecessor.
4. **Missing outcomes form a closed set**: `MISSING`, `PRIVATE`, `DELETED`, `NOT_YET_AVAILABLE`.
   - When `metric_value` is null, a reason from this set is required.
   - When there is a value, the reason must be null.
   - This check sits in a pure validator in `r2/learning`; the accepted A0 contract is unchanged.
5. **Command idempotency.** The observation row is its own command receipt, with a `command_id` that is unique in its scope and the command digest stored alongside.
   - Replaying the same command with the same digest returns the stored result before any other check.
   - The same `command_id` with different content is a conflict (`CommandConflictError`).
   - `m8_command_receipts` is not reused: its `operation` check constraint belongs to the accepted M8-A schema, and changing it would need a separately designed revision (`M8_ACCEPTED_SCHEMA_CHANGE_REQUIRED`).
6. **Cutoff fold.** A pure function `current_as_of(records, cutoff)` resolves each identity to the latest record in its chain with `ingested_at <= cutoff`, so a late correction after the cutoff is invisible. Recommendation evidence (D3) pins this cutoff.
7. **Scope.** Every read and write takes `(user_id, project_name)`, and `lineage.project_name` must equal the project. A foreign or unknown observation id reads as not found.
8. **No route in D1.** Internal adapters (D2) and a route (D3) come later.

## Tasks

- [x] **Pure layer** in `r2/learning/observations.py`:
  - identity key, digest, missing-reason validation;
  - correction admissibility;
  - `current_as_of` fold;
  - unit tests.
- [x] **Migration `914c4a0e0001`** with model `M8LearningObservationModel`:
  - table `m8_learning_observations`, append-only;
  - unique `(user_id, project_name, observation_id)`;
  - a partial unique index on the identity for originals;
  - unique `(user_id, project_name, correction_of)`;
  - a check constraint for the value/reason pair.
- [x] **Repository** `LearningObservationRepository` in `lib/db/repositories/learning.py`: `ingest`, `get`, `chain`, `list_as_of`, implementing `ObservationRepository`.
- [x] **Tests** on SQLite and on PostgreSQL 18:
  - exact replay;
  - divergent duplicate;
  - correction chain and a branch refusal;
  - a concurrent correction race (PostgreSQL);
  - late correction against the cutoff;
  - missing/private/deleted;
  - cross-scope invisibility;
  - command conflict.
- [ ] **Gates**: only the related tests, plus static gates and an independent Codex review before merge.

## Out of scope

D2 adapters, the D3 recommendation lifecycle and UI, D4 evidence sealing, any live platform call.
