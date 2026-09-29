# M8-A independent review record (Codex, 2026-09-29)

Seven rounds were run by Codex through the codex-rescue runtime. Codex reviews in a read-only sandbox and cannot run pytest there. The test runs are recorded in `R2_M8_A_EXPLORATION_PROMOTION.json`, bound to the tested head.

| Round | Job | Reviewed range | Outcome | sha256 of raw output |
|---|---|---|---|---|
| 1 | `task-mumkmd5v-iab8rb` | `dc13cc93..21821568` | CHANGES_REQUIRED: 5 findings (payload digest, M7 lock order, foreign-ID genesis, cascade owner FK, foreign-slot object) | `d4cb9b82397824aba326033aaa6cfce0153d8af388df76e26842bc635b08c858` |
| 2 | `task-mumm3dov-92e1fw` | `dc13cc93..f606ac06` | CHANGES_REQUIRED: round 1 all FIXED, V2-02c accepted; backfill race (V2-02d) and unscoped preview FKs | `d3aac0f28fab72d7df846857a590a1d83a46e25c022a99dd5a9de58305092bb0` |
| 3 | `task-mumnabnb-j68cdt` | `dc13cc93..07cb27f9` | CHANGES_REQUIRED: round 2 FIXED; two backfill paths (V2-02d) | `f6476c80f2d31c932943959cb97eeca58a6ce7fe0d070274af94e8a9e685c379` |
| 4 | `task-mumo1kt0-hhvlo9` | `dc13cc93..809e1358` | CHANGES_REQUIRED: round 3 FIXED; one backfill path (V2-02d) | `0dcac90f0d8957c97ce9097b708c9e5c634edd73ef0c45163806e23fcc75f43b` |
| 5 | `task-mumoru3q-bfv13h` | `dc13cc93..96a84875` | CHANGES_REQUIRED: round 4 FIXED; two pre-existing backfill paths (V2-02d) | `6a39b2418b1a06f4d55fc88abd38637eccf4d64985904dd7e5ebe78c222a48e2` |
| 6 | `task-mumpluj0-nmpspe` | `dc13cc93..72d1de78` | CHANGES_REQUIRED: exhaustive backfill sweep, 3 blocking + 3 non-blocking (V2-02d); amendment 12 then decoupled V2-02d from M8-A | `29e8ed70ff2bd8506de927dbcd052eb13bb501b023d8781760031b6c82f32afc` |
| 7 | `task-mumqsk50-yxozkk` | `dc13cc93..215d18e0` | M8_A_ACCEPTED: all 7 M8/V2-02c fixes in place, no blocking finding, V2-02c accepted, one non-blocking coverage limit | `465cc176c4a6985659f407efc75058c5b2157ed1c34248dec142a0e084386aea` |

Rounds 3 to 6 concerned only the V2-02d backfill. Amendment 12 (`bddb42a4`, a sponsor decision) scoped M8-A acceptance to M8-A and V2-02c and added a stopping rule. V2-02d continues on its own V2 track.

## Round 7 output (verbatim)

## 1. HEAD reviewed

Worktree HEAD: `215d18e06ecb08a805d3663b7d415015124ccdbf`. Tested code HEAD recorded in the evidence: `b72df36ba145befbcc18a42dd920cc518462b40f`. The commits between them change only the evidence JSON and its schema; the working tree is clean.

## 2. Verdict: **ACCEPT**

I found no in-scope blocking defect on the reviewed code paths. **V2-02c remains accepted.** This is a source-level acceptance review with the test execution limit stated below.

## 3. Round 1–2 fix status

| Fix | Status | Working-tree evidence |
|---|---|---|
| Recompute stored payload digest at promotion | STILL FIXED | [promotion.py](/home/anhtuan/content-production-os/.worktrees/r2-m8a/r2/advanced_creative/promotion.py:110) reloads the revision; lines 116–121 compare its stored and recomputed digests with the preview. |
| V2-02c: lock authority row before appending history | STILL FIXED | [M7 promotion.py](/home/anhtuan/content-production-os/.worktrees/r2-m8a/r2/host_hardening/promotion.py:145) calls `advance_head` before `insert_head_version` at line 155. |
| Scope candidate keys by user and project | STILL FIXED | [advanced_creative.py model](/home/anhtuan/content-production-os/.worktrees/r2-m8a/lib/db/models/advanced_creative.py:48) defines the scoped head key; line 68 defines the scoped revision key. |
| Preserve evidence on user deletion with `RESTRICT` | STILL FIXED | [advanced_creative.py model](/home/anhtuan/content-production-os/.worktrees/r2-m8a/lib/db/models/advanced_creative.py:38) supplies `ON DELETE RESTRICT` to the M8 evidence models. |
| Require rendered object to belong to target slot | STILL FIXED | [promotion.py](/home/anhtuan/content-production-os/.worktrees/r2-m8a/r2/advanced_creative/promotion.py:124) locks and rereads the slot; lines 133–141 check the object's slot and digest before calling M7. |
| Map remaining M7 promotion conflicts to M8 errors | STILL FIXED | [advanced_creative.py service](/home/anhtuan/content-production-os/.worktrees/r2-m8a/server/services/advanced_creative.py:35) identifies mapped conflicts; lines 100–113 translate them. |
| Scope authorization and receipt preview foreign keys | STILL FIXED | [advanced_creative.py model](/home/anhtuan/content-production-os/.worktrees/r2-m8a/lib/db/models/advanced_creative.py:169) uses `(user_id, project_name, preview_id)` for authorizations; line 197 does so for receipts. |

