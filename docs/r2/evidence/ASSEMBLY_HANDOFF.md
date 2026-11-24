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

## Film 1 (running)

- Unit `assembly-film-1` (systemd --user), log `~/assembly-data/runs/film-1.log`, state
  `~/assembly-data/runs/01M84JWC2DRNK6SAX24RX3VMG4.json`. Resume: `python -m assembly.connector --state <state> --approve CP1`
  (sponsor waived CP1 for this film). Blocks so far: `R2_RUN_BLOCK_LEDGER.md` rows "assembly 01M84JWC".
- DramaClaw is **v2.1.3** (digests in `override.yml`); data backup of 2.0.2 in `~/assembly-data/backups/`.
- Services added: `image-adapter` (172.17.0.1:23360, Seedream minimum size); NewAPI channel 1 fallback chain
  (`assembly/ops/newapi_text_fallback.py`).

## Film 2 (remake test, at CP1)

- Source: sponsor's local copy of a wordless Netflix Brasil Short (copyright: test only, not for publishing as is);
  story told from 24 frames (`~/assembly-data/runs/video-sources/20261124-132736/story.txt`).
- Project `01M863VMJQECF8PC9Z6FVNT6AV`, unit `assembly-film-2`, log `~/assembly-data/runs/film-2.log`; stopped at CP1.
- CP1 finding: the portrait shows a furry human child, not an animal (style `realistic`, ethnicity Vietnamese).
  Resume after the fix: `python -m assembly.connector --state ~/assembly-data/runs/01M863VMJQECF8PC9Z6FVNT6AV.json --approve CP1`.

## Next steps, in order

Sponsor priorities 2026-11-24 (film 1 produced, low quality but working):
1. DramaClaw Vietnamese UI (D25) and Vietnamese control.
2. Remake from an existing video; advertising / affiliate videos for TikTok and YouTube first.
3. Then the rest of the checklist.
