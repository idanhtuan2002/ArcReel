# R2 V1 H6/H7 final independent review — 2026-09-27

Reviewer: a separate agent with its own context, read-only. Reviewed HEAD:
`d382f5fe`. The tree was clean at the start and at the end.

**Verdict: CHANGES_REQUIRED.**

- **H6:** acceptable pending only the Golden A/B restored-target run
  (V1-05/E2).
- **H7:** blocked by F1.

## Status of the re-review findings

| Finding | Status |
|---|---|
| N1 | Fixed. The differential grid found 0 regressions against `1f287029` and `8fdcfa13`. |
| N2 | Fixed for queue and resume paths; the non-task gap is F3. |
| Minor 1 | Fixed. Left: `vidu_shared` `resp.text[:200]`, and an unterminated quoted value is not masked. |
| Minor 2 | Partially fixed; the rest is accepted by the runbook. Per-target verdict gap: F5. |
| Minors 3, 4, 8 | Fixed |
| Minor 5 | Fixed; regression F6 |
| Minor 6 | Partially fixed: F4 |
| Minor 7 | Bounded, but 1 MB of BEGIN headers with an END marker takes 8 s |
| Minor 9 | Accepted |

## New findings

**Important**

- **F1.** Redaction is quadratic on whitespace runs. The quoted patterns
  place two `\s*` either side of an optional quote after any identifier;
  the cookie and auth line patterns use `^\s*` across newlines. Measured:
  - `"word"` + 20k spaces: 4.8 s;
  - 20k newlines: 18.7 s;
  - 10k CRLF: 11.7 s.

  These are reachable from every log line and from full provider error
  bodies.

**Minor**

- **F2.** Contextvar edges: IDs bound in a child task, IDs under 6
  characters, and plain substring replacement.
- **F3.** Non-task paths (endpoint trial runs) never bind job IDs, so poll
  URLs log the raw ID.
- **F4.** `base_url` stripping: no `g` flag; `[^/@]*` crosses whitespace and
  rewrites prose; `system_setting` `anthropic_base_url` is not stripped.
- **F5.** A single `verdict.json` is overwritten by a later verify; the
  attestation does not cross-check the verdict or evidence files.
- **F6.** Rebuilding the query mangles `options=-c%20…` and `+` in values.
- **F7.** CLI `DeploymentBackupError` detail is not redacted.
- **F8.** `ARCREEL_TELEMETRY_HMAC_KEY` is undocumented; job references
  rotate on restart.

## Remaining blockers

- F1.
- Golden A/B on a restored target.
- Full affected gates on the exact candidate HEAD.

## Reviewer verification

- 73 tests passed on disposable PostgreSQL 18 plus the logging and chain
  tests.
- 1426 targeted unit tests passed.
- Static checks clean.
