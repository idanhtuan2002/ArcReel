---
status: accepted
---

# A new run takes over an unfinished story

Decided 2026-11-11 by the main agent (sponsor: tasks stop abruptly — errors, power loss, a user's shutdown, a mistaken Cancel — and finished work must not be lost; fully automatic). Research: [interruptions and a mistaken cancel](../research/2026-11-11-r2-interruptions-and-mistaken-cancel.md).

Before: a cancelled or failed production run left its story run with its finished chapters, and nothing ever used them again; the next run drafted a new brief, a new Gate A decision and a new story run.

1. **What is taken over.** When a production run's BRIEF would write the same story as the project's newest story run — the same short story (same idea), the same first part of the same book (same idea, same length), or the book's next part — and that story run stopped unfinished (running with an ended task, blocked on budget, quality or propagation, or with its model unavailable) and every automatic run that submitted it has ended (cancelled, failed or succeeded), and the story is one this run could have written itself — the run's writer route, a free route, the project's current content safety level — the new run takes it over. A paid story never spends past its approved cap without a Showrunner. A story run a Showrunner started by hand, a variant, a story whose task is still queued or running, or one whose run may still act, is never taken over.
2. **How.** BRIEF greenlights that story run's own brief under the new run's grant and pins which story run it adopted; the STORY step reserves what the story still needs (up to its structural bound, always within the run's remaining caps), records the new run's command receipt for the story task, writes into the story state exactly the limits it reserved on top of what the story has spent and a baseline of that usage, and only then queues the task again; a replayed step queues the task again if it had finished. The story continues from its checkpoint; finished plans, scenes and reviews are kept; the step settles only what is spent from the baseline.
3. **The task follows its newest run.** The execution guard checks only the newest automatic-run receipt of a task (by time, then command id): a story handed over to a later run is authorized by that run's current grant, and the ended run no longer decides. Only the STORY owner, under the new run's verified grant and only for a story whose runs have all ended, adds such a receipt.
4. **Cancel asks once more** (with the research): Cancel sits apart from Pause and Resume and asks for confirmation pointing to Pause; with this ADR a mistaken cancel costs only the next run's start.

Not adopted: an undo window on a cancelled run (a new run state; taking over already makes a cancel recoverable); taking over a story whose run is only blocked (one project has one active run, and the blocked run's own Resume continues it).

A step after a top-up or a take-over names its story as `story-…#top-up-n`; every owner reads the story run from the part before `#` (the commit owner did not, and a topped-up story could not be committed: fixed with this ADR).
