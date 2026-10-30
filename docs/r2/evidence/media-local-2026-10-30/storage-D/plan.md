# Approved D storage migration — 2026-10-30

Base HEAD c67aaf9265271abd979759169ab21d0483a7fbb7. Sponsor approved using D for models and media after reviewing the storage assessment. This is operational configuration of existing ComfyUI interfaces; no product code or partition changes.

1. Verify mounted D UUID F676A3B876A3784F, free space, existing services and empty queue.
2. Copy immutable model weights and ComfyUI input/output/temp to D/ArcReel; preserve originals until verification.
3. Add a stable, private-parent system mount /mnt/arcreel/D by UUID with nofail + automount, keeping the current desktop mount usable. Back up fstab. System authentication may be needed; no partitions are resized.
4. Configure ComfyUI extra_model_paths.yaml, input/output/temp CLI options and startup mount checks. Keep source, venv, database and ArcReel's managed project copies on ext4.
5. Verify checksums, model discovery, real project generation and service restart. Confirm startup checks reject an absent/wrong storage device.
6. Remove only original files that match the verified D copies, reclaim root space, re-run inference without local weight fallback, document final state and rollback.

Ruling: ArcReel keeps a project-managed copy of generated assets. Moving its entire data root would also move metadata and change production custody behavior. This operational change moves ComfyUI's weights and provider media only; application data root stays unchanged.
