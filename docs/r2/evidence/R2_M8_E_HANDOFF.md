# M8-E handoff (2026-10-14)

**Branch:** `impl/r2-m8e-format`. **HEAD:** see `git log`; code at `c9d28aee`, evidence sealed after it, pushed. Not merged into `r2-v2/main` (`52183f4b`).
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

## Codex verification rounds after `c0e7029b`

- **Verification round** (`5d7a4715`, `0b54b5ad`). Codex reported 7/11 fixed, 4 partial, and 3 new findings. The fixes:
  - candidate preparation locks the candidate head before the plan reports (a PostgreSQL deadlock, reproduced by mutation);
  - a stored semantic pass is revalidated, and ungranted reviews are ignored;
  - review copies are re-encoded;
  - a media race returns 409;
  - F07 is measured per side, with directory mtimes and hashes;
  - the page reuses the render command after an unknown outcome.
- **Confirmation round** (`c9d28aee`). Codex left 2 Medium findings, both fixed:
  - semantic report ids cover grants;
  - an unrecorded success is `m8_format_render_incomplete` (503), which can be retried with the same command.
- Parity resealed at `0b54b5ad`: PASS, `verify_donor_parity` OK, registry digests updated (`59e7b785`). The commits after it change neither `IMPLEMENTATION` file.
- Tests at `c9d28aee`:
  - SQLite: 116 passed, 3 skipped (PostgreSQL-only);
  - PostgreSQL 18: 119 passed, 0 skipped;
  - `pnpm check` at `5d7a4715`: 2594 passed. The frontend is unchanged since.

## Blind review and evidence seal (2026-10-15)

- Deployed `93cb85c0` to V2 staging after a database backup; migrations `914`–`918` applied.
- The sponsor ran the whole flow in the browser on source master `m8e-review-source:SH01`: plan (9:16 PAD), render, 8 technical checks, blind review (7/7 PASS, one reviewer with a showrunner grant), candidate, preview and the first promotion into the empty format slot (version 0 → 1). Every request returned 200.
- Record: `R2_M8_E_BLIND_REVIEW_2026-10-15.json`, with its limits (one reviewer; the reviewer authored the plan; the 9:16 shape reveals the projection; only PAD at 9:16 was reviewed).
- Parity resealed at `93cb85c0`: PASS, `verify_donor_parity` OK, the `IMPLEMENTATION` digests are unchanged, and the registry digests are updated.

## Still open

- A final Codex review, then merge into `r2-v2/main` after the user approves.

## Environment

- The disposable PostgreSQL 18 runs in container `r2-m8d-pg18` on 127.0.0.1:55481.
- The donor clone is `~/.cache/r2-donors/openmontage`, pinned at `08e2151f`.
