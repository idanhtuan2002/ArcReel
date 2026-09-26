# R2 M7 H6: project liveness table

Date: 2026-09-26
Scope: bounded V1-01 research on the current `feat/r2-m7e-v1-lineage`
worktree. This note makes no lifecycle, retention, schema, or capture-policy
decision.

This table expands the existing [liveness map](2026-09-26-r2-m7-h6-project-liveness-map.md)
with explicit direct and selected indirect ORM row identities. The earlier
map contains candidate tombstone and capture-admission policies; neither note
is an approval or evidence of live database contents.

## Required question

H6 design section 8 requires an approved table of project-scoped DB rows,
their live-versus-historical predicates, deletion/tombstone or retirement
semantics, and handling for filesystem-only and DB-only identities before the
V1 inventory/manifest or capture adapter is frozen
(`docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md:839-855`).

### Confirmed facts

- The current project identity is filesystem based. `list_projects()` lists
  visible child directories; `get_project_path()` validates a name and only
  requires the resulting path to exist; `project_exists()` additionally
  requires `project.json`. HTTP creation first writes a minimal
  `{"content_mode": ...}` file and only later saves complete schema metadata;
  `publish=False` deliberately permits an unpublished directory in the Agent
  creation route (`lib/project_manager.py:388-390,400-438,601-610,2436-2454,2505-2507`;
  `server/routers/projects.py:688-716`; `server/tool_runtime.py:1163-1183`).
- The API deletion route calls only `delete_project_directory()`, which
  recursively removes the resolved directory. It has no DB session or row
  operation in that route/helper (`server/routers/projects.py:1100-1116`,
  `lib/project_manager.py:447-462`). The other production caller is failed
  composed creation after `publish=False`, where it removes the unpublished
  directory (`server/tool_runtime.py:1157-1183`).
- Archive import is a separate replacement route. With `overwrite`, the
  installer renames an existing target to `.import-backup-*`, installs the
  staged tree under the same name, then deletes the hidden old tree; exception
  rollback restores it (`server/routers/projects.py:309-344`;
  `server/services/project_archive.py:1930-1950,1956-1987`). Process loss
  between those operations is not covered by that exception handler.
- The v5-to-v6 migrator is another whole-tree writer: it copies to a hidden
  staging sibling and swaps the project directory through a hidden rollback
  sibling. Startup has a presence-based reclaim path for an interrupted swap
  (`lib/project_migrations/v5_to_v6_asset_namespace.py:584-614`;
  `lib/project_migrations/staged_swap.py:90-149`;
  `lib/project_migrations/runner.py:242-255`). This is not a durable H6
  lifecycle record and capture must not invoke that repair path.
- The bounded direct-field scan below found project naming in the listed ORM
  modules. There is no `Project` ORM/table in that scope. This is a bounded
  model-source observation, not a claim about a live database, migrations,
  future modules, or an external registry.

## Current liveness table

`Current predicate` means a source-enforced predicate for the row's own
domain. It does **not** mean a predicate that proves an API project is live.
`No project-liveness predicate` records that the inspected declarations and
the current delete route do not provide one.

