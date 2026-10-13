# M8-C startup freshness anchor research

Date: 2026-10-13  
Scope: the application can read the four public Governance files, while the
operator archive and independent backup remain outside the container. This is
a source-backed design comparison; no production host, path, account, or
operator identity was available in the repository or this workspace.

## Question

How can startup prove that the public checkpoint is not an older coherent copy
of the database while a newer retained archive exists, and what is the shortest
path to a reviewable M8-C gate?

## Current repository evidence

The existing archive verifier is the strongest reusable donor. `verify_operator_archive_preflight()`
opens the operator archive under `_locked_archive`, reads a complete retained
state, verifies the committed database state with `GovernanceGrantRecoveryScanner`,
rereads the archive, and rejects if the before and after complete states differ
(`server/services/governance_operator_archive.py:169-193`). The verifier therefore
has the required archive visibility and stability window, but it is host-side
code and cannot be called by the container while the archive remains unmounted.

The existing `attest_deployment_restore()` donor is a different kind of proof.
It moves a deployment backup set to `VERIFIED` only after a restore verdict and
Golden evidence match the manifest digest (`r2/host_hardening/deployment_backup.py:1007-1074`).
It proves that a particular recovery exercise passed; it does not prove that the
currently published four-file snapshot is at least as new as the retained
Governance archive on every later process start.

The current application startup branch validates the public snapshot and then
raises `GovernanceStartupUnavailable` before database initialization or worker
startup (`server/app.py:352-522`). This is correctly fail-closed while no
archive freshness anchor is available. The current production Compose file has
no Governance mount and uses `restart: unless-stopped` for the application
(`deploy/production/docker-compose.yml:18-49`).

The public directory cannot solve the rollback problem by itself. A database
and all four public files can be restored to an older internally consistent
state while a newer archive remains elsewhere. A receipt stored beside those
files has the same rollback surface. A receipt copied into the application
database has the same problem if that database is restored with the old public
files.

## Option A: operator preflight plus a start barrier

The operator runs the existing archive preflight, then publishes the public
files and starts the application only after the preflight result is recorded.
For a systemd-managed deployment, `ExecStartPre=` commands run serially before
`ExecStart=` and a non-prefixed failing command prevents the service from
starting, according to the systemd service unit documentation. `RequiresMountsFor=`
can add `Requires=` and `After=` dependencies for the filesystem holding the
archive. These are useful host controls.

This option is fast for an initial deployment or an explicitly controlled
restart. It is insufficient as the sole runtime proof when a container runtime
can restart the application independently. Compose's `restart: unless-stopped`
is a daemon restart policy; it does not imply that a host `ExecStartPre=` hook
will run for every container restart. Therefore a durable “last preflight passed”
file in the public directory is not an acceptable authority boundary.

Option A becomes acceptable only if the deployment contract makes the barrier
the only activation path: disable the independent restart path, or have the
service manager own and restart the whole Compose unit so every application
activation reruns the preflight. That deployment fact is currently unknown and
must be proven on the operator host.

## Option B: independent runtime host attestation

Run a small root-owned host attestor that can read the retained archive and
database, calls the existing archive preflight under its lock, and answers a
fresh startup challenge over a root-owned Unix socket. The application sends a
nonce plus the digest it read from the public files. The attestor rereads the
archive/public state, verifies the committed database state, and returns a
short-lived signed or MAC-protected response containing at least the nonce,
deployment ID, public checkpoint digest, archive high-water sequence/digest,
and an expiry. The application must reject missing, stale, mismatched, or
replayed responses before migrations, workers, routes, or readiness.

This survives container restarts because the proof is obtained again from an
independent host process. It also keeps the archive out of the container. The
Unix socket must be root-owned and permission restricted; the application
container receives only the socket, not the archive directory. The attestor
must not accept a digest supplied by the application as the source of truth: it
must compute the retained and public values itself while holding the archive
lock, then compare them.

The systemd socket documentation confirms that a filesystem AF_UNIX path can
be configured with `ListenStream=` and that a socket unit can activate a
service. The service documentation confirms that `ExecStartPre=` is a
synchronous activation barrier. These primitives provide ordering and access
control, but they do not create freshness semantics automatically; the
attestor protocol and its archive read must supply those semantics.

This option has one important boundary: it protects against application or
container rollback when the host archive and attestor are operator-managed. It
does not protect against a fully privileged host operator replacing the
archive, attestor, public files, and application image together. That is outside
the currently evidenced threat model and must not be claimed as solved.

## Decision for the fastest safe M8-C path

Use a two-stage path:

1. Keep the current unconditional startup quarantine and finish the evidence
   around the host contract. The operator must supply absolute paths for
   `ARCREEL_GOVERNANCE_ROOT` and an independent backup root; the repository
   cannot discover real production paths or an operator account.
2. Reuse `verify_operator_archive_preflight()` in a host-side preflight command
   for the restore and publication drill. This gives the quickest meaningful
   gate because it already holds the archive lock, verifies the database, and
   checks the archive is stable.
3. For activation, choose Option B unless the host proves that every container
   restart is forced through the systemd barrier. The runtime attestor is the
   smallest mechanism that closes the restart gap without mounting the archive.
   Do not treat a public-directory receipt, a Compose healthcheck, or the M7
   deployment-backup `VERIFIED` state as the missing freshness proof.

The resulting acceptance sequence is narrow: (a) real same-major PostgreSQL
restore of an older database with a newer retained Governance archive, (b)
host preflight rejection/acceptance evidence, (c) startup challenge evidence
across a process/container restart, and (d) only then the positive activated
lifespan path plus the targeted M8-C gates. A full repository suite is not
needed for this decision; it should be reserved for the final stable HEAD gate.

## Host facts still unknown

No production host or operator-managed directory was discoverable from this
workspace. The following are parameters to be supplied by deployment
configuration and must be observed, not invented:

- absolute Governance root and its `archive/` and public `read/` paths;
- absolute independent backup root and its retention/restore mechanism;
- service manager or container runtime that owns application restarts;
- numeric owner/group and permissions of the archive, public directory, socket,
  and backup root;
- whether the PostgreSQL major version used for the restore drill matches the
  production dump/restore tools.

## Primary sources

- [Docker Compose services reference](https://docs.docker.com/reference/compose-file/services/): image references may use immutable digests; long bind syntax supports `read_only` and `bind.create_host_path: false`; `restart` is a container runtime restart policy.
- [Docker Compose trust model](https://docs.docker.com/compose/trust-model/): tags are mutable, digests are immutable, and bind mounts expose host paths to the container.
- [systemd.service.xml](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml): `ExecStartPre=` commands run before `ExecStart=` and a failing command prevents the remaining start sequence.
- [systemd.unit.xml](https://github.com/systemd/systemd/blob/main/man/systemd.unit.xml): `RequiresMountsFor=` adds `Requires=` and `After=` dependencies for required mount units.
- [systemd.socket.xml](https://github.com/systemd/systemd/blob/main/man/systemd.socket.xml): `ListenStream=` supports a filesystem AF_UNIX socket and can activate a service.

## Evidence limits

The graph project `r2-m8c-binding-design` was indexed at generation
`2026-10-04T09:21:10Z` in fast mode. Coverage reported `metadata_match` for
`r2/host_hardening/deployment_backup.py`, `metadata_changed` for `server/app.py`,
and `not_tracked` for the two new Governance service files. The Governance
files and changed `app.py` were therefore checked from the current filesystem;
graph results are used only for the older donor symbol and are provisional.
No production host, Compose restart trace, systemd unit, archive backup, or
real restore was executed by this research.
