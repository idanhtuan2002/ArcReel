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
   `projects_root`, excluding names beginning with `.` or `_`; project names
   must match `^[A-Za-z0-9-]+$`. `create_project()` creates the directory and
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
   classification, not a conclusion from its column name.

## Inference and alternatives

- A V1 manifest whose project count comes only from SQL would miss a
  filesystem-only project. Conversely, copying only the UI-visible
  `list_projects()` names would silently ignore disallowed/hidden directories
  and DB rows referring to a missing project. The capture adapter needs two
  independently enumerated sets: approved project directories under the
  project root and all project-scoped authoritative DB references. It must
  reconcile them before and after the dump, with a typed discrepancy failure.
- `project.json` is required for every admitted project directory by the
  draft H6 design. A directory lacking it is a fail-closed capture error,
  not a zero-formal-file project. Zero formal files may still be valid when
  the Artifact Manifest and restored DB both have no formal references.
- `_global_assets` cannot be ignored or classified as a normal project. A
  candidate V1 manifest needs a separate `GLOBAL_ASSET` entry role beneath
  the existing logical project root, with exact DB-row/path bindings and
  size/hash checks; missing or out-of-root references fail capture. Whether
  unreferenced orphan files in that directory are retained or rejected is a
  separate explicit policy choice, not a silent omission.
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

## Next decision gate

Before freezing `BackupInventoryEntryV1` or `BackupManifestV1`, resolve:

1. the exact project enumeration domain (including hidden, malformed,
   transient, and DB-orphan cases) and the canonical identity of a project;
2. the full authoritative file-reference surface in `project.json`, Artifact
   Manifest, master rows, `assets`, `asset_derivatives`, and other DB-to-file
   references; specifically classify historical `api_calls.output_path`
   and external `credentials_path` by restore authority rather than by
   column-name pattern (adaptation `target_path` is semantic, not a file);
3. how an absent versus empty Artifact Manifest is encoded without inventing
   a file, and how zero formal files are proved;
4. a separate safe-relative-path rule for backup inventory, with physical
   containment/symlink checks performed again by the capture and restore
   adapters.

These are open schema decisions, not reasons to reinterpret the accepted
pure `RecoveryConfigV1` parser as a production capture implementation.
