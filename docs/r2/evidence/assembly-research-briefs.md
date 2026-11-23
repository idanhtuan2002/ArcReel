# Briefs of the three independent research rounds (2026-11-23)

Run each as a separate read-only agent (no file edits, no docker, no network), Opus, in parallel. Each reads the
documents and donor code itself and does not see the others' answers. Record each answer in
`docs/research/2026-11-23-r2-independent-round-{a,b,c}.md`, then reconcile.

Common context for all three: repo worktree `/home/anhtuan/content-production-os/.worktrees/r2-film-quality`;
read `docs/GOAL.md`, `docs/adr/0170-assemble-the-donors-best-stages-whole.md`, `docs/r2/ASSEMBLY_PLAN.md`,
`docs/r2/evidence/ASSEMBLY_ACCEPTANCE.md`, `docs/research/2026-11-23-r2-assembly-verification-round.md`. Donors pinned:
DramaClaw `/home/anhtuan/.cache/r2-donors/dramaclaw-full` (b299bfd; `src/novelvideo`, `.hermes/plugins/dramaclaw`,
`docs/en`), huohuo-drama `/home/anhtuan/content-os-r1-8/work/huohuo-drama` (f104b85), OpenMontage
`/home/anhtuan/content-os-r1-8/work/OpenMontage` (08e2151). DramaClaw is running locally — do not touch it. Label every
claim FACT (file:line) or INFER; be critical.

## A — What needs to be done

Also read the coverage matrix and old-app-vs-assembly notes (2026-11-23). Build a work breakdown from GOAL (not from the
plan), compare with ASSEMBLY_PLAN; list missing tasks, wrong order, hidden dependencies, unrealistic estimates, and
anything contradicting GOAL rules; verify plan claims against donor code (DramaClaw `api/routes/pipeline.py` step order
and toolset handlers; huohuo `workbench-server/src/routes/novel/novel.ts`, `services/drama/drama-catalog-service.ts`;
DramaClaw `generators/indextts2_fal.py`, `storage/media_relay.py`). Then answer: should the interface reuse the OLD
app's UI (this repo's `frontend/`, Vietnamese React SPA; run panel bound to R2 production-run APIs) or be a NEW small
control page (plan M2b), also considering the donors' own UIs (DramaClaw canvas, zh/en; huohuo `vi`)? Weigh coupling,
effort, operator experience, risk of dragging R2 back, GOAL rule 2. Return a gap table (severity, evidence, fix), a UI
recommendation, and a corrected task order.

## B — What it will produce

Also read `docs/r2/cloud-free-quota-registry.md`, `docs/research/2026-11-08-r2-donor-stage-mechanisms.md`,
`docs/r2/evidence/R2_CRAFT_QUALITY_PROGRAM.md` (end: drama smoke run b961dc0a). Walk one story through every step
(premise → huohuo chapters → translation → DramaClaw ingest spine "drama" → characters → episodes → portraits →
identities → script → sketches → render → first frames → TTS → video → compose) and state, from donor code/prompts,
what each output will be like with these models (ERNIE free text, Gemini/OpenRouter vision, Seedream 4.5 200 images,
Seedance once-only pool, VieNeu presets via the fal adapter): languages, names, zh/en-only detection
(`utils/source_language.py`), voices, identity consistency, durations, 720x1280, subtitles, no music, loudness. Count model
calls per episode vs quotas; compare with GOAL's quality bar and the old app's films. Return a step table, quota
arithmetic, expected shortfalls and fixes.

## C — What could make it fail

Also read the off-course research, its review, the waste audit and the operating-model note (2026-11-23). Pre-mortem:
assume the assembly failed three months from now; write the likely failure stories, then a risk register (likelihood,
impact, earliest warning, prevention, decided response) covering donor runtime and maintenance, language, voices vs
DramaClaw's reference-audio contract, the media relay, quotas and silent model changes, disk/GPU, backups across three
stacks, security (CE trusts every request), coupling to DramaClaw's internal agent toolset, operator load, and recurrence
of the first 2.5 months' process failures. Point out what in GOAL/ADR-0170/ASSEMBLY_PLAN is itself a risk or missing.
