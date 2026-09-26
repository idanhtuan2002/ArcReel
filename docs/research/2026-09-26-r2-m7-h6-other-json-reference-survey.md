# R2 M7 H6 V1-02: other project-local JSON reference survey

**Snapshot:** `b6d245ab0b2993c7a186cb703fb9999d484b8ed6` on 2026-09-26.

## Question and boundary

This note surveys remaining first-party, persisted, project-local JSON records
whose schema carries a reference to another project-local item or logical
resource. It excludes the already documented `project.json`, episode scripts,
Artifact Manifest, versions, grid, presentation, provider-media
staging/checkpoint, and quarantine-draft records.

The search boundary was Python source beneath `lib/`, `server/`, and `r2/` in
this worktree. It used a direct literal sweep for JSON filename construction,
`atomic_write_json`, `json.dump`, and `json.dumps`, then traced the retained
candidates to their writers and readers. The available code graph is for the
separate `content-production-os-m7` worktree at generation
`2026-09-18T10:57:40Z`; it supplied structural leads only. Direct source in
this worktree is the authority for the findings below.

This is a bounded positive survey, not an exhaustive absence claim. Dynamic
filename construction, unindexed/new code after that graph generation, and
records outside the stated source roots are coverage limits. Graph coverage
reported no recorded issue for the five source files cited below, but that is a
best-effort signal only; the scoped coverage gaps are excluded cache and
fixture subtrees.

## Retained records

### `.arcreel_profile_manifest.json`: references materialized profile paths

**Path and schema.** The record is at
`{project_dir}/.arcreel_profile_manifest.json` [lib/profile_manifest.py:3-10].
Its top-level fields are `schema_version`, `profile_id`, `entries`, and optional
`content_mode` [lib/profile_manifest.py:279-316]. Each `entries` key is a
logical relative destination path such as `CLAUDE.md` or a `.claude/**` member;
an active entry stores `sha256`, `size`, and `source: "profile"`, while a
tombstone stores `source: "tombstone"` and `deleted_at`
[lib/profile_manifest.py:431-436]. These keys are path-like references to the
project-local materialized files; they do not name generated-media artifacts.

**Writer and reader.** `sync_profile_to_project` loads the record, reconciles
the mapping, destination files, and recorded keys, and saves it after the
decision table runs [lib/profile_manifest.py:671-739]. A first materialization
or an invalid/mismatched manifest rebuilds the destination profile files and
writes a new manifest [lib/profile_manifest.py:496-545]; targeted restore also
updates its entries [lib/profile_manifest.py:799-853]. `load_manifest` parses
and shape-checks it [lib/profile_manifest.py:319-390], and
`get_profile_status` reads it to identify user customizations
[lib/profile_manifest.py:742-796]. `ProjectManager` provides the production
entry points for sync, restore, and status [lib/project_manager.py:464-511].

**Lifecycle and authority caveat.** This is a synchronization baseline for
built-in agent-profile files. It tracks file locations and content hashes only
for profile reconciliation; it neither claims nor authorizes the lineage,
currency, or promotion of project media. A profile or content-mode mismatch
causes a reset of the materialized profile destinations
[lib/profile_manifest.py:496-545; lib/profile_manifest.py:698-706], so an
entry is not a durable user-content reference.

### `.migration_failure.json`: references migration inputs that need repair

**Path and schema.** The record sits beside `project.json` as
`{project_dir}/.migration_failure.json` [lib/project_migration_failure.py:1-14;
lib/project_migration_failure.py:33]. `MigrationFailureRecord` stores
`schema_version`, `failed_at`, `reason`, and `details`; each detail may carry
an `episode`, path-like `file`, and `violation`
[lib/project_migration_failure.py:58-80]. The `file` value references the input
that the migration rejected (for example `project.json`), rather than a
produced artifact.

**Writer and reader.** `record_migration_failure` serializes the record through
an atomic temporary-file replacement [lib/project_migration_failure.py:153-172;
lib/project_migration_failure.py:222-235].
`migrate_project_with_verdict` writes it when the chain raises or fails to reach
the current schema, then clears it after a successful current-schema result
[lib/project_migrations/runner.py:206-239]. `load_migration_verdict` reads a
record first and otherwise constructs a pending verdict for an old schema
[lib/project_migration_failure.py:122-137; lib/project_migration_failure.py:190-219].
The shared guard converts that verdict into a generation refusal
[lib/project_migration_guard.py:21-44], and workflow status and summary read it
before continuing their normal computation [lib/workflow_state.py:945-958;
lib/workflow_state.py:977-982].

**Lifecycle and authority caveat.** The record is a blocking diagnostic about
migration inputs. Its own documentation says it blocks new generation but
leaves project reading and already visible canvas artifacts open
[lib/project_migration_guard.py:1-7]. It does not pin file contents or supply
artifact authority, so its `file` and `episode` fields are repair pointers, not
lineage evidence.

### `storyboards/generation_failures.json`: references storyboard unit IDs

**Path and schema.** The recorder targets
`{project_dir}/storyboards/generation_failures.json`
[server/media_tools/storyboards.py:55-60]. Each failure contains `resource_id`,
`type` (`segment` or `scene`), `error`, `attempts`, and `timestamp`; the outer
object adds `generated_at`, `total_failures`, and `failures`
[server/media_tools/storyboards.py:63-87]. `resource_id` is an opaque
storyboard-unit reference rather than a filesystem path or artifact key.

**Writer and reader.** `handle_generate_storyboards` constructs the recorder
only after batch submission returns successes/failures, records each returned
failure, and saves the JSON under the project directory
[server/media_tools/storyboards.py:214-245]. Within the bounded direct search,
the only first-party occurrences of the filename/recorder were this
construction and write site; no reader was located. It should therefore be
treated as persisted diagnostics, not a record consumed by the project model.

**Lifecycle and authority caveat.** `save()` overwrites the file only when the
in-memory batch has failures [server/media_tools/storyboards.py:77-87]. A later
all-success batch neither writes nor clears it, so the on-disk failures can be
stale. The record has no hash, artifact key, or verification state and cannot
establish media lineage or authority.

## Non-retained nearby candidates

- `lib/custom_provider/endpoint_test/trial_run.py` persists `result.json` under
  `app_data_dir()/trial_runs`, not under a project directory
  [lib/custom_provider/endpoint_test/trial_run.py:192-215;
  lib/custom_provider/endpoint_test/trial_run.py:289-303].
- Archive, presentation bundle, and Jianying JSON are export/package outputs;
  presentation and Jianying are already excluded by this survey's boundary.
- The remaining JSON writes found in the stated roots either update one of the
  excluded schemas, are configuration/fixture material, or do not carry a
  project-local path or resource reference.
