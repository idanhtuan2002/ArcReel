# R2 V1 H6/H7 confirmation review — 2026-09-27

Reviewer: a separate agent with its own context, read-only. Reviewed HEAD:
`8a8ea340`. The tree was clean at the start and at the end.

**Verdict: APPROVED_WITH_FOLLOWUPS.** H6/H7 are acceptable pending only two
steps:

- the Golden A/B restored-target run (V1-05/E2);
- the full affected gates on the exact candidate HEAD.

## F1–F8

- **F1: fixed.** The sweep covered 75 shapes × 2 functions at 20k/200k
  characters, plus a fuzz. Growth was linear; the slowest case took 850 ms
  at 200k.
- **F3–F8: fixed.**
- **F2: accepted.**

## Follow-ups (none is a blocker)

- **N1 (important).** Separators bounded by the F1 fix unmask 9 credential
  shapes. Examples: a long blank separator, a value on the next line (YAML),
  `Authorization:` header continuation, and a raw newline inside a quoted
  value. A linear fix exists: possessive `\s*+` separators.
- **N2.** The CLI help still says `verdict.json`.
- **N3.** Userinfo stripping does not end the authority at `?`/`#`; a raw
  `@` in a password is left, but flagged as residue.
- **N4.** Re-attesting a VERIFIED set is not crash-atomic.
- **N5.** The attested-target guard compares IDs case-sensitively.
- **N6.** Tampered-to-invalid JSON raises pydantic `ValidationError`
  rather than `BackupIntegrityError`; either way it fails closed.
- **N7.** The handoff's "< 30 ms at 20k" claim does not hold for URL-dense
  input (86 ms at 20k; `httpx.URL` parsing); timing is still linear.

## Reviewer verification

- 220 passed on PostgreSQL 18.
- 99 redaction-helper tests passed.
- 7639 unit tests passed.
- Static checks clean.

Not run: the full suite, Golden A/B, the full affected gates.