| Row type(s), exact current scope | Current predicate / authority fact | Present deletion, tombstone, or retirement semantics | Liveness result |
| --- | --- | --- | --- |
| No DB project row; directory plus `project.json` | Filesystem predicates above; `project_exists()` is metadata-file existence, while `get_project_path()` accepts any existing resolved path. | API delete removes the directory only. Failed-create rollback uses the same low-level remover before publication. | **Fact:** filesystem identity and DB identity are not presently unified. A valid published-directory predicate is not selected by this note. |
| `Task` / `tasks`; `GenerationBatch` / `batches`; `BatchTask` links the two | Both first two rows carry `project_name`. The active-task unique index is limited to `queued`, `running`, and `cancelling` (`lib/db/models/task.py:13-92`). | No project lifecycle FK or delete behavior appears in these declarations or the delete route. | Active task status is an operational predicate only; it cannot prove directory liveness. Completed rows can be historical. |
| `ApiCall` / `api_calls` | `project_name`, `status` (default `pending`), and nullable `output_path`; an optional composite FK attaches an execution ID to an execution attempt with `RESTRICT` (`lib/db/models/api_call.py:14-63`). | No project retirement/tombstone in the inspected path. | A call row is usage/accounting evidence, not project registration. `output_path` requires separate file-authority classification; the companion inventory research records it as unresolved (`docs/research/2026-09-26-r2-m7-h6-project-inventory-authority.md:78-112`). |
| `AgentSession` / `agent_sessions`; indirectly keyed `AgentSessionEventLogEntry` and `AgentSessionUserMessageLink` | The session has `project_name`, `status` defaulting to `idle`, and optional `superseded_by` branch pointer (`lib/db/models/session.py:11-32`). The event and message-link tables carry `session_id` without their own `project_name` (`lib/db/models/session_event.py:11-45`; `lib/db/models/session_message_link.py:11-30`). | No project delete/retirement behavior in the inspected route or models. | Session state/pointer is session-domain state, not project liveness. Child rows need a session join for project attribution; they must not be silently treated as global. |
| Execution/replay evidence: `ExecutionAttemptModel`, `ProviderObservationModel`, `AttemptIntegrityIncidentModel`, `OperatorResolutionReceiptModel`, `CommandReceiptModel`, `ProjectEventModel` | All carry `project_name`. Attempt state is constrained; terminal states are `SUCCEEDED`, `FAILED_BEFORE_ACCEPTANCE`, `FAILED`, `CANCELLED`, and `terminal_at` is present iff terminal (`lib/db/models/host_hardening.py:38-42,50-107`). Child evidence rows scope to attempts with `RESTRICT`; command receipts and events have their own durable identities (`:110-290`). | No project lifecycle FK, tombstone, cancellation, or retirement is invoked by API deletion. | Non-terminal attempt/lease evidence may require an operational disposition, but is not proof that its directory remains live. Append-only evidence may remain historical. |
| Candidate/master lineage: `CandidateObjectModel`, `MasterAuthorityModel`, `MasterHeadVersionModel`, `PromotionReceiptModel` | All are project scoped. Candidate objects are immutable after insert; master authority is the mutable selected pointer and `current_version = 0` means no promotion; versions/receipts retain promoted lineage (`lib/db/models/host_hardening.py:293-416`). | Candidate references in versions/receipts use `RESTRICT`; no project-level retirement is defined in the inspected source. | Current master is authority for an already supplied project scope, not a live-project registry. Immutable lineage is a counterexample to discarding every DB-only named row. |
| Backup lineage: `BackupSetModel` and indirect `BackupSetMediaRefModel` | A backup set carries `project_name` and state in `PREPARING`, `COMPLETE`, `VERIFIED`, `REJECTED`; each media ref is scoped through its `backup_set_id` and retains its candidate with `RESTRICT` (`lib/db/models/host_hardening.py:419-460`). | Media refs cascade only when their backup-set row is deleted. The API project delete does neither. | No backup-set state is defined as project liveness. A row can be recovery/retention evidence after directory removal; `PREPARING` needs an explicit future disposition. |
| Canon: `CanonBranchModel`, `CanonDeltaModel`, `CanonVersionModel`, `CanonResolvedProjectionModel` | Branch and delta carry `project_name`; version is scoped through its branch and committed delta, and projection through its version (`lib/db/models/canon.py:33-138`). The branch has a scoped one-`MAIN` constraint and a head pointer; projection is a cache. | Relationships use model-local constraints; no project lifecycle deletion/tombstone is present in the inspected files. | Canon currentness is canon-domain authority, not filesystem liveness. A branch/head or historical delta cannot establish that the directory exists. |
| Narrative plan: `NarrativePlanModel`, `NarrativePlanVersionModel` | Both carry `project_name`; the plan has nullable `head_version` and approved versions are constrained by their own approval status (`lib/db/models/narrative_plan.py:33-82`). | No project retirement path in the inspected route/models. | Plan head/version status is content authority within a supplied scope, not project liveness. |
| Adaptation: `AdaptationBranchModel`, `AdaptationMapModel`, `AdaptationMapProfileAnalysisRefModel`, `AdaptationMapEntryModel`, `AdaptationScreenplayModel`, `AdaptationScreenplayProfileAnalysisRefModel`, `AdaptationScreenplaySceneModel`, `AdaptationDecisionModel`, `AdaptationHeadModel`, `AdaptationProfileSidecarModel`, `AdaptationEvaluationReportModel`, `AdaptationEvaluationFindingModel`, `AdaptationScreenplayAdmissionModel` | Every listed model carries `project_name`; the declaration ranges identify heads, decisions, versioned/map/screenplay records, evaluation records, and admissions (`lib/db/models/adaptation.py:56-588`). | No project lifecycle relation, delete, tombstone, or retirement is defined by the inspected declarations/delete route. | An adaptation head can select adaptation-domain state; it does not register a live filesystem project. The other rows can be evidence/history. |
| Narrative lifecycle: `NarrativeDraftCandidateModel`, `NarrativeRevisionModel`, `NarrativeExtractionAttemptModel`, `NarrativeExtractionResultModel`, `NarrativeChangeSetModel`, `NarrativeExtractionResultChangeSetModel`, `NarrativeDecisionIdentityModel`, `RevisionAcceptanceDecisionModel`, `ChangeSetReviewDecisionModel`, `ConflictResolutionLineageModel`, `ConflictResolutionDecisionModel`, `ConflictResolutionDecisionCompetitorModel`, `RevisionAcceptanceHeadModel`, `ChangeSetReviewHeadModel`, `ConflictResolutionHeadModel`, `NarrativeCompilationAttemptModel`, `NarrativeCompilationSelectedChangeSetModel`, `NarrativeCompilationConflictResolutionModel`, `NarrativeCompilationObservedHeadModel`, `NarrativeCompilationResultModel`, `NarrativeCompiledCanonDeltaModel`, `NarrativeHandoffAdmissionModel`, `NarrativeHandoffAdmissionObservedHeadModel` | Each listed row carries `project_name`; it contains local heads, decisions and immutable/ordered admission and compilation evidence with model-local `RESTRICT` relationships (`lib/db/models/narrative_lifecycle.py:50-1319`). | No project lifecycle FK/tombstone/retirement is specified in these declarations or called by project delete. | Head/decision currentness establishes only narrative-domain effective state. The remaining rows can be historical evidence; none proves directory liveness. |
| Human gate records: `GreenlightDecisionModel`, `PublishApprovalDecisionModel`, `FinalCutReceiptModel` | Each record carries `project_name`; the model records gate decisions/receipts and per-project sequencing (`lib/db/models/gates.py:36-140`). | No project delete/retirement semantics in the inspected sources. | Prior approval/receipt is evidence, not a project-liveness registration. |
| Global library counterexample: `Asset` / `assets`, `AssetDerivative` / `asset_derivatives` | These are **not project-scoped**: `Asset.source_project` is nullable provenance, and identity is global by `(type, name)`; derivatives belong to assets. Their nullable paths bind files in the global library (`lib/db/models/asset.py:11-47`; `lib/project_manager.py:392-398`). | Asset-derivative cascade is asset-local; project delete has no asset operation. | A source-project name cannot establish that project as live. The rows/files need separate `GLOBAL_ASSET` handling, as H6 §8 requires (`docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md:839-847`). |

