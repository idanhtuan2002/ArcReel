# Assembly handoff — resume here

Updated 2026-11-23 (night), HEAD after 74fe7ac2f. Read with [GOAL](../../GOAL.md), [ASSEMBLY_PLAN](../ASSEMBLY_PLAN.md),
[redirection index](R2_REDIRECTION_2026-11-23.md) and [acceptance record](ASSEMBLY_ACCEPTANCE.md).

## State

- Branch `impl/r2-film-quality`, pushed; worktree `/home/anhtuan/content-production-os/.worktrees/r2-film-quality`.
- Production: ArcReel `r2-v2.5.90`, frozen (fixes only).
- Live tracker: [ASSEMBLY_CHECKLIST.md](../ASSEMBLY_CHECKLIST.md). Models: [ASSEMBLY_MODELS.md](../ASSEMBLY_MODELS.md).
- Done: M0 (+ images pinned by digest); M1a voices (adapter service `voice-adapter`, 172.17.0.1:23350) and local Wan
  video (`Wan22-5B-local`, ComfyUI bridge `comfyui-bridge` 172.17.0.1:8189); M1.0 probes all pass (ERNIE, Gemini,
  embedding, Seedream incl. base64 and `/images/edits`, watermark off, Wan through NewAPI). Profile
  `assembly/config/dramaclaw-profile.json` applied (My Config). Decisions D1–D29 in the plan.
- Services (systemd --user): `voice-adapter`, `comfyui-bridge`, `cloudinary-cleanup.timer`.

## Waiting on the sponsor

Nothing.

## Next steps, in order

1. M2 connector core (`assembly/connector/`): DramaClaw REST client (multipart ingest upload → `ingest/start` with
   `spine_template`), configure (`ethnicity`, `narration_style`, 720×1280, video backend `newapi_Wan22-5B-local`),
   drive `pipeline/status.next_step` task types, run state file, resume, retries, voice casting after `characters`.
2. First narrated film from "Chiếc đồng hồ của ông", then the drama film (huohuo formatter → headers → `drama`).
