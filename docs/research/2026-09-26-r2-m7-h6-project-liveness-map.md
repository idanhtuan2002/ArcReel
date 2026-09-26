# R2 M7 H6: project liveness versus project-scoped DB evidence

Date: 2026-09-26
Source survey: `feat/r2-m7e-v1-lineage` at `3875a797`.

Status: research input only. This note does not select a retention/deletion
policy, alter deletion behavior, or approve an H6 schema/capture adapter.

## Finding

The bounded `lib/db/models/` survey found no database `projects` registry or
DB deletion path in the API project-delete route. The Host's project API uses
filesystem predicates: `get_project_path()` resolves a valid name to an
existing path but does not itself assert that it is a directory, while
`project_exists()` additionally requires `project.json`;
ordinary creation publishes that file. Neither predicate is a durable
database lifecycle registry. In contrast, every row
below is scoped by `(user_id, project_name)` or carries a project-derived
reference, but none has a foreign key to a project lifecycle row. Therefore a
row with a project name cannot, by itself, prove that that project is live for
API admission after directory deletion.

This is deliberately narrower than saying the rows are unimportant: several
are current authority for *content, execution, or recovery* within a supplied
project scope. Their retained value after deletion is the unresolved policy
question.

## Current row map

| Class / table / fields | What can be current authority | Demonstrable predicate | Why it is not live-project authority / counterexample |
| --- | --- | --- | --- |
| No project ORM class/table; filesystem `ProjectManager` / `projects/<name>/project.json` | The present project existence checks are filesystem-based. `get_project_path()` normalizes the name and requires the path to exist; creation normally writes `project.json`. | A candidate live directory must be separately checked as a directory with a valid name; `project_exists()` additionally requires `project.json`. | `get_project_path()` alone accepts any existing path; `list_projects()` merely lists non-`.`/`_` directories and does not validate or require `project.json`; `create_project(..., publish=False)` permits a transient directory. Thus the backup predicate must be selected explicitly. |
| `Task` / `tasks` / `project_name`, `status`; `GenerationBatch` / `batches` | Queue work and batch history in a project scope. | The active-task dedupe index covers `queued`, `running`, and `cancelling`; this is an operational predicate, not a project-existence predicate. | A task may remain in an active state when the delete route removes its directory; completed batches/tasks are historical. Neither table has a project-lifecycle FK. |
| `ApiCall` / `api_calls` / `project_name`, `status`, `output_path` | Usage/cost and provider-call history; `output_path` can originate from a real media-generation output. | `pending` is the schema default; success/failure settlement is recorded separately. The usage repository uses historical paths for cost grouping. | A cost row or its path is not proof that a project directory or that exact output file still exists. See the companion inventory note for path-classification evidence. |
| `AgentSession` / `agent_sessions` / `project_name`, `status`, `superseded_by` | Session history and a current/idle session pointer. | `status` defaults to `idle`; `superseded_by` marks a replaced branch session. | A session may reference a removed project, and API project deletion does not retire it. Session status cannot establish project existence. |
| `ExecutionAttemptModel` / `execution_attempts` / `project_name`, `state`, `terminal_at`, lease fields | Current execution/recovery state for its attempt identity. | Non-terminal iff `state` is not `SUCCEEDED`, `FAILED_BEFORE_ACCEPTANCE`, `FAILED`, or `CANCELLED`; the table CHECK also requires terminal timestamp iff terminal. | A non-terminal attempt evidences work needing handling, not a surviving project directory. API deletion does not inspect it. Its append-only children—`ProviderObservationModel`/`provider_observations`, `AttemptIntegrityIncidentModel`/`attempt_integrity_incidents`, `OperatorResolutionReceiptModel`/`operator_resolution_receipts`, `CommandReceiptModel`/`command_receipts`, and `ProjectEventModel`/`project_events`—are evidence/projections tied to attempts or commands, never a project registry. |
| `MasterAuthorityModel` / `master_authorities` / `project_name`, `artifact_key`, `current_version` | Mutable selected-master pointer per scoped artifact. | `current_version > 0` means a promoted version exists; zero is explicitly no promoted version. | It establishes selected media authority, not project existence. `CandidateObjectModel`/`candidate_objects`, `MasterHeadVersionModel`/`master_head_versions`, and `PromotionReceiptModel`/`promotion_receipts` preserve immutable candidate/promotion lineage, so they are counterexamples to treating all named rows as deletable live state. |
| `BackupSetModel` / `backup_sets` / `project_name`, `state`; `BackupSetMediaRefModel` / `backup_set_media_refs` | Retention/recovery record and its retained candidate references. | State domain is `PREPARING`, `COMPLETE`, `VERIFIED`, `REJECTED`; no source proves that any state means a live filesystem project. | A verified backup can be valuable historical recovery evidence after deletion; a preparing record may require an explicit operation disposition. Neither is consulted by API project deletion. |
| `CanonBranchModel` / `canon_branches` / `project_name`, `head_version_id`; `CanonDeltaModel` / `canon_deltas`; `CanonVersionModel` / `canon_versions` | Canon selection/history. The module describes accepted deltas and immutable versions as authority; branch head is the logical selection pointer. | A branch can have `head_version_id`; one `MAIN` branch is constrained per `(user_id, project_name)`. | The pointers intentionally lack the project lifecycle FK and history relationships are `RESTRICT`; `CanonResolvedProjectionModel` / `canon_resolved_projections` is explicitly disposable cache. A canon row can therefore survive a deleted directory without proving it must be revived as a live project. |
| `NarrativePlanModel` / `narrative_plans` / `project_name`, `head_version`; `NarrativePlanVersionModel` / `narrative_plan_versions` | Logical plan head and approved plan-version history. | `head_version` is nullable; version rows require `approval_status = APPROVED`. | These are content authority in project scope, not creation/deletion authority. No deletion route examines them. |
| `AdaptationHeadModel` / `adaptation_heads` / `project_name`, `generation`, `latest_decision_id`, `effective_decision_id`; `AdaptationDecisionModel` / `adaptation_decisions` | Mutable/rebuildable selection head plus append-only decision chain. | Generation zero is an internal genesis sentinel; a public head exists only once generation is at least one. | This can establish the effective adaptation choice only after an already-supplied project scope. Related branch/map/screenplay/profile/report/admission rows—`AdaptationBranchModel`, `AdaptationMapModel`, `AdaptationScreenplayModel`, `AdaptationProfileSidecarModel`, `AdaptationEvaluationReportModel`, `AdaptationEvaluationFindingModel`, and `AdaptationScreenplayAdmissionModel`—are versioned/evidence rows, not a project registry. |
| Narrative lifecycle heads/decisions: `RevisionAcceptanceHeadModel`, `ChangeSetReviewHeadModel`, `ConflictResolutionHeadModel`; their decision/attempt/result/admission tables in `narrative_lifecycle.py` | Current effective review/acceptance/conflict choices within the narrative domain. | Head rows carry `project_name` and link by `RESTRICT` to the applicable decision/inputs; exact live-project predicate is not defined by the source. | Drafts, revisions, extraction/change-set rows, decisions, compilation rows and handoff admissions are authoritative historical content/evidence in a supplied scope. No model relates them to `projects/<name>` or API deletion. |
| `GreenlightDecisionModel` / `gate_greenlight_decisions`; `PublishApprovalDecisionModel` / `gate_publish_approval_decisions`; `FinalCutReceiptModel` / `gate_final_cut_receipts` | Append-only human gate/receipt history. | Per-project monotonic `sequence`; the source says Gate A has no separate current-effective pointer. | A prior approval or receipt is not a liveness registration; it may be audit evidence after project deletion. |
| `Asset` / `assets` / nullable `source_project`, `image_path`, `audio_path`; `AssetDerivative` / `asset_derivatives` | Global asset library record, outside a project directory. | No liveness predicate: `source_project` is nullable provenance and the uniqueness key is `(type, name)`, not project scope. | Strong counterexample: it may name a deleted project yet be globally shared; it cannot establish the named project as live. |

