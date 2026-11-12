---
status: accepted
---

# The autopilot alerts outside the app, and the report shows what each stage cost

Decided 2026-11-13 by the main agent under the sponsor's instruction to do the re-audit's work items. Research: [workflow re-audit](../research/2026-11-13-r2-workflow-stage-reaudit.md) A7.

A halted autopilot waits for the Showrunner under "Needs you" ([ADR-0124](0124-projects-run-on-autopilot-under-a-standing-delegation.md)), but nobody is told: the 2026-11-12 power loss and every blocked run so far were found by looking. The run report showed reviews and story exceptions, not where the time and money went.

1. **One host webhook.** `ARCREEL_ALERT_WEBHOOK_URL` (unset: no alerts) receives a short Vietnamese message when a project's autopilot halts (run, reason), when a delegated start is refused (reason), and when it has nothing left to write or film. `ARCREEL_ALERT_WEBHOOK_FORMAT=text` (default) posts the message as the plain-text body (ntfy); `json` posts `{"text", "content", "project", "event", "run_id", "reason"}` (Slack, Discord, Telegram `sendMessage?chat_id=…`). Secrets stay in the URL the host sets; nothing about the project leaves the host except its name, run id and reason code.
2. **Once per change.** The scheduler sends a project's state only when it differs from the last one sent (event, run, reason); a running or waiting project clears it, so the next halt is new; a project ready to start keeps it, so a start refused again every scan is sent once. The memory is per process: after a restart a standing halt is sent once more, which is how a power loss gets reported. A send that fails is logged and never stops the scan.
3. **Stage costs in the run report.** `GET …/production-runs/{run_id}/report` gains `stages`: per stage in run order, its steps, model calls, tasks, seconds of work and cost in the policy currency's minor units, read from the run's budget allocations (settled usage, or the reservation of a step still open, counted in `open_steps`).

Not done here: showing `stages` in the run panel (the API carries it), alerts per story run outside the autopilot, and e-mail.
