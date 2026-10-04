# M8-C frame receipt consumer seam — source-backed candidate

Status: proposed interface for the next M8-C gate, **not** a pair-admission implementation or C1 acceptance. Frame-custody code checkpoint: `b47e13dc22153efdca0fe5310626441f63aa9bf0`. C1 working tree: `impl/r2-m8c-spatial-candidates` at `774952b235aa899c0125ee2109d426e9bc6dc9ff` plus eight preserved dirty paths.

## Current source facts

- `SpatialFrameReceiptRepository.get_exact` verifies the stored receipt body, duplicate columns and canonical receipt digest in its own `(user_id, project_name, receipt_id)` scope. `FrameDerivationService.derive` also verifies the current Gate C master projection and media bytes at registration. There is no read API that repeats master-currentness and frame-byte verification for a later consumer (`lib/db/repositories/spatial_source.py`, `server/services/spatial_source.py`). A once-valid receipt can remain historical after its parent head advances.
- The C1 normalizer accepts caller-supplied `sources: dict[str, SpatialSourceIdentity]`; each identity currently contains only `source_digest` and `MASTER`/`REVERSE` view. It copies those fields into `SpatialImageSpan`, and the raw model result supplies `source_ref` (`r2/advanced_creative/spatial.py` in the separate dirty C1 worktree). `SpatialPayload` contains assertions and `execution_id`, but no receipt IDs/digests (`r2/contracts/advanced_creative.py`). Thus passing raw model-selected source strings directly into that map is not an authority check.
- The proposed source vector gives a frame **candidate/receipt ID** beginning `m8f:`, a separate **receipt digest**, and a separate **frame content digest**. The proposed spatial-execution evidence vector carries all three for each ordered role (`tests/fixtures/r2/m8c_source_digest_vectors.json`, `tests/fixtures/r2/m8c_spatial_completion_evidence_vector.json`). The accepted M8-C design requires current parent verification and exact frame bytes before model execution and before promotion (`docs/superpowers/specs/2026-09-30-r2-m8c-binding-authority-design.md`, source and pair sections).

## Candidate read interface

The next consumer should request **exact `(user_id, project_name, receipt_id, receipt_digest, role)`**, with exactly one `MASTER` and one `REVERSE` from distinct parent artifact keys. A server reader should return a verified frame handle only after:

1. Reading each receipt through `get_exact` and comparing its recomputed digest to the caller's pinned receipt digest.
2. Checking the current scoped Gate C master/manifest projection, exact historical version/candidate ID/content digest in the receipt, and parent candidate/media bytes. Pair and promotion transactions must take master locks in ascending artifact-key order before this check; a standalone read can use `serialized_artifacts` for those keys.
3. Reading the frame candidate object in the same scope, requiring its ID, artifact key, object path, byte size, content digest and probe digest to match the receipt; then rehashing the file and checking the PNG probe before handing out bytes or a path.
4. Rejecting a superseded parent, missing projection, missing/altered file, cross-project row, changed receipt digest or duplicate role before any pair decision or model call.

For normalization, a candidate mapping is `source_ref = frame_receipt_id`, `source_digest = frame_content_digest`, `view = role`. The server should build that map from verified handles and give those exact refs to the model prompt; a raw response may only name members of the map. The receipt digest stays in the spatial completion/pair evidence rather than being substituted for image-byte digest in `SpatialImageSpan`. This mapping is an inference from the current C1 type and the fixed vectors; it needs a same-fixture test against a real pair receipt before freezing.

## Unresolved gate

The proposed reader must fit the M8 promotion lock order: M8 command/candidate/preview/binding/target/pair before sorted M7 master rows. It cannot start its own earlier master transaction while the promotion already holds earlier locks. Define a transaction-aware `read_locked(...)` and a standalone `read_current(...)` wrapper, then prove both with PostgreSQL forced interleavings. The current host lacks a local PostgreSQL server. Until that test and an independent exact-HEAD review pass, do not use the receipt as a promotion or provider-submission authority.
