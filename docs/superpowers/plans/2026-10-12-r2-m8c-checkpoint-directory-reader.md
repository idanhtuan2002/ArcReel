# M8-C checkpoint directory reader implementation plan

**Status:** bounded internal follow-up to the recovery scanner at `f211a718`. No deployment mount, verifier registry, signer, startup caller or production activation.

**Goal:** supply the scanner with complete checkpoint bytes from an operator-provided directory, reopening the named file after the scanner obtains its exclusive import fence.

**Design:** add `server/services/governance_checkpoint_file.py` with a fixed `grant-checkpoint.json` basename and an explicit absolute directory path. An async `load()` uses a bounded synchronous file read in a thread. The reader walks the absolute directory without symlinks, opens the final regular file with `O_NOFOLLOW | O_NONBLOCK`, reads at most `MAX_GRANT_CHECKPOINT_BYTES + 1`, and rejects missing, empty, oversized, nonregular or changing files with a sanitized error. It neither parses nor trusts bytes; the scanner verifies the signature, deployment and exact database heads.

The deployment contract requires complete sibling-file write, fsync and same-directory rename by the operator. The reader is not a publication API. A host that replaces both the trusted directory and image remains outside the stated threat limit.

- [x] Write tests for initial read, fresh pathname read after atomic rename, interrupted sibling publication retaining the old file, missing/oversized/empty/symlink/nonregular file and symlinked directory rejection.
- [x] Run RED at absent reader API.
- [x] Implement the bounded reader without adding a Compose mount or application caller.
- [x] Run focused tests and affected static/test-audit gates; record exact results and commit the isolated slice.

Next packet still must own the operator-pinned verifier registry, retained high-water history, actual Compose visibility drill and startup/transaction-bound authority wiring.
