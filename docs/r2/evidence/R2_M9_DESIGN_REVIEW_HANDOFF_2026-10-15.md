# M9 design review handoff (2026-10-15, written before the weekly quota ran out)

## Exact state

- **Branch:** `design/r2-m9-v2-revalidation` in worktree `.worktrees/r2-v2-main`. The base is `23cf146a`
  (M8 implementation accepted, on `impl/r2-m8f-utility`). The sponsor said not to merge M8 yet.
- **Candidate under review:** `4fa2b8e825db606a38ac40eef22a1dbe3c51834a`. The tree was clean at handoff.
- **Review contract:** `docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE_CONTRACT_2026-09-15.json`,
  sha256 `d18b6fb107852cdea8c1d9e486b1e05544ae2564cbc9c0f90b6bb0137a5101b3`, rubric `R2_M9_DESIGN_REVIEW_V1`.
- **Reviewers:** two fresh blind model agents, by sponsor decision on 2026-10-15. The contract allows it:
  it requires reviewers independent of the author and of each other, blind until both are sealed.
  - Reviewer A is a new Claude agent.
  - Reviewer B is a new Codex agent.

## Commits on this branch

| Commit | Content |
|---|---|
| `42e46520` | The M9 design set copied byte for byte from `design/r2-m5b-narrative-context`, plus `docs/research/2026-10-15-r2-m9-prerequisite-path.md`. |
| `a6aaa004` | V2 revalidation: the Factual Authority gate moved to the M9-D release; exact M6 profile ids; the seed lineage resolved on the server. |
| `4f861486` | Fixes for review pass 1, reviewer A (8 blocking findings): umbrella and stop-code sync, digest domains, the acquire command key, the invalidation guard and bridge intents in the lock rank, the host custodian over ADR-0103 grants, retention enforcement, ADR-0109 (seed lineage v3), Task P0 (combined base). |
| `4fa2b8e8` | Fixes for review pass 2, reviewer A (7 blocking findings): interactive principal as actor, `InvalidationSubject` with its custodian port, per-ref M8 evidence entries, the seed revision frozen in a `BridgeIntent` at prepare, guard coverage plus fixpoint propagation, invalidation through validity projections, system command contracts, M9-A's five-table migration. |

## Reviews in flight at handoff (pass 3, same candidate `4fa2b8e8`)

- **Reviewer A** (fresh Claude). It writes its JSON to `/home/anhtuan/content-production-os/.worktrees/m9-design-review-pass3-A.json`.
- **Reviewer B** (fresh Codex). Its output is in the session task transcript
  `/tmp/claude-1000/-home-anhtuan-content-production-os/b7710041-3e77-4f64-89af-b7fb94195e34/tasks/aabec26d261a9181b.output`.
  That file is a JSONL transcript; the final assistant message holds the JSON. If it is lost, rerun reviewer B
  with the same prompt shape against `4fa2b8e8`.

## How to resume

1. **Collect both pass-3 outputs.** If either is FAIL, fix every blocking finding in one revision, sweep
   the candidate artifacts for cross-file contradictions, commit a new candidate, and rerun two fresh
   reviewers on it.
2. **When both PASS on the same HEAD:**
   - write the two sealed reviews to `docs/r2/evidence/reviews/m9/`, following
     `docs/r2/evidence/schemas/R2_M9_DESIGN_REVIEW.schema.json`;
   - write `docs/r2/evidence/R2_M9_DESIGN_ACCEPTANCE.json`;
   - run `uv run python scripts/r2/verify_m9_design_acceptance.py`;
   - commit as the sole child of the candidate, changing only ADR-0081 status, the record and the two
     reviews.
3. **Then:**
   - Task P0, the combined-base acceptance (it needs M8 on a shared lineage; ask the sponsor about the
     merge);
   - FA-1, the Factual Authority packet, before M9-D;
   - M9-A.

## Not done or open

- Reviewer B has not reviewed any earlier candidate. Passes 1–2 were reviewer A only.
- No sealed M9 review exists yet. `R2_M9_DESIGN_ACCEPTANCE.json` does not exist.
- Carried over from M8: `verify_m8f_determinism` can miss a field that is absent only from run 2. It is a
  locked protocol v3 source, so fix it only under a new protocol.
