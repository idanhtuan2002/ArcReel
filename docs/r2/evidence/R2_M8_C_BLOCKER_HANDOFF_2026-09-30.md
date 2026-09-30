# M8-C continuation handoff — 2026-09-30

Status: **full binding-authority direction selected; design proposed; C1 WIP; C2 promotion stopped**. This file supersedes the earlier checkpoint at this path. It is not an implementation acceptance artifact.

## Live worktrees at the checkpoint

| Worktree | Branch and evidence point | Dirty paths and treatment |
| --- | --- | --- |
| `.worktrees/r2-m8c-binding-design` | `design/r2-m8c-binding-authority`, last committed HEAD before this edit `90421d577bab3eea827c950bc42b0e8ab20d5ec5` | This handoff, ADR-0102, binding spec and review record have uncommitted author revisions after the independent review. Recheck `git rev-parse HEAD` and `git status --short` on resume. |
| `.worktrees/r2-m8c` | `impl/r2-m8c-spatial-candidates`, HEAD `774952b235aa899c0125ee2109d426e9bc6dc9ff` | Untracked `docs/r2/evidence/R2_M8_STOP.json` from C2 preflight; modified `r2/contracts/advanced_creative.py`; untracked `r2/advanced_creative/spatial.py`, `tests/unit/r2/advanced_creative/test_spatial_contract.py` and `test_spatial_normalization.py`. The code/tests are C1 WIP, not committed or reviewed. Preserve all five. The failed offline uv-created partial environment was moved intact to `/tmp/r2-m8c-incomplete-venv-20260930`; temporary venv symlinks used for basedpyright were removed. |
| root checkout | `design/r2-m5b-narrative-context`, observed HEAD `dbaf93a6` | Unrelated dirty M12/docs work was not touched. |

M8-B's accepted base remains `774952b2`, with `R2_M8_B_IMPLEMENTATION_ACCEPTANCE.json`. The M8-C stop receipt is valid JSON and intentionally uncommitted under the execution contract.

## Selected design and evidence

ADR-0102 at the design branch selects the full path: a single CAS-versioned Production Preparation binding authority, typed immutable spatial constraints, and a reachable application generation consumer. Candidate-only completion was rejected because it would leave the accepted `SpatialCandidate → PRODUCTION_BINDING` target and C2 promotion unmet. The ADR remains `proposed`; independent reviews of `d1c22de2` and clean `90421d57` both returned **CHANGES_REQUIRED**. At `90421d57`, the consumer, custody and V2 wire findings remained `PARTIALLY_FIXED`; stale note wording was `FIXED`. The review record contains exact evidence. Author revisions after that review specify a registry-owned target version, same-session locks, server-derived proposal and route/task/fingerprint field groups, but are not reviewed or accepted.

The design narrows first support to Take-derived approved Scene/Shot targets through `ApprovedScreenplayReader`, a `LOCATION` binding update, and a separate spatial preview V2 arm. A later source-custody check found the live Gate C approval/projection path is episode-video-specific; direct approval of two image masters has not been proven. The proposed first source path is now two immutable frames derived from two distinct approved video master heads, with parent/recipe/frame digests. This change is not yet independently reviewed or backed by a two-master integration fixture. The live consumer must recheck binding snapshot currentness through a dedicated R2 route/task all the way to M7 submit; Golden-only prompt output cannot release M8-C. The existing queue's `reference_video` task rereads mutable script content and cannot be used as the snapshot carrier without a reviewed change.

Research files: `docs/research/2026-09-30-r2-m8c-production-binding-authority.md`, `2026-09-30-r2-m8c-consumer-options.md`, `2026-09-30-r2-m8c-spatial-fixture-probe.md`, and `2026-09-30-r2-m8c-spatial-source-custody.md`. The pinned DramaClaw source is commit `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`, `scene_spatial_contract.py` SHA-256 `975e634cdd99500be5e29901da4930db14d5b81b1d14e6616e7e2e71081f1c92`. A direct AST-node execution of its overlap/direction normalizers on one fixture showed the shared cabinet moved to the left side once, the plain wall continued smoothly, and only the back door received a direction lock. The donor prompt expressly omits bbox; M8 §8 requires visible source spans. This is an intentional correction needing a failing donor fixture and passing R2 regression before an `IMPROVED` parity row.

