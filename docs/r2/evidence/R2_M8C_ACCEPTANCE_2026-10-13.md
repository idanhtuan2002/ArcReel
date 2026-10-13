# M8-C Spatial candidates: review and acceptance record

**Packet:** M8-C, Gate C (C1–C3) on `impl/r2-m8c-spatial-candidates`.
**Code HEAD reviewed:** `638e3152a27d8cf374f362f93233f3b15758760d`.
**Base:** `r2-v2/main` `0ac1a565`.

**Scope boundary** (`R2_M8C_COMPLETION_PATH_DECISION_2026-10-13.md`):
- SpatialCandidate promotion to `PRODUCTION_BINDING` stays fail-closed under ADR-0095 and contract amendment 2.
- The frame-receipts/Governance packet (`impl/r2-m8c-frame-receipts`) is a separate promotion prerequisite. It is paused at `227d6824`.

## Reviewer and its limit

The sponsor chose **self-review** by the implementing agent (Claude). No independent reviewer ran, and no source was sent to an external service. Two limits follow:
- The 17 frame-receipt commits, cherry-picked from `229a22ba..fab08ab5`, carry their earlier completed Codex review rounds. These are recorded in `R2_M8C_FRAME_CUSTODY_HANDOFF.md` on the frame-receipts branch.
- All other M8-C code has only this self-review.

## Review range and findings

Reviewed: every non-cherry-picked change in `r2-v2/main..638e3152`:
- C1 normalization and contracts;
- prompt and parse;
- the evidence contract;
- migration `8c8c4a0e0001`, its model and repository;
- the route inventory and capability profile;
- `SpatialExecutionService`;
- the tests.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| R1 | Important | The service submitted without `require_submit_route`. A release deployment could therefore call the `UNQUALIFIED` spatial route, bypassing the ADR-0091 paid-route gate. | **Fixed** in `638e3152`. The route is resolved under `current_release_mode()` before any provider call or attempt row. Test: `test_release_mode_refuses_the_unqualified_spatial_route_before_the_provider`. RED before the fix, GREEN after. |
| R2 | Medium | Exact replay did not compare `episode`. The same `command_id` with a different episode returned the old head. | **Fixed** in `638e3152`. Replay rebuilds the provider request from the command and the stored frames, then requires the stored `request_digest`. The changed-episode case went RED, then GREEN. |
| R3 | Low | `scene_name` has no length bound, so a very long name enlarges the prompt and its cost. | Recorded, not fixed. There is no public route yet, so the caller is internal. Bound it when a route is added. |
| R4 | Low (by design) | A crash between the provider result and the evidence commit leaves the attempt `ACCEPTED` with no evidence. That command then fails closed, and the caller must issue a new command, which may cost one more provider call. | Documented in the C2 spec §7. It never creates a fact. |
| R5 | Info | C2 has no public route and no app wiring. The capability is internal until a route packet adds it behind the same service. | Matches the C2 spec decision 1. |

Mutation checks during implementation removed a guard and confirmed that its test turned RED: the replay prompt check, the peer and inode checks (attestor branch), and R1/R2 above.

## Gate evidence at `638e3152`

| Gate | Command | Result |
|---|---|---|
| Donor parity | `scripts/r2/check_m8c_spatial_parity.py <pinned donor> --measure` | exit 0. Of the 5 cases, 4 are PARITY and 1 is IMPROVED; the correction is IMPROVED. |
| Parity report | `scripts/r2/verify_donor_parity.py docs/r2/evidence/R2_M8_C_SPATIAL_PARITY.json --head 638e3152… --donor-clone ~/.cache/r2-donors/dramaclaw` | `M8_DONOR_PARITY_OK`. 12 rows: 9 measured, 3 wholly EXCLUDED with reasons. No skips, no unknowns. |
| Gate C suites (fault, replay, authority boundary) | `pytest <Gate C selection>` on disposable PostgreSQL 18.6, migrated to head | **186 passed, 0 skipped, 0 failed** |
| Static | ruff check/format (1692 files), basedpyright, lint-imports, deptry, test audit | 0 findings. basedpyright 0/0/0; lint-imports 22 kept. |
| Full backend suite | `uv run python -m pytest -n 4 --dist loadfile` | Recorded in `R2_M8_C_IMPLEMENTATION_ACCEPTANCE.json` once complete. |

**Parity performance limit.** No spatial benchmark was pre-registered. The PARITY threshold was set after measurement:
- the R2 median must be within 2× the donor's and under 1 ms per case;
- measured: 1.3–1.6× the donor, 28–92 µs per case;
- peak allocation is within 0.3 KiB.

**No live provider call.** Gate C uses an offline vision fake at the provider boundary. The `gemini-generate-spatial@host-spatial-v1` profile is `UNQUALIFIED`.

**Paused frame-receipts suite.** The full suite that was running on the paused frame-receipts branch (`227d6824`) was stopped at 99% to free CPU. It has no verdict. That packet's open full-suite gate is unchanged.
