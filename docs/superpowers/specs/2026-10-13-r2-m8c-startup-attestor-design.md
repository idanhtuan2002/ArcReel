# M8-C host archive startup attestor

Status: implementation design following the sponsor's instruction to research,
decide and continue autonomously. Production activation and actual-host custody
acceptance remain external gates. Baseline: `7b3f9cab165475a8bf3fab6a7f93a1554f242001`.

## Intended outcome

Every activated application startup must obtain current retained-archive evidence
before migrations, workers or readiness. An old coherent DB/public snapshot must
deny while the operator archive is newer. The archive and independent backup stay
outside the container; no signing key is added to the app. Reuse existing archive
preflight, public validation, schema verifier, full scanner and grant reader.

## Reuse and concrete gap

`verify_operator_archive_preflight(root, session_factory, expected_uid)` already
holds the publisher lock across retained/public verification, exact schema and
complete ledger scan, then rereads. `GovernanceCheckpointFile` provides bounded
no-follow public reads. The three internal review/V2 services already accept a
`CurrentShowrunnerGrantReader` constructor parameter. M7 restore attestation is
backup-set-specific and cannot witness freshness across container restarts.
The prior research found no existing Unix-socket attestor or startup challenge
protocol in the inspected server/lib/r2 scope. Graph generation
`2026-10-04T09:21:10Z` predates these modules; exact source is authoritative.

## Host boundary and protocol

Run a host process with root credentials, a fixed absolute Governance root and a
fixed PostgreSQL session factory. Expose only a separate root-owned runtime
socket directory to the container as a read-only directory bind. Its directory
mode is `0700`, socket basename is `attestor.sock`, socket mode is `0600`, and
UID/GID are `0:0`. The service creates no directory and refuses any existing
socket pathname. Cleanup removes only the exact socket inode it created.

Client and server open directory components with no-follow directory descriptors;
root or the explicitly injected fixture UID owns each ancestor, which cannot be
group/world writable except a root-owned sticky ancestor. That exception supports
disposable local fixtures and is not actual-host custody acceptance. The final
socket directory has exact owner/group/mode. The client connects through its
anchored `/proc/self/fd/<directory-fd>/attestor.sock` path, checks the socket inode
before/after connect and requires the peer UID/GID to match the configured host
principal (production defaults `0:0`) using Linux `SO_PEERCRED`.
[Linux unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html) documents pathname
socket permissions and connected-peer credentials. Platforms without these
facilities deny. A root-remapped deployment must establish its own reviewed
credential/mount mapping before activation; it cannot silently weaken the check.

Each connection carries exactly one canonical JSON request and response, each
at most 4096 bytes, followed by newline and EOF. Strict field/type checking and
canonical reencoding reject duplicates, unknown fields and nonfinite values.
The request contains only schema `governance.startup_challenge.v1` and a newly
generated 256-bit lowercase hex nonce. It supplies no path, DB URL or claimed
archive value. The service calls archive preflight on every accepted challenge;
there is no proof cache or persistent public receipt. At most 16 connection
handlers are admitted; excess connections close immediately. Its response contains
schema `governance.startup_proof.v1`, that nonce, deployment ID, checkpoint
sequence, and four SHA-256 file digests in approval/registry/high-water/checkpoint
order, all derived from the returned verified archive. Only one preflight runs
at a time; a competing request is denied. Both endpoints have a 30-second total
exchange deadline and bounded stream buffers. Failure closes the connection;
public errors contain no DSN, path, request bytes or internal exception detail.

The authenticated host channel and unpredictable per-start nonce provide the
freshness boundary. No extra signature/MAC is needed under this host-custody
model. A recorded response from an earlier start cannot match a new nonce.
Host root replacement, container escape and rollback of every archive/backup
copy remain outside the selected host-local guarantee.

## Application composition

Keep the existing public-only verifier available for offline characterization;
it must never be treated as an activation proof. Add a distinct
`verify_governance_activated_startup(read_directory, socket_directory, ...)`
that reuses the same local public/schema/scanner sequence, obtains the fresh
host proof, checks all four digests plus deployment/sequence, and rereads public
copies before returning a checkpointed reader. Every later checkpoint read also
checks file custody. Activation requires both `ARCREEL_GOVERNANCE_READ_DIR` and
`ARCREEL_GOVERNANCE_ATTESTOR_DIR`; a missing/empty/malformed value denies before
`init_db`. Attestor-only configuration also denies rather than falling back to
normal mode. Normal mode with neither variable keeps its existing behavior.

Activated startup skips automatic DB stamp/upgrade and constructs the existing
SpatialReviewSessionService, CurrentApprovedSpatialPairReaderV2 and
SpatialPairDecisionServiceV2 with that same reader in app state. There are no
new public routes. Any later grant/parent mutation is rechecked by those
transaction-bound services; startup proof is not authority to approve a pair.
Approved image identity still belongs to host deployment preflight. Database
restore and offline migration require stopped application/workers under the
existing M7/operator procedure; this startup proof does not authorize an online
restore or keep a database connection alive through one.

## Operator entry point

Add one CLI with `preflight` and `serve` commands, explicit root/socket paths,
and a database URL read from an environment variable name rather than argv,
following the existing M7 CLI pattern. It requires effective root for real
operation. It runs no migration, imports no grant, publishes no record and
prints only sanitized success/failure metadata. Existing provisioning/deployment
must supply the directories and image pins; this change touches no live host.

Operator recovery boundaries:

- A killed `serve` process (SIGKILL, host crash) leaves `attestor.sock` in place;
  the next `serve` refuses the existing pathname and every application start
  denies. With no `serve` process running (`ss -xlp` shows no listener on that
  path), the operator removes only that socket inode and restarts `serve`. The
  service never unlinks a pathname it did not create.
- Publisher lock contention, a busy preflight or a competing start returns no
  proof; the application denies before migrations and its restart policy retries.
  Concurrent replicas therefore start one at a time.
- `SO_PEERCRED` UID/GID are parsed as unsigned `uid_t`/`gid_t`.

## Verification and acceptance limits

TDD covers transaction custody, real Unix socket positive/replay/wrong owner/
mode/symlink/extra data/timeout cases, real PostgreSQL archive/DB mismatch and
public mutation, and activated lifespan ordering. A versioned same-major
pg_dump/pg_restore drill must preserve ISSUE, advance to REVOKE, restore an old
DB with current archive, assert actual lifespan denial before startup effects,
and prove the current post-REVOKE path starts while revoked service use denies.
Use existing M7 database/tool patterns and Governance fixtures. Then run focused
Governance and startup domains, repository static checks and one independent
review of the committed change. Run the final full backend suite only after
remaining code/review repairs stabilize. Actual-host paths, operator principal,
independent backup restore, image and mount evidence remain required; local
fixtures do not close those gates.
