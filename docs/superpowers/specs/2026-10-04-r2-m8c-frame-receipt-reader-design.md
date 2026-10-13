# M8-C current frame receipt reader — bounded design

Status: implementation design for the next frame-custody consumer, not pair admission, C1 acceptance or production activation. Source checkpoint `eb9bd2e6`; independent review of the integrated frame checkpoint completed at `656a7e24`. The C1 spatial worktree remains separate and dirty.

## Outcome and authority

The server must turn an exact `(user_id, project_name, frame_receipt_id, receipt_digest)` into immutable PNG bytes and verified lineage that a later spatial execution can consume. A receipt is historical evidence; it is usable only while its approved episode-video parent remains the current, completely projected Gate C master. No client may supply frame bytes, source view or parent identity as authority. Pair suitability and MASTER/REVERSE roles remain a separate human admission decision.

The reader returns a frozen `VerifiedSpatialFrame` containing the validated receipt, recomputed receipt digest and exact PNG bytes. Returning only an object path would allow the named file to change between verification and the model request. At most `MAX_FRAME_BYTES` are copied into a private file and rehashed; its PNG probe must match the receipt and registered candidate before those bytes are returned. Consumers must send the returned bytes or a private copy of them, and recheck source currentness before promotion.

## Interfaces and locking

`SpatialFrameReader.read_current(...)` is the standalone entrypoint. It reads a scoped receipt once to discover the parent artifact key, starts `serialized_artifacts` for that key, and delegates to `read_locked(...)`. The latter re-reads the receipt inside the same transaction, compares its recomputed digest to the pinned digest, and assumes its caller already holds sorted M7 master locks. Pair and M8 promotion writers call `read_locked` after their own M8 locks and after locking all distinct parent artifact keys in sorted order; `read_locked` must neither commit nor acquire an earlier M8 lock. A parent key that changes between the first read and the locked read is a conflict.

Under the lock, the reader uses the existing complete `verify_masters` projection check, exact current head and scoped candidate row. Parent key, version, candidate ID and content digest must equal the receipt identity; parent media bytes must still match the approved candidate. The frame candidate row must use `frame_candidate_id`, `artifact_key = spatial_frame:<id>`, the canonical project-local `spatial/frames/<id>.png` path, receipt byte size, frame content digest and probe digest. The reader rehashes and probes a private snapshot of that PNG. Missing, superseded, foreign, altered or malformed evidence raises `FrameSourceConflictError` before any bytes leave the service.

## Verification and limits

Integration tests use real Gate C approvals and derivation receipts. They cover exact read, wrong receipt digest/project, parent advance, missing projection, corrupted candidate row or PNG, and a path/name change during read. A PostgreSQL forced interleaving proves `read_current` holds the parent lock against a concurrent Gate C advance; a transaction-scoped test proves `read_locked` can run after sorted locks without committing them. Candidate bytes and receipt digest remain distinct. The existing same-UID directory mutation limitation requires a project-root ownership/fence decision before production, even when this reader returns verified bytes.

The reader adds no schema, provider call, route or pair decision. Its output is an internal server authority handle only. Acceptance requires affected SQLite and PostgreSQL tests, static gates and independent review of its exact integrated HEAD.
