# Donors used alone vs the assembly — re-evaluated with film 1's evidence

Date: 2026-11-24. Sponsor question: re-assess using each donor on its own against the new app — strengths, weaknesses,
product quality, upgradability, resources. Supersedes the reasoning (not the conclusion) of
[2026-11-23 separate donors vs assembly](2026-11-23-r2-separate-donors-vs-assembly.md), which had no run evidence.
Labels: **FACT** (measured, cited), **INFER**, **UNKNOWN**.

## 1. Evidence from film 1 ("Chiếc đồng hồ của ông", narrated, project `01M84JWC`)

FACT (`docs/r2/evidence/R2_RUN_BLOCK_LEDGER.md` rows "assembly 01M84JWC", `~/assembly-data/runs/film-1.log`,
NewAPI logs):

| Measure | Value |
|---|---|
| Our code | `assembly/` 1 541 lines + 460 test lines; 31 commits on assembly/vendor paths since 2026-11-23 12:00; no donor source line changed |
| Run blocks | 15: **7 integration contracts** (C), **5 free-model limits** (G), 3 environment (E) |
| Integration blocks | project-name rule; spine set only by PATCH before ingest; Custom mode missed `CHARACTER_BUILD`; rewrite task name differs from the Hermes reference; sketch task scope; IndexTTS2 refused inside CE tasks (2.0.2 bug, fixed by upgrading to v2.1.3); beat video route defaulting to Seedance when no backend is named |
| Free-model blocks | ERNIE and its two OpenRouter fallbacks rate-limited together; Gemini ~20 requests/day/model vs ~36 vision calls per episode; ERNIE spending its whole budget on reasoning |
| Wasted resources | 14 beats rendered on Seedance's once-only pool (~1.06 M tokens) through the route default — connector bug, now closed; repeated vision calls on an exhausted Gemini model |
| Per-episode consumption (18 beats) | images ~26 Seedream (of 200 once-only); vision ~36+ Gemini; text ~80 calls; GPU: Wan ~3–4 min per 2–5 s clip |
| Language | DramaClaw writes zh/en only (`utils/source_language.py`); Vietnamese narration needed our translation step; Vietnamese voices needed our VieNeu adapter |
| Upgrade | 2.0.2 → 2.1.3 in about one hour: images re-pinned, Hermes toolset re-vendored (no tool removed), one new step handled (`voice_setup`); settings and the running project survived |
| Product | portraits good (1664×2218, no watermark); 18 Vietnamese beats with correct speakers; Vietnamese speech for all beats; film not yet composed — **final quality UNKNOWN** |

## 2. The options

- **A. Each donor alone**, operated by the sponsor in its own UI: huohuo (novel, its own film pipeline), DramaClaw (film),
  OpenMontage (explainers, repurposing).
- **B. The assembly**: donors run whole; the connector drives DramaClaw's own Hermes playbooks; our adapters supply
  Vietnamese voices, image sizes and local video; NewAPI is the shared model gateway.

## 3. Comparison

| Criterion | A. Donors alone | B. Assembly |
|---|---|---|
| Vietnamese film | **Not possible with DramaClaw alone** (zh/en prose and narration; IndexTTS2 voices for zh/en); huohuo alone writes Chinese and its film path has no Vietnamese voice either | works: translation of DramaClaw's own rewrite, VieNeu voices per character (FACT, film 1) |
| Automation | manual step by step in each UI; DramaClaw's `director-auto` needs a chat agent backend (Codex/Hermes) we do not run | automatic, with the playbooks' checkpoints (CP1 always, CP2–CP5 in step mode) |
| Operator load | several UIs, manual handoff story → film, copy/paste | one start command (console M2b later); donors' UIs for review |
| Product quality per stage | the donor's own | **the same donor code with the same models** → same per-stage quality (INFER); Vietnamese narration passes through one translation (zh rewrite → vi) |
| What limits quality | the models, not the structure (both use the same free tiers) | same |
| Failure surface | donor bugs only | donor bugs **plus** integration contracts (7 of 15 blocks); hidden defaults can spend resources (Seedance incident) |
| Upgradability | install the new release | re-pin, re-vendor the toolset, re-run probes and a short smoke film; one upgrade took ~1 h (FACT) |
| Our maintenance | none | 1.5 k lines + adapters + NewAPI scripts + 5 user services (voice, image, ComfyUI bridge, cleanup timer, film unit) |
| Resource use | same model pools; no connector retries | same pools; automatic retries consume quota on failures; guards added (explicit model on every costly call, zero internal prices, Seedance removed) |
| Cost to build | zero | ~1.5 days of agent work so far (vs. the old app: 91 releases in two weeks, 44 % on governance — resource-waste audit) |

## 4. Conclusion (INFER from §1–§3)

1. **For the stated product — Vietnamese, automatic, one operator — the assembly is the only option that works.**
   No donor alone produces a Vietnamese film: DramaClaw's prose and voices are zh/en, huohuo writes Chinese.
2. **Quality is set by the models, not by the choice A/B.** Both run the same donor code; with free tiers both are
   slow (≈ one short episode a day on Gemini's vision quota) and video is limited to local Wan 480p or a
   once-only Seedance pool. Raising quality means paid text/vision/video models (D20), in either option.
3. **The assembly's real cost is integration risk, not code size.** Half of film 1's blocks were contract
   mismatches, and one hidden default spent a scarce pool. Mitigations now in place or due:
   - every costly call names its model explicitly (no donor defaults);
   - zero internal prices and no paid channel without sponsor approval;
   - on each donor upgrade: re-vendor, run the donor tests, the M1 probes and a two-beat smoke film before real runs.
4. **Donors alone remain the right tool for single-purpose work**, unchanged from the 2026-11-23 note: Chinese/English
   films in DramaClaw's UI, novels in huohuo, explainers in OpenMontage. The assembly does not block that — the
   donors keep their own UIs.

## 5. Unknowns and how they close

- Final film quality and A/V sync: film 1's compose (running).
- huohuo's own film path on the same story: not measured; only needed if DramaClaw's film fails acceptance.
- Cost per episode on paid models: to estimate from film 1's call counts once the sponsor asks for D20 options.

## 6. Direction answer (GOAL rule 5)

**Go** with the assembly; no change of direction. Add to the plan: the upgrade smoke procedure (§4.3) and the
explicit-model rule; bring D20 (paid text/vision models) to the sponsor with film 1's numbers.
