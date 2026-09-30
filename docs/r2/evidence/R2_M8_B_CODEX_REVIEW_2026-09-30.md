# M8-B Creative Canvas — Codex independent review

Reviewer: Codex (read-only, codex companion runtime), under the amendment 12 stopping rule. Branch `impl/r2-m8b-creative-canvas`; executor base `d8d74299` (amendment 14).

| Round | Reviewed head | Job | Verdict |
|---|---|---|---|
| 1 | `9c7007da` | `task-mun7ujjy-kfksdx` | `{"status":"M8_B_NOT_ACCEPTED","head":"9c7007da","blocking_findings":5}` |
| 2 | `1e8f4bb3` | `task-mun91tvz-rnyoie` | `{"status": "M8_B_NOT_ACCEPTED", "head": "1e8f4bb3", "blocking_findings": 2, "open_conditions": ["Sponsor decision on status_strict FAIL versus status_clarified PASS"]}` |
| 3 | `326a52ad` | `task-muna1e6t-wu6agv` | `{"status":"M8_B_NOT_ACCEPTED","head":"326a52ad","blocking_findings":3,"open_conditions":["Sponsor decision on benchmark strict verdict"]}` |
| 4 | `86311a0e` | `task-munfwn4i-7p4a7x` | `{"status":"M8_B_NOT_ACCEPTED","head":"86311a0e","blocking_findings":3,"open_conditions":["Sponsor decision on the benchmark strict verdict"]}` |
| 5 | `217d2f64` | `task-munh2127-h0bbpg` | `{"status":"M8_B_NOT_ACCEPTED","head":"217d2f64","blocking_findings":3,"open_conditions":["Preserve an unkept local graph across close/reopen when storage writes fail, or prevent close from discarding it","Preserve the first selected mine version when a waiting draft cannot move to the kept-aside slot","Keep conflict protection until a requested server reload succeeds"]}` |
| 6 | `96910737` | `task-muni38e1-85nhyn` | `{"status":"M8_B_NOT_ACCEPTED","head":"96910737","blocking_findings":2,"open_conditions":["Guard reload results against a conflict choice or later graph change.","Keep the unload guard active while any in-memory version or unsaved selected graph lacks durable storage."]}` |
| 7 | `04f503b8` | `task-muniqz0e-8dfnx9` | `{"status":"M8_B_NOT_ACCEPTED","head":"04f503b8","blocking_findings":1,"open_conditions":["Guard the chosen graph from the moment a mine choice removes its kept-aside copy until a durable draft or server save exists."]}` |
| 8 | `488a183a` | `task-munjlf4i-wsfpay` | `{"status":"M8_B_ACCEPTED","head":"488a183a","blocking_findings":0,"open_conditions":["Fresh before/after Vitest execution was unavailable in the read-only environment; the baseline failures are established from test assertions and source behavior, while the fixed-head pass is reported in parity evidence."]}` |

## Findings by round (summary)

- Round 1 (5 blocking): kept-aside snapshot not restored on reopen; cross-canvas 409 race; in-flight save clearing a newer draft; resources evidence from observation size; benchmark strict FAIL pending the sponsor.
- Round 2 (2): stacked conflict 'mine' overwriting a newer draft; marginal heap resolving to about 0.
- Round 3 (3): edits during a stacked conflict; failed slot transfer clearing the waiting draft; resources by entry count.
- Round 4 (3): pending field typing missing from the kept copy; both storage writes failing on a 409; stacked 'mine' then 'server' leaving the first unsaved.
- Round 5 (3): unkept graph across close/reopen; first 'mine' behind an unmovable draft; 'load latest' clearing the conflict before the reload. Benchmark condition closed by the sponsor decision (r2-v2/main `b6b54b9b`). The conflict model was redesigned as an ordered kept-aside queue.
- Round 6 (2): overlapping reloads erasing 'mine'; page-scoped unload guard.
- Round 7 (1): the 300 ms interval between settling a kept-aside copy and drafting the chosen graph.
- Round 8: accepted, 0 blocking.

## Round 8 output (verbatim)

**Verdict: the round-7 blocker is fixed on the reviewed “mine” path.** At `488a183a`, the [settle method](/home/anhtuan/content-production-os/.worktrees/r2-m8b/frontend/src/features/creative-canvas/sync/canvasPersistence.ts:292) applies the chosen version, calls `writeDraftNow`, then removes its kept-aside copy. [Draft writing](/home/anhtuan/content-production-os/.worktrees/r2-m8b/frontend/src/features/creative-canvas/sync/canvasPersistence.ts:379) sets the unload guard when storage refuses the write. This also covers a “mine” choice made while other versions remain queued. I found no concrete regression or remaining silent-loss path in the reviewed change.

The two changed [tests](/home/anhtuan/content-production-os/.worktrees/r2-m8b/frontend/src/features/creative-canvas/sync/canvasPersistence.test.ts:778) check the guard and draft **before** the 300 ms timer fires. Their assertions fail by inspection against `04f503b8` and match `c71c6e6f`; I could not independently run either revision. Vitest stopped at startup because this read-only filesystem prevented Vite from creating its temporary config file. The [parity report](/home/anhtuan/content-production-os/.worktrees/r2-m8b/docs/r2/evidence/R2_M8_B_CANVAS_PARITY.json:908) records a passing frontend check and 9 browser tests at `c71c6e6f`; those are reported results, not fresh runs from this review.

**Benchmark:** the retained `42085be3` result really fails the clarified threshold: 100-node drag p95 is 33.3 ms. The [latest result](/home/anhtuan/content-production-os/.worktrees/r2-m8b/docs/r2/evidence/R2_M8_B_CANVAS_BENCHMARK_RESULT.json:1) passes the clarified verdict on unchanged app code. The abnormal frame counts and 33.3 ms idle maximum in the failed run support environmental interference as an *inference*, but do not prove its cause. With a passing rerun and no benchmark-specific code defect established, I record the failed run as a nonblocking variability concern. The strict verdict remains FAIL under the recorded clarification.

{"status":"M8_B_ACCEPTED","head":"488a183a","blocking_findings":0,"open_conditions":["Fresh before/after Vitest execution was unavailable in the read-only environment; the baseline failures are established from test assertions and source behavior, while the fixed-head pass is reported in parity evidence."]}
