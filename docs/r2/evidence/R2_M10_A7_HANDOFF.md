# M10-A7 handoff (2026-10-28, in progress)

Branch `design/r2-m10-a7-parity`, worktree `.worktrees/r2-m10-a7`, base `9ee0652de` (A6 candidate evidence;
A6 source `af67ea71b`). Nothing pushed. Not accepted.

## Done
- `tests/fixtures/r2/m10_kalinga/donor_functions.json`: exact pinned Kalinga `e4b5a2173ca0…` function
  sources (`tech_qc`, `parse_virality`, `virality_gate`, `sh`, `ffprobe_duration`, `_safe_validate`, the
  `run()` ok expression) with sha256; file blobs validate.py `a34d680f…`, make_video.py `617dc1f6…`.
  Produced by `docs/r2/evidence/m10-a7/extract.py` (git bytes only, never the dirty donor worktree).
- Donor characterization (`m10-a7/characterize.py`, A4 fixtures, window [1,10]):
  av [] (mean -21.1 dB); video_only ["no audio stream"]; silent ["very quiet -91"]; intervals [];
  truncated RAISES untyped ValueError; mpeg4 misleading "no audio stream"; missing ["short.mp4 missing"];
  audio.json one tiny word -> [] (near-zero coverage passes); no words -> issue; missing virality ->
  unknown and run ok=True; `_safe_validate` raising -> True. ~100-150 ms per donor tech_qc.

## Decided rows (freeze in a baseline JSON BEFORE measuring, R2-DEC-031 precedent)
Measured: R1 missing master (typed refusal, no subprocess); R2 audio stream required (CONTAINER_STREAM
require_audio); R3 loudness (INTEGRATED_LUFS [-35,-8]; SILENT FAIL under REQUIRED); R4 caption timing
(CAPTIONS coverage; donor sparse-words defect; missing caption -> typed refusal); R5 advisory failure never
PASS/READY (unmet_slots/project_readiness vs ok=True/_safe_validate); R6 tool failure typed (truncated,
mpeg4 -> ProbeFailedError). Wholly EXCLUDED with reason: duration window (M10-B platform-constraint
snapshot, spec 2026-09-16 §7; carry to B), SEO lint (M10-B), virality (rejected self-score), AI
review/repair (rejected auto-approval, needs provider). Donor run() has no short-circuit beyond the
missing-file prerequisite. Volumedetect regex-miss defect: no fixture, not claimed.
Dimension criteria to freeze: performance PARITY iff M10 median <= donor median + 1500 ms and within
max_runtime_ms (never IMPROVED); resources IMPROVED (bounded ceilings + ResourceEvidence); determinism via
measurement_digest twice; data_integrity via content-digest binding.

## Next
1. Baseline JSON + research note; 2. `tests/integration/server/services/test_quality_kalinga_parity.py`
reusing `measure`/`config_for` from test_quality_probe_recipes.py (own helper for a committed sparse.srt);
3. `scripts/r2/verify_m10_a_candidate.py` (+ unit tests): hashes, parity fold via evaluate_quality_parity,
migration chain 65f53650f3a8->07fd34535384->57f67bae0cb4->bed415be3608 single head, no router/network/
credential/export imports in M10-A modules, subprocess only in quality_probe_runtime/worker;
4. all M10-A tests + static gates; 5. `R2_M10_A_CANDIDATE.json`; stop for independent acceptance (Codex
quota returns 2026-11-02 15:12). Test env: see memory test-env-gotchas; PG container arcreel-m10-a4-test-pg :55490.
