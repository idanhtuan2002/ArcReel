# R2 V1.x — admitting the host Agent in release mode (2026-09-29)

**Question.** How can the host creation Agent (Claude Agent SDK) run in `PRODUCTION_CANDIDATE`
under ADR-0091 invariants 1 and 2 (budget before submit; no resend after an ambiguous outcome)?
ADR-0091 amendment item 5 refused the Agent in release mode because its spend is booked after the
fact. It also said "A per-session reservation design would lift this."

**Sponsor wish.** Story and script writing with the Agent (2026-09-29).

## Facts

Unless marked otherwise, the facts come from `claude_agent_sdk` 0.2.139 and its bundled CLI.

1. **The SDK's `ClaudeAgentOptions.max_budget_usd`** becomes `--max-budget-usd` (`subprocess_cli.py:603`).
   - The CLI stops the query and returns a result with subtype `error_max_budget_usd`.
   - The CLI help says the flag "only works with --print". The SDK runs the CLI headless with
     `--input-format stream-json --output-format stream-json`.
   - The same class of option, `max_turns`, already works in ArcReel. This is an **inference**,
     and the canary (decision 4) proves it live.
2. **The budget check is cumulative per CLI process.**
   - The CLI compares `KA() >= maxBudgetUsd`, where `KA()` is the process cost ledger. Its
     message reads "$X spent of the $Y maximum".
   - It checks before launching sub-agents and after each step. Overshoot is bounded by the
     calls already in flight.
3. **`total_cost_usd`, `usage` and `modelUsage` are process totals** (`total_cost_usd:KA()`,
   `usage:this.totalUsage`).
   - ArcReel's `SessionManager` keeps one CLI process per managed session across turns
     (`client.query` on one client).
   - So `_record_assistant_usage` counted earlier turns again on every later turn. This was a
     real V1 defect, fixed in `a2cc69b9` by booking each result's increase.
   - Upstream (`317a7d0d`) has the same code.
4. **Resume can restore cost.** On resume, the CLI restores `lastCost` and `lastModelUsage` from
   its project config when `lastSessionId` equals the resumed ID (`Xha`/`gJo` on the resume
   path). A resumed process may therefore start its cost ledger above zero.
5. **The CLI prices by its own model table.** For other models it notes "costs may be inaccurate
   due to usage of unknown models".
   - The Agent presets in `lib/agent_provider_catalog.py` are mostly non-Claude models:
     `arcreel`/gpt-5.5, GLM, MiMo, DeepSeek, MiniMax, Kimi, Doubao.
   - Only `anthropic-official` with a Claude model is priced by the CLI's table.
6. **The CLI retries API calls by default** on 408, 409, 429, ≥500 and overloaded errors.
   `CLAUDE_CODE_MAX_RETRIES` sets the count, and `0` disables retries.
7. **The budget repository** (`BudgetReservationRepository`) reserves, claims and reconciles.
   `reconcile` accepts an actual cost above the reserved amount, and it is committed in full.

## Options

| Option | Assessment |
|---|---|
| **A1: per-connection reservation with a CLI hard cap.** In release mode, before a session's CLI process starts, reserve R (the operator setting `ARCREEL_AGENT_SESSION_BUDGET_USD`, default 1.00 USD). Start the process with `max_budget_usd = R` and `CLAUDE_CODE_MAX_RETRIES=0`. When the session ends, reconcile the booked increases. Only a CLI-priced route qualifies: `anthropic-official` with no model or a `claude-*` model. | Budget before submit, and a hard stop inside a long agentic turn. It reuses the existing repository and gate. A restored resume cost (fact 4) makes the cap trip early, which is the safe direction. |
| A2: per-turn reservation without a cap | No hard stop inside a turn, where one agentic turn can run many calls. Rejected. |
| A3: host-side token metering plus an operator price table for every preset | Covers the non-Claude presets. Adds a price-table authority and stream interruption logic. Deferred as the extension path. |
| A4: keep the Agent refused (the status quo) | Fails the sponsor's need. |

## Decision (ADR-0093)

A1. Other presets stay refused in release mode until A3 exists.

## Unknowns

- **Overshoot.** The exact overshoot per stop is bounded by in-flight calls but not measured.
  Reconcile books whatever the CLI reports.
- **Unreported spend.** Spend after the last result of a crashed process is not reported, and the
  reservation commits the booked sum. This is disclosed.
