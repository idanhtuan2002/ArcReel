# R2-M3 Golden A — Seam Discovery

**Status:** VERIFIED
**Observed HEAD:** `9a47c9265da6f99a6a976584f53d67a67f8a3ae5`
**Workspace mode:** `IN_PLACE_USER_APPROVED`
**CBM project:** `home-anhtuan-content-production-os`

## Selected seams

| Seam | Decision |
|---|---|
| Contracts export | `r2/contracts/__init__.py` |
| OpenMontage | `FIXTURE_ADAPTER` |
| Composition | `FFMPEG_EXISTING` |
| FFmpeg | `/usr/bin/ffmpeg` |
| ffprobe | `/usr/bin/ffprobe` |
| Artifact Manifest | `lib.artifact_manifest.ProjectArtifactManifestAdapter` |
| R2 Artifact Port | `r2.production.ArcReelArtifactManifestPort` |
| Version manager | `lib.version_manager.VersionManager` |
| Version promoter | `r2.production.ArcReelVersionRestorePromoter` |
| Artifact key strategy | `lib.artifact_manifest.ArtifactKey.episode_video(episode: 'int', resource_id: 'str') -> 'Self'` |
| Screen capture | `DEFERRED` |
| Host patch allowlist | `[]` |

## Cost / provenance sources

- `lib/artifact_provenance.py`
- `lib/artifact_currency.py`
- `r2/contracts/execution.py`
- `r2/contracts/preparation.py`
- `lib/kling_shared.py`
- `lib/asset_derivatives.py`
- `lib/project_migrations/staged_swap.py`
- `lib/project_migrations/runner.py`
- `lib/project_migrations/v9_to_v10_script_plan_naming.py`
- `lib/reference_video/request_projection.py`
- `lib/ledger.py`
- `lib/artifact_activation.py`

## codebase-memory-MCP

Task 0 indexed/queried the repository with codebase-memory-MCP before targeted
filesystem/source probes. Raw query outputs were hashed into the JSON evidence.

## Notes

- CBM mentions OpenMontage but no local callable integration was proven; use approved FIXTURE_ADAPTER.
- No proven Remotion composition seam found in repository.
- SCREEN_CAPTURE remains DEFERRED for baseline Golden A; it is optional by approved spec.
- Initial Host patch allowlist remains empty.
- No production code was modified during Task 0.

## Task 0 decision

Checkpoint A is documentation/seam evidence only. Production implementation may
start at Task 1 only after this evidence is reviewed. Any requirement to modify
Host runtime files must stop execution and amend the approved plan because the
current Host patch allowlist is empty.
