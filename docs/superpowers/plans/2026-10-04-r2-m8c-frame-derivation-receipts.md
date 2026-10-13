# M8-C Frame Derivation Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The project permits at most one background agent and keeps final authority with the main agent.

**Goal:** Register two exact PNG frames derived from approved Gate C video masters with immutable, scoped derivation receipts that can later serve as M8-C spatial sources.

**Architecture:** Decode outside the database lock from pinned parent bytes, publish each frame without replacement, then lock and revalidate the parent heads and frame bytes before inserting candidate object plus receipt in one transaction. The receipt ID is the derived candidate ID; its separate digest binds the parent, decoded ordinal, recipe/build and output bytes. The receipt row also owns the scoped command key and digest for replay. A pair suitability decision and spatial execution are separate later gates.

**Tech Stack:** Python, FFmpeg CLI, SQLAlchemy async, Alembic, Pydantic, pytest, PostgreSQL and SQLite.

**Spec:** `docs/superpowers/specs/2026-09-30-r2-m8c-binding-authority-design.md`, `docs/research/2026-10-03-r2-m8c-frame-selection.md`, `docs/research/2026-10-03-r2-m8c-frame-custody-seam.md`, `docs/research/2026-10-03-r2-m8c-source-digest-vectors.md`.

## Global Constraints

- The current design checkout has Alembic head `8a8c4a0e0001`; verify the integrated branch head before creating a migration. If it differs, rebase the migration plan on that live head.
- First source path: two distinct, current approved episode-video masters; decoded frame index starts at zero; recipe `m8c-frame-rgb24-png-v1`; output PNG; exact decoder build enters identity.
- Frame candidate ID: `m8f:` plus the complete SHA-256 hex of the canonical frame-identity envelope. The receipt ID equals that candidate ID; the receipt digest is separate.
- Verify the complete scoped DB/manifest projection with `verify_masters`; `DatabaseMasterResolver.get_exact` alone accepts a missing projection.
- No provider call, paid route, migration execution against a live database, pair approval or production activation is authorized by this plan.
- Run the affected test selection first; test-file changes also require `scripts/audit_tests.py --check`. Final acceptance needs PostgreSQL concurrency/fault gates and independent exact-HEAD review.

## Review Focus

1. A master from another project or a superseded head must leave zero frame rows; Task 3 owns these tests.
2. A competing destination created during publication must remain unchanged; Task 2 owns this test.
3. An out-of-range decoded ordinal can make FFmpeg exit zero with no output; Task 2 requires an explicit missing-output test.
4. A crash after file publication but before row commit must admit only an exact rehash-and-register replay; Task 3 owns this test.
5. A frame with altered bytes or a changed decoder/recipe under a reused command must conflict; Task 3 owns these tests.

---

## File map

| File | Responsibility |
| --- | --- |
| `r2/contracts/spatial_source.py` | Typed frame identity and receipt bodies, canonical digest verification. |
| `r2/advanced_creative/frame_custody.py` | Pure derivation and replay rules over injected reader/publisher/repository ports. |
| `lib/db/models/spatial_source.py`, `lib/db/repositories/spatial_source.py` | Scoped receipt persistence and current-parent locking. |
| `alembic/versions/8b8c4a0e0001_add_spatial_frame_receipts.py` | Receipt table, composite FKs and uniqueness if the live head remains `8a8c4a0e0001`. |
| `server/services/spatial_source.py` | FFmpeg argument construction, bounded decode and host composition on one session. |
| `tests/unit/r2/advanced_creative/test_frame_custody.py` | Digest/identity, stale/replay and parser behavior. |
| `tests/integration/r2/advanced_creative/test_frame_derivation.py` | Real Gate C parent, media publication and DB transaction paths. |
| `tests/integration/lib/db/migrations/test_spatial_frame_receipts.py` | Upgrade/downgrade and scoped FK checks. |

### Task 1: Typed identity, receipt and scoped schema

**Interfaces:** `FrameIdentityV1` validates the proposed source-vector body; `FrameDerivationReceiptV1` binds the complete identity, candidate ID, byte size/probe digest, creation time and command digest. `SpatialFrameReceiptRepository.get_exact(user_id, project_name, receipt_id)` returns a receipt only in scope; `insert(...)` stages one immutable row without committing.

