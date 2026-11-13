# R2 film-quality release candidate: independent code review (2026-11-13)

Scope: `git diff r2-v2.5.16..HEAD` on `impl/r2-film-quality`, HEAD `d9839a976` (ADR-0133..0139, A9, A11). I read the
code changes, the ADRs, and the tests for the risky paths. I wrote nothing in the repo except this file.

Tests run at HEAD (targeted, PG scratch DB `film_quality_test`):
`uv run python -m pytest tests/integration/server/production_run/test_automation_settings.py tests/integration/server/production_run/test_controller_recovery.py tests/integration/server/production_run/test_story_adapter.py tests/unit/lib/test_text_generator.py tests/unit/lib/text_backends/test_route_failure.py tests/unit/server/production_run/test_alerts.py tests/unit/server/production_run/test_continuity_judge.py tests/unit/server/production_run/test_final_checks.py tests/unit/server/production_run/test_story_run_busy.py -q`
gave **111 passed**. One inline probe: `WebhookAlerts("http://[::1").send(...)` raises `httpx.InvalidURL` (httpx 0.28.1;
`InvalidURL` is not an `HTTPError`). Every other finding comes from reading the code. The existing tests do not reach these paths:
none covers a paid/cloud fallback writer, a crash between the write steps of a take-over or reroute, more than one
fallback move, or `record_launch` after a primary route changes.

## Verdict: ACCEPT_WITH_CONDITIONS

Conditions to meet before deploy: fix H1 and H2, or turn them off for production; fix H4 or stop advertising it; give
H3 a deploy step (re-pin every enabled autopilot) or a code fix. The MEDIUM findings should be fixed in this RC or
tracked explicitly.

Counts: BLOCKING 0, HIGH 4, MEDIUM 7, LOW 8.

---

## HIGH

### H1. A STORY fallback can spend up to the run's whole money cap a second time, with nothing reserved for it
- `server/production_run/story_adapter.py:535-549` (fallback `plan`: `estimated_cost_minor_units=0`),
  `:838-846` (`reroute_brief(... max_cost_minor_units=max(1, min(10_000, run.policy.max_cost_minor_units)))`),
  `:161-169` (`rerouted_limits`), `lib/db/repositories/production_runs.py` `settle_budget` (the cap is checked only
  after the step settles: `AUTHORITATIVE_USAGE_EXCEEDED_CAP`).
- The story's cap check is `prices(total tokens) <= cap` (`server/story_authoring/runtime.py:268-273, 365-373`), so
  `cap = run_max + prices_new(used)` lets the story spend at most `run_max` **from here on**. That bounds new spend by
  the run's *whole* cap, not by what the run still has left. The step reserves 0, so `reserve_budget` always passes.
- Failure scenario: a USD policy with `max_cost_minor_units=500`, local_only false, and a paid cloud writer fallback
  with a ceiling. The BRIEF draw costs 40. The STORY step on the paid primary writer settles 400, then the story stops
  `MODEL_UNAVAILABLE` (quota). STORY reworks with `STORY_MODEL_FALLBACK`; the plan reserves 0; the story is rerouted with
  `max_cost=500 + prices_F(used)`; F writes and spends up to 500 more. The run total reaches about 940 against a cap of
  500, and this is caught only after the money is spent (`AUTHORITATIVE_USAGE_EXCEEDED_CAP`). It gets worse when a
  take-over (ADR-0138) is followed by a fallback in the same run, because both grant the full run cap.
- ADR-0138 §3 ("spends at most what the run reserved") holds only for a story the run has not paid for yet; the
  fallback in ADR-0139 breaks it.
- Fix: in `plan`, compute `room_cost = run.policy.max_cost_minor_units - usage_totals.cost`. When the next fallback is
  priced, reserve `estimated_cost_minor_units = room_cost`. In `_fall_back` (and `_greenlight_adopted`), pass
  `max_cost_minor_units = min(10_000, room_cost)` and skip priced fallbacks when `room_cost < 1`. Add a test with a priced
  fallback after a priced first writer.

