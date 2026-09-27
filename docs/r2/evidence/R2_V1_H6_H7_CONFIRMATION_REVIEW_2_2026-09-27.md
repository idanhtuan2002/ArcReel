# R2 V1 H6/H7 second confirmation review — 2026-09-27

Reviewer: a separate agent with its own context, read-only. Reviewed HEAD:
`901b20a0` (fix commit `7f145dd3`). The tree was clean at the start and at
the end.

**Verdict: APPROVED_WITH_FOLLOWUPS.** H6/H7 remain acceptable pending only
two steps:

- the Golden A/B restored-target run;
- the full affected gates.

None of the findings leaks a credential that the previously accepted bar
protected.

## N1–N7

| # | Status |
|---|---|
| N1 | Partial. `Authorization:\r\nX`, `Authorization:\n X` and `cookie:\n sid=X` are still unmasked: the line patterns mask the empty header value first. |
| N2 | Fixed |
| N3 | Fixed. Trade-off: a raw `?`/`#` inside a password is neither stripped nor flagged; the runbook documents this. |
| N4 | Fixed |
| N5 | Fixed |
| N6 | Fixed on the integrity paths. `attest` still parses the verdict unwrapped (fails closed; the CLI exits 2). |
| N7 | Fixed |

## New findings

- **Important (non-blocking): over-masking.** The optional quote after the
  inline key masks JSON token counts. For example, `"prompt_tokens":128`
  becomes `••••`. The inline value also swallows closing `}}`. This hits
  every log line.
- **Minor.** An unterminated quoted credential masks the rest of the text,
  including later lines.
- **Minor.** Shapes masked in no version: backslash-newline in a quoted
  value, YAML block scalars, `--password X`, XML tags, `=>`.
- **Minor.** Next-line over-masking is back to the `d382f5fe` behaviour.

## Reviewer verification

- Timing: 64 shapes at 20k and 200k characters, plus a 300-case fuzz, all
  linear. Slowest: 157 ms at 200k.
- Masking differential: 99,920 cases; only 6 regressed (the header/cookie
  next-line shapes).
- 108 redaction tests passed.
- 6831 unit tests passed.
- 65 passed on PostgreSQL 18.
- Static checks and `audit_tests` clean.