The adaptation/narrative groups above include their companion rows with the
same project-scoped foreign-key chains (map entries and references; narrative
draft/revision/extraction/change-set/decision/compilation/handoff rows). They
are grouped to avoid falsely promoting every evidence table to a separate
project lifecycle class. This is a source taxonomy, not a migration inventory.

## What API deletion actually does

`DELETE /api/v1/projects/{name}` runs a synchronous helper in a thread and
calls only `get_project_manager().delete_project_directory(name)`.
`delete_project_directory()` resolves the directory through `get_project_path`
and recursively removes it, retrying only `ENOTEMPTY`/`EACCES` races. It does
not open a DB session, write a tombstone, retire a row, cancel attempts, or
remove scoped rows. A missing directory yields the route's `project_not_found`;
the deletion helper treats a concurrently-missing target as already deleted.

Consequences demonstrated by the code:

- Deleting a directory can leave all database evidence carrying its name.
- The inverse is possible too: a directory can be filesystem-only or
transient, because creation can defer `project.json` publication.
- Therefore an unconditional equality check between directory names and DB
project names would reject normal post-delete history as corruption; ignoring
all DB-only names could instead conceal an interrupted/live operational case.

## Follow-up: the directory helper has two different call intents

The current-worktree call-site check found a second production caller of
`delete_project_directory()`: `server/tool_runtime.py:1171-1183` invokes it
only when composed project creation fails after `create_project(...,
publish=False)`. That is rollback of an unpublished directory, not a user
request to delete a previously live project. The API delete route is at
`server/routers/projects.py:1101-1116`; the helper itself is at
`lib/project_manager.py:447-462`. An H6 tombstone or retention disposition
must therefore attach to an explicit published-project deletion command,
not indiscriminately to the low-level directory-removal helper. The helper
can remain a physical operation used by failed-create rollback. This
additional caller was discovered from the indexed M7 graph and verified
against the current worktree; the graph is from a different, older worktree,
so the current source is authoritative.

