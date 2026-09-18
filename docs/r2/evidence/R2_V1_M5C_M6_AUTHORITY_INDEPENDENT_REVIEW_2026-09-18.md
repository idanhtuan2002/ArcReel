# R2 V1 M5C/M6 Authority Remediation — Independent Review

## Round 1 verdict: CHANGES_REQUIRED

- Reviewed exact HEAD: `dffa78c7c7688e2196886eafe9179c718068bb0d`
- Fixed point: `cc3f6e769e26b6379c5d8ac3c2dc7b9e6e4538d3`
- Worktree at review: clean
- Review mode: one independent read-only reviewer; no nested or parallel agents
- License: excluded by sponsor decision

### Blocking spec findings

1. `P0` — Reports carried content hashes but no enforced exact-artifact identity.
   Two screenplay identities with identical bytes could reuse one report to issue a
   waiver for the other; blocking findings were also collapsed to bare finding IDs,
   allowing one report's waiver to cover another report's same-named finding.
2. `P0` — Map approval compared self-declared report sidecar refs but did not bind
   the report to the exact map hash, resolve the sidecar, or recompute its semantic
   digest.
3. `P1` — `REVOKE` reran the positive admission dependency checks, so superseding
   the historical map approval could make an existing admission impossible to
   revoke.
4. `P1` — The remediation evidence overstated closure while those defects remained.

### Non-blocking observations

- `P2` — The approved screenplay reader proves current authority at read time; it
  does not fence or cancel already-started downstream work after releasing the
  transaction lock. The contract needed to state that boundary explicitly.
- `P3` — Effective-selection transition logic remains duplicated between the pure
  fold and repository projection. This is a maintainability smell, not an observed
  correctness failure in this packet.

### Reviewer validation and limits

- Fresh targeted tests at reviewed HEAD: `60 passed, 1 skipped`.
- Targeted Ruff and `git diff --check`: PASS.
- The Codebase Memory project pointed at a different main-worktree HEAD and reported
  missing freshness for the changed paths. Material conclusions therefore came from
  direct source and diff inspection.
- Historical full-suite results were inspected but not treated as reviewer-owned
  acceptance evidence.

## Remediation checkpoint

Commit `f5c85e3cad1abe297f6e408f66ed7743f9aabf11` addresses the blocking findings:

- deterministic exact-artifact sidecar identity plus sidecar resolution and semantic
  hash recomputation;
- report-scoped waiver coverage keyed by report digest, finding ID and rule version;
- a REVOKE path bound to the current effective ADMIT's immutable context without
  requiring historical dependencies to remain current;
- five adversarial cases covering same-bytes cross-artifact reuse, wrong map artifact
  hash, tampered resolved sidecar, same-named cross-report findings, and revocation
  after map supersession;
- ADR/design/plan clarification of the read-time versus in-flight boundary.

This checkpoint is `READY_FOR_INDEPENDENT_REREVIEW`, not accepted. A fresh reviewer
verdict must bind the exact evidence commit containing this record and the updated
machine-readable evidence.

## Final re-review

- Reviewed HEAD: `aaa4eb7eeabbab81650dcbe1fde02ef02103067d`
- Fixed point: `cc3f6e769e26b6379c5d8ac3c2dc7b9e6e4538d3`
- Mode: independent, read-only, exact Git/source review because graph freshness was missing for the worktree
- Fresh targeted verification: `8 passed, 1 warning`
- `git diff --check`: pass
- Verdict: **APPROVED**
- Blocking findings: none

The reviewer confirmed the shared semantic report-digest guard at all three authority consumption boundaries,
exact artifact/sidecar binding, report-scoped waiver tuples, REVOKE behavior after dependency supersession,
read-time reader authority, adversarial metadata/finding-row corruption coverage, and evidence consistency.
