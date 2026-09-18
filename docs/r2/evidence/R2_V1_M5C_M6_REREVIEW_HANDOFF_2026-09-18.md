# R2 V1 M5C/M6 Independent Re-review Handoff — 2026-09-18

## Resume identity

- Worktree: `/home/anhtuan/content-production-os/.worktrees/r2-v1-m5c-m6`
- Branch: `integration/r2-v1-m5c-m6`
- Packet HEAD before this handoff: `e0633feedb7886232858e62909e8c28d92c1938b`
- Remediation code commit: `f5c85e3cad1abe297f6e408f66ed7743f9aabf11`
- Status: `READY_FOR_INDEPENDENT_REREVIEW`; **not accepted**.
- M7 remains closed.

## Completed work

The first independent review returned `CHANGES_REQUIRED`. The remediation closes exact report/artifact/sidecar binding, report-scoped waiver coverage, and REVOKE applicability after dependency supersession. The authoritative review history and candidate packet are recorded in:

- `docs/r2/evidence/R2_V1_M5C_M6_AUTHORITY_INDEPENDENT_REVIEW_2026-09-18.md`
- `docs/r2/evidence/R2_V1_M5C_M6_AUTHORITY_REMEDIATION_2026-09-18.json`

Fresh validation on the remediation code commit:

- five new adversarial cases: passed;
- SQLite adaptation suite: `151 passed, 5 skipped, 1 warning`;
- PostgreSQL 18 adaptation suite: `95 passed`;
- full backend suite: `13699 passed, 17 skipped, 102 warnings`;
- Ruff check and format check, basedpyright, import-linter, deptry, test audit, and `git diff --check`: passed.

## Interrupted re-review

The same sole independent reviewer began re-reviewing exact packet HEAD `e0633feedb7886232858e62909e8c28d92c1938b`. It confirmed a clean worktree and provisionally found no blocker in the deterministic sidecar and exact artifact-binding portion. The reviewer then hit its usage limit before checking waiver tuples, REVOKE/current-ADMIT behavior, documents/evidence, full tests, and call sites. There is no final verdict; this partial inspection must not be treated as acceptance.

## Exact resume gate

1. Verify this handoff commit is the clean branch HEAD and that commits `e0633fee` and `f5c85e3c` are ancestors.
2. Run one fresh independent review against the exact handoff HEAD, covering the complete diff from fixed point `cc3f6e` through the current HEAD.
3. Require explicit checks of cross-artifact/cross-recovery binding, report-scoped waiver tuples, resolved sidecar recomputation, REVOKE after dependency supersession, reader in-flight limitation wording, documents/evidence consistency, and test coverage.
4. Only after an explicit `APPROVED` verdict on the exact candidate may the main agent verify citations/results and record acceptance. Otherwise remediate findings and repeat the exact-HEAD review gate.

The temporary PostgreSQL container used during verification was named `r2-v1-remediation-pg18`; confirm it is stopped or remove it before resuming if it still exists.

## Main-agent final review checkpoint

Review target: exact HEAD `0bc4298759427216093ccca3bf2a59373e0d31de`, against fixed point
`cc3f6e769e26b6379c5d8ac3c2dc7b9e6e4538d3`.

Verdict: `CHANGES_REQUIRED` (main-agent review, not independent acceptance).

Blocking finding:

- **P0 — Stored evaluation-report content is not verified against its content-addressed `report_digest`.**
  `AdaptationRepository.get_exact_report` rebuilds a report from mutable database rows, while the authority
  paths only compare the stored `report_digest` field with the requested reference. They recompute the
  resolved sidecar hash but never recompute `compute_profile_evaluation_report_digest(report)`. A corrupted
  report or finding row can therefore retain the old digest while deleting or changing a blocking finding,
  and map approval, waiver issuance, or screenplay admission may consume evidence that is not the exact
  content named by the digest. Add one shared fail-closed report-integrity guard, use it at every authority
  consumption boundary, and add adversarial database-corruption tests for report metadata and findings.

Review verification: the three focused regression tests for cross-artifact waiver rejection,
report-scoped waiver coverage, and REVOKE after map supersession passed (`3 passed, 1 warning`);
`git diff --check` passed and the worktree was clean before this handoff update.

## Report-integrity remediation

The P0 above is remediated by code commit `54acf51948ef0fdc21da7d868778483cebd230ed`.
The shared authority report-binding path now recomputes every resolved report's semantic digest before
map approval, waiver issuance, or screenplay admission can consume it. Two database-corruption tests
proved RED before implementation and GREEN afterward: one mutates report metadata while retaining the
digest; the other deletes finding rows while retaining the digest.

Fresh gates on the remediation:

- authority suites: `61 passed, 1 skipped`;
- affected SQLite M5C/M6 suite: `258 passed, 5 skipped, 1 warning`;
- affected PostgreSQL 18 suite: `263 passed`;
- full backend: `13701 passed, 17 skipped, 102 warnings`;
- Ruff check/format, basedpyright, import-linter, deptry, test audit, and diff check: pass.

Status returns to `READY_FOR_INDEPENDENT_REREVIEW`; this remediation is not accepted until one independent
reviewer issues an explicit verdict on the exact evidence commit containing this section.

## Final independent verdict

An independent read-only reviewer reviewed exact candidate HEAD
`aaa4eb7eeabbab81650dcbe1fde02ef02103067d` against fixed point
`cc3f6e769e26b6379c5d8ac3c2dc7b9e6e4538d3` and returned `APPROVED` with no blocking
findings. The reviewer independently ran a focused eight-test corruption, binding, waiver, revocation, and
reader set: `8 passed, 1 warning`; `git diff --check` passed and the reviewed worktree was clean.

M5C/M6 authority remediation is accepted at that exact reviewed candidate. The commit recording this verdict
is administrative evidence only. The next session may begin M7 from this accepted lineage; it must still run
M7's own research/design/implementation gates and does not inherit production or publication authority.