## Follow-up: HTTP creation has an intermediate metadata file

The HTTP route calls `create_project()` with its default `publish=True` and
then separately calls `create_project_metadata()`
(`server/routers/projects.py:688-716`). The first call writes a minimal
`project.json` containing only `content_mode`; the second constructs the
current schema metadata and saves it in a later write
(`lib/project_manager.py:400-438,2436-2443,2505-2507`). A process stop or
error between the calls can therefore leave a directory with an existing
`project.json` that is not the completed HTTP creation result. The separate
composed Agent tool uses `publish=False` and rolls back its unpublished
directory on failure (`server/tool_runtime.py:1163-1183`). These are two
distinct intermediate states; neither a bare directory nor mere metadata
file presence proves finished publication. The candidate admission matrix
below must read "valid published project" as an independently checked
schema/lifecycle predicate, not `project_exists()` alone. Historical schema
versions need a read-only compatibility rule or an inspected pre-capture
migration; capture must not mutate the source to make it appear current.

## Follow-up: archive import can replace a published directory

`POST /api/v1/projects/import` passes the caller's `conflict_policy` to
`ProjectArchiveService.import_project_archive()`
(`server/routers/projects.py:309-344`). The service accepts `overwrite` and,
when the target exists, reports `overwritten` before installing the staged
tree (`server/services/project_archive.py:315-323,409-423,1930-1950`). Its
installer renames the old target to a hidden `.import-backup-*` sibling, moves
the staged directory into the same name, syncs the profile, copies back
project memory, and then removes the sibling. On an ordinary exception it
deletes the new target and renames the sibling back
(`server/services/project_archive.py:1956-1987`). Integration tests exercise
replacement and exception rollback
(`tests/integration/server/services/test_project_archive_service.py:1466-1486,1646-1702`).

This route does not call `delete_project_directory()` or the API deletion
route. A process stop after the first rename can leave no target directory
while the old bytes survive under the hidden sibling; a stop after moving the
staged tree can leave a new tree at the old name and the old one hidden. The
rollback in source handles raised exceptions, not a stopped process. These
are crash-window inferences from the ordered file operations, not observed
runtime incidents. Neither condition permits a capture to infer project
deletion, publication, or same-identity continuity from the target name alone.
The candidate lifecycle protocol therefore needs a distinct import-replace
intent, a fence against capture and active work for the target identity, and
an inspected reconciliation rule for hidden siblings. New-name import also
needs to reject a previously retired name under the proposed no-reuse rule.
The source's `project_metadata_lock` use in this service wraps export's
visible-tree copy (`:654-685`), not the import installation (`:1956-1987`),
so that existing lock cannot be counted as an import/capture lifecycle fence.

