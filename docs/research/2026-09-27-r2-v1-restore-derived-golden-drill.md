# R2 V1 — restore-derived Golden A/B drill (V1-05 closure step)

Date: 2026-09-27. Base: `feat/r2-m7e-v1-lineage` at `ea16418b`. This is
research and a proposed procedure, not implementation. License analysis is out
of scope.

## Question

`attest_deployment_restore` needs `GoldenRestoreEvidence`. That is the
no-provider read, review and export of at least two Golden products on a
restored target. How can this be produced from what exists today?

## Facts (source-backed)

1. **Requirement.**
   - Backlog V1-05 acceptance: "clean-target no-provider Golden
     review/export, measured RPO/RTO".
   - M7 spec §8 step 6 and the recovery-closure design §7: RTO ends only when
     restore, verification and the no-provider Golden read, review and export
     all pass.
   - M7-E plan E2 adds a browser workflow on a restore-derived target. That
     is the separate V1-07 packet.
2. **The Golden products exist only inside integration tests.**
   - Golden A (H.264 factual): `r2/m3/fixtures/golden_a_h264.json` with
     `FixtureOpenMontageBackendH264`, in
     `tests/integration/r2/m3/test_golden_a_real_media_closure.py`.
   - Golden B ("ledger reveal", two profile siblings): the
     `tests/fixtures/r2/m6_dual_profile_corpus.py` corpus, in
     `tests/integration/r2/test_m6_dual_profile_acceptance.py`.
   - Both render real Remotion output with zero provider cost
     (`R2_M3_REAL_MEDIA_CLOSURE.json`). Both run in pytest temp dirs, not as
     Host projects in a deployment.
3. **Host entry points (P1 gate surface, `server/routers/gates.py`):**
   - Gate A: `POST /projects/{p}/gates/greenlight`, stored in the DB.
   - Gate B: `POST /projects/{p}/gates/narrative-lock`, via
     `AdaptationAuthorityService`. An end-to-end test exists
     (`test_gates_narrative_lock_e2e.py`).
   - Gate C: `POST /projects/{p}/gates/final-cut`. It stages a rendered file
     from `production/` through `GoldenAHostIntegration`, which writes version
     history, the Artifact Manifest and `r2_m3_current/`, and stores a
     `FinalCutReceipt`.
   - Gate D: `POST /projects/{p}/gates/publish-approval`, stored in the DB.
   - `GET /projects/{p}/gates` returns the history.
4. **There is no separate export mechanism.** The P1 evidence says: "Gate D's
   deliverable_digest reuses whatever digest the approved Final Cut
   candidate already carries. No distinct final-export/packaging mechanism
   exists today".
5. **Backup and restore.**
   - `scripts/r2/deployment_backup.py` covers create, restore, verify and
     attest.
   - `verify` resolves `current_version`, Artifact Manifest entries and asset
     paths, and runs ffprobe on the selected media.

## Inferences

- A restore-derived Golden run has three parts: materialize the Golden
  products as real Host projects in a disposable source deployment, back up
  and restore that deployment, then read, review and export on the restored
  target.
- By the P1 precedent (fact 4), V1 "export" means the approved final-cut file
  on the restored target: it resolves, decodes, and its bytes hash to the
  Gate D `deliverable_digest`. Adding a new export mechanism would be a new
  product decision and is not required.

## Proposed procedure (a drill script plus an evidence file; no product change)

1. **Source.** Create a disposable PostgreSQL database at Alembic head and an
   empty data root. Start the real app (uvicorn) against them with
   `DATABASE_URL` and `ARCREEL_DATA_DIR`, and no provider credentials.
2. **Materialize the products.** Use three projects: `golden-a-h264`,
   `golden-b-western` and `golden-b-shuangwen`. For each:
   - run the existing fixture pipeline (no provider; real Remotion render)
     into `production/`;
   - drive the real HTTP gate routes: A greenlight, then B narrative lock
     (Golden B), then C final cut, then D publish approval, with
     `deliverable_digest` set to the final-cut sha256.
3. **Offline backup.** Stop the app, then run `deployment_backup create`.
4. **Incident.** Record the incident time, then drop the source database and
   delete the source data root.
5. **Restore.** Run `restore` into a new empty database and root, then
   `verify --restore-target-id …`.
6. **Read, review and export on the restored target.** Start the app against
   the restored database and root. For each project:
   - `GET /projects/{p}/gates` shows receipts A, C and D (and B for Golden B);
   - the version manager's current version resolves to the approved master;
   - the file decodes with ffprobe;
   - the file's sha256 equals the Gate D `deliverable_digest`;
   - no provider call occurs (no credentials are present after restore).
7. **Evidence and attest.** Write the `GoldenRestoreEvidence` JSON (three
   products, each with `reviewed` and `export_digest`). Then run `attest`
   with the measured RPO (incident time − recovery point) and RTO (incident
   time → export checks passed). The set becomes VERIFIED.
8. **Record.** Write an evidence file and handoff, bound to the candidate
   HEAD.

## Unknowns and risks

- **Render time.** Remotion takes about 3.5–4 s per output second, so about
  75 s + 2 × 90 s of output means roughly 15 minutes of rendering.
- **Gate B inputs.** Gate B needs the full admission command; I will reuse
  the command construction from `test_gates_narrative_lock_e2e.py`.
- **Runtime DB and data root.** The app must honour `DATABASE_URL` and
  `ARCREEL_DATA_DIR` for both runs; to be confirmed when the script is built.
- **Browser checks.** These stay in V1-07 (E2), not in this drill.