## 4. Findings

### Blocking

| Description | File:line | Why blocking |
|---|---|---|
| None found | — | No concrete in-scope correctness, integrity, security, or acceptance defect was established. |

### Non-blocking

| Description | File:line | Why non-blocking |
|---|---|---|
| The recorded concurrency tests do not force a complete M8 promotion interleaving. The packet discloses this limit. | [M8 evidence](/home/anhtuan/content-production-os/.worktrees/r2-m8a/docs/r2/evidence/R2_M8_A_EXPLORATION_PROMOTION.json:375) | A coverage limit, with no demonstrated failing code path. It does not meet amendment 12’s blocking rule. |

The final sweep found the ADR lock sequence in [M8 promotion](/home/anhtuan/content-production-os/.worktrees/r2-m8a/r2/advanced_creative/promotion.py:74), replay before currentness checks at lines 74–81, and a single M8 authority call at line 144. [Preview creation](/home/anhtuan/content-production-os/.worktrees/r2-m8a/r2/advanced_creative/exploration.py:260) refuses ProductionBinding and manifest targets; promotion checks the target again at lines 106–109. [Host composition](/home/anhtuan/content-production-os/.worktrees/r2-m8a/server/services/advanced_creative.py:93) uses the same session with deferred M7 commit. The migration’s scoped preview constraints match the [ORM declarations](/home/anhtuan/content-production-os/.worktrees/r2-m8a/lib/db/models/advanced_creative.py:162), and the evidence verifier passed.

## 5. Commands actually run and key output

- `git status --short --branch && git rev-parse HEAD && git log -1 --format='%h %s' && git show -s --format='%h %s' b72df36b && git show -s --format='%h %s' 34bd4346` → clean branch; HEAD `215d18e0`; tested code `b72df36b`; V2-02c `34bd4346`.
- `git diff --name-only b72df36b..215d18e0` → only the M8 evidence JSON and schema.
- `rg -n 'promote_registered\(|AtomicPromotionService\(' r2 lib server scripts --glob '*.py'` → one `promote_registered` caller in the M8 host service and one `AtomicPromotionService` construction in M7’s authority unit.
- `python -B scripts/r2/verify_m8_evidence.py docs/r2/evidence/R2_M8_A_EXPLORATION_PROMOTION.json --schema docs/r2/evidence/schemas/R2_M8_A_EXPLORATION_PROMOTION.schema.json --tested-head b72df36ba145befbcc18a42dd920cc518462b40f --repo .` → `M8_EVIDENCE_OK`.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/unit/r2/advanced_creative tests/unit/r2/contracts/test_advanced_creative.py tests/unit/r2/test_m8_architecture_boundaries.py tests/unit/r2/host_hardening/test_promotion.py` → could not start: Python reported no usable temporary directory in the read-only environment.
- Bounded `nl -ba`, `rg`, `git log`, `git diff`, and `git show` reads covered the cited source, ADR, migration, tests, and evidence. Final `git status --short --branch` remained clean.

## 6. Coverage limits

The graph listed this worktree, but graph status and search calls required approval unavailable in this session; structural claims therefore use bounded source searches and direct reads. Fresh pytest execution was unavailable because the read-only environment has no writable temporary directory. I verified the evidence document’s schema, tested-HEAD field, recorded exit codes, and artifact hashes with its verifier; its historical test logs were not rerun. V2-02d backfill files and follow-ups were excluded under [amendment 12](/home/anhtuan/content-production-os/.worktrees/r2-m8a/docs/r2/evidence/R2_M8_EXECUTION_CONTRACT_AMENDMENT_12_2026-09-29.json:13).

{"status":"M8_A_ACCEPTED","reviewed_head":"215d18e06ecb08a805d3663b7d415015124ccdbf","accepts_v2_02c":true,"blocking_findings":[],"nonblocking_findings":["Concurrent M8 promotion tests do not force a complete M8 interleaving; disclosed at docs/r2/evidence/R2_M8_A_EXPLORATION_PROMOTION.json:375."],"material_unknowns":[]}