- [ ] Write failing unit tests that load `m8c_source_digest_vectors.json`, validate both receipt bodies, reject mismatched `m8f:` ID/body digest and reject a changed parent/recipe/frame under the same receipt ID.
- [ ] Run `pytest tests/unit/r2/advanced_creative/test_frame_custody.py -q` and confirm the new tests fail for missing contracts.
- [ ] Add the typed contracts and canonical digest functions, then rerun the unit file to GREEN.
- [ ] Write migration tests for a scoped FK to `candidate_objects(user_id, project_name, candidate_id)` and to `master_head_versions(user_id, project_name, artifact_key, master_version)`; an out-of-scope candidate or parent must fail at the database.
- [ ] Add the receipt model/repository and migration with primary key `(user_id, project_name, receipt_id)`, `receipt_id == frame_candidate_id`, unique `(user_id, project_name, command_id)`, stored `command_digest`, immutable `receipt_body_json`/`receipt_digest`, and `ON DELETE RESTRICT` authority FKs. The row itself is the frame command receipt; do not extend the unrelated M8 exploration command-operation enum. Run the migration test to GREEN on SQLite and the repository test against PostgreSQL before acceptance.
- [ ] Run targeted Ruff, basedpyright, migration downgrade/upgrade and test audit. Commit only Task 1 files.

### Task 2: Bounded frame decode and publish-if-absent

**Interfaces:** `decode_frame(parent_path: Path, decoded_frame_index: int, recipe_version: str, decoder_identity: str, output_temp: Path) -> FrameProbe` returns exact PNG size/digest after validated FFmpeg execution. `publish_frame(temp: Path, final: Path, media_root: Path) -> Path` publishes without replacement and reports an existing unequal destination as conflict.

- [ ] Write failing integration tests for indices 0/1/2 of a distinct-frame clip, out-of-range index with FFmpeg exit zero, negative index, malformed output, a competing final pathname and exact equal-byte replay.
- [ ] Run `pytest tests/integration/r2/advanced_creative/test_frame_derivation.py -q` and confirm the new cases fail for missing behavior.
- [ ] Build FFmpeg arguments as a list using `select=eq(n\,N),format=rgb24`, `-fps_mode passthrough`, `-frames:v 1`; validate one output, bounded size/dimensions and a matching decoder/recipe before returning its digest. Do not shell-interpolate paths or indices.
- [ ] Integrate the reviewed `fix/r2-m8c-frame-publish` candidate only after exact-diff review. Use its publish-if-absent behavior or an equivalent anchored-directory primitive; `os.replace` cannot publish the frame. On collision, rehash the existing bytes and compare its registered receipt before replay.
- [ ] Run the task integration tests, candidate-store tests, Ruff, basedpyright and audit. Commit only Task 2 files.

### Task 3: Transactional frame registration from two Gate C parents

**Interfaces:** `FrameDerivationService.derive(user_id, project_name, parent_artifact_key, expected_master_version, decoded_frame_index, command_id) -> FrameDerivationReceiptV1`. Its constructor receives the shared `AsyncSession`, project directory and injected decoder/publisher ports with production defaults. The service owns decode/publish, sorted authority locks, complete projection verification, exact candidate and receipt insertion, and one commit. An integration test can pause the injected decoder after real decode to force a parent promotion before the commit lock.

- [ ] Extend the existing two-master Gate C fixture with intentionally distinct visual frames; write failing tests that derive MASTER and REVERSE receipts and assert frame bytes/digests, parent versions and scoped rows.
- [ ] Write failing tests for wrong project, missing projection, superseded parent between decode and commit, changed frame bytes, changed recipe/decoder under one command, crash after file link before database insert, and same-command exact replay. Assert zero new rows on each conflict.
- [ ] Implement the service through existing `MasterAuthorityRepository`/`CandidateObjectRepository` and new receipt repository. Decode outside locks; at commit lock the sorted parent master rows, call scoped full `verify_masters`, rehash parent/frame bytes, and stage candidate plus receipt/command row in one session. Return a replay only after rereading exact rows and bytes.
- [ ] Run the complete affected integration files under SQLite, then a PostgreSQL forced interleaving for parent advance, two competing frame writers and rollback. Record exact command output and HEAD.
- [ ] Run targeted static checks, test audit and affected-domain gates; obtain independent exact-HEAD review before any C1 source-custody acceptance. Commit only Task 3 files.

## Self-review and boundary

Tasks 1–3 produce frame custody only. They do not prove that two frames depict a suitable front/reverse pair, run the spatial model, persist its raw response, append a spatial revision or authorize C2 promotion. Those require the separate pair-admission and spatial-completion plans. The proposed receipt/link schema and lock order remain subject to a PostgreSQL fixture and independent review; do not treat this plan or its vector tests as authority.
