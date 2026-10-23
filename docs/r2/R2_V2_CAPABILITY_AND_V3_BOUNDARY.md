# R2 V2 — capability, limits and the V3 boundary (2026-10-23)

Sources (decided, not re-opened):
- ADR-0089 (bounded V1 before portfolio automation; Gates A–D mandatory; no auto-approval; stop at controlled export; no second workflow engine or portfolio scheduler; "a dashboard or scheduler may not become shadow authority");
- `docs/research/2026-09-17-r2-v1-production-readiness-v2-deferment.md` §3 apply/adapt/defer table and §5 P2 order (M5C/M6 → M8 → M9 → M10 → M11 → M12, then the portfolio control plane);
- `R2_01_FROZEN_ARCHITECTURE.md` §2 North Star loop;
- V2 story release plan `docs/superpowers/plans/2026-10-18-r2-v2-story-release-amendment.md`.

Naming: ADR-0089 calls all deferred expansion "V2". The shipped line `r2-v2.0.x` is V1 plus the story-authoring part of that expansion (M5/M6). This document calls the rest of the deferred expansion **V3**.

## What V2 (r2-v2.0.x) does
| North Star stage | V2 capability | Human role (decided) |
|---|---|---|
| Discover / Research | Human-entered idea only (project + story brief = idea inbox) | The Human brings the idea |
| Create / Canon | Story authoring: 3-chapter Vietnamese story on a local model (about 4–5 h), findings, revise/discard, export `.md`, hand-off as project source; or upload a source | Gate A (brief) and story approval are Human |
| Adapt / Script | Episode planning (verbatim-tolerant anchors, local 9B), script plan/review/final script | Gate B Narrative Lock is Human |
| Direct / Prepare | Assets (characters/scenes/props/products), storyboard or reference-video units, M8 spatial formats | Review/regenerate per item |
| Produce | Image/video/TTS via configured providers (none configured on production yet), batch-video admission | Admission "needs confirmation" is Human |
| Evaluate | Operator checklists at gates and workflow blockers (no independent quality authority) | Gate C Final Cut is Human |
| Package / Distribute | Compose, export, Jianying draft | Gate D: the Human publishes manually outside ArcReel |
| Measure / Learn | M12-lite learning page: cohort comparison over recorded observations; recommendations are proposals and change nothing | Each recommendation decision is Human |
| Concurrency | Independent projects and host tasks run in parallel within worker capacity; no orchestrator | The Human starts each flow |
| Oversight UI | Per-project pipeline board (stage states from the server workflow plan, next action, decisions waiting, running story jobs), header North Star stepper, task HUD, notifications, opt-in story-done browser notification | Read and step in |
| Agent | Embedded creative agent; a local 9B model creates sessions but cannot drive the tools; a cloud preset is needed for real agent autonomy | Configure in Settings › Agent |

## Hard limits (decided; any change is a new Human decision)
1. No automatic approval of Gates A–D or of the story approval. Automation may prepare evidence or a proposed decision only. (The 2026-10-22 production trial approvals were performed by the agent on explicit Human instruction; they are recorded as a deviation from ADR-0089 §3 in `evidence/R2_V2_PROD_E2E_TRIAL.json`, and the Human should re-review that story.)
2. No automatic upload, scheduling or reconciliation on any platform.
3. No second workflow engine, portfolio scheduler, Canon/distribution/analytics truth store. Dashboards are read-only views over existing owners.
4. No automated trend or market research, no analytics acquisition.

## Can be done now and stays in sync with V2 (UI/glue only, no new authority)
- A cross-project operations view on the projects page: per project its North Star stage, pending decisions and running jobs, read from existing per-project endpoints (read-only, links into each owner surface).
- A decision inbox that lists every pending Human decision across projects (story briefs/manuscripts, Gates A–D from gate history, batch admission) and links to the owning surface; it never decides.
- Gate visibility on the pipeline board: Evaluate ← Gates B/C, Package ← export state and Gate D.
- Truthful provider readiness: show "no video/image provider configured" on the Produce stage instead of a silent 422.
- Copy that states the automation boundary ("runs automatically up to the next Human gate").
- Small backend in owned seams: per-chapter story progress, source_language at hand-off (done in v2.0.2).

## V3 (deferred expansion, one authority packet at a time, in the decided order)
1. M9 automated opportunity/trend research (Discover/Research) with factual authority and Gate A.
2. M10 independent quality authority (Evaluate beyond checklists).
3. M11 platform delivery: automatic upload/scheduling/reconciliation (Distribute) with credentials and receipts.
4. M12 full analytics acquisition and governed learning loop.
5. Portfolio-wide multi-pipeline control plane / autopilot scheduler: only after the owners above exist, referencing (not copying) their state.
6. Commercial-grade agent autonomy (cloud models qualified per ADR 0109), multi-tenant operation.
