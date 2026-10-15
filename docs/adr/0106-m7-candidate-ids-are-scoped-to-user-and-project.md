---
status: accepted
---

# A new M7 master candidate id is scoped to its user and project

**Found by:** the M8-F integrated run on 2026-10-15. The sponsor delegated technical decisions
after research.

## Context

ADR-0096 registers every Gate C master as an M7 candidate object whose id is
`m7_candidate_id(artifact_key, generation_candidate_id)`. The docstring promised uniqueness "per
artifact within a project", but the id has no project component. `candidate_objects` has a global
primary key on `candidate_id`, and three tables reference it through a foreign key.

Host generation ids repeat across projects: `CAND-SH01-V1`, `CAND-FINAL-V1` and so on. As a result,
the second project of any user that approves the same shot or final version at Gate C fails with
`master_conflict: candidate 'm7c:…' conflicts with an existing candidate in this scope`. The second
project cannot approve masters, which blocks every multi-project use of V2.

## Decision

1. **New candidates get a scoped id.**
   `scoped_m7_candidate_id(user_id, project_name, artifact_key, generation_candidate_id)` hashes
   `m7c-scoped-v1`, the user, the project, the artifact and the generation id. It keeps the `m7c:`
   prefix and the 40-hex length.
2. **Existing candidates keep their id.** `resolve_m7_candidate_id` returns the legacy id when the
   same user and project already registered the candidate under that id. Otherwise it returns the
   scoped id. A legacy id registered by another project is never adopted.
3. **Every place that derives an id uses the resolver.** That covers `promote_staged`,
   `FileMasterProjection` (it now requires a candidate lookup) and the backfill script. Gate C
   projects with the `candidate_id` that its own promotion returned, instead of recomputing it.
4. **No migration.** Stored ids, foreign keys and the primary key are unchanged. Format candidates
   keep `m7_candidate_id(slot_key, execution_id)`, because execution ids are already unique.

## Consequences

- Masters approved before this change still verify, project and replay under their legacy ids.
- Retrying an approval whose candidate was already registered resolves to the same id, so it stays
  idempotent.
- Tests that expected the unscoped id for new promotions now expect the scoped id.
- The defect also exists on any V2 deployment that holds more than one project per user. Before this
  fix, such a deployment could not approve a second project's shot. Those requests failed with 409 and
  wrote nothing, so no data needs repair.

## Rejected

- **A composite primary key `(user_id, project_name, candidate_id)`.** It needs a migration of four
  tables and their foreign keys, which is a larger change to an accepted M7 schema with no extra
  safety.
- **Rewriting legacy ids in a data migration.** The rows do not store the generation id, so the
  rewrite would depend on file manifests and risk a divergent head.
