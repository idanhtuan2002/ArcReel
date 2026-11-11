---
status: accepted
---

# Work survives restarts and deploys

Decided 2026-11-11 by the main agent (sponsor: abrupt stops will happen; runs stay fully automatic). Research: [interruptions and a mistaken cancel](../research/2026-11-11-r2-interruptions-and-mistaken-cancel.md). With [ADR-0129](0129-a-new-run-takes-over-an-unfinished-story.md).

1. **A deploy sets unfinished tasks aside for its backup only.** With the app stopped, the deploy script parks every queued, running or cancelling task (status `parked`, its old status kept in the payload) just before the offline backup, whose fence stays as strict as before (`parked` is not an active status), and gives them back right after it, while the app is still stopped; the new app's restart recovery then treats a task that was running exactly as after any stop (a story continues from its checkpoint, a video resumes from its job id). The script runs with `set -E` and gives tasks back from its ERR, INT and TERM traps too, so no failure leaves tasks parked. The step is plain SQL (`park_tasks_sql.py` beside the deploy script) so it works with any release's code; `scripts/r2/park_tasks.py` does the same by hand. A backup holds its tasks parked: restoring it means running `unpark` before the app starts (the worker of a release with this ADR also gives parked tasks back when it starts, and never stops on a failure to do so).
2. **A media task lost to a restart is queued once more on a free route.** An image, audio or single text task an automatic run submitted on a local, unpaid route, left running by a restart, is queued again once instead of failing, so the run goes on without a person, provided the task's own provider is the run's free route for that role; story runs keep their own recovery. Paid routes, tasks a person queued and a second restart keep the no-resend rule (no charge is ever repeated).
3. **A rename survives power loss.** Atomic writes and blob pins fsync their directory after the rename or link.

Not adopted: a cooperative drain inside the running app (it needs a signal path into every worker and still loses the in-flight call; parking after the stop loses nothing more and needs no app change at stop time); loosening the backup fence.

Still open: a real power-loss drill on the disposable environment (M10 condition C2) and a UPS for the production host.
