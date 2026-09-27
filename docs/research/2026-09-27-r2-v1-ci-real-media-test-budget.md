# R2 V1 — CI budget for real-media (Remotion) tests

Date: 2026-09-27. Branch `feat/r2-m7e-v1-lineage` at `836200bf`. This note is
research. It gives options and a recommendation, not a decision. License is out
of scope.

## Question

The real-render M3/M6 tests take hours. How should they sit in the test tiers
and the CI jobs, so that the CI gates can pass without losing the coverage
that matters?

## Facts (source-backed)

1. **CI jobs** (`.github/workflows/test.yml`).
   - `backend-tests` runs `pytest tests/integration -n 4 --dist loadfile` with
     `timeout-minutes: 25`. `tests/unit` runs as a separate matrix entry.
   - `postgres-compat` runs `-m "uses_db and not sqlite_only"` with the same
     25-minute limit.
   - Selecting `tests/integration` by path leaves `tests/e2e/` out of CI.
2. **Test tiers.**
   - `CONTRIBUTING.md` §分层与目录: CI runs `-m "not e2e"`. `integration`
     allows "ffmpeg 子进程" (ffmpeg subprocesses). `e2e` means real external
     services, "CI 默认跳过" (skipped by default in CI).
   - The `pyproject.toml` marker text for `e2e` also lists "重型 ffmpeg 等"
     (heavy ffmpeg and similar).
   - The tier comes from the directory; conftest injects it.
3. **Timeout policy.**
   - `pyproject.toml` sets `timeout = 120` as a hang guard, not a duration
     budget. Slow tests widen it one by one with `@pytest.mark.timeout(N)`.
   - The M6 tests use 1500 s and cite a "pyproject.toml note" that does not
     exist.
4. **The real-render tests never skip.**
   - `r2/m3/remotion_engine.py::_ensure_npm_dependencies` installs the vendored
     `remotion-composer` dependencies on demand.
   - No `skipif` guards the tests, so on CI they would install and render.
5. **Measured durations** (`R2_V1_FULL_GATE_2026-09-27.md`; the call times
   were measured on a contended local machine).
   - **M6:** `tests/integration/r2/test_m6_dual_profile_acceptance.py` has six
     tests of 837–1500 s each, about 107 min in all. `--dist loadfile` puts
     the whole file on one worker.
   - **M3:** the real-render tests under `tests/integration/r2/m3/` total
     about 72 min across several files.
   - **Isolated run:** alone, the M6 slice test takes 807 s.
   - **Totals:** the local backend suite took 1:48:53, and the PG16 dialect
     suite 1:52:11, because the M6 tests are also `uses_db`.
6. **What the M6 tests check.**
   - Their subject is the authority and lineage behaviour: shared Canon
     parent, sibling isolation, and five adversarial mutations (report reuse,
     stale map approval, re-admission, reused decision ID, waiver
     laundering).
   - Real rendering enters through `run_profile_slice`, via
     `GoldenALocalProducer.produce` per shot. The file-level real-media checks
     are in `_assert_real_video`: ffprobe codec type and frame pixel stddev.
   - The M3 real-media closure spec
     (`docs/superpowers/specs/2026-09-21-r2-m3-real-media-closure-design.md`)
     makes no test-tier or CI decision.
7. **The fork's CI has never run.**
   - `gh api repos/idanhtuan2002/ArcReel/actions/runs` returns
     `total_count: 0`, although Actions permissions are enabled. GitHub does
     not run workflows on a fork until the owner enables them.
   - So nothing blocks a push today. The limit applies once workflows run, or
     if the work goes upstream.

## Inferences

- On a 4-vCPU hosted runner, the integration job and the PG job would each
  pass 25 minutes by a wide margin. The M6 file alone is about 4 times the
  budget, before M3.
- The five M6 mutation tests do not need real pixels to prove their
  rejections. Each one renders two full slices only to reach the state it
  mutates.
- Real media matters where it is the claim: the M3 Golden A closure, the M6
  slice acceptance, and the restore-derived Golden drill.

## Options

- **A. Move every real-render test to `tests/e2e/`.**
  - What it takes: a move only; no code change.
  - Pro: CI gets fast again, and the approach follows the existing tier
    convention (fact 2).
  - Con: the M6 authority mutations lose CI protection. The `e2e`
    definition in `CONTRIBUTING.md` names external services, so it would need
    a one-line clarification.
- **B. Split by what each test proves** (recommended).
  - Real-media claims go to `tests/e2e/`: the M3 real-media closure and
    end-to-end tests, and the M6 two-slice acceptance.
  - The M6 mutation tests stay in `integration`, rendering through a fast
    FFmpeg card producer injected into `GoldenALocalProducer`.
  - Pro: CI keeps the authority and lineage checks, and real media stays
    proven by e2e and the release gate (V1-08 runs full gates on the exact
    SHA).
  - Con: a bounded code change in the M6 fixture, and an audit of which M3
    tests need real media.
- **C. Keep the tiers; add a separate CI job with a large budget.**
  - Pro: every check runs on each PR.
  - Con: about 3 hours of runner time per backend change, plus
    Chrome/npm installs on CI. The `integration` jobs would still need an
    exclude marker.

## Unknowns

- **No fast producer seam exists (checked).** `GoldenALocalProducer.produce`
  calls `remotion_engine.render_cut` directly, and the old solid-colour FFmpeg
  stub was removed on purpose in the M3 real-media closure.
  - B therefore needs a small injection point, such as a renderer argument
    on `GoldenALocalProducer`, plus a fast FFmpeg card renderer used only by
    tests.
  - That is a bounded code change, but it touches the M3 closure's "no stub"
    stance. So it needs an explicit sponsor decision: a stub is allowed in
    authority-only tests and never in real-media evidence.
- Runtime on a hosted runner, which has not been measured.
- Whether the sponsor wants CI enabled on the fork at all before V1-08.

## Recommendation

B. Real-media evidence is what V1-07 and V1-08 need, and it belongs to the
release and e2e gate. Authority mutations are regressions that CI should
catch on every change. This does not block V1-05 acceptance; it blocks a
green CI once workflows run.
