# Run each donor on its own per use, or assemble them? Pros and cons

Date: 2026-11-23. The sponsor asked, after the plan: should each donor simply be run on its own for its own purpose,
and how does that compare with the assembly (ADR-0170, [plan](../r2/ASSEMBLY_PLAN.md))? Labels: **FACT** (source),
**INFER**. Evidence from the donor studies of 11-08 and 11-15 and today's reading of the checkouts.

## 1. What "on its own" means per use

| Use | Donor alone | How it runs alone (FACT) |
|---|---|---|
| Write a novel | huohuo | its UI (has `vi`), API `generate-premise` … `generate-remaining`; writes Chinese |
| Novel/idea → drama film | huohuo alone, or DramaClaw alone | huohuo: `runDramaEpisodePipeline` one call per episode, no human gate (`services/drama/drama-episode-pipeline.ts:312-671`); DramaClaw: 16 staged steps, driven by hand in its UI or by its own chat agent (Hermes) over the same toolset (`.hermes/plugins/dramaclaw`), UI `zh`/`en` |
| Existing story file → film | DramaClaw alone | ingest + the same 16 steps |
| Explainer, documentary, repurposing | OpenMontage alone | an AI coding agent runs its skills; human approval gates on by default (`pipeline_defs/*.yaml`) |
| Idea → short video | ViMax alone | `Idea2VideoPipeline` end to end, no TTS |

## 2. Comparison

| Criterion | Each donor alone | Assembly (huohuo → translate → DramaClaw → post-stages) |
|---|---|---|
| Fidelity to the donor | highest — used exactly as designed | same for each stage (each runs whole); only the hand-off between them is ours |
| Best part at every stage (GOAL) | **no** — a single donor's weakest stage caps the result: huohuo's film stage is weaker than DramaClaw's (DramaClaw "strongest/most complete/richest" in assets, episodes, storyboards, 11-08 study §3–§6); DramaClaw has no long-form novel engine | **yes** — huohuo's story, DramaClaw's film |
| Fully automatic, idea → film | huohuo alone: yes (one call per episode); DramaClaw alone: only through its chat agent (an LLM agent deciding each step; free models are weak at long tool chains — memory `ollama-local-model-gotchas`, the 9B agent limit); OpenMontage: gates on by default | yes — deterministic driver over DramaClaw's own toolset, retries, resume |
| Vietnamese | huohuo: UI `vi`, writes Chinese, TTS MiniMax/Ali (Vietnamese UNKNOWN); DramaClaw: UI `zh`/`en`, needs the same voice configuration | translation + VieNeu voices configured once |
| Our code | none (configuration only) | small: connector ≤ ~1 000 lines over M1–M2, adapters, post-stages |
| Time to a first film | shortest for huohuo-alone (install, configure models, press run) | M0–M2 ≈ 4 days |
| Data carried between stages | inside one donor: its own characters and memory flow into its film | story text only; DramaClaw re-extracts characters from the text (INFER: huohuo's cast/memory is not carried over) |
| Operator load | several apps, UIs, logins, model settings, backups; a person moves files between them for cross-donor work | one run command / page; donors' UIs still available for detailed work |
| Model configuration | per donor (huohuo AI config rows, DramaClaw NewAPI, OpenMontage per tool) | one NewAPI gateway for huohuo and DramaClaw (D12) |
| Upstream updates | move one pin | move one pin per donor; re-check the connector's step table against the donor's toolset |
| Failure isolation | a donor's fault stays in that donor | the connector stops at the failing stage and resumes |

## 3. Conclusion (INFER from §2)

The two are not alternatives: **the assembly already contains "each donor alone"**, because every donor runs whole
with its own UI. So:
- **Single-purpose uses run on the donor alone**, with no connector: write a novel → huohuo; manual drama work → the
  DramaClaw UI; explainers and repurposing → OpenMontage (until its assembly step in M5).
- **The end-to-end automatic product uses the assembly**, because no single donor has the best part of every stage
  and only the connector makes the cross-donor path automatic (GOAL: best parts, automatic, one operator).
- **huohuo's own film pipeline is the ready fallback** for idea → film if DramaClaw fails M2's acceptance: it runs
  whole and one-call per episode; switching costs configuration only. This is a fallback, not a bake-off.

Plan impact: none to the direction; add to the [plan](../r2/ASSEMBLY_PLAN.md) §6 the fallback "DramaClaw fails M2
acceptance → huohuo's own `runDramaEpisodePipeline` on the same story, Vietnamese voice via the same adapter
configuration where huohuo's TTS allows it", and document each donor's UI in the operator README (`assembly/README.md`).