### H2. Text tasks of an automatic run fall back to a live settings list that the run's frozen policy never approved
- `lib/text_generator.py:68-79, 109-126`, `lib/text_backends/factory.py:147-166` (`project_text_fallbacks` reads
  `project.automation.fallbacks` with no checks), compared with `story_adapter._writer_order` (`:760-780`), which at least
  re-applies local_only, the ceiling and reviewer independence.
- Failure scenarios (each one is reachable while a run is open; ADR-0139 says edits are free mid-run):
  1. The run starts with `local_only=true` (every route local). The Showrunner then saves a cloud `script` fallback
     (allowed: it only flips the *settings* to non-local). The run's SCRIPT/EPISODE_PLAN task calls Ollama, which is
     down, raising a `ConnectError`. `TextGenerator` moves to the cloud model and spends money in a run approved as
     local-only. The spend is visible only post hoc, through ledger usage (`owner_tasks.step_usage`).
  2. The Showrunner adds one of the run's reviewer models (for example `reviewer_a`'s identity) as a `script` fallback.
     `save_settings` does not check reviewer independence for fallbacks (preflight does, but only at the *next* run
     start). A route failure on the script model now has the script written by a QUALITY reviewer, and
     `assessment.combine` gets `writer_identities` from the policy only (`r2/automation/assessment.py`), so the
     independence breach is never flagged.
  3. `max_cost_per_call` on a fallback entry is required at save time but never enforced by `TextGenerator`.
- The ADR admits (1). I do not think it is acceptable for an autopilot run: the run is the unit a policy and grant are
  approved for (the ADR says so itself), and the STORY path already shows the guard is cheap to add.
- Fix: when the generation task belongs to a run (the task has a `production-run:` command receipt, which the
  execution guard already resolves), filter the fallbacks with the same rules as `_writer_order` against that run's
  `RunPolicy`. Better still, restrict them to `policy.fallback_routes` (role `script`, same provider/model/identity) so
  only preflighted routes can write. Outside runs, keep the current behaviour. Also add a reviewer-identity check to
  `save_settings` for fallbacks (`FALLBACK_IS_REVIEWER`).

### H3. After deploy, every enabled autopilot is refused with `POLICY_MOVED`
- `server/production_run/composition.py:169`: `target_duration_seconds` comes from the project's
  `episode_target_duration` (or `None`). Before this release it was `launch.target_duration_seconds` (45).
  `r2/automation/identity.py:28-36`: `_LATER_DEFAULTS` cannot hide this field, because the old value (45) was a real
  value and not a default that the digest dropped. `server/production_run/service.py:398-401`: a delegated start
  requires `policy_digest(resolve()) == delegation.policy_digest`.
