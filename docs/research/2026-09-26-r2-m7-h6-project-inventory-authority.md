# R2 M7 H6: project inventory authority before the V1 manifest

Date: 2026-09-26

Checkout: `feat/r2-m7e-v1-lineage` at
`a84638e7558e489d8d83c5910ba0f1f4635cd96f`

Status: research and schema input only. It does not approve the draft H6
design, change capture behavior, or authorize a production backup.

## Question and source boundary

What does "all projects" mean in the present Host, and can the next H6
manifest treat a project as a database row?

The code graph generation is `2026-09-18T10:57:40Z`. Coverage reports
`lib/project_manager.py`, `lib/artifact_manifest.py`,
`server/routers/projects.py`, and `server/services/project_archive.py` as
metadata-matching, but the H6 backup and
Host-hardening model files are stale/not tracked. Graph discovery was followed
by direct reads of each material source. The absence check below is limited
to `lib/db/models/`, not the entire repository or a live database.

## Confirmed facts

1. `ProjectManager.list_projects()` enumerates directories directly under
   `projects_root`, excluding names beginning with `.` or `_`; it does **not**
   validate the name against `PROJECT_NAME_PATTERN`. Creation and path
   resolution do enforce `^[A-Za-z0-9-]+$`. `create_project()` creates the directory and
   normally publishes `project.json`, but its `publish=False` option permits
   a transient directory without that file
   (`lib/project_manager.py:97,315-322,388-437`).
2. The API list route uses that filesystem enumeration and can emit a basic
   project entry even when `project.json` is missing
   (`server/routers/projects.py:543-550,603-618`). The UI list is therefore
   not a strict backup inventory or a proof that every project is restorable.
3. `project_exists()` means that `project.json` exists; it is not a check for
   a database project row. `load_project()` can rewrite that file during a
   legacy-style migration, while `load_project_readonly()` applies the same
   migration only in memory (`lib/project_manager.py:1849-1920`). A capture
   reader must not invoke the write-capable load path while attesting a
   quiescent source.
4. `CandidateObjectModel` and master authority rows carry `user_id` plus
   `project_name`; the candidate row's `object_ref` can be 1024 characters
   (`lib/db/models/host_hardening.py:293-338`). A bounded search for a
   `projects` table or FK in `lib/db/models/` found none. This is not proof
   that no other component or external database contains project metadata.
5. The Artifact Manifest is a project-local
   `.arcreel_artifacts.json`; its portable archive payload has separate
   schema version 2 and binds registered formal paths to basis and content
   digests (`lib/artifact_manifest.py:53-60,1990-2010`). Its
   `normalize_artifact_path()` rejects traversal, drive paths and its own
   runtime-owned filename (`:1871-1908`). That validator is for *formal
   artifact entries*, not a generic backup inventory path: a backup must
   separately represent `project.json` and the manifest file/absence.
6. The current `BackupSetManifest` is one-project/unversioned and contains
   only media entries; the current capture queries one scoped candidate set
   (`r2/contracts/host_hardening.py:324-362`,
   `r2/host_hardening/backup.py:256-329`). It cannot be reused as evidence of
   deployment-wide project/formal/media closure.
7. The existing `ProjectArchiveService` is not an exact H6 backup adapter:
   its full/current export first creates a per-project visible-tree snapshot,
   then repairs that snapshot and may trim version history or exclude hidden
   and non-standard entries (`server/services/project_archive.py:248-296,
   436-483,521-600`). Its copy routine does offer a useful *pattern*: take
   a metadata lock, compare complete source/copy signatures and Artifact
   Manifest state, and reject repeated drift (`:654-685`). The function
   itself is scoped to one project, permits retries and transformed export,
   and does not cover the deployment DB or external candidate media.
8. `_global_assets` is a cross-project library intentionally excluded from
   `list_projects()` (`lib/project_manager.py:392-397,574-580`). The
   `get_global_assets_root()` helper creates that root and its subdirectories,
   so a read-only capture must derive and inspect the path without calling it.
   An absent root must not be synthesized by the reader. The
   `assets` and `asset_derivatives` database tables have `image_path` and
   (for assets) `audio_path` fields (`lib/db/models/asset.py:11-47`), and the
   upload/copy routes put files under `_global_assets/{type}/` and store paths
   relative to `projects_root` (`server/routers/assets.py:91-96,113-125`).
   These are source-backed authoritative DB-to-file references outside any
   individual project directory.
9. A bounded model-field scan also found `api_calls.output_path`,
   `provider_credential.credentials_path`, and
   `adaptation_evaluation_findings.target_path`-shaped fields
   (`lib/db/models/api_call.py:29`, `credential.py:30`,
   `adaptation.py:539`). Their names alone do not prove they are all required
   recovery files. In particular, `credentials_path` points to a separate
   provider credential file read by the provider router
   (`server/routers/providers.py:771-779`), and must not be silently copied
   as a project artifact or exposed by a non-secret manifest. The H6 custody
   design already requires separate external-secret provisioning or proof
   that it is unnecessary for the approved restore profile.
   `adaptation_evaluation_findings.target_path` is a *semantic field path*,
   with observed values such as `scenes[0].dramatic_text`, not a filesystem
   path (`r2/adaptation/western_profile.py:101-121`,
   `tests/unit/r2/adaptation/test_western_profile.py:47`).
   `api_calls.output_path` is populated when usage is settled and is read by
   the usage repository for output-type/cost grouping
   (`lib/db/repositories/usage_repo.py:395-440,747-772`); whether any
   historical value must bind a restorable file remains an open policy
   classification, not a conclusion from its column name. The grouping helper
   explicitly tolerates absolute and relative paths and maps their
   `characters/scenes/props/products` segments to cost buckets
   (`lib/db/repositories/usage_repo.py:116-130`). The media generator can
   pass a real `output_path` into usage settlement
   (`lib/media_generator.py:613-637,730-745`), but this does not establish
   that each historical usage row is the current file authority: a row can
   outlive a deleted or superseded project output. Its path needs a separate
   liveness/ownership decision before being made a required backup file.
   A follow-up bounded current-worktree read found that
   `UsageRepository.finish_call()` writes this field as settlement metadata;
   `_row_to_dict()` returns it in call history, while
   `get_project_image_costs_by_asset_type()` groups its string value by path
   segment without opening the file (`lib/db/repositories/usage_repo.py:115-150,
   395-440,747-772`). This supports a **candidate** classification as
   historical accounting evidence, not a current file-existence obligation.
   The whole DB dump must still preserve the original value exactly; physical
   project census and formal/version/candidate bindings separately preserve
   current output bytes. Do not treat a stale historical `output_path` as
   authority to read outside approved roots. This is not an exhaustive audit
   of every future or dynamic consumer, so the release-pinned classifier
   needs a final reader/call-site review before approval. The separate
   [bounded production-use audit](2026-09-26-r2-m7-h6-api-call-output-path-audit.md)
   followed persistence through the ledger, usage repository/route, cost
   estimator and frontend drawer. It found no file-open or current-media
   consumer in those checked paths; its scope and limits are recorded there.
   A separate custody-path check found that the Vertex credential upload
   writes JSON to `app_data_dir().parent / "vertex_keys" /
   f"vertex_cred_{cred.id}.json` and then stores that **absolute** path in
   `provider_credential.credentials_path`
   (`server/routers/providers.py:688-735`;
   `lib/db/models/credential.py:19-47`). In production Compose,
   `./vertex_keys` is mounted separately at `/app/vertex_keys`
   (`deploy/production/docker-compose.yml:39`), while the application data
   root is resolved separately (`lib/app_data_dir.py:1-39`). Connectivity
   checking opens and parses the named file; credential deletion commits the
   DB row removal before best-effort file unlink
   (`server/routers/providers.py:651-666,768-790`). A whole-DB/project-tree
   archive therefore does not by itself restore this external secret file.
   The candidate V1 no-paid-route profile can treat it as a disabled external
   dependency only with explicit route-disable and no-provider drill proof;
   any profile needing Vertex must provision it through approved secret
   custody and verify the remapped target binding. Neither secret contents
   nor source absolute path belongs in a public inventory. This is a
   source-backed dependency finding, not selection of a key manager or
   authorization to read a live credential.
   The DB row is not the only Vertex file selector. The legacy configuration
   migration can store a discovered `vertex_keys` path in
   `provider_config` (`lib/config/migration.py:82-87`), while
   `resolve_vertex_credentials_path()` selects a preferred JSON file or the
   first other JSON file in that directory (`lib/system_config.py:122-147`).
   The text and video Vertex backends call this resolver directly; the image
   backend uses it when no explicit `credentials_path` is supplied
   (`lib/text_backends/gemini.py:118-136`,
   `lib/video_backends/gemini.py:81-94`,
   `lib/image_backends/gemini.py:58-75`). A restore disposition that enumerates
   only `provider_credential` rows would therefore miss a real file-read
   path. The release-pinned classifier must inventory configured path fields
   **and** resolver-based dependencies, then prove every such route disabled
   or provisioned under an approved profile. These source checks establish
   possible reads, not whether any route is enabled in a live deployment.
