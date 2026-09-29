# V1 Operator Runbook

This is the single-operator procedure for an ArcReel V1 deployment (ADR-0089), with release-mode
paid-route controls (ADR-0091), the O2a export (ADR-0090) and offline backup (ADR-0090,
`m7-backup-restore.md`). Every command names its target explicitly; nothing here calls a paid
provider unless the step says so.

## 1. What V1 is, and what it is not

V1 turns a selected source into a finished short video with four human gates:

| Gate | Decision | Where |
|---|---|---|
| A: Greenlight | the source or idea is approved for development | Project settings, "V1 Human Gates" |
| B: Narrative Lock | the adapted screenplay is admitted for production (drama projects) | gate API |
| C: Final Cut | each shot master, then the composed final, is approved | gate API; the approved finals are listed in project settings |
| D: Publish Approval | the exact final (by digest), platform and visibility are approved for manual publication | Project settings |

**Disabled or manual in V1** (strategy §4; do not describe them as available):

- **Video generation through a paid provider in a release deployment.** Every async video adapter profile is `UNQUALIFIED`, so every video route is refused, and a video canary is refused before it spends anything.
- **The built-in Agent in a release deployment, except on the Anthropic route.** Only the `anthropic-official` preset with Claude models can be qualified. It runs with a per-connection budget reservation and a hard cap (ADR-0093); other Agent presets are refused. Custom-provider trial runs are refused.
- **Publication.** V1 never uploads. After Gate D the operator publishes the downloaded file by hand.
- **Other deferred capabilities:**
  - trend research and autonomous discovery;
  - portfolio scheduling;
  - analytics;
  - automatic learning;
  - multi-tenant operation;
  - provider-agnostic execution;
  - online (zero-downtime) backup, PITR and encrypted backup custody.
- **The Gate B and Gate C review lists.** These gates are decided through their API commands. The UI shows only the approved finals.

## 2. Run the deployment

Configure `.env`:

```bash
AUTH_USERNAME=<operator>
AUTH_PASSWORD=<strong password>
AUTH_TOKEN_SECRET=<long fixed random value>
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
ARCREEL_DATA_DIR=<absolute data root>
ARCREEL_RELEASE_MODE=PRODUCTION_CANDIDATE   # unset = DEV: no paid-route refusal
ARCREEL_BUDGET_SCOPE=release                # budget scopes are <prefix>:<currency>
# OTEL_EXPORTER_OTLP_ENDPOINT=...           # traces leave the host only when set
```

Then run from the tagged source:

```bash
uv sync
(cd frontend && pnpm install --frozen-lockfile && pnpm build)
uv run uvicorn server.app:app --host 127.0.0.1 --port 1241   # migrates the database on startup
```

- The PostgreSQL major version must match the `pg_dump`/`pg_restore` client used for backups (`m7-backup-restore.md`).
- An `ARCREEL_RELEASE_MODE` value that is not a release mode (`DEV`, `PRODUCTION_CANDIDATE`) stops startup with `ReleaseModeConfigError`. Startup logs `release mode: …`; check it.

## 3. Authorize paid routes: budget and canary

In `PRODUCTION_CANDIDATE`, a paid image, text or audio call runs only when two conditions hold:

1. **A budget scope exists** for the call's currency and has room. The limit is fixed when the scope is created. To authorize more, create a scope under a new prefix and point `ARCREEL_BUDGET_SCOPE` at it.

   ```bash
   uv run python -m scripts.r2.budget_scope create --currency USD --limit 50
   uv run python -m scripts.r2.budget_scope show --currency USD
   ```

2. **The exact route is qualified.** Running the canary is your authorization for one small paid call on that route and model.

   ```bash
   uv run python -m scripts.r2.qualify_route --provider openai --media image --model gpt-image-2
   uv run python -m scripts.r2.qualify_route --provider custom-7 --media text --model relay-chat
   ```

   - **What the qualification binds to:** the model the backend really calls, and the provider's configuration by digest. A new key, base URL or model endpoint needs a new canary. Rate and concurrency settings do not.
   - **When it expires:** after 30 days (`--ttl-days`), or when the adapter version changes.
   - **Where it is stored:** under `<data root>/.route_qualifications/`, with a digest-bound evidence file.
   - **A failed canary** records nothing.
   - **A stale `.lock`** in that directory (older than 5 minutes) is cleared automatically.

