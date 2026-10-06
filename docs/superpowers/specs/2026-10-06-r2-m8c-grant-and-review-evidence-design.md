# M8-C Governance grant and exact-frame review evidence

Status: proposed implementation spec. This packet defines the first production-capable authority boundary for a spatial pair decision. It does not issue a grant, accept ADR-0103, enable a route, or authorize a live migration.

## Outcome and existing constraints

A reviewer with an explicit Governance-issued project grant can inspect the exact MASTER and REVERSE PNGs and submit an accountable pair decision. A missing, stale, forged, expired or revoked grant, or a review of different bytes, must deny. Existing `PairDecisionCommandV1` and `PairDecisionV1` remain byte-stable historical contracts. The current internal pair writer and current APPROVE reader remain deny-by-default at a production boundary until the packet's gates pass.

The accepted M5C §6.2 grant boundary, ADR-0103, and [source research](../../research/2026-10-06-r2-m8c-showrunner-grant-and-review-custody.md) supply the authority rationale. The first implementation supports one deployment-pinned Ed25519 verification key. Key rotation and disaster recovery require a separately reviewed procedure; a key mismatch or rollback uncertainty closes grant-based decisions.

## Signed event contract

The importer accepts at most 65,536 bytes of UTF-8 JSON with exactly `body` and `signature`. The `body` is an object with these exact fields:

| Field | Rule |
| --- | --- |
| `schema` | Literal `governance.showrunner_grant_event.v1` for domain separation. |
| `event_type` | `ISSUE` or `REVOKE`. |
| `user_id`, `project_name`, `principal` | Exact nonempty, unpadded scoped identities; no wildcard. |
| `role` | Literal `HUMAN_SHOWRUNNER`. |
| `sequence` | Strict positive integer, increasing by one per exact scope. |
| `previous_event_digest` | Null at sequence 1; otherwise the immediately preceding committed event's digest. |
| `issued_at` | UTC text `YYYY-MM-DDTHH:MM:SSZ`; monotonically increasing within the scope and no later than database time at import. |
| `not_before`, `expires_at` | Present only for ISSUE in the same UTC format; `issued_at <= not_before < expires_at`, and expiry is later than database time at import. |
| `signer_key_id` | Exact identifier of the pinned offline issuer public key, included in signed bytes. |

`signature` is unpadded base64url encoding of exactly 64 Ed25519 signature bytes. The signed payload is `lib.content_digest.canonical_json_bytes(body, allow_nan=False)`. `event_digest` is `sha256:` plus SHA-256 of those bytes. Parsing rejects duplicate keys, unknown fields, alternate timestamp spelling, invalid UTF-8, overlong input, booleans as sequence numbers, and noncanonical envelope/body bytes. The importer verifies the detached signature before it changes any row. Invalid input returns a sanitized category without echoing a submitted signature or event.

The importer owns one event log and head row per exact scope. Under a single PostgreSQL transaction it locks the head, checks the pinned issuer key, signature, sequence, predecessor, timestamps and event transition, appends the immutable event and advances the head. ISSUE is valid only as the first event or immediately after REVOKE; REVOKE is valid only after ISSUE. ISSUE makes that scope valid during its stated interval; REVOKE terminates it immediately. A later signed ISSUE with the next sequence may regrant the same scope. A byte-identical retry may return the existing event only after rechecking stored bytes/digest; a different event at an existing sequence conflicts. No route used by the pair service may write this ledger.

The pair writer takes the scoped grant-head lock inside its existing source transaction, after its current pair/target/binding/M7 lock order. It validates the latest event bytes and digest, `ISSUE` state, exact scope, pinned issuer and current database time before appending or replaying a decision. Importer revocation and pair decisions therefore serialize on that same head. A decision committed before revocation remains historical; a decision or replay that acquires the head afterward denies. No grant row, verifier configuration, reachable database or trustworthy recovery checkpoint means denial. The event log alone cannot detect restoration of an older whole database: the deployment/recovery process must compare a separately retained signed head checkpoint before production enablement.

## Review session and decision evidence

A session starts only after an interactive JWT authenticates a principal and the current grant verifies. API keys and `AUTH_ENABLED=false` anonymous mode are rejected. The server creates an opaque session ID valid for at most ten minutes, bound to exact user, project, principal, Scene/Shot version refs, binding ID/version/envelope/core digests, ordered MASTER/REVERSE receipt IDs/digests, and SHA-256 of each verified PNG byte stream. It stores a digest of this immutable snapshot. The ID is never treated as bearer authority and is not placed in a public file URL.

Each authenticated frame fetch rechecks the same session scope and current sources, serves only its bound PNG bytes with `Cache-Control: no-store`, and records an immutable delivery record identifying the role, content digest and response attempt. The client hashes the returned Blob bytes, completes image decoding, and explicitly acknowledges both named roles/digests. The server stores that acknowledgment with the authenticated principal, session ID and time. A client-reported digest is evidence of an assertion, not proof that a human perceived an image or that the server sent other bytes.

The new versioned pair command refers to the review session and its server-computed evidence digest; these fields participate in the command digest. In the same transaction as a new pair append, the server checks the authenticated principal, current grant, unexpired and unused session, immutable delivery and two-role acknowledgment records, and all source refs/digests/PNG bytes. The session becomes consumed with that decision. Exact command replay reauthenticates the current grant and sources, verifies the stored review evidence, and returns the original immutable decision; it does not require the historical session to remain unexpired or mint replacement evidence. A changed decision, observation or review reference is a new command and must satisfy a fresh session. A source advance or byte change invalidates the session.

The evidence names what can be proven: server-selected and verified bytes, authenticated fetch attempts, client-reported digest/decode, explicit acknowledgment and reviewer decision. It must never be labeled proof of human visual perception.

## Implementation slices and verification gates

1. Pure canonical event parser, signature verifier adapter and fixed vectors. Include malformed/duplicate/oversize JSON, changed signed field, wrong key/scope, expiry, and re-encoded body tests. No database or route in this slice.
2. Governance event log/head migration and importer. Disposable PostgreSQL tests must prove scoped first writer, exact retry, conflicting sequence, predecessor gap, rollback, concurrent revoke/decision lock ordering, expiry and regrant. Add a recovery checkpoint gate before any production enablement.
3. Authenticated review session/bytes/evidence store with two-role browser acknowledgment. Tests must prove API-key/auth-disabled rejection, role swap, missing decode/ack, stale PNG, source advance, expiry, principal/project mismatch and no public static path.
4. Versioned pair command/decision and production authority adapter. Preserve V1 digest vectors; force same-transaction rechecks on first decision and exact replay. Verify current APPROVE withdrawal and affected downstream readers before wiring READY.
5. Exact-HEAD independent review, affected/full required checks, key custody/recovery drill and explicit activation decision. Until then, production APPROVE, READY, promotion and generation stay closed.
