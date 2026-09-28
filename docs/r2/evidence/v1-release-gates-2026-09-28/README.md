# First V1 release-gate run (failed) — candidate `abf5ec1d`

This is the runner's manifest and logs, kept as written. It is **not** release evidence.

**Result.** 9 of 12 gates passed. These three failed:

- `h1_h8`: 15 failed, 15002 passed, 45 skipped;
- `migration`: 5 failed, 1066 passed;
- `golden_a`: 14 failed, 45 passed.

**Failures.**

- **Remotion renders.** Every failure except one is a Remotion render (`npx remotion render`) that exited 1. The runs covered Golden A real-media, the M6 mutation tests and the host-integration tests. Remotion's own output was captured and discarded, so these logs do not show the cause.
- **Trial-run concurrency test.** `TestTrialRuns.test_a_second_concurrent_run_is_refused` received a 404 cancel.

**Diagnosis (inferred, not proven).** `/tmp` is a 12 GB tmpfs.

- Before the run it already held about 5.4 GB of old pytest base directories, 1.7 GB of session scratch and leftover Remotion bundles.
- The run adds more than 1.3 GB of its own, and Remotion bundles into `os.tmpdir()`.
- After the run, the same render and trial-run tests passed when run alone:
  - `tests/integration/r2/m3/test_remotion_engine.py`: 4 passed;
  - the trial-run test: 3 of 3 passed.

**Follow-up.**

1. A failed render now raises `RemotionRenderError` carrying the tail of Remotion's output.
2. The old temporary directories were removed.
3. The rerun, `v1-release-gates-2026-09-28-run2`, sets `TMPDIR` to an on-disk directory and samples `/tmp` usage every minute.