- Failure scenario: a project with autopilot ENABLED before the deploy has a delegation pinned on a digest that holds
  `target_duration_seconds: 45`. After the deploy, `resolve()` gives `None` (no project target) or 60/90 (film looks).
  The digests differ, every scan raises `POLICY_MOVED`, the project shows "refused", and with ADR-0137 configured one
  alert per project goes out. Story autopilots (the sponsor's 2026-11-10 grant) and film batches all stop until a
  Showrunner re-enables them or saves settings. Open runs are not affected, because their stored policy keeps 45.
- Fix: add a deploy step that re-pins each ENABLED delegation (the same `set_autopilot(enabled=True, …)` that
  `put_settings` does), or have the scheduler re-pin automatically when the only digest difference is the
  `target_duration_seconds` move. Write the step into the handoff/runbook. Nothing in
  `docs/r2/evidence/R2_FILM_QUALITY_HANDOFF.md` covers it today.

### H4. Saving settings never re-records a launch qualification that a route change made stale
- `server/routers/production_runs.py:224-234` calls `record_launch`, which calls `build_record`
  (`server/production_run/qualification.py:180-182`). That returns `None` unless
  `report.blocking_reasons == ONLY_MISSING == ("LAUNCH_PROFILE_NOT_QUALIFIED",)`. When a record already exists but its
  `route_digests` no longer match, preflight reports **`LAUNCH_QUALIFICATION_CHANGED`**
  (`server/production_run/preflight.py:77-90`, the `elif` branch), not `NOT_QUALIFIED`.
- Failure scenario: a project qualified on writer/script X. The Showrunner uses "Make default" to promote fallback Y
  (ADR-0139 §5), which changes `routes` and therefore `route_digests`. The save calls `record_launch`, gets
  `{"recorded": False, "reasons": ["LAUNCH_QUALIFICATION_CHANGED"]}`, and the next film run stops at preflight on
  exactly the reason ADR-0139 §4 says this removes. The manual "record launch" button fails the same way, so nothing
  in the UI can recover. ADR-0136 batch films are not affected (they have no record yet). No test covers this
  (`launch_reasons` is tested only in the batch).
- Fix: accept `blocking_reasons` in `{("LAUNCH_PROFILE_NOT_QUALIFIED",), ("LAUNCH_QUALIFICATION_CHANGED",)}` in
  `build_record` (the new record replaces the stale one; `current()` already picks the newest). Add a PG test: qualify,
  change the script route, save, and expect `launch_reasons == []` and a preflight with no blocking reason.

---

## MEDIUM

### M1. A crash in the middle of a take-over sends a `MODEL_UNAVAILABLE` story to the wrong path: the run's own writer is skipped, or the run blocks
- `server/production_run/story_adapter.py:583-587` (it chooses `_fall_back` when `_task_follows` is true),
  `lib/db/repositories/task_repo.py:1281-1327` (`hand_over_story_run` commits the receipt **and** the rerouted brief),
  `server/story_authoring/service.py:958-1010` (`adopt`: `store.apply(top_up)` comes after that commit).
- Failure scenario: the case ADR-0138 was written for. A story stopped `MODEL_UNAVAILABLE` because a free quota ran
  out; a new run on writer W takes it over. `hand_over_story_run` commits (the task now carries the brief on W, and the
  receipt says it follows this run). The process then crashes, or `adopt` refuses, before `store.apply`. On the
  resumed or replayed dispatch, `_unavailable_story_by_id` is still true (phase unchanged) and `_task_follows` is true,
  so `_fall_back` runs with `ref.brief` already on W. `_fallback_writers` returns the writers *after* W: the story moves
  to F1 without W ever being tried, or, with no fallbacks configured, the run blocks `STORY_MODEL_UNAVAILABLE`.
- Fix: make "taken over" mean that the take-over top-up is recorded (a top-up in `state.top_ups` whose `caller_ref` is
  a STORY step command of this run), not that the receipt exists. Or let `_take_over` finish a half-done adoption (its
  replay path through `adopt` already handles an existing hand-over).

### M2. `reroute()` writes the brief before the state; a crash between them skips a fallback writer or blocks the run
- `server/story_authoring/service.py:1031-1050` (`set_story_brief` commit, then `store.apply`, then requeue);
  `story_adapter.py:833-871` (`_fall_back` reads the current writer from `ref.brief`, which `_find` loads from the task
  payload, `service.py:1167-1181`).
- Failure scenario: the story fails on W and the fallback list is [F1, F2]. `_fall_back` reroutes to F1:
  `set_story_brief` commits, then the process dies before `store.apply`. On resume, `done` is `None` (no top-up), but
  `ref.brief.selection` is already F1, so `_fallback_writers` returns [F2] and the story moves to F2 without F1 ever
  writing. With a single fallback, the replay raises `STORY_MODEL_UNAVAILABLE` and the run blocks. While the window is
  open, the task payload (F1) and `RunState.limits` (W's currency and prices) also disagree. A Showrunner retry in that
  window would run F1 under W's limits. The cloud gateway refuses that case when it lacks `cloud_prices`
  (`cloud.py:276`), so no money is lost, but the story fails.
- Fix: write the top-up record and the brief in one transaction (the task row and the run state together), or compute
  the fallback order from the brief recorded in the last top-up (`limits_before` and the selection), not from the
  task payload. The comment "a worker never runs the story on the old route again" is true, but it costs the
  idempotence of the move.

### M3. A STORY fallback is a REWORK: the third move, or any move once top-ups are used, ends the run `FAILED_QUALITY/REPAIR_LIMIT`
- `story_adapter.py:626-640` returns `REWORK` with no limit check. `r2/automation/transitions.py:85-95`: when
  `counts[(STORY, "story")] >= unit_repair_limit` (≤ 2), the run goes to `FAILED_QUALITY`, a terminal status.
  `_top_up_target` (`:897-903`) does respect the limit.
- Failure scenario: writer order W, F1, F2, F3, with the default `unit_repair_limit=2`. W fails and goes to F1
  (count 1). F1 fails and goes to F2 (count 2). F2 fails, `inspect` returns REWORK again, and the run is terminally
  `FAILED_QUALITY "REPAIR_LIMIT"` instead of "the story stays stopped for the Showrunner" (ADR-0139 §2). The same
  happens after one budget top-up plus two fallbacks, and with `unit_repair_limit=0` on the very first failure. Before
  this release, the run stopped in a resumable block. The ADR's "free list of up to 32" is in practice at most 2 moves
  per run, shared with top-ups.
- Fix: in `inspect`, return the fallback REWORK only while the STORY repair count is below `unit_repair_limit`
  (otherwise fall through to the existing PASS/BLOCK path). Document the bound, or give model fallbacks their own
  counter.

### M4. `story_run_busy` can let the autopilot start a second story beside a stopped one that the new run will not take over
- `server/production_run/composition.py:435-448` uses `adoptable(matches=lambda _: True)`, while the run's own
  `_adoptable` (`story_adapter.py:319-366`) also requires an idea or book match, no variant, a non-auto idea, and the
  project's **current content safety**.
- Failure scenario: a story is left `MODEL_UNAVAILABLE` by ended automatic runs. The Showrunner then changes the
  project's content safety, or the autopilot's command idea differs from the stopped brief's idea (a story first started
  by a manual "Start" run with another idea, or `idea_mode=auto` because no drawn idea was recorded). `story_run_busy`
  returns False, so the autopilot starts a run. `_adoptable` returns None, so a **new** story is drafted while the old
  one stays unfinished. That violates the one-unfinished-story rule of ADR-0124 §3 and leaves an orphan whose canon base
  will move. Concurrent execution does not happen (the old task is finished, and `has_active` holds the planner while
  any run is non-terminal), so this is a policy breach, not a race.
- Fix: share one predicate. Have `story_run_busy` run the same matcher and content-safety check the next command
  would use (or call a `BriefAdapter`-level `would_adopt(command)`), and return busy otherwise.

### M5. `put_settings` can answer 500 after the save, and then skip the autopilot re-pin
- `server/routers/production_runs.py:228-234` catches only `QualificationRefused`. `record_launch` calls
  `ProjectPolicyResolver.resolve` and preflight, which can raise `ProductionRunRefused` (for example
  `AUTOMATION_NOT_CONFIGURED/PINNED_MODEL_UNAVAILABLE` from `composition.py:126-133`, when a primary route cannot be
  inspected), pydantic `ValidationError`, or DB errors.
- Failure scenario: a save where a route's inspection fails (an Ollama model whose digest cannot be read at inspect
  time, or a provider config changed between save and inspect). `save_settings` has already written the settings and
  `text_backend_complex`; `record_launch` raises; the request returns 500; the ADR-0127 re-pin below never runs. The
  enabled autopilot then sits on `POLICY_MOVED` (see H3), and the UI shows a failed save that actually took effect.
  The same applies to `films_for_finished_stories_route.qualify_launch` (`:590-595`): an uncaught exception there
  aborts the batch after the film was created and before its autopilot is enabled, and a rerun *skips* that story
  (its film already exists), so that film never gets its autopilot.
