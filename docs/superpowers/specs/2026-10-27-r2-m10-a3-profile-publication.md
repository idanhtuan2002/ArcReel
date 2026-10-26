# M10 A3: scoped profile persistence and Human publication

PROPOSED. Implementation base: `dca138da92ca7bb3e8b6adbb44cacdfce84f0f84`.
This separately reviewed packet continues the user's sequential M10 instruction
on V2. It does not accept M9, full M10, production activation, or deployment.
Two independent design PASS decisions on one exact candidate and a separate
hash-bound acceptance are required before product or migration code.

## Purpose, alternatives and boundary

Store immutable quality-profile revisions and publish one revision through
an authenticated Human action, with CAS, exact replay and atomic receipt/event
creation. Preserve the accepted A0/A1/A2 models, digest domains, operations and
source files. The packet manifest owns the exact paths; no directory grants
additional scope.

Selected proposal: reuse A1 data/digests, A2 errors/interfaces, the existing
interactive-JWT verifier and activated checkpointed Showrunner reader; adapt
the qualified M8 transaction pattern to M10-owned tables. Directly persisting
M8 candidates would give profiles the wrong identity and receipt namespace.
The V1 session-only adapter and generic CurrentUser/admin/API-key authority
cannot issue this action. A second grant ledger would duplicate custody and
is excluded.

The new action-specific issuer below is the proposed qualification of the
previously missing M10 publication custody seam. A Showrunner grant alone
still does not authorize a publication. No existing role contract changes.
No router, application activation, provider, master-row access, probe,
disposition writer, export or outbox delivery is included. Source and disposable
PostgreSQL qualification are separate from production authority.

## Authentication and action custody

`server.auth.get_current_interactive_user(token)` is the only session verifier
used by the new host adapters. It requires enabled authentication, a valid
interactive session JWT and bounded session claims, and rejects API keys,
download tokens, missing/invalid tokens and anonymous mode. Derive tenant from
the returned `id` and principal from `sub`; require exact equality with the
request's user/actor. Never infer Human authority from `CurrentUserInfo`
construction or its `role` field. Re-run this verifier at final admission, so
an expired token, disabled authentication or changed signing secret refuses.

The request-scoped adapters hold the bearer only in private memory; it is
excluded from repr, errors, logs, storage and domain objects. They expose no
provider credential read/write surface. A future router must supply the
actual bearer and project path, and is a separate activation gate.

Proposed host policy constants: `m10.profile-publication.interactive-human.v1`,
version `1`. This policy permits only `PROFILE_PUBLICATION`/`PUBLISH_PROFILE`,
for the interactive principal's exact scoped project with a current authentic
`HUMAN_SHOWRUNNER` grant. It grants no disposition, production or packaging
action. These constants and their behavior are owned by this reviewed source,
not caller configuration.

`InteractiveProfilePublicationCustodian` implements the unchanged A2
`ProfilePublicationCustodianPort`. Its only supported public factory is async
`from_activated_governance(sessions, *, interactive_token, read_directory,
socket_directory, expected_uid, expected_gid)`. It calls the unchanged
`verify_governance_activated_startup` and captures that verifier's returned
`CheckpointedShowrunnerGrantReader`. A missing socket/configuration or failed
archive/current-head verification refuses; the public factory accepts no
caller-supplied reader. Internal construction requires a module-private seal
created only after that verifier succeeds. Verify the interactive JWT before
starting any activation/archive I/O. A public-snapshot-only reader or a
constructed object is not an activation proof. The adapter is request-scoped
and never caches activation across requests. Disposable fixtures must exercise
the real verifier/independent archive protocol, not patch it to return a reader.
This packet changes no existing ceremony and performs none on production.
The allowed external capabilities are the scoped PostgreSQL session and the
existing read-only local governance archive IPC/file reader. Arbitrary sockets,
provider HTTP, upload/publish and new credential I/O are excluded.

`authorize_publication(request)` runs before the publication transaction:
revalidate the A1 request and embedded caches; verify the interactive session;
verify the exact current signed/checkpointed scoped grant in a short issuer
transaction; obtain PostgreSQL `clock_timestamp()` after verification. Create
a server UUIDv7 authorization ID using the existing M8 `uuid7` implementation.
Bind the full action, scope, actor, command ID, computed A1 request/subject
digests, fixed policy identity/version and signed grant-event digest.
Set `issued_at=now`, `admit_not_after=min(now+30s, grant.expires_at)` and refuse
a nonpositive window. Persist the exact request and lease, grant sequence and
digest as an immutable issuance receipt before returning the typed lease.
This is an action receipt, not another project-grant ledger.

The publisher never accepts a caller-supplied lease. Final admission resolves
the issuer-owned authorization row by exact scope/ID on the same session,
revalidates its complete request/lease and all duplicated columns, recomputes
request/subject/cache digests and compares every binding. Require the fixed
current policy, exact interactive identity, and the same currently active
signed grant sequence/digest under its lock. Then fetch fresh database time
and require `issued_at <= now < admit_not_after` with a positive window at
most 30 seconds. Data constructors or a digest column alone cannot admit.
Missing, forged, expired, revoked or mismatched authority refuses with
`M10_PROFILE_PUBLICATION_UNAUTHORIZED`.

