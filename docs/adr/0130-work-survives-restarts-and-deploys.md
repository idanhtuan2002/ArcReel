---
status: accepted
---

# Work survives restarts and deploys

Decided 2026-11-11 by the main agent (sponsor: abrupt stops will happen; runs stay fully automatic). Research: [interruptions and a mistaken cancel](../research/2026-11-11-r2-interruptions-and-mistaken-cancel.md). With [ADR-0129](0129-a-new-run-takes-over-an-unfinished-story.md).

1. **A deploy sets unfinished tasks aside.** With the app stopped, the deploy script parks every queued, running or cancelling task (status `parked`, its old status kept in the payload) before the offline backup, whose fence stays as strict as before (`parked` is not an active status). The application gives parked tasks back when its worker starts, before restart recovery, so a task that was running is recovered exactly as after a crash: a story continues from its checkpoint, a video resumes from its job id. If the deploy fails, its error handler gives them back to the old release. The script step is plain SQL (`park_tasks_sql.py` beside the deploy script) so it works with any release's code; `scripts/r2/park_tasks.py` does the same by hand.
2. **A media task lost to a restart is queued once more on a free route.** An image, audio or single text task an automatic run submitted on a local, unpaid route, left running by a restart, is queued again once instead of failing, so the run goes on without a person. Paid routes, tasks a person queued and a second restart keep the no-resend rule (no charge is ever repeated).
3. **A rename survives power loss.** Atomic writes and blob pins fsync their directory after the rename or link.

Not adopted: a cooperative drain inside the running app (it needs a signal path into every worker and still loses the in-flight call; parking after the stop loses nothing more and needs no app change at stop time); loosening the backup fence.

Still open: a real power-loss drill on the disposable environment (M10 condition C2) and a UPS for the production host.
