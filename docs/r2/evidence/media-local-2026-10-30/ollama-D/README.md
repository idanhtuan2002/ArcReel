# Ollama model storage on D — verified 2026-10-30

Sponsor authorized moving the existing Ollama models to D to reclaim ext4 space. Base HEAD: d102a0d7e93208748442f087e414c0bcfa2cdf2c. No application code, provider URL/model selection, database or partition layout changed.

## Current layout

- Physical model store: `/mnt/arcreel/D/ArcReel/ollama/models` on NTFS UUID F676A3B876A3784F.
- Inside the Ollama service only: `/var/lib/ollama-models`, mapped through systemd `BindPaths`. `OLLAMA_MODELS` points at that service-local path. The host-side `/var/lib/ollama-models` directory is empty; do not use its empty host view to infer that the models are missing.
- Service remains `User=ollama`, `Group=ollama` (UID 997, GID 973). Existing context length 8192 and parallelism 1 remain unchanged.
- `/mnt/arcreel` stays private mode 0700 with no additional traversal ACL. Only the dedicated Ollama model subtree received ACLs/default ACLs for the Ollama account. The same-identity filesystem probe verified read/write, reopening a 0600 file, fsync and atomic replacement on NTFS; listing the private D ancestor remained denied.
- Installed drop-in: `/etc/systemd/system/ollama.service.d/arcreel-model-storage.conf`, matching the version beside this file. It requires/binds to the existing D mount and verifies the expected mounted UUID/type. Missing storage is not ignored.
- Ollama identity keys and the rest of its home remain at `/usr/share/ollama`; only model blobs/manifests moved. ComfyUI and TTS configuration were preserved.

## Retained models and integrity

| Model | Digest |
| --- | --- |
| qwen3.5-vimax:9b | 079e71a587e3dd0c00fb189521886d4b4513531ff0bf4b92708b1c21854bbca2 |
| bge-m3:latest | 7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab |

All nine files (seven blobs and two manifests) were copied. Source/destination sizes and SHA256 matched; blob filename digests also matched their content. All were rehashed before deleting originals. Exact old inventory was required, preventing deletion if an unrelated model appeared during the migration.

## Actual verification

1. File-level permission probe as the real service account passed before switching the real service. It did not require granting access to the private D ancestor.
2. After switching, API model names/digests were unchanged. `/proc/<service-pid>/root/var/lib/ollama-models/...` resolved to the same inode as the physical D file, proving the service used the new store.
3. Before deleting originals: native Vietnamese chat completed in 18.640 s; bge-m3 produced two 1024-element finite embeddings in 26.919 s. Both used keep_alive=0.
4. Deleted only verified old files, leaving the original directory empty (28 KiB directory structure). Restarted Ollama and rechecked model names/digests.
5. After deletion/restart: imported `lib.text_backends.ollama.OllamaChatClient` from deployed HEAD 0cef69a772f1d2946e452b918a8839b0f37fd2d9. Its actual native /api/chat request used stream=false, think=false, truncate=false, shift=false, num_ctx=8192, a JSON schema and keep_alive=0s. Vietnamese JSON matched the schema and completed with done_reason=stop in 6.153 s.
6. Post-restart bge-m3 returned one 1024-element finite, nonzero embedding in 4.511 s. All probes were serialized with ComfyUI; no image job was running.
7. Model digests remained unchanged, source files were absent, Ollama/mount/automount and ComfyUI/TTS services were active; ArcReel /health returned OK. Ollama version 0.32.6. Actual host reboot and disk-removal recovery were not tested.
8. Operational Python helpers passed focused ruff check / format --check. No product source/tests changed, so product suites were not run. No complete story workflow or story-quality acceptance is claimed.

## Verification-tool issue and recovery

The initial installer rolled back cleanly because `systemd-analyze verify` does not load fstab-generated mount units by default. The real mount was active. A temporary unit reproduced failure without generators and success with `--generators=yes`. The installer now uses that option; no mount dependency/UUID guard was removed. The generator verifier emitted an environment warning about a read-only bind remount; the actual requested model bind is writable and passed the independent filesystem/inode probes.

The older r2-v2-main graph had no Ollama symbols and coverage marked the deployed Ollama/story executor files missing. Direct deployed source confirmed ArcReel uses native /api/chat, so the final probe used its actual client rather than the initially assumed OpenAI-compatible path. No graph completeness claim is made.

Final free space: Linux root **32.94 GiB**, D **157.78 GiB**. Net root-space gain from the start snapshot is about **7.19 GiB**, including concurrent small filesystem changes. Raw measurements are in final-verification.json.

## Operation and rollback

- Status/logs: `systemctl status ollama.service`; `journalctl -u ollama.service`.
- Model list: `ollama list`; native API: `http://127.0.0.1:11434/api/tags`. API address and model IDs are unchanged.
- Future `ollama pull` stores files on D through the service's configured model path. The file-level write fixture was tested; a new network model download was not performed.
- The original root model files have been removed. To roll back, ensure no model job is running, stop Ollama, copy all verified D files back into `/usr/share/ollama/.ollama/models` with proper ollama ownership, verify hashes, remove only the migration drop-in, daemon-reload and start. Recheck model digests plus chat/embedding before deleting any D copy.
- The source unit and context-length override are unchanged; `service-before.txt` records them. Do not overwrite unrelated service overrides or remove the D mount while ComfyUI still uses it.
- Both partitions share one SSD. Relocation is not an independent-device backup.

Primary references: https://docs.ollama.com/faq (OLLAMA_MODELS and service-user permissions), https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html (service-specific BindPaths).
