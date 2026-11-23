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

## In flight when this was written

Re-launched after the quota reset (first launch was stopped at the usage limit). Each agent now **appends its findings
to its own report file as it goes**; a partial file is usable and the rest can be re-run from the brief.

Three independent read-only research agents (sponsor asked for at least three independent deep rounds). If their
results are not recorded in `docs/research/2026-11-23-r2-independent-round-{a,b,c}.md`, they were lost: re-run them
with the briefs in [assembly-research-briefs.md](assembly-research-briefs.md).
- A — what needs to be done (plan completeness, order, estimates) + old UI vs new control page.
- B — what it will produce (step-by-step output quality with these models; quota arithmetic per episode).
- C — what could make it fail (pre-mortem, risk register, recurrence of the old failure patterns).

## Next steps, in order

1. Record the three research results, reconcile them, fix the plan (sponsor sees the conflicts).
2. Answer the UI question with evidence.
3. M1 work that needs no keys: `assembly/config/dramaclaw-profile.json`, `docs/r2/ASSEMBLY_MODELS.md`,
   `assembly/voice_adapter/`, `assembly/connector/voices.py` (+ tests).
4. When keys/relay arrive: M1.0 probes, then the rest of M1 and M2.
