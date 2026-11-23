# Assembling the donors' best stages: the options, including starting over

Date: 2026-11-23. The sponsor's model, in the sponsor's words: take **the whole story-writing part** of the donor
that writes best, **the whole film-making part** of the donor that makes films best, and so on; stand them side by
side; our job is only to **connect** them so they work as one; the result is a product as good as the donors can be.
"There must be a change, even if we have to start over. Research the options thoroughly." Labels: **FACT** (source),
**INFER**, **UNKNOWN**. Builds on the [off-course research](2026-11-23-r2-why-the-project-went-off-course.md),
[its review](2026-11-23-r2-review-of-the-off-course-research.md) and the donor studies of 11-08 … 11-16.

## 1. What each donor is, as a whole part (FACT unless marked)

| Donor @ pin | Whole parts it ships | Runs as | Languages | Models |
|---|---|---|---|---|
| **DramaClaw** `b299bfd` (`~/.cache/r2-donors/dramaclaw-full`) | novel import → episode planning → identities, scenes, props → sketch/render storyboards → video → voice → compose; verification; UI | `docker-compose.yml`: `api` (FastAPI + task backend), `newapi` (model gateway), `web` (React); REST API, e.g. `POST /projects/{p}/ingest/upload`, `/ingest/start`, `/pipeline/status` | UI `zh`, `en` only (`frontend/src/i18n/index.ts`: `SUPPORTED = ["zh","en"]`); asset language detection zh/en only (`utils/source_language.py`) | text through one OpenAI-compatible gateway (NewAPI) with per-feature model env vars (dozens in `.env.example`); images/video via the gateway and its providers; voice IndexTTS2/Fish |
| **huohuo-drama** `f104b85` (`~/content-os-r1-8/work/huohuo-drama`) | AI novel engine (premise → outline → brief → chapter, 21 genres, change-record memory) **and** novel → short drama (`runDramaEpisodePipeline`: rewrite, extract, voices, storyboards, images, dubbing, video or slideshow, compose, merge — no human gate in the body, 11-08 study); UI | Node workbench server + Nuxt workbench, SQLite/MySQL, Docker | UI i18n `en`, `zh-CN`, **`vi`**, `fil`; prompts and genre packs Chinese | text: OpenAI-compatible `baseUrl` per service (`services/ai/ai-config-service.ts:28-31`, default the vendor's proxy with gemini-3-pro, Seedream 5, Seedance 1.5 pro, MiniMax speech-2.8); image adapters gemini/openai/ali/minimax/volcengine; video ali/minimax/vidu/volcengine; TTS ali/minimax |
| **OpenMontage** `08e2151` | non-fiction and repurposing pipelines (explainer, documentary montage, talking head, clip factory, podcast, localization, screen demo, cinematic), Remotion composer | Python tools + Remotion, driven by an AI agent with skills; human approval gates by default (`pipeline_defs/*.yaml`) | English | per-tool providers |
| **ViMax** `63bb9c7` | idea → story → characters → portraits → script → video, end to end without a human step (`pipelines/idea2video_pipeline.py:295-340`) | Python | — | OpenAI-compatible (OpenRouter default), duck-typed image/video backends; no TTS |
| **shenbi** `10efa7c` | narrative skills (74) + checkpointed pipeline, human approval at checkpoints | Python + skills | Chinese | — |
| **ArcReel (ours)** | V1/V2 app in production: Vietnamese UI, story authoring, film pipeline, local routes (ComfyUI FLUX/Wan, VieNeu TTS), Gemini reviewers, Remotion, backups/restore | FastAPI + React, PostgreSQL | `vi`, `en`, `zh` | any route via our provider layer, local and cloud |

**No donor has ever been run here** (all donor studies read code only; 11-08 study header "no donor code was run").
Which donor makes the best story or film is therefore **UNKNOWN**; every ranking so far compares mechanisms, not
outputs.

## 2. Constraints any option must meet (FACT from memories/decisions, INFER where marked)

1. **Vietnamese** product. Only huohuo's UI and our app speak Vietnamese; donor prompts are Chinese (DramaClaw also
   English); DramaClaw names identities in Chinese for a Vietnamese story (run 010a7912).
2. **Models and money.** The sponsor's standing rule is free tiers (memory `cloud-free-quota-registry`); the donors'
   quality is built on paid video/image/TTS (Seedance, Seedream, MiniMax, Gemini Pro). INFER: with free or local
   models the quality ceiling is lower under *every* option; the architecture choice does not change that.
3. **One operator.** Three separate apps with three UIs, logins and settings is operator load; the shell matters.
4. **Keep what works** unless deliberately dropped: production deploy and backups, power-loss recovery, Vietnamese
   story authoring, local routes, reviewers.

