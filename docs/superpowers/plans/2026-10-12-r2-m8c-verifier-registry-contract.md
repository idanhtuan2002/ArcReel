# M8-C verifier registry pure contract implementation plan

**Status:** bounded contract slice after `c1090ff6`; no operator enrollment or production key activation.

**Goal:** parse one exact canonical public-key registry from caller-supplied bytes and return a digest for comparison against a separately approved operator manifest.

**Wire shape:** canonical UTF-8 JSON with exactly `schema`, `deployment_id`, `registry_sequence`, `grant_event`, and `grant_checkpoint`. Schema is `governance.verifier_registry.v1`. Both purpose records contain exactly `key_id` and unpadded base64url `public_key` encoding 32 bytes. Deployment/key IDs are nonempty, unpadded and non-wildcard. `registry_sequence` is a strict positive integer; it is an audit coordinate, not rollback protection by itself. The two key IDs and key bytes must differ. The complete file is capped at 4,096 bytes before decoding. Return typed immutable values and a SHA-256 digest of the exact canonical file bytes; do not claim the digest is trusted until a separate operator manifest pins it.

**Failure:** duplicate/unknown fields, noncanonical bytes, invalid UTF-8, wrong purpose, malformed key encoding/length, boolean sequence, oversized input or equal key material raise one sanitized `VerifierRegistryInvalid` without exposing submitted bytes.

- [x] Write fixed valid vector and adversarial contract tests first.
- [x] Run RED at absent parser API.
- [x] Implement the pure parser in `r2/contracts/governance_verifier_registry.py` without file or database access.
- [x] Run affected tests, Ruff, basedpyright, lint-imports, deptry, test audit and diff check; update handoff and commit.

The future deployment packet owns trust-anchor digest custody, registry sequence transition/rotation, directory mount, startup wiring and restore drill.
