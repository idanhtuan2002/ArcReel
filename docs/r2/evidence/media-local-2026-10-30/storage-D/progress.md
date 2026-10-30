# D migration execution ledger

Base HEAD c67aaf9265271abd979759169ab21d0483a7fbb7.

- Preflight: D ntfs3 mounted with UUID F676A3B876A3784F; about 170 GiB free; root about 20.7 GiB free. ComfyUI queue empty. No pre-existing D/ArcReel directory.
- All model directories and ComfyUI input/output/temp copied using rsync -rt --safe-links. Originals retained.
- Three destination model SHA256 values match upstream pinned manifest; all existing input/output file SHA256 values match original copies. See copy-verification.json.
- Stable /mnt/arcreel/D mount configured through pkexec system authentication. Existing desktop mount remains usable. fstab backup: /etc/fstab.arcreel-before-20261030T051649594247Z. Parent /mnt/arcreel is mode 0700 owned by anhtuan.
- findmnt --verify: 0 errors, warnings for pre-existing swap file, ntfs3 driver vs ntfs disk signature and pre-reload systemd state. daemon-reload completed; stable mount reports the expected UUID.
- Wrong-UUID findmnt guard returned 1 as expected. New ComfyUI unit uses a readable model precheck (triggers automount), then exact UUID/type check.
- Graph evidence Tier 2 from r2-v2-main generation 2026-10-15T01:19:44Z guided image-backend/data-dir discovery. Graph coverage has no recorded gap for lib/custom_provider/comfyui_image_backend.py and lib/app_data_dir.py; deployed source at 0cef69a772f1d2946e452b918a8839b0f37fd2d9 was read directly to verify the actual behavior.
- ArcReel fetches its own copy into the project output_path. Its data root also holds non-media metadata; it remains on ext4. No product source or database change is needed for this operational migration.

Pending: automount transition probe; switch ComfyUI configs; hide local weight fallback; actual project generation; remove verified originals; restart and repeat proof; final handoff.

## Completed gates

- Automount transition tested: stopped only the new mnt-arcreel-D.mount, started its .automount, accessed a model file and observed the expected NTFS UUID mounted automatically. Both system units active. Existing desktop D mount remained intact. No actual reboot performed.
- ComfyUI switched to extra_model_paths.yaml plus D input/output/temp CLI paths. Original user service/model manifest backed up at ~/comfyui/storage-before-D/.
- All three old loadable weight filenames were renamed to .migration-backup before restarting; model discovery still succeeded for UnetLoaderGGUF, CLIPLoaderGGUF and VAELoader, proving external paths work without local filename fallback.
- Real production project image via browser succeeded: prompt 9d79510c-cb88-46e1-9564-0dacded6d6c8; client wall 34.276 s; output on D ArcReel-FLUX2-klein_00003_.png, 1792 x 1008, sha256 11a234293461cfbb0e6f3f65982e636bcd42012062cbf55bb52395fcb32dccab. Browser decoded image at 1792 x 1008. ArcReel character/current and version files match the D image checksum.
- Rehashed both original-backup and destination copies against the pinned model manifest before deletion. Only verified source files were removed (see original-removal.json). Reclaimed 5.068 GiB; model manifest now points at D.
- ComfyUI restarted successfully after removing originals. No local model weights or migration-backup files remain.
- Mount installer Python passed ruff check and format --check after import/UTC formatting fixes; unit verify passed with an unrelated installed spice-vdagent warning.

Pending final gate: post-cleanup production image; final health/config/storage checks and durable handoff.

## Final gate complete

- Post-cleanup/restart production regeneration succeeded: c9a1e120-637b-4d63-9c58-7f7c9a75415d, 34.342 s client wall, 33.52 s ComfyUI. D output 00004 and current/version project copies share SHA256 33087de3c471df2884d122bb958fbaea6747436df588a6dba7ea7629b978b6d4.
- Final browser reload decoded the image successfully; screenshot saved. Final health, both services and mount/automount passed. Config defaults preserved.
- Original local weights/backups absent; current manifest paths on D exist with expected sizes. Final root free 25.76 GiB; D free 165.00 GiB (measurement in final-verification.json).
- Rollback steps and the limit on project-managed media copies are documented in README.md. All migration work is complete; no required gate remains for this bounded ComfyUI storage change.
