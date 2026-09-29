---
status: accepted
---

# The host Agent runs in release mode behind a per-connection budget reservation and a CLI hard cap

This ADR supersedes ADR-0091 amendment item 5 for the Agent route only. Trial runs stay
unqualifiable. The research is `docs/research/2026-09-29-r2-v1x-agent-session-budget.md`, and the
sponsor delegated the choice.

**Qualification.**

- **Which routes qualify.** In `PRODUCTION_CANDIDATE`, the Agent route qualifies only when the
  active Agent credential uses the `anthropic-official` preset with no model override or a
  `claude-*` model. Only those models are priced by the CLI's own table, which the budget cap
  relies on. Every other preset stays refused until an operator price table exists.
- **Binding.** The qualification binds the preset, base URL, API key (by digest) and model.
- **Canary.** It is one Agent query with a tiny cap. It must end with `error_max_budget_usd` and
  a reported cost, which proves on the live route that the cap is enforced and cost is reported.

**Budget before submit, per connection.**

1. **Before each CLI process starts** (a new or resumed session), the host reserves and claims
   `ARCREEL_AGENT_SESSION_BUDGET_USD` (default 1.00) in the `…:USD` budget scope. A missing scope
   or no room refuses the session.
2. **The process starts** with `max_budget_usd` equal to the reservation.
3. **When the managed session ends**, the reservation reconciles to the increases booked from the
   process's cumulative totals, which may slightly exceed it.
   - A failed reconciliation keeps the reference: the session retries it at its next settlement
     point, and a dropped session hands it to the patrol, which retries it until it succeeds.
   - At host startup no Agent process is alive, so every claimed `agent_session:` hold is
     committed at its full reserved amount, the process's hard cap.
4. **Restored totals on resume.** The CLI restores a session's final cost and usage on resume only
   when the session is the `lastSessionId` in its global config. The host reads that file before
   the process starts and applies the same rule:
   - **Restored:** booking starts from the restored totals, so they are not booked again.
   - **Not restored:** booking starts from zero.

   The cap compares against the restored ledger, so a long conversation reaches the cap sooner.
   This is the safe direction: continue in a new conversation, or raise the setting.
5. **At the cap, the connection closes.** When a turn ends with `error_max_budget_usd`, the host
   closes the connection at once and settles it. The next message opens a new connection with a
   new reservation.

**No resend after an ambiguous outcome.** In release mode the CLI runs with
`CLAUDE_CODE_MAX_RETRIES=0`.

## Consequences

- **Release mode.** Story and script writing with the Agent is available on the Anthropic route,
  with a hard spend ceiling per session connection. When the ceiling is reached, the operator
  continues in a new connection, which takes a new reservation.
- **Accounting.** Agent usage is booked as the per-result increase of the CLI's process totals
  (`a2cc69b9`), in DEV too.
- **Known limits:**
  - **Overshoot per stop** is bounded by in-flight calls.
  - **Spend after the last result** of a crashed process is not booked.
  - **Config races.** A graceful exit of another session in the same project, between the host's
    read of the CLI config and the CLI's own read, can change the restore outcome. If the CLI
    then restores nothing, the first result's total is smaller than the baseline, and the host
    books it from zero. The case this does not catch undercounts by at most one connection's
    spend.
  - **One host process.** The startup sweep assumes that one host process owns every Agent
    session.
  - **Non-Claude presets stay refused** in release mode.
