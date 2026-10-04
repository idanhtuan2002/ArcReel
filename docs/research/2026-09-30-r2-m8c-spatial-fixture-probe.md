# M8-C donor spatial normalization fixture probe

## Evidence point and method

DramaClaw source: local commit `b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83`, `src/novelvideo/director_world/scene_spatial_contract.py`, SHA-256 `975e634cdd99500be5e29901da4930db14d5b81b1d14e6616e7e2e71081f1c92`. This is a source-level Python execution of the donor's actual helper and normalizer AST nodes, not a provider call or full donor pipeline. Direct package import was blocked by missing `python-dotenv` in the local interpreter; no dependency was installed.

The fixture supplied:

- front `must_preserve`: `red fire extinguisher cabinet`, type `cabinet`, source view `master`, size `large`;
- back `must_preserve`: `blue exit door`, type `door`, source view `reverse`, size `large`;
- a `left_side_join` overlap pair containing the cabinet and `plain wall surface`;
- a duplicate warning naming the cabinet.

Executed donor `apply_overlap_analysis` and then `add_direction_exclusion_locks` on that input. Observed:

| Field | Donor result |
| --- | --- |
| left shared overlap | cabinet appears once |
| front preservation | cabinet removed |
| left join `merge_once` / `do_not_duplicate` | cabinet |
| left join `continue_smoothly` | plain wall surface |
| direction locks | back exit door only |

This establishes a useful same-fixture order dependency: the shared side anchor leaves front preservation before direction-lock synthesis, so R2 should not fabricate a front-center direction lock for it. It does not establish a complete donor parity verdict or R2 behavior.

## Source-span difference

The donor prompt explicitly says to omit bbox and original-image coordinates (`scene_spatial_contract.py:274-277`). The accepted M8 spec §8 requires visible source spans. The existing R2 `SpatialAssertion` contract has `source_refs` but no span (`r2/contracts/advanced_creative.py:275-283`). Therefore direct donor JSON cannot satisfy the M8 visible-assertion rule. The R2 packet must request an object-level source rectangle on an exact image, reject missing or invalid rectangles, and record this as an intentional donor correction with a failing donor fixture and a passing R2 regression fixture. A generic source view or crop name cannot substitute for the object-level span.

## Limits and next parity work

Only one in-memory fixture and two donor functions ran. No R2 normalizer, donor test suite, model call, provider request, database path or media byte proof ran. The full R2-DEC-031 parity gate still needs a fixed fixture corpus, behavioral rows, quality/resource dimensions, exact integrated HEAD and independent review. This probe is research evidence for C1 test design, not C1 acceptance.

## Follow-up differential — 2026-10-04

The C1 worktree's pinned donor script now compares the complete topology recursively, excluding R2-only `source_spans`. Four fixtures match. A fifth fixture starts with `plain wall surface` in left `shared_overlap` and also names that surface in the overlap pair. Both donor and R2 remove it from the unique-anchor list and retain `plain wall surface` in `left_side_join.continue_smoothly`. The sole non-span difference is that donor `_clean_shared_overlap` additionally writes a free-text `left.inferred_fill` instruction; R2 omits that instruction. This was verified by full-object comparison against the pinned source, not inferred from selected names.

The accepted M8 §8 contract requires confidence for inferred assertions. The donor sentence provides no confidence or typed relation, while the structured seam continuation already retains its content. The proposed R2 mapping is to retain the structured continuation and omit **only this exact redundant free-text sentence**; any other donor difference remains a `DIFF`. The differential script checks that removing precisely this sentence makes the complete non-span topology equal, and mutation probes confirmed that changing the seam continuation or a direction-lock body fails this check. It labels the row `PROPOSED_MAPPING` and still exits nonzero, so it does not grant donor-parity acceptance.

This mapping remains proposed. A valid two-view object-span fixture now passes through `normalize_spatial_candidate`: its serialized seam lock retains `plain wall surface` under `continue_smoothly`, and its only inferred assertion is the separate typed corridor inference. The affected unit domain passed **86 tests** under isolated SQLite; test audit, targeted Ruff check/format and basedpyright (**0 errors, 0 warnings**) passed. Preview and exact-diff review remain untested. Malformed/partial donor behavior, M7 execution and the broader C3 gate remain open.
