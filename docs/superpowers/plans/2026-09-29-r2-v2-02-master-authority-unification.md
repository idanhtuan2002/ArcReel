# R2 V2-02 Master Authority Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`.
> Use `superpowers:test-driven-development` for every behavior change. Steps use
> checkbox (`- [ ]`) syntax.

**Goal:** Make the M7 database master head the sole master authority for host-served R2
artifacts. The file manifest's `approved_master` becomes its guarded projection (ADR-0096).

**Architecture:**

- **Composition.** A host composition module wires the existing M7-B pieces onto one
  `AsyncSession`: `prepare_candidate` in verify-in-place mode, `CandidateObjectRepository`,
  `MasterAuthorityRepository`, `PromotionReceiptRepository`, `AtomicPromotionService`, and
  `DatabaseMasterResolver` with a `FileMasterProjection`.
- **Gate C** promotes in the database, then projects the file master with the existing
  `ProductionApprovalService`.
- **Master-consuming routes** verify the project's masters through the resolver before their
  file work.

**Decision:** `docs/adr/0096-v2-the-m7-master-head-is-the-sole-master-authority.md`.
**Research:** `docs/research/2026-09-29-r2-m8a-master-authority-seam.md` (V2-02 section).

**Base:** `r2-v2/main` at the commit that adds this plan. **Branch:** `feat/r2-v2-02-master-authority`.

## Owned files

Create:

- `r2/host_hardening/master_authority.py`: `m7_candidate_id`, `stream_probe_digest`,
  `FileMasterProjection`, `MasterAuthorityUnit` and `verify_project_masters`.
- `scripts/r2/backfill_master_authority.py`
- `tests/unit/r2/host_hardening/test_master_authority.py`
- `tests/integration/r2/host_hardening/test_master_authority_unit.py`
- `tests/integration/server/routers/test_gates_master_authority.py`
- `tests/integration/scripts/r2/test_backfill_master_authority.py`
- `tests/architecture/test_master_authority_boundaries.py`

Modify:

- `lib/db/repositories/host_hardening.py`: add `MasterAuthorityRepository.list_current` (read-only).
- `server/routers/gates.py`:
  - Gate C: promote, then project;
  - guards on the composite dependencies, publish approval and deliverable token.
- `tests/drills/r2/golden_restore_drill.py`: add a `MASTER_AUTHORITY_DIVERGED` check.
- `docs/r2/runbooks/v1-operator.md`: add the backfill release step.

## Fixed behavior

- **Candidate id.** `m7_candidate_id(artifact_key, generation_candidate_id)` is `"m7c:"` followed
  by the first 40 hex digits of `sha256(f"{artifact_key}\n{generation_candidate_id}")`.
- **Probe digest.** `stream_probe_digest(path)` is `"sha256:"` plus the sha256 of the canonical
  JSON list of `(codec_type, codec_name, width, height)` over the `ffprobe -show_streams` output.
  If ffprobe is unavailable or fails, it raises `CandidateMediaProbeMismatchError`, so Gate C
  refuses (fail closed).
- **`MasterAuthorityUnit.promote_staged(...)`.** It takes `user_id`, `project_name`,
  `artifact_key`, `generation_candidate_id`, `version_file`, `approval_record` and `command_id`,
  and returns a `MasterHeadSnapshot`. The steps are:
  1. check for an exact receipt replay;
  2. verify the version file in place through `prepare_candidate`, with `final_path`,
     `media_root` equal to the project dir, and `expected_content_digest` equal to its sha256;
  3. insert the candidate object unless an equal one exists. An unequal one raises
     `CandidateIdentityConflictError`;
  4. read `expected_master_version` from `get_current_version`;
  5. call `AtomicPromotionService.promote`, with `commit=session.commit`.

  The domain errors map to route 409s:
  - `PromotionExpectedVersionConflictError`, `MasterHeadConflictError`;
  - `PromotionReceiptReplayMismatchError`;
  - `CandidateIdentityConflictError`, `CandidateArtifactMismatchError`.
- **`FileMasterProjection.get_selected_candidate_id`.** It reads the manifest entry's
  `approved_master.selected_candidate_id` for the artifact key and returns `m7_candidate_id`
  of it, or `None` when there is no R2 approved master.
- **`verify_project_masters(session, *, user_id, project_name, project_dir)`.** It runs
  `DatabaseMasterResolver.get_exact` over the union of the artifact keys that have a database
  head (`list_current`) and the keys that have a file `approved_master`. It raises
  `MasterDivergedError` on the first divergence. The resolver's rule holds: a missing file
  opinion is not a divergence.
- **The Gate C order:**
  1. stage (worker thread);
  2. `promote_staged` (async, one transaction);
  3. `host.approve` and the export (worker thread);
  4. the Gate C receipt.

  `command_id` is the route's `operation_id`. A retry replays every step. A divergence,
  conflict or probe failure returns 409 `master_*` detail, and nothing is projected.
- **Guards.** Before their file work, the Gate C composite path (the source masters), publish
  approval (`APPROVE_PUBLISH`) and `create_deliverable_token` call `verify_project_masters`.
  A divergence returns 409 `master_diverged`.
- **Download route.** The token-authenticated download route has no user id, so it keeps its
  file checks. Its token is issued only after a verified listing.
- **Backfill.** `backfill_master_authority.py --user-id <id> --project <name>` (or `--all`)
  promotes each file `approved_master` that has no database head, with command
  `backfill:<artifact_key>:<generation_candidate_id>`. Its output is a JSON summary. An
  existing equal head is skipped; a divergent one is reported and exits 2.

## Tasks

- [ ] **T1: unit tests (RED), then the pure pieces.**
  - **Tests:** candidate id stability and scope separation, probe digest, and projection
    mapping (present, absent, non-R2).
  - **Implement:** `m7_candidate_id`, `stream_probe_digest` and `FileMasterProjection`.
- [ ] **T2: integration tests (RED), then `MasterAuthorityUnit`, `list_current` and
  `verify_project_masters`.** The tests cover, on SQLite and PG16:
  - first promotion;
  - exact replay;
  - divergent replay;
  - a stale expected version (two units);
  - a changed version file (a digest conflict);
  - rollback of every staged row on failure;
  - verify with equal, missing-projection and diverged states.
- [ ] **T3: Gate C route tests (RED), then the route change.** The tests cover:
  - approval creates the database head, receipt, event and projected file master;
  - a retry after an injected projection failure converges;
  - a divergent project is refused by the composite, publish and token routes;
  - the existing `test_gates_export.py` and Gate C tests stay green.
- [ ] **T4: backfill tests (RED), then the script.** The tests cover idempotence, the summary,
  the divergent exit 2, and an offline `GoldenARunner` project that becomes verifiable.
- [ ] **T5: architecture test.**
  - `ProductionApprovalService(` and `.approve(` of `GoldenAHostIntegration` appear only in
    `r2/m3/host_integration.py`, `r2/m3/golden_a.py` and `server/routers/gates.py`'s projection
    step.
  - `AtomicPromotionService(` appears only in `r2/host_hardening/master_authority.py`.
- [ ] **T6: drill and runbook.** Add the drill check comparing the database head with the
  projection for each product, and the runbook backfill step.
- [ ] **T7: gates.** Run:
  - ruff, basedpyright, lint-imports, deptry and audit_tests;
  - the targeted suites: host_hardening, gates, deliverables, m3, backfill and architecture,
    on SQLite and on PG16 `arcreel_v201`;
  - Commit; then request an independent Codex review.