- Fix: in both places, catch `(QualificationRefused, *_REFUSALS, ValueError)` and report the code in `launch_reasons`.
  Never let qualification bookkeeping fail a save or a batch.

### M6. `put_settings` now writes `text_backend_complex`: a mid-run change of the script model blocks the open run
- `server/production_run/settings.py:274-281` and `server/production_run/text_adapter.py:323-330`
  (`_require_script_route` → `MODEL_CONFIG_CHANGED`).
- Failure scenario: a run is between ADAPTATION and SCRIPT. The Showrunner uses "Make default" on a script fallback
  (as the ADR's how-to suggests). The save rewrites `text_backend_complex` to the new model, and the open run's next text
  step blocks `MODEL_CONFIG_CHANGED`. ADR-0139 says "an open run keeps its primary models", but it actually blocks.
  Before this release, changing the automation settings left `text_backend_complex` alone, so such a run went on.
  The save also silently replaces a project-level `text_backend_complex` that a user set on purpose for manual
  (non-run) script work. That was already incompatible with runs, but it was still the user's setting.
- Fix: either document that a primary script change blocks open runs (and make the UI say so), or have
  `_require_script_route` accept the run's frozen script route when the project's current one differs only by a
  settings save. The simplest version: text adapters pass the run's frozen `script` route to `TextGenerator` explicitly
  (`provider_id/model_id`) instead of reading the project setting.

### M7. The alert sender can raise, and then stalls the whole autopilot scan
- `server/production_run/alerts.py:55-69` catches only `httpx.HTTPError`; `AlertGate.observe` (`:84-104`) records
  `_sent` *before* sending. `server/production_run/autopilot.py:299-339`: `observe` runs inside `step` and again inside
  the `except Exception` handler of `scan_once`.
- Verified: `WebhookAlerts("http://[::1").send(...)` raises `httpx.InvalidURL` (not an `HTTPError` in httpx 0.28.1).
- Failure scenario: a host typo in `ARCREEL_ALERT_WEBHOOK_URL`. The first non-ready project's `step` raises from
  `observe`. The handler's own `observe("refused")` raises again, which escapes `scan_once`, so projects after it on the
  page are never scanned. The next scan alternates `halted`/`refused` (each a "new" state), raises again, and so on
  forever. Ready projects later in the order never start. That breaks ADR-0137's "a send that fails ... never stops
  the scan".
- Fix: `except Exception` in `WebhookAlerts.send` (log only the type name, as now), and validate the URL in
  `alerts_from_env`. A failed send could also skip recording `_sent`, so the next scan retries.

---

## LOW

### L1. The commit manifest names a brief digest that the Gate A decision never greenlit
`_fall_back` keeps `gate_a_decision_id` (`story_adapter.py:866`), but the brief is now F's (a different digest). The
driver writes `brief_digest=self._brief.digest()` into `ManuscriptCommitManifest` (`driver.py:2219`). Nothing verifies
the pair today (`narrative_authority.bind` does not), so this is an audit-trail mismatch, not a refusal. Fix: record
`basis.brief_digest` and the reroute top-up number in the manifest, or document that Gate A covers the basis brief.

### L2. Continuity restore is lost after a crash
`media_adapter.py:354-363`: the `rejudged` attempt and `kept_version` are committed, then `_restore` runs outside the
transaction. A crash in between leaves the worse version current while `continuity.json` says the better one was kept,
and it is never retried. Fix: restore before recording the attempt (restore is idempotent), or re-check `kept_version`
against the current version on the next poll.

### L3. Continuity judge calls are not in the run's budget, and the judge co-authors what it later reviews
Judge calls (`continuity_judge.py:325-342`) go to a reviewer route with no ledger or usage. On a priced cloud judge (the
ADR's target) they are unaccounted spend against the run caps. The judge's `prompt_fix` then shapes the storyboard
that the same reviewer identity judges in QUALITY. This is dormant until a launch profile pins a judge. Fix: meter judge
calls into the MEDIA step usage before the first pin, and consider using the reviewer that is *not* the continuity
judge as the one whose QUALITY verdict decides.

### L4. Prompt-injection surface of `prompt_fix`
The judge's model output (≤ 600 chars, whitespace collapsed, `continuity_judge.py:270`; stripped and truncated again in
`media_adapter.py:244`) is appended verbatim as `Correction: …` to the image provider prompt
(`generation_tasks.py:380-388`). The frame being judged is model-generated and may contain rendered text that steers the
judge. The impact is bounded: an image prompt, the provider's own safety filter, and the text is recorded with the
version. Fix: strip control and markup characters, and drop fixes that name content outside the shot's characters,
location and props, or run them through the project's content-safety check.

### L5. `parse_verdict` edge: Infinity
`json.loads` accepts `Infinity`, and `round(float(inf))` raises `OverflowError`, which `judge()` does not catch
(`continuity_judge.py:341`). The exception reaches `_continuity_round`'s `except Exception`
(`media_adapter.py:277-280`), so **all** units of the round lose their verdicts, not only the one. The run still never
blocks. Fix: add `OverflowError` to the caught tuple, and catch per unit in `_judge_continuity`.

### L6. `sound_findings`/`measure_loudness` timeouts are not caught
A `subprocess.TimeoutExpired` (600 s) in `final_checks.sound_findings` or `measure_loudness` propagates out of the
reviewer, while `RenderRefused` is caught. If the reviewer turns that into an assessment `FAILED`, QUALITY blocks on
`ASSESSOR_FAILED` because of a MINOR-only check. This is unlikely on a 30–90 s final, but the delivery checks are meant
to be advisory. Fix: catch `(RenderRefused, subprocess.SubprocessError, OSError)` and skip the finding.

### L7. Rollback hazard
`StoryBrief` (`driver.py:249`) and every `AutomationContract` (`r2/contracts/automation.py:43`) are `extra="forbid"`.
After this release writes a `basis` into a story task payload, or a non-empty `fallback_routes`/`continuity_*` into a
run's stored policy, rolling back to `r2-v2.5.16` makes those story runs and production runs fail validation on load.
Fix: note in the deploy runbook that a rollback must be preceded by no reroute or fallback activity, or ship a
tolerant reader first.

### L8. `settled_usage` uses `scalar_one_or_none` per reservation
`lib/db/repositories/production_runs.py:809-827`. `settle_budget` refuses a second usage only when the row is
`SETTLED`. An `UNKNOWN` settle followed by a settle with a different `receipt_ref` for the same reservation can store
two usage rows, and `settled_usage` would then raise `MultipleResultsFound` in the controller. That needs an owner
whose receipt_ref changes within one step, which I did not find on current paths. Fix: order by creation and take the
first, or add a unique constraint on `reservation_id` (not in this RC, which has no migrations).

---

## Answers to the focus questions

1. **Money safety.** No. A paid story can exceed the run's approved cap through the STORY fallback (H1). The
   `rerouted_limits` arithmetic itself is sound: `cap' = new_cap + prices'(used)` bounds *new* spend at `new_cap`,
   because `runtime.py` checks `prices(total)`. The flaw is that `new_cap` is the run's whole cap, and the plan reserves 0.
   Story fallback selection (`_writer_order`) does apply local_only, ceiling presence and reviewer exclusion
   (`story_adapter.py:760-780`), and `CURRENCY_MISMATCH` guards cloud prices. TextGenerator fallback bypasses the frozen
   policy entirely (H2), and I judge that unacceptable for autopilot runs. The cloud story gateway refuses
   `cloud_prices=None` limits (`cloud.py:276`), so no path runs a cloud writer with an unbounded money cap.
2. **Idempotence and replay.** A replay after the top-up is recorded is safe: `_fall_back`, `_take_over` and `reroute`
   find `caller_ref` in `top_ups` and only call `requeue_finished`, which is idempotent and only re-queues finished
   statuses, so a story cannot run twice. A replay **before** the top-up is not safe: M1 (take-over receipt and brief
   committed before the top-up) and M2 (`set_story_brief` committed before the top-up). Each one skips a writer or
   blocks the run. Worker on a stale brief: the worker can only start after `requeue`, which comes last, so it never
   runs the old route after a reroute. In the M2 window, the payload brief is newer than the state limits (see M2).
3. **Fingerprint compatibility.** OK. `basis` is `exclude_if None` (`driver.py:271-274`), so old briefs keep identical
   `digest()`. `_route()` with no basis equals the old inline code (`brief.routes()`, byte-identical concatenation).
   `_converge` uses the brief's own digest when there is no basis. Old persisted briefs validate (`basis` optional;
   `extra="forbid"` only rejects unknown keys, and nothing new is required). The `policy_digest` of existing runs is
   unchanged: `fallback_routes: []` and the three `continuity_*: None` are dropped by `_LATER_DEFAULTS`, and a stored
   policy keeps its explicit `target_duration_seconds: 45` (still within the widened 10–600 bound). Only *newly
   resolved* policies move, which affects enabled autopilots (H3). Other per-request `context_digest`s change after a
   reroute, but they are not node fingerprints, so nothing is rewritten. The `test_a_new_run_on_another_writer...` test
   confirms that all 24 node heads are kept.
