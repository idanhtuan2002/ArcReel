# Final review: the new app against every expectation the sponsor stated

Date: 2026-11-23. A synthesis, not new research: each expectation the sponsor stated (GOAL, memories, messages) is
checked against the assembly as planned ([GOAL](../GOAL.md), [plan](../r2/ASSEMBLY_PLAN.md) incl. §0 corrections),
using the evidence of the three independent rounds and the probes on the running DramaClaw. Status: **met** (by design,
to be proven by the first film), **open** (work or a decision left), **limit** (cannot be met under current constraints;
the sponsor should know). Labels FACT / INFER as in the cited notes.

## 1. Expectation by expectation

| # | Expectation (sponsor's words / source) | How the new app meets it | Status |
|---|---|---|---|
| E1 | Assemble the donors' best parts whole; only connect (09-07, 11-23, GOAL) | huohuo writes, DramaClaw films, both run whole from their own containers; our code is connector, configuration, small adapters, post-stages (ADR-0170) | **met** by design |
| E2 | Quality and function ≥ the original (09-09) | Each stage runs the donor itself, so the stage is the donor's quality **with the same models**. The donors are tuned for paid models (Seedance, Seedream, gpt-image-2, MiniMax/IndexTTS2); we run free tiers and local Wan (D27) | **limit**: equal pipeline, lower models → below what the donors show; closes only with a budget (D20, after the first film) |
| E3 | Don't rebuild what exists (09-07) | No donor unit rewritten; Hermes toolset used as reference (PORTING "Why not ported"); old app units only where no donor has them | **met** |
| E4 | Fully automatic (11-01, 11-23) | Connector drives DramaClaw's steps from its own status, retries, resumes; class rule for "nothing to do" steps | **open**: proven only by M2; the free video route (local Wan) is slow and untested in DramaClaw's ComfyUI channel |
| E5 | See and control every step (11-23, D21) | Thin Vietnamese console: step timeline with Continue / Pause / Redo; deep links into donors' screens for per-step outputs | **open** (M2b) |
| E6 | One operator (09-07) | One console; donors' UIs for detail; three stacks (huohuo, DramaClaw, VieNeu) on one host | **open**: operator load and machine limits (disk 16 GB free, one 8 GB GPU shared by VieNeu, Wan, reviewers) — round C R-register |
| E7 | Vietnamese first, then English, then Chinese (11-15) | Story translated zh→vi; voices VieNeu; console and huohuo UI in Vietnamese; DramaClaw UI Vietnamese (approved donor change) | **met with limits**: DramaClaw writes descriptions and prompts in Chinese for Vietnamese text (`source_language.py`); spoken lines and subtitles stay Vietnamese (to be checked in M2); English/Chinese outputs later |
| E8 | A commercial-quality story, publishable alone (memory `story-is-standalone-commercial-product`) | huohuo's engine (the only full long-form engine) + translation | **limit/open**: huohuo writes Chinese web-novel idiom; `setting = vn` (D16) asks for a Vietnamese setting, quality unknown; translation quality from a free model unknown; first story will show |
| E9 | Every genre and form, TikTok/YouTube first (11-15) | huohuo 18 genres; DramaClaw narrated (prose) now, dialogue drama later via formatter + headers; OpenMontage forms need a driver (agent + gates); StoryBox not covered | **open**: coverage is staged (M5); dialogue drama is not in the first films (prose → `narrated`) |
| E10 | Drama with character voices | `narrated` spine for prose: Vietnamese prose has no "Name:" lines, so dialogue is read by the narrator or attributed loosely (round B) | **limit** for the first films; dialogue drama needs the `drama` spine route (formatter → translation → header rewrite) |
| E11 | Characters consistent across shots | DramaClaw identity planner, portraits, identity images for every identity, sketch → render grids, verification | **met** by design (stronger than the old app); proven by M2 |
| E12 | Episode length follows the story (D23); vertical 9:16 (D17) | One episode per chapter (`structured_v1`); huohuo chapters ~3 000 characters → long episodes; `narrated` defaults 16:9, set to 720×1280 explicitly | **open**: long episodes vs TikTok habits — the sponsor chose "per story"; watch on the first film |
| E13 | Many series in parallel (D19) | Run queue in M6; DramaClaw CE runs tasks in one process | **limit**: free pools (Seedream 200 images, Gemini vision 20/day/model, Seedance once) and one GPU cannot sustain parallel series; needs money or patience |
| E14 | Models easy to switch (11-16) | One NewAPI gateway for huohuo and DramaClaw; mapping by profile JSON | **met** |
| E15 | Free tiers; budget after the first film (D20) | Free/local everywhere; quotas stretched (vision spread, Seedream 4.0 second pool) | **met** as a constraint; it is the cause of E2/E13 limits |
| E16 | Interface clear, every function visible, Vietnamese (11-23) | Console catalog + deep links; DramaClaw Vietnamese UI | **open** (M2b, D25) |
| E17 | Media relay safe (11-23) | Cloudinary with daily cleanup, inline relay option (D28) | **open**: needs the account and the probes |
| E18 | Never lose work to quota limits (11-23) | Rule "防额度中断丢失", Stop hook, handoff file, agents write as they go | **met** |
| E19 | Stay on direction; research first; no waste (11-23) | GOAL above all docs; hooks (codebase-memory, Donor:/Consumers:, reminder); run ledger; no research notes until a film | **met as mechanism**; the warning from round C stands: 30 of 45 commits on 11-23 were docs — the next commits must be code |
| E20 | Data and operations: backups, restarts | M6: backups of three stacks (keys excluded), autostart, alerts | **open** |
| E21 | Security on a single machine | Loopback ports; DramaClaw CE trusts every request (no CORS/Host checks) — a browser on this machine visiting a hostile page could reach it (round C) | **open**: pin images by digest; keep the catalog auto-update off; consider a Host-checking proxy in M6 |

## 2. What this means (INFER)

- The **direction is right and complete**: every expectation has a place in the plan, and nothing in it rebuilds a donor.
- **Three limits are real and should not surprise anyone after the first film**: (1) quality will be below the donors'
  showcase until paid models are used (E2); (2) the first films are narrated, not voiced dialogue drama (E10); (3)
  parallel series are not possible on free pools (E13).
- **The rest is open work**, all already in the plan's order: M1a (voices, local Wan channel) → keys and probes (M1.0,
  D28) → M2 (first film) → M2b (console) → M4 (finish, report-only review) → M3 (story stage) → D25 (Vietnamese
  DramaClaw UI) → M6 → M5.

## 3. Recommendation (GOAL rule 5)

**Go** with M1a now. No further research or document before the first film, except the acceptance record of each step.