**The Agent (ADR-0093).**

1. Set the active Agent credential to the `anthropic-official` preset, with a Claude model or no model.
2. Create a USD budget scope.
3. Run the Agent canary. It makes one tiny call that the CLI must stop at its cap:

   ```bash
   uv run python -m scripts.r2.qualify_route --provider anthropic-official --media agent --model claude-sonnet-4-6
   ```

Each Agent connection then reserves `ARCREEL_AGENT_SESSION_BUDGET_USD` (default 1.00 USD) and cannot spend more than that; the overshoot is at most the calls already in flight. When the cap is reached, the turn ends with a budget message, the connection closes, and the next message opens a new connection with a new reservation. The CLI may restore a conversation's earlier cost on resume, so a long conversation reaches the cap sooner; continue in a new conversation or raise the setting.

**If a paid call is refused:**

- `paid_route_unqualified`: run the canary for that exact provider, media type and model.
- `budget_scope_missing` or `budget_exceeded`: create a scope, or create a larger one under a new prefix, as above.
- **A refused video, Agent or trial-run route is expected in V1.** Use `DEV` only on a non-release deployment.

## 4. Produce, approve and export a product

1. **Gate A:** in Project settings, "V1 Human Gates" → Greenlight, enter the source digest and approve.
2. **Gate B (drama):** admit the screenplay through `POST /api/v1/projects/{p}/gates/narrative-lock`.
For the no-provider factual product (the Golden A bundle), `scripts/r2/v1_operator.py` does steps 3 and 4 under your own login:

- `digests` prints the digests for Gates A and B;
- `produce` renders the shots into `production/`;
- `approve-shots` records Gate C for each shot, after you review the files;
- `approve-final --audio MUTE|AUDIO` composes the final and records its Gate C.

3. **Gate C for each shot:** render the shot, then approve its master through `POST /api/v1/projects/{p}/gates/final-cut`.
   - Send the file path under `production/` and its sha256; the server re-hashes the file and refuses a mismatch.
   - Re-using an `approval_record` for the same request replays safely.
   - Re-using it for a different request is refused.
4. **Gate C for the final:**
   - Compose the final from the approved shot masters. The `GoldenAComposer` concatenates them without re-encoding.
   - Approve it with `method: COMPOSITE`, `tool: ffmpeg`, the composer's `source_master_refs` and empty `direct_dependencies`. The server derives the dependencies from the current masters.
   - The approved bytes are copied to `output/ep<episode>-<target>.mp4`.
5. **Review and download:** Project settings → Final Cut lists each current approved final. "Download" fetches it through a 5-minute download token, and the file's sha256 equals the listed digest.
6. **Gate D:** "Use for Publish Approval" fills the digest; enter the platform and visibility, then approve. The server accepts only the digest of a current approved final whose export copy matches.
7. **Publish** the downloaded file manually, outside ArcReel.

**Staleness.** Re-approving a shot, or changing its master file, makes the final stale:

- it disappears from the Final Cut list;
- Gate D refuses it;
- you compose it again and re-approve it at Gate C, then at Gate D.

A file written into `output/` by another tool under the same name also makes the final non-exportable, until you re-approve it at Gate C.

## 4a. Portfolio admission (V2, ADR-0094)

- **Pause a project** so the worker stops claiming its queued generation tasks. Running tasks
  finish, and queued ones wait. Use Project settings → Generation queue → "Pause this project",
  or `PUT /api/v1/projects/{p}/admission` with `{"paused": true}`. Resume the same way with
  `false`. Cancelling work stays the task cancel API.
- **Cap running tasks per project** in each media lane, so one project cannot take the whole
  pool: `PUT /api/v1/admission` with `{"max_running_per_project": 2}`. `0` removes the cap.
  `GET /api/v1/admission` shows both settings.
- **When it takes effect.** Both apply at the worker's next claim cycle, and a restart keeps them.

