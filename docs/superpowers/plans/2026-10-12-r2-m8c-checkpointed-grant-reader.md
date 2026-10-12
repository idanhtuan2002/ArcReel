# M8-C transaction-bound checkpointed grant reader plan

Status: internal building block after `3dfdef2e`. No production trust anchor, caller migration or activation.

**Goal:** deny a current signed grant unless a freshly loaded signed checkpoint names the exact locked database head in the same caller transaction.

**Interface:** `CheckpointedShowrunnerGrantReader` subclasses the existing current reader. Its constructor takes explicit grant/checkpoint key IDs and public keys, deployment ID, and an async loader callback. `require_current_locked(session, scope)` first uses the existing scoped head lock/full signed-chain/current-ISSUE validation, then loads and verifies a checkpoint and compares exact scope `(head_sequence, head_event_digest)` to the verified event. It maps loader/signature/missing-scope/mismatch to a sanitized `ShowrunnerGrantUnavailableError`. The inherited historical ISSUE check calls this overridden current method before following history, so replay also requires current checkpoint equality. All inputs remain caller-supplied; no registry, route, startup caller or file path is installed here.

- [x] Write PostgreSQL tests for matching ISSUE, missing/wrong/old checkpoint and both importer-first and reader-first lock schedules, checking actual backend blocker where material.
- [x] Run RED at absent class.
- [x] Implement the class without weakening existing local reader semantics.
- [x] Run affected PostgreSQL/SQLite grant-review tests and static/test-audit gates; update handoff and commit.

Later deployment work must pin registry digest/image/deployment identity, provide the directory loader, wire every Governance-backed caller, and run restore/independent review before production APPROVE or READY.
