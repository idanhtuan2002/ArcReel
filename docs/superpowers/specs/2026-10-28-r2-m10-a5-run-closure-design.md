# M10 A5: multi-assessor run closure and validity

Status: design for implementation on `design/r2-m10-a5-run-closure` (base A4 candidate `a57d7c631`).
Research and decisions: [2026-10-28 A5 research](../../research/2026-10-28-r2-m10-a5-run-closure.md)
(D1 factual fail-closed, D2 HUMAN_SHOWRUNNER qualification). Source task: M10-A plan Task A5.

## Purpose and boundary

Seal an immutable `QualityRun` over an exact approved master and published profile from stored,
re-verified observations, and project its operational validity at read time. A5 issues no Human
disposition (A6), builds no Factual Authority, adds no model adapter, export, router or default app
registration, and changes no A1–A4 contract, digest domain, error code or table.

## Producers admitted in the first packet

| Slot kind / class | Admitted evidence | Otherwise |
|---|---|---|
| TECHNICAL / DETERMINISTIC | A4 `m10_quality_probe_observations` row whose full A4 chain replays | missing |
| NARRATIVE / HUMAN | A5 Human observation recorded by a qualified showrunner (below) | missing |
| FACTUAL (any class) | none — `FactualReadPort` has no authoritative implementation (D1) | `M10_REQUIRED_EVIDENCE_MISSING` |
| CONTINUITY, PERCEPTUAL, ACCESSIBILITY, any MODEL/AUTHORITY class | none qualified (D2) | `M10_REQUIRED_EVIDENCE_MISSING` |

A slot whose kind/class has no admitted producer can never be satisfied, waived or marked
not-applicable. A profile requiring such a slot cannot seal a run; that is the intended fail-closed state.

## Human observation recording

`HumanObservationService.for_request(request, sessions, *, interactive_token, governance)` records one
`NarrativeObservation`. Steps: revalidate the interactive JWT and bind `(user.id, user.sub)` to
`(user_id, actor_id)`; read the current signed `HUMAN_SHOWRUNNER` grant for that exact scope through the
existing governance-activated `CheckpointedShowrunnerGrantReader` (as A3); resolve the exact stored profile
revision and approved root (as A4); require the target slot to be `NARRATIVE`/`HUMAN` with
`qualification_policy_digest` equal to the code-embedded policy `m10.qualification.human-showrunner.v1`;
derive `assessor_identity=actor_id`, `assessor_qualification_ref=<grant event digest>`,
`independence_group="human:"+actor_id`, `producer_conflict=False` (the showrunner approves but does not
generate master bytes); recompute every digest; append the row and an M10 command receipt atomically.
Same command key + same canonical body replays; a different body conflicts. Caller-supplied
qualification, independence, digests or identities are recomputed, never trusted.

## Run closure (pure, `r2/quality/runs.py`)

`close_run(profile, subject, observations, *, run_id, completed_at) -> QualityRun`:

1. Every observation must bind the exact `subject_digest`, `config_digest` of its slot rule (technical) or
   rubric (Human), and a `(requirement_id, slot_id)` present in the profile; mismatches refuse.
2. Map `ObservationType` → `AssessorKind`; the slot's kind and assessor class must match the producer.
3. Slot state from its observations: none → refuse sealing (`M10_REQUIRED_EVIDENCE_MISSING`);
   all PASS → SATISFIED; any FAIL without escalation → FAILED; INAPPLICABLE only from a technical
   observation that A4 marked policy-authorized → NOT_APPLICABLE; INDETERMINATE → INDETERMINATE.
4. Disagreement (PASS and FAIL in one slot, or across slots of one requirement) requires observations of
   the requirement's `escalation_requirement_id`; without them the requirement is INDETERMINATE.
5. A requirement is met when at least `minimum_satisfied_slots` slots are SATISFIED/NOT_APPLICABLE with
   pairwise distinct independence groups. Model evidence never counts for a HUMAN slot.
