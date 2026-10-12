# M8-C checkpoint reader in a disposable running container

Status: bounded positive filesystem observation at clean `38d7a628c0aa0a3cdc244b32e26f7d64f8a5710d`, 2026-10-12. This is not a production Compose drill or recovery acceptance.

## Image and source boundary

Cached `arcreel/arcreel:latest` had image ID `sha256:d56db7fdbebc8a8c13b46a44956707e5bbb0b6052fa324061ac3bc3769aedd63` and Python 3.12.14. Direct inspection inside the image returned `r2_absent`. The current `Dockerfile` copies `lib/`, `server/`, `alembic/`, `scripts/`, `agent_runtime_profile/` and `public/`, but has no `COPY r2/`. Since the M8-C scanner and reader import `r2` contracts, a future application image built from this Dockerfile cannot run that code without a packaging change. The cached image itself is older than the current worktree and is not evidence that new M8-C code is packaged.

For a narrow reader/mount probe, a disposable container based on that cached image received three read-only binds: the current worktree's `r2/` at `/app/r2`, the current `governance_checkpoint_file.py` at its module pathname, and a fresh temporary host directory at `/run/arcreel/governance`. It ran `/app/.venv/bin/python`, loaded `GovernanceCheckpointFile` by import and called its async `load()` each time. No application server, database, project data, provider or production Compose stack started.

The host first wrote `old` to `grant-checkpoint.json`, then wrote `new-complete` to a sibling `checkpoint.pending`, queried while that sibling was present, and finally renamed it over the fixed name. The running container returned:

```text
before=old
pending=old
after=new-complete
mount_write=denied
```

The write probe also received `Read-only file system`. The disposable container `arcreel-m8c-reader-drill-20261012` was stopped and auto-removed; the temporary host directory was removed by the trap, and a filtered `docker ps -a` returned no matching container. These results support the pathname-reopen/same-directory-rename candidate on this host and image. They do not prove the actual production Compose mount, full signed checkpoint verification, concurrent transaction publication, crash durability, key rotation, a pinned rebuilt image, startup readiness, or restore behavior.

Next deployment gate: add `r2/` to a candidate image only after its affected build/tests are scoped, pin that exact image digest, and run the Compose drill against that candidate and the operator custody layout. Keep Governance APPROVE/READY inactive meanwhile.
