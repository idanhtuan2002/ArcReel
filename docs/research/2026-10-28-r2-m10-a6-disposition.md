# M10 A6 research: Human disposition authority

Date: 2026-10-28. Base: A5 source candidate. Research only until the A6 spec freezes it.

## Source task (M10-A plan Task A6)

Append-only `PASS/REWORK/WAIVE`, CAS head, readiness projection, authorization/command receipts and outbox.
RED: non-Human/model/probe issuance, actor/scope mismatch, incomplete run, subject/profile drift, 30-second
lease admission, receipt replay/conflict, advisory-hash collision, stale CAS, every crash cut, mandatory expiry,
profile TTL above seven days, waiver above 24 hours, forbidden waiver scope, attempts to waive
identity/integrity/closure. Authorization outside the transaction; lease binds actor, command, subject, run,
decision and policy revision and admits on DB time. Receipt-first replay, scoped command guard, stable
profile/run/subject/disposition lock order, final revalidation, atomic decision/head/receipt/outbox append.
Readiness is a recomputed projection; REWORK exposes repair routing with no production mutation port.

## Facts

- Frozen A1 contracts: `DispositionSubject` (run id/digest, profile, decision, waiver bindings, reason,
  requested expiry, expected disposition version), `DispositionAuthorizationRequest`,
  `DispositionAuthorizationLease` (action QUALITY_DISPOSITION, ≤30 s window), `QualityDisposition`
  (custodian identity/evidence, issued==admitted, TTL ≤7 d, WAIVE ≤24 h, supersedes id), `DispositionRule`
  (max TTLs, waiverable rule ids, non-waiverable failure codes), `QualityDispositionCustodianPort`.
  Digest domains `m10.disposition-subject.v1`, `m10.disposition-request.v1`, `m10.quality-disposition.v1`,
  `m10.waiver-binding.v1` exist. Errors `DispositionUnauthorized`, `DispositionStale`, `WaiverForbidden` exist.
- Closest internal donor: A3 profile publication — `InteractiveProfilePublicationCustodian` (JWT bind,
  governance-activated `CheckpointedShowrunnerGrantReader`, DB-time 30 s lease, persisted authorization),
  `ProfilePublicationService.publish` (replay-first, authorize outside tx, lock command, replay, lock current
  grant, lock head, stage, commit) and `QualityProfileRepository` (commands/outbox/authorizations tables).
- A5 provides sealed runs, run heads and `run_validity`; A4 provides receipts.

## Inferences / proposed reuse

- Reuse the A3 custodian/service/repository shapes with action `QUALITY_DISPOSITION`; same grant reader and
  HUMAN_SHOWRUNNER qualification as D2 (the design allows the same Human to review and decide).
- Readiness = run validity CURRENT ∧ head disposition is the newest, unexpired, bound to that exact run and
  profile ∧ decision PASS, or WAIVE whose bindings cover exactly the failed waiverable rules; INDETERMINATE or
  missing evidence, identity/integrity/closure codes are never waivable.