## Follow-up: v5-to-v6 migration swaps the whole project tree

The v5-to-v6 migrator copies the project to a hidden staging sibling, transforms
that copy, renames the original to a hidden rollback sibling, and renames the
staging tree to the original name
(`lib/project_migrations/v5_to_v6_asset_namespace.py:584-614`). A process stop
between renames leaves the target name absent with a rollback tree present;
after the second rename the target and rollback can both exist. Startup
`run_project_migrations()` calls `reclaim_interrupted_swaps()` before scanning
projects; the helper restores a rollback sibling only if the target is absent
(`lib/project_migrations/runner.py:242-255`;
`lib/project_migrations/staged_swap.py:90-126`). Later cleanup can remove old
staging/rollback siblings when a target exists (`staged_swap.py:129-149`).

These are migration intermediate states, not evidence of published deletion.
The candidate backup census must identify recognized hidden swap siblings and
their target names, block while a swap is active or unresolved, and require an
inspected recovery/disposition before capture. It cannot invoke startup
reclaim or migration during a read-only source snapshot. A future lifecycle
fence must cover this whole-tree writer as well as import overwrite. The
current source's reclaim rule depends on filesystem presence and naming; it
does not provide an H6 signed lifecycle record.

## Candidate policies (not approved)

1. **Filesystem-primary deletion with a durable DB tombstone.** A valid
directory is live; deletion creates a separately governed tombstone and
retires/records the disposition of outstanding operational rows. This makes
post-delete evidence distinguishable from corruption, at the cost of a new
transactional lifecycle boundary and migration.
2. **Deletion admission gate.** Refuse or pause directory deletion while a
scoped operational predicate holds (for example a non-terminal attempt or
`PREPARING` backup); retain authority/evidence rows indefinitely otherwise.
This reduces ambiguous external work, but changes current API semantics and
still needs an explicit policy for terminal masters, canon, and approvals.
3. **Split live registry from evidence and reconcile fail-closed.** Add an
explicit project lifecycle registry; classify every named row as active,
retired, or historical against it during capture/restore. This gives the
strongest inventory proof, but is the broadest schema/API migration and needs
complete write-route, retention, and restore semantics before implementation.

For the narrow single-operator V1, the provisional recommendation is a
two-phase, explicit deletion admission plus durable tombstone, rather than
turning every historical project-scoped row into a live-project registry.
The dedicated delete command would first fail closed on non-terminal work
(at minimum a `queued`/`running`/`cancelling` Task, a non-terminal execution
attempt, unresolved `PREPARING` backup or active recovery lease), durably
record a deletion intent keyed by normalized
project identity, then remove the published directory, and finally mark the
tombstone terminal. Capture would admit a directory only when it is a valid
published project (`project.json` present) with no deletion intent, classify
a DB-only identity with a terminal tombstone as historical, and reject a
DB-only identity without one as ambiguous rather than silently inventing a
deleted project. An in-progress intent, directory-only identity, conflicting
identity reuse or interrupted delete also rejects capture until inspected
disposition. This is a *candidate*, not a selected schema or an instruction
to delete files: the transaction/crash matrix, name-reuse policy and exact
row predicates still need review. Existing DB-only identities predate such
tombstones and cannot be backfilled by guessing from current absence; they
need explicit inspected classification evidence or remain a typed rejection.

Proposed capture-admission matrix for review (all codes and predicates are
candidate contract values, not implemented behavior):

| Directory / `project.json` | Deletion record | Project-scoped DB rows | Proposed capture result |
| --- | --- | --- | --- |
| Present, independently validated published project | None | Any consistent scoped rows | Admit as live; inventory directory and all its reference-bearing rows. Mere `project.json` existence is insufficient. |
| Present, valid published project | Intent or terminal tombstone | Any | Reject `BACKUP_PROJECT_LIFECYCLE_CONFLICT`; a stale or reused name must not silently become live. |
| Absent | Terminal tombstone for exact project identity | Historical rows only | Preserve rows in the whole DB dump, but do not fabricate project files or live project admission. Current mutable heads and non-terminal work still require explicit disposition. |
| Absent | No tombstone or intent | Any scoped row | Reject `BACKUP_PROJECT_LIVENESS_AMBIGUOUS`; legacy evidence must be inspected, never guessed from absence. |
| Present directory, absent/minimal/invalid `project.json` | Any | Any | Reject `BACKUP_PROJECT_UNPUBLISHED`; this may be interrupted creation or damaged published data. |
| Absent or present | Non-terminal deletion intent | Any | Reject `BACKUP_PROJECT_DELETION_INCOMPLETE` until inspected recovery/disposition. |

