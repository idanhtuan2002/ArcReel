# R2-M8F utility execution plan (F0–F3)

**Parent plan:** `2026-09-13-r2-m8f-integrated-utility.md`. **Decisions:** `docs/research/2026-10-15-r2-m8f-evaluation-and-profile-seam.md`
(DEC-F-0 … DEC-F-3), ADR-0105. **Branch:** `impl/r2-m8f-utility` from `r2-v2/main` `6d4f7369`.

## F0 — lineage resolution v2 (done, `560f1aa4`)

ADR-0105: admitted projects bind their M6 profile; ambiguity and an episode other than 1 are refused.

## F1 — pre-registration

- **Corpus builder:** `tests/fixtures/r2/m8f_corpus.py` is pure and deterministic. For each cohort
  (`WESTERN_GENERIC`, `CN_SHORT_DRAMA_SHUANGWEN`) it emits:
  - the creative project `m8f-<cohort>`: an episode-1 script built from Golden B's profile scenes, with shots
    SH01 (MASTER) and SH02 (REVERSE);
  - the learning projects `m8f-<cohort>-train` and `m8f-<cohort>-holdout`: YouTube Analytics day tables, one
    video per arm (`landscape-16x9@1`, baseline; `vertical-9x16@1`). Train days fall before registration;
    holdout days fall after it.

  `corpus_manifest()` returns the input digests without touching the database.
- **Protocol:** `docs/r2/evidence/R2_M8_EVALUATION_PROTOCOL.json`. It locks:
  - the corpus source hashes and `manifest_digest`;
  - cohorts, baseline arm, endpoints, effect policy, design class and windows;
  - the holdout salt and share, and the exclusions (none);
  - rubrics and reviewer qualification, deviations, the resource envelope, replay determinism and stop
    codes;
  - `registered_at`.
- **Verifier:** `scripts/r2/verify_m8_evaluation_protocol.py` recomputes the hashes and the manifest, and
  checks the required fields. It refuses a results file whose `protocol_digest` differs from the protocol or
  whose commit does not descend from the protocol commit. Every refusal is `M8_EVALUATION_NOT_PREREGISTERED`.
- **Tests:** `tests/unit/scripts/test_verify_m8_evaluation_protocol.py` and
  `tests/unit/r2/test_m8f_corpus.py` (determinism, cohort separation, holdout split).
- Commit `test(r2): preregister M8 utility evaluation`.

## F2 — integrated cohort runs

1. **Automated run.** `tests/integration/r2/test_m8f_integrated_utility.py` runs on SQLite and on PostgreSQL
   18, once per cohort, through the host services. The steps:
   - admit the screenplay;
   - Canvas: save sibling alternatives, reload them and check history;
   - Spatial: frames, an execution with the pinned fixture vision, then preview and promotion through
     approval support;
   - Format: plan, render, technical checks, a review by the test reviewer, then candidate, preview and
     promotion at 9:16 and 1:1;
   - Learning: ingest train and holdout, evaluate, then replay against the registered protocol;
   - baseline arm: the same corpus with no M8 calls;
   - invariant probes: profile leak, stale preview, retry after unknown, restart and concurrent promotion.
2. **Results and replay determinism.** `scripts/r2/m8f_utility_run.py` runs the flow twice from an empty
   database and writes `docs/r2/evidence/R2_M8_F_RESULTS.json`. The two runs must have identical artifact
   digests and verdicts. The file also records resources (wall time, peak RSS, disk) and binds
   `protocol_digest`.
3. **Sponsor blind review on V2 staging.** The corpus is seeded with the same builder. The sponsor reviews
   the four format projections (2 cohorts × {9:16, 1:1}) and the two spatial candidates. The record is
   `R2_M8_F_BLIND_REVIEW_<date>.json`, with deviations. The staging render digests must equal the automated
   run's.
4. Commit `test(r2): demonstrate profile-isolated M8 utility`.

## F3 — dossier

Run the affected gates, the test audit, the evidence and parity verifiers and `git diff --check`. Write
`R2_M8_ACCEPTANCE.json` bound to the exact clean HEAD. Then get an independent Codex review and stop.
Production stays unapproved.
