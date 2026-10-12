# M8-C checkpointed grant reader at internal service seams

Status: bounded service integration evidence from `eff8943a`; no production composition or activation.

## Source inventory

- `SpatialReviewSessionService` accepts a `CurrentShowrunnerGrantReader` in its constructor. `create`, `fetch_frame` and `acknowledge_frame` call `require_current_locked` inside their write/read transaction before returning a session, PNG/delivery or acknowledgment (`server/services/spatial_review_session.py:51-160`).
- `SpatialPairDecisionServiceV2` accepts the same reader. It checks the current grant after locking the pair and frame sources, including on its existing-command replay path; replay additionally checks the historical ISSUE (`server/services/spatial_pair_decision_v2.py:41-193`).
- `CurrentApprovedSpatialPairReaderV2` accepts the same reader and checks both current and historical ISSUE before returning an approval (`server/services/spatial_pair_current_v2.py:28-138`).
- `CheckpointedShowrunnerGrantReader` is a subtype of that constructor type. Its current check compares the transaction-locked local head with a freshly loaded signed checkpoint. The inherited historical check calls `self.require_current_locked`, so it also dispatches to the checkpointed override (`server/services/governance_grants.py:238-350`).

The root codebase-memory generation is `2026-09-27T03:07:32Z`, predating these worktree files. `check_index_coverage` reports missing freshness for all four service files. This inventory comes from exact worktree source reads and is bounded to these internal service classes; it does not claim that every future route or caller is covered.

## Executed service gate

The existing full integration fixture constructs real current target, binding, two frame receipts, review session, signed grant, consumed review and V2 approval. A new block injects a checkpointed reader with the same local ISSUE key and an authentic checkpoint signed by the test key but containing no matching scope. It then asserts denial for review creation, PNG fetch, acknowledgment, current V2 approval read and V2 command replay. Counts of session, delivery, acknowledgment and decision rows remain unchanged. This exercises constructor injection without changing service production wiring.

After the test change, the focused selection returned **1 passed, 1 PostgreSQL-only skipped** on SQLite and **2 passed** on disposable PostgreSQL 16 for the pair-first and writer-first variants. The PostgreSQL container was stopped and removed. Ruff check passed; Ruff format initially requested formatting, which was applied. Targeted basedpyright returned **0 errors, 0 warnings**; test audit returned **0 violations**. Recheck Ruff format and diff before committing.

## Remaining activation sequence

1. Establish an operator-approved, independently retained manifest binding deployment identity, image digest, verifier registry digest and checkpoint high-water. Define exact archive, publication, rollback and key-rotation procedures before the application trusts it.
2. Add an explicitly activated composition path that loads only those pinned inputs. Keep a separate offline migration phase. During app startup, verify schema read-only, run the full fenced scanner, then permit readiness and workers. A restored older DB must fail before `init_db` can stamp/upgrade or any worker starts.
3. Construct exactly one checkpointed reader from the approved manifest and `GovernanceCheckpointFile` in the activated composition root. Inject it into all three internal services, and forbid a local-only reader in that mode. Keep their grant-head lock and fresh checkpoint read in each transaction.
4. Exercise actual lifespan on a restored pre-REVOKE database with a newer external checkpoint; assert no route/worker readiness. Exercise valid current and revoked states, manifest mismatch, unavailable mount, image/schema mismatch and forced importer/reader ordering.
5. Reinspect every route/caller added at activation, run the affected backend gate, and obtain independent exact-HEAD review. Only a separately authorized release may enable public APPROVE/READY or production recovery.

This plan makes no selection of the operator archive medium or production key material.