The exact identity key must prevent a deleted project's old evidence being
silently rebound to a new project with the same name. Either disallow name
reuse in V1 or add a durable generation/ID to all relevant write and restore
authorities; a name-only tombstone cannot safely support reuse. The simpler
V1 candidate is no name reuse after published deletion, with a distinct
failed-create rollback that leaves no tombstone. A legacy DB-only disposition
would require a signed, independently stored `LegacyProjectDispositionV1`
bound to source deployment, normalized name, inspected row IDs/states and
evidence digest; the reviewer must decide whether this suffices for capture
or whether the source must first be repaired. Neither option is silently
selected here.

### Crash and race matrix for the candidate

This matrix refines the two-phase tombstone candidate for review; it does not
assert that the current API implements any row or lock below. A candidate
lifecycle key is `(source_deployment_id, normalized_project_name)` because the
filesystem root is keyed by name while current domain rows additionally carry
their own `user_id` (`lib/project_manager.py:418-424`;
`lib/db/models/host_hardening.py:60-67`). Every scoped row belonging to that
name, across users, needs an explicit disposition. No name reuse is the
candidate V1 rule, including after terminal deletion.

| Point reached | Durable candidate state | Directory / metadata may show | Capture and retry consequence |
| --- | --- | --- | --- |
| HTTP create writes its minimal metadata but has not saved the complete schema | No lifecycle row in the narrow tombstone design | Directory and `project.json` exist, but metadata contains only `content_mode` | Reject as unpublished; a retry may repair or remove only after inspecting the intermediate state. |
| Delete command passes a complete active-work check and records intent, before physical removal | `DELETING` intent with expected project identity and command ID | Complete directory may remain | Block capture, same-name creation and another destructive command; resume or dispose the exact intent. |
| Removal has started, including partial `rmtree` or process loss | Same `DELETING` intent | Partial or absent directory | Block capture and same-name creation. Do not infer completion from absence alone. |
| Directory removal finishes, before terminal marker commits | Same `DELETING` intent | Directory absent | Retried command may finish the same intent idempotently after checking the exact identity; a new command may not create a second intent. |
| Terminal marker commits after removal | `RETIRED` tombstone | Directory absent | Preserve DB history as historical only after required operational dispositions; reject future same-name creation. |
| Overwrite import claims the exact existing identity, before renaming the target | Distinct `REPLACING` intent with target identity and staged archive identity | Published target and validated staging tree may both exist | Block capture, deletion and conflicting writers until a single replacement result is known. The current route has no such intent. |
| Overwrite import has renamed the target to `.import-backup-*`, before installing the staged tree | Same `REPLACING` intent | Target name absent, old bytes under a hidden sibling | Block capture; do not classify the DB name as deleted or the sibling as an unrelated orphan. |
| Overwrite import has installed the new tree, before backup cleanup and terminal record | Same `REPLACING` intent | New tree at target name, old bytes under hidden sibling | Block capture; determine whether to complete or roll back from exact staged/old identities before releasing the name. |
| New-name import has installed the tree but stopped before a publication record | Candidate creation/import intent, if adopted | Valid metadata may exist without proven lifecycle publication | Block capture until the source tree and identity are reconciled; a retired name must remain reserved. |
| v5-to-v6 migration has renamed the original to hidden rollback, before moving staging into place | Candidate migration/swap intent or observed unresolved swap | Target absent; `.<name>.v6-rollback-*` and perhaps staging sibling present | Block capture; do not classify name as deleted or infer which tree is current. |
| v5-to-v6 migration has installed staging, before rollback cleanup | Same migration/swap state until a verified completion boundary | Target and hidden rollback sibling present | Block capture or verify an approved completion/disposition rule before excluding the sibling. |
| Metadata/directory diverges without a matching intent or terminal tombstone | None or contradictory state | Missing, minimal, malformed or reused identity | Reject capture with typed ambiguity/corruption evidence; no name-only historical inference. |

