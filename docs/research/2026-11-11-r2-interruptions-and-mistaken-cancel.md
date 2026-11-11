# Interruptions and a mistaken cancel: what survives today and what to add

Date 2026-11-11. Question (sponsor): tasks stop abruptly — errors, power loss, a user shutting the app down, a
deploy — and the run's Cancel button is easy to hit by mistake. What happens in each case, and what should change so
that no finished work is lost and runs stay fully automatic? Code at `impl/autonomous-production` `2e1609d15`;
production evidence from 2026-11-11 (the `r2-v2.5.8` deploy refused by the backup fence while a story task ran).

## 1. What happens today (facts, cited)

| Event | Story run (writing) | Production run | Media tasks of a film run | Files and database |
|---|---|---|---|---|
| Crash, power loss, `kill -9`, app stopped mid-task | On restart the orphaned `running` story task is requeued (`lib/generation_worker.py` story branch, `requeue_story_run`); `recover_run` reconciles the attempt ledger: an in-flight call becomes "outcome unknown" and is charged at its reservation, never silently resent; finished plans, scenes and reviews are kept (`server/story_authoring/runtime.py:871`). At most the scene being written is redone. | Its lease (`claim_due`, 120 s) expires and the controller claims it again. | Orphaned image, audio and single text tasks are marked failed `restart_lost_*` on purpose, to avoid paying twice (`lib/generation_worker.py`, image/audio/text branches); video with a job id resumes. The run then stops on the failed task. | PostgreSQL commits are durable (WAL). Blobs are written to a temp file, fsynced and renamed (`lib/json_io.py:72-110`), so a file is never half-written; the directory is not fsynced, so a file renamed just before power loss can vanish; reconcile then regenerates that node. |
| Deploy while a task runs | The stop script kills the app; the task stays `running` in the database. | Same as a crash. | Same as a crash. | The offline backup refuses: `OFFLINE_FENCE_VIOLATED … task(s) are queued, running or cancelling` (`r2/host_hardening/deployment_backup.py:416`), so the deploy stops before switching code. There is no way to park work for a deploy. |
| User presses Cancel on a production run | The run becomes `CANCELLED` (terminal, `server/production_run/service.py:604-609`); the execution guard refuses the story task before its next model call (`server/production_run/execution_guard.py:1-6`). The story run's state and drafts stay on disk, but nothing ever uses them again: a new run drafts a new brief, a new Gate A decision and therefore a new story run (`run_id_for`). | Terminal; no undo. | Refused by the guard. | Kept but orphaned. |
| User presses Cancel by mistake | Same as above: hours of writing are unrecoverable. The button sits next to Pause/Resume with the same style and acts on one click (`frontend/src/features/production-run/ui/ProductionRunPanel.tsx:632-642`). The story page's Discard asks for a second click (`StoryAuthoringPage.tsx:898`). | | | |

Donor note: shenbi keeps the memory of finished steps when a run resumes after an interruption (`15202d0`, cited in
`2026-11-11-r2-donor-failure-modes.md`); neither donor offers an undo for a cancelled run.

## 2. Gaps

1. **Finished work can be orphaned.** A cancelled, failed or abandoned production run leaves a story run whose
   chapters nobody resumes. This is the root of both "mistaken cancel" and "lost hours after an interruption".
2. **No clean pause for maintenance.** A deploy must either wait for every task to finish or kill one.
3. **Media tasks lost to a restart stop a fully automatic run.** The no-double-charge rule is right for paid routes,
   but on a free local route a retry costs nothing.
4. **A just-written file can vanish on power loss** (no directory fsync).
5. **Cancel is one click, next to Pause.**
6. **Never exercised:** no real power-loss drill (M10 condition C2 still open).

## 3. Options and recommendation

**A. Work is never lost: a new run adopts the unfinished story (recommended, core).** When a production run starts
(or the autopilot starts the next attempt) for a project whose same book part, or the same short story, has an
unfinished story run (any phase but committed or discarded) left by an earlier run, the new run takes that story run
over instead of drafting a new one: it re-binds the story task to itself under its own grant (the task's command
receipt names the adopting run, so the execution guard accepts it), tops it up if it stopped on budget, and lets it
continue from its checkpoint. Covers a mistaken cancel, a failed run, an abandoned run and a crash. Touches the
authority boundary (task re-binding), so it needs careful tests and an independent review.

**B. Cancel is hard to hit and easy to take back.** Move Cancel away from Pause/Resume into a separated danger
place, style it as destructive, require a confirmation that says what is lost and what is kept, and offer Pause as
the reversible alternative. With A, a mistaken cancel only costs the next run's start, because the story is adopted.
(Rejected: a timed "undo" window on the server — it adds a state to the run machine, and A already makes a cancel
recoverable.)

**C. A maintenance drain for deploys.** The stop script asks the app to drain: stop claiming work, let each story
task finish its current model call and park (a `parked` task status outside the active set), then exit; on start,
parked tasks are queued again. The backup fence stays as strict as it is. Needs a change to the stop/start scripts
(run by the Human) and to the task status set.

**D. Free media retries after a restart.** A media task lost to a restart on a free local route is queued once more
automatically; paid routes keep the no-resend rule.

**E. Directory fsync** after every atomic rename (blob store, pins, `atomic_write_bytes`).

**F. A power-loss drill** on the disposable environment: kill the app with `-9` during a story scene and during a
media task, restart, and check the story converges to the same manifest with no lost node and the run continues.

**G. Hardware:** a UPS with automatic clean shutdown — the only way to avoid losing the in-flight call itself.

Order: B and E now (small, safe); A next (largest gain, needs review); D; C (needs the Human to change the
production scripts); F after A–E; G is the sponsor's purchase.

## 4. The current production case

The `minh-co-so-thich-dac-bie-55335b61` part-1 story run (chapters 1–4 written with the protagonist's gender wrong,
from before ADR-0126) blocks the `r2-v2.5.8` backup while its task is `running`. Without C, the choices are: wait for
chapter 5, or discard that story run (its four chapters are lost; part 1 is rewritten with the fixes of
ADR-0126–0128). With A in place, a discarded or cancelled part would no longer be the only way out.
