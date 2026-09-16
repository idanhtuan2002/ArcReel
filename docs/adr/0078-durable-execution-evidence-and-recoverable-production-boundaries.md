---
status: accepted
---

# Host hardening uses durable execution evidence and recoverable production boundaries

M7 shall harden the existing ArcReel queue, task state machine, provider
backends, Artifact Manifest, version history, usage accounting, and project-event
surfaces. It shall not introduce a second queue, workflow engine, artifact
registry, cost authority, or production authority. The Host remains the sole
runtime authority; M7 adds durable evidence and fail-closed recovery seams around
the failure windows that the existing task row cannot represent.

Every paid asynchronous provider submission shall belong to an immutable
`ExecutionAttempt` created before the network call. The attempt binds one exact
task, request digest, provider/model/endpoint/base URL, adapter and capability
version, provider-account scope, client token when supported, and a monotonic
state version. A provider job ID is an observation added to that attempt, not the
attempt's identity. A timeout, connection loss, or process death after request
bytes may have reached the provider enters `SUBMIT_OUTCOME_UNKNOWN`; it is never
silently mapped to failed or queued. The idempotent attempt key is the scoped
`(user_id, project_name, task_id, attempt_no)` tuple; a caller-supplied
`execution_id` is immutable evidence bound to that key, not an alternate key.

Provider adapters declare versioned capabilities for native idempotency,
lookup/reconciliation, polling, cancellation, webhook verification and result
retention. A native client token is reused only with the same request digest.
Adapters without a proved idempotency or lookup capability may not automatically
resubmit an ambiguous attempt: they leave it fail-closed for bounded operator
reconciliation. This deliberately prefers a visible possible charge over an
invisible duplicate charge. `NOT_FOUND` is non-authoritative unless the exact
qualified capability proves that lookup becomes authoritative after a declared
settling window.

Idempotency is enforced at four independent boundaries: command receipt,
queue/task creation, provider execution attempt, and result/promotion ingestion.
Trace IDs, process IDs, worker leases and mutable configuration are never
idempotency identities. Worker mutations require an owner plus monotonically
increasing lease token and unexpired lease; provider observations use a separate
idempotent ingestion authority and are not blocked by a dead worker lease.
Terminal provider observations are monotonic and cannot be reversed by late or
duplicate events.

`NEEDS_OPERATOR` is a non-terminal fail-closed pause. It can change only through
an immutable `OperatorResolutionReceipt` binding the exact attempt version,
operator, action and external evidence. An operator may bind a proved remote job,
prove that no submission occurred, or record proved terminal provider truth; an
operator cannot authorize a blind retry on the same attempt.

Generation output is written to immutable candidate media and verified before it
can become authoritative. Promotion is a short PostgreSQL transaction that
compare-and-swaps the expected master head and appends the promotion receipt,
usage link and durable event/outbox row. Filesystem or object-store preparation
occurs before that transaction. M7 shall not attempt XA across PostgreSQL and
media storage. A failed prepare creates at most a quarantined/orphan candidate;
a failed or conflicting commit leaves the old approved master fully resolvable.
The existing Artifact Manifest/version bridge remains a compatibility projection
until authoritative readers have moved to the database master head; it may not
become a competing master selector.

Project events are created with the execution-attempt schema in M7-A because
every attempt transition must append its public event in the same transaction.
Project SSE later becomes a transport projection of that tenant-scoped durable
event log.
The log and the domain mutation commit together. `Last-Event-ID` is an opaque
ordered cursor; reconnect replays events after the cursor and then tails live
notifications. Delivery is at least once, so consumers deduplicate by event ID.
An expired cursor produces an explicit snapshot-resync response. In-memory
channels and PostgreSQL notifications are wake-up hints only, never event
authority or durability.

A recognized backup is a `BackupSet` that binds an exact PostgreSQL recovery
point to an immutable media inventory, checksums, schema/Alembic head, release
identity and required configuration metadata. A set is not complete until its
files verify. H6 is not closed until the set has been restored into a clean
database and media target and every approved-master reference has been resolved
and probed. M7 initially supports a write-fenced backup drill; PITR/WAL archiving
is a production-candidate capability only after measured archive lag and restore
performance satisfy an explicitly approved RPO/RTO.

OpenTelemetry trace context supplies request-time correlation, while durable
domain IDs preserve correlation across restart and new traces. Telemetry uses an
attribute allowlist and source-side data minimization, followed by collector-side
redaction. Raw prompts, scripts, credentials, signed URLs, authorization data,
provider responses and user identifiers are forbidden from logs, spans and W3C
baggage. Provider job identifiers exposed to general telemetry are keyed hashes;
the raw value remains in the access-controlled execution store.

M7 v1 qualifies polling and bounded reconciliation only. Provider webhooks remain
outside this ADR's implementation scope; every M7 capability profile records
`supports_webhook=false`. A future webhook decision must add signature,
replay-protection, tenancy and observation-ingestion gates before enabling it.

Candidate deletion remains in the existing Host cleanup machinery, but every
delete route must call one retention policy that refuses candidates referenced by
a master head, active attempt, retained promotion receipt or incomplete backup
set. M7 does not create a second garbage collector.

Upstream Host changes enter only through a pinned compatibility candidate with
source provenance, change inventory, isolated merge rehearsal, migration
rehearsal, static and contract gates, H1-H8 fault tests, Golden A/B, browser
workflow evidence and a classified compatibility report. A clean merge or green
unit suite alone is not compatibility evidence. Provider qualification is also
versioned per exact provider/API/capability; unqualified paid routes remain
disabled.

## Considered options

- Extending only the mutable task row was rejected because it cannot preserve
  attempt history or truthfully represent a provider-accepted request whose
  response was lost before `provider_job_id` persistence.
- Adopting a durable workflow engine was rejected because external provider
  effects would still require idempotency/reconciliation, while the new engine
  would create another runtime control plane beyond M7.
- Distributed transactions across PostgreSQL and media storage were rejected
  because local filesystems and object stores do not share a practical atomic
  commit protocol. Immutable preparation plus one authoritative pointer has a
  smaller and testable failure surface.
- Treating SSE delivery as task state was rejected because `Last-Event-ID`
  defines reconnect behavior, not a durable event store or processing
  acknowledgement.
- Database-only or media-only backup was rejected because either can restore a
  syntactically valid but referentially broken production state.
- Automatic retry for providers without proved native idempotency or lookup was
  rejected because it can create duplicate remote work and duplicate charges.

## Consequences

- M7 requires append-only attempt, event, command-receipt and promotion evidence,
  plus bounded recovery workers; it does not require replacing the existing
  scheduler or provider abstraction.
- Unknown outcomes become explicit operational states. Some providers will need
  manual resolution or remain disabled until their capability is qualified.
- Candidate garbage collection is delayed and independently recoverable; it is
  never part of the master-promotion transaction.
- `RECOVERY_VERIFIED` requires H1-H6 fault and clean-target restore evidence.
  `PRODUCTION_CANDIDATE` additionally requires H7-H8, production-like Golden A/B,
  qualified providers, browser evidence and operator runbooks.
- This ADR authorizes M7 design and implementation planning only. It does not
  authorize implementation, operating migrations, provider calls or spend,
  backup/restore against live systems, worker activation, deployment, cleanup,
  publication, or production approval.