## Identity cases

| Observed identity | Facts from current source | Required decision before capture admission |
| --- | --- | --- |
| Filesystem-only directory with valid `project.json` | Normal filesystem project representation; no SQL `projects` registry is present in the bounded model scan. | Select the precise accepted directory/name/metadata predicate and its fence behavior. |
| Directory without `project.json` | `list_projects()` can list it; `create_project(..., publish=False)` can create it before composed metadata creation. | Classify it as unpublished/interrupted/damaged; do not silently promote it to a live project. |
| Directory with only minimal `project.json` | HTTP creation can stop between its initial `create_project()` call and `create_project_metadata()`. | Check the complete supported schema and lifecycle evidence; mere file presence is not publication proof. |
| DB-only project name | Every table above can retain its domain row after API deletion because deletion only removes the directory. | Distinguish historical retention from interrupted/operational state; current source supplies no tombstone to do so. |
| Same name in directory and DB after reuse | The current identity is name based in both filesystem and scoped rows. | Define reuse/generation semantics; a name-only comparison cannot distinguish an old row from a new directory. |
| Target temporarily absent or changed during archive overwrite | The import installer can put the old tree under a hidden sibling before moving a different staged tree into the same target name. | Define a distinct replacement intent, source/target identity proof, capture fence, and crash reconciliation. Do not treat target absence as deletion or same-name replacement as proven continuity. |
| Target absent or paired with hidden v6 swap siblings | Migration can leave rollback/staging siblings around an absent or newly swapped target; startup may later reclaim or clean them. | Recognize exact swap sibling names, block unresolved capture, and require independent migration disposition. Do not treat target absence as published deletion or silently discard the hidden old tree. |

