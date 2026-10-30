# Approved Ollama D migration — 2026-10-30

Base HEAD d102a0d7e93208748442f087e414c0bcfa2cdf2c. Sponsor authorized migrating Ollama models to the existing D model/media store to reclaim Linux space.

1. Capture model names/digests, service identity/configuration and root free space; require no active model job before switching.
2. Copy the complete model directory to D/ArcReel/ollama/models. Verify all nine files, manifest digests and blob SHA256 names. Preserve originals until real inference succeeds.
3. Keep User/Group=ollama and the private /mnt/arcreel ancestor permissions. Give ollama read/write ACLs only within its own D model tree and expose that tree through a service-specific systemd BindPaths mount at /var/lib/ollama-models. Use supported OLLAMA_MODELS and system mount dependency/UUID guard.
4. Prove filesystem read/write/atomic-replace behavior as UID ollama in the same bind-mount context before switching the real service. Verify it cannot list the private D ancestor.
5. Restart with the drop-in, verify unchanged model digests, generate Vietnamese text with the story model and an embedding with bge-m3. Use keep_alive=0 and serialize with ComfyUI GPU work.
6. Delete only the verified old files, restart and repeat the native model probes using the deployed ArcReel OllamaChatClient and its native non-truncating /api/chat payload. Record final storage, service and privacy checks with rollback instructions.

Ruling: do not grant ollama traversal of /mnt/arcreel or change its service user to anhtuan. A service-specific bind mount exposes only its model directory while preserving the existing private storage boundary. Existing context-length/parallel settings remain unchanged. No provider URL/model selection, database, application code or partition layout is changed.
