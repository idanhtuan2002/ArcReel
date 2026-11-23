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

1. Sponsor answers: video money, GOAL amendment (DramaClaw Vietnamese UI), GOAL additions, Cloudinary.
2. M1 work that needs no keys: `assembly/config/dramaclaw-profile.json`, `docs/r2/ASSEMBLY_MODELS.md`,
   `assembly/voice_adapter/`, `assembly/connector/voices.py` (+ tests).
3. Set up DramaClaw's ComfyUI channel with the local Wan workflow (free video route).
4. When keys/relay arrive: M1.0 probes, then the rest of M1 and M2.