## Schema, ownership and immutability

The baseline's 82 migration files have the singleton head `918c4a0e0001`.
Apply the existing derivation rule
`first12hex(SHA256(UTF8("r2.m10a.migration.v1:" + baseline)))`:
revision `65f53650f3a8`, predecessor `918c4a0e0001`, exact file
`alembic/versions/65f53650f3a8_quality_profile_publication.py`. The ID has been
checked against all 82 revision assignments without importing Alembic.
Freeze this base; do not silently rederive on another HEAD.

Five new tables only, with `users.id` ownership FKs using RESTRICT:

| Table | Identity and required content |
| --- | --- |
| `m10_quality_profile_heads` | PK(user_id, project_name, profile_id); nullable current_revision/current_digest as one coherent pair; head FK to the corresponding immutable revision, deferred for genesis |
| `m10_quality_profile_revisions` | PK(scope, profile_id, revision); revision>=1, parent NULL exactly at1 else revision-1 with a scoped parent FK; complete A1 QualityProfileRevision JSON, policy/profile digest columns; FK to scoped head and scoped issuance receipt |
| `m10_profile_publication_authorizations` | PK(scope, authorization_id); actor/command, full A1 request and lease JSON, policy/time/digest columns, signed grant sequence/digest; FK to the existing scoped grant event |
| `m10_quality_commands` | PK(user_id, project_name, actor_id, operation, command_id); operation=PUBLISH_PROFILE; computed request digest, exact result profile/revision/digest, complete A1 CommandReceipt JSON and commit time; FK to scoped revision |
| `m10_quality_outbox` | PK(full command key); FK to exact command receipt; immutable publication metadata event, profile/revision/digest, previous revision, cohort/surface, supersession effect and admission time |

Heads may advance only by the repository's expected-revision CAS. The four
other tables are append-only: migration-installed UPDATE/DELETE refusal
triggers on PostgreSQL and SQLite. A public migration helper installs that
same DDL for tests using the existing metadata-based per-test schema fixture;
no test-only product schema generator or new engine constructor. Service
fixtures may reuse the existing `_ready_schema` test helper to construct the
Alembic version-table input expected by the real startup verifier. That is
intentional fixture state, not evidence of migration execution. The separate
real SQLite/PostgreSQL round trips below cannot be replaced by metadata or
version stamping.
Downgrade removes only these tables/triggers and the owned PostgreSQL trigger
function, in reverse dependency order, first dropping the owned head-current
revision FK to break its genesis cycle. Upgrade/down/upgrade preserves all
predecessor tables and seeded predecessor data. SQLite migration compatibility
is required; authority mutations themselves require PostgreSQL and refuse
SQLite with `M10_SCHEMA_CHANGE_REQUIRED`.

Each read/admission recomputes the full typed row and compares body, scope,
parent, caches, authority linkage and duplicated digest/time columns. Revisions
of one profile keep the genesis cohort/product-surface pair. Never normalize,
truncate or overwrite an identity. Operational admission bounds are 255 UTF-8
bytes per command/scope identity and 1 MiB for canonical request JSON; exceeding
them yields `M10_OPERATIONAL_ENVELOPE_EXCEEDED` before DB work.

## Transaction and replay

`ProfilePublicationService.publish(request)` implements the existing A2 port.
It owns its transaction/session and exposes no transaction parameter to callers.

1. Verify the interactive caller and typed request. A read-only receipt lookup
   may return only the exact historical result after full receipt/revision
   digest and command-binding recomputation. Different content under one full
   command key yields `M10_COMMAND_REPLAY_CONFLICT`.
2. With no receipt, obtain the action lease through the qualified issuer above,
   outside the publication transaction. Failed publication can leave an unused
   immutable issuance receipt; it is not a publication.
3. Begin the authoritative transaction. Acquire a transaction advisory guard
   over the accepted `m10.command-key-guard.v1` digest; reread the exact full-key
   receipt with fresh ORM population before any new mutation. A hash collision
   serializes work but never becomes receipt identity.
4. Lock the actor's current grant head/history through the qualified reader;
   then insert an empty scoped profile head with ON CONFLICT DO NOTHING and
   lock that head. This is command -> grant -> profile order. Grant importers
   lock grant state and never acquire M10 command/profile rows. Publication
   never locks masters or dispositions. Hold the grant lock through commit.
5. Require expected_profile_revision=current_revision (0 for empty genesis),
   contiguous revision/parent and stable cohort/surface. Freshly resolve and
   revalidate the persisted authorization and interactive session. Fetch final
   `clock_timestamp()` after waits and all authorization I/O; reject expiry or
   grant/policy drift. `CURRENT_TIMESTAMP`/application clocks cannot admit.
6. Build the full revision from the draft plus resolved authorization and final
   admission time; recompute policy/profile digests using unchanged A1 domains.
   Append revision, CAS the head, append exact receipt and immutable outbox
   event, then commit once. Admission/receipt/event time is the same instant.

