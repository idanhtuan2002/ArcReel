# Story Task4 handoff (2026-10-18, usage limit)

- Worktree: `.worktrees/r2-v2-story-release`, branch `release/r2-v2-story`. The HEAD is the commit that adds this file; the tree is otherwise clean. The disposable test PostgreSQL is docker `arcreel-story-test-pg` at 127.0.0.1:55480 (tmpfs, `arcreel` / `arcreel_test_only` / `arcreel_story_test`).
- Task4 is open by Human decision (`ecc8d742`).
- **Done:**
  - 4.0 rubric and winning rule fixed (`805a6feb`);
  - 4.1 `checks.py` L1, with the Huohuo dedupe parity (`9ee48afc`);
  - 4.2 `repair.py` span patches and length normalizing, with the Huohuo patch parity (`bb97a44a`).
- **In progress, 4.3 prompts and schemas:** no code written yet. Donor sources were read: Shenbi short-outline (S01), and Novel Studio `prompts.ts` seed / story bible / style bible / chapter outline / scene beats / chapterDraftPrompt / continuity (S02, S04, S05).
  - Still to read: Shenbi chapter-planning memo (S03), drafting craft rules and anti-ai-reference (S04), short-packaging (S11).
  - To produce: `server/story_authoring/prompts/{outline,planning,drafting,packaging}.py`, the stage Pydantic schemas, and `test_prompts.py`.
- **Remaining:**
  - 4.4 `audits.py` (L2 specialists, L3 critic, quote-verified findings);
  - 4.5 `pipeline.py` (dependency graph, staleness, chapter loop), the run driver and executor registration (`story_authoring_run`, `recover_run` at start), the service/router API and `handoff.py`;
  - 4.6 the live end-to-end run, the n ≥ 10 differential per the fixed rubric, and the `R2_STORY_*_PARITY.json` contracts;
  - then Task5 (UI), Task6 (acceptance runs), Task7 (release; push only on Human confirmation).
- **Resume:** read `docs/superpowers/plans/2026-10-18-r2-v2-story-release-amendment.md` and `docs/r2/evidence/R2_STORY_AUTHORING_QUALIFICATION.md` (Task0–3 sections), then continue at 4.3.
