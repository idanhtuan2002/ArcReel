# M8-C Target Consumer Authority Resolver Plan

**Status:** implementation verified on the affected selection; independent exact-HEAD review and overall M8-C acceptance remain open. ADR-0102 remains proposed.

**Goal:** Let an internal consumer that starts with only `(user_id, project_name, target_type, target_id)` resolve one current approved Take target without acquiring any target lock before its full upstream admission lock.

**Source basis:** ADR-0102's admission → Scene → Shot order; the M8-C binding-authority spec's untrusted-admission-hint rule; `TransactionBoundApprovedScreenplayReader` in `r2/adaptation/screenplay_reader.py`; `ProductionTargetRepository.get_current_verified` in `lib/db/repositories/production_target.py`. The root graph generation `2026-09-27T03:07:32Z` excludes `.worktrees`; structural conclusions for these new files were checked against exact worktree source. This packet makes no binding CAS or production activation decision.

## Interface and transaction

- Add a repository `peek_current_admission_hint` that performs one scoped, unlocked head→version query and returns an immutable copy of `(TargetVersionRef, AdmittedScreenplayRef)`. The values are untrusted. Missing head returns `None`; a committed genesis, missing version or malformed hint raises `ProductionTargetIntegrityError`. No `FOR UPDATE` appears in this method.
- Add a transaction-bound internal resolver over a caller-supplied `AsyncSession`. It first obtains that hint; then uses `TransactionBoundApprovedScreenplayReader(AdaptationRepository(session), expected_admission=hint.admitted_screenplay_ref)` to lock/fold/verify the current full admission, including profile; then calls `get_current_verified(..., expected_admission=hint.admitted_screenplay_ref)` on the same session. It compares the locked target's exact ref and full admission with the primitive hint. A changed or missing target fails closed. The resolver neither opens a second session nor commits.
- A Shot local read retains the existing untrusted Scene-dependency hint and Scene-before-Shot lock order. The resolver returns `VerifiedTargetVersion` only after both the admission and target checks. Its API must not expose the first hint as authority.
- A direct known-admission writer continues to use the registration service's own admission lock and target reads; the new resolver is for consumers whose only entry identity is a target key.

## RED → GREEN verification

1. Write focused integration tests for Scene and Shot resolution from a persisted admission/Take registration. Assert the expected target and full profile; wrong user/project and unknown target return no authority. Confirm a forged profile or stale admission raises rather than returning a target.
2. Instrument the repository and admission reader to assert the first target lookup is unlocked and that admission verification completes before any Scene/Shot `FOR UPDATE`. Force a changed exact target ref after the hint but before the locked re-read; expect `ProductionTargetIntegrityError` even when the replacement row and digest are internally coherent. Include an ORM identity refresh case using primitive snapshots.
3. On disposable PostgreSQL 16, force an admission-changing writer between hint and admission lock and verify the resolver rejects the stale hint. Force a target-head advance after admission lock waits, then verify the hint comparison rejects the changed head. Capture backend PIDs or use test-owned barriers to prove the order; no lock may span an external call.
4. Run the affected admission/target/resolver selection on SQLite and PostgreSQL, changed-file Ruff, full basedpyright, lint-imports, deptry and test audit. Record the exact code HEAD, skip/coverage limits and independent exact-diff review. A repository-wide backend gate is already red in unrelated domains and remains a separate release gate.

## Boundary after this packet

The binding authority may use this resolver before binding-head locks. Binding create/update, version-envelope vectors, snapshot reads, asset-custody proof, pair decisions and spatial promotion require their own design and test packet. A successful resolver test does not establish binding or M8-C acceptance.

## Execution checkpoint — 2026-10-05

The new repository method performs one unlocked scoped outer join for the untrusted admission/ref hint. `TransactionBoundTargetAuthorityResolver` validates the full stored admission using the same session, then calls the locked current target read and compares the exact primitive hint. The test first failed on the missing resolver module. The final affected selection returned **70 passed, 9 PostgreSQL-only skipped** on SQLite and **79 passed** on disposable PostgreSQL 16 (`-n 4 --dist loadfile`). PostgreSQL cases force a same-admission target-head advance and an admission revocation after the hint, and record SQL to show an unlocked hint query followed by admission, Scene and Shot `FOR UPDATE` in that order. Corrupt profile hints and committed genesis heads fail closed. Ruff check `.`, changed-file formatting, basedpyright (**0 errors, 0 warnings**), lint-imports (**22 kept**), deptry, test audit (**0 violations**) and diff check passed. The repository-wide backend gate remains red from the preceding checkpoint. Do not mark this resolver or binding authority accepted before exact-HEAD review.
