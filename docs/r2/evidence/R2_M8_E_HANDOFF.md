# M8-E handoff (2026-10-14)

**Branch:** `impl/r2-m8e-format`. **HEAD:** `c0e7029b`, pushed (updated after the review fixes). Not merged into `r2-v2/main` (`52183f4b`).
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

## The fourth Codex review (at `4acbe8dd`): fixed in `eb672993`

All 11 findings are fixed, each with a regression test; the decisions are plan items 12–18.
- `76696b6b` adds page tests and shows a refused review packet. `pnpm check`: 2593 passed.
- `c0e7029b` reseals parity at `76696b6b`: PASS, with F07 measured per dimension. `verify_donor_parity` reports OK, and the registry digests are updated.
- Format tests passed on SQLite (113 passed, 2 skipped as PostgreSQL-only) and on PostgreSQL 18 (115 passed, 0 skipped).
- A browser check on dev servers ran the whole flow (plan, render, checks) and showed the 503 grant message for review.

## Still open

- A Codex verification round on `4acbe8dd..c0e7029b`.
- The real blind review by the sponsor. It needs a server with activated showrunner grants (staging); dev returns 503.
- The final evidence seal, then merge after the user approves.

## Environment

- The disposable PostgreSQL 18 runs in container `r2-m8d-pg18` on 127.0.0.1:55481.
- The donor clone is `~/.cache/r2-donors/openmontage`, pinned at `08e2151f`.
