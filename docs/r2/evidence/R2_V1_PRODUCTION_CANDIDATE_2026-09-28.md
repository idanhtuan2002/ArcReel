# R2 V1 — production candidate dossier (2026-09-28)

## Status

**Status:** `PRODUCTION_CANDIDATE`, with one sponsor-accepted gate exception. The dossier never claims `PRODUCTION_APPROVED`.

**What production approval still needs.** Deployment, live migration, credentials, paid canaries and publication each need their own human or operations approval (ADR-0089; the V1 strategy).

## Identity

| Item | Value |
|---|---|
| Candidate (code) | `d5c4e6b09c53e82392da7416848b199b18b02df6`, branch `feat/r2-m7e-v1-lineage` |
| Gate evidence commit | `138b0c80`: only the runner's manifest and logs, `docs/r2/evidence/v1-release-gates-2026-09-28-run2/` |
| Alembic head | `c9e1f4a2b701` (ADR-0092) |
| Upstream base | 0.29.0 merge base `6ddedc77`; range to `317a7d0d` inventoried (4 UNCHANGED, 12 ADAPTED, 278 DEFERRED) |
| Rollback target | `20a030d8` |
| Tag | `r2-v1.0.0`, annotated, local only; it is not pushed |

## V1 release gate (strategy §6) against evidence

| Condition | Result | Evidence |
|---|---|---|
| Both product slices pass the media and restart/reopen criteria | MET | See below the table. |
| Every product has A, B, C and D decisions bound to exact revisions | MET | See below the table. |
| Enabled paid routes prove duplicate, restart and ambiguous-outcome behaviour | MET (no paid route is enabled) | See below the table. |
| Database plus media restore succeeds into a clean target | MET | Drill: backup set `bs-golden-drill`, manifest `sha256:7639…efaf`, restore target `golden-drill-target-1`, `attest` → `VERIFIED`; RPO 1 s, RTO 10 s (single machine). |
| Owner packets and host gates pass on the integrated SHA | MET, with one exception | 11 of 12 runner gates PASS. `migration` is accepted by the sponsor (see "Gate exception"). The M5C/M6/M7-A…D packets were accepted earlier; several are human-override acceptances, and their evidence files record this. |
| The release includes run, backup, recovery and manual-publication instructions, and truthfully identifies deferred automation | MET | `docs/r2/runbooks/v1-operator.md` (§1 lists what is disabled or manual) and `docs/r2/runbooks/m7-backup-restore.md` |

**Product slices.** Evidence: `R2_V1_08_GOLDEN_RESTORE_DRILL_2026-09-28.json` (the drill at `d5c4e6b0`) and the browser gate.

- **Golden A,** a factual explainer: 75.2 s.
- **Golden B,** a drama scene in two profiles from one Canon, Western and 爽文: 96.3 s each.
- **Checks:** each final is H.264 with AAC and decodes. Its host download matches Gate D, and it is re-composed byte-exact from the restored masters.
- **Restart and reopen:** covered by the browser gate.

**Gate decisions.** The drill's restored-target check found no problems for any product.

- **A:** a Greenlight for every product, recorded first.
- **B:**
  - the Golden A script lock (ADR-0092) is recorded before production;
  - the Golden B screenplay admission.
- **C:** a receipt for each shot master and for the composed final, with `audio_decision: MUTE` verified silent by the server.
- **D:** each is bound to the digest of the exportable final.

**Paid routes.**

- **No paid route is enabled.** In `PRODUCTION_CANDIDATE` every paid route is refused until an operator canary qualifies it (ADR-0091). Video, the Agent and trial runs cannot be qualified in V1.
- **Tested ambiguity behaviour:** no resend after an ambiguous outcome, with SDK retries off; budget before submit.
- **Not proven:** no route has a live proof, because no canary has run.

## Release gates (ADR-0091 T1)

- **Runner.** `scripts/r2/run_gates.py`, with `scripts/r2/v1_release_gates.json`.
- **Environment.** `TMPDIR` pointed at an on-disk directory; the browser gate ran on the drill's restored target.

| Gate | Result |
|---|---|
| `h1_h8` (whole backend) | PASS: 15018 passed, 45 declared skips |
| `migration` (PG16 round trip and dialect suite) | FAIL, accepted by exception: alembic up/idempotent/down/up exit 0; dialect suite 19 failed, 1052 passed |
| `static` (ruff, format, audit_tests) | PASS |
| `type` (basedpyright) | PASS |
| `imports` (lint-imports) | PASS |
| `dependencies` (deptry) | PASS |
| `i18n` | PASS: 18 passed |
| `frontend` (pnpm check and build) | PASS: 2156 passed |
| `website` (node tests and pnpm check) | PASS: 17 passed |
| `golden_a` (M3 real media and M4) | PASS: 59 passed |
| `golden_b` (M6 dual-profile acceptance) | PASS: 10 passed |
| `browser` (restore-derived operator workflow) | PASS: 1 passed |

## Gate exception

Record: `R2_V1_RELEASE_SPONSOR_DECISION_2026-09-28.json`.

- **What failed.** All 19 dialect failures are in `tests/integration/r2/host_hardening/test_deployment_backup.py`.
- **Why.** The session's PG16 client shims mounted only `/tmp` into their container, so `pg_dump` could not write under the on-disk `TMPDIR`. The fault is in the test tooling, not the product.
- **Recheck.** With the shims fixed, the file passed 23/23 on disposable PG16 at the same candidate (`v1-release-gates-2026-09-28-run2-migration-recheck.log`).
- **Not rerun.** By the sponsor's instruction, the migration gate and the full run were not rerun.

**E1 upstream compatibility** (`R2_V1_E1_UPSTREAM_REPORT_2026-09-28.json`).

- **Verifier output.** Run at evidence HEAD `138b0c80`, the verifier returns `INCOMPATIBLE`: "migration gate lacks fresh complete PASS evidence". This follows directly from the exception.
- **What passed.** The report's other checks passed: pins, the ordered upstream inventory, the integration proof and the other eleven gate logs. A dry run of the same pipeline in a throwaway clone returned `COMPATIBLE`.
- **Consequence.** The E1 verdict stands at INCOMPATIBLE-by-one-gate, and the sponsor accepts it.

## Run history

The first run, at `abf5ec1d` in `docs/r2/evidence/v1-release-gates-2026-09-28/`, failed three gates. Remotion renders failed while `/tmp` (tmpfs) was near full; the README there gives the details. That run led to two changes:

- `RemotionRenderError` now reports the output of a failed render;
- the gates run with `TMPDIR` on disk.

## Known limits carried into V1

- **Paid routes.** No paid canary has run, so no provider route is qualified yet. The runbook covers how to qualify one.
- **Audio.** All V1 corpus finals are silent, by explicit MUTE decision. Narration needs a qualified TTS route.
- **Gate B enforcement.** Gate B before production is checked by the dossier and the drill, not enforced at runtime (ADR-0092).
- **Operations not proven.** SSE resync is proven for the project event stream only. The failed-provider-regeneration path needs a provider.
- **Copy review.** The sponsor approved the nine new UI strings (zh/en/vi) on 2026-09-28. They keep the gate terms "Final Cut" and "gate API" in English, which follows the sponsor's preference for short, clear English or Vietnamese terms.
- **Reviews.** No independent review covers the V1-07/V1-08 commits; the main agent's review found no correctness defect.
- **Not pushed.** Fork CI has never run.
