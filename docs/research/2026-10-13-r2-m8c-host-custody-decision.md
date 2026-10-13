# M8-C operator-managed host custody decision

Status: research decision on 2026-10-13. It narrows the host inputs and
evidence needed for M8-C without provisioning a directory, changing Compose,
operating a backup, or activating Governance. License assessment is outside
this packet.

## Decision

Use a deployment-supplied, absolute `ARCREEL_GOVERNANCE_ROOT` with the two
subtrees already selected by the M8-C design:

| Parameterized path | Owner and mode | Purpose |
|---|---|---|
| `${ARCREEL_GOVERNANCE_ROOT}/archive/` | root:root; directories `0700`, records and lock `0600` | Retained approvals, registry/checkpoint bytes, high-water chain, custody receipts and publisher staging. It is never mounted into a container. |
| `${ARCREEL_GOVERNANCE_ROOT}/read/` | root:root; directory `0755`, public files `0644` | The four public copies consumed by the application: approved deployment, verifier registry, high-water, and checkpoint. |
| `${ARCREEL_GOVERNANCE_BACKUP_ROOT}/` | a separately approved backup principal and restrictive permissions | Encrypted or otherwise independently protected copies of `archive/`, plus its restore evidence. It must not be below the Governance root, Compose project, PostgreSQL data, `projects`, `logs`, an M7 backup-set directory, or a restore target. |

`ARCREEL_GOVERNANCE_ROOT` and `ARCREEL_GOVERNANCE_BACKUP_ROOT` remain
parameters until an operator supplies a real host inventory. The prior
`/srv/arcreel-governance` string is illustrative only; the selected design
explicitly says it was neither created nor approved on this machine
([design §Selected host-directory boundary](../superpowers/specs/2026-10-12-r2-m8c-operator-high-water-manifest-design.md)). No source in the repository
identifies a production host, an absolute Governance root, a backup target, or
an enrolled operator account. A local, read-only check found no child under
this sandbox's `/srv`; its interactive user is `anhtuan` (UID/GID 1000). That
is development-environment data and is not evidence about the operator host.

A further local inventory on 2026-10-13 found no `ARCREEL`, `GOVERNANCE`,
`DEPLOY`, or `PROD` environment key, no readable user SSH or Kubernetes
configuration, and only the Docker `default` context at
`unix:///var/run/docker.sock`. The only matching environment key was
`SSH_AUTH_SOCK`, which does not identify a host. The relevant deployment,
runbook and research files contain no production-host alias. These are
bounded observations about this workspace, not a claim that no operator host
exists elsewhere.

The publisher identity is therefore specified as an auditable host principal,
not guessed from this checkout: `root` owns the tree and an explicitly named
operator principal invokes the publisher through the audited root procedure.
The evidence record must capture the invoking account, effective UID/GID,
host identity, time, command version and deployment-record ID. The application
container never gets archive access, a writeable Governance mount, or a
private signing key.

This reuses the accepted root-owned archive/read split, exclusive host-side
publication lock and public-file set from the existing plan
([plan](../superpowers/plans/2026-10-12-r2-m8c-operator-archive-preflight.md)).
It also preserves the reuse audit's conclusion: local atomic/no-follow/lock
primitives and the fixed ArcReel/PIOS donor procedures are useful implementation
seams, but none is an independently retained latest-checkpoint authority
([reuse audit](2026-10-12-r2-m8c-host-custody-reuse-audit.md)).

## Why the current deployment cannot be accepted as custody

`deploy/production/docker-compose.yml` mounts `./pgdata`, `./projects` and
`./logs` relative to the Compose project and runs `arcreel/arcreel:latest`; it
has no Governance mount ([Compose file](../../deploy/production/docker-compose.yml)).
The M7 runbook uses example project and backup locations under
`/srv/arcreel/projects` and `/backups`, requires an empty non-overlapping
restore target, and warns that the production `postgres:18-alpine` tag must be
pinned by digest before reliable cross-upgrade restore
([M7 runbook](../r2/runbooks/m7-backup-restore.md)). Those paths and tags are
not a verified Governance custody arrangement.