On rollback none of revision/head/command/outbox may advance. A crash after
commit replays the exact original receipt/result, including after later head
advances or authorization expiry; this makes no fresh-currentness claim.
Read access still requires the bound authenticated tenant/principal. The issuer
may issue multiple unused leases for competing retries; the command guard and
receipt select at most one publication. No outbox dispatcher, ack flag or
sequence cursor is introduced here.

The lock-order amendment specializes the earlier proposed command -> profile
order with the required grant lock. Validate both grant-import/publication
orders with observed PostgreSQL blockers, plus distinct commands racing genesis,
same-head CAS, same command replay and forced advisory-hash collisions. No
lock order is accepted from a diagram or a passing uncontrolled gather alone.

## Pure interfaces and supersession

`r2/quality/profiles.py` owns only validation/building over accepted models:
`publication_bindings(request)->tuple[str,str]` returns request/subject digests;
`build_published_profile(request, lease, admitted_at, *, policy_id,
policy_version)->QualityProfileRevision` checks all data bindings/window and
builds the digest-complete body. Neither function authenticates a user, resolves
an issuance receipt, declares grant currentness or grants Human authority.

`profile_requires_reevaluation(previous, newer)->bool` returns true only for a
strictly newer revision of the same scope/profile/cohort/surface declaring
REEVALUATE_CURRENT. HISTORICAL_ONLY and other cohorts/surfaces do not trigger
it. A3 persists this intent in the profile/event and leaves historical bodies
unchanged. Actual QualityRun/readiness/disposition integration is A5/A6 work;
this packet cannot claim it complete because those runtime readers do not yet
exist. This explicitly narrows the original A3 readiness scenario to a tested
input predicate and durable event; the full scenario remains an A5 gate.

## Acceptance and verification

The separate acceptance commit has exactly one parent, the reviewed design
candidate, and changes only the acceptance artifact plus two actual reviewer
artifacts in the manifest's review directory. Its record is schema_version1,
status `M10_A3_DESIGN_ACCEPTED`, author_id, baseline_head, design_head,
scope_allowlist, five design_artifacts `{path,sha256,mode}` rows, two reviewers
and reviewer_artifacts `{path,sha256}` rows, reviewed_at UTC, empty
required_skips/material_unknowns, and explicit false runtime-activation,
production-migration and provider-call permissions. Each distinct reviewer
records actual qualification, NO_CONFLICT, rubric
`R2_M10_A3_DESIGN_REVIEW_V1`, the same exact design candidate, PASS and UTC
review time. This is source/migration-authoring and disposable-test acceptance,
not a Human grant. The implementation pins the exact acceptance Git ref and
artifact hash; the current design/reviewer bodies must still match that seal.

The manifest lists exact product/design/editable paths, immutable source pins,
all predecessor migration byte/mode pins and the proposed revision. The only
existing product edit is adding the five named ORM exports/import to
`lib/db/models/__init__.py`; removing those additions must reproduce the exact
baseline AST. No A0/A1/A2 file is editable. The new A3 source guard consumes a
separate pinned acceptance and actual reviewer records, checks real HEAD/source
custody, dirty/hidden/ignored source, baseline/registry/migration boundaries and
owner-specific imports. It reuses only the verified historical bootstrap's
public Git reader; it never fabricates HEAD or repins the A2 guard.
Before acceptance, every read-only/editable baseline pin and all82 migration
pins must match the baseline and no new product path may exist. After
acceptance, require actual HEAD/source equality and ancestry before/after
inspection, all read-only pins plus bound design/review/acceptance bytes/modes,
the registry-only AST amendment and only the16 product-path delta. The new
migration may be absent during the guard/pure-source tasks; when present it is
the sole addition and must produce the exact83-node, single-head graph. Final
implementation evidence requires all16 product paths and complete migration
qualification. No success flag substitutes for missing implementation.

Guard refusal codes are M10_DESIGN_NOT_ACCEPTED,
M10_PREREQUISITE_NOT_ACCEPTED, POST_M8_BASE_SEAM_CHANGED,
M10_SCHEMA_CHANGE_REQUIRED and M10_NETWORK_SIDE_EFFECT_FORBIDDEN. Sanitize
read failures. Besides the allowed SQL/Unix custody capabilities, deny new
provider, arbitrary network, master/production/disposition/export imports and
generic/V1/public-only authentication fallbacks. Static checks are bounded
source checks, not a general Python sandbox.

Success is only `M10_A3_SCOPE_OK`; the original full-M10 and A2 guards remain
unchanged and correctly refuse expanded paths. The separate acceptance permits
source/migration authoring and disposable-DB qualification only. No production
migration or Human activation is inferred. Required checks: focused TDD on all
bindings/expiry/tamper/replay/CAS/atomicity, controlled PostgreSQL interleavings,
SQLite and PostgreSQL migration round trips, affected predecessor/auth/grant
fixtures, full backend static gates and backend suite after model registration.
Record actual commands, hashes, zero required skips and exact limitations.
One final independent implementation review, then bounded material repair and
re-verification. No code is implemented by this proposed document.
