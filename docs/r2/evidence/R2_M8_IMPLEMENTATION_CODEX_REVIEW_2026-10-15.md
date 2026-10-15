# M8 implementation acceptance review (Codex, 2026-10-15)

**Candidate:** `2bba4e3bcf39ea45f6dd25988b854b28080c51b0` on `impl/r2-m8f-utility`. **Verdict:** `M8_IMPLEMENTATION_ACCEPTED`.

**Reviewer:** Codex, run as a separate agent, read-only. The reported model is "GPT-5". `gpt-5.6-sol` was
requested, but the runtime did not confirm it.

## Findings

- **Critical:** none.
- **High:** none.
- **Previous High 1, the Canvas check/append race.** Accepted as a documented residual (ADR-0107):
  - The append route checks the full client lineage against a current server resolution before it
    writes.
  - A concurrent change leaves only a lineage that was valid at check time and still declares its
    profile.
  - Canvas cannot be promoted.
  - Learning ingest requires the current server lineage, and its cohorts are keyed on profile and
    version.
  - No evidence crosses an undeclared profile or cohort boundary (spec §13 `M8_PROFILE_COHORT_LEAK`),
    so the §12 zero-leakage exit is not blocked.
- **Previous High 2, reviewer A not blind.** Fixed:
  - ADR-0108 amendment 1 and the protocol v3 roster are in place.
  - The packet discloses neither the calibration items nor the expected verdicts.
  - Both independent verdict sets are sealed; both reviewers failed F3 and S2; they do not disagree.
- **Medium, non-blocking:**
  - (1) The determinism verifier builds run 1's comparison from run 2's keys, so it misses a field
    omitted only from run 2. The sealed v3 results are unaffected; a full independent comparison
    found no difference.
  - (2) Protocol v3's pilot rationale still says "one reviewer".
  - (3) In the draft dossier, the pytest entries carried the protocol-verifier command. This was
    corrected when the dossier was sealed.

## Verified by the reviewer

- **State.** HEAD and a clean tree; `git diff --check b81d7aa0..HEAD`.
- **Order and hashes.** Protocol, then results, then reviews; the dossier's SHA-256 values match.
- **Verifiers.** `verify_m8_evaluation_protocol --results` and `verify_m8f_determinism` both pass on the
  sealed v3 results. An independent full stable-view comparison found no differences.
- **Review integrity.** The raw review outputs match the record. The packet has no disclosure.
- **Media.** The projection digests match the results.

## Not verified by the reviewer

- **Tests and gates.** The sandbox was read-only, so it ran no pytest and did not rerun the
  historical static gates, the PostgreSQL suite, the render suite, donor parity, the provider canary
  or the full suite.
- **Reviewer runs.** Reviewer process isolation and model identities cannot be fully reconstructed
  from git.
- **Graph coverage.** The codebase-memory graph calls were refused by the approval policy.
