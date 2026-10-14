# M8-C packet 7: operator tools for ADR-0103 activation

**Basis:**
- [ADR-0103](../../adr/0103-showrunner-grants-and-spatial-review-custody.md), which lists the activation items.
- The [host record and publication contract](../specs/2026-10-12-r2-m8c-host-record-and-publication-contract.md).
- The [startup attestor design](../specs/2026-10-13-r2-m8c-startup-attestor-design.md).
- The [grant and review evidence spec](../specs/2026-10-06-r2-m8c-grant-and-review-evidence-design.md).
- The sponsor's 2026-10-14 request: write an activation runbook first, then check the Shots page in a browser.

## Facts

- **The verification side exists and is tested:**
  - record parsers: registry, approved deployment, high-water, signed checkpoint and signed grant event;
  - the locked archive reader;
  - create-once and public-replace file operations;
  - `publish_candidate_archive` for successor checkpoints;
  - `verify_operator_archive_preflight`;
  - the startup attestor (`scripts/r2/governance_preflight.py preflight|serve`);
  - the activated startup path (`ARCREEL_GOVERNANCE_READ_DIR`, `ARCREEL_GOVERNANCE_ATTESTOR_DIR`).
- **The producing side exists only in test fixtures.** These steps have no operator command:
  - generating keys;
  - building the registry and approved deployment;
  - signing the genesis checkpoint, grant events and successor checkpoints;
  - enrolling a genesis archive;
  - importing a signed grant event;
  - deriving the next checkpoint body from the committed ledger.

  `tests/unit/r2/governance/test_operator_archive_reader.py::_tree` and `_append_successor`, together with the importer test's `_signed` and `_event`, show the exact byte shapes.
- **The ADR's limits apply.** The app must hold no signing key, and grant administration runs offline with the app and workers stopped. Genesis requires an empty grant ledger. The first approval is sequence 1 only.

## Decisions

1. **Pure builders, `r2/governance/ceremony.py`.**
   - Each builder emits canonical bytes through `canonical_json_bytes` and re-parses them with the existing parser before returning, so a builder can never emit a record the verifiers reject.
   - The builders cover: Ed25519 key generation (raw 32-byte private key, base64url public key), the registry, the approved deployment, the genesis checkpoint body, a signed checkpoint, a signed ISSUE/REVOKE event and the successor high-water record.
   - Signing takes private key bytes and is used only by the offline commands.
2. **Database steps, `server/services/governance_ceremony.py`:**
   - **`enroll_genesis`:**
     - creates the `archive/` and `read/` tree with the contract's modes and owner;
     - publishes the four retained files create-once and the four public copies under the archive lock;
     - then runs `verify_operator_archive_preflight`.

     It refuses if the tree already exists or the grant ledger is not empty.
   - **`import_grant_event`:** verifies the event under the registry's grant key read from `read/`, then imports it through `GovernanceGrantImporter`.
   - **`next_checkpoint_body`:** reads every committed grant head under the recovery scan fence, verifies each chain, and builds the unsigned successor body naming the retained latest checkpoint.
   - **`publish_signed_checkpoint`:** builds the successor high-water record and calls `publish_candidate_archive`.
3. **One CLI, `scripts/r2/governance_ceremony.py`:**
   - Offline subcommands, no database: `keygen`, `registry`, `sign-event`, `sign-checkpoint`.
   - Host subcommands, effective root and a database URL read from an environment variable as `governance_preflight.py` does: `enroll`, `import-event`, `next-body`, `publish`.
   - Output files are created exclusively, and private keys get mode 0600. The CLI prints sanitized results only.
4. **Runbook, `docs/r2/runbooks/governance-activation.md`.** Ordered operator steps, each with its command, its check and its stop condition:
   1. offline keys;
   2. registry;
   3. image pin;
   4. genesis enrollment;
   5. first ISSUE;
   6. successor checkpoint;
   7. attestor service;
   8. app env and mounts;
   9. backup/restore drill;
   10. REVOKE and key rotation.

   It records which items remain external evidence.
5. **Not here:**
   - a live key or host;
   - online grant administration;
   - a key rotation ceremony beyond refusal (the publisher accepts approval sequence 1 only);
   - a Compose file change. The runbook gives the mounts; the deployment's own file is the operator's.

## Tests

- **Unit:** every builder's bytes parse with the existing parser. Signatures verify, and a wrong key fails.
- **Integration, PostgreSQL:** the full ceremony in a temporary root with test keys:
  - enroll → import ISSUE → next-body → sign → publish → `verify_operator_archive_preflight`, then the checkpointed grant reader reports the scope as current;
  - enrolling twice, enrolling over a nonempty ledger, and publishing a checkpoint signed by the wrong key are all refused.