10. Global-asset deletion commits the asset and derivative row removal before
    unlinking their files; a file-unlink error is logged rather than rolled
    back (`server/routers/assets.py:248-262`). Thus an unreferenced file in
    `_global_assets` is possible in normal operation. The asset row IDs,
    derivative row IDs and nullable reference fields are distinct
    (`lib/db/models/asset.py:11-47`). `source_project` is nullable provenance,
    not a substitute for the asset/derivative file binding.

## Inference and alternatives

- A V1 manifest whose project count comes only from SQL would miss a
  filesystem-only project. Conversely, copying only the UI-visible
  `list_projects()` names would silently ignore hidden/underscore directories
  and DB rows referring to a missing project; a malformed non-hidden directory
  can appear in that list but fail `get_project_path()` validation. The capture
  adapter needs independent filesystem and DB enumeration, then an explicit
  liveness/classification rule before it can reconcile them. The current
  delete route removes only the project directory
  (`server/routers/projects.py:1100-1116`,
  `lib/project_manager.py:447-462`); historical DB rows with its name can
  remain. Equating every DB project name with a live directory would therefore
  reject an otherwise valid post-delete source, while ignoring every DB-only
  name could hide a corrupt live project. This is unresolved, not a basis for
  an unconditional discrepancy check.
- The root census also has whole-project intermediate directories. Archive
  overwrite can leave `.import-backup-*` beside a missing or replacement
  target (`server/services/project_archive.py:1956-1987`). The v5-to-v6
  migration creates hidden staging/rollback siblings and swaps the target
  through them (`lib/project_migrations/v5_to_v6_asset_namespace.py:584-614`;
  `lib/project_migrations/staged_swap.py:37-74,90-149`). UI-visible project
  enumeration skips these names. A read-only H6 census must recognize their
  exact ownership and reject unresolved replacement/swap state; it cannot
  silently omit them or run startup repair to make the source appear stable.
- `project.json` is required for every admitted project directory by the
  draft H6 design. A directory lacking it is a fail-closed capture error,
  not a zero-formal-file project. Zero formal files may still be valid when
  the Artifact Manifest and restored DB both have no formal references.
- `_global_assets` cannot be ignored or classified as a normal project. A
  candidate V1 manifest needs a separate `GLOBAL_ASSET` entry role beneath
  the existing logical project root, with exact DB-row/path bindings and
  size/hash checks; missing or out-of-root references fail capture. Whether
  unreferenced orphan files in that directory are retained or rejected is a
  separate explicit policy choice, not a silent omission. The current delete
  ordering means "reject every orphan" may reject a source left by a
  previously successful API deletion; the policy must account for that state.
- Reusing `normalize_artifact_path()` for formal-entry references is useful,
  but using it for every backup file would incorrectly conflate formal
  registration with `project.json`, the Artifact Manifest file, and possibly
  global assets. A generic safe-relative-path rule plus role-specific checks
  is the cleaner candidate; on-disk no-symlink/containment remains an adapter
  obligation.
- Reusing the project archive's lock/signature idea is plausible only after
  proving it does not mutate source bytes, omit hidden-but-authoritative
  files, or convert one project's copy into a deployment-wide consistency
  claim. Calling its repair/export path as the H6 backup implementation would
  change the recovery bytes and conceal missing source artifacts.

## V1 file-authority matrix for the next schema review

This matrix names confirmed source classes and the minimum counterexample the
manifest/fault corpus must express. It is **not** yet a complete list of every
path-like value inside `project.json` or every Host file writer; that bounded
inventory and its exclusions remain the decision gate below.

