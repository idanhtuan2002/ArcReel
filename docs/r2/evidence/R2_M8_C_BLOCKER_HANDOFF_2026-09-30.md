# M8-C continuation handoff — 2026-09-30

Status: **full binding-authority direction selected; design proposed; C1 WIP; C2 promotion stopped**. This file supersedes the earlier checkpoint at this path. It is not an implementation acceptance artifact.

## Live worktrees at the checkpoint

| Worktree | Branch and evidence point | Dirty paths and treatment |
| --- | --- | --- |
| `.worktrees/r2-m8c-binding-design` | `design/r2-m8c-binding-authority`, last design commit before this handoff `efde73cd` | Clean before editing this handoff. Recheck `git rev-parse HEAD` and `git status --short` on resume. |
| `.worktrees/r2-m8c` | `impl/r2-m8c-spatial-candidates`, HEAD `774952b235aa899c0125ee2109d426e9bc6dc9ff` | Untracked `docs/r2/evidence/R2_M8_STOP.json` from C2 preflight; modified `r2/contracts/advanced_creative.py`; untracked `tests/unit/r2/advanced_creative/test_spatial_contract.py`. The last two are C1 source-span WIP, not committed or reviewed. Preserve all three. The failed offline uv-created partial environment was moved intact to `/tmp/r2-m8c-incomplete-venv-20260930`; a temporary venv symlink used for basedpyright was removed. |
| root checkout | `design/r2-m5b-narrative-context`, observed HEAD `dbaf93a6` | Unrelated dirty M12/docs work was not touched. |

M8-B's accepted base remains `774952b2`, with `R2_M8_B_IMPLEMENTATION_ACCEPTANCE.json`. The M8-C stop receipt is valid JSON and intentionally uncommitted under the execution contract.

## Selected design and evidence

ADR-0102 at the design branch selects the full path: a single CAS-versioned Production Preparation binding authority, typed immutable spatial constraints, and a reachable application generation consumer. Candidate-only completion was rejected because it would leave the accepted `SpatialCandidate → PRODUCTION_BINDING` target and C2 promotion unmet. The ADR remains `proposed`; an independent review of `d1c22de2` returned **CHANGES_REQUIRED**. The response at `70d32113` and the review record `docs/r2/evidence/R2_M8_C_BINDING_DESIGN_REVIEW_2026-09-30.md` address the findings in design text but have not been independently re-reviewed.

The design narrows first support to Take-derived approved Scene/Shot targets through `ApprovedScreenplayReader`, two exact M7 approved master images and candidate-object digests, a `LOCATION` binding update, and a separate spatial preview V2 arm. The live consumer must recheck binding snapshot currentness through a dedicated R2 route/task all the way to M7 submit; Golden-only prompt output cannot release M8-C. The existing queue's `reference_video` task rereads mutable script content and cannot be used as the snapshot carrier without a reviewed change.

Research files: `docs/research/2026-09-30-r2-m8c-production-binding-authority.md`, `2026-09-30-r2-m8c-consumer-options.md`, and `2026-09-30-r2-m8c-spatial-fixture-probe.md`. The pinned DramaClaw source is commit `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`, `scene_spatial_contract.py` SHA-256 `975e634cdd99500be5e29901da4930db14d5b81b1d14e6616e7e2e71081f1c92`. A direct AST-node execution of its overlap/direction normalizers on one fixture showed the shared cabinet moved to the left side once, the plain wall continued smoothly, and only the back door received a direction lock. The donor prompt expressly omits bbox; M8 §8 requires visible source spans. This is an intentional correction needing a failing donor fixture and passing R2 regression before an `IMPROVED` parity row.

The codebase graph generation `2026-09-27T03:07:32Z` indexes the root checkout and excludes `.worktrees`; material M8/runtime paths show missing freshness. All findings in this handoff are bounded by direct reads/searches of the stated worktrees, not graph completeness.

## Verification and environment limit

- C1 WIP red test first: isolated pytest collection failed because `SpatialImageSpan` did not exist.
- C1 WIP green: `/home/anhtuan/content-production-os/.venv/bin/python -m pytest --confcutdir=tests/unit/r2/advanced_creative tests/unit/r2/advanced_creative -q` → **62 passed**. The `--confcutdir` limit is material: normal root `tests/conftest.py` import fails on missing `opentelemetry.exporter` in the available root venv, so this is not the required full test gate.
- `/home/anhtuan/content-production-os/.venv/bin/ruff check` on the first source-span revision → passed; `python scripts/audit_tests.py --check` → 0 violations. Re-run both after the plural-span edit and any later changes.
- After the plural-span edit: affected-domain isolated pytest → **62 passed**; targeted Ruff → passed; test audit → 0 violations; targeted `basedpyright` → 0 errors/0 warnings after linking the available root venv. These do not replace the blocked normal root pytest gate.
- `UV_CACHE_DIR=/tmp/uv-m8c-cache uv run --offline ...` failed because the needed `claude-agent-sdk==0.2.139` wheel is absent from that cache. This is an environment limitation, not a test pass.
- Claude Code implementation attempt failed before changes with API/DNS `EAI_AGAIN`; no Claude implementation or tests were produced.
- Design docs passed `git diff --check` and local relative-link checks before the later handoff edit. No backend DB, donor full suite, provider call, frontend check or independent re-review passed.

## Exact resume sequence

1. Recheck both worktree HEADs/status and preserve the M8-C untracked stop receipt and C1 WIP. Verify the donor pin/hash and do not re-import its package through unavailable dependencies; the AST fixture probe is recorded research only.
2. Complete the C1 design mapping from donor wall/joins/gaps and enriched object-level spans into `SpatialPayload`. The plural `SpatialImageSpan` contract WIP preserves old JSON bytes but is not independently accepted. Implement normalizer tests first, then donor same-fixture differential, malformed/partial cases and actual M7 execution boundary; run relevant checks with a complete environment before C1 commit/review.
3. Resolve design gate 1 for ADR-0102: a real Take target-registration fixture using current screenplay admission, two approved M7 image masters, canonical digest vectors, exact spatial V2 wire/persistence models and migration, and dedicated route/task/submit fingerprint contract. Amend the M8 execution contract only after this design is independently reviewed. Keep ADR `proposed` until then.
4. Implement and independently accept target/binding authority and live consumer before C2 promotion. Then complete C2 preview/authorization/atomic promotion, C3 donor parity with zero required skips/unknowns, affected-domain tests and independent full-diff review on exact integrated HEAD. M8-D stays gated on full M8-C acceptance.

Do not describe historical tests, the author design response, candidate-only work, or the C1 WIP as M8-C acceptance. No source or destination branch was pushed or merged in this checkpoint.
