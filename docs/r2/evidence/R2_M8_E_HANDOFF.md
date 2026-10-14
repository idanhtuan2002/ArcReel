# M8-E handoff (2026-10-14)

**Branch:** `impl/r2-m8e-format`. **HEAD:** `4ecd883a`, pushed. Not merged into `r2-v2/main` (`52183f4b`).
**Plan:** `docs/superpowers/plans/2026-10-14-r2-m8e-format-projection.md`, decisions 1–11 plus the reviewer decision.

## Done

| Part | Commits | Evidence |
|---|---|---|
| E1 persistence | `01d36d4e`, `b318f855` | Profiles and overlays fail closed; `validate_plan` recomputes geometry; reports are append-only with a per-plan sequence. |
| E2 donor parity | `017e702d` … `aa05e33e` | `R2_M8_E_FORMAT_PARITY.json` with its MEASURES file. The donor tests pass unmodified (3 passed). PSNR is 39.6–47.2 dB; crops are within 1 px of the donor's; `verify_donor_parity` reports OK. |
| E2 render on M7 | `d3de93e8` | Route `local-ffmpeg / format-projection / host-format-v1` with an `OFFLINE_VERIFIED` profile bound to the parity report digest. `m8_format_renders` is the success evidence keyed to `execution_attempts`. |
| E3 technical checks | `510f5e79` | The 8 checks are measured, and every verdict is recomputed from the plan. |
| E3 blind review | `172a7f45` | Packets labelled A/B; reports aggregated over reviewers; the single-reviewer deviation is recorded (sponsor decision). |
| E3 evidence gate and genesis | `546bdcdc`, `6c0e59a3` (`917c4a0e0001`) | A fail-closed `HostFormatEvidence` gates FORMAT preview and promotion. A format slot's first promotion may run at version 0, through a narrow contract amendment and an additive migration. |
| E3 API and UI | `4acbe8dd`, `fc6d1285`, `9e2bfdd4`, `4ecd883a` | The routes are tested over HTTP on SQLite and PostgreSQL 18. The formats page passes typecheck and lint but has no page tests yet. |

## Open: the fourth Codex review (at `4acbe8dd`) is blocking

Each finding below is still to be fixed, with a regression test:
1. Promotion reads reports and the source head without locks before taking the slot lock. Evidence must be serialized with report writers and source-head changes until the promotion commits.
2. Concurrent reviews can hide disagreement. The plan and artifact must be locked before duplicate checks and aggregation.
3. The A/B order is reversible: the reviewer can see the plan and render digests and hash the clips. Review assets need a neutral, access-bounded path, and identifying data must be withheld from reviewers.
4. A crash after ACCEPTED but before the success-evidence transaction is not recoverable. Recovery must rebuild the result from the durable attempt (job id `<execution>:<digest>`) and complete idempotently.
5. Long renders (up to 1800 s) outlive the 300 s M7 lease. The lease must be renewed during the render, and a lost fence must be handled before publication.
6. Reviewer assignment is self-service. It needs a stored assignment, and the deviation must be bound to the authorized reviewer (sponsor decision: a single reviewer, the sponsor).
7. Validation and review delivery hash a file and then reopen it. They must work from snapshots.
8. Overlay evidence is checked against ideal geometry. It must use the actual pixel geometry.
9. The missing-source parity row derives every dimension from booleans. It must measure each dimension or mark it explicitly.
10. Plan creation and candidate preparation hold transactions open across media I/O. Media must be prepared outside the transaction, then revalidated briefly.
11. Missing media returns HTTP 500. It must map to 404 or 409.

## Then

- The page tests, `pnpm check`, and a browser check with a real blind review by the sponsor (a human step).
- The E4 seal `R2_M8_E_FORMAT_PARITY.json`. Rerunning the harness changes its digest, so the registry `evidence_digest` and `test_provider_capabilities` must be updated together.
- A Codex verification round, then merge.

## Environment

- The disposable PostgreSQL 18 runs in container `r2-m8d-pg18` on 127.0.0.1:55481.
- The donor clone is `~/.cache/r2-donors/openmontage`, pinned at `08e2151f`.
