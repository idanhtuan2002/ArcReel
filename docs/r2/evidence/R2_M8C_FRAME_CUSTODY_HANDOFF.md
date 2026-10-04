# M8-C frame custody implementation checkpoint — 2026-10-04

**Status:** implementation checkpoint only. No M8-C C1 acceptance, PostgreSQL gate, independent exact-HEAD review, live migration or production activation is claimed.

## Resume point and Git state

- Implementation worktree: `.worktrees/r2-m8c-binding-design`, branch `impl/r2-m8c-frame-receipts`, tested code HEAD `b47e13dc22153efdca0fe5310626441f63aa9bf0`. The worktree was clean when this handoff was written, before adding this file.
- Commits on top of design HEAD `50eb063493ec910a0ef09928ea497ceac1f70083`: `229a22ba` scoped frame receipt contracts/schema/repository; `810766b5` cherry-pick of the candidate-store no-overwrite fix from `fix/r2-m8c-frame-publish`; `ee81fd71` bounded FFmpeg decode and candidate-store publisher; `b47e13dc` current-master registration and adversarial tests.
- Spatial C1 worktree `.worktrees/r2-m8c`: branch `impl/r2-m8c-spatial-candidates`, HEAD `774952b235aa899c0125ee2109d426e9bc6dc9ff`, eight dirty paths including untracked `docs/r2/evidence/R2_M8_STOP.json`; preserve all of them. Its parity script still exits 1 on the accepted typed mapping deviation. No frame code from this checkpoint has been merged into that worktree.

## Implemented and observed

- `FrameIdentityV1` derives `m8f:` from the complete canonical parent/ordinal/recipe/build/output digest; `FrameDerivationReceiptV1` rejects an ID/body mismatch. The fixed MASTER/REVERSE vectors validate.
- Migration `8b8c4a0e0001` adds one scoped receipt table with composite `RESTRICT` references to candidate objects and historical master versions. Real SQLite foreign-key probes reject cross-user candidate and master references, and a valid scoped insert succeeds. Repository reads verify stored columns, body and digest.
- FFmpeg decodes a zero-based ordinal to a bounded RGB24 PNG; the output is checked even when FFmpeg exits zero without a frame. The decoder identity hashes the complete local `ffmpeg -version` output. Publication reuses the candidate store's hard-link, publish-if-absent path and rejects unequal existing bytes.
- `FrameDerivationService` checks the full scoped Gate C DB/manifest projection, approved candidate and parent bytes before decode; after publication it takes the existing master-authority row lock, repeats those checks, verifies final frame bytes and stages the candidate plus receipt in one transaction. Exact same-command replay rechecks bytes; changed command input conflicts. The service takes the existing session factory because `serialized_artifacts` owns its transaction and sorted authority lock.
- At code HEAD `b47e13dc`, the combined affected selection returned **55 passed, 5 SQLite reflection warnings**. It includes the fixed-vector, migration, candidate-store, real Gate C, black/white parent-frame, corrupt byte, missing projection, stale parent, crash-after-link replay and forced two-writer tests. Ruff check `.`, full basedpyright (`0 errors, 0 warnings`), `lint-imports` (`22 kept, 0 broken`), `deptry` (success) and `scripts/audit_tests.py --check` (`0 violations`) also passed on the same code tree. The initial sandbox migration attempt timed out in `aiosqlite`; the successful async database tests ran outside the sandbox against temporary SQLite databases.

## Open gates and next action

1. Run the migration/repository and forced writer/parent-advance/rollback tests on **real PostgreSQL**. The current host has no responding server at `127.0.0.1:5432` (`pg_isready` exit 2) and `/usr/lib/postgresql/18/bin` contains client programs only. SQLite success is not a substitute for PostgreSQL lock/FK behavior.
2. Review the exact diff `50eb0634..b47e13dc` independently, including candidate-store parent-directory symlink race, `os.link` filesystem behavior, receipt replay under different parent keys and read-side integrity. The shared-store fix closes the final-path overwrite race; an anchored directory-handle proof is still missing.
3. If review finds defects, repair on the isolated branch, rerun affected tests/static gates and record a new exact HEAD. Keep live migration and production use inactive.
4. Continue C1 source custody only after the frame receipt read/verification API and pair-admission receipt can bind two current approved video parents. The separate C1 spatial-completion sidecar and its raw/model/prompt/overlap binding remain proposed; C2 promotion remains closed.

No source or test files are dirty in this worktree after the code checkpoint. This handoff is the only pending tracked change at writing time.
