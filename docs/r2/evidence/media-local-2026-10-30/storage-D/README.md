# D storage migration — completed 2026-10-30

The sponsor-approved ComfyUI storage migration is complete. Application source, virtual environments, database and ArcReel's managed project copies remain on Linux ext4. Only existing ComfyUI model weights and its provider-side input/output/temp media were migrated. Ollama storage was not changed. No partition resizing or formatting occurred.

## Current locations

| Content | Path |
| --- | --- |
| Model root | `/mnt/arcreel/D/ArcReel/comfyui/models` |
| Generated provider images/video | `/mnt/arcreel/D/ArcReel/media/comfyui/output` |
| Uploaded provider input | `/mnt/arcreel/D/ArcReel/media/comfyui/input` |
| Provider temporary media | `/mnt/arcreel/D/ArcReel/media/comfyui/temp` |
| Source and Python environment | `~/comfyui` and `~/comfyui/.venv` |
| Project-managed asset copies | `~/arcreel-v2-staging/data/<project>/...` |

D is NTFS UUID `F676A3B876A3784F`. The stable mount `/mnt/arcreel/D` comes from `/etc/fstab` with `nofail,x-systemd.automount`; `/mnt/arcreel` is private (0700, anhtuan-owned). The desktop D mount was preserved. Configuration is in `extra_model_paths.yaml` and `arcreel-comfyui.service` alongside this file. These copies match the installed files.

The user service first accesses a required model (triggering automount), then verifies the exact mounted UUID and ntfs3 type before starting ComfyUI. If D cannot be mounted, startup fails rather than silently using a root-filesystem output directory. The unit retries on failure. This guard was exercised with a deliberately wrong UUID; a real disk-failure/Windows-hibernation scenario was not tested.

## Verification

- Every destination weight matches its pinned upstream SHA256. Existing provider media matches its source checksum. Original weights were hidden from model discovery before the first production proof.
- Automount was tested by stopping only the new stable mount, starting its automount and accessing a model. The expected UUID mounted automatically. No actual host reboot was performed.
- First production regeneration via the browser succeeded with only D weights discoverable: 1792 x 1008, 34.276 s client wall time. The resulting image was stored on D and the project's current/version PNGs matched its SHA256.
- Rehashed both model copies against upstream pins before deleting originals. Removed only files matching verified D copies; net root-space gain was 5.068 GiB.
- Restarted ComfyUI with no local weights or backups left, then regenerated from the same real project: 1792 x 1008, 34.342 s client wall time; ComfyUI reported 33.52 s. Output: `ArcReel-FLUX2-klein_00004_.png`, SHA256 `33087de3c471df2884d122bb958fbaea6747436df588a6dba7ea7629b978b6d4`.
- Final current project asset and version PNG match the D output checksum. Browser reload decoded it at 1792 x 1008; screenshot is `project-D-final.png`.
- ArcReel /health, ComfyUI /system_stats, both provider user services, system mount and automount all passed. ComfyUI remains enabled.
- Image default remains `custom-3/flux2-klein-4b-gguf`; TTS remains `custom-2/vieneu-tts-v3-turbo`; video remains paid Veo. This migration does not accept a free-video gate.
- Mount installer passed ruff check and format --check. Unit verification passed; it emits an unrelated pre-existing spice-vdagent unit warning. No product code/tests were changed, so product suites were not run.

Final free space: Linux root **25.75 GiB**, D **165.00 GiB**. Final measurements are in `final-verification.json`.

## Operation

- Status: `systemctl --user status arcreel-comfyui.service`; storage: `systemctl status mnt-arcreel-D.automount mnt-arcreel-D.mount`.
- Logs: `journalctl --user -u arcreel-comfyui.service`.
- Put future model weights in the appropriate subfolder on D and select them in the workflow. Add an extra-model-path key if introducing a model category not listed in the current YAML.
- ArcReel keeps its own project-managed copy of generated media for versioning and custody. Those copies can continue to consume ext4 space. Moving the entire application data root is a separate change and has not been done.
- Both volumes are partitions of the same physical SSD; the D copy is storage relocation, not an independent-device backup.

## Rollback

Configuration backups: `~/comfyui/storage-before-D/` (old user unit and old manifest). fstab backup: `/etc/fstab.arcreel-before-20261030T051649594247Z`.

1. Stop the ComfyUI user service and ensure its queue is empty.
2. Copy each verified D model back to its `original_local_path` from the current manifest, checking SHA256. Copy D provider input/output files back to the old ComfyUI directories if returning those paths too. The verified originals on ext4 were removed; restoring the old unit alone is insufficient.
3. Restore the old unit/model manifest, remove or disable the extra-model-path YAML, reload the user daemon and start ComfyUI. Prove model discovery and a real image before deleting any D copy.
4. Only when no consumer uses the stable mount, optionally remove its exact ArcReel fstab entry and stop its automount/mount. Do not blindly replay the whole historical fstab over unrelated later changes.

The shared root checkout's unrelated dirty work was preserved. This evidence belongs to the m10-c worktree, starting at c67aaf9265271abd979759169ab21d0483a7fbb7.