Docker Compose supports a long bind mount with a host `source`, container
`target`, per-mount `read_only`, and `bind.create_host_path: false`; its
documentation says the short syntax creates a missing host directory while
the latter setting prevents that behavior
([Docker Compose volumes reference](https://docs.docker.com/reference/compose-file/services/#volumes)).
The future application mount therefore has this required shape, once the
operator has provisioned and verified the actual value:

```yaml
- type: bind
  source: ${ARCREEL_GOVERNANCE_ROOT}/read
  target: /run/arcreel/governance
  read_only: true
  bind:
    create_host_path: false
```

Compose accepts an image reference with either a tag or an `@digest`
([Docker Compose image reference](https://docs.docker.com/reference/compose-file/services/#image)); M8-C needs the latter for the approved application and PostgreSQL images. This is a proposed deployment fragment, not a Compose change.

## Fastest evidence-first route through the host gate

The slow part of the earlier plan was treating host custody as a broad
infrastructure decision. It can be closed as one narrow operator evidence
packet before an application integration run. The operator executes the checks
below on the actual host with the services stopped, records their output in a
restricted evidence artifact, and supplies the resolved paths and principal.
No command is run from this checkout against a host.

1. Resolve both parameters with `readlink -f`; reject empty, relative, missing
   or symlinked components. Capture `findmnt -T` for the root and backup root,
   `stat -c '%n %F %u:%g %a %d:%i'` for each component, and the hostname or
   immutable host ID. Verify that neither root is inside the Compose directory,
   `pgdata`, `projects`, `logs`, an M7 backup-set directory, or a restore root.
2. Run `namei -l` and `find -xdev` over the new root. Accept only root-owned
   regular files/directories at the prescribed modes; reject symlinks,
   device files, sockets, group/world-writable parents and unexpected entries.
   Record the actual operator account and `id` output when it invokes the
   root-owned publisher. This closes the missing identity and access-review
   facts without inventing an account name.
3. Create only a disposable test archive under the verified root, publish
   synthetic test-key records through the existing offline publisher, then run
   the existing preflight against a disposable PostgreSQL restore. Exercise
   retained/public mismatch and restored-old-DB denial. Remove only the
   disposable test subtree after preserving the evidence. This reuses the
   clean-target and separate-verdict conventions from the M7 runbook rather
   than making a second backup workflow.
4. Copy the real `archive/` only after the above pass to the independently
   resolved backup root, record a byte digest manifest outside both locations,
   and restore that copy into a new empty, non-application directory. Run the
   archive verifier against the restored copy. The full application restore
   remains a separate M7/M8-C gate; this short drill proves the independent
   archive recovery path first.
5. Pin image digests in the deployment record, compare them to locally
   resolved image digests during the stopped-service preflight, then mount
   only `read/` as above. The app startup path must deny before readiness if
   any public file is absent, mismatched or lower than retained high-water.

Steps 1--4 are one bounded custody drill and can run once per chosen host;
they avoid repeating the full backend suite. Step 5 is only ready after the
separate startup/preflight implementation exists. The existing design still
requires its archive-before-public ordering and directory `fsync`, because a
valid signature alone does not make an older record acceptable
([design publication ordering](../superpowers/specs/2026-10-12-r2-m8c-operator-high-water-manifest-design.md)).

## Acceptance evidence and open facts

The following must be present before this gate is `CONFIRMED`:

| Required evidence | Current state |
|---|---|
| Actual absolute Governance and independent-backup paths, resolved filesystem/mount identities, and non-overlap proof | Unknown; no production-host access was supplied. |
| Operator account/service principal, effective UID/GID, root-procedure authorization and access review | Unknown; repository and sandbox user cannot establish it. |
| Root/archive/read ownership, modes and no-follow inventory on that host | Proposed only. |
| Independent archive backup retention/restore drill with digest equality and archive verifier result | Not run. |
| Digest-pinned app and PostgreSQL deployment record and a read-only `read/` bind with missing-source refusal | Not deployed; local Compose syntax probe is not host evidence. |

The host-local design does not protect against a privileged host actor replacing
both `archive/` and `read/`, deletion of the host, or a rollback of every copy;
the underlying design records those limits. A distinct backup destination and
the restore drill reduce host-loss exposure but do not change that authority
boundary. Governance `APPROVE`/`READY` remains closed until these facts and the
separate startup, restore, scanner, capacity, affected-test and independent
exact-HEAD review gates are complete.