## 4b. Master authority (V2, ADR-0096)

- **What changed.** A Gate C approval promotes the master in the database first, then writes
  the file manifest's approved master as its projection.
- **Routes that refuse divergence.** Publish approval, the deliverable listing and a composite
  final's Gate C refuse a project whose database masters and file masters disagree. They return
  409 with a `master_diverged` detail.
- **Release step for existing projects.** A project approved before this release has file
  masters only, which the routes above refuse. Run this once, with the application stopped or
  idle:

      uv run python -m scripts.r2.backfill_master_authority --user-id default --all

  The JSON summary lists, for each project:
  - `promoted`: new database heads;
  - `current`: heads that already agree;
  - `diverged`: heads that disagree.

  A rerun is safe: it promotes nothing new.
- **If the exit status is 2**, some artifact is diverged, and nothing was changed for it. Keep
  the summary. Re-approve the artifact through Gate C, which writes a new head and its projection.
- **A failed Gate C** that fails after the database promotion converges on a retry with the
  same `approval_record`.

## 5. Backup, restore and recovery

- **Procedure:** follow `docs/r2/runbooks/m7-backup-restore.md`. The steps are:
  1. stop the app;
  2. `create`;
  3. record the backup set;
  4. to recover: `restore` into an empty target, then `verify`;
  5. prove the restored products with the restore drill (`tests/drills/r2/golden_restore_drill.py` for the Golden corpus);
  6. `attest`.
- **Credentials are not backed up.** After a restore, re-enter the provider keys.
- **Qualifications need new canaries.** Route qualifications bound to the old keys stop matching, so run the canaries again.
- **Browser check after a restore.** Run the operator browser workflow against the restored target (`tests/e2e/test_m7_production_candidate_workflow.py`; see its docstring).

## 6. Incidents and rollback

- **Suspected overspend.**
  1. Run `budget_scope show` for each currency.
  2. Stop new paid work by pointing `ARCREEL_BUDGET_SCOPE` at a prefix with no scopes, then restart. Every paid call is then refused before submit.
  3. Reconcile in-flight provider jobs from the task and usage records before re-authorizing.
- **Ambiguous provider outcome** (a timeout after a submit). V1 never resubmits automatically (ADR-0078).
  1. Check the provider's console for the job.
  2. Retry by hand only if it does not exist.
- **A provider key is compromised.**
  1. Rotate it in system settings.
  2. Every qualification bound to the old key stops matching. Run the canaries again.
- **A bad release.**
  1. Stop the app.
  2. Restore the last verified backup set into a clean target.
  3. Run the previous tagged source against it.
  4. Do not run a newer schema against an older tag. Downgrades are not a supported rollback.

## 7. Release gates

The twelve release gates (ADR-0091 T1) are declared in `scripts/r2/v1_release_gates.json`. They run from a clean tree with the gate runner, which writes one log per gate plus a manifest. The whole backend suite runs first, while the tree is still clean.

```bash
export GATE_PG_URL=postgresql+asyncpg://…/<empty disposable db>   # migration round trip + dialect suite
export GATE_E2E_DATA_DIR=<drill work>/restored-data               # restore-derived target (golden drill)
export GATE_E2E_DATABASE_URL=postgresql+asyncpg://…/golden_drill_target
uv run python -m scripts.r2.run_gates --config scripts/r2/v1_release_gates.json \
  --out docs/r2/evidence/<run id> --changes <upstream dispositions json>
```

- **Before the gates:** run the golden restore drill on the same HEAD, so the browser gate runs against a target restored from that HEAD.
- **Skips:** `allowed_skips` declares the whole-suite skips up front. The gate logs list each skip reason (`-rs`).
- **After the gates:** commit the manifest and logs as the only change after the candidate, then run the E1 verifier (`scripts/r2/verify_upstream_candidate.py`).

## 8. Evidence to keep per release

For each release, keep:

- the tag;
- the release-gate manifest and logs;
- the backup-set id and `attest` output;
- the drill and browser evidence;
- the ledger of qualifications (`.route_qualifications/`);
- the Gate D decisions (`GET /api/v1/projects/{p}/gates`).
