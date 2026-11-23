# Critical review of GOAL, the assembly plan and today's coverage notes

Date: 2026-11-23. The sponsor asked to review critically what was just written ([GOAL](../GOAL.md),
[assembly plan](../r2/ASSEMBLY_PLAN.md), [coverage matrix](2026-11-23-r2-assembly-coverage-matrix.md),
[separate vs assembly](2026-11-23-r2-separate-donors-vs-assembly.md)) and to answer: does the new version include
everything the donors can do, and are the functions clearly shown in the user interface? Labels: **FACT**, **INFER**.

## 1. Checks run for this review (FACT)

- Registry: `claymorelab/dramaclaw:2.0.2`, `dramaclaw-frontend:2.0.2`, `dramaclaw-gateway:v1.0.0-rc.24-dramaclaw.1`
  exist (`docker manifest inspect`); **`huohuo/huohuo-drama:latest` does not** — huohuo must be built from its checkout.
- DramaClaw `project_config.py`: `narration_style` ∈ {`first_person`, `third_person`}, default `third_person`;
  `ethnicity` default `"Chinese"` (free text into prompts).
- DramaClaw voice samples: 1.8–15.2 s each, "should be 3–5 s" (`seedance2_i2v/pipeline.py:110-120`).
- OpenMontage is driven by an AI coding agent (`AGENT_GUIDE.md`); human gates are enforced in code — "a gated stage
  cannot be written `completed` without `human_approved=True`" (`AGENT_GUIDE.md:589`, `lib/checkpoint.py`).

## 2. Defects found, and the fix applied to the plan

| # | Defect | Fix (applied in the plan now) |
|---|---|---|
| R1 | **No user interface in the plan.** Automation is a CLI; functions are spread over DramaClaw's UI (`zh`/`en`), huohuo's UI (`vi`) and OpenMontage (no UI). Nothing lists what the product can do | New milestone **M2b — Vietnamese control page** right after M2 (see §4) |
| R2 | **Translation would fail on names.** M3.3 passed Chinese character names as protected terms, but `translate_text` keeps terms verbatim *and* rejects CJK in Vietnamese output — a contradiction on every name | M3.3: first translate the cast names to Hán-Việt once (glossary), replace them in the Chinese text, then translate with the Vietnamese names as protected terms |
| R3 | D14 left `narration_style` to "read at implementation time" | D14 fixed: `narration_style = third_person`, `ethnicity = "Vietnamese"` |
| R4 | Voice mapping by SHA-256 assumes the media relay serves the uploaded bytes unchanged | M1: the sample is a 4 s WAV; acceptance includes the round trip; fallback key = the sample's file name if the relay re-encodes |
| R5 | huohuo image does not exist on the registry | M3.1: build from the pinned checkout (`deploy/docker-compose.yml` has the build context) |
| R6 | BytePlus through NewAPI's VolcEngine channel (Base URL override) is assumed, not verified | M1 starts with a one-call probe per media model; fallback for video = DramaClaw's own **ComfyUI channel** with our local Wan workflow (supported by the donor, free) |
| R7 | **OpenMontage was marked "whole and automatic"**; it is agent-driven with enforced human gates | Coverage and plan corrected: OpenMontage needs an agent driver and gate approval; M5's OpenMontage item becomes "research the driver (Claude Code headless vs our connector approving gates) before planning" |
| R8 | **Not all donors are included.** The plan runs huohuo, DramaClaw, (later) OpenMontage; ViMax, take, shenbi, Jellyfish, AIVPE, StoryBox, novel-studio-ai, ai-short-film, Butterfly are not run | Explicit per-donor decision (§3) |
| R9 | Operations from the old app (backups of donor volumes, autostart, alerts, autopilot, local fallbacks) were in the carry-over note but **missing from the plan's milestones** | New milestone **M6 — Operations** |
| R10 | **A product question was decided silently**: huohuo writes Chinese stories (Chinese settings, names, webnovel idiom); translated, they are Chinese stories in Vietnamese | Raised to the sponsor (GOAL rule 6): Chinese-setting stories translated, or a Vietnamese setting asked for in the premise (quality of huohuo on a Vietnamese setting unknown) |
| R11 | Free pools: BytePlus image (200) and video quotas are once-only; sustained production will exhaust them | Stated in the plan's fallbacks: local ComfyUI for video and images when pools end; a spend decision is a GOAL tolerance |
| R12 | Two donors offer the same function (huohuo and DramaClaw both make films; canvases in both) — confusing for one operator | The control page shows **one path per function** (catalog in §4) and keeps the other only as a named fallback |

## 3. Does the new version include everything the donors do?

**Not yet, and not all of it should be.** Per donor:

| Donor | In the new version | Reason |
|---|---|---|
| huohuo-drama | ✅ run whole (story; its film pipeline as fallback) | ADR-0170 |
| DramaClaw | ✅ run whole (film) | ADR-0170 |
| OpenMontage | ⏳ needs an agent driver and gate approval (R7) | research in M5 |
| shenbi | ◐ its genre/fanfic skills only (M5) | its novel engine overlaps huohuo's, which was chosen; checkpoints need human approval |
| ViMax | ◐ its children's adaptation prompt only (M5) | idea → video is covered by huohuo → DramaClaw at higher quality (stage ranking) |
| take | ✗ | shot grammar is inside DramaClaw's script and keyframe builders |
| Jellyfish | ✗ | shot readiness is inside DramaClaw's verification |
| AIVPE | ◐ its judge guards, in our review post-stage (M4) | — |
| StoryBox (simulation lab) | ✗ **not covered** | story ideas from character simulation; no other donor has it — listed for after M5 |
| novel-studio-ai | ✗ | narrative workbench overlaps huohuo |
| ai-short-film, Butterfly | ✗ | visual identity anchors and prompt history are inside DramaClaw |

So the new version covers every **function** of the donors except StoryBox's simulation and OpenMontage until its
driver exists, and the gaps no one covers (publishing upload, analytics, learning).

## 4. Are the functions shown clearly in the interface? — No; M2b fixes it

FACT today: three interfaces in two languages plus a CLI; no single list of functions. The fix, kept inside GOAL rule 2
(our code = connector + small surfaces):

**M2b — Vietnamese control page** (`assembly/web/`, FastAPI + server-rendered HTML, ≤ 500 lines, 1 day):
- **Catalog**: every function of the product in Vietnamese, grouped as Story / Film / Non-fiction / Operations, each
  with its status (available, fallback, coming in Mx, not covered) and where it runs — a button that starts it
  (automatic runs) or a deep link into the donor's own screen (huohuo `:18088`, DramaClaw `:8080`) for manual work.
  The catalog's source is the coverage matrix, so the page and the research cannot drift apart.
- **Runs**: start (story file, or premise + genre + chapters), stage-by-stage progress from the run state, errors with
  the stage and the donor's message, resume.
- **Results**: play the episode film, the story text (Chinese and Vietnamese), the reviewers' verdicts (after M4).
- **Settings shortcuts**: links to DramaClaw's Models & Channels and Media Storage, huohuo's AI config, the model map
  document.
Acceptance: the sponsor finds every function from the catalog without reading documents, starts the M2 film from the
page and watches it there.

## 5. What did not change

The direction (GOAL, ADR-0170) holds; the review found gaps in the plan, not reasons to assemble differently.
