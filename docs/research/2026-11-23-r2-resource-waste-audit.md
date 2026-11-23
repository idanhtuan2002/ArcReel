# Where R2's resources went, and what stops the waste

Date: 2026-11-23. Asked by the sponsor: "the best donor parts should run at once and well; why do we still spend so
much?" Scope: the whole project, 2026-11-10 … 11-23 (releases r2-v2.5.0 … r2-v2.5.90, every production run on the
host). Labels: **FACT** (with source), **INFER**.

## 1. What was spent (FACT)

- **91 releases in 14 days** (`git tag -l 'r2-v2.5.*'`), 20 on 11-15 and 30 on 11-16. Each is a sponsor deploy
  (stop, sudo deploy, ~a pre-deploy backup of ~2.3 GB), a resume, and a session cycle of mine.
- **24 production runs** on the host (`GET /projects/*/production-runs`): 11 SUCCEEDED, 5 FAILED_QUALITY (all
  STORY on san-xuat, 11-14/15), 3 cancelled, 2 BLOCKED_CONFIGURATION, 1 BLOCKED_UNKNOWN, 1 paused, 1 running.
  Run 37fdb3bd reached generation 6 and fece65fc generation 9: each generation is a block, a fix, a resume.
- **Reviewer qualification corpora** (ADR-0113/0134/0165/0167): days of local GPU 11-16 … 11-22 and the Gemini free
  quota, then removed by ADR-0169. No donor has this mechanism.
- **Disk**: every deploy keeps a full backup set; 81 sets were deleted on 11-22 and 11 more today to let a run start
  (`INSUFFICIENT_DISK` twice). `v2-deploy.sh` keeps them all.

## 2. Why each release was made (FACT: release subjects; class by the main agent)

| Class | Releases | Share |
|---|---|---|
| **G** our own run/governance layer: currency, digests, resume, fences, locks, preflight, grants | 29 (2.5.0, 3, 5, 11, 12, 20, 36, 38–49, 58, 60, 68–70, 73, 74, 85, 87, 88) | 32 % |
| **Q** our own reviewer-qualification and quality-gate machinery | 11 (2.5.15, 59, 66, 77–84) | 12 % |
| **C** content checks and craft written by us where a donor has the unit | 19 (2.5.6–8, 10, 13, 14, 21, 22, 24–26, 37, 56, 57, 61, 67, 76, 86, 89) | 21 % |
| **F** new forms and features | 13 | 14 % |
| **U** UI | 15 | 16 % |
| docs-only tags | 4 | 4 % |

**44 % of releases (G + Q) repaired mechanisms no donor has.** Another 21 % repaired content behaviour we rewrote
instead of porting. Only one release (2.5.90) carried a donor unit ported whole, and it ran on the first try (113
donor tests unchanged).

## 3. The repeated patterns inside G (FACT, with the releases that show them)

1. **One state, several predicates.** "Is this episode's media complete?" is decided in the workflow planner and again
   in `media_adapter._episode_media_current`; each new state broke the copy separately: a stale storyboard (2.5.44),
   audio `not_applicable` (2.5.88).
2. **A new mode not swept through its consumers.** Silent units under TTS delivery broke the narration check (2.5.85),
   then the video task, the execution checkpoint and selection coverage (2.5.87): two releases, two blocked resumes.
3. **The run's own writes seen as outside changes.** Characters a run registered after adaptation (2.5.41), the
   pinned-input audit (2.5.42), input-changed resumes (2.5.58, 2.5.60), `EXTERNAL_INPUT_CHANGED` on a complete
   episode (2.5.88).
4. **Whole-file digests between sibling tasks.** TTS and video tasks fail "formal artifact input changed" because
   each commit writes `generated_assets` into the script the others pinned (tracker, open since 11-22).
5. **Recorded approvals invalidated by ordinary changes.** `LAUNCH_QUALIFICATION_CHANGED` (7 mentions in evidence),
   `POLICY_MOVED` (4), `AUTOMATION_GRANT_NOT_CURRENT` (one run still blocked): each needs a sponsor or agent action,
   then a resume. ADR-0127/0139 already patch two of them by re-recording automatically.
6. **Resume semantics fixed piecemeal** (2.5.38, 39, 46, 58, 60, 77).

How the donors handle the same things (FACT): DramaClaw @ b299bfd runs Celery tasks over SQLite with column-level
patches (`IdentityPlanner._write_episode_identities`: "a whole-row write here would … lose a menu written
meanwhile"), so sibling writes do not conflict and a rerun is a resume; no donor pins a run to an input digest,
re-qualifies a launch, or blocks on a policy digest.

## 4. Causes (INFER)

1. **The frozen R2 architecture put authority, evidence and fencing in front of every step**, before any real run. Each
   real run then meets an edge of that layer; the layer is ours alone, so no donor test covers it.
2. **Fixes were made per instance, not per class**, so the same root cost two or three deploy cycles (patterns 1, 2, 6).
3. **Own mechanisms with a recurring cost were added without a donor comparison of their cost** (qualification corpora;
   launch qualification records).
4. **Content units were rewritten, not ported** (class C; see the companion note on donor ports).
5. **No ledger of blocks**: the waste was invisible until counted today.

## 5. What changes now (decided by the main agent, no product change)

1. **Class fix rule** (AGENTS.md): a run block is fixed for its whole class in one release: find every consumer of the
   state, mode or digest involved (`grep` the value), fix and test each, and say so in the commit.
2. **New-state sweep rule** (AGENTS.md): adding a state value or delivery mode lists every predicate that reads it in
   the ADR or commit.
3. **Recurring-cost rule** (AGENTS.md): an own mechanism that costs GPU, quota, a human step or a run block on every
   run needs a donor comparison and the sponsor's approval; ADR-0169 is the model.
4. **Block ledger** `docs/r2/evidence/R2_RUN_BLOCK_LEDGER.md`: one line per run block (date, run, reason, class,
   false or true, fix). Reviewed when the ledger grows by ten lines.
5. **Backup retention**: the deploy keeps the newest three backup sets (patch for `v2-deploy.sh`, run by the sponsor).

## 6. Decisions for the sponsor (proposals)

- **D1. Launch qualification and policy digests stop blocking.** Record them at run start as evidence (as ADR-0169 did
  for reviewers); a run is never stopped by `LAUNCH_QUALIFICATION_CHANGED` or `POLICY_MOVED`.
- **D2. The run's own writes never block it.** The input witness ignores every write made by the run's tasks;
  `EXTERNAL_INPUT_CHANGED` only for a human edit or another run. Script currency per unit, not per file (ends
  pattern 4), as DramaClaw patches per column.
- **D3. One completeness predicate.** The run asks the workflow planner whether the target episode is complete;
  `media_adapter` keeps no copy.
- **D4. Port, do not rewrite, the class-C behaviour** in the order of the donor-port note (ViMax selectors, huohuo
  skills verbatim, OpenMontage pipelines).
