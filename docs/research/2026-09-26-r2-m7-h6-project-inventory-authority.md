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
| `provider_credential.credentials_path` | Provider connectivity reads a separate credential file (`lib/db/models/credential.py:30`; `server/routers/providers.py:771-779`). | Keep this outside non-secret inventory; require the approved custody/restore profile's separate provisioning proof or proof that the profile needs no such secret. Never embed the path or bytes in a public manifest. |

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

Candidate scope choices for schema review, not settled policy:

| Choice | Benefit | Unclosed risk / required proof |
| --- | --- | --- |
| All regular project files, except an exact runtime exclusion set | Retains otherwise unknown user files and version history. | Audit secrets, symlinks, sockets, temporary/lock files and the exact exclusion set; classify unknown hidden paths before release. |
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
and still records a snapshot path without copying bytes (`:364-431`); this
does not prove current production callers use that state, but it prevents a
blanket assumption that every record has bytes. Conversely,
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

These are open schema decisions, not reasons to reinterpret the accepted
pure `RecoveryConfigV1` parser as a production capture implementation.