The codebase graph generation `2026-09-27T03:07:32Z` indexes the root checkout and excludes `.worktrees`; material M8/runtime paths show missing freshness. All findings in this handoff are bounded by direct reads/searches of the stated worktrees, not graph completeness.

## Verification and environment limit

- C1 WIP red test first: isolated pytest collection failed because `SpatialImageSpan` did not exist.
- C1 WIP green: `/home/anhtuan/content-production-os/.venv/bin/python -m pytest --confcutdir=tests/unit/r2/advanced_creative tests/unit/r2/advanced_creative -q` → **62 passed**. The `--confcutdir` limit is material: normal root `tests/conftest.py` import fails on missing `opentelemetry.exporter` in the available root venv, so this is not the required full test gate.
- `/home/anhtuan/content-production-os/.venv/bin/ruff check` on the first source-span revision → passed; `python scripts/audit_tests.py --check` → 0 violations. Re-run both after the plural-span edit and any later changes.
- Latest C1 WIP: affected-domain isolated pytest → **78 passed** after source-ref preservation, two-view shared-anchor span merge, malformed seam rejection and server-stamped wall detail; targeted Ruff → passed. Before the final wall-detail edit, test audit → 0 violations, targeted `basedpyright` → 0 errors/0 warnings, Ruff format check → passed, and one donor fixture had eight selected semantic fields at parity. Re-run audit/type/format and any differential after further edits. These do not replace the blocked normal root pytest gate.
- `UV_CACHE_DIR=/tmp/uv-m8c-cache uv run --offline ...` failed because the needed `claude-agent-sdk==0.2.139` wheel is absent from that cache. This is an environment limitation, not a test pass.
- Claude Code implementation attempt failed before changes with API/DNS `EAI_AGAIN`; no Claude implementation or tests were produced.
- Design docs passed `git diff --check` and local relative-link checks before the later handoff edit. No backend DB, donor full suite, provider call, frontend check or independent re-review passed.

## Exact resume sequence

1. Recheck both worktree HEADs/status and preserve the M8-C untracked stop receipt and C1 WIP. Verify the donor pin/hash and do not re-import its package through unavailable dependencies; the AST fixture probe is recorded research only.
2. Complete the C1 design mapping from donor wall/joins/gaps and enriched object-level spans into `SpatialPayload`. The plural `SpatialImageSpan` contract WIP preserves old JSON bytes but is not independently accepted. Add validated model-response schema, actual M7 execution/source custody, complete donor same-fixture differential and malformed/partial cases; run relevant checks with a complete environment before C1 commit/review.
3. Resolve design gate 1 for ADR-0102: a real Take target-registration fixture with two successive admitted screenplay versions to prove registry-owned versioning; two videos approved through Gate C and their immutable derived frame objects; full canonical byte/digest vectors; exact spatial V2 models, migration/sidecar constraints; transaction-consistent legacy projection; and route/task/submit contract checked against live M7 attempt guard. Amend the M8 execution contract only after this design is independently reviewed. Keep ADR `proposed` until then.
4. Implement and independently accept target/binding authority and live consumer before C2 promotion. Then complete C2 preview/authorization/atomic promotion, C3 donor parity with zero required skips/unknowns, affected-domain tests and independent full-diff review on exact integrated HEAD. M8-D stays gated on full M8-C acceptance.

Do not describe historical tests, the author design response, candidate-only work, or the C1 WIP as M8-C acceptance. No source or destination branch was pushed or merged in this checkpoint.
