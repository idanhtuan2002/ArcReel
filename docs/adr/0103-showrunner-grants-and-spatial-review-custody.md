---
status: accepted
---

# Governance issues project-scoped Showrunner grants; Production records exact-frame review evidence

**Sponsor acceptance (2026-10-13):** the sponsor accepted this ADR ("Chấp nhận ADR, làm luôn"). Acceptance fixes the architecture. Production APPROVE stays denied until the activation items under "Consequences" are proven on a real host: operator-custodied verification key, pinned image, retained grant-head checkpoint, and restore drill.

The M8-C pair writer currently has only a test authority. The accepted M5C authority policy forbids deriving a `HUMAN_SHOWRUNNER` grant from a host admin role, API key or single-operator session. Choose a Governance-owned, explicit project-scoped grant ledger populated only by signed manual issue/revoke events from an offline issuer. The pair service receives a transaction-bound read/verify port, never a grant writer. This is a proposed architecture decision until root-of-trust custody and implementation are reviewed; production APPROVE remains denied.

## Decision

1. A grant is scoped to exact `(user_id, project_name, authenticated_principal, HUMAN_SHOWRUNNER)`, an issuer key ID, an issue event, validity interval and a monotonic current event head. Revocation appends a signed successor. No wildcard project, implicit admin conversion or route for self-issuance exists. An unconfigured/invalid issuer, missing grant, expiry, revoked head or unavailable ledger denies.
2. Governance alone imports verified events and advances the grant head. The pair writer locks and verifies that head after its existing source-lock sequence and before decision commit. Revocation and decision therefore serialize on the same row. Every new decision and exact replay authenticates current grant; replay returns historical evidence without appending another pair decision or authorization. Revocation stops new commands/replays but does not rewrite a historically authorized decision. Withdrawing an existing APPROVE requires a separate effective-pair REJECT or a specifically designed emergency invalidation authority.
3. Pair approval requires a short-lived, scoped review session for the exact two derived PNGs and a versioned decision envelope referencing immutable delivery/acknowledgment evidence and inline observations. Frame and decision routes require an interactive session JWT plus the current grant; API keys and authentication-disabled anonymous mode are denied. The server serves bytes through an authenticated endpoint and rechecks current source custody at decision time. The client reports a digest check and completed image decode for each role, and the reviewer explicitly acknowledges both. These records establish returned-and-acknowledged bytes, not provable human perception. No new public static frame URL, filesystem path, or bearer token in a URL is accepted.
4. Existing `PairDecisionCommandV1`, `PairDecisionV1` and their digests remain historical bytes. The production route needs a new versioned command/decision/evidence shape; it cannot overload `authorization_ref` with review evidence or treat the synthetic V1 vectors as live approval proof. Until that schema, grant issuer, review flow, route and adversarial PostgreSQL tests pass independent review, the production pair authority stays deny-by-default.

## Why this boundary

The [source comparison](../research/2026-10-06-r2-m8c-showrunner-grant-and-review-custody.md) found no production grant issuer. A pair-owned allowlist would violate the frozen single-writer governance boundary; V1 session authentication has no project grant; a signed file alone cannot serialize with revocation during a pair transaction. A Governance ledger and read-only pair port preserve one issuer and give the decision a verifiable currentness point. The browser acknowledgment makes the exact bytes inspectable without claiming software can prove a human viewed them.

## Consequences

The next implementation packet must define offline issuer key custody/rotation, canonical signed-event vectors, ledger schema/import and rollback, review-session delivery/acknowledgment records, versioned pair evidence, route authentication, and same-transaction grant/source checks. The current Compose deployment has no trusted key/checkpoint mount and uses a floating image tag; the V1 backup attestation is unsigned. Activation therefore also requires a pinned image, an operator-custodied verification key outside mutable application data, and a separately retained monotonic grant-head checkpoint checked after restore. No live key, signed grant, migration, public route or provider call is authorized by this proposed ADR.
