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

## Pass-3 results (both received, both FAIL), stored in `docs/r2/evidence/m9-design-review/`

- **Reviewer A** (`pass3-reviewer-A-4fa2b8e8.json`): 2 blocking findings, 8/10 checks pass.
  1. The invalidation guard and coverage refusal in M9-B/C/D need the job table, which only M9-E creates.
     Fix: Task E owns the guard call sites in acquisition, signals, candidates, greenlight and bridges, with
     their tests. The spec says the rank-1a guard applies from M9-E, because no invalidation exists before
     it. Add `M9_INVALIDATION_INCOMPLETE` to the routing rows.
  2. `get_greenlight` returns a bare decision. Fix: add `GreenlightDecisionView(decision, validity)` and make
     incomplete propagation return `M9_INVALIDATION_INCOMPLETE`.
- **Reviewer B** (`pass3-reviewer-B-4fa2b8e8.json`, `gpt-5.6-sol`): 6 blocking findings.
  1. Add the creative policy-pack digest to cohort profiles and M8 entries, and require it to equal
     `LineageBinding.policy_digest`.
  2. `grant_digest` must cover `refresh_after` and `deletion_deadline_seconds`, and `snapshot_digest` must
     cover `capability_evaluation_digest`.
  3. Define the retention and refresh deadline anchor (database time per page and data class), the
     calculation, the closure fold, and the behaviour at refresh expiry, retention expiry and
     delete-on-revoke.
  4. Add a selected-content ref and integrity ref to `FactualEvidenceSelection`, bound in the digests and
     in replay.
  5. The frozen seed revision has `created_by = user_id`, and the M9 evidence keeps `actor_id`.
  6. Task D owns `r2/advanced_creative/lineage.py` and the M8 resolver tests, and the no-M8-change rule
     excepts ADR-0109.
- **Cheap notes to apply in the same revision:**
  - the sweep wording `RETENTION_SWEEP`;
  - port invalidation applies to Factual only, not Canvas;
  - `SweepRetention` and `IntakeM8Correction` take UUIDv7 command ids, with their own idempotency key
    columns;
  - the M8 entry state mapping goes into the M9-C packet;
  - domains for `dependency_closure_digest`, the bridge intent `closure_digest`/`request_digest` and the
    cursor digests;
  - the `host_custodian_leases` columns include `operation`.
- **Next:** apply all of the above in one revision, sweep for cross-file contradictions, then run two fresh
  reviewers (A Claude, B Codex) on the new candidate.

## Session end (2026-10-15)

- **M8 merged locally.** At the sponsor's request, `r2-v2/main` was fast-forwarded to `23cf146a` (the M8
  implementation acceptance), 18 commits from `6d4f7369`. It is **not pushed**: `origin/r2-v2/main` is still
  at `6d4f7369`. Push only with the sponsor's approval.
- **M9 design branch.** `design/r2-m9-v2-revalidation` descends from `r2-v2/main`. Task P0 (combined base)
  can bind M8 on the shared lineage once the M9 design is accepted.
- **Resume point.** The pass-3 fix list above. Apply all 8 blocking findings and the cheap notes in one
  revision, then run fresh reviewers A (Claude) and B (Codex) on the new candidate.

## Codex takeover (2026-10-15, after Claude's session)

The takeover started from clean `0899a550381f568cfb662acd2232d3ad35aa0088` on
`design/r2-m9-v2-revalidation`. The older root worktree's unrelated dirty documents
were preserved. No M9 implementation, migration, provider call or push was performed.

The remediation revision addresses the pass-3 findings in the proposed design:

| Finding | Candidate change |
|---|---|
| A1 | M9-E owns guard/coverage checks in acquisition, signals, candidates, Greenlight, bridges and readers, with backfill/enable ordering and PostgreSQL interleaving tests; B-D routing names E-integrated refusal. |
| A2 | `GreenlightDecisionView` carries validity; reads during propagation refuse and completed invalidation exposes historical `INVALIDATED` decisions. |
| B1 | Cohort profiles and M8 entries bind the full creative profile ID/version/policy-pack tuple through digests and server-resolved seed checks. |
| B2 | Grant digest covers all semantic fields, including refresh/deletion deadlines; snapshot digest covers capability evaluation and persisted class clocks. |
| B3 | Database page/class anchors, observation page ordinal, closure minima, exact expiry boundaries, revocation detection, sweep origin keys and non-renewable deadlines are specified. |
| B4 | Factual selection refs/integrity refs are frozen and hashed; resolved content exists only in the transient port call. Replay, erasure and unknown-outcome lookup behavior are explicit. |
| B5 | Frozen M8 revision uses `created_by=user_id`; M9 retains the interactive `actor_id` separately. |
| B6 | M9-D owns the additive ADR-0109 resolver and focused M8 tests, with existing resolutions frozen. |

The same revision specifies UUIDv7 system command IDs and separate origin hashes,
remaining digest domains, M8 entry-state mapping/test ownership, Factual-only port
invalidation, bridge dispatch guarding, cross-project interactive replay conflicts,
and the host lease `operation` column and downgrade coupling. The existing note
that the verifier does not independently recheck its base-review contract remains
a tooling limitation; the unchanged base contract hash/status was checked directly.

Validation on the candidate working tree:

- `git diff --check`: exit 0.
- Ordinary `uv run python -m pytest tests/unit/scripts/r2/test_verify_m9_design_acceptance.py -q`:
  unavailable because the default uv cache is read-only. Retrying with a `/tmp`
  cache and `--offline --no-sync` did not complete and was interrupted; no pass claimed.
  A direct run with application conftest setup under `timeout 55s` exited 124
  without a test result; that execution is unavailable, not a product failure.
