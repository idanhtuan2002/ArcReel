# M8-C spatial revision append boundary

Status: source-grounded research, not an implementation or test pass. Inspected from the accepted M8-B base through the M8-C worktree.

## Current path

The public `POST /projects/{project_name}/m8/exploration/revisions` route accepts an entire caller-authored `ExplorationRevision` in `AppendRevisionRequest`, then calls `ExplorationService.append_revision` (`server/routers/advanced_creative.py:32-36,71-85`). The service checks project and creator scope and forwards the body to `ExplorationStore.append_revision` (`r2/advanced_creative/exploration.py:177-199`). This is appropriate for existing user-authored Canvas revisions, but the route does not verify a SpatialCandidate's `execution_id`, raw response digest, model/route fingerprint, schema/prompt version or source media custody.

The accepted M8 spatial spec requires bounded M7 executions, retained raw/model/source/normalizer identities, schema validation before normalization, and no revision on malformed response, missing source, provider failure or normalization mismatch (`docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md:646-658`). A caller-authored spatial revision could assert `VISIBLE` evidence without any of those checks. Pydantic shape validation alone cannot prove execution or media authority.

## Required boundary

The generic public append route and its service must reject `ExplorationKind.SPATIAL` before any write with the existing `m8_candidate_conflict` category. A C1 worktree change now adds that guard and a unit test, but it is dirty WIP and has no independent acceptance. A server-owned spatial completion service must read one terminal successful M7 execution and its exact raw-response object/digest, route/model fingerprint, prompt/schema version and the two source-frame derivation receipts. It must rehash response and frame bytes, validate the R2 response/overlap schemas, normalize, construct the `SpatialCandidate` and append it with the existing M8 CAS/idempotency semantics in one unit of work. The `execution_id` and source refs in the resulting candidate are server-derived, never trusted from a client body. A duplicate completion with the same execution and digest is an exact replay; a different raw body or source identity for that execution is a conflict. Failed/cancelled/unknown attempts, missing or stale source, invalid schema and normalization mismatch create no revision.

The append service may retain the candidate as evidence even when a pair admission is absent or unsuitable; pair admission is required before production promotion of seam/direction constraints. Tests must exercise both the public-route rejection and the server-owned execution-to-revision path, including same-command replay, changed-body conflict and rollback. No currently inspected runtime path satisfies this server-owned append flow.
