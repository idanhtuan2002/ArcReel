# Storage cleanup and D partition assessment — 2026-10-30

## Scope and authorization

Sponsor requested cleanup of the previously identified reclaim candidates, followed by checking D and whether the current Linux partition can be safely expanded. No partition resizing, formatting, unmounting or model migration was performed.

## Executed cleanup

- `uv cache clean --cache-dir /home/anhtuan/.cache/uv`: completed, reported 96122 files / 6.6 GiB logical content removed. Preflight scanned 32 venvs and found zero symlinks into that cache. Existing hardlinked environment files remain valid.
- Removed 11 old app-server-daemon releases: 0.157.1, 0.158.0, 0.159.0, 0.159.1, 0.159.2, 0.159.3, 0.160.0, 0.160.1, 0.162.1, 0.163.0, 0.164.0. Revalidated executable paths before removal. Kept current 0.166.0 and previous 0.165.0 per selection-history.
- Removed disposable download caches: `~/.cache/pip`, `~/.npm/_cacache`, `~/.cache/google-chrome` (Chrome not running).
- Preserved Coccoc cache because its browser executable is active; also preserved npm _npx tools, Docker images/volumes, worktrees, sessions, models, production data/backups and swap.
- Root available bytes before: 11159916544; after verification: 22216450048. Net measured gain: 10.297 GiB. Available: 20.691 GiB (`df -h`: 21G, 89% used).

## D and physical layout (read-only)

D was already mounted when inspected at `/run/media/anhtuan/D`, ntfs3. `df -B1`: capacity 297150705664, used 114539380736, available 182611324928 bytes (170.07 GiB available).

Same physical SSD `/dev/nvme0n1`, total 512110190592 bytes:

| Partition | Start byte | End byte, exclusive | Size | Role |
| --- | ---: | ---: | ---: | --- |
| nvme0n1p1 | 1048576 | 297151758336 | 276.743 GiB | NTFS D |
| nvme0n1p2 | 297151758336 | 298278977536 | 1.050 GiB | EFI mounted /boot/efi |
| nvme0n1p3 | 298278977536 | 512108789760 | 199.145 GiB | ext4 Linux / |

There is no gap between these three partitions. Only 1400832 bytes remain after p3, including trailing partition-table/metadata space. This is not usable capacity for a meaningful root expansion.

UDisks drive properties expose an empty SmartCriticalWarning, SmartSelftestStatus success, temperature 312 K. These are supplied device telemetry, not a new full self-test or proof of filesystem health. No NTFS shrink-limit/error check or root fsck was performed; direct raw block-device access/sudo is unavailable without interactive authentication.

## Assessment, not authorization to resize

Ordinary expansion at the right edge of p3 cannot add meaningful space. Free bytes inside D are not unallocated adjacent sectors. To transfer D capacity into the existing root partition requires shrinking D and relocating the intervening EFI partition and the start of Linux (or a different backup/restore/migration design). A root-start move cannot be done while root is mounted and introduces boot/data recovery risk. It is technically possible with verified independent backups, live boot media, filesystem/shrink checks and a concrete offline plan; this inspection does not establish that it is safe to execute now.

Lower-risk candidate for the current media task: keep D as NTFS and store model weight files / generated media there; keep Python environments, source and database on ext4. Existing ComfyUI supports external model paths through `extra_model_paths.yaml`; the local example was read. A stable mount and startup dependency must be designed/verified before migration. No files have been moved to D.

Primary sources:
- https://gparted.org/display-doc.php?name=help-manual (adjacent unallocated space, offline moves, boot/data risk)
- https://docs.astral.sh/uv/concepts/cache/ (official cache-clean command)
- https://docs.comfy.org/basic-concepts/models (extra_model_paths.yaml)

## Post-cleanup verification

- `current/bin/codex --version`: codex-cli 0.166.0.
- Only 0.165.0 and 0.166.0 remain under app-server-daemon/releases.
- ArcReel `/health`: OK. ComfyUI `/system_stats`: responds successfully.
- Both `arcreel-comfyui.service` and `vieneu-tts-shim.service`: active.
- No application source, database schema or partition table changed.
