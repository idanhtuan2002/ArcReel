# R2 V1 H6/H7 third confirmation review — 2026-09-27

Reviewer: a separate agent with its own context, read-only. Reviewed HEAD:
`a0fe0291` (commits `c9776606`, `c26c0fb5`). The tree was clean at the
start and at the end.

**Verdict: CHANGES_REQUIRED (narrow).**

- **H6 fence (`c9776606`): approved.** H6 is acceptable pending only
  Golden A/B and the full gates.
- **H7 redaction (`c26c0fb5`): blocked by R1.**

## Fence probes (PostgreSQL 18.6, 78 runs, pre- and post-dump)

- **Detected:** INSERT, UPDATE and DELETE; COPY; TRUNCATE; column
  add/drop/rename and type or default changes; rename, create and drop of
  tables; CREATE INDEX and CREATE VIEW; `nextval`/`setval`; inserts into
  another schema; a transaction still open at the after snapshot.
- **No false positive:** ANALYZE, VACUUM, CHECKPOINT, and real autovacuum
  plus autoanalyze during an 8 s capture (4/4 runs). The old database
  counter would have moved by 176 in that run.
- **Missed, catalog-only (M1):** large objects; DDL or TRUNCATE in a
  non-current schema; CHECK constraints; non-rewriting type widening;
  functions; comments.
- **Flush race:** 450 write-then-exit iterations, 0 violations.

## Findings

- **R1 (Important).** `_INLINE_VALUE_RE` stops at the first `}`, `]` or
  `)`, so the rest of an unquoted credential leaks: 450 grid cases, e.g.
  `password=abc)def`.
- **R2 (Minor).** The numeric exemption also applies to quoted values and to
  generic `*_token` keys, e.g. `"github_token": "84736251"`.
- **M1 (Minor).** The runbook should state that the relation fingerprint
  covers only `current_schema()`.
- **M2 (Minor).** New required fence fields were added without a manifest
  `schema_version` bump; older sets fail with a raw `ValidationError`.
- **M3 (Minor).** A non-UTF-8 verdict raises `UnicodeDecodeError` in
  `attest`; it fails closed.
- **Pre-existing.** camelCase `secretKey` is not masked.

## Redaction differential (6552 cases per function)

| Version | Leaks |
|---|---|
| `8a8ea340` | 1358 |
| `901b20a0` | 98 |
| `a0fe0291` | 1016 |

Timing is linear everywhere (fuzz peak: 13 ms at 20k).

## Reviewer verification

- 21 H6 tests passed on PostgreSQL 18.
- 84 redaction tests passed.
- Static checks clean.
