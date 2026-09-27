# R2 V1 H6/H7 independent re-review — 2026-09-27

Reviewer: a separate agent with its own context, read-only. Reviewed HEAD:
`8fdcfa13`. The tree was clean at the start and at the end.

**Verdict: CHANGES_REQUIRED.** There are 0 critical, 2 important and 9 minor
findings.

## Previous findings

| ID | Status |
|---|---|
| I1 | Fixed |
| I2 | Fixed; `?password=` query form left |
| I3 | Timing fixed, with regression N1. PEM path quadratic (pre-existing). |
| I4 | Largely fixed; gaps below |
| I5 | Partially fixed (N2) |
| I6 | Fixed |
| M1 | Fixed |
| M2 | Fixed; unsalted digest is brute-forceable |
| M3 | Fixed; `base_url` userinfo and runbook wording left |
| M4 | Fixed |
| M5 | Accepted |
| M6 | Fixed / accepted |

## New findings

**Important**

- **N1.** The redaction lookbehind `(?<![A-Za-z0-9_-])` stops masking keys
  preceded by `-`/`_` or with a digit-leading segment. Examples:
  `--password=`, `_token=`, `self._api_key=`, `{"_secret": …}`,
  `2fa_token=`. Confirmed by comparison with `1f287029`.
- **N2.** Raw provider job IDs still reach logs through exception text in
  worker `logger.exception`, poll-retry messages carrying URL paths, and the
  declarative request log of poll URLs. The job-ID log canary claim holds
  only for the synthetic path.

**Minor**

1. Truncation before redaction leaks partial secrets:
   `generation_queue` `error_message[:200]`, `retry`, poll warnings.
2. Attestation checks self-consistency only. A forged verdict or duplicate
   and unknown products are accepted, a hand-set `VERIFIED` state is
   accepted, and there is no target binding.
3. Verify gaps: a current record without a `file`, and a project without
   `project.json` skips `versions.json`.
4. A connect failure leaves the set in `PREPARING`; the CLI raises a raw
   traceback.
5. A `?password=` query parameter stays on argv.
6. `base_url` userinfo credentials are not sanitized.
7. PEM redaction is quadratic on many unterminated BEGIN headers.
8. Declarative prompt keys (`input`/`caption`/`description`) are not
   summarized.
9. The test reset hook lives in a production module.

## Reviewer verification

- 13 passed on disposable PostgreSQL 18.
- 1736 targeted tests passed.
- Alembic on PostgreSQL: upgrade, downgrade ×2 and upgrade OK.
- Static checks clean.

Not run: the full suite, Golden/E2 and real provider backends.