4. **Authority.** Not fully sound. On the STORY path, a writer added to the settings *after* the grant (absent from
   `policy.fallback_routes`, so never preflighted) can write under the run's grant without a new Gate A, because
   `_writer_order` reads the live list. It is filtered against the run's local_only, ceiling and reviewers, but its
   `config_digest` and identity are never compared with what was approved. On the text-task path it is fully
   unapproved (H2). Recommendation: intersect the live list with `policy.fallback_routes` (role, provider, model,
   model_identity), so that "part of the policy the grant approved" is literally true. The live list then only removes
   or reorders entries. Removal and reordering mid-run are safe with the current code.
5. **Concurrency.** No second *concurrently executing* story run: `has_active` holds the planner while any run is
   non-terminal, and `adoptable` requires a finished task. It can, however, leave two *unfinished* stories (M4), which
   conflicts with ADR-0124 §3 and with ADR-0129's "the next run takes it over" premise.
6. **Settings save side effect.** Yes. It overwrites a deliberate `text_backend_complex`, and it can block an open run
   (M6). The save itself cannot fail on the `next(script)` lookup, because roles are validated at
   `settings.py:200-201`, but the request can return 500 after a successful save through `record_launch` exceptions
   (M5), and the advertised re-qualification does not happen after a route change (H4).
