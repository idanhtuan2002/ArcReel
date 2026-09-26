# R2 M7 H6: current project path writers and readers

**Status:** bounded V1-02 research; no production change.

**Observed worktree:** `r2-m7e-v1-lineage` at `8dba59f5` (2026-09-26).

**Question bounded here:** first-party writers/readers for the named path-bearing
fields in `project.json` and the episode scripts it names. This is not a complete
schema inventory, a backup policy, or a proof that no other writer exists.

## Persistence boundary

`ProjectManager.save_project()` locks and atomically writes `project.json`;
`update_project()` is a separate locked read-modify-write seam used by the
project-level field mutators below (`lib/project_manager.py:2004-2077`).
Script-level fields are committed through `locked_script()` / the script write
path; `update_scene_asset()` deliberately writes only a selected
`generated_assets` member (`lib/project_manager.py:1557-1624`).

The following classification is evidence about *current values*, not a proposed
H6 policy:

- **Required binding:** a field required by the structural validator.
- **Pending/optional:** empty or absent is an explicitly supported pre-generation
  state; a nonempty local value is still a file reference.
- **Remote-capable:** an external URI is accepted only for `video_uri`; a local
  value in that same field remains a local file reference.

## Project metadata (`project.json`)

| Field | State and current writer(s) | Reader / validation evidence |
| --- | --- | --- |
| `style_image` | Pending/optional local file. `POST /projects/{project_name}/style-image` writes bytes as `style_reference.<ext>` and stores the bare filename through `update_project()` (`server/routers/files.py:980-1044`). Choosing a template or explicit clear removes it (`server/routers/projects.py:1023-1043`). | Tree validation treats a nonempty value as a local reference (`lib/data_validator.py:1501-1506`); style migration prefers it over legacy template style (`lib/project_manager.py:1859-1875`). |
| `characters[*].character_sheet` | Pending/optional local file. Asset upload dispatch maps character sheets to `update_project_character_sheet` (`server/routers/files.py:100-145`); asset creation initializes the sheet field to `""` (`lib/project_manager.py:3623-3638`). There is also the legacy script-scoped writer `update_character_sheet()` for a character within a script (`lib/project_manager.py:1363-1372`), which is not the project-level field. | Tree validation uses `characters/` as a basename fallback, not a confinement rule (`lib/data_validator.py:201-250,1513-1519`); project-cover selection reads it when no stronger video/storyboard cover exists (`server/services/project_cover.py:100-109`). |
| `characters[*].reference_image` | Pending/optional local file. The files router maps the character-reference upload to `update_character_reference_image` (`server/routers/files.py:100-154`), which stores the supplied relative path through `update_project()` (`lib/project_manager.py:3380-3399`). | Validator accepts absence/empty and otherwise checks a project-contained local reference, with `characters/refs` as a basename fallback (`lib/data_validator.py:201-250,1520-1526`). |
| `characters[*].reference_audio` | Pending/optional local file. Normal upload installs bytes and pointer atomically (`server/routers/files.py:375-401`; `lib/project_manager.py:3435-3472`); clearing changes the field to `""` then best-effort removes an unreferenced former file (`lib/project_manager.py:3503-3525`). Global asset-library import is a separate writer (`server/routers/assets.py:720-748`). | Validator checks a project-contained local reference, with `characters/refs_audio` as a basename fallback (`lib/data_validator.py:201-250,1527-1533`). Video generation uses the field as a current voice input, so a nonempty value has production significance beyond display. |
| `scenes[*].scene_sheet` | Pending/optional local file. Files upload dispatch maps it to `update_scene_sheet` (`server/routers/files.py:155-171`), which delegates to the project asset-sheet update seam (`lib/project_manager.py:3531-3535`). | Validator checks a project-contained local value, with `scenes/` as a basename fallback (`lib/data_validator.py:201-250,1540-1546`). |
| `props[*].prop_sheet` | Pending/optional local file. Files upload dispatch maps it to `update_prop_sheet` (`server/routers/files.py:166-171`), which delegates to the same asset-sheet seam (`lib/project_manager.py:3549-3553`). | Validator checks a project-contained local value, with `props/` as a basename fallback (`lib/data_validator.py:201-250,1553-1559`); `collect_reference_images()` reads it when preparing scene references (`lib/project_manager.py:3700-3723`). |
| `episodes[*].script_file` | **Required binding** when an episode entry exists: missing/empty or non-string is a validation error (`lib/data_validator.py:447-470`). Writers are `_apply_episode_sync()`, which stores `scripts/{normalized-name}` after a script write (`lib/project_manager.py:1227-1255`), and `add_episode()` (`lib/project_manager.py:2509-2534`). | It is a local script path. Full-tree validation allows a missing target as a deliberate forward/pending episode-ledger state only when the episode number is valid (`lib/data_validator.py:1561-1589`). Project cover and route readers load it, but skip unavailable scripts rather than making a project unreadable (`server/services/project_cover.py:60-79`). |