| Source class | Confirmed authority and current behavior | Required distinction / fault case |
| --- | --- | --- |
| `project.json` in an admitted project directory | `ProjectManager` normally creates it; `project_exists()` tests it, whereas `list_projects()` can show a directory without it (`lib/project_manager.py:419-437,1848-1857`; `server/routers/projects.py:603-618`). | Missing metadata file is different from a valid project with zero formal files. Do not create/repair it during capture. |
| Project-local `.arcreel_artifacts.json` and registered formal files | Manifest entries bind a canonical formal `artifact_path` and basis digest; the project adapter's read-only loader returns `({}, None)` when the manifest file is absent, while a present empty manifest serializes as a real JSON file with `"entries": {}` (`lib/artifact_manifest.py:113-125,1025-1060,1401-1442,1958-1966,2075-2135`). | `snapshot_entries()` alone collapses absent and present-empty to `{}`. Inventory must record presence and, when present, the file bytes/hash separately from the zero-or-more formal entries. Missing/corrupt registered file fails; zero entries can be valid only with no contradictory DB reference. |
| Candidate media and approved master | Immutable candidate rows carry `candidate_id`, `object_ref`, size/content/probe digests; master head/version rows bind the selected candidate and repeated object/content identity (`lib/db/models/host_hardening.py:293-380`). Current backup copies one project's candidate list even though `pg_dump` captures the whole DB (`r2/host_hardening/backup.py:256-329`). | Capture all admitted deployment-scoped candidates and master links, reject an out-of-root or missing candidate, and prove the selected master resolves after restore. A single-project inventory cannot close a whole-DB archive. |
| DB-bound `_global_assets` | `assets.image_path`, `assets.audio_path`, and `asset_derivatives.image_path` are nullable file references; normal upload/copy stores paths relative to `projects_root` under `_global_assets/{type}/` (`lib/db/models/asset.py:11-47`; `server/routers/assets.py:90-125`). | Bind each non-null reference by exact table/row ID/field, then check safe relative path, root containment, bytes and hash. Do not call creating `get_global_assets_root()` to discover an absent root. A null field is not a missing file. |
| Unreferenced `_global_assets` bytes | API asset deletion commits row removal before unlink and only logs an unlink error (`server/routers/assets.py:248-262`). | Orphans can follow an otherwise successful delete. Explicitly choose include, reject or documented exclusion; do not infer that every orphan means corruption, and test an absent versus empty root. |
| `api_calls.output_path` | The media generator writes a real output path into accounting, but the usage repository also classifies historical absolute/relative paths by cost bucket (`lib/media_generator.py:613-637,730-745`; `lib/db/repositories/usage_repo.py:116-130,395-440,747-772`). | A usage row is neither automatic current-file authority nor automatically irrelevant. Classify current owner versus historical evidence and test a stale path after project deletion. |
| Vertex external secret selectors | Provider connectivity reads `provider_credential.credentials_path`; legacy migration can populate `provider_config.credentials_path`, and text/video/image backends can select a file from `vertex_keys` without a DB row path (`server/routers/providers.py:771-779`; `lib/config/migration.py:82-87`; `lib/system_config.py:122-147`). | Keep paths/bytes outside non-secret inventory; enumerate both explicit fields and resolver-based selectors in protected restore evidence. Require independently approved provisioning or exact disabled-route/no-provider proof for every selector. |

The existing project archive is a transformed one-project export, not a
substitute for this matrix: it can exclude hidden/non-standard entries and
trim version history (`server/services/project_archive.py:436-483,521-600`).

## Project-tree scope: profile state is not disposable runtime state

The standard project tree has `source`, `scripts`, `drafts`, `characters`,
`scenes`, `props`, `products`, `storyboards`, `videos`, `audio`, `subtitles`,
`presentations`, `thumbnails`, `output`, and `grids`, plus `project.json`
(`lib/project_manager.py:286-315`). That list is a creation layout, **not** a
complete backup allowlist. The archive export walks only visible, approved
root entries and excludes hidden paths, `.claude/`, and `CLAUDE.md`
(`server/services/project_archive.py:220-226,714-734`). Its import then
re-synchronizes the project agent profile (`:1965-1978`). These behaviors
serve portable project export, not byte-exact whole-deployment recovery.

In particular, `sync_agent_profile()` materializes the deployment profile
into project-local `.claude/` and `CLAUDE.md`. The adjacent hidden
`.arcreel_profile_manifest.json` tracks the baseline and deletion tombstones
(`lib/project_manager.py:464-487`; `lib/profile_manifest.py:1-7,36-44`). The
sync state machine preserves user-modified and project-only files, and a
deleted built-in file becomes a tombstone rather than being automatically
restored (`lib/profile_manifest.py:586-640`). If the manifest is absent,
corrupt, or incompatible, sync takes a reset path that removes the destination
profile tree before materializing the current deployment profile
(`:321-355,502-550,671-739`). Thus simply excluding the hidden manifest or
copying only `.claude/` bytes can change project behavior on restore. This is
an inference from the state machine, not evidence that any particular live
project has customizations.

The same tree can contain transient lock files: profile sync uses
`.profile_sync.lock`, Artifact Manifest uses `.artifact_manifest.lock`, and
project metadata/file locking uses `.project.json.lock` or
`.{basename}.lock` (`lib/profile_manifest.py:36-38,166-174`;
`lib/artifact_manifest.py:53-60`; `lib/project_manager.py:1921-1930,1951-1986`).
These names identify synchronization machinery, but this research has not
proved a repository-wide exhaustive lock pattern or a safe rule for every
unknown hidden file. A blanket hidden-file exclusion loses known state; a
blanket tree copy can retain transient state and potentially unclassified
secret-bearing bytes. Neither can be approved from the archive export filter.

Follow-up positive lock-writer census for the release exclusion review:

| Writer | Observed on-disk lock identity | Boundary |
| --- | --- | --- |
| `project_metadata_lock()` in `lib/formal_write.py:79-87` | Project-root `.project.json.lock`. | Known synchronization file, not the `project.json` payload. |
| `lib/profile_manifest.py:36-38,166-174` and `lib/artifact_manifest.py:53-60` | Project-root `.profile_sync.lock` and `.artifact_manifest.lock`. | Preserve the adjacent hidden *manifests*; these names identify lock writers but do not by themselves authorize exclusion. |
| `ProjectManager.file_lock()` / `async_file_lock()` (`lib/project_manager.py:1949-1987`) | `.{target.name}.lock` in the **target's parent directory**. | Target can be a script, draft, plan, prompt-authoring file or asset file, so a static root-filename list is incomplete. |
| `GridManager._record_lock()` (`lib/grid_manager.py:122-129`) | `.{record.name}.lock` next to a grid record. | The grid record itself remains project payload. |
| `generation_admission._lock_path()` (`lib/generation_admission.py:17-24`) | Digest-named lock under application-data `.generation-admission-locks`, not a project tree. | It is outside the proposed project-file census; do not invent a project exclusion for it. |

The M7 graph's inbound trace for `ProjectManager.file_lock()` found 18
callers and seven for `async_file_lock()`, across the manager, script
generator/review and server draft/text flows. Current-worktree source checks
confirmed the dynamic path derivation and representative calls
(`lib/script_generator.py:1401-1402,1771-1772`;
`server/draft_workflow.py:1156,1240`;
`server/text_generation.py:848,1508`). This is a *positive* writer set,
not proof that no other module makes project-local locks. If H6 excludes
locks, it must derive each identity from a release-pinned writer and target
class, then test the expected regular-file type and exact location; it must
not drop an arbitrary `*.lock`, unknown hidden file, symlink named like a
lock, or the locked payload. A competing V1 option is to retain every regular
lock file as opaque bytes under encrypted custody. The examined lock
functions use these files as lock handles and do not parse their contents
(`lib/formal_write.py:79-87`; `lib/project_manager.py:1949-1987`;
`lib/artifact_manifest.py:1269-1338`;
`lib/profile_manifest.py:166-209`). The all-regular-file option avoids an
unproven ownership claim for a user-modified file that happens to match a
writer's lock name and matches the exact-tree recovery goal. It still rejects
symlinks/devices and requires a verified quiescent fence. The proposed V1
preference is to *include* regular locks and test that subsequent project
operations work after restore; the reviewer must approve this before schema
freeze. The complete lock-writer map remains useful for fence completeness.

