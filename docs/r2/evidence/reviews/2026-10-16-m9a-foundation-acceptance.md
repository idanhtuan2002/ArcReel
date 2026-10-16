# M9-A acceptance review

**Verdict: `PASS_M9_A_FOUNDATION`**

- Candidate: `912abc3bedf5cf2f5965284919f11acc3a3c7593`
- P0 base: `39b9c5dab5d0fd56cf52bf65e95355437cb1023b`
- Tested implementation head: `fd9543de6053c5b21a17605c5ea13b967a6ff638`
- Initial and final checkout status: clean
- Final HEAD remained the authorized candidate.
- No files were edited, staged, or committed.

## Confirmed defects

- **Critical:** none.
- **Important:** none.

## Verified sound

- Publication derives owner, project, and actor from authenticated host composition and rejects caller scope substitution before custody or writes: `server/routers/opportunity.py:31-88`, `server/services/opportunity.py:41-57`, `r2/opportunity/profiles.py:122-154`.
- Custody is fail closed and durable: command/subject/policy bound leases, exact retained signed ISSUE proof, grant-validity window, no renewal after expiry, and current-grant checks for new leases: `server/services/m9_custodian.py:51-208`.
- Replay and mutation are correctly ordered. Receipt preflight occurs before reauthorization, the command guard and receipt reread occur inside the mutation transaction, and profile/head/event/receipt writes share that transaction: `r2/opportunity/profiles.py:131-236`, `lib/db/repositories/opportunity.py:127-252`.
- Cross-project command UUID reuse returns only `M9_COMMAND_REPLAY_CONFLICT`; stored receipt/profile digests and scope are reconstructed and verified before reads are returned: `lib/db/repositories/opportunity.py:58-166`, `r2/opportunity/profiles.py:238-282`.
- PostgreSQL concurrency evidence covers equal/divergent command races, advisory-lock collisions, concurrent genesis, head waiters, and both policy-head interleavings: `tests/integration/r2/opportunity/test_profile_concurrency.py:23-228`.
- The project policy read takes the required `adaptation_heads` table lock before resolving effective admissions, preserving policy identity across admission races: `server/services/opportunity.py:20-38`.
- The migration is a single linear successor and its disposable-PostgreSQL test exercises downgrade/upgrade twice, exact five-table isolation, primary keys, receipt/lease uniqueness, parent checks, and owner FKs: `tests/integration/lib/db/migrations/test_alembic_m9_foundation.py:26-83`.
- HTTP tests cover interactive-only publication, API-key read access, migration refusal, scope injection, stable stop codes, and byte-equal replay: `tests/unit/server/routers/test_opportunity_router.py:55-193`.
- Sponsor and scheduler amendments are immutable Git-bound inputs. The foundation verifier restricts the exception to unchanged native runtime and migration bytes and emits exactly nine `DEFERRED_RUNTIME` entries with `donor_runtime_executed=false`, `runtime_parity_claimed=false`, and no runtime ports: `scripts/r2/verify_m9_scope.py:125-186`, `scripts/r2/verify_m9_parity.py:23-70`.
- Evidence verification recomputes immutable bindings, parses command results and JUnit, derives owned tests from source, validates fault/graph proofs, and rejects relabeled or broadened foundation evidence: `scripts/r2/verify_m9_evidence.py:58-504` and its mutation tests.

## Evidence validation

Fresh read-only checks performed during this review:

- All 46 referenced retained artifacts exist and match their declared SHA-256 hashes.
- JUnit parsing found:
  - required affected gate: 802 cases, zero skips/failures/errors;
  - migration gate: two cases, zero skips/failures/errors;
  - PostgreSQL compatibility: 1,582 cases, 23 skips, zero failures/errors, matching the recorded 1,559 passes.
- The historical SQLite result is bound to `0e6842efc1c4d8507c8749bc3afe1bc1dc7d2bde`: 17,297 passed and 187 skipped.
- The delta from that SHA to the tested implementation contains exactly the declared five scheduler amendment/test/verifier paths. The interrupted target-head SQLite run has exit 2 and explicitly sets `fresh_full_sqlite_pass_claimed=false`; I did not count its incomplete JUnit rows as passes.
- Retained `auto-strict-verifier.log` records `M9_A_CANDIDATE_EVIDENCE_OK`.
- I did not rerun the recorded test suites. A fresh module-form strict-verifier probe reached the expected fail-closed prerequisite check but could not pass without current disposable-target and grant inputs. No fresh verifier or database-execution pass is claimed.

## Graph and source coverage

Tier-2 graph verification used project `r2-m9a`, generation `2026-10-16T05:59:52Z`, fast/best-effort. Both call directions were checked for the publication service, custody adapter, and host composition. Class-level absence of callees was not treated as evidence.

Coverage checking found no recorded issue for core models, contracts, repository, service, router, migration, and unit-test paths. Documentation, scripts, and integration tests were excluded by index policy; material files in those groups were read directly. `server/services/opportunity.py` had changed metadata and was also read directly. The graph signal remains best effort and is not an exhaustive completeness proof.

## Minor notes and limits

- The candidate evidence correctly remains `M9_A_CANDIDATE` with independent review `PENDING`; this report supplies the author-independent judgment but does not mutate that artifact.
- Current donor bare caches were not available for a fresh donor-blob rehash. Donor pins are supported by the Git-bound baseline and retained successful scope verification; no donor runtime or parity claim is accepted.
- Human-declared profile metadata was reviewed as contract data. Physical corpus contents and calibration quality were outside this foundation acceptance.

## Declined to judge

- Production readiness or deployment acceptance.
- M9-B through M9-F authorization or release.
- Donor runtime parity.
- Provider/network behavior.
- License matters.
- Physical corpus or calibration validity.
- A fresh full-suite pass or live database/grant ceremony.

This pass accepts only the amended M9-A foundation contract and its retained evidence. It grants no production or later-packet authority.
