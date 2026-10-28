# M10 A6: Human disposition authority

Status: design on `design/r2-m10-a6-disposition` (base A5 candidate `d84993648`).
Research: [2026-10-28 A6 research](../../research/2026-10-28-r2-m10-a6-disposition.md). Source: M10-A plan Task A6.

## Boundary

A qualified Human showrunner issues `PASS`, `REWORK` or `WAIVE` over one exact sealed, current run.
Dispositions are append-only; one CAS head per subject/profile; readiness is a recomputed projection.
No model, probe, API key or background identity can issue. REWORK exposes repair routing only — there is
no production mutation port. No router, default registration, export or packaging (M10-B).

## Reuse

The A3 publication path is the donor: interactive JWT binding, governance-activated
`CheckpointedShowrunnerGrantReader`, a ≤30 s lease issued on PostgreSQL `clock_timestamp()` and persisted
before use, then admitted on DB time inside the write transaction (`lock_current_grant`). A5 supplies sealed
runs, run heads and the validity projection (refactored to run inside the caller's transaction).

## Issuance

`DispositionService.issue(request: DispositionAuthorizationRequest) -> QualityDisposition`:

1. Re-authenticate; receipt-first replay in its own transaction (no governance activation for a replay).
2. `DispositionCustodian.authorize_disposition(request)` outside the write transaction: activation, current
   grant, DB-time lease (`admit_not_after = min(issued+30s, grant expiry)`), persisted authorization row.
3. Write transaction, lock order: command advisory key → stored authorization + current grant + lease
   window on DB time → master authority rows of the run subject (sorted) → profile head (share) →
   run head (share) → disposition head (`FOR UPDATE`, absent head created under an advisory identity).
4. Revalidate: run exists and its recomputed digest equals `quality_run_digest`; subject/profile identities
   equal; the run is the run head and its validity is `CURRENT`; `expected_disposition_version` equals the
   head version (0 when absent) else `M10_STALE_HEAD`.
5. Decision rules (pure, `r2/quality/dispositions.py`):
   - PASS: every requirement met — SATISFIED/NOT_APPLICABLE slots ≥ `minimum_satisfied_slots` (ALL: all) and
     no FAILED/INDETERMINATE slot in a counted requirement.
   - WAIVE: every unmet slot is FAILED (INDETERMINATE = incomplete evidence, never waivable); waiver bindings
     cover exactly the failed slots' rule ids, each in `waiverable_rule_ids` and not a non-waivable code;
     scope `requirement:slot`; identity/integrity/closure/currentness are never waivable.
   - REWORK: always admissible over a current run; carries repair routing = unmet slots.
   - Expiry: `requested_expires_at` after DB now and within `max_disposition_ttl_seconds` (≤7 d) and, for
     WAIVE, `max_waiver_ttl_seconds` (≤24 h). Violations → `M10_WAIVER_FORBIDDEN` / `M10_DISPOSITION_STALE`.
6. Append disposition (`supersedes_disposition_id` = previous head), head CAS, command receipt and outbox event
   in that one transaction. Lease or grant failure → `M10_DISPOSITION_UNAUTHORIZED`.

## Readiness projection

`quality_readiness(...) -> Readiness(state READY | NOT_READY, reasons, repair_slots)` at DB time:
READY only if the head disposition is PASS or WAIVE, unexpired, bound to the run that is still the run
head and still `CURRENT`, and its waivers still cover exactly the run's failed slots. REWORK, expiry, a newer
run, stale/invalidated runs → NOT_READY with reasons. Never stored as a boolean.

## Persistence (migration after `57f67bae0cb4`)

Append-only with refusal triggers and 1 MiB JSON ceilings (ORM + migration, both dialects):
`m10_disposition_authorizations`, `m10_quality_dispositions`, `m10_disposition_commands`
(operation `ISSUE_DISPOSITION`), `m10_disposition_outbox`; mutable CAS `m10_disposition_heads`.

## Gates

RED-first for every task bullet: non-Human/API-key/expired/wrong actor, scope mismatch, incomplete or
non-current run, subject/profile drift, lease window 0/30/>30 s and expiry on DB time, replay/conflict,
advisory collision only serializing, stale CAS, crash cuts (before lease, after lease before write, after
write), mandatory expiry, TTL >7 d, waiver >24 h, forbidden waiver scope, waiving INDETERMINATE/identity;
concurrent first-call convergence and both-order races with real promotion/sealing on PostgreSQL;
migration cycle; static gates; independent review; `R2_M10_A6_CANDIDATE.json`.