Candidate scope choices for schema review, not settled policy:

| Choice | Benefit | Unclosed risk / required proof |
| --- | --- | --- |
| All regular project files, including lock files | Retains otherwise unknown user files, version history and any user-modified lock-named bytes without exclusion ambiguity. | Require no-follow type checks, encrypted custody, quiescent fence, exact restore comparison and post-restore lock-use test. |
| All regular project files, except an exact runtime exclusion set | Reduces copied runtime files. | Prove writer-specific ownership of each excluded file; a matching name alone is insufficient if a user modified it. |
| Only known formal/DB-bound files | Smaller authority surface. | Prove every project-local customization, source file, version and profile tombstone is either restorable or intentionally out of scope; current profile state contradicts a simple formal-only assumption. |
| Enumerated authoritative roots plus explicit metadata/profile roles, fail-closed on unknown paths | Makes omissions visible and supports role-specific validation. | Requires an exhaustive writer/reference inventory and migration rule for new roots; no such approval exists yet. |

Minimum V1-02 fault corpus from this finding: a modified `.claude/` file;
a project-only `.claude/` file; a tombstoned built-in file with its manifest;
an absent versus present-empty profile manifest; a transient lock; and an
unknown hidden file. Restore verification must compare the chosen profile
state before any sync operation that could rewrite it. Whether project-local
profile content belongs inside the encrypted archive, in a separate custody
artifact, or in an explicitly unsupported V1 capability remains a sponsor
decision tied to the secret-custody policy.

## Positive path-field sample; not yet an exhaustive schema

The archive repair pass supplies a concrete *sample* of project-file links
that a backup reader must classify without invoking that mutating repair pass:

| Source payload | Observed local-file fields | Boundary case |
| --- | --- | --- |
| `project.json` | `style_image`; `characters[*].character_sheet`, `reference_image`, `reference_audio`; `scenes[*].scene_sheet`; `props[*].prop_sheet`; `episodes[*].script_file` (`server/services/project_archive.py:761-945`). | An episode ledger may declare a prospective `script_file` before the script exists; archive repair treats a valid positive episode number as a warning, not a missing-file blocker (`:906-936`). H6 must decide separately whether to retain that pending state, rather than rejecting every absent path-like value. |
| Episode script JSON | `generated_assets.storyboard_image`, `video_clip`, `narration_audio` for storyboard skeletons; `generated_assets.video_clip`, `video_thumbnail` for `video_units` (`server/services/project_archive.py:970-1149,1240-1335`). | Version metadata can resolve a current media file from `versions/`, while the archive repair pass may materialize or rewrite it. A backup reader must inventory the original bytes and references, not silently repair them (`:1452-1556`). |
| `generated_assets.video_uri` | The archive's reference-video repair path calls this a remote URL and deliberately does not canonicalize it (`server/services/project_archive.py:1240-1258`), but the current validator accepts either an external URI or an existing local path (`lib/data_validator.py:252-290,784-790`). | Classify by value, not field name. External URI identity/provider availability is not proven by a local-file hash; a local value needs file closure. |

The validator reveals two further local-file fields not covered by that archive
repair sample: `generated_assets.storyboard_last_image` and per-item
`end_frame_image` (`lib/data_validator.py:770-776,812-832`). Conversely,
`GeneratedAssets` declares `video_thumbnail` and project-cover rendering
reads it, but `_validate_generated_assets()` has no corresponding reference
check (`lib/script_models.py:184-201`; `server/services/project_cover.py:60-98`;
`lib/data_validator.py:750-810`). A direct, read-only probe of the current
method returned `val_path_missing` for nonexistent `storyboard_last_image`
and local `video_uri`, no error for nonexistent `video_thumbnail`, and no
error for an external `https://` video URI. The probe used the existing
`/home/anhtuan/content-production-os/.venv/bin/python` because this
worktree's virtualenv lacks Pydantic; `uv run` could not fetch its missing
locked dependency with network unavailable. This checks this method's
behavior only, not every caller. H6 therefore cannot use a passing
`DataValidator.validate_project_tree()` result as proof that all file
references are present; its own inventory/restore checker needs an explicit
field map and fault corpus.

The project catalog has another source-backed omission from the initial
sample: `products[*].product_sheet` and each
`products[*].reference_images[]` element. `ASSET_SPECS` declares the former
as a sheet path and the latter as uploaded original-image paths;
`ProjectManager` has dedicated sheet/reference writers, and generation reads
the originals for product-sheet creation (`lib/asset_types.py:121-139`;
`lib/project_manager.py:3573-3608`;
`server/services/generation_tasks.py:2892-2914`). The generation reader
skips missing originals and merely warns if all declared originals are
missing. `DataValidator` checks the product reference list's *element types*,
but its project-tree path walk does not check product sheet/reference file
existence (`lib/data_validator.py:605-671,1485-1610`). Character derivative
sheet references are likewise type-checked in `_validate_derivatives()` but
not enumerated by that project-tree path walk (`:565-603`). These are
positive file-reference findings, not a claim that every declared product or
derivative sheet must already exist: the H6 liveness predicate still needs
to distinguish pending assets from dangling current references.

The validator's path resolver also accepts an absolute path if `safe_join()`
resolves it *within* the project root, and returns the input candidate spelling
after its existence check; `safe_join()` resolves symlinks for containment but
does not forbid an in-root symlink (`lib/data_validator.py:201-250`;
`lib/path_safety.py:37-101`). This is suitable evidence of the validator's
current behavior, not a canonical H6 inventory path rule. The H6 reader must
decide separately whether to reject absolute aliases and every symlink at
capture/restore rather than treating validation success as a normalized
portable reference.

This is **not** a complete `project.json`/script schema or a liveness rule for
every field. The evidence began with one archive repair path, which may omit
fields that it does not repair. A bounded first-party writer/reader pass for
the named fields is recorded in
`docs/research/2026-09-26-r2-m7-h6-path-writers.md`; it does not close
historical migration/import writers or every path-bearing field. The
remaining V1-02 work is to expand that inventory, then distinguish required
existing bytes, intentionally pending references, remote URIs, history, and
deprecated fields. The backup adapter must not borrow the archive's auto-fix
behavior as a capture-time integrity check.

### Candidate release-pinned reference field map (positive evidence)