The intent must be durably recorded **before** `rmtree`; a normal database
transaction cannot atomically include filesystem removal. The active-work
predicate and intent claim need one serialized admission boundary, otherwise
a task or backup can start between the check and the intent. Finalizing the
tombstone after absence needs an independently inspectable audit record. A
capturing source must observe the exact lifecycle version under its signed
write fence and recheck it before closure. The current creation and deletion
routes have no such shared boundary
(`server/routers/projects.py:688-716,1100-1116`;
`server/tool_runtime.py:1163-1183`). The overwrite import installer also has
no shared lifecycle boundary (`server/services/project_archive.py:1956-1987`).
These are candidate invariants and tests,
not implementation authorization.

The task predicate must not be inferred solely from execution attempts:
`Task.status` has a separate active unique-index domain of `queued`,
`running`, and `cancelling` (`lib/db/models/task.py:13-68`), while attempt
states/terminal timestamps are independently constrained
(`lib/db/models/host_hardening.py:38-42,73-107`). The inspected declarations
do not require a matching attempt for every active Task, and the two rows may
diverge after interruption; treating either
table as a complete proxy would leave a deletion race. A candidate gate should
read both scoped predicates and block on either active result, then require
an explicit inspected disposition for contradictory or stale states. The
current delete route reads neither table (`server/routers/projects.py:1100-1116`).

## Unknowns and required decision checks

- No source inspected defines a durable project tombstone, retirement state,
or DB transaction coupling API delete to execution, master, canon, adaptation,
narrative, or gate rows.
- The intended disposition of non-terminal attempts, `PREPARING` backups,
and current master/canon/narrative heads at deletion is not specified.
- A database-level inventory was not queried; this note classifies model and
route behavior, not existing production rows.
- Before freezing H6 inventory/capture, select the authoritative filesystem
  predicate, enumerate all affected write/delete/replace routes (including
  failed-create rollback, archive overwrite and v5-to-v6 migration swap), define typed
filesystem-only/DB-only/tombstoned cases, and add adversarial tests. This is
the unresolved gate already required by the recovery-closure design.

## Sources and method

First-party source only. Structural discovery used codebase-memory project
`home-anhtuan-content-production-os-m7` (generation
  `2026-09-18T10:57:40Z`), then direct-read source where graph coverage was
  stale/changed. `check_index_coverage` reported no recorded issue for the
  named model/route paths, but `host_hardening.py`, `api_call.py`,
  `usage_repo.py` and `transitions.py` were metadata-changed and `gates.py`
  was not tracked; their claims above are from direct source. This is a
  source-code survey, not a live-database audit.

- `server/routers/projects.py:1101-1116`;
  `server/routers/projects.py:309-344`;
  `server/services/project_archive.py:315-423,1930-1987`;
  `tests/integration/server/services/test_project_archive_service.py:1466-1486,1646-1702`;
  `lib/project_migrations/v5_to_v6_asset_namespace.py:584-614`;
  `lib/project_migrations/staged_swap.py:90-149`;
  `lib/project_migrations/runner.py:242-255`;
  `server/tool_runtime.py:1160-1183`;
  `lib/project_manager.py:388-438,447-462,601-611,1852-1857`.
- `lib/db/models/host_hardening.py:1-12,38-107,230-287,293-460`; `r2/host_hardening/transitions.py:30-90`.
- `lib/db/models/task.py:12-104`; `lib/db/models/api_call.py:14-55`;
  `lib/db/models/session.py:11-34`;
  `lib/db/repositories/usage_repo.py:116-130,395-440,747-772`.
- `lib/db/models/canon.py:1-138`; `lib/db/models/narrative_plan.py:33-82`.
- `lib/db/models/adaptation.py:313-435`; `lib/db/models/narrative_lifecycle.py:745-1315`; `lib/db/models/gates.py:36-140`.
- `lib/db/models/asset.py:11-47`; prior H6 inventory research at
  `docs/research/2026-09-26-r2-m7-h6-project-inventory-authority.md:24-174`;
  recovery-closure gate at
  `docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md:671-680`.
