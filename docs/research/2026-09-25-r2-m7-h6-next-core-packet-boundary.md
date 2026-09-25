# R2 M7-D H6: boundary for the next core-contract packet

Date: 2026-09-25
Checkout: `r2-m7e-v1-lineage`, `6dce02906ae26dd67e2ad90817fe6a509e240198`
Status: research and recommendation only; not sponsor approval, implementation, or H6 acceptance.

## Question

What is the smallest independently reviewable H6 core packet after the pure
fence-evidence preflight, without upgrading the existing disposable backup
mechanism into production authority by accident?

## Confirmed repository facts

1. The current `BackupSetManifest`, `BackupVerdict`, and `MediaInventoryEntry`
   in `r2/contracts/host_hardening.py:324-362` are unversioned drill shapes.
   `r2/host_hardening/backup.py:195-206,239-296,317-386` consumes and emits
   them. Replacing them in place would change the existing disposable API.
2. The old manifest carries a single media tuple, not the deployment-wide
   project/formal/candidate inventory described in the draft H6 design
   (`r2/contracts/host_hardening.py:324-349`; design §4). The old verdict has
   no custody receipt/attestation references, crypto-profile binding, or
   ledger sequence (`host_hardening.py:351-362`; design §6).
3. The current backup row is still project-scoped through `UserOwnedMixin`,
   with non-null project name (`lib/db/models/host_hardening.py:419-438`).
   The repository inserts/flushes `PREPARING` and media refs and its retention
   query matches scoped `PREPARING`/`COMPLETE`, not the draft design's global
   deployment and `VERIFIED`/`DISPOSED` lifecycle
   (`lib/db/repositories/host_hardening.py:1100-1144`; design §4).
4. The pure `r2.host_hardening.fence_evidence` verifier exists and has passed
   bounded review, but the current `create_backup_set` does not call it. The
   runbook explicitly limits the old mechanism to disposable drills
   (`docs/r2/runbooks/m7-backup-restore.md:1-23`).
5. The H6 closure design is marked **DRAFT FOR SPONSOR REVIEW**. Its §8
   separates a disposable core-contract packet from a deployment-bound
   custody packet. §6 says no production crypto profile is pinned and forbids
   treating a test fixture as production custody. It also makes approval of
   `CustodyPolicyV1` and a real drill receipt a production gate.

These are direct source/document observations, not an exhaustive repository
absence claim. The available code graph predates this worktree: its
2026-09-18 generation reports `backup.py` not tracked and changed metadata
for the contract and repository files. Direct file reads and bounded `rg`
were therefore used for the source claims above.

## Inference and alternatives

- **Extend the old manifest in place:** fewer new names, but risks silently
  changing the existing disposable callers and confusing old drill evidence
  with H6 V1. Not recommended while compatibility is unproved.
- **Migrate persistence first:** establishes global set identity and retention
  invariants, but couples migration/downgrade/CAS decisions to a draft design
  and requires disposable PostgreSQL verification. This is not the smallest
  first packet.
- **Introduce separate, pure V1 wire contracts:** keep old drill types and
  operations unchanged; reject absent/unknown V1 versions and incomplete
  authority fields; test canonical bytes and adversarial inputs without DB,
  backup writes, encryption, or restore. This is the smallest candidate seam,
  **provided the exact V1 field map and digest domains are approved first**.

## Decision still needed before a V1 schema plan or implementation

The draft describes required content but does not yet provide one complete,
machine-testable field map for `RecoveryConfigV1`, the inner manifest, every
inventory entry, and `BackupVerdictV1`: cardinality and ordering of project /
formal / candidate entries; absent Artifact Manifest encoding; exact digest
domains; source-vs-target identity comparison; and the references that bind
fence, policy, crypto profile, receipt, attestation, ledger sequence, and
RPO/RTO evidence. A plan that invents these fields would freeze an interface
before its owner reviews it.

Recommended next gate: write a narrow V1 wire-schema addendum with sample
canonical records, explicit invalid cases, and legacy separation; self-review
it against design §§4, 6–8 and the existing contract callers, then obtain the
required design approval. Only then plan/test/implement the pure contracts.
Do not attach production `RECOVERY_VERIFIED` semantics to that packet. The
database migration, inventory capture, custody adapters, archive crypto,
restore drill, and H7 remain separate dependent gates.

## Primary sources already pinned for later packets

The repository's existing research notes cite PostgreSQL's first-party dump /
restore behavior and NIST's backup, cryptographic, key, retention, and restore
guidance: `docs/research/2026-09-25-r2-m7-h6-h8-primary-source-notes.md` §1
and `docs/research/2026-09-25-r2-m7-h6-custody-policy-primary-sources.md`.
This note does not re-verify those external facts or select a product.