The table consolidates *confirmed* field identities for the proposed H6
classifier. It is review input, not a claim that all historical schema
versions or DB path fields have been exhausted. A nonempty local value must
resolve to a physical inventory binding unless a stated pending rule applies;
absent/null/empty values retain their distinct source states. H6's no-follow
canonical path policy remains stricter than the ordinary validator's basename
fallback.

| Source and field | Candidate classification | Counterexample to test |
| --- | --- | --- |
| `project.json`: `style_image`; `characters[*].character_sheet`, `reference_image`, `reference_audio`; `scenes[*].scene_sheet`; `props[*].prop_sheet` | Optional local file; every nonempty value binds project bytes. | Missing local file, absolute alias and in-root symlink. |
| `project.json`: `products[*].product_sheet`, each `products[*].reference_images[]`, and `characters[*].derivatives[*].character_sheet` | Optional local file(s); validator checks some types but not all file existence. | Missing product original/derivative sheet while ordinary tree validation passes. |
| `project.json`: `episodes[*].script_file` | Required nonempty ledger field; absent target is pending only when `episode` parses as a positive episode number, while an existing target binds bytes and is parsed as an episode script. | Positive-number pending script versus malformed-number missing script; no automatic script creation. |
| Episode script: supported segment/scene/shot/video-unit `generated_assets.storyboard_image`, `storyboard_last_image`, `video_clip`, `video_thumbnail`, `narration_audio` | Optional local file; nonempty values bind bytes. The current generated-assets validator omits thumbnail. | Missing thumbnail with otherwise passing tree validator. |
| Episode script: supported segment/scene/shot `end_frame_image` | Optional local file constrained to `end_frames/` in the existing validator; H6 must also reject aliases/symlinks. | Same bytes at a path outside the end-frame root. |
| Episode script: `generated_assets.video_uri` | Value-sensitive: absent/empty, approved external URI, or local file binding. External URI is recorded as remote identity, not invented local bytes. | `https://` URI versus same field containing a local path. |
| Artifact Manifest `entries[*].artifact_path` and `versions/versions.json` `versions[*].file` | Registered formal artifact and retained history snapshot respectively; each declared nonpending reference requires bytes. | Missing unselected/rejected history snapshot; absent versus present-empty manifest/index. |
| Project `grids/grid_*.json`: `grid_image_path`, `frame_chain[*].image_path`, `reference_images[*].path`, `script_file` | Grid record fields name a composite, split-frame outputs, reference inputs and an episode script. Their exact required-versus-pending predicates remain to be approved. | Ready composite missing while metadata survives; missing split-frame or reference input; malformed grid JSON skipped by the UI list; grid record referring to a missing script. |
| Persisted `presentations/episode_*/*.json`: `script_file`, `subtitle_artifact_path`, `presentation_artifact_path`, `video.artifact_path`, nullable `narration_audio.artifact_path` | Version-1 presentation projection names its own formal files and selected media. `ArtifactPlanner` reads and compares it with a recomputed expected presentation. | Missing selected video/audio, stale internal path, or a presentation JSON that exists but fails the planner's exact comparison. |
| `tasks.execution_checkpoint_json` and project-local `.arcreel/tasks/*/provider_media/manifest.json`: `script_file`, `narration.artifact_path`, `media[*].source_locator`, `media[*].staged_locator` | Versioned submission checkpoint and staging manifest bind provider input copies for task resume. Staging cleanup can remove files while the DB checkpoint remains. | Active checkpoint with missing staged bytes; terminal task with intentionally cleaned staging; checkpoint/manifest digest or task-identity mismatch. |
| Project-local quarantine draft JSON `meta.source` | A nullable source selector is reused when revalidating or promoting the draft; null derives the episode source file. | Named source missing or changed, null with missing derived episode source, corrupt draft whose `meta.source` cannot be trusted. |
| Project-local `.arcreel_profile_manifest.json` `entries` keys | Profile synchronization baseline names materialized `CLAUDE.md`/`.claude/**` destinations and tracks active hashes or tombstones. It is a profile-state binding, not media lineage. | Missing customized destination, tombstone restored as an active file, absent versus present-empty manifest; profile sync must not run during capture to erase the distinction. |
| Project-local `.migration_failure.json` `details[*].file` and `storyboards/generation_failures.json` `failures[*].resource_id` | The first names rejected migration inputs and is read by the generation guard; the second names storyboard units for diagnostics and can remain after a later successful batch. Preserve actual JSON bytes under the tree policy, but do not infer media authority or required target bytes from either field. | Captured failed-migration record omitted or altered while project files are retained; stale storyboard failure mistaken for a currently missing artifact. |
| DB `assets.image_path`, `assets.audio_path`, `asset_derivatives.image_path`; candidate/master object references | Non-null global-asset binding by table/row/field; candidate/master binding by exact candidate/object-version identity under approved media root. | Two rows share one file; absent `_global_assets` with DB reference; out-of-root master. |
| DB `api_calls.output_path`, explicit Vertex credential/config paths, implicit Vertex file resolvers, adaptation finding `target_path` | **Review-only**: candidate historical usage metadata, separate secret-custody selectors and semantic field path respectively. Do not classify by column suffix, enumerate only DB rows, or quietly copy credential files. | Historical usage path after deletion; explicit and resolver selectors covered by protected disposition but secret paths absent from public manifest; semantic `target_path` not treated as a filesystem path. |

This field map is deliberately positive, not a default for unknown schemas.
The bounded [other JSON survey](2026-09-26-r2-m7-h6-other-json-reference-survey.md)
supplies the profile, migration-failure and storyboard-failure classifications;
it found no reader for the last record within its stated Python source scope,
which does not establish that no external consumer exists.
Before acceptance, enumerate each supported project/script/history schema
revision and additional writer/import/migration routes, decide whether
`api_calls.output_path` is historical evidence or current file authority
under each lifecycle state, and make unknown declared reference types a typed
capture failure. See the [writer/reader pass](2026-09-26-r2-m7-h6-path-writers.md)
for observed field mutators and ordinary validator behavior.

### Grid-record reference gap found in the current tree

`GridGeneration` persists `script_file`, nullable `grid_image_path`,
`frame_chain[*].image_path`, and `reference_images[*].path` in a project-local
grid JSON record (`lib/grid/models.py:11-27,31-64,116-165`). The constructor
starts with `grid_image_path=None` and `status="pending"`, while replacing a
composite sets it to `grids/{id}.png` (`:203-254`). Split completion writes
frame image paths and `split_at` to that same record
(`server/services/grid_split.py:461-472`); the split operation reads each
reference image path from the record and uses it as an input when present
(`:304-325`). Generation and regeneration also load the named script
(`server/services/generation_tasks.py:3201-3207`;
`server/routers/grids.py:305-312`). These are positive path-bearing fields
outside the earlier project/script/history matrix, even if some paths also
have a formal Manifest entry.

