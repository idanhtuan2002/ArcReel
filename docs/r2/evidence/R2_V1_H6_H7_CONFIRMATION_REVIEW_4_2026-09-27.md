# R2 V1 H6/H7 fourth confirmation review — 2026-09-27

Reviewer: a separate agent with its own context, read-only. Reviewed HEAD:
`ea16418b` (commit `7eadb05f`). The tree was clean at the start and at the
end.

**Verdict: CHANGES_REQUIRED (narrow, H7 only).**

- **H6:** acceptable pending only Golden A/B and the full gates. M2/M3 are
  closed; the CLI end-to-end run reached VERIFIED with real ffprobe.
- **H7:** blocked by N1.

## Status

| ID | Status |
|---|---|
| R1 | Fixed for inner and trailing brackets; regressed for a leading bracket (N1) |
| R2 | Fixed |
| M1 | Fixed |
| M2 | Fixed |
| M3 | Fixed |
| secretKey | Fixed on the text path only (N2) |

## Findings

- **N1 (Important).** `_INLINE_VALUE_RE` requires a non-bracket first
  character, so an unquoted credential starting with `)`, `}` or `]` is
  emitted in full. Examples: `password=)Zq9X…`, `Foo(password=}…)`. In
  the grid this is 832 regressions against `901b20a0`; in the random fuzz,
  about 3.4% of symbol passwords.
- **N2 (pre-existing).** The structured-key paths
  (`sanitize_diagnostic_payload`, `format_kwargs_for_log`) and text
  `"secret_key": "v"` / `aws_secret_key: v` do not mask
  `secretKey`/`secret_key`.
- **N3 (Minor).** `read_state` raises raw `UnicodeDecodeError` or
  `JSONDecodeError` for a corrupt `state.json`.

## Differential grid (4896 cases per function)

| Version | Leaks |
|---|---|
| `901b20a0` | 153 |
| `a0fe0291` | 1297 |
| `ea16418b` | 424 |

Timing is linear (worst: 92 ms at 200k). Over-masking is much lower than at
`901b20a0`.

## Reviewer verification

- 22 passed on PostgreSQL 18.
- 91 redaction and chain tests passed.
- 6 CLI tests passed.
- Static checks clean.
