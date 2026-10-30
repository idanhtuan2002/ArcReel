# Ollama D migration ledger

Base: d102a0d7e93208748442f087e414c0bcfa2cdf2c. Sponsor approved moving Ollama models.

- Existing Ollama 0.32.6 system service runs as ollama:ollama (UID 997/GID 973). Context length 8192 and parallelism 1 are preserved. Before switch /api/ps was empty; both models retained: qwen3.5-vimax:9b and bge-m3:latest.
- Store contains 9 files, 7752148645 logical bytes / 7752183808 allocated bytes. All copied to D; all source/destination SHA256 values match, and seven blob filename digests match file content.
- Scope: model directory only; Ollama identity keys/home remain on ext4. Do not change service user or expose the private D ancestor. Model ACLs are restricted to the Ollama subtree; a systemd BindPaths mount exposes it at /var/lib/ollama-models only inside service namespaces.
- Permission fixture as UID 997 proved model-manifest reads, creation of 0600 files in a 0700 directory, reopening, fsync and atomic replacement on NTFS; direct listing of /mnt/arcreel remained denied.
- First installer attempt rolled back before inference because systemd-analyze verify does not load fstab generators by default. The real mount was active. A temporary unit reproduced exit 1 without generators and exit 0 with --generators=yes; the installer was corrected to enable generators. No mount dependency or guard was removed.
- Second installation passed, with an environment warning about a read-only bind remount during the generator verification. The actual service uses a writable bind mount, independently verified by the fixture and matching D inode through /proc/PID/root.
- Native Vietnamese chat passed in 18.640 s. Native bge-m3 embedding passed in 26.919 s with 2 x 1024 finite values. Both used keep_alive=0. No complete story workflow acceptance is claimed.
- Graph r2-v2-main has no Ollama symbols; coverage marks lib/text_backends/ollama.py and server/story_authoring/executor.py missing in the older graph generation. Direct deployed source at 0cef69a772f1d2946e452b918a8839b0f37fd2d9 verified ArcReel uses native /api/chat through OllamaChatClient, not the OpenAI-compatible path. The final plan/probe was corrected accordingly.

Pending: finish original-file cleanup/restart; repeat embedding and the deployed non-truncating OllamaChatClient structured request; final disk/health/privacy checks; handoff.

## Final gate complete

- Rehashed source and D copies before removing exactly nine originals. Restart preserved both model digests.
- Deployed ArcReel OllamaChatClient produced schema-valid Vietnamese JSON with non-truncating native payload in 6.153 s, done_reason stop. Post-restart bge-m3 embedding returned 1024 finite nonzero values in 4.511 s.
- Final root free 32.94 GiB, D free 157.78 GiB. Parent 0700 and service identity preserved. All relevant services active; actual reboot not tested.
- Migration and rollback documented in README.md. No remaining gate for this bounded model-storage migration.