`GridManager` stores records under `grids/`, but its constructor creates that
directory; its `list_all()` uses `glob("grid_*.json")` and logs/skips invalid
JSON (`lib/grid_manager.py:23-29,157-165`). Therefore neither invoking that
constructor during read-only capture nor using `list_all()` as a complete
grid-record proof is safe. The existing pure
`r2/host_hardening/grid_reference_probe.py:97-166` reads supplied bytes and
extracts all declared grid paths while preserving absent/null/present states;
the existing `scan_project_tree()` retains and hashes physical bytes. Reuse
both under an approved fence instead of adding another grid parser or tree
scanner. Neither supplies status-sensitive file authority: regeneration can
leave an old composite path in `pending`, and composite replacement can leave
old frame paths with null `split_at`. The [grid state matrix](2026-09-27-r2-m7-h6-grid-reference-state-matrix.md)
records those counterexamples; the [reuse audit](2026-09-27-r2-m7-h6-v102-reuse-audit.md)
bounds the other readers. V1-02 still must approve version/shape, Task/attempt
and Manifest reconciliation, missing-byte results, and complete malformed-grid
coverage. This is bounded current-source evidence, not an approved capture rule.

Candidate grid field rules for review, using the existing **unversioned** JSON
shape and the pure probe (not `GridGeneration.from_dict()`'s legacy projection):

| Raw field/state | Candidate file rule | Fixture that must decide the final rule |
| --- | --- | --- |
| `script_file`: required string in a persisted grid | Resolve the exact bound episode script and require its bytes; an absent target has no demonstrated grid-specific pending semantics. | Missing script with a still-present grid record. |
| `grid_image_path`: absent/null in a newly `pending` grid | No composite binding until a path is declared; `completed` with no path is a conflict to inspect, not an automatic pending case. | New pending record versus completed record missing its path. |
| `grid_image_path`: nonempty in any status | Bind the declared path to physical bytes; do not discard an old path solely because regeneration set `pending` or failure set `failed`. A missing old path needs an approved stale-reference disposition or a typed rejection. | Pending/failed regeneration with old composite present, then missing. |
| `frame_chain[*].image_path`: absent/null or nonempty | No path is required for every frame merely because `split_at` exists; each nonempty declared path needs an explicit binding/disposition even when `split_at` is null. | Skipped scene after split and stale frame path after composite replacement. |
| `reference_images[*].path`: list present, null or absent | Every listed path is a declared input reference; preserve null/absent list states and reject unsupported item shape. Empty string and missing target semantics still need review. | Missing reference image, empty path, and unknown field in an unversioned record. |

`inspect_grid_references()` currently accepts legacy `splitting` and rejects
unknown fields rather than guessing a future unversioned schema
(`r2/host_hardening/grid_reference_probe.py:16-41,83-166`). These rows specify
review cases and conservative candidate bindings; they do not approve the
Task/attempt fence, current Manifest mapping or stale-path disposition.

### Presentation projections and provider-media staging

`MaterializedPresentation.to_dict()` writes `script_file`, its subtitle and
presentation artifact paths, and a version-1 `SpeechPresentation` payload
(`server/services/presentation_read_model.py:66-92,839-887`;
`lib/speech_presentation.py:233-250`). The nested video and optional narration
tracks emit their selected media `artifact_path`, version and content evidence
(`lib/speech_presentation.py:54-72,167-198,469-478`); the raw-video variant
also emits a selected video path (`:253-287,333-350`). These JSON files are
registered as formal artifacts, and `ArtifactPlanner` later reads the optional
subtitle/presentation pair and compares the persisted object with a
recomputed expected value before accepting it as current evidence
(`server/services/presentation_read_model.py:873-887`;
`lib/artifact_planner.py:1029-1045,1135-1148`). Thus exact physical retention
alone does not classify the declared internal paths. V1-02 must decide whether
to parse and bind every nested media path, verify the planner's reconstructed
projection, or explicitly narrow the restore claim. This is a positive
current-source finding, not a claim that a missing optional presentation is
corruption.

`Task.execution_checkpoint_json` is a nullable persisted field
(`lib/db/models/task.py:16-46`). A guarded pre-submit transition writes a
video checkpoint for a running task before provider submission
(`lib/db/repositories/task_repo.py:1059-1084`;
`server/services/reference_video_tasks.py:700-711`). The checkpoint's
versioned payload includes `script_file`, narration `artifact_path`, and for
each media item `source_locator` and `staged_locator`; it binds the latter to
`.arcreel/tasks/{task_id}/provider_media/`
(`lib/reference_video/execution_checkpoint.py:147-225,600-679,681-715`).
The project-local staging `manifest.json` has schema version 1 and repeats
the same media records; the loader validates the manifest, and a separate
verifier hashes staged files (`:283-298,325-339`). Checkpoint resume binds its
task ID, project, script and unit to the owning DB row (`:952-987`). Finalized task
paths and cancellation/error paths can remove staging
(`server/services/reference_video_tasks.py:713-720,786-790`;
`lib/reference_video/execution_checkpoint.py:361-425`). Therefore a retained
checkpoint row is not unconditional proof that its staged file should still
exist. V1-01 task-state disposition and V1-02 reference classification must
jointly define pre-submit, submitted and terminal dispositions. In particular,
`classify_video_resume_state()` distinguishes checkpoint/no-job from a valid
checkpoint/job pair (`lib/reference_video/execution_checkpoint.py:997-1021`).
The submitted-job resume path uses the checkpoint and provider job, does not
read the staged provider inputs, and cleans staging on exit
(`server/services/resume_executor.py:96-166,232-239`). A still-running initial
submit can read those files; its state cannot be inferred from the DB row
alone. Do not treat the hidden `.arcreel/` subtree as disposable by name or
fabricate missing staged files from mutable source inputs.

Candidate V1-02 classification for review (not an approved inventory schema):

| Persisted state | Binding and byte disposition | Existing boundary to reuse |
| --- | --- | --- |
| A persisted subtitle/presentation pair | Capture both files exactly. Parse the presentation's top-level `script_file`, subtitle/presentation paths, and nested video plus optional narration `artifact_path`; bind each declared local path to the project census and its owning script/media identity. A raw-video projection still has a video path. Missing or inconsistent declared bytes block the exact-recovery claim for this pair. | `MaterializedPresentation.to_dict()` and the `SpeechPresentation`/raw-video serializers enumerate the fields; `ArtifactPlanner._prove_persisted_presentation()` recomputes the expected object. Its `CURRENT` result can support consistency, but is not by itself a backup byte or fence proof. |
| No persisted pair | Record the observed absence or partial pair state explicitly. Do not invent a presentation file or infer one from the live UI projection. A partial pair requires a reviewed invalid/orphan disposition before exact recovery. | `ArtifactPlanner` skips absent optional pair members; its behavior does not settle backup authority. |
| Running video task, before or during initial submit | Treat as an active-writer blocker for a quiescent exact capture unless V1-01 proves a stronger fence. A checkpoint without a job ID cannot resume after restart. If a staging tree exists, census it and verify its manifest and bytes before assigning any reference binding; missing staging is not repaired from mutable sources. | `TaskRepository.persist_execution_checkpoint()` guards the pre-submit transition; `stage_provider_media()` reads the staged inputs for first submission; `classify_video_resume_state()` marks checkpoint/no-job separately. |
| Running video task with valid checkpoint and provider job ID | `READY` means its execution identity is parseable and bound to the DB row, not that staged bytes are required for provider polling. Candidate quiescent capture still blocks this active task. If a staging tree exists, retain and verify it; if absent, record absence separately rather than claiming missing required resume input. Bind `script_file` and nonempty narration `artifact_path` under their own file rules. | `load_task_video_checkpoint()` and `classify_video_resume_state()` classify DB facts. `execute_resume_video_task()` resumes the provider job from checkpoint data and cleans staging; it does not reopen staged inputs. |
| Terminal task, absent checkpoint, or an unapproved/ambiguous task state | Retain any existing staging in the physical census pending an orphan/cleanup disposition. Do not require or discard staging merely because a checkpoint column is populated or a directory is hidden. A malformed checkpoint is an explicit invalid-state finding, not an empty checkpoint. | Normal finalization and worker cleanup can remove staging. The existing `_load_staging_manifest()` and `_verify_staged_files()` can validate a present tree, but their ordinary-stage behavior does not establish H6 capture authority. |

Fixtures for the review must cover both presentation variants, missing one member
of a persisted pair, a nested media path that points to a different existing
file, a checkpoint whose task coordinates disagree with its row, malformed and
absent checkpoints, checkpoint/no-job with missing staged bytes, a valid
checkpoint/job pair with staging absent, checkpoint/manifest record mismatch,
source changed after staging, a terminal
checkpoint with staging already cleaned, and a terminal orphan staging tree.
The task-state predicate, partial-pair policy, and a fence that keeps DB rows
and project files coherent are still open; this table cannot authorize capture
or restore adapters on its own.

### Quarantined draft source selectors

Quarantine drafts are persisted as versioned envelopes with `meta` and
`content` (`lib/draft_quarantine.py:95-97,165-185,242-267`). The draft workflow
records a validated `meta.source` and later reuses it for revalidation and
promotion (`server/draft_workflow.py:166-184,1197-1222`). A string value names
a project-local source file; null resolves to `source/episode_N.txt`, and the
loader requires that file to exist and contain text
(`server/text_generation.py:498-538`). The reader treats an invalid envelope
as no usable draft while the physical file can still block normal generation
(`lib/draft_quarantine.py:270-276`). Thus V1-02 must preserve draft bytes and
classify `meta.source` by its value and draft state; it cannot declare every
draft JSON an opaque file with no relevant path. Whether a broken or obsolete
draft blocks exact H6 recovery, or is retained only as historical bytes,
remains a reviewed policy decision.

## Global-asset reference multiplicity

The `assets` table uniquely constrains `(type, name)`, and
`asset_derivatives` uniquely constrains `(asset_id, name)`; neither model
places a uniqueness constraint on `image_path` or `audio_path`
(`lib/db/models/asset.py:11-47`). The normal upload/copy helpers produce a
fresh UUID filename in `_global_assets/{type}/`, so two normal writes are
expected to have distinct paths (`server/routers/assets.py:90-125`). That is
not a database invariant: the repository's `create()`/`update()` accepts the
provided path, and `replace_derivatives()` replaces rows with caller-supplied
paths (`lib/db/repositories/asset_repo.py:16-39,70-77,113-136`). H6 must not
assume one DB binding per physical file when reading a restored or manually
modified database.

Candidate inventory representation: one normalized file identity and digest
may have **multiple** binding receipts, each with table, primary-key, field,
and nullable/non-null value. This is a schema candidate, not an approved
deduplication policy. A safe version would reject inconsistent hashes for the
same physical path across capture phases, and explicitly test two rows sharing
a path, two fields in one row sharing a path, and a duplicate reference whose
file is missing.
The live delete/replace routes commit the DB change before attempting to
unlink old files; unlink failure leaves orphans, while the deletion helper
does not look up other rows before unlinking (`server/routers/assets.py:128-136,
247-262,283-299`). Therefore both orphan bytes and a shared-path dangling
reference are plausible edge cases if a duplicate path was introduced outside
the UUID-creating route. This is an inference about possible states, not a
claim that the ordinary API currently creates duplicate paths.

The UI-oriented repository `list()` is paginated with a default limit of 100
and orders by mutable `updated_at` (`lib/db/repositories/asset_repo.py:54-68`).
A capture implementation cannot treat one default `list()` call as a complete
deployment inventory; it needs a fenced, complete row scan, including every
derivative row. The exact query/transaction strategy remains a V1-03 design
decision.

Reuse the ORM field definitions and `list_derivatives_by_asset_ids()` only
after the complete set of asset IDs is established; that method returns
derivatives for the IDs supplied, not an independent full-table census
(`lib/db/repositories/asset_repo.py:96-111`). Likewise,
`CandidateObjectRepository.list_all()` is complete **within one**
`(user_id, project_name)` pair, while the current disposable backup invokes it
for exactly one such pair (`lib/db/repositories/host_hardening.py:820-835`;
`r2/host_hardening/backup.py:282-295`). Neither reader by itself proves
whole-deployment media coverage. V1-03 must establish the complete scoped-row
set in a fenced DB snapshot before reusing those per-scope readers, or use a
reviewed full-scan query with equivalent row identity checks.

## Project-local version history is another file authority

`VersionManager` keeps `versions/versions.json` under each project and records
each version's relative `file` plus `current_version`; its read API exposes
every recorded version as a file URL (`lib/version_manager.py:126-136,
171-221`). The normal staged-commit paths copy snapshot bytes before
persisting the version record and current-file selection, with rollback on
failure (`:433-542,544-690`). `restore_version()` later reads the selected
record's file and copies it back to the current path (`:1198-1257`). A
rejected paid result can stay in history after the current selection moves
back (`:875-975`). Therefore a backup containing only currently selected
media can lose user-visible history and future restore choices; the archive
export's `scope="current"` deliberately trims `versions.json` and snapshot
files, so it is not an exact recovery source (`server/services/project_archive.py:521-600`).

The history state also has edge cases the H6 manifest must represent rather
than silently fix. `_load_versions()` treats an absent `versions.json` as an
empty in-memory map, while a present empty map is a distinct file
(`lib/version_manager.py:171-182`). `add_version()` accepts `source_file=None`
and still records a snapshot path without copying bytes (`:364-431`). A
follow-up current-worktree call-site check found that all four production
callers supply `source_file`: `backup_current()` and
`ensure_current_tracked()` first check the current file exists
(`lib/version_manager.py:1106-1167`), while the image/video generator passes
its output path (`lib/media_generator.py:252-276,645-664`). This does **not**
make a recorded snapshot's bytes guaranteed: `add_version()` also skips the
copy when a supplied source path no longer exists, yet still persists the
record. Thus an H6 fail-closed missing-snapshot rule is defensible for a
verified exact restore, but a pre-existing missing history file blocks that
capture until source repair or a rejected-attempt disposition; it is not an approved
pending state merely because the parameter is nullable. Conversely,
`purge_resource()` removes its record before best-effort unlink of snapshots,
so an unreferenced history file can remain after a legitimate purge
(`:1169-1196`). No read-only H6 reader should call version migration, restore,
or archive repair to normalize these cases during capture.

V1-02 decision/fault cases: absent versus present-empty `versions.json`;
selected and unselected version records with missing files; a rejected-but-
retained version; an orphan snapshot after purge; path escape/symlink in a
record's `file`; and mismatch between selected history bytes and the current
formal file. The policy must say which references are required for an exact
recovery claim and how to handle a pre-existing dangling record. This is a
research inventory, not approval to trim history or reject production data
under an unreviewed rule.

The existing index has no top-level schema discriminator in the ordinary
`VersionManager` writer (`lib/version_manager.py:384-431`); `get_versions()`
projects one resource, adds `is_current`/`file_url`, and makes absent index and
absent resource look alike (`:171-221`). Reuse `RESOURCE_TYPES`,
`version_snapshot_dir()` and `is_managed_snapshot_path()` for typed bucket
vocabulary (`lib/resource_paths.py:42-57,88-103`;
`lib/version_manager.py:155-169`), but the latter only checks bucket, path
segment count and extension. A disposable probe returned true for a
`characters` snapshot named for a different resource; it does not verify the
record's resource ID, version or bytes. Another disposable probe made
`add_version()` persist one record when its source file was absent, with no
snapshot bytes. Those results agree with the source contract and are not a
reason to change the ordinary version API in this packet.

Candidate V1-02 rule: classify the raw index as absent, present-empty, valid
supported content or corrupt/unknown before any UI projection; bind **every**
declared `versions[*].file` to a no-follow physical record, regardless of
`current_version` or rejection status. Require a reviewed match among resource
key, version number and file path, using existing path vocabulary without
assuming the bucket check proves full identity. A missing declared snapshot
would fail `BACKUP_REQUIRED_FILE_MISSING` under the draft exact-recovery
policy; an unreferenced post-purge snapshot stays in the physical census with
an orphan disposition. Fixtures must include an absent and empty index, wrong
resource filename in the right bucket, missing unselected/rejected snapshot,
selected/current divergence and post-purge orphan. The historical filename
compatibility rule and exact identity grammar remain for review.

## Draft-design delta for review, not a schema choice

The current H6 draft enumerates project metadata/formal, `GLOBAL_ASSET`, and
candidate-media roles in its inventory description
(`docs/superpowers/specs/2026-09-25-r2-v1-m7d-recovery-closure-design.md:163-189`).
The source findings above additionally require an explicit disposition for
project-local profile state/tombstones, non-formal inputs and thumbnails,
`versions.json` and historical snapshots, pending script references, and
remote-capable `video_uri`. Calling these all “formal” would contradict the
Artifact Manifest's narrower registration semantics; omitting them would
weaken the draft's complete-project/recovery claim. This is a gap to resolve
*before* freezing `BackupInventoryEntryV1`, not an accepted role expansion.

The review must choose and document, for each class, one of: exact captured
bytes and binding; a separately authenticated custody/provisioning artifact;
an intentionally pending/remote reference that is verified by its own rule;
or an explicit V1 exclusion with a narrowed recovery claim. The same review
must define handling of unrecognized project files and stale/orphan bytes,
because neither the current archive's visible-tree filter nor a blanket tree
copy preserves both completeness and custody safety. Fault tests should
assert each chosen disposition, including absent-versus-empty metadata,
duplicate bindings, same-path content drift, and missing selected/unselected
history. No implementation may silently pick a disposition by filename.

## Next decision gate

Before freezing `BackupInventoryEntryV1` or `BackupManifestV1`, resolve:

1. the exact project enumeration domain (including hidden, malformed,
   transient, and DB-orphan cases) and the canonical identity of a project;
   enumerate the exact DB row types that establish live project authority,
   define each liveness predicate and historical-row exclusion, and decide
   whether deletion needs a durable tombstone or row retirement. Specify typed
   handling for filesystem-only, intentionally deleted, and corrupt DB-only
   identities; no production capture adapter can infer this from names alone;
2. the full authoritative file-reference surface in `project.json`, Artifact
   Manifest, master rows, `assets`, `asset_derivatives`, and other DB-to-file
   references; specifically classify historical `api_calls.output_path`
   and external `credentials_path` by restore authority rather than by
   column-name pattern (adaptation `target_path` is semantic, not a file);
3. how an absent versus empty Artifact Manifest is encoded without inventing
   a file, and how zero formal files are proved;
4. a separate safe-relative-path rule for backup inventory, with physical
   containment/symlink checks performed again by the capture and restore
   adapters;
5. the global-asset binding identity (asset versus derivative table, row ID,
   reference field and media kind), duplicate shared paths, null references,
   unreferenced orphan files, and absent versus empty `_global_assets` root;
6. project-local profile customizations and tombstones, together with the
   exact transient/secret/unknown-path rule. The project export's hidden-file
   filter is not an H6 backup policy;
7. current project/script path-field writers and readers beyond the positive
   archive-repair sample, including the pending episode-ledger case and
   local-versus-remote `video_uri`, `storyboard_last_image`, `end_frame_image`,
   `video_thumbnail` missed by the present validator, product originals/sheet,
   and character derivative sheets;
8. exact `versions.json`/snapshot history scope, including selected,
   rejected-but-retained, missing and orphan snapshot cases. A current-only
   portable export is not an exact H6 restore.
9. `grids/grid_*.json` identity and read-only parsing, with explicit rules for
   its script, composite, split-frame and reference-image paths under each
   recorded status; UI-style malformed-record skipping cannot prove complete
   capture.
10. persisted presentation/subtitle projection pairs and their nested selected
    media paths, including optional absence and exact planner comparison;
    versioned task checkpoints and staging manifests, with required staged
    bytes determined from task/resume state rather than a path-name heuristic.
11. quarantine-draft `meta.source` selectors, including a named source, null
    derived episode source and an invalid or obsolete envelope.
12. profile-manifest path keys and tombstones, migration-failure repair
    pointers and storyboard-failure unit IDs; preserve their bytes while
    keeping their distinct profile, blocking-diagnostic and possibly stale
    diagnostic meanings.

These are open schema decisions, not reasons to reinterpret the accepted
pure `RecoveryConfigV1` parser as a production capture implementation.