- `.venv/bin/python -m pytest --noconftest tests/unit/scripts/r2/test_verify_m9_design_acceptance.py -q`:
  **21 passed**. This runs the real verifier tests with pytest built-in fixtures,
  excluding application-wide conftest setup; it does not prove application integration.
- Direct Python checks: all five pinned tool/schema/contract hashes match; the
  base-review contract hash/status match; all 12 candidate paths exist; all seven
  Python fences in the spec parse. No design acceptance record exists.
- Graph project `r2-v2-main`, Tier 2, generation `2026-10-15T01:19:44Z`: contract
  and exploration evidence had matching metadata; `lineage.py` was stale and
  was read directly. Docs/scripts are excluded and were read directly. This is
  bounded source verification, not an exhaustive graph audit or fresh donor run.

**Next gate:** commit the remediation candidate, then obtain two fresh mutually
blind author-independent reviews against that exact HEAD and unchanged review
contract `d18b6fb107852cdea8c1d9e486b1e05544ae2564cbc9c0f90b6bb0137a5101b3`.
The changes above are proposed repairs, not independent acceptance. Keep ADR-0081
proposed, do not start P0/M9-A, and do not push the local M8 merge without sponsor
approval. Follow the existing four-path acceptance-commit rule only after both PASS.

## Subsequent review and repair checkpoint (2026-10-15)

The first remediation was committed as
`ffc75a22d3d9d2c2bc6e8d9951ec75927adc18e4`. Native reviewer B independently
sealed **FAIL** against it at `2026-10-15T08:33:20Z` with two blocking findings.
The exact diagnostic is kept locally outside the reviewed linked worktree at
`.worktrees/m9-design-review-pass4-B-ffc75a22.json` (not an accepted sealed review).
Runtime session `01a13ea9-8ae4-7ee0-ae92-34ae73987655` records
`turn_context.model=gpt-5.6-sol`; the generic GPT-6 persona text quoted in that
review is not runtime model authority.

The sponsor explicitly said Claude has no quota and to skip Claude review.
The review contract itself still requires two distinct author-independent,
mutually blind reviewers, not two different model families. A fresh native
reviewer A read the same candidate independently, but its turn failed at the
usage limit **before sealing a result**. This is unavailable review evidence,
not a second PASS or FAIL. No more background agents are launched at this
checkpoint. Preserve the existing two-review acceptance requirement.

The next revision addresses both confirmed B findings and a main-agent
cross-check; these are proposed repairs pending fresh independent review:

| Item | Source-grounded defect | Repair |
|---|---|---|
| B-01 | Caller `requested_at` affected invalidation timing but was absent from the authorization subject; crash-before-commit could replay the lease with changed timing. | Remove it from the Human command; freeze database admission time into job/result evidence, retain exact receipt replay, and test extra-field rejection plus crash/lease boundaries in E. |
| B-02 | Candidate/Greenlight contracts bound source-rule profiles without defining admission for required presence, coverage and age. | Add deterministic source-rule proof rows bound into the closure, an explicit coverage compatibility table, conservative page-age deadlines, explicit optional absence and required-source refusal. C owns the fold; D rechecks it for Greenlight/seed. |
| Main cross-check | Rank-1a refused bridge finalization during a covering job, while job completion required reconciliation of dispatched bridge outcomes (candidate spec lines 1502-1510 and 1822-1827). | Permit only history-only reconciliation under the same locks, atomically extend job dependencies for discovered Factual refs, and prohibit COMPLETE while dispatched outcomes or Factual invalidation receipts remain unknown. Fresh dispatch remains refused. |

Additional validation after these repairs:

- `git diff --check`: exit 0.
- Rebuilt all **80** proposed Pydantic models from the seven spec Python fences
  against the actual accepted M8 base/canonical/digest types; a valid Human
  invalidation command parsed, and adding caller `requested_at` failed with the
  exact `extra_forbidden` location. Greenlight view, source-rule payload and
  ref-only versus transient-resolved Factual selection shapes were checked.
  This executes documentation contracts only, not the future M9 application.
- `.venv/bin/python -m pytest --noconftest tests/unit/scripts/r2/test_verify_m9_design_acceptance.py -q`: **21 passed in 0.15s** on the revised tree; no application-conftest or M9 runtime integration claim.

**Resume:** inspect current HEAD/status and
`.worktrees/M9_CODEX_TAKEOVER_2026-10-15.md`. Obtain two fresh blind reviews of
the revised clean candidate when review quota is available. The `ffc75a22`
diagnostic does not transfer acceptance to a later revision. Keep ADR-0081
proposed; no `R2_M9_DESIGN_ACCEPTANCE.json`, P0 or M9-A implementation is authorized
by the repairs or the contract probe. The M8 merge remains local and unpushed.

## Explicit sponsor acceptance (2026-10-15)

The sponsor explicitly accepted the revised design: `chap nhan m9 roi sang buoc tiep theo luon`. ADR-0110
records the one-candidate exception for `24fa05e0610efa6fb60db50d1b22b10de48f2786`.
`R2_M9_DESIGN_ACCEPTANCE.json` now records **M9_DESIGN_ACCEPTED by sponsor**,
with twelve candidate artifact hashes and no fabricated review outputs.
All earlier missing-review notes remain historical; this section supersedes
their design-acceptance blocker for this candidate only.

Next: execute umbrella Task P0, using the dedicated sponsor schema and
Git-bound verification; preserve the existing later-packet review requirements.
No M9 implementation, production activation or remote push is accepted here.