## Inferences and open decisions

### Inferences from the facts

1. Equality of directory names and database `project_name` values cannot be a
   safe unconditional capture invariant: ordinary deletion can leave
   historical rows, while a filesystem-only directory can exist before
   publication.
2. A non-terminal execution attempt or a `PREPARING` backup is stronger
   evidence of unfinished operational work than a terminal history row, but
   the source does not say whether project deletion must refuse, cancel,
   preserve, or retire it.
3. The failed-create caller means a future published-project tombstone, if
   selected, must distinguish explicit published deletion from rollback of an
   uncommitted directory. This follows from the two observed callers, not
   from an approved design.
4. Archive overwrite is an independent lifecycle writer. A delete-only
   tombstone protocol cannot classify its intermediate hidden backup or the
   replacement tree by name alone.

### Open decisions for the H6 gate

1. Select a durable project identity and the exact predicate for live,
   unpublished, deleting, retired, and historical states.
2. Define the atomic/crash-safe disposition of active tasks, non-terminal
   attempts/leases, `PREPARING` backups, current heads, and retained evidence
   when a published project is deleted.
3. Define whether and how names may be reused without re-binding historical
   rows to a different project identity.
4. Specify typed capture results for every identity case above, including
   legacy DB-only rows that lack any future lifecycle record.
5. Include archive import, especially `overwrite`, in the lifecycle writer
   fence and crash matrix; decide whether replacement preserves the exact
   project identity or creates a new generation, and how a retired name is
   rejected on new-name import.
6. Include the v5-to-v6 whole-tree swap and startup reclaim/cleanup in the
   census and writer fence. An H6 read-only capture cannot use presence-based
   startup repair as its proof of a stable project identity.

## Evidence limits

- Source only: no live database, filesystem instance, migration history, or
  runtime delete was queried/executed.
- Graph discovery used `home-anhtuan-content-production-os-m7`, generation
  `2026-09-18T10:57:40Z`, Tier 2. Coverage reported no recorded gap for the
  cited paths, but `lib/db/models/api_call.py` and
  `lib/db/models/host_hardening.py` were metadata-changed and
  `lib/db/models/gates.py` was not tracked; all three were directly read in
  this worktree. The `lib/db/models/` scope reports only an excluded
  `__pycache__` subtree, which is not semantic-completeness proof.
- This table enumerates ORM declarations containing direct `project_name` in
  the bounded `lib/db/models/` scan, plus selected indirect backup-media,
  canon, session-child and global-asset cases. Other indirectly scoped rows,
  dynamic SQL, future modules, and external systems remain out of scope.