## 3. The options

### A. Continue: R2 core, port donor units into it (status quo)
Fidelity to the sponsor's model: **low** — units, not whole parts; our stages feed them (run 010a7912 showed the
mismatch). Keeps everything. Cost: the 2.5-month pattern continues. Not recommended.

### B. One donor platform as the base, others plugged into it
Example: DramaClaw as the drama product; huohuo's novel engine (or ours) produces the story text that DramaClaw
imports; OpenMontage for non-fiction. Fidelity: **high for film**. Needs: Vietnamese in DramaClaw's UI and asset
language (a seam inside the donor), providers we can use through NewAPI, operator learns DramaClaw's UI. Our app's
role shrinks to the story part and non-fiction, or ends.

### C. Stage assembly: each stage's winner runs whole as its own service; a thin connector app (the sponsor's model)
Story stage = winner A runs untouched (its API or CLI); film stage = winner B runs untouched; non-fiction = OpenMontage.
Our code = **connectors** (hand-off of plain files: story text → film import; film → package), a **shell** (one
Vietnamese UI to start a run, watch it, see results, set models) and a **provider bridge** (each donor pointed at our
model routes: OpenAI-compatible endpoints for text; for media, a small adapter where a donor cannot reach our routes).
Fidelity: **highest**; donors can be updated by moving the pin. Hand-offs are simple: story → film is a text file
(DramaClaw `ingest/upload`; huohuo imports chapters). Risks: running several stacks (Docker), language seams in each
donor, provider adapters for local models.

### D. Start over in a new repository built as C
A new small repo: donors as pinned submodules/containers, connectors and shell only; ArcReel stays in production until
the new one replaces it. Same as C, minus R2's weight; loses nothing that is not deliberately ported. Extra cost: a new
shell (or the ArcReel React UI carried over). Clean ownership and no frozen documents.

### E. Strangler: keep ArcReel as the shell, replace its insides stage by stage with donor services
ArcReel's UI, accounts, settings, run panel and deploy stay; each stage's internals are switched to a donor service
behind the same screen, one at a time; R2 governance is switched off stage by stage. Fidelity: high once done; keeps the
working shell and Vietnamese UI; risk that R2's coupling slows each switch (the same coupling that made ports costly).

## 4. Comparison (INFER; to be confirmed by the bake-off in §5)

| | A | B | C | D | E |
|---|---|---|---|---|---|
| Matches "take whole parts, only connect" | ✗ | ◐ (one base) | ✓ | ✓ | ✓ eventually |
| Quality ceiling | ours | donor's | best per stage | best per stage | best per stage |
| Code we own | very large | small | small (connectors, shell, bridge) | smallest | large until stripped |
| Time to a first assembled film | — | short | short-medium | medium | medium-long |
| Donor updates | hard | easy for base | easy | easy | easy per stage |
| Vietnamese | yes | needs seam | needs seams in donors, shell is ours | same as C | yes (shell) |
| Operator load | one app | donor's UI | one shell | one shell | one app |
| Keeps production/backups | yes | no | partly | no (until switch) | yes |

## 5. How to choose with evidence (the step missing for 2.5 months)

1. **Bake-off, time-boxed** (proposal: 2–3 working days, a fixed model budget the sponsor sets). Same reference story
   ("Chiếc đồng hồ của ông", Vietnamese), same models where the donor can take them:
   - film stage: DramaClaw, huohuo-drama, ViMax, our app — one episode each;
   - story stage: huohuo's novel engine, shenbi's pipeline (if it runs), our story authoring — one short story each
     from the same premise.
   Measure: runs at all, wall time, cost, Vietnamese quality, identity consistency, both reviewers' verdicts, the
   sponsor's eye. Each donor is run **as shipped**, with only provider settings changed.
2. **Pick the winner per stage** from those results. A donor that cannot run here or cannot speak Vietnamese loses
   that stage, recorded with the reason.
3. **Choose B, C, D or E** from the winners: if one donor wins every stage → B; if winners differ → C or D (D if
   ArcReel's weight would slow C); if keeping the running app matters most → E.
4. **Budget decision** (sponsor): free/local only, or a paid budget per film — the bake-off shows the quality gap.

## 6. Unknowns
- Whether DramaClaw and huohuo run here with our model routes (NewAPI channels for Gemini/OpenRouter; local ComfyUI
  and VieNeu need adapters). Whether shenbi's pipeline runs unattended. Real output quality of each donor in Vietnamese.
- Effort of the Vietnamese seam in each donor (prompts are Chinese; output language may follow an instruction).
