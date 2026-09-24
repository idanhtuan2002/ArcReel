# R2 V1 P0 / M7 H6–H8 — research before remediation

Date: 2026-09-25
Examined checkout: `r2-m7e-v1-lineage`, HEAD `4ad51b7778a8dbf7430767827106b77515e47221`.

## Scope and method

This is research only. It records facts from official PostgreSQL,
OpenTelemetry, Git, and (where attestation is concerned) GitHub documentation,
then relates those facts to exact current-checkout code and accepted local
requirements. It does not select an architecture, approve an integration, or
prescribe remediation. No provider call, credential use, migration, deployment,
or live backup/restore was authorized or performed.

The codebase-memory project supplied for this task is stale (generation
`2026-09-18T10:57:40Z`); its coverage marks the material H6/H7 modules as
`not_tracked`, the compatibility module as missing, and repository metadata as
changed. The code observations below therefore use direct reads of the exact
files cited. They are not an exhaustive caller/callee inventory.

## 1. PostgreSQL dump/restore, snapshots, and external media

### Facts from primary sources

1. A parallel `pg_dump` relies on synchronized snapshots: PostgreSQL says the
   leader and workers use multiple connections, and without synchronized
   snapshots those connections are not guaranteed to see the same data set.
   [`pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html#APP-PGDUMP-OPTION-J)
   The `--snapshot` option supplies a synchronized snapshot and is also used
   by a parallel dump instead of taking a new one.
   [`pg_dump --snapshot`](https://www.postgresql.org/docs/current/app-pgdump.html#APP-PGDUMP-OPTION-SNAPSHOT)

2. `pg_dump --serializable-deferrable` uses a serializable transaction and
   waits for a point at which no serializability anomaly can occur. PostgreSQL
   says that, without this option, a dump can reflect a state inconsistent with
   any serial execution of eventually committed transactions; it also says this
   option is not beneficial for a disaster-recovery dump.
   [`pg_dump --serializable-deferrable`](https://www.postgresql.org/docs/current/app-pgdump.html#APP-PGDUMP-OPTION-SERIALIZABLE-DEFERRABLE)

3. These PostgreSQL mechanisms describe database connections and database
   snapshots. The cited documentation does not claim that `pg_dump` establishes
   an atomic recovery point with an independently stored media/object system.
   **Inference:** a database snapshot mechanism alone is insufficient evidence
   of one atomic database-plus-external-media recovery point; any claim about
   that combined property needs evidence from both systems and their capture
   protocol.

4. `pg_restore` directly connected to a database executes SQL. PostgreSQL
   explicitly warns that restoring a dump executes arbitrary code chosen by the
   source superusers; partial dump/restore does not limit that, and untrusted
   source SQL must be inspected (including `pg_restore --file` for non-plain
   archives).
   [`pg_restore warning`](https://www.postgresql.org/docs/current/app-pgrestore.html)

5. `pg_restore --no-password` prevents an interactive prompt and fails if no
   password is otherwise available. The PostgreSQL password-file documentation
   requires Unix `.pgpass` permissions to exclude group and world access
   (`chmod 0600` is the documented example), otherwise libpq ignores it.
   [`pg_restore connection options`](https://www.postgresql.org/docs/current/app-pgrestore.html#APP-PGRESTORE-OPTION-W)
   [`libpq password file`](https://www.postgresql.org/docs/current/libpq-pgpass.html)

### Current-checkout observations

- `create_backup_set()` copies and verifies each selected media object before
  running custom-format `pg_dump --no-password`; it compares only the count of
  candidate rows before and after the work. See
  `r2/host_hardening/backup.py:257-280`. Its documented precondition is that
  the application and worker have been stopped (`backup.py:240-245`), while
  the module docstring describes this as an operator-enforced write fence
  (`backup.py:1-19`).
- The copied media inventory has size and SHA-256 checks (`backup.py:146-192`),
  and restore refuses non-empty database/media targets before invoking
  `pg_restore --no-password` (`backup.py:302-346`). Restoration subsequently
  copies media; the provided verification checks Alembic head, a master-head
  count, and every media entry's presence/size/digest (`backup.py:349-386`).
- The code passes a libpq URL as an argv element and does not deliberately put
  the URL in its returned manifest/verdict (`backup.py:105-121`, `224-296`).
  **Unknown:** direct inspection here cannot establish how every caller obtains,
  masks, rotates, or logs the URL/credential, nor whether the runbook’s
  operational fence is actually followed.
- **Inference:** the count-before/count-after proof detects one class of change
  (a changed candidate-row count), not every possible database or media mutation.
  This follows from the exact query and equality comparison at
  `backup.py:124-134` and `257-275`; it is not a claim that such mutations
  occur.

## 2. OpenTelemetry Python SDK/exporters and baggage

### Facts from primary sources

1. OpenTelemetry’s Python documentation says applications need the SDK, then
   initialize a `TracerProvider` and may make it global. Its example attaches a
   `BatchSpanProcessor` to the provider.
   [`Python manual instrumentation`](https://opentelemetry.io/docs/languages/python/instrumentation/)

2. The Python exporter documentation shows an OTLP exporter with a resource
   service name, a `BatchSpanProcessor` for traces, and a
   `PeriodicExportingMetricReader` for metrics. It describes sending to an
   OpenTelemetry Collector as a production best practice and distinguishes
   console exporters as useful for local development/debugging.
   [`Python exporters`](https://opentelemetry.io/docs/languages/python/exporters/)

3. The Python propagation guide says instrumentation libraries can propagate
   context automatically and are preferred to manual propagation. Its manual
   example separately injects/extracts W3C Trace Context and W3C Baggage.
   [`Python propagation`](https://opentelemetry.io/docs/languages/python/propagation/)

4. The OpenTelemetry SDK configuration documentation lists `tracecontext,baggage`
   as the default `OTEL_PROPAGATORS` value. Thus baggage is a transportable
   context channel, not merely an in-process variable.
   [`SDK general configuration`](https://opentelemetry.io/docs/languages/sdk-configuration/general/)

### Current-checkout observations

- `server/telemetry.py` imports the OTel API and SDK but configures only an
  in-memory exporter through `SimpleSpanProcessor` in `configure_test_tracer()`
  (`server/telemetry.py:22-28`, `68-85`). Directly read source in this pass
  shows no OTLP exporter configuration in that file. **Scope limit:** this is
  not a repository-wide absence claim.
- Production span creation goes through `execution_span()` and validates the
  attribute map before setting attributes (`server/telemetry.py:108-146`); the
  allowed durable IDs and low-cardinality metric-label policy are declared in
  `r2/host_hardening/telemetry.py:30-56` and enforced at `80-95`.
- `clear_baggage_for_provider_call()` returns a context in which ambient
  baggage is cleared, explicitly because provider tracing may receive baggage
  via request headers (`server/telemetry.py:149-157`). **Inference:** this is
  aligned with the official propagation fact that baggage can cross a remote
  boundary; it does not prove that every actual outbound provider request uses
  that returned context.

## 3. Git patch identity, range comparison, and gate evidence

### Facts from primary sources

1. `git patch-id` hashes file diffs with line numbers ignored. Git calls it
   reasonably stable and reasonably unique, and identifies its primary use as
   locating likely duplicate commits. With `--stable`, reordered file diffs do
   not change the ID and all patch whitespace is ignored.
   [`git-patch-id`](https://git-scm.com/docs/git-patch-id)
   **Inference:** equal stable patch IDs can support a content-equivalence
   observation for a diff under that normalization, but do not by themselves
   prove commit ancestry, source remote identity, build inputs, test execution,
   reviewer independence, or artifact provenance.

2. `git range-diff` compares versions of patch series/ranges by finding commits
   with reasonably similar patches; Git documents a tunable creation/deletion
   cost because the matching can otherwise consider a large change a complete
   rewrite. Git further states that its output is human-readable porcelain,
   may change across Git versions, and is not machine-readable.
   [`git-range-diff`](https://git-scm.com/docs/git-range-diff)
   **Inference:** range-diff is suitable as review evidence, but its official
   output-stability limit prevents treating its text alone as a durable,
   cross-version machine-verifiable integration attestation.

3. GitHub’s official artifact-attestation documentation describes signed claims
   that bind build provenance to, among other information, the workflow,
   repository, environment, commit SHA, and triggering event. It also says
   attestations must be verified, and that they are not a guarantee that the
   artifact itself is secure. GitHub’s offline-verification guide requires the
   artifact, bundle, trusted root, and verification command.
   [`Artifact attestations`](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
   [`Offline verification`](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline)
   This is an official GitHub feature, not a Git core feature.

### Current-checkout observations

- `verify_upstream_candidate()` requires a clean host worktree; exact host and
  evidence SHAs with ancestry; a pinned upstream `origin`; an exact merge-base;
  a source-tree hash; and an ordered `old_sha..new_sha` inventory. See
  `r2/host_hardening/compatibility.py:86-146`.
- It hashes committed evidence and dependency bytes and requires every named
  gate to bind the candidate SHA, report `PASS`, have no required skips, and
  include a non-empty command with zero exit code (`compatibility.py:161-207`).
  This is a local verification policy; it is not, on inspection alone, a
  cryptographic external attestation of who ran the gate or the environment in
  which it ran.
- The same module explicitly says its offline checks do not establish
  independent review or a provider call (`compatibility.py:86-91`) and refuses
  to elevate local fixture evidence to sandbox/qualified provider status absent
  trusted external attestation (`compatibility.py:218-223`, `267-275`).

## 4. Local contract and reuse comparison

- Accepted ADR-0078 requires a PostgreSQL recovery point bound to immutable
  media, then a clean-target restore with every approved-master reference
  resolved and probed (`docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md:72-79`).
  Frozen H6 also names project records, Artifact Manifests, formal files and
  secure credential handling
  (`docs/r2/R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md:258-277`). The
  accepted M7 design requires exact release/schema and all project/manifest/
  master checks, media probes, no-provider Golden A/B review/export, and a
  `VERIFIED` transition after a measured drill
  (`docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md:590-605`).
- The dump is whole-database (`r2/host_hardening/backup.py:266-269`), while
  the media inventory and before/after count select only one `(user_id,
  project_name)` (`backup.py:124-134`, `250-275`). The restore verifier counts
  master rows but does not resolve or probe their references (`backup.py:349-386`).
  **Inference:** a passing `BackupVerdict` does not prove deployment-wide
  database/media closure or master playability.
- `recovery_target` is assigned from the caller-supplied `now` after the dump,
  rather than read from a PostgreSQL snapshot identifier
  (`backup.py:266-294`). **Inference:** its timestamp alone cannot prove the
  exact database snapshot was simultaneous with the copied media.
- The backup module claims `add_media_ref()` fences GC (`backup.py:1-14`),
  but the repository method only flushes and the backup function does not
  commit before media copying and the DB dump
  (`lib/db/repositories/host_hardening.py:1100-1128`, `backup.py:250-282`).
  **Inference:** visibility of PREPARING refs to a separate GC transaction is
  unproved; a transaction/visibility test is needed.
- Restore joins `manifest.database_backup_ref` and each media `object_ref`
  directly to source/target roots (`backup.py:195-203`, `315-346`).
  **Inference:** supplied manifest paths require safe-relative-path and
  symlink-boundary validation to prove containment; these functions do not
  perform it.
- The runbook says credentials are never part of a backup set
  (`docs/r2/runbooks/m7-backup-restore.md:96-103`), but the whole-DB dump has
  no table exclusions (`backup.py:266-269`) and credential models have
  plaintext fields (`lib/db/models/credential.py:29-35`,
  `lib/db/models/agent_credential.py:36`). **Inference:** that runbook claim
  is not established for the DB dump. The M7 design says only that credentials
  are absent from project media/manifest and need a separate access-controlled
  policy (`docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md:603-605`);
  the exact DB-backup policy remains unresolved.
- Existing project research already compared a write-fenced logical/physical
  DB-plus-media drill with a WAL/PITR profile and defined the inventory/restore
  protocol (`docs/research/2026-09-12-r2-m7-host-production-hardening-research.md:283-334`).
  The pinned ArcReel baseline is `v0.29.0` at
  `6ddedc775e7fe5f398b10081ab741985f7dceda7`
  (`docs/r2/HOST_BASELINE.txt:1-4`; local Git tag and SHA matched).
  A path/name inventory of its `lib/` and `tests/` trees found project
  migration/manifest components, not a directly reusable deployment
  backup/restore module. This is a bounded inventory, not exhaustive absence.
- ADR-0078 requires source-side telemetry minimization, keyed public job refs,
  and durable cross-restart IDs (`docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md:81-87`).
  The M7-D plan asks for all request/provider/candidate/promotion/usage seams
  and canary absence from logs, spans, baggage and public events
  (`docs/superpowers/plans/2026-09-12-r2-m7d-backup-observability.md:45-61`).
  Scoped searches of `r2/`, `server/` and `lib/` found the test tracer called
  only by tests, `execution_span()` called in recovery scheduling, and no
  production caller of `clear_baggage_for_provider_call()`. **Inference:**
  current source evidence does not establish full H7 or a production exporter;
  this is not an exhaustive runtime/logging audit.

## 5. V1 paid-route policy versus executable gating

ADR-0089 permits V1 only after each paid provider path is qualified **or
disabled** and a DB-plus-media restore drill succeeds
(`docs/adr/0089-ship-a-bounded-v1-before-v2-portfolio-automation.md:44-48`).
The V1 strategy requires no unqualified paid route remain enabled, and
duplicate/restart/ambiguous-outcome evidence for enabled paid routes
(`docs/r2/R2_V1_PRODUCTION_RELEASE_STRATEGY.md:74-87`, `111-122`). Neither
document itself defines a technical switch or proves a route is disabled.

- All 11 entries in `r2/provider_capabilities/registry.json` are currently
  `UNQUALIFIED` (`:21,43,65,87,109,131,153,175,197,219,241`).
  `require_enabled_capability()` rejects that status only in
  `PRODUCTION_CANDIDATE`, not `DEV`
  (`r2/host_hardening/provider_capabilities.py:207-237`).
- `require_submit_route()` defaults to `DEV`
  (`r2/host_hardening/route_inventory.py:131-147`), and the shared video submit
  adapter calls it without a release-mode argument
  (`lib/video_backends/execution_adapter.py:133-149`). A request with no
  `task_id` returns before this route check (`:143-148`). Worker video
  creation constructs an `AttemptSubmitter` for task-bound requests
  (`server/services/generation_tasks.py:2693-2720`), but does not change the
  release-mode default.
- A scoped search of `r2/`, `lib/video_backends/`, `server/`,
  `lib/media_generator.py`, and `lib/generation_worker.py` found no call passing
  `ReleaseMode.PRODUCTION_CANDIDATE` to this submit route. **Inference:** the
  registry's `UNQUALIFIED` values alone do not prove paid submit is disabled
  on the examined runtime path. Other controls/deployments were not audited;
  this is not a system-wide claim that a paid call can or will occur.

## 6. Acceptance state and questions before a decision

- The committed E1 handoff binds reviewed code SHA `404a5945...`, records
  14,228 backend tests passed/35 skipped and 52 focused tests passed, but
  independent spec and standards reviews returned `CHANGES_REQUIRED`
  (`docs/r2/evidence/R2_M7_E1_INTEGRATION_STOP_2026-09-25.json`). The
  findings include unproved upstream-to-candidate mapping, self-asserted
  gate outcomes, and provider evidence whose payload may itself say failure.
  These are review findings, not a fresh proof of exploitability in this note.
- The same handoff records M7-D prerequisite review as `CHANGES_REQUIRED`
  on exact candidate `05314871...`; it does not confer `RECOVERY_VERIFIED`.
  Neither E1 tests nor this note confer M7-E acceptance or
  `PRODUCTION_CANDIDATE`.
- ADR-0078 places H6 under `RECOVERY_VERIFIED` and H7/H8 under
  `PRODUCTION_CANDIDATE` (`:136-138`), while the M7-D plan demanded H1–H7 and
  Golden A/B at D3
  (`docs/superpowers/plans/2026-09-12-r2-m7d-backup-observability.md:64-79`).
  The current acceptance target and any stricter later gate need explicit
  reconciliation; a previous human/self-review report cannot settle it alone.

Non-selected options requiring evidence before a proposal:

1. Keep the accepted write-fenced V1 drill and prove deployment-wide
   DB/media/manifest/master closure, or seek explicit approval for a narrower
   backup boundary. The latter changes the accepted H6/V1 contract.
2. Reconcile the runbook, whole-DB dump, and M7 design before selecting
   DB-backup secret exclusion, encryption/access controls, or reprovisioning.
3. Qualify only exact V1 corpus paid routes, or disable other paid routes with
   an enforced production gate. First inventory the corpus routes and runtime
   configuration and prove fail-closed enforcement.
4. Distinguish committed byte-identical E1 evidence from trustworthy execution
   provenance. Local command artifacts/upstream patch mapping and signed CI
   attestations are different possible mechanisms; neither is selected here.

## Unknowns and limits

- No production backup, restore, provider call, migration, test suite, or
  deployment was run for this research note.
- This note did not inspect configuration/secrets storage, CI workflows,
  provider-call sites, or the full backup/restore runbook; it therefore makes
  no system-wide credential, propagation, or operational-compliance claim.
- Official PostgreSQL documentation supports database-snapshot and restore
  facts, but this pass found no PostgreSQL-owned specification for an atomic
  snapshot spanning PostgreSQL plus this repository’s external media store.
- Official Git documentation defines patch-id/range-diff behavior and limits;
  it does not define a general CI-gate attestation protocol. The GitHub sources
  describe one artifact-provenance/verification mechanism, whose applicability
  to this repository is unexamined here.

## Source index

- PostgreSQL: [`pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html),
  [`pg_restore`](https://www.postgresql.org/docs/current/app-pgrestore.html),
  [`libpq password file`](https://www.postgresql.org/docs/current/libpq-pgpass.html).
- OpenTelemetry: [`Python instrumentation`](https://opentelemetry.io/docs/languages/python/instrumentation/),
  [`Python exporters`](https://opentelemetry.io/docs/languages/python/exporters/),
  [`Python propagation`](https://opentelemetry.io/docs/languages/python/propagation/),
  [`SDK configuration`](https://opentelemetry.io/docs/languages/sdk-configuration/general/).
- Git and GitHub: [`git-patch-id`](https://git-scm.com/docs/git-patch-id),
  [`git-range-diff`](https://git-scm.com/docs/git-range-diff),
  [`GitHub artifact attestations`](https://docs.github.com/en/actions/concepts/security/artifact-attestations),
  [`GitHub offline verification`](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline).

## 7. PostgreSQL primary-source addendum: credentials and the DB-plus-media boundary

This addendum is research only. It does not select an implementation, alter the
accepted recovery boundary, or authorize a backup, restore, credential use, or
production operation.

### Facts from PostgreSQL primary sources

1. `pg_dump` exports one PostgreSQL database, makes a consistent export while
   readers and writers continue, and PostgreSQL cautions that it is generally
   not the right regular-production-backup tool except in simple cases.
   [`pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html)
   Its custom archive is selectively restorable, but an archive restore executes
   source-superuser-chosen code; an untrusted archive must be inspected first.
   [`pg_dump warning`](https://www.postgresql.org/docs/current/app-pgdump.html)

2. PostgreSQL provides explicit content-selection controls: `--exclude-table`
   excludes matching tables and `--exclude-table-data` excludes only their data.
   It also warns that a selective `--table` dump has no guarantee of restoring
   into a clean database by itself because dependencies are not collected.
   [`pg_dump selection and exclusion`](https://www.postgresql.org/docs/current/app-pgdump.html)
   These are database-archive controls; the documentation does not describe
   them as a cross-store transaction with external media.

3. For client authentication, PostgreSQL says `PGPASSWORD` is not recommended
   because some operating systems expose process environments to non-root users.
   It instead identifies a password file as an alternative; on Unix libpq
   ignores that file unless group and world access are denied (for example,
   mode `0600`).
   [`libpq environment variables`](https://www.postgresql.org/docs/current/libpq-envars.html)
   [`libpq password file`](https://www.postgresql.org/docs/current/libpq-pgpass.html)
   This concerns the credential used to invoke the PostgreSQL client; it makes
   no assertion that values stored in application tables are absent from an
   archive.

4. PostgreSQL's physical-backup guidance is scoped to the database cluster.
   A frozen database-volume snapshot must include the required WAL and, where
   database files span volumes, those snapshots must be simultaneous. If that
   cannot be achieved, PostgreSQL names shutdown long enough to establish frozen
   snapshots or a continuous-archiving base backup as database alternatives.
   [`file-system backup`](https://www.postgresql.org/docs/current/backup-file.html)
   `pg_basebackup` similarly backs up the entire cluster, not individual
   databases or objects.
   [`pg_basebackup`](https://www.postgresql.org/docs/current/app-pgbasebackup.html)

5. PostgreSQL continuous archiving combines a physical base backup with WAL and
   can restore the database to a chosen point after the base backup; logical
   `pg_dump` archives cannot be used for that WAL-replay solution.
   [`continuous archiving and PITR`](https://www.postgresql.org/docs/current/continuous-archiving.html)
   The low-level online-backup procedure requires WAL archiving to be working,
   ordered start/copy/stop operations, and the necessary WAL segments to be
   archived before the set is complete.
   [`low-level base backup procedure`](https://www.postgresql.org/docs/current/continuous-archiving.html)

### Current-checkout comparison

- The current helper invokes a whole-database custom `pg_dump` with neither
  table nor table-data exclusions (`r2/host_hardening/backup.py:266-269`). The
  database models contain credential-bearing `Text` columns, including provider
  `api_key`, `access_key`, and `secret_key`
  (`lib/db/models/credential.py:26-35`) and the agent `api_key`
  (`lib/db/models/agent_credential.py:31-36`). **Inference:** the source does
  not establish the runbook's statement that credentials are never part of a
  backup set (`docs/r2/runbooks/m7-backup-restore.md:96-103`); a whole-database
  archive can include rows from those tables unless an uninspected database
  feature or operational policy changes that result.

- The runbook correctly requires a manual application/worker fence and no
  mid-write background job (`docs/r2/runbooks/m7-backup-restore.md:9-19`), while
  the helper copies selected media before running `pg_dump`
  (`r2/host_hardening/backup.py:257-275`). PostgreSQL's database-consistency
  mechanisms do not extend to that independently stored media root.
  **Inference:** the accepted DB-plus-media property depends on the application
  fence, immutable/versioned media retention, and a protocol that binds the DB
  recovery point to the media inventory; it is not supplied by `pg_dump`, a
  database snapshot, or PITR alone.

- ADR-0078 requires that binding and clean-target probing of every
  approved-master reference (`docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md:72-79`).
  The accepted M7 design likewise specifies one authoritative snapshot,
  immutable object versions, inventory closure, and reference probes
  (`docs/superpowers/specs/2026-09-12-r2-m7-host-production-hardening-design.md:590-605`).
  **Fact:** those are stronger local acceptance requirements than the current
  helper's candidate-row count and media digest checks
  (`r2/host_hardening/backup.py:257-295`, `349-386`).

### Non-selected viable options and tradeoffs

1. **Explicitly write-fenced logical archive plus immutable media capture.**
   Keep the manual drain/fence, make the credential-table inclusion/exclusion
   policy explicit, capture the media versions referenced by the fenced DB
   state, and require clean-target reference probes. This retains the accepted
   V1 shape and uses `pg_dump` portability; it has downtime/coordination cost,
   requires a separately evidenced credential policy, and is not PITR.

2. **Write-fenced physical cluster backup plus immutable media capture.**
   Use a PostgreSQL-supported full-cluster physical backup/simultaneous database
   storage snapshot, with the same external-media manifest and restore probes.
   This can align the database storage boundary more closely with PostgreSQL's
   physical-backup model, but it is cluster-wide, requires operational storage
   and WAL handling, and still does not make the external media store atomic
   with PostgreSQL.

3. **Continuous-archiving/PITR database profile plus a separately coordinated
   media recovery target.** Use a PostgreSQL base backup and complete WAL chain
   for database point-in-time recovery, while retaining immutable media versions
   and recording an application-level mapping from the selected DB target to
   media inventory/version visibility. This improves database RPO flexibility,
   but adds archive-lag, WAL-completeness, restore-performance, and
   cross-store-coordination obligations. It is consistent with ADR-0078's
   production-candidate-only condition, not evidence that the condition is met.

### Unknowns and limits

- No inspected source establishes which credential tables, if any, are excluded
  by a wrapper, database policy, or operator procedure outside
  `create_backup_set`; no claim is made about actual archive contents without a
  bounded archive inspection under separate authorization.
- PostgreSQL documents consistency and recovery for PostgreSQL data/cluster
  files and WAL. It does not, in the sources above, define a transaction or
  atomic snapshot across PostgreSQL and this repository's external media root.
- No credentials, dump, restore, database connection, provider call, migration,
  deployment, or test suite was run for this addendum.

## 8. V1 P0 synthesis — recommended path, not an accepted design

### Further first-party source checks

- The actual Host project is also a filesystem authority: `ProjectManager`
  creates `project.json` and project subdirectories under `projects_root`
  (`lib/project_manager.py:289-312`, `375-390`), and the artifact manifest is
  `.arcreel_artifacts.json` within a project
  (`lib/artifact_manifest.py:52-58`, `593-637`). The current H6 integration
  fixture seeds two candidate objects and one master in one project
  (`tests/integration/r2/host_hardening/test_backup_restore_drill.py:180-235`);
  it does not establish an inventory of every Host project file. This is a
  source-backed reason that merely changing candidate selection from one
  project to all projects would still be insufficient.
- The V1 corpus calls for one real factual and one real drama product with
  selected media, playback, export and restart evidence
  (`docs/research/2026-09-17-r2-v1-production-readiness-v2-deferment.md:147-163`,
  `219-235`). The M3 real-media packet reports both local-rendered products
  with `external_provider_cost=0` (`docs/r2/evidence/R2_M3_REAL_MEDIA_CLOSURE.json:43-69`).
  But that packet also says paid production methods were not exercised
  (`:120-127`), and the M7-B packet says the M3 master flow was only a CLI,
  not a FastAPI caller (`docs/r2/evidence/R2_M7_B_ATOMIC_PROMOTION.json:44-53`).
  **Inference:** a no-paid-provider V1 is plausible, but its live operator/
  browser workflow still has to be implemented or proved on the release SHA.
- The runtime route selection is layered from project, task payload, and global
  settings (`lib/config/resolver.py:1273-1305`); selected backends are then
  assembled by `server/services/generation_context.py:92-111,358-365`.
  Built-in and custom paid asynchronous video families in the frozen inventory
  use the shared `submit_video_attempt()` path
  (`r2/host_hardening/route_inventory.py:42-101`;
  `lib/custom_provider/declarative_backend.py:401-449`), but its check currently
  defaults to `DEV` and taskless calls bypass the check entirely
  (`lib/video_backends/execution_adapter.py:133-149`). **Inference:** changing
  UI choices or deleting provider config is not a sufficient disable proof;
  the final submit seam needs an explicit, enforced release policy.
- Credential-bearing tables are broader than the two rows named earlier:
  `custom_provider.api_key` and `provider_config.value` with `is_secret` also
  exist (`lib/db/models/custom_provider.py:44-48`,
  `lib/db/models/config.py:20-24`). `api_keys` stores a hash and prefix, not a
  plaintext key (`lib/db/models/api_key.py:13-20`). **Inference:** a table-
  exclusion approach needs a full data-custody inventory, not a two-table
  shortcut; table-data exclusion cannot selectively remove only rows marked
  `is_secret` while retaining nonsecret rows from the same table. Whole-DB
  archives must be treated as secret-bearing unless proved otherwise.

### Alternatives compared against accepted constraints

1. **Recommended candidate: repair the existing write-fenced H6 module, then
   prove H7 and E1 on the same lineage.** Keep PostgreSQL as the DB authority
   and the existing project/manifest/master readers as file/reference
   authorities. Make the backup interface cover the whole deployment recovery
   boundary, enumerate and hash all project/formal files plus every DB-backed
   media/master reference, bind them under one externally enforced write/GC
   fence, and verify through real readers and media probes on a clean target.
   Treat the DB archive as secret-bearing with separately controlled storage
   and restore injection; correct the false secret-free runbook claim. This
   reuses accepted ADR-0078's initial write-fenced profile and existing
   modules, but its operational fence, custody and full-file inventory still
   need precise design and independent review. PostgreSQL itself cautions that
   `pg_dump` is generally not the regular-production-backup tool except in
   simple cases, so this recommendation is for the bounded V1 recovery drill,
   not an unproven ongoing RPO/RTO promise
   ([`pg_dump`](https://www.postgresql.org/docs/current/app-pgdump.html)).
2. **Narrow one-project backup while retaining whole-DB dump.** This minimizes
   code change but preserves a split scope, leaves other projects/formal files
   unrestorable and would change accepted H6/V1 semantics. Not recommended.
3. **Replace the first V1 drill with physical backup plus WAL/PITR.** This can
   reduce database RPO in a mature operation, but still needs the same external
   media coordination and adds WAL/archive/replay monitoring. ADR-0078 makes
   this conditional on measured RPO/RTO, not the baseline prerequisite
   (`docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md:72-79`;
   [`PostgreSQL continuous archiving`](https://www.postgresql.org/docs/current/continuous-archiving.html)).

For paid routes, the recommended *V1 design candidate* is a provider-free
profile for the two known corpus products, keeping every paid outbound path
disabled until a specific V1 path is independently qualified. This is broader
than M7's 11 asynchronous video submit families: `lib/backend_assembly/specs.py`
also registers image, audio and text providers, and
`lib/image_backends/dashscope.py:162-176` plus
`lib/audio_backends/dashscope.py:149-165` contain distinct outbound paid
calls. The exhaustive paid-path inventory and its disable tests therefore
remain open. For the inventoried video families, disabling must be enforced
at their common submit seam for both task-bound and taskless calls, with
production mode explicit and fail-closed; a configuration-only/UI-only disable
is weaker. This is not yet an assertion that the complete Host V1 workflow
works offline; the CLI-to-Host and browser gates above remain open. If V1
requires a paid route, qualify its exact provider/API/profile and separately
authorize credentials, a bounded canary and spend before enabling it.

The sequencing recommendation is to resolve M7-D H6/H7 findings before
accepting E1 or beginning E2: the M7-E plan explicitly requires independently
accepted `RECOVERY_VERIFIED` at entry
(`docs/superpowers/plans/2026-09-12-r2-m7e-production-candidate.md:18-24`).
Keep H7 within the current M7-D remediation because its later D3 plan demands
H1–H7, even though ADR-0078's minimum maturity definition places H7 at
`PRODUCTION_CANDIDATE` (`docs/superpowers/plans/2026-09-12-r2-m7d-backup-observability.md:64-79`;
`docs/adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md:136-138`).
After D is independently accepted, repair E1's source-to-host mapping,
semantic evidence validation and test-tier placement, then run restore-derived
Golden/browser gates on the integrated SHA. Do not treat passing tests or
committed self-reports as independent acceptance.

### Required decisions/evidence before implementation or release claims

- Approve the exact secret-custody policy for a whole-DB archive (encryption,
  key ownership, access, retention and isolated restore handling), and prove
  the operator can enforce the write/GC fence. This note does not choose a key
  provider or perform a backup.
- Confirm whether the bounded V1 release is permitted with **zero enabled
  paid routes**. ADR-0089 and the V1 strategy say qualify *or disable* each
  paid path, but the M7-E plan's `PRODUCTION_CANDIDATE` dossier says
  "qualified providers" (`docs/adr/0089-ship-a-bounded-v1-before-v2-portfolio-automation.md:44-48`;
  `docs/r2/R2_V1_PRODUCTION_RELEASE_STRATEGY.md:74-87,111-122`;
  `docs/superpowers/plans/2026-09-12-r2-m7e-production-candidate.md:5-24`).
  Reconcile that wording in a reviewed spec/acceptance packet rather than
  silently treating an empty qualified set as a pass.
- Re-run all dependent verification on exact clean lineage and obtain fresh
  independent reviews; previous override/self-review results are historical
  evidence, not an approval of this design or current implementation.