6. Recompute `observation_closure_digest` (`m10.observation-closure.v1` over sorted bindings),
   `requirements_digest`, `subject_digest`, `profile_digest`; build `QualityRun` with sorted refs and
   A4 execution refs. Sealing records completeness, not acceptability: a complete run with FAILED slots seals.

## Validity projection (pure + read)

`project_validity(run, current, now) -> RunValidity` with precedence
`INVALIDATED > STALE > SUPERSEDED > EXPIRED > CURRENT`:

- INVALIDATED: any referenced row missing, digest drift, A4 chain no longer replays, or a Human
  observation's grant was revoked before the run.
- STALE: the approved root or any dependency head (`MasterAuthorityRepository.get_current` for every
  `dependency_heads` key, sorted) differs from the run subject; content basis digest differs.
- SUPERSEDED: a newer sealed run exists for the same subject+profile, or a newer profile revision with
  `REEVALUATE_CURRENT` exists.
- EXPIRED: an observation is older than its kind's `FreshnessRule.max_age_seconds` at `now` (DB time).
Historical reads always return the sealed run unchanged; validity never mutates it.

## Persistence (migration after `07fd34535384`)

Append-only, scoped, user FK RESTRICT, ≤1 MiB JSON checks, UPDATE/DELETE refusal triggers (PG + SQLite):

- `m10_quality_human_observations` PK `(user_id, project_name, observation_id)`; full observation JSON +
  digest, grant event digest, command key; unique `(user_id, project_name, actor_id, command_id)`.
- `m10_quality_runs` PK `(user_id, project_name, run_id)`; full `QualityRun` JSON + digest, subject and
  profile identities, command key.
- `m10_quality_run_commands` PK `(user_id, project_name, actor_id, operation, command_id)` with operation
  in `('RECORD_HUMAN_OBSERVATION','COMPLETE_RUN')`; request digest, result ref/digest, receipt JSON.
  (A3's `m10_quality_commands` is constrained to `PUBLISH_PROFILE` and is not widened.)
- `m10_quality_run_heads` PK `(user_id, project_name, subject_digest, profile_id)`; the only mutable row:
  current run id/digest, CAS by expected run id; created absent under the command advisory lock.

## Locking and transactions

Lock order follows the M10 design §6: scoped command advisory key → master authority rows read (sorted)
→ profile revision → run head `FOR UPDATE`. Run completion: authenticate, lock, replay receipt first,
load every referenced observation and re-verify it (A4 replay chain; Human row digest + grant), verify
current root/dependency heads, `close_run`, append run + receipt, CAS head — one transaction, PostgreSQL
only. No subprocess or network I/O inside the transaction.

## Errors

Missing/unadmitted evidence → `M10_REQUIRED_EVIDENCE_MISSING`; changed root/dependency →
`M10_SUBJECT_STALE`; profile mismatch → `M10_PROFILE_STALE`; same key different body →
`M10_COMMAND_REPLAY_CONFLICT`; lost head CAS → `M10_STALE_HEAD`; auth/grant failure →
`M10_REQUIRED_EVIDENCE_MISSING` (unknown scope indistinguishable).

## Owned paths

`r2/quality/runs.py`; `lib/db/models/quality_runs.py`; `lib/db/repositories/quality_runs.py`;
`server/services/quality_runs.py`; `alembic/versions/<rev>_quality_run_closure.py`; additive exports in
`lib/db/models/__init__.py`; mirrored tests under `tests/unit` / `tests/integration`; evidence under
`docs/r2/evidence/m10-a5-reviews/`. The A4 scope guard keeps verifying A4 bytes; A5 adds no route or
capability entry.

## Qualification gates

RED-first tests for every A5 task bullet (missing/duplicate slots, N-of-M, independence, Human+model,
disagreement/escalation, invalid INAPPLICABLE/INDETERMINATE, mixed subject/profile, stale tool/config,
factual fail-closed, producer conflict, unqualified reviewer, cohort leakage), real PostgreSQL replay,
both-order head races, supersession/deletion invalidation with historical reads, migration cycle on
SQLite and PostgreSQL, affected-domain static gates, one independent review, then
`R2_M10_A5_CANDIDATE.json`. No production activation.
