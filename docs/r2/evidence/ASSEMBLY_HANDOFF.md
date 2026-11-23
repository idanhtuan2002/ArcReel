# Assembly handoff — resume here

Updated 2026-11-23 (late). Read with [GOAL](../../GOAL.md), [ASSEMBLY_PLAN](../ASSEMBLY_PLAN.md),
[redirection index](R2_REDIRECTION_2026-11-23.md) and [acceptance record](ASSEMBLY_ACCEPTANCE.md).

## State

- Branch `impl/r2-film-quality`, pushed; worktree `/home/anhtuan/content-production-os/.worktrees/r2-film-quality`.
  No uncommitted work of this task.
- Production: ArcReel `r2-v2.5.90`, frozen (fixes only). Drama run `010a7912` left BLOCKED on purpose.
- **M0 accepted**: DramaClaw runs via `assembly/deploy/dramaclaw/up.sh` (project `assembly-dramaclaw`, loopback
  8780/8080/3000), NewAPI initialized in Custom mode, root password `~/assembly-data/secrets/newapi-root` (600),
  `.env` in `~/assembly-data/deploy/dramaclaw/`.
- Decisions D1–D26 in the plan (latest: D25 Vietnamese UI everywhere, D26 spine drama/narrated; D7 corrected: images
  via NewAPI OpenAI-type channel → BytePlus Seedream mapped to `LingShan-G2`).

## Waiting on the sponsor

1. Cloudinary account (recommended) or approval of the "inline" relay donor seam
   ([verification round §4](../../research/2026-11-23-r2-assembly-verification-round.md)).
2. Keys (OpenRouter, Gemini, BytePlus) pasted into DramaClaw → Settings → Models & Channels → Custom after the
   profile is loaded (M1).
3. Answer: old app UI vs new control page — to be decided from research round A below.

## Research done

Three independent rounds recorded and reconciled ([reconciled](../../research/2026-11-23-r2-independent-rounds-reconciled.md));
the plan's §0 holds the corrections. No new research notes until the first film.

## Next steps, in order

The live tracker is [ASSEMBLY_CHECKLIST.md](../ASSEMBLY_CHECKLIST.md); this list summarises it.

Sponsor answered 2026-11-23: video = local Wan through DramaClaw's ComfyUI channel (D27); GOAL amended for interface
languages (DramaClaw Vietnamese UI allowed); no Go/Kill or quota tolerance added to GOAL; media relay decided by the
M1.0 base64 probe (D28).

1. M1a (no keys): voice adapter (`assembly/voice_adapter/`, data: URL in, MP3 out, SHA-256 map, unknown = error) and
   casting (`assembly/connector/voices.py`, after `characters`), with tests.
2. M1a: DramaClaw ComfyUI channel with our local Wan workflow (video), probe one clip.
3. Sponsor keys (OpenRouter, Gemini, BytePlus) → M1.0 probes incl. base64 on Seedream and the ComfyUI channel → D28.
4. M2 per plan §0/§5.
