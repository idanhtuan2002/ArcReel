# M8-C authority checkpoint — 2026-09-30

Status: `M8_C2_PROMOTION_STOPPED / AUTHORITY_DESIGN_PROPOSED`.

## Live Git state at this checkpoint

- M8-B implementation acceptance: `774952b235aa899c0125ee2109d426e9bc6dc9ff`, clean `impl/r2-m8b-creative-canvas` worktree. Its acceptance artifact records independent review of `488a183a` with `M8_B_ACCEPTED` and zero blocking findings; its benchmark still has a recorded strict FAIL and a sponsor-clarified PASS.
- M8-C implementation worktree: `.worktrees/r2-m8c`, branch `impl/r2-m8c-spatial-candidates`, HEAD `774952b235aa899c0125ee2109d426e9bc6dc9ff`. Its only intended dirty path is uncommitted `docs/r2/evidence/R2_M8_STOP.json`, the contract stop receipt for C2 promotion. No M8-C code or test was changed.
- Authority design worktree: `.worktrees/r2-m8c-binding-design`, branch `design/r2-m8c-binding-authority`, research/ADR checkpoint `8fa544b4` based on `r2-v2/main` `8d4328d6`. The design worktree contains no product code changes. The parent checkout's unrelated M12/document edits were left untouched.

## Proven findings

- ADR-0095 and execution-contract amendment 2 require an independently accepted persistent `ProductionBinding` authority with an atomic CAS writer **for the M8-C promotion step**. Candidate validation and append remain possible without it.
- At the checked M8-B and V2-main trees, `ProductionBinding` is a contract and fixture/in-memory value. M8 preview refuses `PRODUCTION_BINDING`; there is no accepted persistent writer in the bounded inspected source. Graph generation `2026-09-27T03:07:32Z` indexes the root checkout and excludes `.worktrees`, so M8 code conclusions were checked directly in those trees.
- The pinned DramaClaw source is `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`, `scene_spatial_contract.py` SHA-256 `975e634cdd99500be5e29901da4930db14d5b81b1d14e6616e7e2e71081f1c92`. Source inspection was performed; donor tests and runtime parity were not run.
- The current binding body has no spatial topology fields. A binding store by itself cannot represent seam/direction/gap evidence. The inspected global asset repository is mutable and lacks approval/digest custody. These are separate design gaps, documented in the research and proposed ADR.

## Reviewable artifacts and decision

- `docs/research/2026-09-30-r2-m8c-production-binding-authority.md`: source-grounded facts and limits.
- `docs/adr/0102-production-binding-is-a-versioned-production-authority.md`: **proposed**, not accepted. It recommends an immutable typed spatial constraint set linked through a versioned `ProductionBinding`; a narrower candidate-only scope is the alternative and would require an explicit roadmap change.
- The sponsor has been asked to choose the spatial representation direction. No implementation plan or authority code is authorized by this checkpoint. Do not report M8-C accepted or start M8-D.

## Resume sequence

1. Read the sponsor answer and re-check both live worktrees, exact HEADs and dirty paths. Preserve the uncommitted M8-C stop receipt and unrelated work.
2. Resolve the spatial representation and asset/source custody questions against actual readers. Revise ADR-0102, write the design spec, and obtain independent review/acceptance of the authority decision and implementation.
3. If the full-promotion direction is accepted, implement and independently accept the ProductionBinding authority before resuming M8-C C2. C1 pure normalizers may proceed in the isolated M8-C tree after a fixed donor fixture/test inventory; C1 cannot be called M8-C acceptance.
4. Reseal M8-C donor parity on the exact integrated HEAD. Only its independent acceptance releases M8-D under the execution contract.

## Verification and limits

The M8-C stop receipt passed `python -m json.tool`. The proposed research/ADR passed `git diff --cached --check`, and all their relative Markdown file links resolved. No backend, frontend, database, donor or provider test was run for this documentation/checkpoint work; no production side effect occurred.
