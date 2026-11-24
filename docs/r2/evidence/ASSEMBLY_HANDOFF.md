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

## Film 2 (remake test, produced 2026-11-24 15:45, awaiting the sponsor's viewing)

- Source: sponsor's local copy of a wordless Netflix Brasil Short (copyright: test only, not for publishing as is);
  story told from 24 frames (`~/assembly-data/runs/video-sources/20261124-132736/story.txt`).
- Project `01M863VMJQECF8PC9Z6FVNT6AV`; film `/mnt/arcreel/D/ArcReel/assembly/films/01M863VMJQECF8PC9Z6FVNT6AV-ep01.mp4`
  (51.5 s, 720×1280, audio mean −20 dB). Finished films now go to drive D (`ASSEMBLY_FILMS_DIR`).
- CP1: sponsor chose "realistic animal"; character re-described as a real red squirrel without clothes (DramaClaw's
  portrait template still adds a black T-shirt edge). Lesson: animal characters need "animal, no clothes" in the
  description before portraits (part of the deferred CP1 prompt review).
- Blocks fixed on the way (ledger rows 2026-11-24): first frames in batches of 9; waits cover every fanned-out task;
  full queue is transient; gateway disk guard (disk cleaned, `DISK_AUDIT_2026-11-24.md`).
- Visible defects: style drifts between beats (white sketch-like backgrounds, one magenta glove, a nut-shell hat),
  a few dark/near-empty frames; squirrel identity holds across beats.

## Ad probe 1 (fictional product LUMA 500 ml, OpenMontage + Codex), paused for OpenRouter's daily quota

- Inputs `~/assembly-data/inbox/san-pham-thu/` (4 FLUX.2 klein stills, `san-pham.md`, `brief.txt`, `approve-1.txt`);
  project `~/assembly-data/openmontage/projects/luma-500-tiktok/` (proposal, script, scene plan, voice, music, word
  subtitles done; only a 4 s landscape test render). Codex session `01a20ce9-4e0a-7b10-9a3e-0b65277f3fcb`.
- Sponsor: decide ad checkpoints myself for the best real quality (memory `decide-ad-checkpoints-myself`).
- Resume is scheduled by the user timer `assembly-ad-1` at 2026-11-25 07:10 (after the OpenRouter daily reset).
- Research: `docs/research/2026-11-24-r2-affiliate-ad-video-donors.md`; film 2 review deferred:
  `docs/research/2026-11-24-r2-film-2-quality-review.md`.

## Next steps, in order

Sponsor priorities 2026-11-24 (film 1 produced, low quality but working):
1. DramaClaw Vietnamese UI (D25) and Vietnamese control.
2. Remake from an existing video; advertising / affiliate videos for TikTok and YouTube first.
3. Then the rest of the checklist.