7. **ADR-0133..0137 against existing flows.** The renderer always produces an audio track (`anullsrc` base), a silent
   final skips mastering (≤ −70 LUFS), `linear=true` falls back to dynamic mode with the `aresample=48000` already in
   place, and verification runs on the mastered file. The new tests pass, and I found no break. The new findings are
   all MINOR, and `ModelAssessment.accepts()` and `combine` ignore MINOR (`r2/automation/assessment.py:47-50, 92-99`),
   so QUALITY pass/fail is unchanged, apart from the L6 timeout corner. Alerts at startup: `alerts_from_env()` is
   `None` when unset (no change). When set, M7 is the risk. The `stages` report uses `RunSnapshot` as a `RunScope`
   (duck-typed attributes; works). Note H3: the ADR-0135 policy change halts enabled autopilots on deploy.

## Verified OK

- `rerouted_limits` arithmetic and `top_up(reroute=True)`: only `ROUTE_LIMIT_FIELDS` and the grown fields may change;
  the record keeps `limits_before/after`; the phase returns to RUNNING; nodes off their required fingerprint are
  reopened.
- `reroute_brief` returns the brief unchanged when routes and cloud profiles already match, so a take-over on the same
  writer keeps the old digest and `adopt` sees `rerouted=False`. `basis` is set once and kept across further reroutes.
