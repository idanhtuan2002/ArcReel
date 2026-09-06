# R2-M2 ArcReel Seam Discovery

**Status:** VERIFIED  
**Baseline:** `6ddedc775e7fe5f398b10081ab741985f7dceda7`  
**Branch:** `r2/main`  
**Discovery method:** codebase-memory-mcp 0.10.5 first, followed by targeted local source confirmation.

## Selected exact seam

### Manifest model
- Path: `lib/artifact_manifest.py`
- Symbol: `ArtifactManifestEntry`

### Manifest read
- Path: `lib/artifact_manifest.py`
- Symbol: `_load_unlocked`

### Manifest write
- Path: `lib/artifact_manifest.py`
- Symbol: `replace_entries_atomically`

### Current target read
- Path: `lib/artifact_currency.py`
- Symbol: `resolve_current_artifact_target`

### Manifest target activation
- Path: `lib/artifact_activation.py`
- Symbol: `activate_artifact_target_state`

### Currency projection
- Path: `lib/artifact_currency.py`
- Symbol: `ArtifactCurrencyResolver`

### Provenance
- Path: `lib/artifact_provenance.py`
- Symbol: `build_script_plan_basis`

### Lock / atomic replacement
- Path: `lib/artifact_manifest.py`
- Symbol: `_atomic_replace`

## Verified host semantics

- `ArtifactManifestEntry` is the manifest entry model.
- `ArtifactManifestAdapter` is the storage seam used by the manifest domain module.
- `ProjectArtifactManifestAdapter` is the durable project-directory JSON adapter.
- `replace_entries_atomically()` replaces complete target state under one manifest lock and one atomic rename.
- `_locked()` owns the durable manifest lock.
- `_atomic_replace()` performs final `os.replace(...)`.
- `ArtifactCurrencyResolver` projects artifact currency.
- `ArtifactManifest.compare_entry()` produces CURRENT / STALE and blockers/missing preserve native semantics.
- `artifact_is_usable()` treats CURRENT and STALE as usable while BLOCKED fails.
- `resolve_current_artifact_target()` is the current manifest-target read seam.
- `activate_artifact_target_state()` reconstructs/activates complete manifest target state and includes rollback on concurrent mismatch.

## Legacy regression protection

- `tests/integration/lib/test_artifact_manifest_storage.py`
- `tests/unit/lib/test_artifact_manifest.py`
- `tests/unit/lib/test_artifact_provenance.py`
- `tests/unit/lib/test_artifact_activation_schema_gate.py`
- `tests/integration/server/services/test_artifact_version_restore.py`
- `tests/unit/lib/test_version_manager.py`
- `tests/integration/server/services/test_video_artifact_currency.py`
- `tests/integration/lib/test_video_artifact_commit.py`
- `tests/integration/lib/test_project_manager_concurrent_save.py`

## Initial Host patch allowlist

- `lib/artifact_manifest.py`

This allowlist is intentionally minimal. Current evidence proves that adding an optional R2
metadata envelope requires extending the manifest entry/schema implementation in
`lib/artifact_manifest.py`. No current evidence proves that `lib/version_manager.py` or
`server/services/artifact_version_restore.py` must be modified.

If a later M2 TDD failure proves that per-version promotion requires a Host modification
outside this allowlist, execution MUST stop and amend this seam evidence before editing
that Host file. That is an implementation-discovery correction, not an architecture reopen.

## Version-selection clarification

ArcReel exposes two related but distinct concepts:

1. **Manifest target activation** — verified here through
   `activate_artifact_target_state()` and `resolve_current_artifact_target()`.
2. **Stored artifact-version restore/selection** — protected by
   `tests/integration/server/services/test_artifact_version_restore.py` and
   `tests/unit/lib/test_version_manager.py`.

M2 ApprovedMaster must not assume these are the same operation. Task 6 must first use the
existing version-restore API as a consumer. It may not patch version storage/restore unless
the Host allowlist is explicitly amended after a failing integration test proves that need.

## Decision

- Existing extension seam available: `YES`
- Parallel artifact registry required: `NO`
- New R2 SQL artifact registry required: `NO`
- Initial bounded Host schema patch: `lib/artifact_manifest.py`