## Episode-script `generated_assets`

All named fields are initialized to `None` with `status="pending"`; that is the
normal pre-generation state, not evidence of a missing file (`lib/project_manager.py:1376-1398`).
`GeneratedAssets` models each as nullable (`lib/script_models.py:184-202`).

| Field | State and current writer(s) | Reader / validation evidence |
| --- | --- | --- |
| `storyboard_image` | Pending/optional local file. The image-finalization seam updates the selected script item through `update_scene_asset(..., "storyboard_image", artifact_path)` (`server/services/generation_tasks.py:1126-1184`). | Nonempty values are local references validated with `storyboards/` as a basename fallback (`lib/data_validator.py:201-250,763-769`); cover selection reads them after thumbnails (`server/services/project_cover.py:93-98`). |
| `video_clip` | Pending/optional local file. Standard video finalization writes `videos/scene_{id}.mp4` through `update_scene_asset()` (`server/services/generation_tasks.py:2757-2786`). Reference-video finalization writes `reference_videos/{unit_id}.mp4` via `apply_unit_video_assets()` (`server/services/reference_video_tasks.py:793-835,838-871`). Version restore also sets a local clip and clears remote/thumbnail sidecars (`server/services/artifact_version_restore.py:190-200`). | Validator requires a local reference for a nonempty value (`lib/data_validator.py:777-783`). |
| `narration_audio` | Pending/optional local file. TTS commit creates `generated_assets` if absent and writes the selected `audio_rel`; cancellation compensates it back to the prior value or removes it (`server/services/generation_tasks.py:2009-2022,2145-2165`). | Validator checks a nonempty project-contained local value, with `audio/` as a basename fallback (`lib/data_validator.py:201-250,792-798`). |
| `video_thumbnail` | Pending/optional local file. Normal video finalization writes it only if thumbnail extraction succeeds (`server/services/generation_tasks.py:2788-2800`); reference-video finalization writes or removes it based on the same outcome (`server/services/reference_video_tasks.py:856-869`). Manual shot upload uses the same three-field update contract (`server/services/upload_finalize.py:280-315`). | The project-cover reader prefers it (`server/services/project_cover.py:60-98`). Important gap: `_validate_generated_assets()` validates storyboard, clip, URI, and narration but has **no `video_thumbnail` local-reference check** (`lib/data_validator.py:750-798`). A passing validator result therefore does not prove thumbnail bytes exist. |
| `video_uri` | **Remote-capable, optional sidecar.** Normal finalization writes it only when the provider supplies a URI (`server/services/generation_tasks.py:2769-2786`). Reference-video finalization writes it when supplied and otherwise removes any stale value (`server/services/reference_video_tasks.py:823-832`). Manual upload and version restore clear it (`server/services/upload_finalize.py:293-303`; `server/services/artifact_version_restore.py:194-200`). | The validator accepts a matching external URI but otherwise applies local-file validation (`lib/data_validator.py:252-290,784-791`). Thus the field name alone is insufficient for H6 classification: an external URL has no local-byte closure, while a local value must be inventoried as a file. |

## Bounded gaps and H6 implications

1. This pass followed the named fields through the current first-party project
   manager, router, generation, reference-video, restoration, and validator
   paths. It does not establish every historical migration/import/archive writer;
   migration scope inspection reported only an excluded `__pycache__` subtree,
   not evidence of semantic completeness.
2. `ProjectArchiveService` repair is intentionally excluded: it is mutating
   recovery/repair behavior, not an H6 backup capture policy. It must not be
   treated as a read-only source of truth for what a backup reader should repair.
3. H6 needs an explicit value-sensitive rule for `video_uri`, and an explicit
   thumbnail existence/hash check if thumbnails are in scope. Existing validator
   success is insufficient for the latter.
   Most `default_dir` arguments above are basename lookup fallbacks, not
   directory confinement; `_resolve_existing_path()` first accepts any
   project-contained candidate and only then tries the fallback
   (`lib/data_validator.py:201-250`). `end_frame_image` is a separate case
   that explicitly sets `confine_to_default_dir=True` (`:812-832`). H6 must
   define canonical path/role containment independently.
4. The graph index was generation `2026-09-18T10:57:40Z`; coverage was clean for
   the cited paths except `server/services/generation_tasks.py`, whose metadata
   was changed. The current worktree source was read directly for every cited
   generation-task assertion. Coverage remains best-effort, not an exhaustive
   absence proof.