- `hand_over_story_run(brief=)` writes the brief and the receipt in one commit, and a replay adds nothing.
  `set_story_brief` refuses queued and running tasks.
- `_fallback_writers` with the current writer removed from the list goes back to the primary writer, never loops
  (bounded by the order list and by M3's repair limit).
- `RunPolicy.fallbacks_are_text_routes`: role restricted to writer/script, no repeat of a primary, no duplicates.
  `save_settings` mirrors this (`FALLBACK_ROLE_UNSUPPORTED`, `FALLBACK_REPEATED`), applies the media type and ceiling
  through the shared `entry()`, and folds fallbacks into `local_only` and `paid`.
- Preflight applies `CLOUD_ROUTE_FORBIDDEN`, `UNBOUNDED_PAID_ROUTE` (including currency) and reviewer independence
  to `policy.fallback_routes`. `ProjectPolicyResolver.fallback_routes` drops entries it cannot inspect and never
  refuses. `CONTINUITY_JUDGE_NOT_QUALIFIED` requires the policy pin to equal the launch profile pin, the judge to be
  one of the run's reviewer routes, and committed evidence with the schema and sha256 digest (`profiles.py:439-485`).
- `is_route_failure`: walks `__cause__`/`__context__` with a cycle guard and ignores `bool` status codes; answer-level
  errors (400, schema) are re-raised. `TextGenerator` stays on the fallback, and each call goes to the ledger under the
  answering model. (A non-route error raised while handling a route error is classified as a route failure through
  `__context__`. That is acceptable: at worst it causes one retry on another model.)
- The continuity judge never blocks: a transport or parse failure gives `None`, a job exception maps to `(None, None)`
  for every unit, the frame is kept, and the second round only restores when both scores exist and the new one is
  lower. `MEDIA` waits on `WAIT_FOR_TASK`, so a re-judge never runs before the redo task finishes. The redo and rejudge
  write-ahead attempts (`continuity:{unit}:{round}`) make each step happen at most once per command.
- `cast_check`: a `same_person: false` entry forces a high identity issue, which caps the score at 69 (drift). A
  non-list or non-dict `cast_check`/`issues` is filtered or raises `TypeError`, which is caught, so there is no crash.
- `prompt_addenda` in the storyboards tool is type-checked (dict of str), and `_with_prompt_addendum` refuses empty text
  or text over 600 chars. `image_prompt` is not edited.
- A9 (`controller._settle`): a resumed step reuses the committed usage (its digest is verified), so a later
  re-measure cannot conflict. Behaviour for `UNKNOWN` is no worse than before.
- A11 `publish_metadata`: deterministic, ≤ 3 de-duplicated hashtags, description ≤ 5000 chars including the tail;
  `series.episodes ≥ episode`.
- ADR-0136 batch: a film is qualified only when its own preflight's sole blocker is the missing record, and nothing is
  inherited from the template. `episode_adaptation` defaults to `screen` unless the template sets it. The voice rate is
  applied only when the template's audio route equals the profile's.
- Alerts: the payload holds only the project name, event, run id and reason code; the URL and secrets are never logged
  (only the exception type is); once per (event, run, reason) per process; the URL comes from the host env only, so
  there is no user-controlled SSRF.
- Render mastering: picture stream-copied, audio mastered once with the measured values, before/after loudness in the
  manifest, `loudness_lufs=None` opt-out, source hashes still checked after mastering.


## Dispositions by the main agent (2026-11-13)

| Finding | Disposition |
|---|---|
| H1 | Fixed: fallback and take-over steps reserve the run's remaining money and cap the story at it (`story_adapter._room`, `_fall_back`, `_take_over`, adoption `plan`). |
| H2 | Fixed: run rules set per task by the worker (`fallback_rules.py`, `execution_guard.run_fallback_rules_for`, `generation_tasks.execute_generation_task`); `FALLBACK_IS_REVIEWER` at save. |
| H3 | Deploy step (runbook in the handoff): production has one ENABLED delegation (`minh-co-so-thich-dac-bie-55335b61`, itself blocked); re-enable or save its settings after deploy. |
| H4 | Fixed: `build_record` accepts `LAUNCH_QUALIFICATION_CHANGED` alone (`ONLY_STALE`); test `test_launch_record.py`. |
| M1 | Fixed: `_taken_over` checks a recorded top-up of this run's steps. |
| M2 | Fixed: `reroute` writes state, then brief, then queue; `_fall_back` pins the chosen brief; replay test. |
| M3 | Fixed: fallback REWORK only below `unit_repair_limit`; test. |
| M4 | Fixed: `story_run_busy` uses the take-over conditions and the autopilot's idea; tests. |
| M5 | Fixed: `_launch_reasons` never raises. |
| M6 | Fixed: an open run's script work stays on its frozen model; the text-stage comparison is removed. |
| M7 | Fixed: the sender never raises, a malformed URL disables alerts at start, an undelivered alert is retried. |
| L5, L6 | Fixed (finite score; advisory sound checks swallow measurement failures). |
| L1 | Accepted: the fallback is approved by the run's policy and rules; the manifest keeps the story's Gate A. |
| L2, L3, L4 | Accepted while no launch profile pins a continuity judge (dormant path); to fix before the first pin. |
| L7 | Runbook: no rollback below this release once a story was rerouted or a run froze fallbacks. |
| L8 | Accepted: no current path produces two usage rows for one reservation. |
